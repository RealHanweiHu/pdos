"""Retain model request bindings and settlement evidence in the append-only ledger."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0062_model_budget_evidence"
down_revision: str | Sequence[str] | None = "0061_provider_admission"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("model_invocations", sa.Column("budget_call_id", sa.Uuid()), schema="cehub_ai")
    for name in ("request_binding", "usage_evidence"):
        op.add_column(
            "budget_journal",
            sa.Column(name, postgresql.JSONB(none_as_null=True)),
            schema="cehub_ai",
        )
    op.create_check_constraint(
        op.f("ck_budget_journal_model_evidence_shape"),
        "budget_journal",
        "(request_binding IS NULL OR jsonb_typeof(request_binding) = 'object') AND "
        "(usage_evidence IS NULL OR (jsonb_typeof(usage_evidence) = 'object' "
        "AND reservation_status = 'settled'))",
        schema="cehub_ai",
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM cehub_ai.budget_journal "
                "WHERE request_binding IS NOT NULL OR usage_evidence IS NOT NULL) OR "
                "EXISTS (SELECT 1 FROM cehub_ai.model_invocations WHERE budget_call_id IS NOT NULL)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("refusing downgrade: model budget evidence exists")
    op.drop_constraint(
        op.f("ck_budget_journal_model_evidence_shape"),
        "budget_journal",
        type_="check",
        schema="cehub_ai",
    )
    for name in ("request_binding", "usage_evidence"):
        op.drop_column("budget_journal", name, schema="cehub_ai")
    op.drop_column("model_invocations", "budget_call_id", schema="cehub_ai")
