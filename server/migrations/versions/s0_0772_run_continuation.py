"""Link a new human-requested turn to its actual previous Run."""

import sqlalchemy as sa
from alembic import op

revision = "s0_0772"
down_revision = "s0_0771"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agent_runs", sa.Column("continued_from_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "kernel_continuation_fk",
        "agent_runs",
        "agent_runs",
        ["tenant_id", "continued_from_id"],
        ["tenant_id", "id"],
    )
    op.create_unique_constraint(
        "uq_kernel_continuation", "agent_runs", ["tenant_id", "continued_from_id"]
    )
    op.execute("""CREATE FUNCTION kernel_continuation_guard() RETURNS trigger
    LANGUAGE plpgsql AS $$ DECLARE p agent_runs; BEGIN
      IF TG_OP='UPDATE' THEN
        IF NEW.continued_from_id IS DISTINCT FROM OLD.continued_from_id THEN
          RAISE EXCEPTION 'Continuation binding immutable' USING ERRCODE='23514';
        END IF;
      ELSIF NEW.continued_from_id IS NOT NULL THEN
        SELECT * INTO p FROM agent_runs WHERE tenant_id=NEW.tenant_id
          AND id=NEW.continued_from_id FOR UPDATE;
        IF p.id IS NULL OR p.id=NEW.id OR p.requester_id<>NEW.requester_id
          OR p.session_id<>NEW.session_id OR p.category_id IS DISTINCT FROM NEW.category_id
          OR p.product_id IS DISTINCT FROM NEW.product_id
          OR p.proposal_id IS DISTINCT FROM NEW.proposal_id OR p.reverted_at IS NOT NULL
          OR p.state NOT IN ('completed','partial','failed','cancelled') THEN
          RAISE EXCEPTION 'Continuation requires same actual completed scope'
            USING ERRCODE='23514';
        END IF;
      END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER kernel_continuation BEFORE INSERT OR UPDATE ON agent_runs "
        "FOR EACH ROW EXECUTE FUNCTION kernel_continuation_guard()"
    )


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM agent_runs
        WHERE continued_from_id IS NOT NULL) THEN
      RAISE EXCEPTION 'Continuation history requires s0_0772'; END IF; END $$""")
    op.execute("DROP TRIGGER kernel_continuation ON agent_runs")
    op.execute("DROP FUNCTION kernel_continuation_guard()")
    op.drop_constraint("uq_kernel_continuation", "agent_runs", type_="unique")
    op.drop_constraint("kernel_continuation_fk", "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "continued_from_id")
