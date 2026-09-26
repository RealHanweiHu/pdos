"""structured test runs with sample linkage and long-run states (vNext V1-B3)

Revision ID: 0040_test_runs
Revises: 0039_req_spec_traceability
Create Date: 2026-08-25 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0040_test_runs"
down_revision: str | Sequence[str] | None = "0039_req_spec_traceability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

QUALITY_SCHEMA = "cehub_quality"


def upgrade() -> None:
    op.create_table(
        "test_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("test_case_id", sa.Uuid(), nullable=False),
        sa.Column("sample_id", sa.Uuid(), nullable=True),
        sa.Column("operator_user_id", sa.Uuid(), nullable=True),
        sa.Column("evidence_document_id", sa.Uuid(), nullable=True),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default=sa.text("'planned'")
        ),
        sa.Column(
            "draft_state",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'confirmed'"),
        ),
        sa.Column(
            "conditions", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "metrics", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("equipment", sa.String(length=256), nullable=True),
        sa.Column("environment", sa.String(length=256), nullable=True),
        sa.Column("result_notes", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expected_completion_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'in_progress', 'passed', 'failed', 'aborted')",
            name="status_allowed",
        ),
        sa.CheckConstraint("draft_state IN ('draft', 'confirmed')", name="draft_state_allowed"),
        sa.CheckConstraint("run_number > 0", name="run_number_positive"),
        sa.CheckConstraint("jsonb_typeof(conditions) = 'object'", name="conditions_object"),
        sa.CheckConstraint("jsonb_typeof(metrics) = 'array'", name="metrics_array"),
        sa.CheckConstraint(
            "(status IN ('passed', 'failed', 'aborted') AND executed_at IS NOT NULL) "
            "OR (status IN ('planned', 'in_progress') AND executed_at IS NULL)",
            name="executed_at_consistent",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["cehub_core.tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["cehub_project.projects.tenant_id", "cehub_project.projects.id"],
            name="fk_test_runs_tenant_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "test_case_id"],
            ["cehub_quality.test_cases.tenant_id", "cehub_quality.test_cases.id"],
            name="fk_test_runs_tenant_test_case",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sample_id"],
            ["cehub_product.samples.tenant_id", "cehub_product.samples.id"],
            name="fk_test_runs_tenant_sample",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "operator_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_test_runs_tenant_operator",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "evidence_document_id"],
            ["cehub_project.documents.tenant_id", "cehub_project.documents.id"],
            name="fk_test_runs_tenant_evidence_document",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_test_runs_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id", "test_case_id", "run_number", name="uq_test_runs_case_run_number"
        ),
        schema=QUALITY_SCHEMA,
    )
    op.create_index(
        "ix_test_runs_tenant_project_case",
        "test_runs",
        ["tenant_id", "project_id", "test_case_id"],
        schema=QUALITY_SCHEMA,
    )


def downgrade() -> None:
    connection = op.get_bind()
    run_rows = connection.execute(
        sa.text(f"SELECT count(*) FROM {QUALITY_SCHEMA}.test_runs")
    ).scalar_one()
    if run_rows:
        raise RuntimeError("refusing lossy downgrade while test runs exist")
    op.drop_index("ix_test_runs_tenant_project_case", "test_runs", schema=QUALITY_SCHEMA)
    op.drop_table("test_runs", schema=QUALITY_SCHEMA)
