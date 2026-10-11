"""Keep direct T1 preview material immutable while permitting its consumption."""

from alembic import op

from migrations.schema_s0_0728 import SCHEMA_SQL

revision = "s0_0728"
down_revision = "s0_0727"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("LOCK TABLE public.confirmations IN ACCESS EXCLUSIVE MODE")
    for statement in SCHEMA_SQL:
        op.execute(statement)


def downgrade():
    op.execute("LOCK TABLE public.confirmations IN ACCESS EXCLUSIVE MODE")
    op.execute("DROP TRIGGER direct_confirmation_immutable ON public.confirmations")
    op.execute("DROP FUNCTION public.protect_direct_confirmation()")
