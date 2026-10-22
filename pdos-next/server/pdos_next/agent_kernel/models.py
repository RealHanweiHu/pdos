"""M2-owned metadata and work references; Agent role has no direct DML grants."""

from datetime import datetime
from uuid import UUID, uuid4

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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.clock import now
from pdos_next.models import Base

from .execution_schema import SHAPE


class KernelRow:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AgentSession(KernelRow, Base):
    __tablename__ = "agent_sessions"
    category_id: Mapped[UUID | None] = mapped_column(index=True)
    product_id: Mapped[UUID | None]
    proposal_id: Mapped[UUID | None]
    project_id: Mapped[UUID | None]
    owner_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint(
            "project_id IS NULL OR (category_id IS NOT NULL AND product_id IS NOT NULL)",
            name="kernel_session_project_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id"],
            ["projects.tenant_id", "projects.product_id", "projects.id"],
            name="kernel_session_project_fk",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"], ["categories.tenant_id", "categories.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "product_id"],
            ["products.tenant_id", "products.category_id", "products.id"],
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
    )


class AgentRun(KernelRow, Base):
    __tablename__ = "agent_runs"
    category_id: Mapped[UUID | None] = mapped_column(index=True)
    product_id: Mapped[UUID | None]
    proposal_id: Mapped[UUID | None]
    project_id: Mapped[UUID | None]
    session_id: Mapped[UUID]
    continued_from_id: Mapped[UUID | None]
    requester_id: Mapped[UUID]
    writer_id: Mapped[UUID]
    trigger: Mapped[str] = mapped_column(String(40))
    goal: Mapped[str] = mapped_column(Text)
    intent_key: Mapped[str] = mapped_column(String(160))
    intent_digest: Mapped[str] = mapped_column(String(64))
    cancel_epoch: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(32), default="queued")
    private_context: Mapped[bool] = mapped_column(Boolean, default=False)
    data_categories: Mapped[list] = mapped_column(JSONB, default=list)
    customer_identities: Mapped[list] = mapped_column(JSONB, default=list)
    versions: Mapped[dict] = mapped_column(JSONB, default=dict)
    read_sources: Mapped[list] = mapped_column(JSONB, default=list)
    token_limit: Mapped[int] = mapped_column(Integer, default=100000)
    validation_budget_id: Mapped[UUID | None]
    held_tokens: Mapped[int] = mapped_column(Integer, default=0)
    used_tokens: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(80))
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reverted_by: Mapped[UUID | None]
    revert_receipt_id: Mapped[UUID | None]
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint(
            "project_id IS NULL OR (category_id IS NOT NULL AND product_id IS NOT NULL)",
            name="kernel_run_project_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id"],
            ["projects.tenant_id", "projects.product_id", "projects.id"],
            name="kernel_run_project_fk",
        ),
        Index(
            "ix_kernel_project_runs", "tenant_id", "category_id", "product_id",
            "project_id", "requester_id",
        ),
        UniqueConstraint("tenant_id", "category_id", "id", name="uq_agent_runs_category_identity"),
        UniqueConstraint("tenant_id", "requester_id", "intent_key"),
        UniqueConstraint("tenant_id", "continued_from_id", name="uq_kernel_continuation"),
        ForeignKeyConstraint(
            ["tenant_id", "continued_from_id"], ["agent_runs.tenant_id", "agent_runs.id"],
            name="kernel_continuation_fk",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "session_id"], ["agent_sessions.tenant_id", "agent_sessions.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"], ["categories.tenant_id", "categories.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "product_id"],
            ["products.tenant_id", "products.category_id", "products.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "requester_id"], ["principals.tenant_id", "principals.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "writer_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "validation_budget_id"],
            ["agent_validation_budgets.tenant_id", "agent_validation_budgets.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reverted_by"], ["principals.tenant_id", "principals.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "revert_receipt_id"], ["action_receipts.tenant_id", "action_receipts.id"],
            name="kernel_revert_receipt_fk", use_alter=True,
        ),
    )


class AgentToolCall(KernelRow, Base):
    __tablename__ = "agent_tool_calls"
    run_id: Mapped[UUID]
    call_key: Mapped[str] = mapped_column(String(200))
    tool: Mapped[str] = mapped_column(String(160))
    input_digest: Mapped[str] = mapped_column(String(64))
    execution_binding: Mapped[dict] = mapped_column(
        JSONB, default=lambda: {"kind": "unbound"}
    )
    state: Mapped[str] = mapped_column(String(32), default="started")
    result: Mapped[dict | None] = mapped_column(JSONB)
    receipt_id: Mapped[UUID | None]
    error_code: Mapped[str | None] = mapped_column(String(80))
    reserved_tokens: Mapped[int] = mapped_column(Integer, default=0)
    charged_tokens: Mapped[int] = mapped_column(Integer, default=0)
    provider_request_id: Mapped[str | None] = mapped_column(String(200))
    cost_pricing: Mapped[dict] = mapped_column(JSONB, default=dict)
    cost_state: Mapped[str] = mapped_column(String(32), default="unmetered")
    cost_reserved_micro_usd: Mapped[int] = mapped_column(Integer, default=0)
    cost_charged_micro_usd: Mapped[int] = mapped_column(Integer, default=0)
    input_token_reservation: Mapped[int] = mapped_column(Integer, default=0)
    output_token_reservation: Mapped[int] = mapped_column(Integer, default=0)
    actual_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    actual_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (
        CheckConstraint(SHAPE, name="kernel_execution_binding_shape"),
        UniqueConstraint("tenant_id", "run_id", "call_key"),
        ForeignKeyConstraint(["tenant_id", "run_id"], ["agent_runs.tenant_id", "agent_runs.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"], ["action_receipts.tenant_id", "action_receipts.id"]
        ),
    )


class AgentEvent(KernelRow, Base):
    __tablename__ = "agent_run_events"
    run_id: Mapped[UUID]
    sequence: Mapped[int] = mapped_column(Integer)
    body: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("tenant_id", "run_id", "sequence"),
        ForeignKeyConstraint(["tenant_id", "run_id"], ["agent_runs.tenant_id", "agent_runs.id"]),
    )


class TenantAdministrator(KernelRow, Base):
    __tablename__ = "tenant_administrators"
    principal_id: Mapped[UUID]
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (
        UniqueConstraint("tenant_id", "principal_id"),
        ForeignKeyConstraint(
            ["tenant_id", "principal_id"], ["principals.tenant_id", "principals.id"]
        ),
    )


class ProviderDataAgreement(KernelRow, Base):
    __tablename__ = "provider_data_agreements"
    provider: Mapped[str] = mapped_column(String(160))
    revision: Mapped[int] = mapped_column(Integer)
    signed_on: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    data_categories: Mapped[list] = mapped_column(JSONB)
    retention_terms: Mapped[str] = mapped_column(Text)
    training_terms: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    registered_by: Mapped[UUID]
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    receipt_id: Mapped[UUID | None]
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", "revision"),
        ForeignKeyConstraint(
            ["tenant_id", "registered_by"], ["principals.tenant_id", "principals.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"], ["action_receipts.tenant_id", "action_receipts.id"]
        ),
    )


class TenantSkillEnablement(KernelRow, Base):
    __tablename__ = "tenant_skill_enablements"
    skill_key: Mapped[str] = mapped_column(String(160))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    pilot: Mapped[bool] = mapped_column(Boolean, default=False)
    qualified_skill_version: Mapped[str | None] = mapped_column(String(160))
    qualified_model_version: Mapped[str | None] = mapped_column(String(200))
    review_case_refs: Mapped[list] = mapped_column(JSONB, default=list)
    reviewed_by: Mapped[UUID | None]
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    qualification_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    qualified_skill_digest: Mapped[str | None] = mapped_column(String(64))
    qualified_tool_digest: Mapped[str | None] = mapped_column(String(64))
    qualified_model_digest: Mapped[str | None] = mapped_column(String(64))
    qualification_id: Mapped[UUID | None]
    quality_paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    quality_paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quality_review_id: Mapped[UUID | None]
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    receipt_id: Mapped[UUID | None]
    __table_args__ = (
        UniqueConstraint("tenant_id", "skill_key"),
        ForeignKeyConstraint(
            ["tenant_id", "qualification_id"],
            ["agent_skill_qualifications.tenant_id", "agent_skill_qualifications.id"],
            name="skill_qualification_fk",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["tenant_id", "quality_review_id"],
            ["agent_skill_review_batches.tenant_id", "agent_skill_review_batches.id"],
            name="skill_quality_review_fk",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"],
            ["action_receipts.tenant_id", "action_receipts.id"],
            name="skill_enablement_receipt_fk",
            deferrable=True,
            initially="DEFERRED",
        ),
    )


class McpConnector(KernelRow, Base):
    __tablename__ = "mcp_connectors"
    key: Mapped[str] = mapped_column(String(160))
    endpoint: Mapped[str] = mapped_column(String(1000))
    secret_ref: Mapped[str] = mapped_column(String(200))
    admitted_by: Mapped[UUID]
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    tools: Mapped[dict] = mapped_column(JSONB)
    receipt_id: Mapped[UUID | None]
    control_record_id: Mapped[UUID | None]
    __table_args__ = (
        UniqueConstraint("tenant_id", "key"),
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"],
            ["action_receipts.tenant_id", "action_receipts.id"],
            name="mcp_connector_receipt_fk",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["tenant_id", "control_record_id"],
            ["mcp_control_records.tenant_id", "mcp_control_records.id"],
            name="mcp_connector_control_fk",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
    )


class McpToolGrant(KernelRow, Base):
    __tablename__ = "mcp_tool_grants"
    connector_id: Mapped[UUID]
    tool: Mapped[str] = mapped_column(String(160))
    skill_key: Mapped[str | None] = mapped_column(String(160))
    automation_rule_id: Mapped[UUID | None]
    explicit_external_write: Mapped[bool] = mapped_column(Boolean, default=False)
    authorized_by: Mapped[UUID]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    connector_binding_digest: Mapped[str | None] = mapped_column(String(64))
    receipt_id: Mapped[UUID | None]
    control_record_id: Mapped[UUID | None]
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "connector_id"],
            ["mcp_connectors.tenant_id", "mcp_connectors.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"],
            ["action_receipts.tenant_id", "action_receipts.id"],
            name="mcp_grant_receipt_fk",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["tenant_id", "control_record_id"],
            ["mcp_control_records.tenant_id", "mcp_control_records.id"],
            name="mcp_grant_control_fk",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        Index("ix_mcp_grants_connector", "tenant_id", "connector_id", "id"),
        Index(
            "ix_mcp_grants_current",
            "tenant_id",
            "connector_id",
            "tool",
            "expires_at",
            postgresql_where=text("active IS TRUE"),
        ),
    )


class PublicWebSnapshot(KernelRow, Base):
    __tablename__ = "public_web_snapshots"
    category_id: Mapped[UUID] = mapped_column(index=True)
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16), default="category")
    url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    markdown: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(160))
    credibility: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(32))
    registered_by_run_id: Mapped[UUID]
    receipt_id: Mapped[UUID]
    __table_args__ = (
        UniqueConstraint("tenant_id", "category_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"], ["categories.tenant_id", "categories.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "registered_by_run_id"], ["agent_runs.tenant_id", "agent_runs.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"],
            ["action_receipts.tenant_id", "action_receipts.id"],
            deferrable=True,
            initially="DEFERRED",
        ),
    )


class AgentInput(KernelRow, Base):
    __tablename__ = "agent_run_inputs"
    run_id: Mapped[UUID]
    requester_id: Mapped[UUID]
    idempotency_key: Mapped[str] = mapped_column(String(160))
    payload_digest: Mapped[str] = mapped_column(String(64))
    answers: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("tenant_id", "run_id", "idempotency_key"),
        ForeignKeyConstraint(["tenant_id", "run_id"], ["agent_runs.tenant_id", "agent_runs.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "requester_id"], ["principals.tenant_id", "principals.id"]
        ),
    )


class ValidationBudget(KernelRow, Base):
    __tablename__ = "agent_validation_budgets"
    requester_id: Mapped[UUID]
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    limit_micro_usd: Mapped[int] = mapped_column(Integer)
    input_token_limit: Mapped[int] = mapped_column(Integer)
    output_token_limit: Mapped[int] = mapped_column(Integer)
    call_limit: Mapped[int] = mapped_column(Integer)
    calls: Mapped[int] = mapped_column(Integer, default=0)
    held_micro_usd: Mapped[int] = mapped_column(Integer, default=0)
    spent_micro_usd: Mapped[int] = mapped_column(Integer, default=0)
    held_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    used_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    held_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    used_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    receipt_id: Mapped[UUID | None]
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "requester_id"], ["principals.tenant_id", "principals.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"],
            ["action_receipts.tenant_id", "action_receipts.id"],
            name="agent_budget_receipt_fk",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        Index("ix_agent_budget_control_revision", "tenant_id", "requester_id", "revision"),
        Index("ix_agent_budget_active", "tenant_id", "requester_id", "id",
              postgresql_where=text("active IS TRUE")),
    )


class TenantPilotAdmission(Base):
    __tablename__ = "tenant_pilot_admissions"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    approval_reference: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SkillReviewBatch(KernelRow, Base):
    __tablename__ = "agent_skill_review_batches"
    reviewed_by: Mapped[UUID]
    skill_key: Mapped[str] = mapped_column(String(160))
    skill_version: Mapped[str] = mapped_column(String(160))
    skill_digest: Mapped[str] = mapped_column(String(64))
    tool_digest: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(200))
    model_digest: Mapped[str] = mapped_column(String(64))
    model_label: Mapped[str] = mapped_column(String(200))
    cases: Mapped[list] = mapped_column(JSONB)
    receipt_id: Mapped[UUID]
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "reviewed_by"], ["principals.tenant_id", "principals.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"],
            ["action_receipts.tenant_id", "action_receipts.id"],
            name="skill_review_receipt_fk",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        Index(
            "ix_skill_reviews_owner", "tenant_id", "reviewed_by", "skill_key", "created_at", "id"
        ),
    )

    @property
    def revision(self):
        return 1

    @property
    def status(self):
        return "reviewed"


class SkillQualification(KernelRow, Base):
    __tablename__ = "agent_skill_qualifications"
    decided_by: Mapped[UUID]
    skill_key: Mapped[str] = mapped_column(String(160))
    decision: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(4000))
    after_snapshot: Mapped[dict] = mapped_column(JSONB)
    receipt_id: Mapped[UUID]
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "decided_by"], ["principals.tenant_id", "principals.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"],
            ["action_receipts.tenant_id", "action_receipts.id"],
            name="skill_decision_receipt_fk",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
    )

    @property
    def revision(self):
        return 1

    @property
    def status(self):
        return "qualified" if self.decision == "批准" else "revoked"


class McpControlRecord(KernelRow, Base):
    __tablename__ = "mcp_control_records"
    operation: Mapped[str] = mapped_column(String(80))
    subject_id: Mapped[UUID]
    subject_revision: Mapped[int] = mapped_column(Integer)
    decided_by: Mapped[UUID]
    after_snapshot: Mapped[dict] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(String(4000))
    receipt_id: Mapped[UUID]
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "decided_by"], ["principals.tenant_id", "principals.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"],
            ["action_receipts.tenant_id", "action_receipts.id"],
            name="mcp_control_receipt_fk",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        Index("ix_mcp_control_subject", "tenant_id", "subject_id", "created_at", "id"),
    )
