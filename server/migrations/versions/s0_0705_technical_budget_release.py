"""Release reserved technical slots after cancellation or source/identity revocation."""

from alembic import op

revision = "s0_0705"
down_revision = "s0_0704"
branch_labels = None
depends_on = None


def upgrade():
    # This entry point can only reduce an existing reservation and record its outcome.
    # It exposes no result, changes no business facts, and never restores revoked scope.
    op.execute("""CREATE FUNCTION kernel_release_call(rid uuid,cid uuid,reason text,
        outcome_unknown boolean,charge integer,request_id text) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
        DECLARE r agent_runs%ROWTYPE; c agent_tool_calls%ROWTYPE; consumed integer;
        BEGIN
          IF charge<0 OR length(request_id)>200 OR reason NOT IN ('CANCELLED_RUN','FORBIDDEN_SCOPE',
            'SOURCE_UNAVAILABLE','EXTERNAL_OUTCOME_UNKNOWN','VERSION_CONFLICT',
            'RATE_LIMITED') THEN RAISE EXCEPTION 'Invalid technical release'; END IF;
          SELECT * INTO r FROM agent_runs WHERE id=rid
            AND tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid
            AND writer_id=scope_actor() AND requester_id=scope_requester()
            AND category_id IS NOT DISTINCT FROM
              NULLIF(current_setting('pdos.category_id',true),'')::uuid FOR UPDATE;
          IF NOT FOUND THEN RETURN false; END IF;
          SELECT * INTO c FROM agent_tool_calls WHERE id=cid AND run_id=rid
            AND tenant_id=r.tenant_id FOR UPDATE;
          IF NOT FOUND OR c.state<>'started' THEN RETURN false; END IF;
          consumed=CASE WHEN outcome_unknown THEN GREATEST(charge,c.reserved_tokens)
            ELSE charge END;
          UPDATE agent_runs SET held_tokens=GREATEST(0,held_tokens-c.reserved_tokens),
            used_tokens=used_tokens+consumed WHERE id=rid;
          UPDATE agent_tool_calls SET reserved_tokens=0,charged_tokens=charged_tokens+consumed,
            state=CASE WHEN outcome_unknown THEN 'unknown' ELSE 'failed' END,
            error_code=reason,provider_request_id=request_id WHERE id=cid;
          RETURN true;
        END $$""")
    op.execute("REVOKE ALL ON FUNCTION kernel_release_call(uuid,uuid,text,boolean,integer,text) FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch")
    op.execute("GRANT EXECUTE ON FUNCTION kernel_release_call(uuid,uuid,text,boolean,integer,text) TO pdos_next_app")


def downgrade():
    op.execute("DROP FUNCTION kernel_release_call(uuid,uuid,text,boolean,integer,text)")
