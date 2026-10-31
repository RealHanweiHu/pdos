"""P31 account metadata and external-delivery facts; never a second business store."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row


def link(field, table, target="id"):
    return ForeignKeyConstraint(["tenant_id", field], [f"{table}.tenant_id", f"{table}.{target}"])


class Application(Row, Base):
    __tablename__ = "dingtalk_applications"
    administrator_id: Mapped[UUID]
    service_principal_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    corp_id: Mapped[str] = mapped_column(String(160), unique=True)
    client_id: Mapped[str] = mapped_column(String(160))
    robot_code: Mapped[str] = mapped_column(String(160))
    secret_arn: Mapped[str] = mapped_column(Text)
    secret_version: Mapped[str] = mapped_column(String(160))
    active: Mapped[bool] = mapped_column(Boolean)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id"),
        link("administrator_id", "principals"),
        link("service_principal_id", "principals"),
        CheckConstraint("revision>0 AND length(corp_id)>0 AND length(secret_version)>0"),
    )


class Binding(Row, Base):
    __tablename__ = "dingtalk_account_bindings"
    application_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    external_user_id: Mapped[str] = mapped_column(String(200))
    verified_nonce_id: Mapped[UUID]
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    epoch: Mapped[int] = mapped_column(Integer, default=1)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[UUID | None]
    revoke_key: Mapped[UUID | None]
    revoke_reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        link("application_id", "dingtalk_applications"),
        link("owner_id", "principals"),
        link("revoked_by", "principals"),
        link("verified_nonce_id", "dingtalk_binding_nonces"),
        UniqueConstraint("tenant_id", "verified_nonce_id"),
        Index(
            "dingtalk_one_active_account",
            "tenant_id",
            "owner_id",
            unique=True,
            postgresql_where=active.is_(True),
        ),
        Index(
            "dingtalk_one_active_external",
            "application_id",
            "external_user_id",
            unique=True,
            postgresql_where=active.is_(True),
        ),
        CheckConstraint("epoch>0 AND length(external_user_id)>0"),
        CheckConstraint(
            "(active AND revoked_by IS NULL AND revoke_key IS NULL) OR "
            "(NOT active AND revoked_by IS NOT NULL AND revoke_key IS NOT NULL)"
        ),
    )


class BindingNonce(Row, Base):
    __tablename__ = "dingtalk_binding_nonces"
    application_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    app_revision: Mapped[int] = mapped_column(Integer)
    state_sha256: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("state_sha256"),
        link("application_id", "dingtalk_applications"),
        link("owner_id", "principals"),
        CheckConstraint("app_revision>0 AND length(state_sha256)=64"),
    )


class Message(Row, Base):
    __tablename__ = "dingtalk_messages"
    application_id: Mapped[UUID]
    binding_id: Mapped[UUID]
    binding_epoch: Mapped[int] = mapped_column(Integer)
    owner_id: Mapped[UUID]
    external_message_id: Mapped[str] = mapped_column(String(200))
    envelope_sha256: Mapped[str] = mapped_column(String(64))
    conversation_kind: Mapped[str] = mapped_column(String(16))
    conversation_id: Mapped[str] = mapped_column(String(200))
    run_id: Mapped[UUID]
    state: Mapped[str] = mapped_column(String(24), default="pending")
    error_code: Mapped[str | None] = mapped_column(String(80))
    lease_id: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    workflow_id: Mapped[str | None] = mapped_column(String(240))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("application_id", "external_message_id"),
        UniqueConstraint("tenant_id", "run_id"),
        link("application_id", "dingtalk_applications"),
        link("binding_id", "dingtalk_account_bindings"),
        link("owner_id", "principals"),
        link("run_id", "agent_runs"),
        CheckConstraint("binding_epoch>0 AND length(envelope_sha256)=64"),
        CheckConstraint("conversation_kind IN ('direct','group')"),
        CheckConstraint(
            "state IN ('pending','admitted','completed','cancelled','unknown','blocked')"
        ),
    )


class ShareConsent(Row, Base):
    __tablename__ = "dingtalk_share_consents"
    message_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    request_key: Mapped[UUID]
    payload_sha256: Mapped[str] = mapped_column(String(64))
    include_citations: Mapped[bool] = mapped_column(Boolean)
    state: Mapped[str] = mapped_column(String(24), default="confirmed")
    error_code: Mapped[str | None] = mapped_column(String(80))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "owner_id", "request_key"),
        link("message_id", "dingtalk_messages"),
        link("owner_id", "principals"),
        CheckConstraint("length(payload_sha256)=64"),
        CheckConstraint(
            "state IN ('confirmed','dispatched','blocked','delivered','unknown','cancelled')"
        ),
    )


class Delivery(Row, Base):
    __tablename__ = "dingtalk_deliveries"
    message_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    consent_id: Mapped[UUID | None]
    request_key: Mapped[UUID]
    phase: Mapped[str] = mapped_column(String(24))
    payload: Mapped[dict] = mapped_column(JSONB)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    content_kind: Mapped[str] = mapped_column(String(24))
    source_dependencies: Mapped[list] = mapped_column(JSONB, default=list)
    state: Mapped[str] = mapped_column(String(24))
    p26: Mapped[dict | None] = mapped_column(JSONB)
    provider_receipt: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(80))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    attempt_id: Mapped[UUID | None]
    send_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "request_key"),
        link("message_id", "dingtalk_messages"),
        link("owner_id", "principals"),
        link("consent_id", "dingtalk_share_consents"),
        CheckConstraint("phase IN ('received','answer','group_notice','share')"),
        CheckConstraint(
            "state IN ('planned','sending','delivered','unknown','blocked','cancelled')"
        ),
        CheckConstraint("attempts>=0 AND length(payload_sha256)=64"),
        CheckConstraint("content_kind IN ('control','answer','local_link')"),
        CheckConstraint(
            "CASE WHEN jsonb_typeof(source_dependencies)='array' THEN "
            "(content_kind='answer')=(jsonb_array_length(source_dependencies)>0) "
            "ELSE false END"
        ),
        CheckConstraint(
            "(phase='share' AND consent_id IS NOT NULL) OR (phase<>'share' AND consent_id IS NULL)"
        ),
        CheckConstraint("state NOT IN ('sending','delivered','unknown') OR p26 IS NOT NULL"),
    )
