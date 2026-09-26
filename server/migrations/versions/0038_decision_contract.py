"""decision first-class contract: context, options, trade-offs, follow-up (vNext V1-B4)

Revision ID: 0038_decision_contract
Revises: 0037_reminder_dm_operation
Create Date: 2026-08-25 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038_decision_contract"
down_revision: str | Sequence[str] | None = "0037_reminder_dm_operation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROJECT_SCHEMA = "cehub_project"
ALLOWED_KINDS = (
    "requirement_to_development_case",
    "gate_review",
    "ecr_approval",
    "ecn_effectivity",
    "technical_choice",
    "supplier_choice",
    "process_decision",
    "debate_brief",
    "rebaseline",
    "definition_release",
    "ccr_response",
)


def upgrade() -> None:
    connection = op.get_bind()
    stray_kinds = (
        connection.execute(
            sa.text(
                f"SELECT DISTINCT decision_kind FROM {PROJECT_SCHEMA}.decisions "
                "WHERE decision_kind NOT IN :allowed"
            ).bindparams(sa.bindparam("allowed", expanding=True)),
            {"allowed": list(ALLOWED_KINDS)},
        )
        .scalars()
        .all()
    )
    if stray_kinds:
        raise RuntimeError(
            f"cannot freeze decision_kind: unknown existing values {sorted(stray_kinds)}"
        )

    op.add_column(
        "decisions", sa.Column("owner_user_id", sa.Uuid(), nullable=True), schema=PROJECT_SCHEMA
    )
    op.add_column(
        "decisions", sa.Column("approver_user_id", sa.Uuid(), nullable=True), schema=PROJECT_SCHEMA
    )
    op.add_column(
        "decisions", sa.Column("issue_id", sa.Uuid(), nullable=True), schema=PROJECT_SCHEMA
    )
    op.add_column(
        "decisions", sa.Column("context", sa.Text(), nullable=True), schema=PROJECT_SCHEMA
    )
    op.add_column(
        "decisions",
        sa.Column(
            "options",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        schema=PROJECT_SCHEMA,
    )
    op.add_column(
        "decisions", sa.Column("trade_offs", sa.Text(), nullable=True), schema=PROJECT_SCHEMA
    )
    op.add_column(
        "decisions", sa.Column("consequence", sa.Text(), nullable=True), schema=PROJECT_SCHEMA
    )
    op.add_column(
        "decisions",
        sa.Column(
            "evidence_refs",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        schema=PROJECT_SCHEMA,
    )
    op.add_column(
        "decisions",
        sa.Column(
            "follow_up_state",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'none'"),
        ),
        schema=PROJECT_SCHEMA,
    )
    op.add_column(
        "decisions", sa.Column("follow_up_note", sa.Text(), nullable=True), schema=PROJECT_SCHEMA
    )
    kind_list = ", ".join(f"'{kind}'" for kind in ALLOWED_KINDS)
    op.create_check_constraint(
        op.f("ck_decisions_decision_kind_allowed"),
        "decisions",
        f"decision_kind IN ({kind_list})",
        schema=PROJECT_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_decisions_issue_requires_project"),
        "decisions",
        "issue_id IS NULL OR project_id IS NOT NULL",
        schema=PROJECT_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_decisions_options_array"),
        "decisions",
        "jsonb_typeof(options) = 'array'",
        schema=PROJECT_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_decisions_evidence_refs_array"),
        "decisions",
        "jsonb_typeof(evidence_refs) = 'array'",
        schema=PROJECT_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_decisions_follow_up_state_allowed"),
        "decisions",
        "follow_up_state IN ('none', 'pending', 'completed')",
        schema=PROJECT_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_decisions_follow_up_note_consistent"),
        "decisions",
        "(follow_up_state = 'none') = (follow_up_note IS NULL)",
        schema=PROJECT_SCHEMA,
    )
    op.create_foreign_key(
        "fk_decisions_tenant_owner",
        "decisions",
        "users",
        ["tenant_id", "owner_user_id"],
        ["tenant_id", "id"],
        source_schema=PROJECT_SCHEMA,
        referent_schema="cehub_core",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_decisions_tenant_approver",
        "decisions",
        "users",
        ["tenant_id", "approver_user_id"],
        ["tenant_id", "id"],
        source_schema=PROJECT_SCHEMA,
        referent_schema="cehub_core",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_decisions_tenant_issue",
        "decisions",
        "issues",
        ["tenant_id", "issue_id"],
        ["tenant_id", "id"],
        source_schema=PROJECT_SCHEMA,
        referent_schema=PROJECT_SCHEMA,
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    connection = op.get_bind()
    enriched_rows = connection.execute(
        sa.text(
            f"SELECT count(*) FROM {PROJECT_SCHEMA}.decisions "
            "WHERE context IS NOT NULL OR trade_offs IS NOT NULL OR consequence IS NOT NULL "
            "OR owner_user_id IS NOT NULL OR approver_user_id IS NOT NULL "
            "OR issue_id IS NOT NULL OR follow_up_state <> 'none' "
            "OR options <> '[]'::jsonb OR evidence_refs <> '[]'::jsonb"
        )
    ).scalar_one()
    if enriched_rows:
        raise RuntimeError("refusing lossy downgrade while enriched decision rows exist")

    for name in (
        "fk_decisions_tenant_issue",
        "fk_decisions_tenant_approver",
        "fk_decisions_tenant_owner",
    ):
        op.drop_constraint(name, "decisions", schema=PROJECT_SCHEMA, type_="foreignkey")
    for name in (
        "ck_decisions_follow_up_note_consistent",
        "ck_decisions_follow_up_state_allowed",
        "ck_decisions_evidence_refs_array",
        "ck_decisions_options_array",
        "ck_decisions_issue_requires_project",
        "ck_decisions_decision_kind_allowed",
    ):
        op.drop_constraint(op.f(name), "decisions", schema=PROJECT_SCHEMA, type_="check")
    for column in (
        "follow_up_note",
        "follow_up_state",
        "evidence_refs",
        "consequence",
        "trade_offs",
        "options",
        "context",
        "issue_id",
        "approver_user_id",
        "owner_user_id",
    ):
        op.drop_column("decisions", column, schema=PROJECT_SCHEMA)
