"""Shared validation call/token/USD budgets with conservative unknown-cost settlement."""

from alembic import op

revision = "s0_0707"
down_revision = "s0_0706"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE agent_validation_budgets (
      id uuid PRIMARY KEY,tenant_id uuid NOT NULL,created_at timestamptz NOT NULL,
      requester_id uuid NOT NULL,active boolean NOT NULL,limit_micro_usd integer NOT NULL,
      input_token_limit integer NOT NULL,output_token_limit integer NOT NULL,call_limit integer NOT NULL,
      calls integer NOT NULL,held_micro_usd integer NOT NULL,spent_micro_usd integer NOT NULL,
      held_input_tokens integer NOT NULL,used_input_tokens integer NOT NULL,
      held_output_tokens integer NOT NULL,used_output_tokens integer NOT NULL,
      UNIQUE(tenant_id,id),FOREIGN KEY(tenant_id,requester_id) REFERENCES principals(tenant_id,id),
      CHECK(limit_micro_usd>=0 AND input_token_limit>0 AND output_token_limit>0 AND call_limit>0),
      CHECK(calls>=0 AND calls<=call_limit AND held_micro_usd>=0 AND spent_micro_usd>=0
        AND held_micro_usd+spent_micro_usd<=limit_micro_usd AND held_input_tokens>=0
        AND used_input_tokens>=0 AND held_input_tokens+used_input_tokens<=input_token_limit
        AND held_output_tokens>=0 AND used_output_tokens>=0
        AND held_output_tokens+used_output_tokens<=output_token_limit))""")
    op.execute(
        "CREATE INDEX ix_agent_validation_budgets_tenant_id ON agent_validation_budgets(tenant_id)"
    )
    op.execute("ALTER TABLE agent_validation_budgets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agent_validation_budgets FORCE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY budget_read ON agent_validation_budgets FOR SELECT USING (
      tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid
      AND requester_id=scope_requester())""")
    op.execute("""CREATE POLICY budget_provision ON agent_validation_budgets FOR INSERT WITH CHECK (
      tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid
      AND requester_id=scope_requester() AND kernel_admin_authorized())""")
    op.execute("""CREATE POLICY budget_settle ON agent_validation_budgets FOR UPDATE USING (
      tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid
      AND requester_id=scope_requester()) WITH CHECK(requester_id=scope_requester())""")
    op.execute(
        "REVOKE ALL ON agent_validation_budgets FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch"
    )
    op.execute("GRANT SELECT,INSERT,UPDATE ON agent_validation_budgets TO pdos_next_app")
    op.execute("ALTER TABLE agent_runs ADD COLUMN validation_budget_id uuid")
    op.execute("""ALTER TABLE agent_runs ADD FOREIGN KEY(tenant_id,validation_budget_id)
      REFERENCES agent_validation_budgets(tenant_id,id)""")
    for name, kind, default in [
        ("cost_pricing", "jsonb", "'{}'::jsonb"),
        ("cost_state", "varchar(32)", "'unmetered'"),
        ("cost_reserved_micro_usd", "integer", "0"),
        ("cost_charged_micro_usd", "integer", "0"),
        ("input_token_reservation", "integer", "0"),
        ("output_token_reservation", "integer", "0"),
        ("actual_input_tokens", "integer", "0"),
        ("actual_output_tokens", "integer", "0"),
    ]:
        op.execute(
            f"ALTER TABLE agent_tool_calls ADD COLUMN {name} {kind} NOT NULL DEFAULT {default}"
        )
        op.execute(f"ALTER TABLE agent_tool_calls ALTER COLUMN {name} DROP DEFAULT")
    op.execute("""CREATE FUNCTION kernel_cost_identity() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_OP='UPDATE' AND (NEW.validation_budget_id IS DISTINCT FROM OLD.validation_budget_id)
          THEN RAISE EXCEPTION 'Budget binding immutable'; END IF;
        IF NEW.validation_budget_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM agent_validation_budgets b
          WHERE b.tenant_id=NEW.tenant_id AND b.id=NEW.validation_budget_id
          AND b.requester_id=NEW.requester_id)
          THEN RAISE EXCEPTION 'Budget identity invalid'; END IF;
        RETURN NEW;
      END $$""")
    op.execute("""CREATE TRIGGER kernel_cost_identity BEFORE INSERT OR UPDATE ON agent_runs
      FOR EACH ROW EXECUTE FUNCTION kernel_cost_identity()""")
    op.execute("""CREATE FUNCTION kernel_budget_guard() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF NEW.id<>OLD.id OR NEW.tenant_id<>OLD.tenant_id OR NEW.requester_id<>OLD.requester_id
          OR NEW.limit_micro_usd<>OLD.limit_micro_usd OR NEW.call_limit<>OLD.call_limit
          OR NEW.input_token_limit<>OLD.input_token_limit OR NEW.output_token_limit<>OLD.output_token_limit
          OR NEW.calls<OLD.calls OR NEW.spent_micro_usd<OLD.spent_micro_usd
          OR NEW.used_input_tokens<OLD.used_input_tokens OR NEW.used_output_tokens<OLD.used_output_tokens
          THEN RAISE EXCEPTION 'Validation budget immutable/monotonic'; END IF; RETURN NEW;
      END $$""")
    op.execute("""CREATE TRIGGER kernel_budget_guard BEFORE UPDATE ON agent_validation_budgets
      FOR EACH ROW EXECUTE FUNCTION kernel_budget_guard()""")
    op.execute("""CREATE FUNCTION kernel_cost_settled() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
      SET search_path=public,pg_temp AS $$ DECLARE bid uuid; charge integer; inp integer; outp integer;
      BEGIN
        IF OLD.state='started' AND NEW.state<>'started' AND OLD.cost_pricing<>'{}'::jsonb THEN
          SELECT validation_budget_id INTO bid FROM agent_runs WHERE id=NEW.run_id AND tenant_id=NEW.tenant_id;
          IF bid IS NULL THEN RAISE EXCEPTION 'Missing validation cost budget'; END IF;
          charge=CASE WHEN NEW.state='unknown' THEN OLD.cost_reserved_micro_usd ELSE NEW.cost_charged_micro_usd END;
          inp=CASE WHEN NEW.state='unknown' THEN OLD.input_token_reservation ELSE NEW.actual_input_tokens END;
          outp=CASE WHEN NEW.state='unknown' THEN OLD.output_token_reservation ELSE NEW.actual_output_tokens END;
          UPDATE agent_validation_budgets SET held_micro_usd=held_micro_usd-OLD.cost_reserved_micro_usd,
            spent_micro_usd=spent_micro_usd+charge,held_input_tokens=held_input_tokens-OLD.input_token_reservation,
            used_input_tokens=used_input_tokens+inp,held_output_tokens=held_output_tokens-OLD.output_token_reservation,
            used_output_tokens=used_output_tokens+outp WHERE id=bid AND tenant_id=NEW.tenant_id;
          UPDATE agent_tool_calls SET cost_reserved_micro_usd=0,cost_charged_micro_usd=charge,
            cost_state=CASE WHEN NEW.state='unknown' THEN 'estimated_unknown'
              WHEN NEW.cost_state='actual' THEN 'actual' ELSE 'known_zero' END,
            actual_input_tokens=inp,actual_output_tokens=outp WHERE id=NEW.id;
        END IF; RETURN NEW;
      END $$""")
    op.execute("""CREATE TRIGGER kernel_cost_settled AFTER UPDATE ON agent_tool_calls
      FOR EACH ROW EXECUTE FUNCTION kernel_cost_settled()""")
    op.execute("""CREATE FUNCTION kernel_record_cost(rid uuid,cid uuid,inp integer,outp integer,cost integer)
      RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
      BEGIN
        UPDATE agent_tool_calls c SET actual_input_tokens=inp,actual_output_tokens=outp,
          cost_charged_micro_usd=cost,cost_state='actual' WHERE c.id=cid AND c.run_id=rid AND c.state='started'
          AND inp>=0 AND inp<=c.input_token_reservation AND outp>=0 AND outp<=c.output_token_reservation
          AND cost>=0 AND cost<=c.cost_reserved_micro_usd AND EXISTS(SELECT 1 FROM agent_runs r
            WHERE r.id=rid AND r.tenant_id=c.tenant_id
            AND r.tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid
            AND r.writer_id=scope_actor() AND r.requester_id=scope_requester()
            AND r.category_id IS NOT DISTINCT FROM NULLIF(current_setting('pdos.category_id',true),'')::uuid);
      END $$""")
    for function in (
        "kernel_cost_identity()",
        "kernel_budget_guard()",
        "kernel_cost_settled()",
        "kernel_record_cost(uuid,uuid,integer,integer,integer)",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch"
        )
    op.execute(
        "GRANT EXECUTE ON FUNCTION kernel_record_cost(uuid,uuid,integer,integer,integer) TO pdos_next_app"
    )


def downgrade():
    op.execute("DROP FUNCTION kernel_record_cost(uuid,uuid,integer,integer,integer)")
    op.execute("DROP TRIGGER kernel_cost_settled ON agent_tool_calls")
    op.execute("DROP FUNCTION kernel_cost_settled()")
    op.execute("DROP TRIGGER kernel_cost_identity ON agent_runs")
    op.execute("DROP FUNCTION kernel_cost_identity()")
    op.execute("ALTER TABLE agent_runs DROP COLUMN validation_budget_id")
    for name in (
        "cost_pricing",
        "cost_state",
        "cost_reserved_micro_usd",
        "cost_charged_micro_usd",
        "input_token_reservation",
        "output_token_reservation",
        "actual_input_tokens",
        "actual_output_tokens",
    ):
        op.execute(f"ALTER TABLE agent_tool_calls DROP COLUMN {name}")
    op.execute("DROP TABLE agent_validation_budgets")
    op.execute("DROP FUNCTION kernel_budget_guard()")
