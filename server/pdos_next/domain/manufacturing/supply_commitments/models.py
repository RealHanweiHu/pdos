"""Append-only supplier-commitment facts and one exact Current per commitment.

Rows inherit the fixed Build's owner and visibility, so a commitment is readable
exactly when its Build is. Nothing here is stock, an arrival or a reservation.
"""

# ruff: noqa: E501 -- PostgreSQL predicates remain readable as full expressions.

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.core.models import Base, Row

from .schemas import ACTIONS, OPERATION

VERSIONS = "supply_commitment_versions"
CURRENTS = "supply_commitment_currents"
BINDING = (
    "tenant_id",
    "category_id",
    "product_id",
    "project_id",
    "build_id",
    "owner_id",
    "visibility",
)


def _fk(local, table, remote, **options):
    return ForeignKeyConstraint(list(local), [f"{table}.{name}" for name in remote], **options)


def _scope():
    return (
        _fk(
            ("tenant_id", "category_id", "product_id"),
            "products",
            ("tenant_id", "category_id", "id"),
        ),
        _fk(
            ("tenant_id", "product_id", "project_id", "build_id"),
            "builds",
            ("tenant_id", "product_id", "project_id", "id"),
        ),
        _fk(("tenant_id", "owner_id"), "principals", ("tenant_id", "id")),
        CheckConstraint("visibility IN ('private','category','audience')"),
    )


class _Scope(Row):
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))


class SupplyCommitmentVersion(_Scope, Base):
    __tablename__ = VERSIONS
    commitment_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(16))
    material_id: Mapped[UUID]
    writer_id: Mapped[UUID]
    actor_id: Mapped[UUID]
    requester_id: Mapped[UUID]
    operation: Mapped[str] = mapped_column(String(80))
    command_id: Mapped[UUID]
    command: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    reads: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    body: Mapped[dict] = mapped_column(JSONB)
    body_sha256: Mapped[str] = mapped_column(String(64))
    intent_digest: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))
    receipt_id: Mapped[UUID]

    @property
    def status(self):
        return self.state

    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "receipt_id"),
        UniqueConstraint("tenant_id", "command_id"),
        UniqueConstraint("tenant_id", "product_id", "commitment_id", "revision"),
        UniqueConstraint(*BINDING, "commitment_id", "id", "revision"),
        *(
            _fk(("tenant_id", name), "principals", ("tenant_id", "id"))
            for name in ("writer_id", "actor_id", "requester_id")
        ),
        _fk(
            ("tenant_id", "receipt_id"),
            "action_receipts",
            ("tenant_id", "id"),
            deferrable=True,
            initially="DEFERRED",
        ),
        _fk(
            (*BINDING, "commitment_id", "previous_id", "previous_revision"),
            VERSIONS,
            (*BINDING, "commitment_id", "id", "revision"),
        ),
        CheckConstraint(
            "(revision=1 AND commitment_id=id AND action='create' AND state='open' "
            "AND previous_id IS NULL AND previous_revision IS NULL) OR "
            "(revision>1 AND action<>'create' AND previous_id IS NOT NULL AND previous_id<>id "
            "AND previous_revision=revision-1)",
            name="supply_commitment_version_chain",
        ),
        CheckConstraint(
            f"operation='{OPERATION}' AND writer_id=actor_id", name="supply_commitment_t0_only"
        ),
        CheckConstraint("state IN ('open','closed')", name="supply_commitment_state"),
        CheckConstraint(
            "action IN (" + ",".join(repr(value) for value in ACTIONS) + ")",
            name="supply_commitment_action",
        ),
        CheckConstraint(
            "jsonb_typeof(command)='object' AND jsonb_typeof(body)='object' AND jsonb_typeof(source_basis)='object' "
            "AND jsonb_typeof(sources)='array' AND jsonb_typeof(reads)='array' "
            "AND (jsonb_array_length(sources)>0 OR (body->>'time_basis'='human_recorded' AND body->>'statement' IS NOT NULL)) "
            "AND body->>'commitment_id'=commitment_id::text AND (body->>'revision')::integer=revision AND body->>'state'=state "
            "AND body->>'build_id'=build_id::text AND body->>'material_id'=material_id::text",
            name="supply_commitment_body",
        ),
        CheckConstraint(
            "body_sha256 ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$' AND intent_digest ~ '^[a-f0-9]{64}$'",
            name="supply_commitment_digests",
        ),
    )


class SupplyCommitmentCurrent(_Scope, Base):
    __tablename__ = CURRENTS
    commitment_id: Mapped[UUID]
    version_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16))
    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "commitment_id"),
        _fk(
            (*BINDING, "commitment_id", "version_id", "revision"),
            VERSIONS,
            (*BINDING, "commitment_id", "id", "revision"),
        ),
        CheckConstraint(
            "revision>0 AND state IN ('open','closed')", name="supply_commitment_current_state"
        ),
    )
