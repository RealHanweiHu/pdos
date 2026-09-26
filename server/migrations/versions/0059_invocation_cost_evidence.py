"""Preserve unknown model costs and immutable price provenance."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0059_invocation_cost_evidence"
down_revision: str | Sequence[str] | None = "0058_ai_test_plan_changes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COST_EVIDENCE = (
    "(cost_status = 'legacy_unverified' AND rate_card_snapshot IS NULL) OR "
    "(cost_status = 'unknown' AND normalized_cost_microusd IS NULL AND "
    "rate_card_snapshot IS NULL) OR (cost_status = 'not_invoked' AND "
    "normalized_cost_microusd IS NOT NULL AND normalized_cost_microusd = 0 AND "
    "structured_attempts = 0 AND status = 'budget_exceeded' AND rate_card_snapshot IS "
    "NULL) OR ((cost_status = 'priced' AND normalized_cost_microusd IS NOT NULL AND "
    "rate_card_snapshot IS NOT NULL AND jsonb_typeof(rate_card_snapshot) = 'object' "
    "AND rate_card_snapshot ?& ARRAY['provider', 'model', 'version', 'source', "
    "'currency', 'rate_unit', 'input_microusd_per_million_tokens', "
    "'output_microusd_per_million_tokens', 'calculation'] AND "
    "rate_card_snapshot->>'provider' = provider AND rate_card_snapshot->>'model' = "
    "model AND length(btrim(rate_card_snapshot->>'version')) > 0 AND "
    "length(btrim(rate_card_snapshot->>'source')) > 0 AND "
    "rate_card_snapshot->>'currency' = 'USD' AND rate_card_snapshot->>'rate_unit' = "
    "'microusd_per_million_tokens') IS TRUE)"
)


def upgrade() -> None:
    # Existing traces stay byte-for-byte intact; their amounts have no verified
    # rate provenance. The default also labels writes from older app versions.
    op.alter_column(
        "model_invocations",
        "normalized_cost_microusd",
        existing_type=sa.BigInteger(),
        nullable=True,
        server_default=None,
        schema="cehub_ai",
    )
    op.add_column(
        "model_invocations",
        sa.Column(
            "cost_status",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'legacy_unverified'"),
        ),
        schema="cehub_ai",
    )
    op.add_column(
        "model_invocations",
        sa.Column("rate_card_snapshot", postgresql.JSONB(none_as_null=True), nullable=True),
        schema="cehub_ai",
    )
    op.create_check_constraint(
        op.f("ck_model_invocations_cost_evidence_consistent"),
        "model_invocations",
        COST_EVIDENCE,
        schema="cehub_ai",
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM cehub_ai.model_invocations "
                "WHERE cost_status <> 'legacy_unverified' OR normalized_cost_microusd IS NULL)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("refusing downgrade: cost evidence or unknown amounts exist")
    op.drop_constraint(
        op.f("ck_model_invocations_cost_evidence_consistent"),
        "model_invocations",
        type_="check",
        schema="cehub_ai",
    )
    op.drop_column("model_invocations", "rate_card_snapshot", schema="cehub_ai")
    op.drop_column("model_invocations", "cost_status", schema="cehub_ai")
    op.alter_column(
        "model_invocations",
        "normalized_cost_microusd",
        existing_type=sa.BigInteger(),
        nullable=False,
        server_default=sa.text("0"),
        schema="cehub_ai",
    )
