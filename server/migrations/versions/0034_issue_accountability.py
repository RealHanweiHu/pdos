"""issue accountability contract: type, verifier, closure criteria (vNext V1-A4)

Revision ID: 0034_issue_accountability
Revises: 0033_expand_model_providers
Create Date: 2026-08-25 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034_issue_accountability"
down_revision: str | Sequence[str] | None = "0033_expand_model_providers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROJECT_SCHEMA = "cehub_project"


def upgrade() -> None:
    op.add_column(
        "issues",
        sa.Column("verifier_user_id", sa.Uuid(), nullable=True),
        schema=PROJECT_SCHEMA,
    )
    op.add_column(
        "issues",
        sa.Column(
            "issue_type",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'engineering'"),
        ),
        schema=PROJECT_SCHEMA,
    )
    op.add_column(
        "issues",
        sa.Column("closure_criteria", sa.Text(), nullable=True),
        schema=PROJECT_SCHEMA,
    )
    op.add_column(
        "issues",
        sa.Column("closure_evidence_ref", sa.Text(), nullable=True),
        schema=PROJECT_SCHEMA,
    )
    op.add_column(
        "issues",
        sa.Column(
            "reopen_count",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        schema=PROJECT_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_issues_issue_type_allowed"),
        "issues",
        "issue_type IN ('engineering', 'quality', 'supplier', 'test_failure', 'certification')",
        schema=PROJECT_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_issues_reopen_count_nonnegative"),
        "issues",
        "reopen_count >= 0",
        schema=PROJECT_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_issues_four_eyes_distinct"),
        "issues",
        "NOT (severity IN ('high', 'critical') AND owner_user_id IS NOT NULL "
        "AND verifier_user_id IS NOT NULL AND owner_user_id = verifier_user_id)",
        schema=PROJECT_SCHEMA,
    )
    op.create_foreign_key(
        "fk_issues_tenant_verifier",
        "issues",
        "users",
        ["tenant_id", "verifier_user_id"],
        ["tenant_id", "id"],
        source_schema=PROJECT_SCHEMA,
        referent_schema="cehub_core",
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    connection = op.get_bind()
    accountable_rows = connection.execute(
        sa.text(
            f"SELECT count(*) FROM {PROJECT_SCHEMA}.issues "
            "WHERE verifier_user_id IS NOT NULL OR closure_criteria IS NOT NULL "
            "OR closure_evidence_ref IS NOT NULL OR reopen_count > 0 "
            "OR issue_type <> 'engineering'"
        )
    ).scalar_one()
    if accountable_rows:
        raise RuntimeError("refusing lossy downgrade while issue accountability data exists")

    op.drop_constraint(
        "fk_issues_tenant_verifier", "issues", schema=PROJECT_SCHEMA, type_="foreignkey"
    )
    op.drop_constraint(
        op.f("ck_issues_four_eyes_distinct"), "issues", schema=PROJECT_SCHEMA, type_="check"
    )
    op.drop_constraint(
        op.f("ck_issues_reopen_count_nonnegative"),
        "issues",
        schema=PROJECT_SCHEMA,
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_issues_issue_type_allowed"), "issues", schema=PROJECT_SCHEMA, type_="check"
    )
    op.drop_column("issues", "reopen_count", schema=PROJECT_SCHEMA)
    op.drop_column("issues", "closure_evidence_ref", schema=PROJECT_SCHEMA)
    op.drop_column("issues", "closure_criteria", schema=PROJECT_SCHEMA)
    op.drop_column("issues", "issue_type", schema=PROJECT_SCHEMA)
    op.drop_column("issues", "verifier_user_id", schema=PROJECT_SCHEMA)
