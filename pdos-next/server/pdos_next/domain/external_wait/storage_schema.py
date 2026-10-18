"""External wait SQL declarations; shared-guard predecessors come from the host.

No SQL is executed here. The migration owns actual head, common subject/lifecycle
registration and the ordinary-owner installation of these finite guards.
"""

# ruff: noqa: E501 -- finite SQL guards stay readable as complete expressions.

from collections.abc import Mapping

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from pdos_next import models as registered_models  # noqa: F401 -- full registry before child DDL
from pdos_next.domain.work_management import storage_schema as work_storage

from .models import CURRENT, OPERATION, SUBJECT, WAIT, ExternalWaitCurrent, ExternalWaitVersion

TABLES = (ExternalWaitVersion.__table__, ExternalWaitCurrent.__table__)
CURRENT_GUARD = work_storage.current_guard(
    CURRENT, WAIT, "previous_id", "previous_revision", ("version_id", "revision", "state")
)
CURRENT_ATOM = work_storage.current_atom(CURRENT, WAIT)
MEMBERS_SIGNATURE = "assert_work_management_members(uuid,uuid,text)"
WRITE_SIGNATURE = "assert_work_management_write(uuid,uuid,text)"
COMMON_SIGNATURES = (
    MEMBERS_SIGNATURE,
    WRITE_SIGNATURE,
    "protect_work_receipt()",
    "protect_work_member()",
    "require_work_member()",
)


def _once(value, anchor, replacement):
    if value.count(anchor) != 1:
        raise ValueError(f"Actual external-wait predecessor requires one exact anchor: {anchor}")
    return value.replace(anchor, replacement, 1)


def _captured(definitions, signature):
    name = signature.partition("(")[0]
    value = definitions.get(signature)
    if not isinstance(value, str) or f"FUNCTION public.{name}(" not in value:
        raise ValueError(f"Missing actual captured function: {signature}")
    if "SECURITY DEFINER" not in value or "SET search_path" not in value:
        raise ValueError(f"Actual captured guard lost its owner/search-path contract: {signature}")
    if "public.external_wait_versions" in value or OPERATION in value:
        raise ValueError(f"External waiting already present in captured guard: {signature}")
    return value


def upgraded_common_functions(definitions: Mapping[str, str]) -> dict[str, str]:
    """Extend only explicit subjects/T0 operation, preserving captured artifact IO guards."""
    values = {signature: _captured(definitions, signature) for signature in COMMON_SIGNATURES}
    selector = " ELSE RAISE EXCEPTION 'Unknown work subject' USING ERRCODE='23514'; END IF;"
    for signature in (MEMBERS_SIGNATURE, WRITE_SIGNATURE):
        values[signature] = _once(
            values[signature],
            selector,
            " ELSIF kind='external_wait' THEN SELECT * INTO STRICT v FROM public.external_wait_versions WHERE tenant_id=t AND id=target;\n"
            + selector,
        )
    values[MEMBERS_SIGNATURE] = _once(
        values[MEMBERS_SIGNATURE],
        "CASE WHEN kind='work_task' THEN v.body->>'state' ELSE 'recorded' END",
        "CASE WHEN kind IN ('work_task','external_wait') THEN v.body->>'state' ELSE 'recorded' END",
    )
    result_anchor = " ELSE expected_result=expected_result||jsonb_build_object('project_id',v.project_id); END IF;"
    values[MEMBERS_SIGNATURE] = _once(
        values[MEMBERS_SIGNATURE],
        result_anchor,
        " ELSIF kind='external_wait' THEN expected_result=expected_result||jsonb_build_object('wait_id',v.wait_id,'state',v.state,'project_id',v.project_id);\n"
        + result_anchor,
    )
    event_anchor = "WHEN 'work.status_update.create' THEN 'project.status_updated' END;"
    values[MEMBERS_SIGNATURE] = _once(
        values[MEMBERS_SIGNATURE],
        event_anchor,
        "WHEN 'work.status_update.create' THEN 'project.status_updated' WHEN 'work.external_wait.record' THEN 'external_wait.recorded' END;",
    )
    values[MEMBERS_SIGNATURE] = _once(
        values[MEMBERS_SIGNATURE],
        "IF v.operation<>'work.task.create' THEN",
        "IF v.operation NOT IN ('work.task.create','work.external_wait.record') THEN",
    )
    xmin_anchor = " ELSE SELECT xmin INTO vx FROM public.project_status_updates WHERE tenant_id=t AND id=target; END IF;"
    values[WRITE_SIGNATURE] = _once(
        values[WRITE_SIGNATURE],
        xmin_anchor,
        " ELSIF kind='external_wait' THEN SELECT xmin INTO vx FROM public.external_wait_versions WHERE tenant_id=t AND id=target;\n"
        + xmin_anchor,
    )
    values[WRITE_SIGNATURE] = _once(
        values[WRITE_SIGNATURE],
        "v.operation<>'work.task.create' AND",
        "v.operation NOT IN ('work.task.create','work.external_wait.record') AND",
    )
    values[WRITE_SIGNATURE] = _once(
        values[WRITE_SIGNATURE],
        "v.operation='work.task.create' AND v.actor_id<>v.requester_id",
        "v.operation IN ('work.task.create','work.external_wait.record') AND v.actor_id<>v.requester_id",
    )
    for signature, repetitions in (
        ("protect_work_receipt()", 2),
        ("protect_work_member()", 2),
        ("require_work_member()", 1),
    ):
        for anchor, extra in ((work_storage.OPS, OPERATION), (work_storage.SUBJECTS, SUBJECT)):
            if values[signature].count(anchor) != repetitions:
                raise ValueError(f"Actual common work scope changed: {signature}")
            values[signature] = values[signature].replace(
                anchor, anchor[:-1] + "," + repr(extra) + ")"
            )
    return values


def table_sql():
    return tuple(
        str(statement.compile(dialect=postgresql.dialect()))
        for table in TABLES
        for statement in (
            CreateTable(table),
            *(CreateIndex(index) for index in sorted(table.indexes, key=lambda value: value.name)),
        )
    )


def policy_sql():
    statements = []
    for table in TABLES:
        name = table.name
        read = (
            "public.category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM public.projects p "
            f"WHERE p.tenant_id={name}.tenant_id AND p.category_id={name}.category_id "
            f"AND p.product_id={name}.product_id AND p.id={name}.project_id "
            f"AND p.owner_id={name}.owner_id AND p.visibility={name}.visibility)"
        )
        write = "public.category_access(tenant_id,category_id,true)"
        statements.extend(
            (
                f'ALTER TABLE public."{name}" ENABLE ROW LEVEL SECURITY',
                f'ALTER TABLE public."{name}" FORCE ROW LEVEL SECURITY',
                f'CREATE POLICY owner_internal ON public."{name}" TO pdos_next_owner USING(true) WITH CHECK(true)',
                f'CREATE POLICY external_wait_read ON public."{name}" FOR SELECT TO pdos_next_app USING({read})',
                f'CREATE POLICY external_wait_insert ON public."{name}" FOR INSERT TO pdos_next_app WITH CHECK({write} AND {read})',
                f'REVOKE ALL ON public."{name}" FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
                f'GRANT SELECT,INSERT ON public."{name}" TO pdos_next_app',
            )
        )
        if table.name == CURRENT:
            statements.extend(
                (
                    f'CREATE POLICY external_wait_advance ON public."{name}" FOR UPDATE TO pdos_next_app USING({write} AND {read}) WITH CHECK({write} AND {read})',
                    f'GRANT UPDATE(version_id,revision,state) ON public."{name}" TO pdos_next_app',
                )
            )
    return tuple(statements)


CALENDAR_ATOM = r"""
DECLARE v public.external_wait_versions; cal jsonb; ref jsonb;
BEGIN
 SELECT * INTO STRICT v FROM public.external_wait_versions WHERE tenant_id=t AND id=target;
 cal=v.source_basis->'calendar'; ref=v.body->'calendar';
 IF coalesce(ref,'null'::jsonb)='null'::jsonb THEN
  IF coalesce(cal,'null'::jsonb)<>'null'::jsonb THEN
   RAISE EXCEPTION 'No inline calendar or detached calendar basis may be supplied' USING ERRCODE='23514'; END IF;
  RETURN;
 END IF;
 IF jsonb_typeof(cal) IS DISTINCT FROM 'object' OR cal->'ref' IS DISTINCT FROM ref
  OR cal->'scope' IS DISTINCT FROM jsonb_build_object('tenant_id',t,'category_id',v.category_id,'product_id',v.product_id,'project_id',v.project_id)
  OR jsonb_typeof(cal->'source_calendar') IS DISTINCT FROM 'object'
  OR cal->>'digest' IS NULL OR cal->>'digest' !~ '^[a-f0-9]{64}$'
  OR cal->>'calendar_sha256' IS NULL OR cal->>'calendar_sha256' !~ '^[a-f0-9]{64}$'
  OR jsonb_typeof(cal->'material'->'source_basis'->'artifacts') IS DISTINCT FROM 'array'
  OR NOT coalesce((v.source_basis->'artifacts') @> (cal#>'{material,source_basis,artifacts}'),false) THEN
  RAISE EXCEPTION 'Calendar requires the exact native reference and retained direct sources' USING ERRCODE='23514'; END IF;
 IF ref->>'kind'='project_plan' THEN
  IF NOT EXISTS(SELECT 1 FROM public.plan_revisions pl JOIN public.plan_proposals pp
   ON pp.tenant_id=pl.tenant_id AND pp.category_id=pl.category_id AND pp.product_id=pl.product_id
    AND pp.project_id=pl.project_id AND pp.id=pl.proposal_id
   JOIN public.project_product_links link ON link.tenant_id=pl.tenant_id AND link.category_id=pl.category_id
    AND link.product_id=pl.product_id AND link.project_id=pl.project_id
   WHERE pl.tenant_id=t AND pl.category_id=v.category_id AND pl.product_id=v.product_id AND pl.project_id=v.project_id
    AND pl.id::text=ref->>'id' AND pl.revision::text=ref->>'revision' AND pl.status='applied'
    AND pl.id::text=cal->'material'->>'plan_id' AND pl.revision::text=cal->'material'->>'plan_revision'
    AND pp.id::text=cal->'material'->>'proposal_id' AND pp.revision::text=cal->'material'->>'proposal_revision'
    AND cal->'material'->'definition_ref'=jsonb_build_object('id',link.definition_id,'revision',link.definition_revision)
    AND pp.input_snapshot->'calendar'=cal->'source_calendar'
    AND ref->>'calendar_key'=pp.input_snapshot->'calendar'->>'key'
    AND ref->>'calendar_version'=pp.input_snapshot->'calendar'->>'version'
    AND coalesce(ref->'resource_id','null'::jsonb)='null'::jsonb) THEN
   RAISE EXCEPTION 'Calendar is not the selected actual project plan calendar' USING ERRCODE='23514'; END IF;
 ELSIF ref->>'kind'='build_resource' THEN
  IF NOT EXISTS(SELECT 1 FROM public.build_operational_facts fixed
   JOIN public.build_operational_current ptr ON ptr.tenant_id=fixed.tenant_id AND ptr.category_id=fixed.category_id
    AND ptr.product_id=fixed.product_id AND ptr.project_id=fixed.project_id AND ptr.build_id=fixed.build_id
   JOIN public.build_operational_facts live ON live.tenant_id=ptr.tenant_id AND live.category_id=ptr.category_id
    AND live.product_id=ptr.product_id AND live.project_id=ptr.project_id AND live.build_id=ptr.build_id
    AND live.id=ptr.fact_id AND live.revision=ptr.fact_revision AND live.series_id=fixed.series_id
   JOIN LATERAL jsonb_array_elements(fixed.data->'resources') res ON true
   JOIN LATERAL jsonb_array_elements(live.data->'resources') actual ON true
   JOIN public.operational_asset_sentinels asset ON asset.tenant_id=fixed.tenant_id
    AND asset.id::text=actual->'resource'->>'id' AND asset.revision::text=actual->'resource'->>'revision'
   WHERE fixed.tenant_id=t AND fixed.category_id=v.category_id AND fixed.product_id=v.product_id AND fixed.project_id=v.project_id
    AND fixed.id::text=ref->>'id' AND fixed.revision::text=ref->>'revision'
    AND fixed.id::text=cal->'material'->>'fact_id' AND fixed.revision::text=cal->'material'->>'fact_revision'
    AND fixed.fact_sha256=cal->'material'->>'fact_sha256' AND fixed.build_id::text=cal->'material'->>'build_id'
    AND fixed.state='active' AND fixed.valid_from<=v.created_at AND (fixed.valid_until IS NULL OR v.created_at<fixed.valid_until)
    AND live.state='active' AND live.valid_from<=v.created_at AND (live.valid_until IS NULL OR v.created_at<live.valid_until)
    AND res->'resource'->>'id'=ref->>'resource_id' AND actual->'resource'->>'id'=ref->>'resource_id'
    AND cal->'material'->>'resource_id'=ref->>'resource_id' AND res->'resource'->>'revision'=cal->'material'->>'resource_revision'
    AND res->>'lifecycle'='active' AND actual->>'lifecycle'='active'
    AND res->'calendar'=cal->'source_calendar' AND actual->'calendar'->>'calendar_id'=res->'calendar'->>'calendar_id'
    AND ref->>'calendar_key'=res->'calendar'->>'calendar_id' AND ref->>'calendar_version'=res->'calendar'->>'version'
    AND asset.kind='resource' AND asset.data->>'state'='active') THEN
   RAISE EXCEPTION 'Calendar is not a retained native resource with a currently usable source' USING ERRCODE='23514'; END IF;
 ELSE RAISE EXCEPTION 'Unknown native calendar source' USING ERRCODE='23514'; END IF;
END
"""


WAIT_ATOM = r"""
DECLARE v public.external_wait_versions; prior public.external_wait_versions;
 cur public.external_wait_currents; p public.projects; receipt public.action_receipts;
 payload jsonb; record jsonb; expected jsonb; entry jsonb; expected_entry jsonb;
 leaf text; human_actor boolean; vx xid; cx xid;
BEGIN
 SELECT * INTO STRICT v FROM public.external_wait_versions WHERE tenant_id=t AND id=target;
 SELECT xmin INTO vx FROM public.external_wait_versions WHERE tenant_id=t AND id=target;
 SELECT * INTO STRICT cur FROM public.external_wait_currents WHERE tenant_id=t AND product_id=v.product_id AND wait_id=v.wait_id;
 SELECT xmin INTO cx FROM public.external_wait_currents WHERE tenant_id=t AND id=cur.id;
 PERFORM public.assert_work_management_write(t,target,'external_wait');
 PERFORM public.assert_external_wait_calendar(t,target);
 SELECT * INTO STRICT p FROM public.projects WHERE tenant_id=t AND id=v.project_id;
 SELECT * INTO STRICT receipt FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;
 payload=v.command->'envelope'->'payload'; record=payload->'record';
 human_actor=v.actor_id=v.requester_id AND receipt.run_id IS NULL AND receipt.agent_run_id IS NULL
  AND EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id=t AND h.id=v.actor_id AND h.kind='human' AND h.active);
 IF vx IS DISTINCT FROM cx
  OR ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.wait_id,cur.version_id,cur.revision,cur.state)
   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.wait_id,v.id,v.revision,v.state)
  OR v.body->>'wait_id' IS DISTINCT FROM v.wait_id::text OR v.body->>'revision' IS DISTINCT FROM v.revision::text
  OR v.body->>'state' IS DISTINCT FROM v.state OR record->>'action' IS DISTINCT FROM v.action
  OR v.operation<>'work.external_wait.record' OR v.confirmation_id IS NOT NULL THEN
  RAISE EXCEPTION 'External wait requires its exact same-transaction version and Current' USING ERRCODE='23514'; END IF;
 IF v.revision=1 THEN
  IF v.action<>'create' OR v.state<>'open' OR v.wait_id<>v.id
   OR coalesce(payload->'wait','null'::jsonb)<>'null'::jsonb
   OR v.body->>'responsible_id' IS DISTINCT FROM v.requester_id::text
   OR (v.body->>'created_at')::timestamptz IS DISTINCT FROM v.created_at THEN
   RAISE EXCEPTION 'New external wait has the actual requester as responsible person' USING ERRCODE='23514'; END IF;
  IF coalesce(record->'milestone','null'::jsonb)<>'null'::jsonb AND NOT EXISTS(
   SELECT 1 FROM public.project_tasks m JOIN public.plan_revisions pl ON pl.tenant_id=m.tenant_id
    AND pl.category_id=m.category_id AND pl.product_id=m.product_id AND pl.project_id=m.project_id AND pl.id=m.plan_id
   WHERE m.tenant_id=t AND m.category_id=v.category_id AND m.product_id=v.product_id AND m.project_id=v.project_id
    AND m.id::text=record->'milestone'->>'id' AND pl.revision::text=record->'milestone'->>'revision') THEN
   RAISE EXCEPTION 'Waiting milestone must bind an actual task in the fixed project plan' USING ERRCODE='23514'; END IF;
  IF coalesce(record->'build','null'::jsonb)<>'null'::jsonb AND NOT EXISTS(
   SELECT 1 FROM public.builds b WHERE b.tenant_id=t AND b.category_id=v.category_id
    AND b.product_id=v.product_id AND b.project_id=v.project_id AND b.id::text=record->'build'->>'id'
    AND b.revision::text=record->'build'->>'revision') THEN
   RAISE EXCEPTION 'Waiting Build must bind its actual project and version' USING ERRCODE='23514'; END IF;
  expected=jsonb_build_object('title',record->'title','target',record->'target','request_content',record->'request_content',
   'closure_condition',record->'closure_condition','blocking',record->'blocking','next_check_at',record->'next_check_at',
   'original_timezone',record->'original_timezone','wait_id',v.wait_id,'revision',1,'state','open',
   'responsible_id',v.requester_id,'created_at',v.body->'created_at',
   'milestone',coalesce(record->'milestone','null'::jsonb),'build',coalesce(record->'build','null'::jsonb),
   'replaces',coalesce(record->'replaces','null'::jsonb),'calendar',coalesce(record->'calendar','null'::jsonb),
   'initiation',NULL,'delivery',NULL,'counterparty_commitment',NULL,'reply',NULL,'last_closure',NULL,'transfer',NULL);
 ELSE
  SELECT * INTO STRICT prior FROM public.external_wait_versions WHERE tenant_id=t AND id=v.previous_id;
  IF payload->'wait' IS DISTINCT FROM jsonb_build_object('id',v.wait_id,'revision',prior.revision)
   OR v.previous_revision<>prior.revision OR v.revision<>prior.revision+1
   OR ROW(prior.category_id,prior.product_id,prior.project_id,prior.owner_id,prior.visibility,prior.wait_id)
    IS DISTINCT FROM ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.wait_id) THEN
   RAISE EXCEPTION 'External wait action requires its exact stable identity and prior revision' USING ERRCODE='23514'; END IF;
  IF v.action<>'transfer_accept' AND v.requester_id::text NOT IN (prior.body->>'responsible_id',p.owner_id::text) THEN
   RAISE EXCEPTION 'Only current responsible person or project owner may record waiting facts' USING ERRCODE='23514'; END IF;
  IF NOT ((prior.state='closed' AND v.action='reopen') OR (prior.state='open' AND v.action<>'reopen')) THEN
   RAISE EXCEPTION 'Closed waiting must be explicitly reopened before recording more progress' USING ERRCODE='23514'; END IF;
  expected=prior.body||jsonb_build_object('revision',v.revision);
  IF v.action='details' THEN
   expected=expected||jsonb_build_object('title',record->'title','closure_condition',record->'closure_condition',
    'blocking',record->'blocking','next_check_at',record->'next_check_at',
    'original_timezone',record->'original_timezone','calendar',coalesce(record->'calendar','null'::jsonb));
  ELSIF v.action IN ('initiate','delivery','commitment','reply','close') THEN
   leaf=CASE v.action WHEN 'initiate' THEN 'initiation' WHEN 'delivery' THEN 'delivery'
    WHEN 'commitment' THEN 'counterparty_commitment' WHEN 'reply' THEN 'reply' ELSE 'last_closure' END;
   entry=v.body->leaf;
   IF jsonb_typeof(entry) IS DISTINCT FROM 'object'
    OR (entry->>'recorded_at')::timestamptz IS DISTINCT FROM v.created_at THEN
    RAISE EXCEPTION 'New waiting entry requires its server recording time' USING ERRCODE='23514'; END IF;
   expected_entry=jsonb_build_object('actor_id',v.actor_id,'requester_id',v.requester_id,
    'recorded_at',entry->'recorded_at','sources',payload->'sources');
   IF v.action='close' THEN expected_entry=expected_entry||jsonb_build_object('result',record->'result');
   ELSE expected_entry=expected_entry||jsonb_build_object('text',record->'text','original_timezone',record->'original_timezone'); END IF;
   IF v.action IN ('initiate','delivery','reply') THEN
    expected_entry=(expected_entry-'at')||jsonb_build_object('at',entry->'at',
     'time_basis',CASE WHEN human_actor THEN 'human_recorded' ELSE 'source_claim' END);
    IF v.action IN ('delivery','reply') THEN expected_entry=expected_entry||jsonb_build_object('status',record->'status'); END IF;
    IF (entry->>'at')::timestamptz IS DISTINCT FROM (record->>'at')::timestamptz
     OR (entry->>'at')::timestamptz>(entry->>'recorded_at')::timestamptz THEN
     RAISE EXCEPTION 'Waiting event time differs from its declared source' USING ERRCODE='23514'; END IF;
   ELSIF v.action='commitment' THEN
    expected_entry=(expected_entry-'promised_at')||jsonb_build_object('promised_at',entry->'promised_at');
    IF (entry->>'promised_at')::timestamptz IS DISTINCT FROM (record->>'promised_at')::timestamptz THEN
     RAISE EXCEPTION 'Counterparty stated date differs from its recorded source' USING ERRCODE='23514'; END IF;
   END IF;
   IF entry IS DISTINCT FROM expected_entry THEN
    RAISE EXCEPTION 'Waiting entry must retain the actual command authors and sources' USING ERRCODE='23514'; END IF;
   IF (v.action='delivery' AND entry->>'status' NOT IN ('effective','unverified','conflict'))
    OR (v.action='reply' AND entry->>'status' NOT IN ('partial','received','conflict','unknown')) THEN
    RAISE EXCEPTION 'Waiting entry has an unknown delivery or reply state' USING ERRCODE='23514'; END IF;
   IF v.action='delivery' AND (entry->>'status'='effective' OR prior.body->'delivery'->>'status'='effective') THEN
    IF NOT human_actor OR entry->>'time_basis' IS DISTINCT FROM 'human_recorded'
     OR (entry->>'status'='effective' AND (entry->>'at')::timestamptz IS NULL) THEN
     RAISE EXCEPTION 'Effective delivery and its correction require a real human record' USING ERRCODE='23514'; END IF;
   END IF;
   IF v.action='initiate' AND entry->>'time_basis'='human_recorded' AND entry->>'at' IS NOT NULL
    AND prior.body->'delivery'->>'status'='effective'
    AND (entry->>'at')::timestamptz>(prior.body->'delivery'->>'at')::timestamptz THEN
    RAISE EXCEPTION 'Human initiation conflicts with the previously verified delivery time' USING ERRCODE='23514'; END IF;
   IF v.action='delivery' AND entry->>'status'='effective'
    AND prior.body->'initiation'->>'time_basis'='human_recorded'
    AND (entry->>'at')::timestamptz<(prior.body->'initiation'->>'at')::timestamptz THEN
    RAISE EXCEPTION 'Verified delivery cannot precede its actual recorded initiation' USING ERRCODE='23514'; END IF;
   expected=jsonb_set(expected,ARRAY[leaf],entry);
   IF v.action='close' THEN expected=expected||jsonb_build_object('state','closed'); END IF;
  ELSIF v.action='reopen' THEN
   IF prior.state<>'closed' THEN RAISE EXCEPTION 'Only closed waiting can be reopened' USING ERRCODE='23514'; END IF;
   expected=expected||jsonb_build_object('state','open');
  ELSIF v.action='transfer_request' THEN
   entry=v.body->'transfer';
   IF coalesce(prior.body->'transfer','null'::jsonb)<>'null'::jsonb
    OR jsonb_typeof(entry) IS DISTINCT FROM 'object' OR (entry->>'request_id')::uuid IS NULL
    OR record->>'to_id' IS NOT DISTINCT FROM prior.body->>'responsible_id'
    OR (entry->>'requested_at')::timestamptz IS DISTINCT FROM v.created_at THEN
    RAISE EXCEPTION 'Responsibility transfer requires a new explicit pending request' USING ERRCODE='23514'; END IF;
   expected_entry=jsonb_build_object('request_id',entry->'request_id','from_id',prior.body->'responsible_id',
    'to_id',record->'to_id','actor_id',v.actor_id,'requested_at',entry->'requested_at','sources',payload->'sources');
   IF entry IS DISTINCT FROM expected_entry OR NOT EXISTS(SELECT 1 FROM public.principals h
    JOIN public.grants g ON g.tenant_id=h.tenant_id AND g.principal_id=h.id
    WHERE h.tenant_id=t AND h.id::text=record->>'to_id' AND h.kind='human' AND h.active
     AND g.category_id=v.category_id AND g.can_write AND (g.expires_at IS NULL OR v.created_at<g.expires_at)) THEN
    RAISE EXCEPTION 'Transfer must name one actual eligible human target' USING ERRCODE='23514'; END IF;
   expected=jsonb_set(expected,'{transfer}',entry);
  ELSIF v.action IN ('transfer_accept','transfer_cancel') THEN
   entry=prior.body->'transfer';
   IF jsonb_typeof(entry) IS DISTINCT FROM 'object'
    OR record->'request_id' IS DISTINCT FROM entry->'request_id'
    OR entry->'from_id' IS DISTINCT FROM prior.body->'responsible_id' THEN
    RAISE EXCEPTION 'Transfer action requires its exact outstanding request' USING ERRCODE='23514'; END IF;
   expected=expected||jsonb_build_object('transfer',NULL);
   IF v.action='transfer_accept' THEN
    IF NOT human_actor OR entry->>'to_id' IS DISTINCT FROM v.requester_id::text THEN
     RAISE EXCEPTION 'Only the named target can personally accept responsibility' USING ERRCODE='23514'; END IF;
    expected=expected||jsonb_build_object('responsible_id',entry->'to_id');
   END IF;
  ELSE RAISE EXCEPTION 'Unknown external wait transition' USING ERRCODE='23514'; END IF;
 END IF;
 IF v.body IS DISTINCT FROM expected THEN
  RAISE EXCEPTION 'External wait action cannot replace other fixed facts or responsibility' USING ERRCODE='23514'; END IF;
END
"""


def functions():
    return (
        ("assert_external_wait_calendar", "t uuid,target uuid", CALENDAR_ATOM, "void"),
        ("assert_external_wait", "t uuid,target uuid", WAIT_ATOM, "void"),
        (
            "require_external_wait",
            "",
            "BEGIN PERFORM public.assert_external_wait(NEW.tenant_id,NEW.id); RETURN NULL; END",
            "trigger",
        ),
        ("protect_external_wait_current", "", CURRENT_GUARD, "trigger"),
        ("require_external_wait_current", "", CURRENT_ATOM, "trigger"),
    )


def signatures():
    return tuple(
        name + "(" + ",".join(part.split()[-1] for part in args.split(",") if part) + ")"
        for name, args, _body, _returns in functions()
    )


def function_sql():
    return tuple(work_storage._function(*value) for value in functions())


def trigger_sql():
    return (
        f"CREATE TRIGGER external_wait_immutable BEFORE UPDATE OR DELETE ON public.{WAIT} "
        "FOR EACH ROW EXECUTE FUNCTION public.reject_work_mutation()",
        f"CREATE CONSTRAINT TRIGGER external_wait_atom AFTER INSERT ON public.{WAIT} "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_external_wait()",
        f"CREATE TRIGGER external_wait_current_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{CURRENT} "
        "FOR EACH ROW EXECUTE FUNCTION public.protect_external_wait_current()",
        f"CREATE CONSTRAINT TRIGGER external_wait_current_atom AFTER INSERT OR UPDATE ON public.{CURRENT} "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_external_wait_current()",
    )


def upgrade_sql(definitions: Mapping[str, str]):
    common = upgraded_common_functions(definitions)
    return (
        *table_sql(),
        *(common[signature] for signature in COMMON_SIGNATURES),
        *function_sql(),
        *(
            f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"
            for signature in signatures()
        ),
        *policy_sql(),
        *trigger_sql(),
    )


def downgrade_sql(definitions: Mapping[str, str]):
    original = {signature: _captured(definitions, signature) for signature in COMMON_SIGNATURES}
    return (
        f"LOCK TABLE public.{WAIT},public.{CURRENT},public.action_receipts IN ACCESS EXCLUSIVE MODE",
        f"DO $external_wait$ BEGIN IF EXISTS(SELECT 1 FROM public.{WAIT}) OR EXISTS(SELECT 1 FROM public.{CURRENT}) "
        "OR EXISTS(SELECT 1 FROM public.action_receipts WHERE operation='work.external_wait.record' OR subject_type='external_wait') "
        "THEN RAISE EXCEPTION 'External waiting history retained; downgrade refused' USING ERRCODE='23514'; END IF; END; $external_wait$",
        *(original[signature] for signature in COMMON_SIGNATURES),
        *(f"DROP TABLE public.{table.name}" for table in reversed(TABLES)),
        *(f"DROP FUNCTION public.{signature}" for signature in reversed(signatures())),
    )
