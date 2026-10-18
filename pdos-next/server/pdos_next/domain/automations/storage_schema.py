"""Offline SQL declarations for manual, human-admitted, read-only automation.

The root migration supplies shared lifecycle/native-subject registrations. This
module neither installs SQL nor grants service, model, network or MCP authority.
"""

# ruff: noqa: E501 -- keep complete PostgreSQL predicates together.

import re

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from .models import (
    OPERATIONS,
    AutomationRuleCurrent,
    AutomationRuleVersion,
    AutomationTriggerOccurrence,
)

TABLES = tuple(
    model.__table__
    for model in (AutomationRuleVersion, AutomationRuleCurrent, AutomationTriggerOccurrence)
)
OPS = "(" + ",".join(repr(value) for value in OPERATIONS) + ")"
T1 = "('ai.automation.activate','ai.automation.pause')"


def table_sql():
    return tuple(
        str(statement.compile(dialect=postgresql.dialect()))
        for table in TABLES
        for statement in (
            CreateTable(table),
            *(CreateIndex(i) for i in sorted(table.indexes, key=lambda value: value.name)),
        )
    )


def _function(name, args, body, returns="trigger"):
    return f"CREATE FUNCTION public.{name}({args}) RETURNS {returns}\nLANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $automation$\n{body.rstrip()};\n$automation$"


MEMBERS = r"""
DECLARE v public.automation_rule_versions; r public.action_receipts; c public.confirmations; event_name text; current_state text;
BEGIN
 SELECT * INTO STRICT v FROM public.automation_rule_versions WHERE tenant_id=t AND id=target;
 SELECT * INTO STRICT r FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;
 current_state=CASE WHEN v.action='draft' AND v.previous_id IS NOT NULL THEN v.command->'review'->'before'->>'state' ELSE v.state END;
 event_name=CASE v.action WHEN 'draft' THEN 'ai.automation_draft_saved' WHEN 'activate' THEN 'ai.automation_activated' WHEN 'pause' THEN 'ai.automation_paused' END;
 IF ROW(r.category_id,r.product_id,r.command_id,r.confirmation_id,r.actor_id,r.requester_id,r.operation,r.subject_type,r.subject_id,r.subject_revision,r.visibility,r.request_digest,r.intent_digest)
  IS DISTINCT FROM ROW(v.category_id,NULL::uuid,v.command_id,v.confirmation_id,v.actor_id,v.requester_id,v.operation,'automation_rule'::varchar,v.id,v.revision,'private'::varchar,v.request_digest,v.intent_digest)
  OR r.run_id IS NOT NULL OR r.agent_run_id IS NOT NULL
  OR r.result IS DISTINCT FROM jsonb_build_object('id',v.id,'revision',v.revision,'status',v.state,'rule_id',v.rule_id,'state',current_state)
  OR r.created_at<v.created_at
  OR (SELECT count(*) FROM public.action_receipts x WHERE x.tenant_id=t AND x.operation=v.operation AND x.subject_type='automation_rule' AND x.subject_id=v.id AND x.subject_revision=v.revision)<>1
  OR (SELECT count(*) FROM public.audit_entries a WHERE a.tenant_id=t AND a.receipt_id=r.id)<>1
  OR NOT EXISTS(SELECT 1 FROM public.audit_entries a WHERE a.tenant_id=t AND a.receipt_id=r.id AND a.category_id=v.category_id AND a.actor_id=v.actor_id AND a.operation=v.operation AND a.created_at>=v.created_at)
  OR (SELECT count(*) FROM public.outbox_events e WHERE e.tenant_id=t AND e.receipt_id=r.id)<>1
  OR NOT EXISTS(SELECT 1 FROM public.outbox_events e WHERE e.tenant_id=t AND e.receipt_id=r.id AND e.category_id=v.category_id AND e.actor_id=v.actor_id AND e.type=event_name AND e.subject_id=v.id AND e.subject_revision=v.revision AND e.schema_version=1 AND e.correlation_id=v.command_id AND e.created_at>=v.created_at)
  OR v.command->>'original_key_sha256' IS NULL OR v.command->>'original_key_sha256' !~ '^[a-f0-9]{64}$'
  OR v.command->'envelope' ? 'idempotency_key' OR v.command->'envelope'->'payload' ? 'confirmation_token'
  OR NOT EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=t AND k.category_id=v.category_id AND k.actor_id=v.actor_id AND k.receipt_id=r.id AND k.digest=v.request_digest AND encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.command->>'original_key_sha256') THEN
  RAISE EXCEPTION 'Automation original common group mismatch' USING ERRCODE='23514'; END IF;
 IF v.confirmation_id IS NOT NULL THEN
  SELECT * INTO STRICT c FROM public.confirmations WHERE tenant_id=t AND id=v.confirmation_id;
  IF c.consumed IS DISTINCT FROM true OR ROW(c.category_id,c.product_id,c.actor_id,c.operation,c.subject_type,c.subject_id)
    IS DISTINCT FROM ROW(v.category_id,NULL::uuid,v.actor_id,v.operation,'category'::varchar,v.category_id)
   OR c.revision::text IS DISTINCT FROM v.command->'envelope'->>'expected_revision'
   OR c.snapshot IS DISTINCT FROM v.command->'review' OR c.created_at>v.created_at
   OR c.expires_at IS NULL OR v.created_at>=c.expires_at OR r.created_at>=c.expires_at THEN
   RAISE EXCEPTION 'Automation T1 requires its original consumed confirmation' USING ERRCODE='23514'; END IF;
 END IF;
END
"""

VERSION_ATOM = r"""
DECLARE v public.automation_rule_versions; cur public.automation_rule_currents; envelope jsonb; vx xid; rx xid; cx xid;
BEGIN
 SELECT * INTO STRICT v FROM public.automation_rule_versions WHERE tenant_id=t AND id=target;
 SELECT * INTO STRICT cur FROM public.automation_rule_currents WHERE tenant_id=t AND rule_id=v.rule_id;
 SELECT xmin INTO vx FROM public.automation_rule_versions WHERE tenant_id=t AND id=v.id;
 SELECT xmin INTO rx FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;
 SELECT xmin INTO cx FROM public.automation_rule_currents WHERE tenant_id=t AND id=cur.id;
 PERFORM public.assert_automation_members(t,target);
 envelope=v.command->'envelope';
 IF vx IS DISTINCT FROM rx OR vx IS DISTINCT FROM cx
  OR ROW(cur.category_id,cur.owner_id,cur.version_id,cur.revision) IS DISTINCT FROM ROW(v.category_id,v.owner_id,v.id,v.revision)
  OR v.owner_id IS DISTINCT FROM public.scope_actor() OR v.owner_id IS DISTINCT FROM public.scope_requester()
  OR NOT public.category_access(t,v.category_id,true)
  OR NOT EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=t AND p.id=v.owner_id AND p.active AND p.kind='human')
  OR NOT EXISTS(SELECT 1 FROM public.categories c WHERE c.tenant_id=t AND c.id=v.category_id AND c.revision::text=envelope->>'expected_revision')
  OR envelope->>'category_id' IS DISTINCT FROM v.category_id::text OR envelope->'product_id' IS DISTINCT FROM 'null'::jsonb
  OR envelope->>'operation' IS DISTINCT FROM v.operation OR envelope->>'command_id' IS DISTINCT FROM v.command_id::text
  OR envelope->'source_read_set' IS DISTINCT FROM '[]'::jsonb
  OR (v.action='draft' AND envelope->'payload'->'spec' IS DISTINCT FROM v.spec)
  OR v.command->'review'->>'operation' IS DISTINCT FROM v.operation
  OR v.command->'review'->'declaration' IS DISTINCT FROM envelope->'payload'
  OR v.command->'review'->'after' IS DISTINCT FROM jsonb_build_object('rule_id',v.rule_id,'revision',v.revision,'action',v.action,'state',v.state,'spec',v.spec)
  OR v.command->'review'->>'effect' IS DISTINCT FROM '规则仅供本人手动触发只读工作；暂停只阻止新受理。'
  OR v.spec->>'trigger_kind' IS DISTINCT FROM 'manual' OR v.spec->'allow_network' IS DISTINCT FROM 'false'::jsonb
  OR v.spec->'mcp_tools' IS DISTINCT FROM '[]'::jsonb OR v.spec->'cross_object_write' IS DISTINCT FROM 'false'::jsonb
  OR EXISTS(SELECT 1 FROM public.audit_entries a WHERE a.tenant_id=t AND a.receipt_id=v.receipt_id AND a.xmin IS DISTINCT FROM vx)
  OR EXISTS(SELECT 1 FROM public.outbox_events e WHERE e.tenant_id=t AND e.receipt_id=v.receipt_id AND e.xmin IS DISTINCT FROM vx)
  OR NOT EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=t AND k.receipt_id=v.receipt_id AND k.actor_id=v.actor_id AND k.digest=v.request_digest AND k.xmin=vx AND encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.command->>'original_key_sha256') THEN
  RAISE EXCEPTION 'Automation version requires current human and one actual common transaction' USING ERRCODE='23514'; END IF;
 IF envelope->'payload'->>'restored_from' IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM public.automation_rule_versions old WHERE old.tenant_id=t AND old.category_id=v.category_id
   AND old.owner_id=v.owner_id AND old.rule_id=v.rule_id AND old.id::text=envelope->'payload'->>'restored_from'
   AND old.spec=v.spec AND old.spec_sha256=v.spec_sha256 AND old.revision<v.revision) THEN
  RAISE EXCEPTION 'Automation rollback copies an actual prior version into new draft' USING ERRCODE='23514'; END IF;
 IF v.confirmation_id IS NOT NULL THEN
  SELECT xmin INTO cx FROM public.confirmations WHERE tenant_id=t AND id=v.confirmation_id;
  IF cx IS DISTINCT FROM vx THEN RAISE EXCEPTION 'Automation confirmation must consume in its fact transaction' USING ERRCODE='23514'; END IF;
 END IF;
END
"""

CURRENT_GUARD = r"""
DECLARE v public.automation_rule_versions; prior public.automation_rule_versions; before_value jsonb;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Automation Current history retained' USING ERRCODE='23514'; END IF;
 SELECT * INTO STRICT v FROM public.automation_rule_versions WHERE tenant_id=NEW.tenant_id AND id=NEW.version_id;
 IF TG_OP='INSERT' THEN
  IF NEW.revision<>1 OR v.revision<>1 OR v.action<>'draft' OR NEW.state<>'draft' OR NEW.draft_version_id IS DISTINCT FROM v.id
   OR NEW.published_version_id IS NOT NULL OR NEW.admitted_count<>0 OR NEW.last_admitted_at IS NOT NULL
   OR v.command->'envelope'->'payload'->'rule_id' IS DISTINCT FROM 'null'::jsonb
   OR v.command->'envelope'->'payload'->>'expected_rule_revision' IS DISTINCT FROM '0'
   OR v.command->'review'->'before' IS DISTINCT FROM 'null'::jsonb THEN
   RAISE EXCEPTION 'Automation Current starts with an unadmitted draft' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF (to_jsonb(NEW)-ARRAY['admitted_count','last_admitted_at']) IS NOT DISTINCT FROM (to_jsonb(OLD)-ARRAY['admitted_count','last_admitted_at']) THEN
  IF OLD.state<>'active' OR NEW.admitted_count<>OLD.admitted_count+1 OR NEW.last_admitted_at IS NULL
   OR (OLD.last_admitted_at IS NOT NULL AND NEW.last_admitted_at<OLD.last_admitted_at) THEN
   RAISE EXCEPTION 'Automation admission only advances its actual counter once' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF (to_jsonb(NEW)-ARRAY['version_id','revision','state','draft_version_id','published_version_id']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['version_id','revision','state','draft_version_id','published_version_id'])
  OR NEW.revision<>OLD.revision+1 OR v.previous_id IS DISTINCT FROM OLD.version_id OR v.previous_revision IS DISTINCT FROM OLD.revision
  OR v.command->'envelope'->'payload'->>'rule_id' IS DISTINCT FROM OLD.rule_id::text
  OR v.command->'envelope'->'payload'->>'expected_rule_revision' IS DISTINCT FROM OLD.revision::text THEN
  RAISE EXCEPTION 'Automation Current requires one exact CAS and retained counters' USING ERRCODE='23514'; END IF;
 before_value=jsonb_build_object('revision',OLD.revision,'state',OLD.state,'draft_version_id',OLD.draft_version_id,'published_version_id',OLD.published_version_id);
 IF v.command->'review'->'before' IS DISTINCT FROM before_value THEN RAISE EXCEPTION 'Automation review must bind actual prior Current' USING ERRCODE='23514'; END IF;
 IF v.action='draft' THEN
  IF NEW.state IS DISTINCT FROM OLD.state OR NEW.draft_version_id IS DISTINCT FROM v.id OR NEW.published_version_id IS DISTINCT FROM OLD.published_version_id THEN
   RAISE EXCEPTION 'Editing automation preserves its published rule and state' USING ERRCODE='23514'; END IF;
 ELSIF v.action='activate' THEN
  SELECT * INTO STRICT prior FROM public.automation_rule_versions WHERE tenant_id=OLD.tenant_id AND id=coalesce(OLD.draft_version_id,OLD.published_version_id);
  IF prior.action NOT IN ('draft','activate') OR v.spec IS DISTINCT FROM prior.spec OR v.spec_sha256 IS DISTINCT FROM prior.spec_sha256
   OR v.command->'envelope'->'payload'->>'version_id' IS DISTINCT FROM prior.id::text
   OR NEW.state<>'active' OR NEW.published_version_id IS DISTINCT FROM v.id OR NEW.draft_version_id IS NOT NULL THEN
   RAISE EXCEPTION 'Activation publishes exactly the saved draft' USING ERRCODE='23514'; END IF;
 ELSIF v.action='pause' THEN
  SELECT * INTO STRICT prior FROM public.automation_rule_versions WHERE tenant_id=OLD.tenant_id AND id=OLD.published_version_id;
  IF OLD.state<>'active' OR prior.action<>'activate' OR v.spec IS DISTINCT FROM prior.spec OR v.spec_sha256 IS DISTINCT FROM prior.spec_sha256
   OR v.command->'envelope'->'payload'->>'version_id' IS DISTINCT FROM prior.id::text
   OR NEW.state<>'paused' OR NEW.published_version_id IS DISTINCT FROM OLD.published_version_id OR NEW.draft_version_id IS DISTINCT FROM OLD.draft_version_id THEN
   RAISE EXCEPTION 'Pause retains published version and pending draft' USING ERRCODE='23514'; END IF;
 ELSE RAISE EXCEPTION 'Unknown automation transition' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END
"""

CURRENT_ATOM = r"""
DECLARE cur public.automation_rule_currents; v public.automation_rule_versions; count_actual bigint; last_actual timestamptz; cx xid; vx xid;
BEGIN
 SELECT * INTO STRICT cur FROM public.automation_rule_currents WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
 SELECT * INTO STRICT v FROM public.automation_rule_versions WHERE tenant_id=cur.tenant_id AND id=cur.version_id;
 IF ROW(cur.category_id,cur.owner_id,cur.rule_id,cur.revision) IS DISTINCT FROM ROW(v.category_id,v.owner_id,v.rule_id,v.revision)
  OR (cur.draft_version_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.automation_rule_versions d WHERE d.tenant_id=cur.tenant_id AND d.id=cur.draft_version_id AND d.action='draft'))
  OR (cur.published_version_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.automation_rule_versions p WHERE p.tenant_id=cur.tenant_id AND p.id=cur.published_version_id AND p.action='activate'))
  OR (cur.state IN ('active','paused') AND cur.published_version_id IS NULL) THEN
  RAISE EXCEPTION 'Automation Current requires exact actual version pointers' USING ERRCODE='23514'; END IF;
 IF TG_OP='INSERT' OR NEW.version_id IS DISTINCT FROM OLD.version_id THEN
  SELECT xmin INTO cx FROM public.automation_rule_currents WHERE tenant_id=cur.tenant_id AND id=cur.id;
  SELECT xmin INTO vx FROM public.automation_rule_versions WHERE tenant_id=v.tenant_id AND id=v.id;
  IF cx IS DISTINCT FROM vx THEN RAISE EXCEPTION 'Automation Current and appended version share transaction' USING ERRCODE='23514'; END IF;
 END IF;
 SELECT count(*),max(created_at) INTO count_actual,last_actual FROM public.automation_trigger_occurrences WHERE tenant_id=cur.tenant_id AND rule_id=cur.rule_id;
 IF cur.admitted_count IS DISTINCT FROM count_actual OR cur.last_admitted_at IS DISTINCT FROM last_actual THEN
  RAISE EXCEPTION 'Automation counter requires actual occurrence history' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END
"""

OCCURRENCE_ATOM = r"""
DECLARE o public.automation_trigger_occurrences; v public.automation_rule_versions; cur public.automation_rule_currents; r public.agent_runs; b public.agent_validation_budgets; ox xid; rx xid; cx xid; count_actual bigint; last_actual timestamptz; previous_at timestamptz;
BEGIN
 SELECT * INTO STRICT o FROM public.automation_trigger_occurrences WHERE tenant_id=t AND id=target;
 SELECT * INTO STRICT v FROM public.automation_rule_versions WHERE tenant_id=t AND id=o.published_version_id;
 SELECT * INTO STRICT cur FROM public.automation_rule_currents WHERE tenant_id=t AND rule_id=o.rule_id;
 SELECT * INTO STRICT r FROM public.agent_runs WHERE tenant_id=t AND id=o.run_id;
 SELECT * INTO STRICT b FROM public.agent_validation_budgets WHERE tenant_id=t AND id=r.validation_budget_id;
 SELECT xmin INTO ox FROM public.automation_trigger_occurrences WHERE tenant_id=t AND id=o.id;
 SELECT xmin INTO rx FROM public.agent_runs WHERE tenant_id=t AND id=r.id;
 SELECT xmin INTO cx FROM public.automation_rule_currents WHERE tenant_id=t AND id=cur.id;
 SELECT count(*),max(created_at) INTO count_actual,last_actual FROM public.automation_trigger_occurrences WHERE tenant_id=t AND rule_id=o.rule_id;
 SELECT max(created_at) INTO previous_at FROM public.automation_trigger_occurrences WHERE tenant_id=t AND rule_id=o.rule_id AND id<>o.id;
 IF ROW(v.category_id,v.owner_id,v.rule_id) IS DISTINCT FROM ROW(o.category_id,o.owner_id,o.rule_id)
  OR ROW(cur.category_id,cur.owner_id,cur.published_version_id,cur.state) IS DISTINCT FROM ROW(o.category_id,o.owner_id,o.published_version_id,'active'::varchar)
  OR v.action<>'activate' OR v.state<>'active' OR v.spec->>'trigger_kind' IS DISTINCT FROM 'manual'
  OR o.owner_id IS DISTINCT FROM public.scope_actor() OR o.owner_id IS DISTINCT FROM public.scope_requester()
  OR NOT public.category_access(t,o.category_id,true)
  OR NOT EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=t AND p.id=o.requester_id AND p.kind='human' AND p.active)
  OR ROW(r.category_id,r.requester_id,r.trigger,r.goal,r.intent_key,r.intent_digest,r.validation_budget_id,r.token_limit)
    IS DISTINCT FROM ROW(o.category_id,o.requester_id,'automation_manual'::varchar,v.spec->>'goal',('automation:'||o.intent_key)::varchar,o.request_digest,(v.spec->>'validation_budget_id')::uuid,(v.spec->>'token_limit')::integer)
  OR r.product_id IS DISTINCT FROM (v.spec->>'product_id')::uuid OR r.proposal_id IS NOT NULL OR r.continued_from_id IS NOT NULL
  OR r.read_sources IS DISTINCT FROM '[]'::jsonb
  OR b.requester_id<>o.owner_id OR NOT b.active
  OR cur.admitted_count IS DISTINCT FROM count_actual OR cur.last_admitted_at IS DISTINCT FROM last_actual
  OR count_actual>(v.spec->>'max_runs')::integer
  OR (previous_at IS NOT NULL AND o.created_at<previous_at+make_interval(secs=>(v.spec->>'cooldown_seconds')::integer))
  OR o.created_at<r.created_at OR o.created_at<v.created_at
  OR ox IS DISTINCT FROM rx OR ox IS DISTINCT FROM cx THEN
  RAISE EXCEPTION 'Manual occurrence requires exact saved rule new human Run and counter' USING ERRCODE='23514'; END IF;
END
"""

PROOF = f"""
DECLARE scoped boolean=false;
BEGIN
 IF TG_OP<>'INSERT' THEN scoped=OLD.operation IN {T1}; END IF;
 IF TG_OP<>'DELETE' THEN scoped=scoped OR NEW.operation IN {T1}; END IF;
 IF scoped THEN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Automation confirmation history retained' USING ERRCODE='23514';
  ELSIF TG_OP='INSERT' THEN
   IF NEW.consumed IS DISTINCT FROM false THEN RAISE EXCEPTION 'Automation confirmation starts unconsumed' USING ERRCODE='23514'; END IF;
  ELSIF OLD.operation NOT IN {T1} OR NEW.operation NOT IN {T1} OR OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS DISTINCT FROM true
   OR (to_jsonb(NEW)-'consumed') IS DISTINCT FROM (to_jsonb(OLD)-'consumed') THEN
   RAISE EXCEPTION 'Automation confirmation only consumes original false to true' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END
"""

PROOF_TARGET = f"""
BEGIN
 IF NEW.operation IN {T1} AND (OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS DISTINCT FROM true
  OR (SELECT count(*) FROM public.automation_rule_versions v WHERE v.tenant_id=NEW.tenant_id AND v.confirmation_id=NEW.id AND v.operation=NEW.operation)<>1) THEN
  RAISE EXCEPTION 'Consumed automation confirmation requires exactly one version' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END
"""

RECEIPT_GUARD = f"""
DECLARE scoped boolean=false;
BEGIN
 IF TG_OP<>'INSERT' THEN scoped=OLD.operation IN {OPS} OR OLD.subject_type='automation_rule'; END IF;
 IF TG_OP<>'DELETE' THEN scoped=scoped OR NEW.operation IN {OPS} OR NEW.subject_type='automation_rule'; END IF;
 IF scoped AND TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Automation receipt immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END
"""

MEMBER_GUARD = f"""
DECLARE scoped boolean=false; old_scoped boolean=false;
BEGIN
 IF TG_OP<>'DELETE' THEN SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.receipt_id AND (r.operation IN {OPS} OR r.subject_type='automation_rule')) INTO scoped; END IF;
 IF TG_OP<>'INSERT' THEN SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=OLD.tenant_id AND r.id=OLD.receipt_id AND (r.operation IN {OPS} OR r.subject_type='automation_rule')) INTO old_scoped; END IF;
 IF TG_OP<>'INSERT' AND (scoped OR old_scoped) THEN
  IF TG_OP='UPDATE' AND TG_TABLE_NAME='outbox_events' AND (to_jsonb(NEW)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) IS NOT DISTINCT FROM (to_jsonb(OLD)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Automation audit event or original key immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END
"""

MEMBER_TARGET = f"""
DECLARE r public.action_receipts;
BEGIN
 IF TG_TABLE_NAME='action_receipts' THEN r=NEW; ELSE SELECT * INTO r FROM public.action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id; END IF;
 IF r.operation IN {OPS} OR r.subject_type='automation_rule' THEN
  IF r.operation NOT IN {OPS} OR r.subject_type<>'automation_rule' THEN RAISE EXCEPTION 'Automation operation and subject must match' USING ERRCODE='23514'; END IF;
  PERFORM public.assert_automation_members(r.tenant_id,r.subject_id);
 END IF;
 RETURN NULL;
END
"""


def functions():
    return (
        ("assert_automation_members", "t uuid,target uuid", MEMBERS, "void"),
        ("assert_automation_version", "t uuid,target uuid", VERSION_ATOM, "void"),
        ("assert_automation_occurrence", "t uuid,target uuid", OCCURRENCE_ATOM, "void"),
        ("protect_automation_current", "", CURRENT_GUARD, "trigger"),
        ("require_automation_current", "", CURRENT_ATOM, "trigger"),
        ("protect_automation_confirmation", "", PROOF, "trigger"),
        ("require_automation_confirmation", "", PROOF_TARGET, "trigger"),
        ("protect_automation_receipt", "", RECEIPT_GUARD, "trigger"),
        ("protect_automation_member", "", MEMBER_GUARD, "trigger"),
        ("require_automation_member", "", MEMBER_TARGET, "trigger"),
        (
            "reject_automation_mutation",
            "",
            "BEGIN RAISE EXCEPTION 'Automation facts are immutable' USING ERRCODE='23514'; END",
            "trigger",
        ),
        (
            "require_automation_version",
            "",
            "BEGIN PERFORM public.assert_automation_version(NEW.tenant_id,NEW.id); RETURN NULL; END",
            "trigger",
        ),
        (
            "require_automation_occurrence",
            "",
            "BEGIN PERFORM public.assert_automation_occurrence(NEW.tenant_id,NEW.id); RETURN NULL; END",
            "trigger",
        ),
    )


def function_sql():
    return tuple(_function(*row[:3], row[3]) for row in functions())


def signatures():
    return tuple(
        f"{name}({','.join(arg.split()[-1] for arg in args.split(',')) if args else ''})"
        for name, args, _, _ in functions()
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
        read = "public.category_access(tenant_id,category_id) AND owner_id=public.scope_requester()"
        write = f"{read} AND public.category_access(tenant_id,category_id,true) AND owner_id=public.scope_actor() AND EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id={name}.tenant_id AND h.id={name}.owner_id AND h.active AND h.kind='human')"
        statements.extend(
            (
                f'ALTER TABLE public."{name}" ENABLE ROW LEVEL SECURITY',
                f'ALTER TABLE public."{name}" FORCE ROW LEVEL SECURITY',
                f'CREATE POLICY owner_internal ON public."{name}" TO pdos_next_owner USING(true) WITH CHECK(true)',
                f'CREATE POLICY automation_read ON public."{name}" FOR SELECT TO {app_role},{agent_role} USING({read})',
                f'CREATE POLICY automation_insert ON public."{name}" FOR INSERT TO {app_role} WITH CHECK({write})',
                f'REVOKE ALL ON public."{name}" FROM PUBLIC,{app_role},{agent_role},pdos_next_auth,pdos_next_dispatch',
                f'GRANT SELECT ON public."{name}" TO {app_role},{agent_role}',
                f'GRANT INSERT ON public."{name}" TO {app_role}',
            )
        )
        if table is TABLES[1]:
            statements.extend(
                (
                    f'CREATE POLICY automation_advance ON public."{name}" FOR UPDATE TO {app_role} USING({write}) WITH CHECK({write})',
                    f'GRANT UPDATE(version_id,revision,state,draft_version_id,published_version_id,admitted_count,last_admitted_at) ON public."{name}" TO {app_role}',
                )
            )
    return tuple(statements)


def trigger_sql():
    statements = []
    for table in TABLES:
        statements.extend(
            (
                f"CREATE TRIGGER automation_category_immutable BEFORE UPDATE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.protect_category_binding()",
                f"CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.lifecycle_reference_gate()",
                f"CREATE TRIGGER category_lifecycle_clock AFTER INSERT OR UPDATE OR DELETE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.category_lifecycle_clock()",
            )
        )
    for table, stem in ((TABLES[0], "version"), (TABLES[2], "occurrence")):
        statements.extend(
            (
                f"CREATE TRIGGER automation_immutable BEFORE UPDATE OR DELETE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.reject_automation_mutation()",
                f"CREATE CONSTRAINT TRIGGER automation_fact_atom AFTER INSERT ON public.{table.name} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_automation_{stem}()",
            )
        )
    statements.extend(
        (
            "CREATE TRIGGER automation_current_guard BEFORE INSERT OR UPDATE OR DELETE ON public.automation_rule_currents FOR EACH ROW EXECUTE FUNCTION public.protect_automation_current()",
            "CREATE CONSTRAINT TRIGGER automation_current_atom AFTER INSERT OR UPDATE ON public.automation_rule_currents DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_automation_current()",
            "CREATE TRIGGER automation_proof_guard BEFORE INSERT OR UPDATE OR DELETE ON public.confirmations FOR EACH ROW EXECUTE FUNCTION public.protect_automation_confirmation()",
            "CREATE CONSTRAINT TRIGGER automation_proof_target AFTER UPDATE ON public.confirmations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_automation_confirmation()",
            "CREATE TRIGGER automation_receipt_guard BEFORE INSERT OR UPDATE OR DELETE ON public.action_receipts FOR EACH ROW EXECUTE FUNCTION public.protect_automation_receipt()",
        )
    )
    for table in ("action_receipts", "audit_entries", "outbox_events", "request_keys"):
        statements.append(
            f"CREATE CONSTRAINT TRIGGER automation_member_atom AFTER INSERT ON public.{table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_automation_member()"
        )
        if table != "action_receipts":
            statements.append(
                f"CREATE TRIGGER automation_member_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.protect_automation_member()"
            )
    return tuple(statements)


def upgrade_sql(app_role="pdos_next_app", agent_role="pdos_agent"):
    app_role, agent_role = _role(app_role), _role(agent_role)
    return (
        *table_sql(),
        *function_sql(),
        *(
            f"REVOKE ALL ON FUNCTION public.{name} FROM PUBLIC,{app_role},{agent_role},pdos_next_auth,pdos_next_dispatch"
            for name in signatures()
        ),
        *policy_sql(app_role, agent_role),
        *trigger_sql(),
    )


def downgrade_sql():
    return (
        "LOCK TABLE "
        + ",".join(f"public.{table.name}" for table in TABLES)
        + ",public.confirmations,public.action_receipts IN ACCESS EXCLUSIVE MODE",
        "DO $automation$ BEGIN IF "
        + " OR ".join(f"EXISTS(SELECT 1 FROM public.{table.name})" for table in TABLES)
        + f" OR EXISTS(SELECT 1 FROM public.confirmations WHERE operation IN {T1}) OR EXISTS(SELECT 1 FROM public.action_receipts WHERE operation IN {OPS} OR subject_type='automation_rule') THEN RAISE EXCEPTION 'Automation history retained; downgrade refused' USING ERRCODE='23514'; END IF; END; $automation$",
        "DROP TRIGGER automation_proof_guard ON public.confirmations",
        "DROP TRIGGER automation_proof_target ON public.confirmations",
        "DROP TRIGGER automation_receipt_guard ON public.action_receipts",
        *(
            f"DROP TRIGGER automation_member_atom ON public.{name}"
            for name in ("action_receipts", "audit_entries", "outbox_events", "request_keys")
        ),
        *(
            f"DROP TRIGGER automation_member_guard ON public.{name}"
            for name in ("audit_entries", "outbox_events", "request_keys")
        ),
        *(f"DROP TABLE public.{table.name}" for table in reversed(TABLES)),
        *(f"DROP FUNCTION public.{name}" for name in reversed(signatures())),
    )
