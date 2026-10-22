# ruff: noqa: I001 -- register child tables after their shared parent definitions
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    FetchedValue,
    Index,
    Integer,
    Numeric,
    Date,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


from pdos_next.clock import now
from pdos_next.command_handlers import T2_OPERATIONS


class Base(DeclarativeBase):
    pass


class Row:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    @declared_attr
    def category_id(cls):
        if any("product_id" in base.__dict__.get("__annotations__", {}) for base in cls.__mro__):
            return mapped_column(Uuid, nullable=False, index=True, server_default=FetchedValue())
        return None


class Principal(Row, Base):
    __tablename__ = "principals"
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    access_epoch: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("kind IN ('human','agent')"),
    )


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[UUID]
    principal_id: Mapped[UUID]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "principal_id"], ["principals.tenant_id", "principals.id"]
        ),
    )


class Category(Row, Base):
    __tablename__ = "categories"
    key: Mapped[str] = mapped_column(Text, default=lambda: "category-" + uuid4().hex)
    name: Mapped[str] = mapped_column(String(160))
    purpose: Mapped[str] = mapped_column(Text)
    owner_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="active")
    lifecycle_epoch: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by_run_id: Mapped[UUID | None]
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "key"),
        CheckConstraint("key ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="category_key_shape"),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_run_id"],
            ["agent_runs.tenant_id", "agent_runs.id"],
            use_alter=True,
            name="category_created_by_run_fk",
        ),
        CheckConstraint("revision > 0 AND status IN ('active','archived')"),
    )


class ObjectAudience(Row, Base):
    __tablename__ = "object_audiences"
    category_id: Mapped[UUID] = mapped_column(index=True)
    object_type: Mapped[str] = mapped_column(String(128))
    subject_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    principal_id: Mapped[UUID]
    __table_args__ = (
        UniqueConstraint("tenant_id", "category_id", "object_type", "subject_id", "principal_id"),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"], ["categories.tenant_id", "categories.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "principal_id"], ["principals.tenant_id", "principals.id"]
        ),
    )


class Product(Row, Base):
    __tablename__ = "products"
    name: Mapped[str] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    lifecycle_epoch: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    owner_id: Mapped[UUID]
    parent_product_id: Mapped[UUID | None]
    category_id: Mapped[UUID] = mapped_column(index=True)
    visibility: Mapped[str] = mapped_column(String(16), default="category")
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    target_price_currency: Mapped[str | None] = mapped_column(Text)
    target_price_basis: Mapped[str | None] = mapped_column(Text)
    target_price_includes_tax: Mapped[bool | None] = mapped_column(Boolean)
    target_price_as_of: Mapped[date | None] = mapped_column(Date)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "parent_product_id"],
            ["products.tenant_id", "products.category_id", "products.id"],
            name="m3_product_parent_fk",
        ),
        CheckConstraint("parent_product_id IS DISTINCT FROM id", name="m3_product_parent_not_self"),
        CheckConstraint(
            "target_price_basis IS NULL OR target_price_basis IN ('retail','promo','unknown')",
            name="m3_target_price_basis",
        ),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "category_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"], ["categories.tenant_id", "categories.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("revision > 0"),
    )


class Grant(Row, Base):
    __tablename__ = "grants"
    category_id: Mapped[UUID] = mapped_column(index=True)
    principal_id: Mapped[UUID]
    can_write: Mapped[bool] = mapped_column(Boolean, default=False)
    product_manager: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    access_epoch: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        UniqueConstraint("tenant_id", "category_id", "principal_id"),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"], ["categories.tenant_id", "categories.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "principal_id"], ["principals.tenant_id", "principals.id"]
        ),
    )


class Artifact(Row, Base):
    __tablename__ = "artifact_versions"
    product_id: Mapped[UUID | None]
    owner_id: Mapped[UUID]
    title: Mapped[str] = mapped_column(String(200))
    source_label: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    visibility: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    original_id: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(String(16), default="active")
    __table_args__ = (
        UniqueConstraint("tenant_id", "original_id"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "original_id"],
            [
                "uploaded_originals.tenant_id",
                "uploaded_originals.product_id",
                "uploaded_originals.id",
            ],
        ),
        UniqueConstraint("tenant_id", "product_id", "id"),
        ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"]),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("visibility IN ('private','category','audience')"),
        CheckConstraint("status IN ('active','withdrawn')"),
    )


class Claim(Row, Base):
    __tablename__ = "claims"
    product_id: Mapped[UUID | None]
    artifact_id: Mapped[UUID | None]
    proposal_id: Mapped[UUID | None]
    snapshot_id: Mapped[UUID | None]
    source_kind: Mapped[str] = mapped_column(Text, default="artifact", server_default="artifact")
    source_locator: Mapped[str | None] = mapped_column(Text)
    source_revision: Mapped[int] = mapped_column(Integer)
    line: Mapped[int] = mapped_column(Integer)
    quote: Mapped[str] = mapped_column(Text)
    statement: Mapped[str] = mapped_column(Text)
    content: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    vendor_claimed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    privacy: Mapped[str] = mapped_column(Text, default="private", server_default="private")
    origin: Mapped[str] = mapped_column(Text, default="human", server_default="human")
    run_id: Mapped[UUID | None]
    confirmed_by: Mapped[UUID | None]
    receipt_id: Mapped[UUID | None]
    prepared_event_id: Mapped[UUID | None]
    extraction_ref: Mapped[dict | str | None] = mapped_column(JSONB)
    nature: Mapped[str] = mapped_column(String(16))
    availability: Mapped[str] = mapped_column(String(16))
    visibility: Mapped[str] = mapped_column(String(16))
    human_owner_id: Mapped[UUID]
    writer_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="active")
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint("tenant_id", "category_id", "id", name="claim_category_identity"),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "proposal_id"],
            ["proposals.tenant_id", "proposals.category_id", "proposals.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "snapshot_id"],
            [
                "public_web_snapshots.tenant_id",
                "public_web_snapshots.category_id",
                "public_web_snapshots.id",
            ],
            use_alter=True,
            name="m3_claims_tenant_id_category_id_snapshot_id_fk",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "run_id"],
            ["agent_runs.tenant_id", "agent_runs.category_id", "agent_runs.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "confirmed_by"],
            ["principals.tenant_id", "principals.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"],
            ["action_receipts.tenant_id", "action_receipts.id"],
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
            name="claim_receipt_fk",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "artifact_id"],
            [
                "artifact_versions.tenant_id",
                "artifact_versions.category_id",
                "artifact_versions.id",
            ],
            name="fk_claims_category_artifact_id",
        ),
        ForeignKeyConstraint(["tenant_id", "writer_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "human_owner_id"],
            ["principals.tenant_id", "principals.id"],
        ),
        CheckConstraint("nature IN ('observed','extracted','computed','inferred','decided')"),
        CheckConstraint("availability IN ('known','unknown','conflicted','not_applicable')"),
        CheckConstraint("visibility IN ('private','category','audience')"),
        CheckConstraint("status IN ('active','reverted','withdrawn')"),
        CheckConstraint("line > 0 AND revision > 0 AND source_revision > 0"),
        CheckConstraint(
            "(source_kind='artifact' AND artifact_id IS NOT NULL AND snapshot_id IS NULL) OR "
            "(source_kind='snapshot' AND artifact_id IS NULL AND snapshot_id IS NOT NULL)",
            name="claim_one_source",
        ),
        CheckConstraint("privacy IN ('private','shared')", name="claim_privacy"),
        CheckConstraint("origin IN ('human','ai_draft')", name="claim_origin"),
        CheckConstraint("NOT vendor_claimed OR nature='extracted'", name="claim_vendor_nature"),
    )


class Consumption(Row, Base):
    __tablename__ = "claim_consumptions"
    product_id: Mapped[UUID | None]
    claim_id: Mapped[UUID]
    claim_version: Mapped[int | None]
    decision_id: Mapped[UUID | None]
    definition_id: Mapped[UUID | None]
    receipt_id: Mapped[UUID | None]
    consumer_type: Mapped[str] = mapped_column(String(80))
    consumer_id: Mapped[UUID]
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "claim_id"],
            ["claims.tenant_id", "claims.category_id", "claims.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "decision_id"],
            [
                "proposal_decisions.tenant_id",
                "proposal_decisions.category_id",
                "proposal_decisions.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "definition_id"],
            [
                "definition_revisions.tenant_id",
                "definition_revisions.category_id",
                "definition_revisions.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"],
            ["action_receipts.tenant_id", "action_receipts.id"],
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
            name="claim_consumption_receipt_fk",
        ),
        CheckConstraint(
            "claim_version IS NULL OR claim_version>0", name="claim_consumption_version"
        ),
    )


class WorkRequest(Row, Base):
    __tablename__ = "work_requests"
    product_id: Mapped[UUID]
    artifact_id: Mapped[UUID]
    source_revision: Mapped[int] = mapped_column(Integer)
    goal: Mapped[str] = mapped_column(Text)
    outcome_spec: Mapped[dict] = mapped_column(JSONB)
    accountable_owner_id: Mapped[UUID]
    authorization: Mapped[dict] = mapped_column(JSONB)
    max_actions: Mapped[int] = mapped_column(Integer)
    stop_condition: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(32), default="accepted")
    error_code: Mapped[str | None] = mapped_column(String(80))
    result_id: Mapped[UUID | None]
    revision: Mapped[int] = mapped_column(Integer, default=1)
    signal_epoch: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "artifact_id"],
            [
                "artifact_versions.tenant_id",
                "artifact_versions.category_id",
                "artifact_versions.id",
            ],
            name="fk_work_requests_category_artifact_id",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "accountable_owner_id"],
            ["principals.tenant_id", "principals.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "result_id"],
            ["claims.tenant_id", "claims.product_id", "claims.id"],
        ),
        CheckConstraint("status IN ('accepted','running','waiting_input','completed','cancelled')"),
    )


class Run(Row, Base):
    __tablename__ = "runs"
    product_id: Mapped[UUID]
    work_id: Mapped[UUID]
    requester_id: Mapped[UUID]
    writer_id: Mapped[UUID | None]
    cancel_epoch: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    skill_version: Mapped[str] = mapped_column(String(80), default="source-claim@1")
    provider_version: Mapped[str | None] = mapped_column(String(160))
    lease_id: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_limit: Mapped[int] = mapped_column(Integer, default=10000)
    reserved_tokens: Mapped[int] = mapped_column(Integer, default=0)
    used_tokens: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "work_id"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "work_id"],
            ["work_requests.tenant_id", "work_requests.product_id", "work_requests.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "requester_id"], ["principals.tenant_id", "principals.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "writer_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint(
            "status IN ('queued','running','waiting','succeeded','failed','cancelled')"
        ),
    )


class Qualification(Row, Base):
    __tablename__ = "qualifications"
    writer_id: Mapped[UUID]
    skill_version: Mapped[str] = mapped_column(String(80))
    provider_version: Mapped[str] = mapped_column(String(160))
    operation: Mapped[str] = mapped_column(String(80))
    purpose: Mapped[str] = mapped_column(String(80))
    evaluation_kind: Mapped[str] = mapped_column(String(16))
    evaluation_ref: Mapped[str] = mapped_column(String(200))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "writer_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("evaluation_kind IN ('synthetic','real')"),
    )


class Receipt(Row, Base):
    __tablename__ = "action_receipts"
    product_id: Mapped[UUID | None]
    command_id: Mapped[UUID]
    actor_id: Mapped[UUID]
    requester_id: Mapped[UUID]
    operation: Mapped[str] = mapped_column(String(80))
    subject_type: Mapped[str] = mapped_column(String(32))
    subject_id: Mapped[UUID]
    subject_revision: Mapped[int] = mapped_column(Integer)
    visibility: Mapped[str] = mapped_column(String(16))
    request_digest: Mapped[str] = mapped_column(String(64))
    intent_digest: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[UUID | None]
    agent_run_id: Mapped[UUID | None]
    confirmation_id: Mapped[UUID | None]
    result: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "confirmation_id", name="material_receipt_confirmation_once"),
        ForeignKeyConstraint(
            ["tenant_id", "confirmation_id"],
            ["confirmations.tenant_id", "confirmations.id"],
            name="material_receipt_confirmation_fk",
            use_alter=True,
        ),
        UniqueConstraint(
            "tenant_id",
            "category_id",
            "product_id",
            "intent_digest",
            name="uq_action_receipts_scope_intent",
            postgresql_nulls_not_distinct=True,
        ),
        ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"]),
        ForeignKeyConstraint(["tenant_id", "actor_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "requester_id"],
            ["principals.tenant_id", "principals.id"],
        ),
        ForeignKeyConstraint(["tenant_id", "run_id"], ["runs.tenant_id", "runs.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "agent_run_id"],
            ["agent_runs.tenant_id", "agent_runs.category_id", "agent_runs.id"],
            name="fk_action_receipts_agent_run",
        ),
        CheckConstraint("run_id IS NULL OR agent_run_id IS NULL", name="receipt_one_run_identity"),
    )


class RequestKey(Row, Base):
    __tablename__ = "request_keys"
    actor_id: Mapped[UUID]
    key: Mapped[str] = mapped_column(String(160))
    digest: Mapped[str] = mapped_column(String(64))
    receipt_id: Mapped[UUID]
    category_id: Mapped[UUID] = mapped_column(index=True, server_default=FetchedValue())
    __table_args__ = (
        UniqueConstraint("tenant_id", "actor_id", "key"),
        ForeignKeyConstraint(["tenant_id", "actor_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"],
            ["action_receipts.tenant_id", "action_receipts.id"],
        ),
    )


class Audit(Row, Base):
    __tablename__ = "audit_entries"
    receipt_id: Mapped[UUID]
    category_id: Mapped[UUID] = mapped_column(index=True, server_default=FetchedValue())
    actor_id: Mapped[UUID]
    operation: Mapped[str] = mapped_column(String(80))
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"],
            ["action_receipts.tenant_id", "action_receipts.id"],
        ),
    )


class Outbox(Row, Base):
    __tablename__ = "outbox_events"
    receipt_id: Mapped[UUID]
    category_id: Mapped[UUID] = mapped_column(index=True, server_default=FetchedValue())
    type: Mapped[str] = mapped_column(String(80))
    subject_id: Mapped[UUID]
    subject_revision: Mapped[int] = mapped_column(Integer)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    actor_id: Mapped[UUID]
    correlation_id: Mapped[UUID]
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_id: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(80))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"],
            ["action_receipts.tenant_id", "action_receipts.id"],
        ),
    )


class Confirmation(Row, Base):
    __tablename__ = "confirmations"
    product_id: Mapped[UUID | None]
    actor_id: Mapped[UUID]
    subject_id: Mapped[UUID]
    subject_type: Mapped[str] = mapped_column(
        String(32), default="product", server_default="product"
    )
    operation: Mapped[str] = mapped_column(String(80))
    revision: Mapped[int] = mapped_column(Integer)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    payload_digest: Mapped[str | None] = mapped_column(String(64))
    snapshot: Mapped[dict | None] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_confirmations_tenant_id_id_capa"),
        CheckConstraint(
            "expires_at IS NOT NULL OR operation IN ("
            + ",".join(repr(operation) for operation in sorted(T2_OPERATIONS))
            + ")",
            name="ck_confirmations_decision_deadline",
        ),
        ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"]),
        ForeignKeyConstraint(["tenant_id", "actor_id"], ["principals.tenant_id", "principals.id"]),
    )


class UploadedOriginal(Row, Base):
    __tablename__ = "uploaded_originals"
    product_id: Mapped[UUID | None]
    owner_id: Mapped[UUID]
    title: Mapped[str] = mapped_column(String(200))
    filename: Mapped[str] = mapped_column(String(200))
    source_label: Mapped[str] = mapped_column(String(200))
    visibility: Mapped[str] = mapped_column(String(16), default="private")
    media_type: Mapped[str] = mapped_column(String(100))
    byte_count: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(300), unique=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    parse_code: Mapped[str | None] = mapped_column(String(80))
    locator_map: Mapped[list] = mapped_column(JSONB, default=list)
    parse_manifest: Mapped[dict | None] = mapped_column(JSONB)
    scan_status: Mapped[str] = mapped_column(String(32), default="not_scanned")
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "id"),
        ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"]),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("visibility IN ('private','category','audience')"),
        CheckConstraint("byte_count > 0 AND byte_count <= 8388608"),
        CheckConstraint("status IN ('uploaded','parsed','needs_ocr','failed')"),
    )


class OriginalScanRequest(Row, Base):
    __tablename__ = "original_scan_requests"
    product_id: Mapped[UUID | None]
    original_id: Mapped[UUID]
    requester_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="requested")
    binding: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "original_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "original_id", "revision"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "original_id"],
            [
                "uploaded_originals.tenant_id",
                "uploaded_originals.product_id",
                "uploaded_originals.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "requester_id"], ["principals.tenant_id", "principals.id"]
        ),
        CheckConstraint("revision > 0 AND status = 'requested'"),
    )


class OriginalScanResult(Row, Base):
    __tablename__ = "original_scan_results"
    product_id: Mapped[UUID | None]
    original_id: Mapped[UUID]
    request_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    result: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("tenant_id", "request_id"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "original_id", "request_id"],
            [
                "original_scan_requests.tenant_id",
                "original_scan_requests.product_id",
                "original_scan_requests.original_id",
                "original_scan_requests.id",
            ],
        ),
        CheckConstraint(
            "revision > 0 AND status IN "
            "('clean','infected','unknown','unavailable','timeout','rejected')"
        ),
    )


class OriginalSecurity(Row, Base):
    __tablename__ = "original_security"
    product_id: Mapped[UUID | None]
    original_id: Mapped[UUID]
    epoch: Mapped[int] = mapped_column(Integer, default=1)
    source_state: Mapped[str] = mapped_column(String(16), default="active")
    disposition: Mapped[str] = mapped_column(String(16), default="active")
    current_request_id: Mapped[UUID | None]
    __table_args__ = (
        UniqueConstraint("tenant_id", "original_id"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "original_id"],
            [
                "uploaded_originals.tenant_id",
                "uploaded_originals.product_id",
                "uploaded_originals.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "original_id", "current_request_id"],
            [
                "original_scan_requests.tenant_id",
                "original_scan_requests.product_id",
                "original_scan_requests.original_id",
                "original_scan_requests.id",
            ],
        ),
        CheckConstraint("epoch > 0 AND source_state IN ('active','withdrawn')"),
        CheckConstraint("disposition IN ('active','quarantined','unknown')"),
    )


class Inbox(Row, Base):
    __tablename__ = "inbox_deliveries"
    event_id: Mapped[UUID]
    product_id: Mapped[UUID | None]
    consumer: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    workflow_id: Mapped[str | None] = mapped_column(String(200))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("tenant_id", "consumer", "event_id"),
        ForeignKeyConstraint(
            ["tenant_id", "event_id"], ["outbox_events.tenant_id", "outbox_events.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"]),
        CheckConstraint("status IN ('pending','received','ignored')"),
    )


class Invocation(Row, Base):
    __tablename__ = "model_invocations"
    run_id: Mapped[UUID]
    step_key: Mapped[str] = mapped_column(String(80))
    input_digest: Mapped[str] = mapped_column(String(64))
    provider_version: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(16), default="started")
    candidate: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(80))
    call_id: Mapped[UUID | None]
    __table_args__ = (
        UniqueConstraint("tenant_id", "call_id"),
        UniqueConstraint("tenant_id", "run_id", "step_key"),
        ForeignKeyConstraint(["tenant_id", "run_id"], ["runs.tenant_id", "runs.id"]),
        CheckConstraint("status IN ('started','completed','unknown','rejected')"),
    )


class BudgetReservation(Row, Base):
    __tablename__ = "model_budget_reservations"
    run_id: Mapped[UUID]
    call_id: Mapped[UUID]
    token_hash: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))
    reserved: Mapped[int] = mapped_column(Integer)
    charged: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="reserved")
    error_code: Mapped[str | None] = mapped_column(String(80))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    provider_version: Mapped[str | None] = mapped_column(String(160))
    protocol: Mapped[str | None] = mapped_column(String(32))
    route_digest: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(200))
    normalized_usage: Mapped[dict | None] = mapped_column(JSONB)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reconciliation_history: Mapped[list] = mapped_column(JSONB, default=list)
    __table_args__ = (
        UniqueConstraint("tenant_id", "call_id"),
        ForeignKeyConstraint(["tenant_id", "run_id"], ["runs.tenant_id", "runs.id"]),
        CheckConstraint("status IN ('reserved','completed','rejected','unknown')"),
        CheckConstraint("reserved > 0 AND (charged IS NULL OR charged >= 0)"),
    )


class UploadAttempt(Row, Base):
    """Committed reservation precedes bytes; terminal abandonment excludes late registration."""

    __tablename__ = "upload_attempts"
    product_id: Mapped[UUID | None]
    owner_id: Mapped[UUID]
    request_key: Mapped[str] = mapped_column(String(200))
    request_digest: Mapped[str] = mapped_column(String(64))
    reference: Mapped[dict] = mapped_column(JSONB)
    title: Mapped[str] = mapped_column(String(200))
    filename: Mapped[str] = mapped_column(String(200))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="reserved")
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint("tenant_id", "owner_id", "request_key"),
        ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"]),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("revision > 0 AND status IN ('reserved','committed','abandoned')"),
        CheckConstraint(
            "(status='reserved' AND terminal_at IS NULL) OR "
            "(status<>'reserved' AND terminal_at IS NOT NULL)"
        ),
    )


class LifecycleObject(Row, Base):
    __tablename__ = "lifecycle_objects"
    product_id: Mapped[UUID | None]
    owner_id: Mapped[UUID]
    reference: Mapped[dict] = mapped_column(JSONB)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[dict] = mapped_column(JSONB)
    manual_hold: Mapped[bool | None] = mapped_column(Boolean)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    protection_revision: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "id"),
        ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"]),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("revision > 0 AND protection_revision > 0"),
    )


class LifecycleCandidate(Row, Base):
    __tablename__ = "lifecycle_candidates"
    product_id: Mapped[UUID | None]
    object_id: Mapped[UUID]
    actor_id: Mapped[UUID]
    document: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "object_id"],
            ["lifecycle_objects.tenant_id", "lifecycle_objects.product_id", "lifecycle_objects.id"],
        ),
        ForeignKeyConstraint(["tenant_id", "actor_id"], ["principals.tenant_id", "principals.id"]),
    )


class LifecycleIntentRecord(Row, Base):
    __tablename__ = "lifecycle_intents"
    category_id: Mapped[UUID] = mapped_column(index=True, server_default=FetchedValue())
    product_id: Mapped[UUID | None]
    object_id: Mapped[UUID]
    actor_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    intent_digest: Mapped[str] = mapped_column(String(64))
    document: Mapped[dict] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (
        Index(
            "lifecycle_candidate_once",
            "tenant_id",
            text("((document -> 'value'::text) ->> 'candidate_id'::text)"),
            unique=True,
        ),
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint(
            "tenant_id",
            "category_id",
            "object_id",
            "intent_digest",
            name="uq_lifecycle_intents_scope_intent",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "object_id"],
            ["lifecycle_objects.tenant_id", "lifecycle_objects.product_id", "lifecycle_objects.id"],
        ),
        ForeignKeyConstraint(["tenant_id", "actor_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("revision > 0"),
    )


class LifecycleRequest(Row, Base):
    __tablename__ = "lifecycle_requests"
    product_id: Mapped[UUID | None]
    object_id: Mapped[UUID]
    actor_id: Mapped[UUID]
    key: Mapped[str] = mapped_column(String(200))
    fingerprint: Mapped[str] = mapped_column(String(64))
    intent_id: Mapped[UUID]
    __table_args__ = (
        UniqueConstraint("tenant_id", "actor_id", "key"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "object_id"],
            ["lifecycle_objects.tenant_id", "lifecycle_objects.product_id", "lifecycle_objects.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "intent_id"],
            ["lifecycle_intents.tenant_id", "lifecycle_intents.product_id", "lifecycle_intents.id"],
        ),
        ForeignKeyConstraint(["tenant_id", "actor_id"], ["principals.tenant_id", "principals.id"]),
    )


# Independent product entities share this metadata, never the legacy schema.
from pdos_next.domain.build_execution.models import (  # noqa: E402,F401
    ActualConfiguration,
    BuildLot,
    SampleAllocation,
    SampleUnit,
)
from pdos_next.domain.build_operational_facts.models import (  # noqa: E402,F401
    BuildOperationalCurrent,
    BuildOperationalFact,
    MaterialHold,
    OperationalAsset,
    ResourceOccupancy,
)
from pdos_next.domain.build_start.models import (  # noqa: E402,F401
    BuildAssessmentCurrent,
    BuildAuthorizationCurrent,
    BuildAuthorizationDecision,
    BuildExecutionAssessment,
    BuildStart,
)
from pdos_next.domain.builds.models import Build, BuildReadiness  # noqa: E402,F401
from pdos_next.domain.configurations.models import (  # noqa: E402,F401
    BomLine,
    BomRevision,
    EngineeringConfiguration,
    PartIdentity,
    ProcessRevision,
)
from pdos_next.domain.cost_execution.models import (  # noqa: E402,F401
    CostCapture,
    CostCurrent,
    CostEstimate,
    CostInputSnapshot,
)
from pdos_next.domain.products.models import (  # noqa: E402,F401
    DefinitionRevision,
    DefinitionSource,
    DefinitionSpecRow,
)
from pdos_next.domain.products.variant_models import Variant, VariantRevision  # noqa: E402,F401
from pdos_next.domain.professional_authority.models import (  # noqa: E402,F401
    ProfessionalCurrent,
    ProfessionalFact,
)
from pdos_next.domain.projects.models import (  # noqa: E402,F401
    PlanProposal,
    PlanRevision,
    Project,
    ProjectProductLink,
    ProjectTask,
    ProjectWorkPackage,
    TaskDependency,
)
from pdos_next.domain.sample_handoff.models import (  # noqa: E402,F401
    SampleReadinessCurrent,
    SampleReadinessFact,
)
from pdos_next.domain.supply_execution.models import (  # noqa: E402,F401
    KitProjection,
    SupplyCapture,
    SupplyCurrent,
    SupplySnapshot,
)
from pdos_next.domain.test_resources.models import (  # noqa: E402,F401
    SampleRunUsage,
    SampleUsageSentinel,
    TestResourceCurrent,
    TestResourceFact,
    TestResourceReservation,
)
from pdos_next.domain.verification_execution.models import (  # noqa: E402,F401
    VerificationCurrent,
    VerificationPreparation,
)
from pdos_next.domain.verification_front.models import (  # noqa: E402,F401
    FormalVerificationCurrent,
    FormalVerificationRequest,
    MethodApplicability,
    VerificationWindowProposal,
)
from pdos_next.domain.verification_handoff.models import (  # noqa: E402,F401
    ActualMethodApplicability,
    ActualMethodBatch,
    ActualMethodCurrent,
    VerificationHandoffFact,
)
from pdos_next.domain.verification_launch.models import (  # noqa: E402,F401
    VerificationLaunchFact,
    VerificationRunCurrent,
    VerificationRunIdentity,
    VerificationRunVersion,
)
from pdos_next.domain.verification_results.models import (  # noqa: E402,F401
    MeasurementImportCapture,
    MeasurementRecord,
    TestResultActionFact,
    TestResultProjection,
)

# Exact fixed result identities referenced by quality event/failure links.
for _parent in (VerificationRunVersion, MeasurementRecord, TestResultProjection):
    _parent.__table__.append_constraint(
        UniqueConstraint(
            "tenant_id",
            "product_id",
            "project_id",
            "request_id",
            "run_id",
            "id",
            "revision",
            name=f"uq_{_parent.__tablename__}_quality_scope",
        )
    )

from pdos_next.domain.capa_verification.models import (  # noqa: E402,F401
    CapaVerificationEvidence,
    RemediationLinkRecord,
)
from pdos_next.domain.change_execution.models import (  # noqa: E402,F401
    ChangeCurrent,
    ChangeGraphCapture,
    ChangeRequestVersion,
)
from pdos_next.domain.quality_execution.models import (  # noqa: E402,F401
    QualityEventFailureLink,
    QualityFailureMap,
    QualityIssueCurrent,
    QualityIssueVersion,
    QualityPolicyCurrent,
    QualityPolicyFact,
)

from pdos_next.domain.capa_effectiveness.models import (  # noqa: E402,F401
    NamedReviewRecord,
    ObservationCurrent,
    ObservationFact,
    RuleCurrent,
    RuleFact,
)


# Proposed change host atoms: register modules without requiring partially-loaded classes.
import pdos_next.change_order_store  # noqa: E402,F401
import pdos_next.change_controlled_store  # noqa: E402,F401

from pdos_next.domain.manufacturing_baseline.models import (  # noqa: E402,F401
    BaselineDocumentLink,
    PreparationCurrent,
    PreparationVersion,
)

import pdos_next.change_dependency_clock  # noqa: E402,F401

import pdos_next.domain.change_coverage_owner.models  # noqa: E402,F401

# Every model-scoped row uses the same tenant/category/product foreign key.
# Scope metadata is part of the mapped schema, never a client-selected ACL.
for _table in Base.metadata.tables.values():
    if "category_id" not in _table.c or _table.name in {"products", "object_audiences", "grants"}:
        continue
    _table.append_constraint(
        ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["categories.tenant_id", "categories.id"],
            name=f"fk_{_table.name}_category",
        )
    )
    if "product_id" in _table.c:
        _table.append_constraint(
            ForeignKeyConstraint(
                ["tenant_id", "category_id", "product_id"],
                ["products.tenant_id", "products.category_id", "products.id"],
                name=f"fk_{_table.name}_category_product",
            )
        )

# Optional-model source bookkeeping still binds exact category/object identities.
for _source in (
    Artifact,
    UploadedOriginal,
    OriginalScanRequest,
    UploadAttempt,
    LifecycleObject,
    LifecycleCandidate,
    LifecycleIntentRecord,
):
    _source.__table__.append_constraint(
        UniqueConstraint(
            "tenant_id", "category_id", "id", name=f"uq_{_source.__tablename__}_category_identity"
        )
    )
OriginalScanRequest.__table__.append_constraint(
    UniqueConstraint(
        "tenant_id",
        "category_id",
        "original_id",
        "revision",
        name="uq_original_scan_requests_scope_revision",
    )
)
for _child, _column, _parent in (
    (Artifact, "original_id", UploadedOriginal),
    (OriginalScanRequest, "original_id", UploadedOriginal),
    (OriginalSecurity, "original_id", UploadedOriginal),
    (OriginalSecurity, "current_request_id", OriginalScanRequest),
    (OriginalScanResult, "request_id", OriginalScanRequest),
    (LifecycleCandidate, "object_id", LifecycleObject),
    (LifecycleIntentRecord, "object_id", LifecycleObject),
    (LifecycleRequest, "object_id", LifecycleObject),
    (LifecycleRequest, "intent_id", LifecycleIntentRecord),
):
    _child.__table__.append_constraint(
        ForeignKeyConstraint(
            ["tenant_id", "category_id", _column],
            [
                f"{_parent.__tablename__}.tenant_id",
                f"{_parent.__tablename__}.category_id",
                f"{_parent.__tablename__}.id",
            ],
            name=f"fk_{_child.__tablename__}_category_{_column}",
        )
    )

# Database-owned audience projections are not domain payload or fact material.
for _name in (
    "actual_configurations",
    "build_authorization_decisions",
    "build_execution_assessments",
    "build_lots",
    "build_operational_facts",
    "build_readiness",
    "build_starts",
    "builds",
    "measurement_import_captures",
    "professional_authority_facts",
    "sample_allocations",
    "sample_readiness_facts",
    "sample_run_usages",
    "sample_units",
    "test_measurements",
    "test_resource_facts",
    "test_resource_reservations",
    "test_result_actions",
    "test_result_projections",
    "verification_actual_method_applicabilities",
    "verification_actual_method_batches",
    "verification_formal_requests",
    "verification_handoff_facts",
    "verification_launch_facts",
    "verification_method_applicabilities",
    "verification_preparations",
    "verification_run_identities",
    "verification_run_versions",
    "verification_window_proposals",
    "quality_issue_versions",
    "quality_event_failure_links",
    "quality_policy_facts",
    "capa_remediation_links",
    "capa_verification_evidence",
    "capa_verification_rule_facts",
    "capa_observation_facts",
    "capa_named_verification_reviews",
):
    Base.metadata.tables[_name].append_column(
        Column("audience_dependencies", JSONB, nullable=False, server_default=FetchedValue())
    )

# The Agent kernel owns its category scope and composite identity constraints.
import pdos_next.agent_kernel.models  # noqa: E402,F401
import pdos_next.agent_kernel.session_presentation_models  # noqa: E402,F401

# Tenant model metadata is part of the actual shared schema; credentials stay in host ports.
import pdos_next.model_configuration.persistence  # noqa: E402,F401

# M3 is part of the active schema after its frozen candidate migration.
Base.metadata.tables["definition_revisions"].append_constraint(
    UniqueConstraint("tenant_id", "category_id", "id", name="definition_category_identity")
)
import pdos_next.domain.preproject.category_models  # noqa: E402,F401
import pdos_next.domain.preproject.category_creation_models  # noqa: E402,F401
import pdos_next.domain.preproject.evidence_models  # noqa: E402,F401
import pdos_next.domain.products.platform_models  # noqa: E402,F401
import pdos_next.domain.manufacturing_baseline.publication_models  # noqa: E402,F401

import pdos_next.domain.manufacturing_trials.native_models  # noqa: E402,F401
import pdos_next.domain.release.models  # noqa: E402,F401

from pdos_next.domain.release import policy_models as _release_policy_models  # noqa: F401, E402

import pdos_next.domain.external_handoff.models  # noqa: E402,F401

from pdos_next.domain.release_exceptions.models import (  # noqa: E402,F401
    ReleaseExceptionDecision,
    ReleaseExceptionCurrent,
)

from pdos_next.domain.knowledge.models import (  # noqa: E402,F401
    ApplicabilityAssessment,
    DesignRuleCurrent,
    DesignRuleVersion,
    KnowledgeCandidateCurrent,
    KnowledgeCandidateVersion,
)
from pdos_next.domain.work_management.models import (  # noqa: E402,F401
    ProjectStatusUpdate,
    WorkTaskVersion,
    WorkTaskCurrent,
    WorkCommitmentVersion,
    WorkCommitmentCurrent,
)

import pdos_next.domain.automations.models  # noqa: E402,F401

import pdos_next.domain.automations.service_models  # noqa: E402,F401

import pdos_next.domain.work_fulfillment.models  # noqa: E402,F401

import pdos_next.domain.external_wait.models  # noqa: E402,F401
import pdos_next.domain.project_risk.models  # noqa: E402,F401

from pdos_next.domain.field_feedback.models import (  # noqa: E402,F401
    FieldFeedbackVersion, FieldFeedbackCurrent, FieldResponseRecord,
)
