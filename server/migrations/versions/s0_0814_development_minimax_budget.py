"""Retain metered local development usage beyond historical wallet ceilings."""

from alembic import op

from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0814"
down_revision = "s0_0813"
branch_labels = None
depends_on = None

NAME = "agent_validation_budgets_check1"
NONNEGATIVE = (
    "calls>=0 AND held_micro_usd>=0 AND spent_micro_usd>=0 "
    "AND held_input_tokens>=0 AND used_input_tokens>=0 "
    "AND held_output_tokens>=0 AND used_output_tokens>=0"
)
CEILINGS = (
    "calls<=call_limit AND held_micro_usd+spent_micro_usd<=limit_micro_usd "
    "AND held_input_tokens+used_input_tokens<=input_token_limit "
    "AND held_output_tokens+used_output_tokens<=output_token_limit"
)


def upgrade():
    ordinary_owner()
    op.execute("ALTER TABLE public.agent_validation_budgets ADD COLUMN "
               "development_unlimited boolean NOT NULL DEFAULT false")
    op.execute(f"ALTER TABLE public.agent_validation_budgets DROP CONSTRAINT {NAME}")
    op.execute(f"ALTER TABLE public.agent_validation_budgets ADD CONSTRAINT {NAME} "
               f"CHECK ({NONNEGATIVE} AND (development_unlimited OR ({CEILINGS})))")
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    if op.get_bind().exec_driver_sql(
        "SELECT EXISTS(SELECT 1 FROM public.agent_validation_budgets WHERE development_unlimited)"
    ).scalar_one():
        raise RuntimeError("Development usage history exists; preserve it instead of downgrading")
    op.execute(f"ALTER TABLE public.agent_validation_budgets DROP CONSTRAINT {NAME}")
    op.execute(f"ALTER TABLE public.agent_validation_budgets ADD CONSTRAINT {NAME} "
               f"CHECK ({NONNEGATIVE} AND {CEILINGS})")
    op.execute("ALTER TABLE public.agent_validation_budgets DROP COLUMN development_unlimited")
    op.execute("SET LOCAL ROLE NONE")
