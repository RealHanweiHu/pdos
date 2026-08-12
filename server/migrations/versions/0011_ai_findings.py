"""add AI Finding review and apply state machine

Revision ID: 0011_ai_findings
Revises: 0010_agent_runtime
Create Date: 2026-08-11 23:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_ai_findings"
down_revision: str | Sequence[str] | None = "0010_agent_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AI_SCHEMA = "cehub_ai"
CORE_SCHEMA = "cehub_core"


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_agent_runs_tenant_project_id_agent",
        "agent_runs",
        ["tenant_id", "project_id", "id", "agent_key"],
        schema=AI_SCHEMA,
    )
    op.create_unique_constraint(
        "uq_model_invocations_tenant_id_id",
        "model_invocations",
        ["tenant_id", "id"],
        schema=AI_SCHEMA,
    )
    op.create_table(
        "findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("model_invocation_id", sa.Uuid(), nullable=False),
        sa.Column("agent_key", sa.String(length=64), nullable=False),
        sa.Column("finding_type", sa.String(length=64), nullable=False),
        sa.Column("origin_key", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'pending_review'"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "proposed_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "accepted_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "evidence_event_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("confidence_basis_points", sa.SmallInteger(), nullable=False),
        sa.Column("preflight_version", sa.String(length=64), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("applied_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_entity_type", sa.String(length=64), nullable=True),
        sa.Column("applied_entity_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "finding_type IN ('risk_suggestion')",
            name=op.f("ck_findings_type_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('pending_review', 'accepted', 'rejected', 'applied')",
            name=op.f("ck_findings_status_allowed"),
        ),
        sa.CheckConstraint(
            "btrim(origin_key) <> ''",
            name=op.f("ck_findings_origin_key_nonblank"),
        ),
        sa.CheckConstraint("btrim(title) <> ''", name=op.f("ck_findings_title_nonblank")),
        sa.CheckConstraint("btrim(summary) <> ''", name=op.f("ck_findings_summary_nonblank")),
        sa.CheckConstraint(
            "btrim(preflight_version) <> ''",
            name=op.f("ck_findings_preflight_version_nonblank"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(proposed_payload) = 'object'",
            name=op.f("ck_findings_proposed_payload_object"),
        ),
        sa.CheckConstraint(
            "accepted_payload IS NULL OR jsonb_typeof(accepted_payload) = 'object'",
            name=op.f("ck_findings_accepted_payload_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_event_ids) = 'array' "
            "AND jsonb_array_length(evidence_event_ids) > 0",
            name=op.f("ck_findings_evidence_event_ids_array"),
        ),
        sa.CheckConstraint(
            "confidence_basis_points BETWEEN 0 AND 10000",
            name=op.f("ck_findings_confidence_range"),
        ),
        sa.CheckConstraint(
            "(status = 'pending_review' AND reviewed_by_user_id IS NULL "
            "AND reviewed_at IS NULL AND accepted_payload IS NULL) OR "
            "(status = 'accepted' AND reviewed_by_user_id IS NOT NULL "
            "AND reviewed_at IS NOT NULL AND accepted_payload IS NOT NULL) OR "
            "(status = 'rejected' AND reviewed_by_user_id IS NOT NULL "
            "AND reviewed_at IS NOT NULL AND accepted_payload IS NULL) OR "
            "(status = 'applied' AND reviewed_by_user_id IS NOT NULL "
            "AND reviewed_at IS NOT NULL AND accepted_payload IS NOT NULL)",
            name=op.f("ck_findings_review_lifecycle_consistent"),
        ),
        sa.CheckConstraint(
            "(status <> 'applied' AND applied_by_user_id IS NULL AND applied_at IS NULL "
            "AND applied_entity_type IS NULL AND applied_entity_id IS NULL) OR "
            "(status = 'applied' AND applied_by_user_id IS NOT NULL AND applied_at IS NOT NULL "
            "AND applied_entity_type = 'risk' AND applied_entity_id IS NOT NULL "
            "AND reviewed_at < applied_at)",
            name=op.f("ck_findings_apply_lifecycle_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{CORE_SCHEMA}.tenants.id"],
            name=op.f("fk_findings_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "run_id", "agent_key"],
            [
                f"{AI_SCHEMA}.agent_runs.tenant_id",
                f"{AI_SCHEMA}.agent_runs.project_id",
                f"{AI_SCHEMA}.agent_runs.id",
                f"{AI_SCHEMA}.agent_runs.agent_key",
            ],
            name="fk_findings_tenant_project_run_agent",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "model_invocation_id"],
            [
                f"{AI_SCHEMA}.model_invocations.tenant_id",
                f"{AI_SCHEMA}.model_invocations.id",
            ],
            name="fk_findings_tenant_model_invocation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reviewed_by_user_id"],
            [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
            name="fk_findings_tenant_reviewer",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "applied_by_user_id"],
            [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
            name="fk_findings_tenant_applier",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_findings")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_findings_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "id",
            name="uq_findings_tenant_project_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "run_id",
            "origin_key",
            name="uq_findings_tenant_run_origin",
        ),
        schema=AI_SCHEMA,
    )
    op.create_index(
        "ix_findings_tenant_status_created",
        "findings",
        ["tenant_id", "status", "created_at", "id"],
        unique=False,
        schema=AI_SCHEMA,
    )
    op.create_index(
        "ix_findings_tenant_project_status",
        "findings",
        ["tenant_id", "project_id", "status", "id"],
        unique=False,
        schema=AI_SCHEMA,
    )
    op.create_table(
        "finding_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('created', 'accepted', 'rejected', 'applied')",
            name=op.f("ck_finding_actions_action_allowed"),
        ),
        sa.CheckConstraint(
            "(action = 'created' AND actor_user_id IS NULL AND from_status IS NULL "
            "AND to_status = 'pending_review') OR "
            "(action IN ('accepted', 'rejected') AND actor_user_id IS NOT NULL "
            "AND from_status = 'pending_review' AND to_status = action) OR "
            "(action = 'applied' AND actor_user_id IS NOT NULL "
            "AND from_status = 'accepted' AND to_status = 'applied')",
            name=op.f("ck_finding_actions_transition_consistent"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(detail) = 'object'",
            name=op.f("ck_finding_actions_detail_object"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{CORE_SCHEMA}.tenants.id"],
            name=op.f("fk_finding_actions_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "finding_id"],
            [
                f"{AI_SCHEMA}.findings.tenant_id",
                f"{AI_SCHEMA}.findings.project_id",
                f"{AI_SCHEMA}.findings.id",
            ],
            name="fk_finding_actions_tenant_project_finding",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_user_id"],
            [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
            name="fk_finding_actions_tenant_actor",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_finding_actions")),
        sa.UniqueConstraint(
            "tenant_id",
            "finding_id",
            "action",
            name="uq_finding_actions_tenant_finding_action",
        ),
        schema=AI_SCHEMA,
    )
    op.create_index(
        "ix_finding_actions_tenant_finding_created",
        "finding_actions",
        ["tenant_id", "finding_id", "created_at", "id"],
        unique=False,
        schema=AI_SCHEMA,
    )
    op.execute(
        sa.text(
            """
            CREATE FUNCTION cehub_ai.reject_finding_action_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $function$
            BEGIN
                RAISE EXCEPTION 'finding_actions is append-only';
            END
            $function$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER finding_actions_immutable
            BEFORE UPDATE OR DELETE ON cehub_ai.finding_actions
            FOR EACH ROW EXECUTE FUNCTION cehub_ai.reject_finding_action_mutation()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER finding_actions_immutable ON cehub_ai.finding_actions"))
    op.execute(sa.text("DROP FUNCTION cehub_ai.reject_finding_action_mutation()"))
    op.drop_index(
        "ix_finding_actions_tenant_finding_created",
        table_name="finding_actions",
        schema=AI_SCHEMA,
    )
    op.drop_table("finding_actions", schema=AI_SCHEMA)
    op.drop_index(
        "ix_findings_tenant_project_status",
        table_name="findings",
        schema=AI_SCHEMA,
    )
    op.drop_index(
        "ix_findings_tenant_status_created",
        table_name="findings",
        schema=AI_SCHEMA,
    )
    op.drop_table("findings", schema=AI_SCHEMA)
    op.drop_constraint(
        "uq_model_invocations_tenant_id_id",
        "model_invocations",
        type_="unique",
        schema=AI_SCHEMA,
    )
    op.drop_constraint(
        "uq_agent_runs_tenant_project_id_agent",
        "agent_runs",
        type_="unique",
        schema=AI_SCHEMA,
    )
