"""Use run -> call -> wallet lock order for failure cost records and cancellation."""

from alembic import op

revision = "s0_0710"
down_revision = "s0_0709"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE OR REPLACE FUNCTION kernel_record_cost(
      rid uuid,cid uuid,inp integer,outp integer,cost integer)
      RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
      DECLARE r agent_runs; c agent_tool_calls;
      BEGIN
        SELECT * INTO r FROM agent_runs WHERE id=rid
          AND tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid
          AND writer_id=scope_actor() AND requester_id=scope_requester()
          AND category_id IS NOT DISTINCT FROM
            NULLIF(current_setting('pdos.category_id',true),'')::uuid FOR UPDATE;
        IF NOT FOUND THEN RETURN; END IF;
        SELECT * INTO c FROM agent_tool_calls WHERE id=cid AND run_id=rid
          AND tenant_id=r.tenant_id FOR UPDATE;
        IF NOT FOUND OR c.state<>'started' THEN RETURN; END IF;
        IF inp<0 OR inp>c.input_token_reservation OR outp<0 OR outp>c.output_token_reservation
          OR cost<0 OR cost>c.cost_reserved_micro_usd
          THEN RAISE EXCEPTION 'Cost usage exceeds reservation'; END IF;
        UPDATE agent_tool_calls SET actual_input_tokens=inp,actual_output_tokens=outp,
          cost_charged_micro_usd=cost,cost_state='actual' WHERE id=c.id;
      END $$""")


def downgrade():
    op.execute("""CREATE OR REPLACE FUNCTION kernel_record_cost(
      rid uuid,cid uuid,inp integer,outp integer,cost integer)
      RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
      DECLARE c agent_tool_calls;
      BEGIN
        SELECT * INTO c FROM agent_tool_calls a WHERE a.id=cid AND a.run_id=rid
          AND EXISTS(SELECT 1 FROM agent_runs r WHERE r.id=rid AND r.tenant_id=a.tenant_id
            AND r.tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid
            AND r.writer_id=scope_actor() AND r.requester_id=scope_requester()
            AND r.category_id IS NOT DISTINCT FROM
              NULLIF(current_setting('pdos.category_id',true),'')::uuid) FOR UPDATE;
        IF c.id IS NULL OR c.state<>'started' THEN RETURN; END IF;
        IF inp<0 OR inp>c.input_token_reservation OR outp<0 OR outp>c.output_token_reservation
          OR cost<0 OR cost>c.cost_reserved_micro_usd
          THEN RAISE EXCEPTION 'Cost usage exceeds reservation'; END IF;
        UPDATE agent_tool_calls SET actual_input_tokens=inp,actual_output_tokens=outp,
          cost_charged_micro_usd=cost,cost_state='actual' WHERE id=c.id;
      END $$""")
