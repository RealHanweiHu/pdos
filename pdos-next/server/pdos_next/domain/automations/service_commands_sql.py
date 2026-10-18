"""Narrow host start/stop commands and reciprocal service Run proof declarations.

No connection, migration execution, model call or human-context impersonation.
The root migration installs the service tables and union-based Current guards.
"""

# ruff: noqa: E501 -- preserve complete PostgreSQL predicates.

import re

STOP_REASONS = (
    "GOAL_REACHED",
    "SCOPE_INVALID",
    "EXPIRED",
    "SUPERSEDED",
    "MAX_RUNS",
    "MODEL_BUDGET_EXHAUSTED",
)
REASONS_SQL = "(" + ",".join(repr(reason) for reason in STOP_REASONS) + ")"


def _function(name, args, body, returns):
    return f"CREATE FUNCTION public.{name}({args}) RETURNS {returns}\nLANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $automation_commands$\n{body.rstrip()};\n$automation_commands$"


STOP = r"""
DECLARE t uuid=nullif(current_setting('pdos.tenant_id',true),'')::uuid;
 g public.automation_service_grants; v public.automation_rule_versions; prior public.automation_service_attempts;
 chain_id uuid; attempt_id uuid; point timestamptz; origin_value jsonb; fingerprint text;
BEGIN
 IF stop_reason IS NULL OR stop_reason NOT IN __REASONS__ THEN
  RAISE EXCEPTION 'Unregistered service stop reason' USING ERRCODE='23514'; END IF;
 SELECT * INTO STRICT g FROM public.automation_service_grants WHERE tenant_id=t AND id=grant_id;
 IF NOT COALESCE(public.automation_service_identity(t,g.owner_id,g.writer_id),false)
  OR g.category_id IS DISTINCT FROM nullif(current_setting('pdos.category_id',true),'')::uuid THEN
  RAISE EXCEPTION 'Stop requires actual stored service identity' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM public.categories WHERE tenant_id=t AND id=g.category_id FOR UPDATE;
 PERFORM pg_advisory_xact_lock(hashtextextended('automation-service-stop:'||t::text||':'||g.id::text,0));
 SELECT * INTO prior FROM public.automation_service_attempts WHERE tenant_id=t AND service_grant_id=g.id AND trigger_key='lifecycle:stop';
 IF FOUND THEN
  IF prior.origin->>'kind' IS DISTINCT FROM 'lifecycle' OR prior.state<>'suppressed'
   OR prior.error_code NOT IN __REASONS__ OR prior.run_id IS NOT NULL OR prior.admitted_at IS NOT NULL THEN
   RAISE EXCEPTION 'Original service stop record is inconsistent' USING ERRCODE='23514'; END IF;
  RETURN prior.id;
 END IF;
 SELECT * INTO STRICT v FROM public.automation_rule_versions WHERE tenant_id=t AND id=g.published_version_id;
 point=clock_timestamp(); chain_id=gen_random_uuid(); attempt_id=gen_random_uuid();
 origin_value=jsonb_build_object('kind','lifecycle','reason',stop_reason,'grant_id',g.id,'published_version_id',v.id);
 fingerprint=encode(sha256(convert_to(g.id::text||':lifecycle:stop:'||stop_reason,'UTF8')),'hex');
 INSERT INTO public.automation_causal_chains(id,tenant_id,category_id,owner_id,root_grant_id,budget,max_depth,created_at)
  VALUES(chain_id,t,g.category_id,g.owner_id,g.id,v.spec->'budget',(v.spec->>'max_cascade_depth')::integer,point);
 INSERT INTO public.automation_service_attempts(id,tenant_id,category_id,owner_id,writer_id,rule_id,published_version_id,service_grant_id,chain_id,parent_run_id,depth,trigger_kind,trigger_key,origin,request_digest,state,error_code,run_id,admitted_at,due_at,created_at)
  VALUES(attempt_id,t,g.category_id,g.owner_id,g.writer_id,g.rule_id,g.published_version_id,g.id,chain_id,NULL,0,v.spec->>'trigger_kind','lifecycle:stop',origin_value,fingerprint,'queued',NULL,NULL,NULL,NULL,point);
 UPDATE public.automation_service_attempts SET state='suppressed',error_code=stop_reason WHERE tenant_id=t AND id=attempt_id;
 RETURN attempt_id;
END
""".replace("__REASONS__", REASONS_SQL)


START = r"""
DECLARE t uuid=nullif(current_setting('pdos.tenant_id',true),'')::uuid;
 a public.automation_service_attempts; g public.automation_service_grants; v public.automation_rule_versions;
 chain public.automation_causal_chains; cur public.automation_rule_currents; wallet public.agent_validation_budgets;
 product public.products; point timestamptz; reason text; private_value boolean=false;
 session_id uuid; new_run_id uuid; authority_count integer;
 rule_cost numeric; rule_input numeric; rule_output numeric; rule_calls bigint;
 chain_cost numeric; chain_input numeric; chain_output numeric; chain_calls bigint;
BEGIN
 SELECT * INTO STRICT a FROM public.automation_service_attempts WHERE tenant_id=t AND id=attempt_id;
 SELECT * INTO STRICT g FROM public.automation_service_grants WHERE tenant_id=t AND id=a.service_grant_id;
 IF NOT COALESCE(public.automation_service_identity(t,g.owner_id,g.writer_id),false)
  OR g.category_id IS DISTINCT FROM nullif(current_setting('pdos.category_id',true),'')::uuid
  OR ROW(a.category_id,a.owner_id,a.writer_id,a.rule_id,a.published_version_id) IS DISTINCT FROM ROW(g.category_id,g.owner_id,g.writer_id,g.rule_id,g.published_version_id) THEN
  RAISE EXCEPTION 'Start requires the actual fixed service identity' USING ERRCODE='42501'; END IF;
 -- The same lock order is used by lifecycle/configuration and chain reservation.
 PERFORM 1 FROM public.categories WHERE tenant_id=t AND id=g.category_id FOR UPDATE;
 PERFORM pg_advisory_xact_lock(hashtextextended('automation-chain:'||a.chain_id::text,0));
 SELECT * INTO STRICT chain FROM public.automation_causal_chains WHERE tenant_id=t AND id=a.chain_id FOR UPDATE;
 PERFORM pg_advisory_xact_lock(hashtextextended('automation-budget:'||t::text||':'||g.rule_id::text,0));
 SELECT * INTO STRICT cur FROM public.automation_rule_currents WHERE tenant_id=t AND rule_id=g.rule_id FOR UPDATE;
 SELECT * INTO STRICT a FROM public.automation_service_attempts WHERE tenant_id=t AND id=attempt_id FOR UPDATE;
 IF a.state='admitted' THEN PERFORM public.assert_automation_service_run(t,a.run_id); RETURN a.run_id; ELSIF a.state='suppressed' THEN RETURN NULL;
 ELSIF a.state<>'queued' THEN RAISE EXCEPTION 'Unknown service attempt state' USING ERRCODE='23514'; END IF;
 SELECT * INTO STRICT v FROM public.automation_rule_versions WHERE tenant_id=t AND id=g.published_version_id;
 point=clock_timestamp();
 SELECT x.error_code INTO reason FROM public.automation_service_attempts x WHERE x.tenant_id=t AND x.service_grant_id=g.id
  AND x.origin->>'kind'='lifecycle' AND x.state='suppressed' AND x.error_code IN __REASONS__ ORDER BY x.created_at,x.id LIMIT 1;
 IF reason IS NULL THEN
  IF cur.published_version_id IS DISTINCT FROM g.published_version_id OR cur.state<>'active' THEN reason='SUPERSEDED';
  ELSIF g.expires_at IS NOT NULL AND point>=g.expires_at THEN reason='EXPIRED';
  ELSIF NOT public.automation_service_grant_available(t,g.id,point) THEN reason='SCOPE_INVALID'; END IF;
 END IF;
 IF reason IS NOT NULL THEN
  UPDATE public.automation_service_attempts SET state='suppressed',error_code=reason WHERE tenant_id=t AND id=a.id;
  PERFORM public.automation_service_stop(g.id,reason); RETURN NULL;
 END IF;
 -- Lock current authority, then check expiry at this actual admission instant.
 PERFORM 1 FROM public.principals p WHERE p.tenant_id=t AND p.id IN (g.owner_id,g.writer_id) ORDER BY p.id FOR SHARE;
 PERFORM 1 FROM public.grants access WHERE access.tenant_id=t AND access.category_id=g.category_id AND access.principal_id IN (g.owner_id,g.writer_id) ORDER BY access.principal_id FOR SHARE;
 SELECT count(*) INTO authority_count FROM public.principals p JOIN public.grants access ON access.tenant_id=p.tenant_id AND access.principal_id=p.id
  WHERE p.tenant_id=t AND p.id IN (g.owner_id,g.writer_id) AND p.active AND access.category_id=g.category_id
   AND (access.expires_at IS NULL OR point<access.expires_at);
 IF authority_count<>2 THEN
  UPDATE public.automation_service_attempts SET state='suppressed',error_code='SCOPE_INVALID' WHERE tenant_id=t AND id=a.id;
  PERFORM public.automation_service_stop(g.id,'SCOPE_INVALID'); RETURN NULL;
 END IF;
 IF a.depth>chain.max_depth THEN
  UPDATE public.automation_service_attempts SET state='suppressed',error_code='CASCADE_DEPTH_EXCEEDED' WHERE tenant_id=t AND id=a.id; RETURN NULL;
 END IF;
 IF a.parent_run_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.automation_service_attempts parent
  WHERE parent.tenant_id=t AND parent.run_id=a.parent_run_id AND parent.state='admitted' AND parent.chain_id=a.chain_id AND parent.depth+1=a.depth) THEN
  RAISE EXCEPTION 'Service parent must be an actual admitted member of the same chain' USING ERRCODE='23514'; END IF;
 IF a.parent_run_id IS NOT NULL AND EXISTS(SELECT 1 FROM public.automation_service_attempts parent
  WHERE parent.tenant_id=t AND parent.run_id=a.parent_run_id AND parent.state='admitted' AND parent.rule_id=g.rule_id) THEN
  UPDATE public.automation_service_attempts SET state='suppressed',error_code='SELF_TRIGGERED' WHERE tenant_id=t AND id=a.id; RETURN NULL;
 END IF;
 IF cur.admitted_count>=(v.spec->>'max_runs')::integer THEN
  UPDATE public.automation_service_attempts SET state='suppressed',error_code='MAX_RUNS' WHERE tenant_id=t AND id=a.id;
  PERFORM public.automation_service_stop(g.id,'MAX_RUNS'); RETURN NULL;
 END IF;
 IF (a.due_at IS NOT NULL AND point<a.due_at)
  OR (cur.last_admitted_at IS NOT NULL AND point<cur.last_admitted_at+make_interval(secs=>(v.spec->>'cooldown_seconds')::integer)) THEN RETURN NULL; END IF;
 IF v.spec->>'product_id' IS NOT NULL THEN
  SELECT * INTO product FROM public.products p WHERE p.tenant_id=t AND p.category_id=g.category_id AND p.id=(v.spec->>'product_id')::uuid FOR SHARE;
  IF product.id IS NULL OR NOT(product.visibility='category' OR product.owner_id=g.owner_id OR EXISTS(
   SELECT 1 FROM public.object_audiences audience WHERE audience.tenant_id=t AND audience.category_id=g.category_id
    AND audience.object_type='products' AND audience.subject_id=product.id AND audience.owner_id=product.owner_id AND audience.principal_id=g.owner_id)) THEN
   UPDATE public.automation_service_attempts SET state='suppressed',error_code='SCOPE_INVALID' WHERE tenant_id=t AND id=a.id;
   PERFORM public.automation_service_stop(g.id,'SCOPE_INVALID'); RETURN NULL;
  END IF;
  private_value=product.visibility<>'category';
 END IF;
 SELECT * INTO wallet FROM public.agent_validation_budgets b WHERE b.tenant_id=t AND b.id=(v.spec->>'validation_budget_id')::uuid FOR UPDATE;
 IF wallet.id IS NULL OR wallet.requester_id<>g.owner_id OR NOT wallet.active THEN
  UPDATE public.automation_service_attempts SET state='suppressed',error_code='MODEL_BUDGET_EXHAUSTED' WHERE tenant_id=t AND id=a.id;
  PERFORM public.automation_service_stop(g.id,'MODEL_BUDGET_EXHAUSTED'); RETURN NULL;
 END IF;
 SELECT coalesce(sum(CASE WHEN call.cost_state='reserved' THEN call.cost_reserved_micro_usd ELSE call.cost_charged_micro_usd END),0),
  coalesce(sum(CASE WHEN call.cost_state='reserved' THEN call.input_token_reservation ELSE call.actual_input_tokens END),0),
  coalesce(sum(CASE WHEN call.cost_state='reserved' THEN call.output_token_reservation ELSE call.actual_output_tokens END),0),count(*)
  INTO rule_cost,rule_input,rule_output,rule_calls FROM public.agent_tool_calls call JOIN (
   SELECT service.run_id FROM public.automation_service_attempts service WHERE service.tenant_id=t AND service.rule_id=g.rule_id AND service.state='admitted'
   UNION SELECT manual.run_id FROM public.automation_trigger_occurrences manual WHERE manual.tenant_id=t AND manual.rule_id=g.rule_id
  ) refs ON refs.run_id=call.run_id WHERE call.tenant_id=t AND call.cost_state<>'unmetered';
 SELECT coalesce(sum(CASE WHEN call.cost_state='reserved' THEN call.cost_reserved_micro_usd ELSE call.cost_charged_micro_usd END),0),
  coalesce(sum(CASE WHEN call.cost_state='reserved' THEN call.input_token_reservation ELSE call.actual_input_tokens END),0),
  coalesce(sum(CASE WHEN call.cost_state='reserved' THEN call.output_token_reservation ELSE call.actual_output_tokens END),0),count(*)
  INTO chain_cost,chain_input,chain_output,chain_calls FROM public.agent_tool_calls call JOIN public.automation_service_attempts member
   ON member.tenant_id=call.tenant_id AND member.run_id=call.run_id WHERE member.tenant_id=t AND member.chain_id=chain.id AND member.state='admitted' AND call.cost_state<>'unmetered';
 IF wallet.calls>=wallet.call_limit OR wallet.held_input_tokens::bigint+wallet.used_input_tokens>=wallet.input_token_limit
  OR wallet.held_output_tokens::bigint+wallet.used_output_tokens>=wallet.output_token_limit
  OR wallet.held_micro_usd::bigint+wallet.spent_micro_usd>wallet.limit_micro_usd
  OR rule_calls>=(v.spec->'budget'->>'call_limit')::bigint OR rule_input>=(v.spec->'budget'->>'input_token_limit')::bigint
  OR rule_output>=(v.spec->'budget'->>'output_token_limit')::bigint OR rule_cost>(v.spec->'budget'->>'limit_micro_usd')::numeric THEN
  UPDATE public.automation_service_attempts SET state='suppressed',error_code='MODEL_BUDGET_EXHAUSTED' WHERE tenant_id=t AND id=a.id;
  PERFORM public.automation_service_stop(g.id,'MODEL_BUDGET_EXHAUSTED'); RETURN NULL;
 END IF;
 IF chain_calls>=(chain.budget->>'call_limit')::bigint OR chain_input>=(chain.budget->>'input_token_limit')::bigint
  OR chain_output>=(chain.budget->>'output_token_limit')::bigint OR chain_cost>(chain.budget->>'limit_micro_usd')::numeric THEN
  UPDATE public.automation_service_attempts SET state='suppressed',error_code='CHAIN_BUDGET_EXHAUSTED' WHERE tenant_id=t AND id=a.id; RETURN NULL;
 END IF;
 session_id=gen_random_uuid(); new_run_id=gen_random_uuid(); point=clock_timestamp();
 -- Recheck explicit deadlines after locks and preflight; a preview is not authority.
 IF NOT public.automation_service_grant_available(t,g.id,point) OR (SELECT count(*) FROM public.principals p JOIN public.grants access
  ON access.tenant_id=p.tenant_id AND access.principal_id=p.id WHERE p.tenant_id=t AND p.id IN (g.owner_id,g.writer_id)
   AND p.active AND access.category_id=g.category_id AND (access.expires_at IS NULL OR point<access.expires_at))<>2 THEN
  UPDATE public.automation_service_attempts SET state='suppressed',error_code='SCOPE_INVALID' WHERE tenant_id=t AND id=a.id;
  PERFORM public.automation_service_stop(g.id,'SCOPE_INVALID'); RETURN NULL;
 END IF;
 INSERT INTO public.agent_sessions(id,tenant_id,created_at,category_id,product_id,proposal_id,owner_id,revision)
  VALUES(session_id,t,point,g.category_id,(v.spec->>'product_id')::uuid,NULL,g.owner_id,1);
 INSERT INTO public.agent_runs(id,tenant_id,created_at,category_id,product_id,proposal_id,session_id,continued_from_id,requester_id,writer_id,trigger,goal,intent_key,intent_digest,cancel_epoch,state,private_context,data_categories,customer_identities,versions,read_sources,token_limit,validation_budget_id,held_tokens,used_tokens,result,error_code,reverted_at,reverted_by,revert_receipt_id)
  VALUES(new_run_id,t,point,g.category_id,(v.spec->>'product_id')::uuid,NULL,session_id,NULL,g.owner_id,g.writer_id,'automation_service',v.spec->>'goal','automation-service:'||a.id,a.request_digest,0,'queued',private_value,'["internal"]'::jsonb,'[]'::jsonb,'{"checkpoint_layout":"session-run-ns/v1"}'::jsonb,'[]'::jsonb,(v.spec->>'token_limit')::integer,wallet.id,0,0,NULL,NULL,NULL,NULL,NULL);
 INSERT INTO public.agent_run_events(id,tenant_id,created_at,run_id,sequence,body)
  VALUES(gen_random_uuid(),t,point,new_run_id,1,'{"type":"accepted","status":"queued"}'::jsonb);
 UPDATE public.automation_service_attempts SET state='admitted',run_id=new_run_id,admitted_at=point WHERE tenant_id=t AND id=a.id;
 UPDATE public.automation_rule_currents SET admitted_count=admitted_count+1,last_admitted_at=point WHERE tenant_id=t AND id=cur.id;
 RETURN new_run_id;
END
""".replace("__REASONS__", REASONS_SQL)


RUN_ATOM = r"""
DECLARE r public.agent_runs; a public.automation_service_attempts; g public.automation_service_grants;
 v public.automation_rule_versions; session public.agent_sessions;
BEGIN
 SELECT * INTO STRICT r FROM public.agent_runs WHERE tenant_id=t AND id=rid;
 SELECT * INTO STRICT a FROM public.automation_service_attempts WHERE tenant_id=t AND run_id=r.id AND state='admitted';
 SELECT * INTO STRICT g FROM public.automation_service_grants WHERE tenant_id=t AND id=a.service_grant_id;
 SELECT * INTO STRICT v FROM public.automation_rule_versions WHERE tenant_id=t AND id=g.published_version_id;
 SELECT * INTO STRICT session FROM public.agent_sessions WHERE tenant_id=t AND id=r.session_id;
 IF (SELECT count(*) FROM public.automation_service_attempts x WHERE x.tenant_id=t AND x.run_id=r.id AND x.state='admitted')<>1
  OR ROW(a.category_id,a.owner_id,a.writer_id,a.rule_id,a.published_version_id) IS DISTINCT FROM ROW(g.category_id,g.owner_id,g.writer_id,g.rule_id,g.published_version_id)
  OR ROW(g.category_id,g.owner_id,g.rule_id,g.receipt_id) IS DISTINCT FROM ROW(v.category_id,v.owner_id,v.rule_id,v.receipt_id)
  OR v.action<>'activate' OR v.state<>'active' OR v.confirmation_id IS NULL
  OR ROW(r.category_id,r.requester_id,r.writer_id,r.trigger,r.goal,r.intent_key,r.intent_digest,r.token_limit,r.validation_budget_id)
   IS DISTINCT FROM ROW(g.category_id,g.owner_id,g.writer_id,'automation_service'::varchar,v.spec->>'goal',('automation-service:'||a.id)::varchar,a.request_digest,(v.spec->>'token_limit')::integer,(v.spec->>'validation_budget_id')::uuid)
  OR r.product_id IS DISTINCT FROM (v.spec->>'product_id')::uuid OR r.proposal_id IS NOT NULL OR r.continued_from_id IS NOT NULL
  OR ROW(session.category_id,session.product_id,session.proposal_id,session.owner_id) IS DISTINCT FROM ROW(r.category_id,r.product_id,NULL::uuid,r.requester_id)
  OR a.admitted_at IS NULL OR r.created_at>a.admitted_at THEN
  RAISE EXCEPTION 'Service Run requires one actual admitted attempt and original T1 grant' USING ERRCODE='23514'; END IF;
END
"""

RUN_TARGET = r"""
DECLARE ax xid; rx xid;
BEGIN
 IF NEW.trigger='automation_service' OR (TG_OP='UPDATE' AND OLD.trigger='automation_service') THEN
  PERFORM public.assert_automation_service_run(NEW.tenant_id,NEW.id);
  IF TG_OP='INSERT' THEN
   IF NOT COALESCE(public.automation_service_identity(NEW.tenant_id,NEW.requester_id,NEW.writer_id),false) THEN
    RAISE EXCEPTION 'Service Run creation keeps its actual agent actor' USING ERRCODE='42501'; END IF;
   SELECT xmin INTO rx FROM public.agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
   SELECT xmin INTO ax FROM public.automation_service_attempts WHERE tenant_id=NEW.tenant_id AND run_id=NEW.id AND state='admitted';
   IF ax IS DISTINCT FROM rx THEN RAISE EXCEPTION 'Service Run and admitted attempt share one transaction' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 RETURN NULL;
END
"""


def functions():
    return (
        ("automation_service_stop", "grant_id uuid,stop_reason text", STOP, "uuid"),
        ("assert_automation_service_run", "t uuid,rid uuid", RUN_ATOM, "void"),
        ("automation_service_start", "attempt_id uuid", START, "uuid"),
        ("require_automation_service_run", "", RUN_TARGET, "trigger"),
    )


def function_sql():
    return tuple(_function(*row) for row in functions())


def signatures():
    return tuple(
        f"{name}({','.join(arg.split()[-1] for arg in args.split(',')) if args else ''})"
        for name, args, *_ in functions()
    )


def _role(value):
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", value):
        raise ValueError("Expected an ordinary PostgreSQL role identifier")
    return value


def authorization_sql(app_role="pdos_next_app", agent_role="pdos_agent"):
    app_role, agent_role = _role(app_role), _role(agent_role)
    return (
        *(
            f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC,{app_role},{agent_role},pdos_next_auth,pdos_next_dispatch"
            for signature in signatures()
        ),
        f"GRANT EXECUTE ON FUNCTION public.automation_service_start(uuid) TO {app_role}",
        f"GRANT EXECUTE ON FUNCTION public.automation_service_stop(uuid,text) TO {app_role}",
    )


def trigger_sql():
    return (
        "CREATE CONSTRAINT TRIGGER automation_service_run_atom AFTER INSERT OR UPDATE ON public.agent_runs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_automation_service_run()",
    )


def upgrade_sql(app_role="pdos_next_app", agent_role="pdos_agent"):
    return (*function_sql(), *authorization_sql(app_role, agent_role), *trigger_sql())


def downgrade_sql():
    return (
        "LOCK TABLE public.agent_runs,public.automation_service_grants,public.automation_service_attempts IN ACCESS EXCLUSIVE MODE",
        "DO $automation_commands$ BEGIN IF EXISTS(SELECT 1 FROM public.automation_service_grants) OR EXISTS(SELECT 1 FROM public.automation_service_attempts) OR EXISTS(SELECT 1 FROM public.agent_runs WHERE trigger='automation_service') THEN RAISE EXCEPTION 'Service command history retained; downgrade refused' USING ERRCODE='23514'; END IF; END; $automation_commands$",
        "DROP TRIGGER automation_service_run_atom ON public.agent_runs",
        *(f"DROP FUNCTION public.{signature}" for signature in reversed(signatures())),
    )
