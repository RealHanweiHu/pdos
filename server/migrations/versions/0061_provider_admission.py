"""Allow a verified zero-call provider admission rejection without rewriting traces."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0061_provider_admission"
down_revision: str | Sequence[str] | None = "0060_budget_reservations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PREVIOUS_COST_EVIDENCE = (
    "(cost_status = 'legacy_unverified' AND rate_card_snapshot IS NULL) OR (cost_status = "
    "'unknown' AND normalized_cost_microusd IS NULL AND rate_card_snapshot IS NULL) OR "
    "(cost_status = 'not_invoked' AND normalized_cost_microusd IS NOT NULL AND "
    "normalized_cost_microusd = 0 AND structured_attempts = 0 AND status = "
    "'budget_exceeded' AND rate_card_snapshot IS NULL) OR ((cost_status = 'priced' AND "
    "normalized_cost_microusd IS NOT NULL AND rate_card_snapshot IS NOT NULL AND "
    "jsonb_typeof(rate_card_snapshot) = 'object' AND rate_card_snapshot ?& "
    "ARRAY['provider', 'model', 'version', 'source', 'currency', 'rate_unit', "
    "'input_microusd_per_million_tokens', 'output_microusd_per_million_tokens', "
    "'calculation'] AND rate_card_snapshot->>'provider' = provider AND "
    "rate_card_snapshot->>'model' = model AND "
    "length(btrim(rate_card_snapshot->>'version')) > 0 AND "
    "length(btrim(rate_card_snapshot->>'source')) > 0 AND rate_card_snapshot->>'currency' "
    "= 'USD' AND rate_card_snapshot->>'rate_unit' = 'microusd_per_million_tokens') IS "
    "TRUE)"
)
ADMISSION_EVIDENCE = (
    "((cost_status = 'not_invoked' AND normalized_cost_microusd = 0 AND "
    "structured_attempts = 0 AND status = 'provider_error' AND error_code = "
    "'PROVIDER_OUTPUT_LIMIT_UNCONFIGURED' AND input_tokens = 0 AND output_tokens = 0 AND "
    "cache_read_tokens = 0 AND cache_creation_tokens = 0 AND rate_card_snapshot IS NULL) "
    "IS TRUE)"
)


def replace_constraint(condition: str) -> None:
    op.drop_constraint(
        op.f("ck_model_invocations_cost_evidence_consistent"),
        "model_invocations",
        type_="check",
        schema="cehub_ai",
    )
    op.create_check_constraint(
        op.f("ck_model_invocations_cost_evidence_consistent"),
        "model_invocations",
        condition,
        schema="cehub_ai",
    )


def upgrade() -> None:
    replace_constraint(f"({PREVIOUS_COST_EVIDENCE}) OR {ADMISSION_EVIDENCE}")


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM cehub_ai.model_invocations "
                "WHERE cost_status = 'not_invoked' AND status = 'provider_error')"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("refusing downgrade: provider admission evidence exists")
    replace_constraint(PREVIOUS_COST_EVIDENCE)
