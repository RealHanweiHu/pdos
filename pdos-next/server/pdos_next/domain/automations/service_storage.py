"""Offline service-automation DDL, without replacements for installed functions.

The root migration binds lifecycle references, version/Run reciprocals, admission
and counters. Agent roles receive SELECT only; service facts belong to the host.
"""

# ruff: noqa: E501 -- keep SQL predicates intact.

import re

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from .service_models import (
    AutomationCausalChain,
    AutomationServiceAttempt,
    AutomationServiceGrant,
)

TABLES = tuple(
    model.__table__
    for model in (AutomationServiceGrant, AutomationCausalChain, AutomationServiceAttempt)
)


def table_sql():
    return tuple(
        str(statement.compile(dialect=postgresql.dialect()))
        for table in TABLES
        for statement in (
            CreateTable(table),
            *(CreateIndex(i) for i in sorted(table.indexes, key=lambda item: item.name)),
        )
    )


def _function(name, args, body, returns="trigger", *, language="plpgsql"):
    return f"CREATE FUNCTION public.{name}({args}) RETURNS {returns}\nLANGUAGE {language} SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $automation_service$\n{body.rstrip()};\n$automation_service$"


IDENTITY = r"""
 SELECT t=nullif(current_setting('pdos.tenant_id',true),'')::uuid
  AND service_owner=public.scope_requester() AND service_writer=public.scope_actor()
  AND service_owner<>service_writer
  AND EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id=t AND h.id=service_owner AND h.kind='human')
  AND EXISTS(SELECT 1 FROM public.principals a WHERE a.tenant_id=t AND a.id=service_writer AND a.kind='agent')
"""

AVAILABLE = r"""
 SELECT EXISTS(SELECT 1 FROM public.automation_service_grants g
  JOIN public.automation_rule_versions v ON v.tenant_id=g.tenant_id AND v.category_id=g.category_id
   AND v.owner_id=g.owner_id AND v.rule_id=g.rule_id AND v.id=g.published_version_id
  JOIN public.automation_rule_currents cur ON cur.tenant_id=g.tenant_id AND cur.category_id=g.category_id
   AND cur.owner_id=g.owner_id AND cur.rule_id=g.rule_id AND cur.published_version_id=g.published_version_id
  WHERE g.tenant_id=t AND g.id=target AND cur.state='active' AND v.action='activate' AND v.state='active'
   AND v.receipt_id=g.receipt_id AND v.spec->>'trigger_kind' IN ('schedule','domain_event','relative_milestone')
   AND public.automation_service_identity(t,g.owner_id,g.writer_id)
   AND EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id=t AND h.id=g.owner_id AND h.active AND h.kind='human')
   AND EXISTS(SELECT 1 FROM public.principals a WHERE a.tenant_id=t AND a.id=g.writer_id AND a.active AND a.kind='agent')
   AND (SELECT count(*) FROM public.principals a WHERE a.tenant_id=t AND a.active AND a.kind='agent')=1
   AND public.category_access(t,g.category_id,false)
   AND at_time>=g.created_at AND (g.expires_at IS NULL OR at_time<g.expires_at))
"""

GRANT_ATOM = r"""
DECLARE g public.automation_service_grants; v public.automation_rule_versions; r public.action_receipts; c public.confirmations; gx xid; vx xid; rx xid; cx xid;
BEGIN
 SELECT * INTO STRICT g FROM public.automation_service_grants WHERE tenant_id=t AND id=target;
 SELECT * INTO STRICT v FROM public.automation_rule_versions WHERE tenant_id=t AND id=g.published_version_id;
 SELECT * INTO STRICT r FROM public.action_receipts WHERE tenant_id=t AND id=g.receipt_id;
 SELECT * INTO STRICT c FROM public.confirmations WHERE tenant_id=t AND id=v.confirmation_id;
 SELECT xmin INTO gx FROM public.automation_service_grants WHERE tenant_id=t AND id=g.id;
 SELECT xmin INTO vx FROM public.automation_rule_versions WHERE tenant_id=t AND id=v.id;
 SELECT xmin INTO rx FROM public.action_receipts WHERE tenant_id=t AND id=r.id;
 SELECT xmin INTO cx FROM public.confirmations WHERE tenant_id=t AND id=c.id;
 PERFORM public.assert_automation_members(t,v.id);
 IF ROW(g.category_id,g.owner_id,g.rule_id,g.receipt_id) IS DISTINCT FROM ROW(v.category_id,v.owner_id,v.rule_id,v.receipt_id)
  OR v.action<>'activate' OR v.state<>'active' OR v.operation<>'ai.automation.activate'
  OR NOT COALESCE(v.spec->>'trigger_kind' IN ('schedule','domain_event','relative_milestone'),false)
  OR g.expires_at IS DISTINCT FROM (v.spec#>>'{trigger_config,expires_at}')::timestamptz
  OR g.owner_id IS DISTINCT FROM public.scope_actor() OR g.owner_id IS DISTINCT FROM public.scope_requester()
  OR NOT public.category_access(t,g.category_id,true)
  OR NOT EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id=t AND h.id=g.owner_id AND h.active AND h.kind='human')
  OR NOT EXISTS(SELECT 1 FROM public.principals a WHERE a.tenant_id=t AND a.id=g.writer_id AND a.active AND a.kind='agent')
  OR (SELECT count(*) FROM public.principals a WHERE a.tenant_id=t AND a.active AND a.kind='agent')<>1
  OR ROW(r.category_id,r.actor_id,r.requester_id,r.operation,r.subject_type,r.subject_id,r.subject_revision,r.confirmation_id)
   IS DISTINCT FROM ROW(g.category_id,g.owner_id,g.owner_id,'ai.automation.activate'::varchar,'automation_rule'::varchar,v.id,v.revision,v.confirmation_id)
  OR r.run_id IS NOT NULL OR r.agent_run_id IS NOT NULL
  OR c.consumed IS DISTINCT FROM true OR c.operation<>'ai.automation.activate'
  OR c.actor_id<>g.owner_id OR c.category_id<>g.category_id OR c.subject_type<>'category' OR c.subject_id<>g.category_id
  OR c.snapshot IS DISTINCT FROM v.command->'review'
  OR c.created_at>g.created_at OR g.created_at<v.created_at
  OR gx IS DISTINCT FROM vx OR gx IS DISTINCT FROM rx OR gx IS DISTINCT FROM cx THEN
  RAISE EXCEPTION 'Service grant requires actual named T1 activation and unique Pai in one transaction' USING ERRCODE='23514'; END IF;
END
"""

CHAIN_ATOM = r"""
DECLARE chain public.automation_causal_chains; g public.automation_service_grants; v public.automation_rule_versions; chain_xid xid;
BEGIN
 SELECT * INTO STRICT chain FROM public.automation_causal_chains WHERE tenant_id=t AND id=target;
 SELECT * INTO STRICT g FROM public.automation_service_grants WHERE tenant_id=t AND id=chain.root_grant_id;
 SELECT * INTO STRICT v FROM public.automation_rule_versions WHERE tenant_id=t AND id=g.published_version_id;
 SELECT xmin INTO chain_xid FROM public.automation_causal_chains WHERE tenant_id=t AND id=chain.id;
 IF ROW(chain.category_id,chain.owner_id) IS DISTINCT FROM ROW(g.category_id,g.owner_id)
  OR chain.budget IS DISTINCT FROM v.spec->'budget' OR chain.max_depth IS DISTINCT FROM (v.spec->>'max_cascade_depth')::integer
  OR chain.created_at<g.created_at
  OR NOT COALESCE(public.automation_service_identity(t,g.owner_id,g.writer_id),false)
  OR (NOT public.automation_service_grant_available(t,g.id,statement_timestamp()) AND NOT EXISTS(
   SELECT 1 FROM public.automation_service_attempts diagnostic WHERE diagnostic.tenant_id=t AND diagnostic.chain_id=chain.id
    AND diagnostic.service_grant_id=g.id AND diagnostic.depth=0 AND diagnostic.origin->>'kind'='lifecycle'
    AND diagnostic.state='suppressed' AND diagnostic.run_id IS NULL AND diagnostic.admitted_at IS NULL AND diagnostic.xmin=chain_xid)) THEN
  RAISE EXCEPTION 'Causal chain fixes the actual root grant budget and depth' USING ERRCODE='23514'; END IF;
END
"""

ATTEMPT_GUARD = r"""
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Service attempt history retained' USING ERRCODE='23514'; END IF;
 IF NOT COALESCE(public.automation_service_identity(NEW.tenant_id,NEW.owner_id,NEW.writer_id),false) THEN
  RAISE EXCEPTION 'Service attempt belongs to actual Pai actor and named delegator' USING ERRCODE='23514'; END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.state<>'queued' OR NEW.run_id IS NOT NULL OR NEW.admitted_at IS NOT NULL OR NEW.error_code IS NOT NULL THEN
   RAISE EXCEPTION 'Service attempt starts queued without invented Run' USING ERRCODE='23514'; END IF;
 ELSIF OLD.state<>'queued' OR NEW.state NOT IN ('admitted','suppressed')
  OR (to_jsonb(NEW)-ARRAY['state','error_code','run_id','admitted_at']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','error_code','run_id','admitted_at']) THEN
  RAISE EXCEPTION 'Service attempt only leaves queued once and retains its original origin' USING ERRCODE='23514';
 END IF;
 IF NEW.state<>'suppressed' AND NEW.origin->>'kind' IS DISTINCT FROM 'lifecycle'
  AND NOT public.automation_service_grant_available(NEW.tenant_id,NEW.service_grant_id,statement_timestamp()) THEN
  RAISE EXCEPTION 'New queued or admitted service attempt requires current usable grant' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END
"""

ATTEMPT_ATOM = r"""
DECLARE a public.automation_service_attempts; g public.automation_service_grants; v public.automation_rule_versions; chain public.automation_causal_chains; r public.agent_runs; ax xid; rx xid;
BEGIN
 SELECT * INTO STRICT a FROM public.automation_service_attempts WHERE tenant_id=t AND id=target;
 SELECT * INTO STRICT g FROM public.automation_service_grants WHERE tenant_id=t AND id=a.service_grant_id;
 SELECT * INTO STRICT v FROM public.automation_rule_versions WHERE tenant_id=t AND id=g.published_version_id;
 SELECT * INTO STRICT chain FROM public.automation_causal_chains WHERE tenant_id=t AND id=a.chain_id;
 IF a.state<>'suppressed' AND NOT public.automation_service_grant_available(t,g.id,statement_timestamp()) THEN
  RAISE EXCEPTION 'Unavailable lifecycle attempt must finish suppressed in its own transaction' USING ERRCODE='23514'; END IF;
 IF ROW(a.category_id,a.owner_id,a.writer_id,a.rule_id,a.published_version_id) IS DISTINCT FROM ROW(g.category_id,g.owner_id,g.writer_id,g.rule_id,g.published_version_id)
  OR a.trigger_kind IS DISTINCT FROM v.spec->>'trigger_kind' OR (a.state='admitted' AND a.depth>chain.max_depth)
  OR (a.depth=0 AND chain.root_grant_id IS DISTINCT FROM a.service_grant_id)
  OR (a.depth>0 AND NOT EXISTS(SELECT 1 FROM public.automation_service_attempts parent_attempt
    WHERE parent_attempt.tenant_id=t AND parent_attempt.run_id=a.parent_run_id AND parent_attempt.state='admitted'
     AND parent_attempt.chain_id=a.chain_id AND parent_attempt.depth+1=a.depth))
  OR a.created_at<g.created_at OR a.created_at<chain.created_at
  OR (a.parent_run_id IS NOT NULL AND (a.parent_run_id IS NOT DISTINCT FROM a.run_id
   OR NOT EXISTS(SELECT 1 FROM public.agent_runs parent WHERE parent.tenant_id=t AND parent.id=a.parent_run_id AND parent.created_at<=a.created_at))) THEN
  RAISE EXCEPTION 'Service attempt requires fixed grant actual parent and causal budget chain' USING ERRCODE='23514'; END IF;
 IF a.state='admitted' THEN
  SELECT * INTO STRICT r FROM public.agent_runs WHERE tenant_id=t AND id=a.run_id;
  SELECT xmin INTO ax FROM public.automation_service_attempts WHERE tenant_id=t AND id=a.id;
  SELECT xmin INTO rx FROM public.agent_runs WHERE tenant_id=t AND id=r.id;
  IF ROW(r.category_id,r.requester_id,r.writer_id,r.trigger,r.intent_key,r.goal,r.intent_digest,r.validation_budget_id,r.token_limit)
    IS DISTINCT FROM ROW(a.category_id,a.owner_id,a.writer_id,'automation_service'::varchar,('automation-service:'||a.id)::varchar,v.spec->>'goal',a.request_digest,(v.spec->>'validation_budget_id')::uuid,(v.spec->>'token_limit')::integer)
   OR r.product_id IS DISTINCT FROM (v.spec->>'product_id')::uuid OR r.proposal_id IS NOT NULL OR r.continued_from_id IS NOT NULL
   OR a.admitted_at<a.created_at OR a.admitted_at<r.created_at
   OR (a.due_at IS NOT NULL AND a.admitted_at<a.due_at) OR ax IS DISTINCT FROM rx THEN
   RAISE EXCEPTION 'Admitted service attempt binds its exact new Run and real admission time' USING ERRCODE='23514'; END IF;
 END IF;
END
"""


def functions():
    return (
        (
            "automation_service_identity",
            "t uuid,service_owner uuid,service_writer uuid",
            IDENTITY,
            "boolean",
            "sql",
        ),
        (
            "automation_service_grant_available",
            "t uuid,target uuid,at_time timestamptz",
            AVAILABLE,
            "boolean",
            "sql",
        ),
        ("assert_automation_service_grant", "t uuid,target uuid", GRANT_ATOM, "void", "plpgsql"),
        ("assert_automation_causal_chain", "t uuid,target uuid", CHAIN_ATOM, "void", "plpgsql"),
        (
            "assert_automation_service_attempt",
            "t uuid,target uuid",
            ATTEMPT_ATOM,
            "void",
            "plpgsql",
        ),
        ("protect_automation_service_attempt", "", ATTEMPT_GUARD, "trigger", "plpgsql"),
        (
            "reject_automation_service_mutation",
            "",
            "BEGIN RAISE EXCEPTION 'Service grants and causal chains are immutable' USING ERRCODE='23514'; END",
            "trigger",
            "plpgsql",
        ),
        *(
            (
                f"require_{stem}",
                "",
                f"BEGIN PERFORM public.assert_{stem}(NEW.tenant_id,NEW.id); RETURN NULL; END",
                "trigger",
                "plpgsql",
            )
            for stem in (
                "automation_service_grant",
                "automation_causal_chain",
                "automation_service_attempt",
            )
        ),
    )


def function_sql():
    return tuple(_function(*row[:3], row[3], language=row[4]) for row in functions())


def signatures():
    return tuple(
        f"{name}({','.join(arg.split()[-1] for arg in args.split(',')) if args else ''})"
        for name, args, *_ in functions()
    )


def _role(value):
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", value):
        raise ValueError("Expected an ordinary PostgreSQL role identifier")
    return value


def policy_sql(app_role="pdos_next_app", agent_role="pdos_agent"):
    app_role, agent_role = _role(app_role), _role(agent_role)
    statements = []
    for table in TABLES:
        name = table.name
        read = "public.category_access(tenant_id,category_id,false) AND owner_id=public.scope_requester()"
        if table is TABLES[0]:
            insert = f"{read} AND owner_id=public.scope_actor() AND public.category_access(tenant_id,category_id,true) AND EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id={name}.tenant_id AND h.id={name}.owner_id AND h.active AND h.kind='human')"
        elif table is TABLES[1]:
            insert = f"{read} AND EXISTS(SELECT 1 FROM public.automation_service_grants g WHERE g.tenant_id={name}.tenant_id AND g.id={name}.root_grant_id AND g.owner_id={name}.owner_id AND g.category_id={name}.category_id AND g.writer_id=public.scope_actor())"
        else:
            insert = f"{read} AND writer_id=public.scope_actor() AND EXISTS(SELECT 1 FROM public.principals a WHERE a.tenant_id={name}.tenant_id AND a.id={name}.writer_id AND a.active AND a.kind='agent')"
        statements.extend(
            (
                f'ALTER TABLE public."{name}" ENABLE ROW LEVEL SECURITY',
                f'ALTER TABLE public."{name}" FORCE ROW LEVEL SECURITY',
                f'CREATE POLICY owner_internal ON public."{name}" TO pdos_next_owner USING(true) WITH CHECK(true)',
                f'CREATE POLICY automation_service_read ON public."{name}" FOR SELECT TO {app_role},{agent_role} USING({read})',
                f'CREATE POLICY automation_service_insert ON public."{name}" FOR INSERT TO {app_role} WITH CHECK({insert})',
                f'REVOKE ALL ON public."{name}" FROM PUBLIC,{app_role},{agent_role},pdos_next_auth,pdos_next_dispatch',
                f'GRANT SELECT ON public."{name}" TO {app_role},{agent_role}',
                f'GRANT INSERT ON public."{name}" TO {app_role}',
            )
        )
        if table is TABLES[2]:
            statements.extend(
                (
                    f'CREATE POLICY automation_service_close ON public."{name}" FOR UPDATE TO {app_role} USING({insert}) WITH CHECK({insert})',
                    f'GRANT UPDATE(state,error_code,run_id,admitted_at) ON public."{name}" TO {app_role}',
                )
            )
    return tuple(statements)


def trigger_sql():
    statements = []
    for table, stem in zip(
        TABLES,
        ("automation_service_grant", "automation_causal_chain", "automation_service_attempt"),
        strict=True,
    ):
        statements.extend(
            (
                f"CREATE TRIGGER automation_service_category_immutable BEFORE UPDATE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.protect_category_binding()",
                f"CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.lifecycle_reference_gate()",
                f"CREATE TRIGGER category_lifecycle_clock AFTER INSERT OR UPDATE OR DELETE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.category_lifecycle_clock()",
                f"CREATE CONSTRAINT TRIGGER automation_service_atom AFTER INSERT{' OR UPDATE' if table is TABLES[2] else ''} ON public.{table.name} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_{stem}()",
            )
        )
        if table is TABLES[2]:
            statements.append(
                f"CREATE TRIGGER automation_service_attempt_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.protect_automation_service_attempt()"
            )
        else:
            statements.append(
                f"CREATE TRIGGER automation_service_immutable BEFORE UPDATE OR DELETE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.reject_automation_service_mutation()"
            )
    return tuple(statements)


def upgrade_sql(app_role="pdos_next_app", agent_role="pdos_agent"):
    app_role, agent_role = _role(app_role), _role(agent_role)
    return (
        *table_sql(),
        *function_sql(),
        *(
            f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC,{app_role},{agent_role},pdos_next_auth,pdos_next_dispatch"
            for signature in signatures()
        ),
        *policy_sql(app_role, agent_role),
        *trigger_sql(),
    )


def downgrade_sql():
    return (
        "LOCK TABLE "
        + ",".join(f"public.{table.name}" for table in TABLES)
        + " IN ACCESS EXCLUSIVE MODE",
        "DO $automation_service$ BEGIN IF "
        + " OR ".join(f"EXISTS(SELECT 1 FROM public.{table.name})" for table in TABLES)
        + " THEN RAISE EXCEPTION 'Service automation history retained; downgrade refused' USING ERRCODE='23514'; END IF; END; $automation_service$",
        *(f"DROP TABLE public.{table.name}" for table in reversed(TABLES)),
        *(f"DROP FUNCTION public.{signature}" for signature in reversed(signatures())),
    )
