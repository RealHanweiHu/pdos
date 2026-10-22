"""Immutable named release exceptions and their two-step Current projection.

An exception binds one fixed package, policy and purpose. Its existence grants no
release; rule evaluation still owns applicability and non-waivable conditions.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row

DECISION = "release_exception_decisions"
CURRENT = "release_exception_currents"
DECIDE = "release.exception.decide"
WITHDRAW = "release.exception.withdraw"
SUBJECT = "release_exception"
SCOPE = ("tenant_id", "category_id", "product_id", "project_id")
BINDING = (*SCOPE, "series_id", "owner_id", "visibility")
FIXED_FIELDS = (
    "basis_package_id",
    "basis_package_revision",
    "policy_fact_id",
    "policy_fact_revision",
    "discipline",
    "purpose",
)


def _fk(local, table, remote, **options):
    return ForeignKeyConstraint(list(local), [f"{table}.{key}" for key in remote], **options)


def _scope():
    return (
        _fk(
            ("tenant_id", "category_id", "product_id"),
            "products",
            ("tenant_id", "category_id", "id"),
        ),
        _fk(
            ("tenant_id", "product_id", "project_id"),
            "projects",
            ("tenant_id", "product_id", "id"),
        ),
        _fk(("tenant_id", "owner_id"), "principals", ("tenant_id", "id")),
        CheckConstraint("visibility IN ('private','category','audience')"),
        CheckConstraint("discipline IN ('engineering','manufacturing') AND length(purpose)>0"),
        CheckConstraint("basis_package_revision>0 AND policy_fact_revision>0"),
    )


class ReleaseExceptionDecision(Row, Base):
    __tablename__ = DECISION
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer, default=1)
    series_id: Mapped[UUID]
    previous_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    owner_id: Mapped[UUID]
    writer_id: Mapped[UUID]
    actor_id: Mapped[UUID]
    requester_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    basis_package_id: Mapped[UUID]
    basis_package_revision: Mapped[int] = mapped_column(Integer)
    policy_fact_id: Mapped[UUID]
    policy_fact_revision: Mapped[int] = mapped_column(Integer)
    discipline: Mapped[str] = mapped_column(String(16))
    purpose: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(16))
    operation: Mapped[str] = mapped_column(String(80))
    write_tier: Mapped[str] = mapped_column(String(4), default="T2")
    expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    body: Mapped[dict] = mapped_column(JSONB)
    body_sha256: Mapped[str] = mapped_column(String(64))
    material_snapshot: Mapped[dict] = mapped_column(JSONB)
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    authority_snapshot: Mapped[dict] = mapped_column(JSONB)
    command_id: Mapped[UUID]
    receipt_id: Mapped[UUID]
    intent_digest: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))
    shared_proof_id: Mapped[UUID]
    shared_proof_revision: Mapped[int] = mapped_column(Integer)
    proof_consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    proof_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_sha256: Mapped[str] = mapped_column(String(64))
    material_sha256: Mapped[str] = mapped_column(String(64))
    read_set_sha256: Mapped[str] = mapped_column(String(64))

    @property
    def status(self):
        """The common receipt records this fact's action without mutating it."""
        return self.action

    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "id", "revision"),
        UniqueConstraint(*BINDING, "id", "revision"),
        UniqueConstraint(*BINDING, "id", "revision", "action"),
        UniqueConstraint("tenant_id", "previous_id"),
        UniqueConstraint("tenant_id", "receipt_id"),
        UniqueConstraint("tenant_id", "command_id"),
        UniqueConstraint("tenant_id", "shared_proof_id"),
        UniqueConstraint("tenant_id", "product_id", "actor_id", "operation", "intent_digest"),
        _fk(
            (*BINDING, "previous_id", "previous_revision"),
            DECISION,
            (*BINDING, "id", "revision"),
        ),
        _fk(
            ("tenant_id", "product_id", "basis_package_id", "basis_package_revision"),
            "release_packages",
            ("tenant_id", "product_id", "id", "revision"),
        ),
        # Policy revisions are checked against the immutable row by the SQL atom;
        # its existing candidate key is (tenant_id,id), not a fabricated new key.
        _fk(("tenant_id", "policy_fact_id"), "release_policy_facts", ("tenant_id", "id")),
        *(
            _fk(("tenant_id", field), "principals", ("tenant_id", "id"))
            for field in ("writer_id", "actor_id", "requester_id")
        ),
        *(
            _fk(
                ("tenant_id", field),
                table,
                ("tenant_id", "id"),
                deferrable=True,
                initially="DEFERRED",
            )
            for field, table in (
                ("receipt_id", "action_receipts"),
                ("shared_proof_id", "confirmations"),
            )
        ),
        CheckConstraint("revision=1 AND shared_proof_revision>0 AND write_tier='T2'"),
        CheckConstraint("actor_id=requester_id AND writer_id=actor_id"),
        CheckConstraint(
            f"(action='approved' AND operation='{DECIDE}' AND series_id=id "
            "AND previous_id IS NULL AND previous_revision IS NULL) OR "
            f"(action='withdrawn' AND operation='{WITHDRAW}' AND previous_id=series_id "
            "AND previous_id<>id AND previous_revision=1)"
        ),
        CheckConstraint(
            "proof_consumed_at<=created_at AND "
            "(proof_expires_at IS NULL OR created_at<proof_expires_at)"
        ),
        CheckConstraint("action='withdrawn' OR expiry IS NULL OR created_at<expiry"),
        CheckConstraint(
            "jsonb_typeof(body)='object' AND jsonb_typeof(material_snapshot)='object' "
            "AND jsonb_typeof(input_snapshot)='object' AND jsonb_typeof(source_basis)='object' "
            "AND jsonb_typeof(authority_snapshot)='object' "
            "AND jsonb_typeof(sources)='array' AND jsonb_array_length(sources)>0 "
            "AND jsonb_typeof(required_source_read_set)='array' "
            "AND jsonb_array_length(required_source_read_set)>0"
        ),
        CheckConstraint(
            "body_sha256 ~ '^[a-f0-9]{64}$' AND intent_digest ~ '^[a-f0-9]{64}$' "
            "AND request_digest ~ '^[a-f0-9]{64}$' AND token_sha256 ~ '^[a-f0-9]{64}$' "
            "AND material_sha256 ~ '^[a-f0-9]{64}$' AND read_set_sha256 ~ '^[a-f0-9]{64}$'"
        ),
    )


class ReleaseExceptionCurrent(Row, Base):
    __tablename__ = CURRENT
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    series_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    basis_package_id: Mapped[UUID]
    basis_package_revision: Mapped[int] = mapped_column(Integer)
    policy_fact_id: Mapped[UUID]
    policy_fact_revision: Mapped[int] = mapped_column(Integer)
    discipline: Mapped[str] = mapped_column(String(16))
    purpose: Mapped[str] = mapped_column(Text)
    decision_id: Mapped[UUID]
    decision_revision: Mapped[int] = mapped_column(Integer, default=1)
    action: Mapped[str] = mapped_column(String(16))
    epoch: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        *_scope(),
        UniqueConstraint(*SCOPE, "series_id"),
        _fk(
            (*BINDING, "decision_id", "decision_revision", "action"),
            DECISION,
            (*BINDING, "id", "revision", "action"),
        ),
        CheckConstraint(
            "decision_revision=1 AND ((action='approved' AND epoch=1 AND decision_id=series_id) "
            "OR (action='withdrawn' AND epoch=2 AND decision_id<>series_id))"
        ),
    )
