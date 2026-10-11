"""Caller-Session adapter; mapping registration and migration/RLS remain with mainline.

No create_all, connection, commit or rollback. Head rows must be tenant-provisioned by
mainline, so initial revision 0 has a real row to lock for concurrent first saves.
"""

from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from pdos_next.model_configuration.ports import SecretBinding
from pdos_next.model_configuration.service import ConfigurationVersion, fail
from pdos_next.models import Base, Row
from pdos_next.schemas.model_configuration import ModelMetadata


class ModelConfigurationHead(Base):
    __tablename__ = "model_configuration_heads"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (CheckConstraint("revision >= 0"),)


class ModelConfigurationVersion(Row, Base):
    __tablename__ = "model_configuration_versions"
    revision: Mapped[int] = mapped_column(Integer)
    public_metadata: Mapped[dict] = mapped_column(JSONB)
    enabled: Mapped[bool] = mapped_column(Boolean)
    created_by: Mapped[UUID]
    secret_reference: Mapped[UUID | None]
    secret_version: Mapped[UUID | None]
    secret_available: Mapped[bool | None]
    binding_digest: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "revision"),
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(["tenant_id"], ["model_configuration_heads.tenant_id"]),
        ForeignKeyConstraint(
            ["tenant_id", "created_by"], ["principals.tenant_id", "principals.id"]
        ),
        CheckConstraint("revision > 0"),
        CheckConstraint(
            "(secret_reference IS NULL AND secret_version IS NULL "
            "AND secret_available IS NULL) OR (secret_reference IS NOT NULL "
            "AND secret_version IS NOT NULL AND secret_available IS NOT NULL)"
        ),
    )

    @property
    def status(self):
        return "enabled" if self.enabled else "disabled"


def decode(row: ModelConfigurationVersion) -> ConfigurationVersion:
    try:
        metadata = ModelMetadata.model_validate(row.public_metadata)
    except (ValidationError, TypeError, ValueError):
        fail("MODEL_CONFIGURATION_STORAGE_INVALID")
    version = ConfigurationVersion(
        tenant_id=row.tenant_id,
        id=row.id,
        revision=row.revision,
        metadata=metadata,
        enabled=row.enabled,
        created_by=row.created_by,
        created_at=row.created_at,
        secret=SecretBinding(
            row.tenant_id,
            row.secret_reference,
            row.secret_version,
            metadata.protocol,
            row.secret_available,
        )
        if row.secret_reference is not None
        else None,
    )
    if version.binding_digest != row.binding_digest:
        fail("MODEL_CONFIGURATION_STORAGE_INVALID")
    return version


class SessionConfigurationStore:
    def __init__(self, session: Session):
        self.session = session

    def current(self, tenant_id: UUID) -> ConfigurationVersion | None:
        head = self.session.scalar(
            select(ModelConfigurationHead)
            .where(ModelConfigurationHead.tenant_id == tenant_id)
            .execution_options(populate_existing=True)
        )
        if head is None:
            fail("MODEL_CONFIGURATION_STORAGE_NOT_PROVISIONED")
        if head.revision == 0:
            return None
        row = self.session.scalar(
            select(ModelConfigurationVersion)
            .where(
                ModelConfigurationVersion.tenant_id == tenant_id,
                ModelConfigurationVersion.revision == head.revision,
            )
            .execution_options(populate_existing=True)
        )
        if row is None:
            fail("MODEL_CONFIGURATION_STORAGE_INVALID")
        return decode(row)

    def append(self, version: ConfigurationVersion, *, expected_revision: int) -> None:
        head = self.session.scalar(
            select(ModelConfigurationHead)
            .where(ModelConfigurationHead.tenant_id == version.tenant_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if head is None:
            fail("MODEL_CONFIGURATION_STORAGE_NOT_PROVISIONED")
        if head.revision != expected_revision or version.revision != expected_revision + 1:
            fail("MODEL_CONFIGURATION_STALE")
        secret = version.secret
        self.session.add(
            ModelConfigurationVersion(
                id=version.id,
                tenant_id=version.tenant_id,
                revision=version.revision,
                public_metadata=version.metadata.model_dump(mode="json"),
                enabled=version.enabled,
                created_by=version.created_by,
                created_at=version.created_at,
                secret_reference=secret.reference if secret else None,
                secret_version=secret.version if secret else None,
                secret_available=secret.available if secret else None,
                binding_digest=version.binding_digest,
            )
        )
        head.revision = version.revision
        self.session.flush()  # Common receipt/audit/outbox writes must share this transaction.
