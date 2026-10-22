"""Finite SQL declarations for native G0 risk follow-up; never an installer.

Shared guards are extended from actual captured predecessors. The root migration
owns head allocation, subject/lifecycle visibility, and ordinary function owners.
"""

# ruff: noqa: E501 -- finite PostgreSQL predicates stay readable as complete expressions.

from collections.abc import Mapping

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from pdos_next import models as registered_models  # noqa: F401 -- full registry before child DDL
from pdos_next.domain.external_wait.models import OPERATION as WAIT_OPERATION
from pdos_next.domain.external_wait.models import SUBJECT as WAIT_SUBJECT
from pdos_next.domain.work_management import storage_schema as work_storage

from .models import (
    CURRENT,
    EFFECT,
    FOLLOWUP,
    OPERATION,
    SUBJECT,
    ProjectRiskFollowup,
    ProjectRiskFollowupCurrent,
)

TABLES = (ProjectRiskFollowup.__table__, ProjectRiskFollowupCurrent.__table__)
CURRENT_GUARD = work_storage.current_guard(
    CURRENT, FOLLOWUP, "previous_id", "previous_revision", ("version_id", "revision", "state")
)
CURRENT_ATOM = work_storage.current_atom(CURRENT, FOLLOWUP)
MEMBERS_SIGNATURE = "assert_work_management_members(uuid,uuid,text)"
WRITE_SIGNATURE = "assert_work_management_write(uuid,uuid,text)"
COMMON_SIGNATURES = (
    MEMBERS_SIGNATURE,
    WRITE_SIGNATURE,
    "protect_work_receipt()",
    "protect_work_member()",
    "require_work_member()",
    "protect_work_confirmation()",
    "require_work_confirmation()",
)
PREDECESSOR_OPS = work_storage.OPS[:-1] + "," + repr(WAIT_OPERATION) + ")"
PREDECESSOR_SUBJECTS = work_storage.SUBJECTS[:-1] + "," + repr(WAIT_SUBJECT) + ")"


def _once(value, anchor, replacement):
    if value.count(anchor) != 1:
        raise ValueError(f"Actual risk-follow-up predecessor requires one exact anchor: {anchor}")
    return value.replace(anchor, replacement, 1)


def _captured(definitions, signature):
    name = signature.partition("(")[0]
    value = definitions.get(signature)
    if not isinstance(value, str) or f"FUNCTION public.{name}(" not in value:
        raise ValueError(f"Missing actual captured function: {signature}")
    if "SECURITY DEFINER" not in value or "SET search_path" not in value:
        raise ValueError(f"Actual captured guard lost its owner/search-path contract: {signature}")
    if "public.project_risk_followups" in value or OPERATION in value:
        raise ValueError(f"Risk follow-up already present in captured guard: {signature}")
    return value


def upgraded_common_functions(definitions: Mapping[str, str]) -> dict[str, str]:
    """Add one T1 subject, preserving real source checks and existing T0 rules."""
    values = {signature: _captured(definitions, signature) for signature in COMMON_SIGNATURES}
    selector = " ELSE RAISE EXCEPTION 'Unknown work subject' USING ERRCODE='23514'; END IF;"
    for signature in (MEMBERS_SIGNATURE, WRITE_SIGNATURE):
        values[signature] = _once(
            values[signature],
            selector,
            " ELSIF kind='risk_followup' THEN SELECT * INTO STRICT v FROM public.project_risk_followups WHERE tenant_id=t AND id=target;\n"
            + selector,
        )
    values[MEMBERS_SIGNATURE] = _once(
        values[MEMBERS_SIGNATURE],
        "CASE WHEN kind IN ('work_task','external_wait') THEN v.body->>'state' ELSE 'recorded' END",
        "CASE WHEN kind IN ('work_task','external_wait','risk_followup') THEN v.body->>'state' ELSE 'recorded' END",
    )
    result_anchor = " ELSE expected_result=expected_result||jsonb_build_object('project_id',v.project_id); END IF;"
    values[MEMBERS_SIGNATURE] = _once(
        values[MEMBERS_SIGNATURE],
        result_anchor,
        " ELSIF kind='risk_followup' THEN expected_result=expected_result||jsonb_build_object('risk_id',v.risk_id,'decision_id',v.g0_decision_id,'state',v.state,'project_id',v.project_id);\n"
        + result_anchor,
    )
    values[MEMBERS_SIGNATURE] = _once(
        values[MEMBERS_SIGNATURE],
        "WHEN 'work.external_wait.record' THEN 'external_wait.recorded' END;",
        "WHEN 'work.external_wait.record' THEN 'external_wait.recorded' WHEN 'work.risk.followup.record' THEN 'risk.followup_recorded' END;",
    )
    xmin_anchor = " ELSE SELECT xmin INTO vx FROM public.project_status_updates WHERE tenant_id=t AND id=target; END IF;"
    values[WRITE_SIGNATURE] = _once(
        values[WRITE_SIGNATURE],
        xmin_anchor,
        " ELSIF kind='risk_followup' THEN SELECT xmin INTO vx FROM public.project_risk_followups WHERE tenant_id=t AND id=target;\n"
        + xmin_anchor,
    )
    values[WRITE_SIGNATURE] = _once(
        values[WRITE_SIGNATURE],
        " ELSIF v.source_basis ? 'g0_open_item' THEN",
        " ELSIF kind<>'risk_followup' AND v.source_basis ? 'g0_open_item' THEN",
    )
    for signature, repetitions in (
        ("protect_work_receipt()", 2),
        ("protect_work_member()", 2),
        ("require_work_member()", 1),
    ):
        for anchor, extra in ((PREDECESSOR_OPS, OPERATION), (PREDECESSOR_SUBJECTS, SUBJECT)):
            if values[signature].count(anchor) != repetitions:
                raise ValueError(f"Actual common work scope changed: {signature}")
            values[signature] = values[signature].replace(
                anchor, anchor[:-1] + "," + repr(extra) + ")"
            )
    for signature, repetitions in (
        ("protect_work_confirmation()", 2),
        ("require_work_confirmation()", 1),
    ):
        anchor = work_storage.T1
        if values[signature].count(anchor) != repetitions:
            raise ValueError(f"Actual work confirmation scope changed: {signature}")
        values[signature] = values[signature].replace(
            anchor, anchor[:-1] + "," + repr(OPERATION) + ")"
        )
    confirmation_anchor = "   UNION ALL SELECT confirmation_id FROM public.project_status_updates WHERE tenant_id=NEW.tenant_id AND confirmation_id=NEW.id AND operation=NEW.operation) refs;"
    values["require_work_confirmation()"] = _once(
        values["require_work_confirmation()"],
        confirmation_anchor,
        "   UNION ALL SELECT confirmation_id FROM public.project_status_updates WHERE tenant_id=NEW.tenant_id AND confirmation_id=NEW.id AND operation=NEW.operation\n"
        "   UNION ALL SELECT confirmation_id FROM public.project_risk_followups WHERE tenant_id=NEW.tenant_id AND confirmation_id=NEW.id AND operation=NEW.operation) refs;",
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
        write = (
            "public.category_access(tenant_id,category_id,true) "
            "AND public.scope_actor()=public.scope_requester() "
            "AND EXISTS(SELECT 1 FROM public.principals h "
            "WHERE h.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid "
            "AND h.id=public.scope_actor() AND h.kind='human' AND h.active)"
        )
        statements.extend(
            (
                f'ALTER TABLE public."{name}" ENABLE ROW LEVEL SECURITY',
                f'ALTER TABLE public."{name}" FORCE ROW LEVEL SECURITY',
                f'CREATE POLICY owner_internal ON public."{name}" TO pdos_next_owner USING(true) WITH CHECK(true)',
                f'CREATE POLICY risk_followup_read ON public."{name}" FOR SELECT TO pdos_next_app USING({read})',
                f'CREATE POLICY risk_followup_insert ON public."{name}" FOR INSERT TO pdos_next_app WITH CHECK({write} AND {read})',
                f'REVOKE ALL ON public."{name}" FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
                f'GRANT SELECT,INSERT ON public."{name}" TO pdos_next_app',
            )
        )
        if table.name == CURRENT:
            statements.extend(
                (
                    f'CREATE POLICY risk_followup_advance ON public."{name}" FOR UPDATE TO pdos_next_app USING({write} AND {read}) WITH CHECK({write} AND {read})',
                    f'GRANT UPDATE(version_id,revision,state) ON public."{name}" TO pdos_next_app',
                )
            )
    return tuple(statements)


RISK_ATOM = r"""
DECLARE v public.project_risk_followups; prior public.project_risk_followups;
 cur public.project_risk_followup_currents; oi public.project_open_items; p public.projects;
 receipt public.action_receipts; payload jsonb; native jsonb; expected_native jsonb; expected jsonb;
 vx xid; cx xid;
BEGIN
 SELECT * INTO STRICT v FROM public.project_risk_followups WHERE tenant_id=t AND id=target;
 SELECT xmin INTO vx FROM public.project_risk_followups WHERE tenant_id=t AND id=target;
 SELECT * INTO STRICT cur FROM public.project_risk_followup_currents WHERE tenant_id=t AND product_id=v.product_id AND risk_id=v.risk_id;
 SELECT xmin INTO cx FROM public.project_risk_followup_currents WHERE tenant_id=t AND id=cur.id;
 PERFORM public.assert_work_management_write(t,target,'risk_followup');
 SELECT * INTO STRICT p FROM public.projects WHERE tenant_id=t AND id=v.project_id;
 SELECT * INTO STRICT receipt FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;
 SELECT * INTO oi FROM public.project_open_items x WHERE x.tenant_id=t AND x.category_id=v.category_id
  AND x.product_id=v.product_id AND x.project_id=v.project_id AND x.id=v.risk_id AND x.g0_decision_id=v.g0_decision_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'Risk follow-up requires one actual native G0 project item' USING ERRCODE='23514'; END IF;
 payload=v.command->'envelope'->'payload'; native=v.source_basis->'g0_open_item';
 expected_native=jsonb_build_object('id',oi.id,'decision_id',oi.g0_decision_id,'kind',oi.kind,
  'title',oi.title,'note',oi.note,'owner_id',oi.owner_id,'due_date',oi.due_date::text,
  'source_question_id',oi.source_question_id,'source_spec_item_id',oi.source_spec_item_id,
  'category_id',oi.category_id,'product_id',oi.product_id,'project_id',oi.project_id);
 IF oi.kind<>'risk' OR oi.status<>'open' OR p.g0_decision_id IS DISTINCT FROM oi.g0_decision_id
  OR jsonb_typeof(native) IS DISTINCT FROM 'object' OR (native-'digest') IS DISTINCT FROM expected_native
  OR native->>'digest' IS NULL OR native->>'digest' !~ '^[a-f0-9]{64}$'
  OR v.actor_id IS DISTINCT FROM oi.owner_id OR v.requester_id IS DISTINCT FROM oi.owner_id
  OR v.writer_id IS DISTINCT FROM oi.owner_id OR receipt.run_id IS NOT NULL OR receipt.agent_run_id IS NOT NULL
  OR NOT EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id=t AND h.id=oi.owner_id AND h.kind='human' AND h.active)
  OR payload->'risk' IS DISTINCT FROM jsonb_build_object('id',v.risk_id,'decision_id',v.g0_decision_id)
  OR payload->>'action' IS DISTINCT FROM v.action
  OR v.command->'review'->>'effect' IS DISTINCT FROM '__EFFECT__'
  OR jsonb_typeof(payload->'summary') IS DISTINCT FROM 'string' OR length(btrim(payload->>'summary'))=0
  OR vx IS DISTINCT FROM cx
  OR ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.risk_id,cur.g0_decision_id,cur.version_id,cur.revision,cur.state)
   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.risk_id,v.g0_decision_id,v.id,v.revision,v.state) THEN
  RAISE EXCEPTION 'Risk follow-up requires its fixed G0 responsibility and exact same-transaction Current' USING ERRCODE='23514'; END IF;
 expected=jsonb_build_object('risk_id',v.risk_id,'decision_id',v.g0_decision_id,'revision',v.revision,'state',v.state,'summary',payload->'summary');
 IF v.body IS DISTINCT FROM expected THEN
  RAISE EXCEPTION 'Risk follow-up records only its exact internal result body' USING ERRCODE='23514'; END IF;
 IF v.revision=1 THEN
  IF v.action<>'close' OR v.state<>'closed'
   OR coalesce(payload->'current','null'::jsonb)<>'null'::jsonb
   OR coalesce(v.command->'review'->'before','null'::jsonb)<>'null'::jsonb THEN
   RAISE EXCEPTION 'First native risk follow-up closes only the open internal record' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT * INTO STRICT prior FROM public.project_risk_followups WHERE tenant_id=t AND id=v.previous_id;
  IF payload->'current' IS DISTINCT FROM jsonb_build_object('id',prior.id,'revision',prior.revision)
   OR v.command->'review'->'before' IS DISTINCT FROM prior.body
   OR native IS DISTINCT FROM prior.source_basis->'g0_open_item'
   OR NOT((prior.state='closed' AND v.action='reopen' AND v.state='open')
       OR (prior.state='open' AND v.action='close' AND v.state='closed')) THEN
   RAISE EXCEPTION 'Risk follow-up requires one exact reversal of its retained predecessor' USING ERRCODE='23514'; END IF;
 END IF;
END
""".replace("__EFFECT__", EFFECT.replace("'", "''"))


def functions():
    return (
        ("assert_project_risk_followup", "t uuid,target uuid", RISK_ATOM, "void"),
        (
            "require_project_risk_followup",
            "",
            "BEGIN PERFORM public.assert_project_risk_followup(NEW.tenant_id,NEW.id); RETURN NULL; END",
            "trigger",
        ),
        ("protect_project_risk_followup_current", "", CURRENT_GUARD, "trigger"),
        ("require_project_risk_followup_current", "", CURRENT_ATOM, "trigger"),
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
        f"CREATE TRIGGER risk_followup_immutable BEFORE UPDATE OR DELETE ON public.{FOLLOWUP} "
        "FOR EACH ROW EXECUTE FUNCTION public.reject_work_mutation()",
        f"CREATE CONSTRAINT TRIGGER risk_followup_atom AFTER INSERT ON public.{FOLLOWUP} "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_project_risk_followup()",
        f"CREATE TRIGGER risk_followup_current_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{CURRENT} "
        "FOR EACH ROW EXECUTE FUNCTION public.protect_project_risk_followup_current()",
        f"CREATE CONSTRAINT TRIGGER risk_followup_current_atom AFTER INSERT OR UPDATE ON public.{CURRENT} "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_project_risk_followup_current()",
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
        f"LOCK TABLE public.{FOLLOWUP},public.{CURRENT},public.action_receipts,public.confirmations IN ACCESS EXCLUSIVE MODE",
        f"DO $risk_followup$ BEGIN IF EXISTS(SELECT 1 FROM public.{FOLLOWUP}) OR EXISTS(SELECT 1 FROM public.{CURRENT}) "
        "OR EXISTS(SELECT 1 FROM public.action_receipts WHERE operation='work.risk.followup.record' OR subject_type='risk_followup') "
        "OR EXISTS(SELECT 1 FROM public.confirmations WHERE operation='work.risk.followup.record') "
        "THEN RAISE EXCEPTION 'Risk follow-up history retained; downgrade refused' USING ERRCODE='23514'; END IF; END; $risk_followup$",
        *(original[signature] for signature in COMMON_SIGNATURES),
        *(f"DROP TABLE public.{table.name}" for table in reversed(TABLES)),
        *(f"DROP FUNCTION public.{signature}" for signature in reversed(signatures())),
    )
