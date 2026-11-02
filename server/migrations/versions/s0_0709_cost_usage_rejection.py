"""Reject over-reservation fee records instead of silently treating them as free."""

from alembic import op

revision = "s0_0709"
down_revision = "s0_0708"
branch_labels = None
depends_on = None


def upgrade():
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


def downgrade():
    op.execute("""CREATE OR REPLACE FUNCTION kernel_record_cost(
      rid uuid,cid uuid,inp integer,outp integer,cost integer)
      RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
      BEGIN
        UPDATE agent_tool_calls c SET actual_input_tokens=inp,actual_output_tokens=outp,
          cost_charged_micro_usd=cost,cost_state='actual'
          WHERE c.id=cid AND c.run_id=rid AND c.state='started'
          AND inp>=0 AND inp<=c.input_token_reservation
          AND outp>=0 AND outp<=c.output_token_reservation
          AND cost>=0 AND cost<=c.cost_reserved_micro_usd AND EXISTS(SELECT 1 FROM agent_runs r
            WHERE r.id=rid AND r.tenant_id=c.tenant_id
            AND r.tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid
            AND r.writer_id=scope_actor() AND r.requester_id=scope_requester()
            AND r.category_id IS NOT DISTINCT FROM
              NULLIF(current_setting('pdos.category_id',true),'')::uuid);
      END $$""")
