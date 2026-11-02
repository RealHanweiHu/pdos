"""Settle model cost in the original call transition, retaining terminal immutability."""

from alembic import op

revision = "s0_0708"
down_revision = "s0_0707"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DROP TRIGGER kernel_cost_settled ON agent_tool_calls")
    op.execute("""CREATE OR REPLACE FUNCTION kernel_cost_settled() RETURNS trigger
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
      DECLARE bid uuid; charge integer; inp integer; outp integer;
      BEGIN
        IF NEW.cost_pricing IS DISTINCT FROM OLD.cost_pricing
          OR NEW.input_token_reservation<>OLD.input_token_reservation
          OR NEW.output_token_reservation<>OLD.output_token_reservation
          THEN RAISE EXCEPTION 'Cost reservation immutable'; END IF;
        IF OLD.state='started' AND NEW.state<>'started' AND OLD.cost_pricing<>'{}'::jsonb THEN
          SELECT validation_budget_id INTO bid FROM agent_runs
            WHERE id=NEW.run_id AND tenant_id=NEW.tenant_id;
          IF bid IS NULL THEN RAISE EXCEPTION 'Missing validation cost budget'; END IF;
          IF NEW.cost_charged_micro_usd<0 OR NEW.cost_charged_micro_usd>OLD.cost_reserved_micro_usd
            OR NEW.actual_input_tokens<0 OR NEW.actual_input_tokens>OLD.input_token_reservation
            OR NEW.actual_output_tokens<0 OR NEW.actual_output_tokens>OLD.output_token_reservation
            THEN RAISE EXCEPTION 'Cost usage exceeds reservation'; END IF;
          charge=CASE WHEN NEW.state='unknown' THEN OLD.cost_reserved_micro_usd
            ELSE NEW.cost_charged_micro_usd END;
          inp=CASE WHEN NEW.state='unknown' THEN OLD.input_token_reservation ELSE NEW.actual_input_tokens END;
          outp=CASE WHEN NEW.state='unknown' THEN OLD.output_token_reservation ELSE NEW.actual_output_tokens END;
          UPDATE agent_validation_budgets SET held_micro_usd=held_micro_usd-OLD.cost_reserved_micro_usd,
            spent_micro_usd=spent_micro_usd+charge,held_input_tokens=held_input_tokens-OLD.input_token_reservation,
            used_input_tokens=used_input_tokens+inp,held_output_tokens=held_output_tokens-OLD.output_token_reservation,
            used_output_tokens=used_output_tokens+outp WHERE id=bid AND tenant_id=NEW.tenant_id;
          IF NOT FOUND THEN RAISE EXCEPTION 'Missing validation cost budget'; END IF;
          NEW.cost_reserved_micro_usd=0;
          NEW.cost_charged_micro_usd=charge;
          NEW.cost_state=CASE WHEN NEW.state='unknown' THEN 'estimated_unknown'
            WHEN NEW.cost_state='actual' THEN 'actual' ELSE 'known_zero' END;
          NEW.actual_input_tokens=inp;
          NEW.actual_output_tokens=outp;
        END IF;
        RETURN NEW;
      END $$""")
    op.execute("""CREATE TRIGGER kernel_cost_settled BEFORE UPDATE ON agent_tool_calls
      FOR EACH ROW EXECUTE FUNCTION kernel_cost_settled()""")


def downgrade():
    # Restore the installed predecessor exactly; a further downgrade removes its meter.
    import importlib

    prior = importlib.import_module("migrations.versions.s0_0707_validation_cost_budget")
    statements = []

    class Capture:
        @staticmethod
        def execute(statement):
            statements.append(statement)

    original = prior.op
    try:
        prior.op = Capture
        prior.upgrade()
    finally:
        prior.op = original
    op.execute("DROP TRIGGER kernel_cost_settled ON agent_tool_calls")
    function = next(s for s in statements if s.startswith("CREATE FUNCTION kernel_cost_settled()"))
    op.execute(function.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))
    op.execute("""CREATE TRIGGER kernel_cost_settled AFTER UPDATE ON agent_tool_calls
      FOR EACH ROW EXECUTE FUNCTION kernel_cost_settled()""")
