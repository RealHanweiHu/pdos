"""SQL declarations only. Root installs shared lifecycle and subject bindings."""

# ruff: noqa: E501 -- PostgreSQL predicates are kept intact.

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from .constants import CREATE, OPERATIONS
from .models import (
    ProjectStatusUpdate,
    WorkCommitmentCurrent,
    WorkCommitmentVersion,
    WorkTaskCurrent,
    WorkTaskVersion,
)

TABLES = tuple(
    value.__table__
    for value in (
        WorkTaskVersion,
        WorkTaskCurrent,
        WorkCommitmentVersion,
        WorkCommitmentCurrent,
        ProjectStatusUpdate,
    )
)
FACTS = (TABLES[0], TABLES[2], TABLES[4])
OPS = "(" + ",".join(repr(value) for value in OPERATIONS) + ")"
T1 = "(" + ",".join(repr(value) for value in OPERATIONS if value != CREATE) + ")"
SUBJECTS = "('work_task','work_commitment','project_status_update')"


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
    return f"CREATE FUNCTION public.{name}({args}) RETURNS {returns}\nLANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $work_management$\n{body.rstrip()};\n$work_management$"


SELECT_FACT = r"""
 IF kind='work_task' THEN SELECT * INTO STRICT v FROM public.work_task_versions WHERE tenant_id=t AND id=target;
 ELSIF kind='work_commitment' THEN SELECT * INTO STRICT v FROM public.work_commitment_versions WHERE tenant_id=t AND id=target;
 ELSIF kind='project_status_update' THEN SELECT * INTO STRICT v FROM public.project_status_updates WHERE tenant_id=t AND id=target;
 ELSE RAISE EXCEPTION 'Unknown work subject' USING ERRCODE='23514'; END IF;
"""

MEMBERS = r"""
DECLARE v record; r public.action_receipts; c public.confirmations; expected_status text; event_name text; expected_result jsonb;
BEGIN
__SELECT__
 expected_status=CASE WHEN kind='work_task' THEN v.body->>'state' ELSE 'recorded' END;
 expected_result=jsonb_build_object('id',v.id,'revision',v.revision,'status',expected_status);
 IF kind='work_task' THEN expected_result=expected_result||jsonb_build_object('task_id',v.task_id,'state',v.state,'project_id',v.project_id);
 ELSIF kind='work_commitment' THEN expected_result=expected_result||jsonb_build_object('task_id',v.task_id,'recipient_id',v.recipient_id);
 ELSE expected_result=expected_result||jsonb_build_object('project_id',v.project_id); END IF;
 event_name=CASE v.operation WHEN 'work.task.create' THEN 'task.created' WHEN 'work.task.assign' THEN 'task.assigned'
  WHEN 'work.task.accept' THEN 'task.accepted' WHEN 'work.task.start' THEN 'task.started'
  WHEN 'work.task.submit' THEN 'task.submitted' WHEN 'work.task.review' THEN 'task.reviewed'
  WHEN 'work.commitment.accept' THEN 'commitment.accepted' WHEN 'work.status_update.create' THEN 'project.status_updated' END;
 SELECT * INTO STRICT r FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;
 IF ROW(r.category_id,r.product_id,r.command_id,r.confirmation_id,r.actor_id,r.requester_id,r.operation,r.subject_type,r.subject_id,r.subject_revision,r.visibility,r.request_digest,r.intent_digest)
  IS DISTINCT FROM ROW(v.category_id,v.product_id,v.command_id,v.confirmation_id,v.actor_id,v.requester_id,v.operation,kind::varchar,v.id,v.revision,v.visibility,v.request_digest,v.intent_digest)
  OR r.result IS DISTINCT FROM expected_result
  OR r.created_at<v.created_at OR event_name IS NULL
  OR (SELECT count(*) FROM public.action_receipts x WHERE x.tenant_id=t AND x.operation=v.operation AND x.subject_type=kind AND x.subject_id=v.id AND x.subject_revision=v.revision)<>1
  OR (SELECT count(*) FROM public.audit_entries a WHERE a.tenant_id=t AND a.receipt_id=r.id)<>1
  OR NOT EXISTS(SELECT 1 FROM public.audit_entries a WHERE a.tenant_id=t AND a.receipt_id=r.id AND a.category_id=v.category_id AND a.actor_id=v.actor_id AND a.operation=v.operation AND a.created_at>=v.created_at)
  OR (SELECT count(*) FROM public.outbox_events e WHERE e.tenant_id=t AND e.receipt_id=r.id)<>1
  OR NOT EXISTS(SELECT 1 FROM public.outbox_events e WHERE e.tenant_id=t AND e.receipt_id=r.id AND e.category_id=v.category_id AND e.actor_id=v.actor_id AND e.type=event_name AND e.subject_id=v.id AND e.subject_revision=v.revision AND e.schema_version=1 AND e.correlation_id=coalesce(r.agent_run_id,r.run_id,v.command_id) AND e.created_at>=v.created_at)
  OR v.command->>'original_key_sha256' IS NULL OR v.command->>'original_key_sha256' !~ '^[a-f0-9]{64}$'
  OR v.command->'envelope' ? 'idempotency_key' OR v.command->'envelope'->'payload' ? 'confirmation_token'
  OR NOT EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=t AND k.category_id=v.category_id AND k.actor_id=v.actor_id AND k.receipt_id=r.id AND k.digest=v.request_digest AND encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.command->>'original_key_sha256') THEN
  RAISE EXCEPTION 'Work fact original common group mismatch' USING ERRCODE='23514'; END IF;
 IF v.operation<>'work.task.create' THEN
  SELECT * INTO STRICT c FROM public.confirmations WHERE tenant_id=t AND id=v.confirmation_id;
  IF c.consumed IS DISTINCT FROM true OR ROW(c.category_id,c.product_id,c.actor_id,c.operation)
   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.actor_id,v.operation)
   OR c.subject_type IS DISTINCT FROM 'product' OR c.subject_id IS DISTINCT FROM v.product_id
   OR c.revision::text IS DISTINCT FROM v.command->'envelope'->>'expected_revision'
   OR c.snapshot IS DISTINCT FROM v.command->'review' OR c.created_at>v.created_at
   OR c.expires_at IS NULL OR v.created_at>=c.expires_at OR r.created_at>=c.expires_at
   OR r.run_id IS NOT NULL OR r.agent_run_id IS NOT NULL THEN
   RAISE EXCEPTION 'Work T1 needs its actual consumed confirmation' USING ERRCODE='23514'; END IF;
 END IF;
END
""".replace("__SELECT__", SELECT_FACT)

WRITE_ATOM = r"""
DECLARE v record; p public.projects; envelope jsonb; ref jsonb; basis jsonb; vx xid; rx xid; cx xid;
BEGIN
__SELECT__
 IF kind='work_task' THEN SELECT xmin INTO vx FROM public.work_task_versions WHERE tenant_id=t AND id=target;
 ELSIF kind='work_commitment' THEN SELECT xmin INTO vx FROM public.work_commitment_versions WHERE tenant_id=t AND id=target;
 ELSE SELECT xmin INTO vx FROM public.project_status_updates WHERE tenant_id=t AND id=target; END IF;
 SELECT * INTO STRICT p FROM public.projects WHERE tenant_id=t AND id=v.project_id;
 SELECT xmin INTO rx FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;
 PERFORM public.assert_work_management_members(t,target,kind);
 envelope=v.command->'envelope';
 IF ROW(p.category_id,p.product_id,p.owner_id,p.visibility) IS DISTINCT FROM ROW(v.category_id,v.product_id,v.owner_id,v.visibility)
  OR v.actor_id IS DISTINCT FROM public.scope_actor() OR v.requester_id IS DISTINCT FROM public.scope_requester()
  OR v.writer_id<>v.actor_id OR vx IS DISTINCT FROM rx OR NOT public.category_access(t,v.category_id,true)
  OR NOT EXISTS(SELECT 1 FROM public.principals a WHERE a.tenant_id=t AND a.id=v.actor_id AND a.active)
  OR NOT EXISTS(SELECT 1 FROM public.principals a WHERE a.tenant_id=t AND a.id=v.requester_id AND a.kind='human' AND a.active)
  OR envelope->>'operation' IS DISTINCT FROM v.operation OR envelope->>'command_id' IS DISTINCT FROM v.command_id::text
  OR envelope->>'category_id' IS DISTINCT FROM v.category_id::text OR envelope->>'product_id' IS DISTINCT FROM v.product_id::text
  OR envelope->'payload'->>'project_id' IS DISTINCT FROM v.project_id::text
  OR v.command->'review'->'declaration' IS DISTINCT FROM envelope->'payload'
  OR v.command->'review'->>'operation' IS DISTINCT FROM v.operation
  OR v.command->'review'->'sources' IS DISTINCT FROM v.sources
  OR v.command->'review'->'source_basis' IS DISTINCT FROM v.source_basis
  OR (v.body #- '{recorded_at}' #- '{actual_start,recorded_at}' #- '{submission,time,recorded_at}' #- '{review,time,recorded_at}') IS DISTINCT FROM v.command->'review'->'after'
  OR NOT EXISTS(SELECT 1 FROM public.products x WHERE x.tenant_id=t AND x.category_id=v.category_id AND x.id=v.product_id AND x.revision::text=envelope->>'expected_revision')
  OR NOT COALESCE(envelope->'source_read_set' @> v.reads,false) OR NOT COALESCE(v.reads @> (envelope->'source_read_set'),false)
  OR jsonb_array_length(envelope->'source_read_set')<>jsonb_array_length(v.reads)
  OR NOT public.direct_source_set_visible(t,v.category_id,v.product_id,v.reads)
  OR (v.operation<>'work.task.create' AND (v.actor_id<>v.requester_id OR NOT EXISTS(SELECT 1 FROM public.principals a WHERE a.tenant_id=t AND a.id=v.actor_id AND a.kind='human')))
  OR (v.operation='work.task.create' AND v.actor_id<>v.requester_id AND NOT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=t AND r.id=v.receipt_id AND coalesce(r.agent_run_id,r.run_id) IS NOT NULL))
  OR EXISTS(SELECT 1 FROM public.audit_entries x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT FROM vx)
  OR EXISTS(SELECT 1 FROM public.outbox_events x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT FROM vx)
  OR NOT EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=t AND k.receipt_id=v.receipt_id AND k.actor_id=v.actor_id AND k.digest=v.request_digest AND k.xmin=vx AND encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.command->>'original_key_sha256') THEN
  RAISE EXCEPTION 'Work fact requires actual project actor and one transaction' USING ERRCODE='23514'; END IF;
 IF v.confirmation_id IS NOT NULL THEN
  SELECT xmin INTO cx FROM public.confirmations WHERE tenant_id=t AND id=v.confirmation_id;
  IF cx IS DISTINCT FROM vx THEN RAISE EXCEPTION 'Work confirmation consumption must share its new fact transaction' USING ERRCODE='23514'; END IF;
 END IF;
 IF jsonb_typeof(v.source_basis->'artifacts') IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'Work direct source metadata required' USING ERRCODE='23514'; END IF;
 FOR basis IN SELECT value FROM jsonb_array_elements(v.source_basis->'artifacts') LOOP
  IF NOT EXISTS(SELECT 1 FROM public.artifact_versions a WHERE a.tenant_id=t AND a.category_id=v.category_id
   AND (a.product_id IS NULL OR a.product_id=v.product_id) AND a.id::text=basis->>'id'
   AND a.revision::text=basis->>'revision' AND a.content_hash=basis->>'hash' AND a.status='active'
   AND a.status=basis->>'status' AND a.owner_id::text=basis->>'owner_id' AND a.visibility=basis->>'visibility'
   AND (v.visibility='private' OR a.visibility<>'private')
   AND (NOT(basis ? 'original') OR EXISTS(SELECT 1 FROM public.original_security sec
    WHERE sec.tenant_id=t AND sec.original_id=a.original_id AND sec.original_id::text=basis->'original'->>'id'
     AND sec.epoch::text=basis->'original'->>'epoch' AND sec.source_state='active' AND sec.disposition='active'))) THEN
   RAISE EXCEPTION 'Retained work source metadata changed' USING ERRCODE='23514'; END IF;
 END LOOP;
 FOR ref IN SELECT value FROM jsonb_array_elements(v.sources) LOOP
  SELECT value INTO STRICT basis FROM jsonb_array_elements(v.source_basis->'artifacts') WHERE value->>'id'=ref->>'id';
  IF ref->>'kind' IS DISTINCT FROM 'artifact' OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(v.reads) rd WHERE rd->>'artifact_id'=ref->>'id' AND rd->'expected_revision'=ref->'revision')
   OR NOT EXISTS(SELECT 1 FROM public.artifact_versions a WHERE a.tenant_id=t AND a.category_id=v.category_id
    AND a.id::text=ref->>'id' AND a.revision::text=ref->>'revision' AND a.status='active'
    AND a.revision::text=basis->>'revision' AND a.content_hash=basis->>'hash' AND a.status=basis->>'status'
    AND a.owner_id::text=basis->>'owner_id' AND a.visibility=basis->>'visibility'
    AND (v.visibility='private' OR a.visibility<>'private')
    AND ((a.original_id IS NULL AND basis->>'source_kind'='registered_native_text' AND EXISTS(
      SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=t AND r.subject_id=a.id AND r.subject_revision=a.revision
       AND r.subject_type='artifact' AND r.operation='evidence.artifact.register' AND r.id::text=basis->'registration'->>'receipt_id'
       AND r.actor_id::text=basis->'registration'->>'actor_id' AND r.requester_id::text=basis->'registration'->>'requester_id'
       AND r.run_id::text IS NOT DISTINCT FROM basis->'registration'->>'run_id'))
     OR (a.original_id IS NOT NULL AND basis->>'source_kind'='uploaded_original' AND EXISTS(
      SELECT 1 FROM public.uploaded_originals o JOIN public.original_security sec ON sec.tenant_id=o.tenant_id AND sec.original_id=o.id
       WHERE o.tenant_id=t AND o.category_id=v.category_id AND o.id=a.original_id AND o.id::text=basis->'original'->>'id'
        AND o.status='parsed' AND sec.epoch::text=basis->'original'->>'epoch' AND sec.source_state='active' AND sec.disposition='active'
        AND sec.source_state=basis->'original'->>'source_state' AND sec.disposition=basis->'original'->>'disposition'
        AND (v.visibility='private' OR o.visibility<>'private'))))) THEN
   RAISE EXCEPTION 'Work source metadata security or audience changed' USING ERRCODE='23514'; END IF;
 END LOOP;
END
""".replace("__SELECT__", SELECT_FACT)

TASK_ATOM = r"""
DECLARE v public.work_task_versions; prior public.work_task_versions; cur public.work_task_currents;
 vx xid; cx xid; allowed text[]; required_key text; time_value jsonb;
BEGIN
 SELECT * INTO STRICT v FROM public.work_task_versions WHERE tenant_id=t AND id=target;
 SELECT xmin INTO vx FROM public.work_task_versions WHERE tenant_id=t AND id=target;
 SELECT * INTO STRICT cur FROM public.work_task_currents WHERE tenant_id=t AND product_id=v.product_id AND task_id=v.task_id;
 SELECT xmin INTO cx FROM public.work_task_currents WHERE tenant_id=t AND id=cur.id;
 PERFORM public.assert_work_management_write(t,target,'work_task');
 IF vx IS DISTINCT FROM cx OR ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.task_id,cur.version_id,cur.revision,cur.state)
  IS DISTINCT FROM ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.task_id,v.id,v.revision,v.state)
  OR v.body->>'task_id' IS DISTINCT FROM v.task_id::text OR v.body->>'revision' IS DISTINCT FROM v.revision::text OR v.body->>'state' IS DISTINCT FROM v.state THEN
  RAISE EXCEPTION 'Task fact needs its exact same-transaction Current' USING ERRCODE='23514'; END IF;
 IF v.revision=1 THEN
  IF v.body->>'title' IS DISTINCT FROM v.command->'envelope'->'payload'->>'title' OR v.body->>'goal' IS DISTINCT FROM v.command->'envelope'->'payload'->>'goal'
   OR v.body->'outcomes' IS DISTINCT FROM v.command->'envelope'->'payload'->'outcomes'
   OR v.body->'plan_task' IS DISTINCT FROM v.command->'envelope'->'payload'->'plan_task'
   OR v.body->'assignee_id' IS DISTINCT FROM 'null'::jsonb OR v.body->'recipient_id' IS DISTINCT FROM 'null'::jsonb
   OR v.body->'actual_start' IS DISTINCT FROM 'null'::jsonb OR v.body->'submission' IS DISTINCT FROM 'null'::jsonb OR v.body->'review' IS DISTINCT FROM 'null'::jsonb THEN
   RAISE EXCEPTION 'Created task records proposed work only' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT * INTO STRICT prior FROM public.work_task_versions WHERE tenant_id=t AND id=v.previous_id;
  IF v.command->'envelope'->'payload'->'task' IS DISTINCT FROM jsonb_build_object('id',v.task_id,'revision',prior.revision) THEN
   RAISE EXCEPTION 'Task action requires its exact stable task revision' USING ERRCODE='23514'; END IF;
  allowed=ARRAY['revision','state'];
  IF v.action='assign' AND prior.state IN ('proposed','assigned') AND v.state='assigned' AND v.actor_id=v.owner_id THEN
   allowed=allowed||ARRAY['assignee_id','recipient_id'];
   IF v.body->'assignee_id' IS DISTINCT FROM v.command->'envelope'->'payload'->'assignee_id' OR v.body->'recipient_id' IS DISTINCT FROM v.command->'envelope'->'payload'->'recipient_id' THEN RAISE EXCEPTION 'Task assignment mismatch' USING ERRCODE='23514'; END IF;
  ELSIF v.action='accept' AND prior.state='assigned' AND v.state='accepted' AND prior.body->>'assignee_id'=v.actor_id::text THEN NULL;
  ELSIF v.action='start' AND prior.state='accepted' AND v.state='in_progress' AND prior.body->>'assignee_id'=v.actor_id::text THEN
   allowed=allowed||ARRAY['actual_start'];
  ELSIF v.action='submit' AND prior.state='in_progress' AND v.state='submitted' AND prior.body->>'assignee_id'=v.actor_id::text THEN
   allowed=allowed||ARRAY['submission','review'];
  ELSIF v.action='review' AND prior.state='submitted' AND prior.body->>'recipient_id'=v.actor_id::text
   AND ((v.body->'review'->>'decision'='accepted' AND v.state='completed') OR (v.body->'review'->>'decision'='returned' AND v.state='in_progress')) THEN
   allowed=allowed||ARRAY['review'];
   IF v.state='completed' THEN
    FOR required_key IN SELECT value->>'key' FROM jsonb_array_elements(v.body->'outcomes') WHERE value->'required'='true'::jsonb LOOP
     IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(v.body->'submission'->'results') x WHERE x->>'key'=required_key AND x->>'status'='present')
      OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(v.body->'review'->'checks') x WHERE x->>'key'=required_key AND x->>'decision'='accepted') THEN
      RAISE EXCEPTION 'Required task outcome not accepted' USING ERRCODE='23514'; END IF;
    END LOOP;
   END IF;
  ELSE RAISE EXCEPTION 'Invalid task transition or actual actor' USING ERRCODE='23514'; END IF;
  IF (v.body-allowed) IS DISTINCT FROM (prior.body-allowed) THEN RAISE EXCEPTION 'Task action cannot replace fixed base or other facts' USING ERRCODE='23514'; END IF;
 END IF;
 FOR time_value IN SELECT value FROM jsonb_array_elements(jsonb_build_array(v.body->'actual_start',v.body->'submission'->'time',v.body->'review'->'time')) WHERE value<>'null'::jsonb LOOP
  IF (time_value->>'actual_at')::timestamptz>(time_value->>'recorded_at')::timestamptz
   OR (time_value->>'recorded_at')::timestamptz>v.created_at THEN
   RAISE EXCEPTION 'Task actual time cannot be in the future of its recording' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF (v.body->'actual_start'->>'actual_at')::timestamptz>(v.body->'submission'->'time'->>'actual_at')::timestamptz
  OR (v.body->'submission'->'time'->>'actual_at')::timestamptz>(v.body->'review'->'time'->>'actual_at')::timestamptz THEN
  RAISE EXCEPTION 'Task actual start submission and review must be monotone' USING ERRCODE='23514'; END IF;
END
"""

COMMITMENT_ATOM = r"""
DECLARE v public.work_commitment_versions; task public.work_task_versions; cur public.work_commitment_currents; vx xid; cx xid;
BEGIN
 SELECT * INTO STRICT v FROM public.work_commitment_versions WHERE tenant_id=t AND id=target;
 SELECT xmin INTO vx FROM public.work_commitment_versions WHERE tenant_id=t AND id=target;
 SELECT * INTO STRICT task FROM public.work_task_versions WHERE tenant_id=t AND product_id=v.product_id AND task_id=v.task_id AND revision=v.task_revision;
 SELECT * INTO STRICT cur FROM public.work_commitment_currents WHERE tenant_id=t AND product_id=v.product_id AND task_id=v.task_id AND promisor_id=v.promisor_id AND recipient_id=v.recipient_id;
 SELECT xmin INTO cx FROM public.work_commitment_currents WHERE tenant_id=t AND id=cur.id;
 PERFORM public.assert_work_management_write(t,target,'work_commitment');
 IF vx IS DISTINCT FROM cx OR ROW(task.category_id,task.project_id,task.owner_id,task.visibility) IS DISTINCT FROM ROW(v.category_id,v.project_id,v.owner_id,v.visibility)
  OR ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.task_id,cur.promisor_id,cur.recipient_id,cur.series_id,cur.version_id,cur.revision)
   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.task_id,v.promisor_id,v.recipient_id,v.series_id,v.id,v.revision)
  OR NOT EXISTS(SELECT 1 FROM public.work_task_currents c WHERE c.tenant_id=t AND c.product_id=v.product_id AND c.task_id=v.task_id AND c.revision=v.task_revision)
  OR task.body->>'assignee_id' IS DISTINCT FROM v.promisor_id::text OR task.state NOT IN ('accepted','in_progress','submitted')
  OR v.body->>'task_id' IS DISTINCT FROM v.task_id::text OR v.body->>'task_revision' IS DISTINCT FROM v.task_revision::text
  OR v.body->>'revision' IS DISTINCT FROM v.revision::text OR v.body->>'promisor_id' IS DISTINCT FROM v.promisor_id::text OR v.body->>'recipient_id' IS DISTINCT FROM v.recipient_id::text
  OR v.body->'outcome_keys' IS DISTINCT FROM v.outcome_keys OR (v.body->>'promised_at')::timestamptz IS DISTINCT FROM v.promised_at
  OR v.body->>'original_timezone' IS DISTINCT FROM v.original_timezone OR (v.body->>'calendar_id')::uuid IS DISTINCT FROM v.calendar_id
  OR v.command->'envelope'->'payload'->'task' IS DISTINCT FROM jsonb_build_object('id',v.task_id,'revision',v.task_revision)
  OR v.command->'envelope'->'payload'->'recipient_id' IS DISTINCT FROM v.body->'recipient_id'
  OR v.command->'envelope'->'payload'->'outcome_keys' IS DISTINCT FROM v.outcome_keys
  OR (v.command->'envelope'->'payload'->>'promised_at')::timestamptz IS DISTINCT FROM v.promised_at
  OR v.command->'envelope'->'payload'->>'original_timezone' IS DISTINCT FROM v.original_timezone
  OR (v.command->'envelope'->'payload'->>'calendar_id')::uuid IS DISTINCT FROM v.calendar_id
  OR v.body->'replaces' IS DISTINCT FROM (CASE WHEN v.replaces_id IS NULL THEN 'null'::jsonb ELSE jsonb_build_object('id',v.replaces_id,'revision',v.replaces_revision) END)
  OR v.command->'envelope'->'payload'->'replaces' IS DISTINCT FROM v.body->'replaces'
  OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(v.outcome_keys) key WHERE NOT EXISTS(SELECT 1 FROM jsonb_array_elements(task.body->'outcomes') o WHERE o->>'key'=key)) THEN
  RAISE EXCEPTION 'Commitment requires actual accepted task and separate recipient chain' USING ERRCODE='23514'; END IF;
END
"""

STATUS_ATOM = r"""
DECLARE v public.project_status_updates; ref jsonb;
BEGIN
 SELECT * INTO STRICT v FROM public.project_status_updates WHERE tenant_id=t AND id=target;
 PERFORM public.assert_work_management_write(t,target,'project_status_update');
 IF v.body->>'fact_summary' IS DISTINCT FROM v.fact_summary OR v.body->>'next_steps' IS DISTINCT FROM v.next_steps
  OR v.actor_id<>v.owner_id
  OR v.body->'task_refs' IS DISTINCT FROM v.task_refs OR v.body->>'actor_id' IS DISTINCT FROM v.actor_id::text
  OR v.command->'envelope'->'payload'->>'fact_summary' IS DISTINCT FROM v.fact_summary
  OR v.command->'envelope'->'payload'->>'next_steps' IS DISTINCT FROM v.next_steps
  OR v.command->'envelope'->'payload'->'task_refs' IS DISTINCT FROM v.task_refs THEN
  RAISE EXCEPTION 'Named status update exact payload mismatch' USING ERRCODE='23514'; END IF;
 FOR ref IN SELECT value FROM jsonb_array_elements(v.task_refs) LOOP
  IF NOT EXISTS(SELECT 1 FROM public.work_task_versions x WHERE x.tenant_id=t AND x.category_id=v.category_id AND x.product_id=v.product_id AND x.project_id=v.project_id AND x.task_id::text=ref->>'id' AND x.revision::text=ref->>'revision') THEN
   RAISE EXCEPTION 'Status update requires actual fixed project task references' USING ERRCODE='23514'; END IF;
 END LOOP;
END
"""


def current_guard(table, version_table, previous_id, previous_revision, allowed):
    fields = ",".join(repr(value) for value in allowed)
    return f"""
BEGIN
 IF TG_OP='INSERT' AND NEW.revision=1 THEN RETURN NEW;
 ELSIF TG_OP='UPDATE' AND (to_jsonb(NEW)-ARRAY[{fields}]) IS NOT DISTINCT FROM (to_jsonb(OLD)-ARRAY[{fields}])
  AND NEW.revision=OLD.revision+1 AND EXISTS(SELECT 1 FROM public.{version_table} v WHERE v.tenant_id=NEW.tenant_id
   AND v.id=NEW.version_id AND v.revision=NEW.revision AND v.{previous_id}=OLD.version_id AND v.{previous_revision}=OLD.revision) THEN RETURN NEW;
 END IF;
 RAISE EXCEPTION '{table} requires one exact Current CAS' USING ERRCODE='23514';
END
"""


def current_atom(table, version_table):
    return f"""
DECLARE cur public.{table}; cx xid; vx xid;
BEGIN
 SELECT * INTO STRICT cur FROM public.{table} WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
 SELECT xmin INTO cx FROM public.{table} WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
 SELECT xmin INTO vx FROM public.{version_table} WHERE tenant_id=NEW.tenant_id AND id=cur.version_id;
 IF vx IS DISTINCT FROM cx THEN RAISE EXCEPTION 'Work Current requires its new same-transaction immutable version' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END
"""


PROOF = f"""
DECLARE old_scoped boolean=false; new_scoped boolean=false;
BEGIN
 IF TG_OP<>'INSERT' THEN old_scoped=OLD.operation IN {T1}; END IF;
 IF TG_OP<>'DELETE' THEN new_scoped=NEW.operation IN {T1}; END IF;
 IF old_scoped OR new_scoped THEN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Work confirmation history retained' USING ERRCODE='23514';
  ELSIF TG_OP='INSERT' THEN
   IF NEW.consumed IS DISTINCT FROM false THEN RAISE EXCEPTION 'Work confirmation starts unconsumed' USING ERRCODE='23514'; END IF;
  ELSIF NOT(old_scoped AND new_scoped) OR OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS DISTINCT FROM true
   OR (to_jsonb(NEW)-'consumed') IS DISTINCT FROM (to_jsonb(OLD)-'consumed') THEN
   RAISE EXCEPTION 'Work confirmation only consumes original false to true' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END
"""

TRANSITION = f"""
DECLARE amount integer;
BEGIN
 IF NEW.operation IN {T1} THEN
  SELECT count(*) INTO amount FROM (
   SELECT confirmation_id FROM public.work_task_versions WHERE tenant_id=NEW.tenant_id AND confirmation_id=NEW.id AND operation=NEW.operation
   UNION ALL SELECT confirmation_id FROM public.work_commitment_versions WHERE tenant_id=NEW.tenant_id AND confirmation_id=NEW.id AND operation=NEW.operation
   UNION ALL SELECT confirmation_id FROM public.project_status_updates WHERE tenant_id=NEW.tenant_id AND confirmation_id=NEW.id AND operation=NEW.operation) refs;
  IF amount<>1 OR OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS DISTINCT FROM true THEN
   RAISE EXCEPTION 'Consumed work confirmation needs exactly one new fact' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NULL;
END
"""

RECEIPT_GUARD = f"""
DECLARE scoped boolean=false;
BEGIN
 IF TG_OP<>'INSERT' THEN scoped=OLD.operation IN {OPS} OR OLD.subject_type IN {SUBJECTS}; END IF;
 IF TG_OP<>'DELETE' THEN scoped=scoped OR NEW.operation IN {OPS} OR NEW.subject_type IN {SUBJECTS}; END IF;
 IF scoped AND TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Work receipt immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END
"""

MEMBER_GUARD = f"""
DECLARE scoped boolean=false; old_scoped boolean=false;
BEGIN
 IF TG_OP<>'DELETE' THEN SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.receipt_id AND (r.operation IN {OPS} OR r.subject_type IN {SUBJECTS})) INTO scoped; END IF;
 IF TG_OP<>'INSERT' THEN SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=OLD.tenant_id AND r.id=OLD.receipt_id AND (r.operation IN {OPS} OR r.subject_type IN {SUBJECTS})) INTO old_scoped; END IF;
 IF TG_OP<>'INSERT' AND (scoped OR old_scoped) THEN
  IF TG_OP='UPDATE' AND TG_TABLE_NAME='outbox_events' AND (to_jsonb(NEW)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) IS NOT DISTINCT FROM (to_jsonb(OLD)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Work audit event or original key immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END
"""

MEMBER_TARGET = f"""
DECLARE r public.action_receipts;
BEGIN
 IF TG_TABLE_NAME='action_receipts' THEN r=NEW; ELSE SELECT * INTO r FROM public.action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id; END IF;
 IF r.operation IN {OPS} OR r.subject_type IN {SUBJECTS} THEN PERFORM public.assert_work_management_members(r.tenant_id,r.subject_id,r.subject_type::text); END IF;
 RETURN NULL;
END
"""


def functions():
    values = [
        ("assert_work_management_members", "t uuid,target uuid,kind text", MEMBERS, "void"),
        ("assert_work_management_write", "t uuid,target uuid,kind text", WRITE_ATOM, "void"),
        ("assert_work_task", "t uuid,target uuid", TASK_ATOM, "void"),
        ("assert_work_commitment", "t uuid,target uuid", COMMITMENT_ATOM, "void"),
        ("assert_project_status_update", "t uuid,target uuid", STATUS_ATOM, "void"),
        ("protect_work_confirmation", "", PROOF, "trigger"),
        ("require_work_confirmation", "", TRANSITION, "trigger"),
        ("protect_work_receipt", "", RECEIPT_GUARD, "trigger"),
        ("protect_work_member", "", MEMBER_GUARD, "trigger"),
        ("require_work_member", "", MEMBER_TARGET, "trigger"),
        (
            "reject_work_mutation",
            "",
            "BEGIN RAISE EXCEPTION 'Work facts are immutable' USING ERRCODE='23514'; END",
            "trigger",
        ),
    ]
    for stem, _atom in (
        ("work_task", TASK_ATOM),
        ("work_commitment", COMMITMENT_ATOM),
        ("project_status_update", STATUS_ATOM),
    ):
        values.append(
            (
                f"require_{stem}",
                "",
                f"BEGIN PERFORM public.assert_{stem}(NEW.tenant_id,NEW.id); RETURN NULL; END",
                "trigger",
            )
        )
    for stem, table, versions, prior_id, prior_revision, allowed in (
        (
            "work_task",
            "work_task_currents",
            "work_task_versions",
            "previous_id",
            "previous_revision",
            ("version_id", "revision", "state"),
        ),
        (
            "work_commitment",
            "work_commitment_currents",
            "work_commitment_versions",
            "replaces_id",
            "replaces_revision",
            ("version_id", "revision"),
        ),
    ):
        values.extend(
            (
                (
                    f"protect_{stem}_current",
                    "",
                    current_guard(table, versions, prior_id, prior_revision, allowed),
                    "trigger",
                ),
                (f"require_{stem}_current", "", current_atom(table, versions), "trigger"),
            )
        )
    return tuple(values)


def function_sql():
    return tuple(_function(*row[:3], row[3]) for row in functions())


def signatures():
    return tuple(
        f"{name}({','.join(x.split()[-1] for x in args.split(',')) if args else ''})"
        for name, args, _, _ in functions()
    )


def policy_sql():
    statements = []
    for table in TABLES:
        name = table.name
        read = f"public.category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id={name}.tenant_id AND p.category_id={name}.category_id AND p.product_id={name}.product_id AND p.id={name}.project_id AND p.owner_id={name}.owner_id AND p.visibility={name}.visibility)"
        write = "public.category_access(tenant_id,category_id,true)"
        if table not in (TABLES[0], TABLES[1]):
            write += " AND public.scope_actor()=public.scope_requester() AND EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND h.id=public.scope_actor() AND h.kind='human' AND h.active)"
        statements.extend(
            (
                f'ALTER TABLE public."{name}" ENABLE ROW LEVEL SECURITY',
                f'ALTER TABLE public."{name}" FORCE ROW LEVEL SECURITY',
                f'CREATE POLICY owner_internal ON public."{name}" TO pdos_next_owner USING(true) WITH CHECK(true)',
                f'CREATE POLICY work_read ON public."{name}" FOR SELECT TO pdos_next_app USING({read})',
                f'CREATE POLICY work_insert ON public."{name}" FOR INSERT TO pdos_next_app WITH CHECK({write} AND {read})',
                f'REVOKE ALL ON public."{name}" FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
                f'GRANT SELECT,INSERT ON public."{name}" TO pdos_next_app',
            )
        )
        if table in (TABLES[1], TABLES[3]):
            fields = "version_id,revision,state" if table is TABLES[1] else "version_id,revision"
            statements.extend(
                (
                    f'CREATE POLICY work_advance ON public."{name}" FOR UPDATE TO pdos_next_app USING({write} AND {read}) WITH CHECK({write} AND {read})',
                    f'GRANT UPDATE({fields}) ON public."{name}" TO pdos_next_app',
                )
            )
    return tuple(statements)


def trigger_sql():
    statements = []
    for table in TABLES:
        statements.extend(
            (
                f"CREATE TRIGGER work_category BEFORE INSERT ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.bind_model_category()",
                f"CREATE TRIGGER work_category_immutable BEFORE UPDATE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.protect_category_binding()",
                f"CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.lifecycle_reference_gate()",
                f"CREATE TRIGGER category_lifecycle_clock AFTER INSERT OR UPDATE OR DELETE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.category_lifecycle_clock()",
            )
        )
    for table, stem in (
        (TABLES[0], "work_task"),
        (TABLES[2], "work_commitment"),
        (TABLES[4], "project_status_update"),
    ):
        statements.extend(
            (
                f"CREATE TRIGGER work_immutable BEFORE UPDATE OR DELETE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.reject_work_mutation()",
                f"CREATE CONSTRAINT TRIGGER work_fact_atom AFTER INSERT ON public.{table.name} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_{stem}()",
            )
        )
    for table, stem in ((TABLES[1], "work_task"), (TABLES[3], "work_commitment")):
        statements.extend(
            (
                f"CREATE TRIGGER work_current_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.protect_{stem}_current()",
                f"CREATE CONSTRAINT TRIGGER work_current_atom AFTER INSERT OR UPDATE ON public.{table.name} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_{stem}_current()",
            )
        )
    statements.extend(
        (
            "CREATE TRIGGER work_proof_guard BEFORE INSERT OR UPDATE OR DELETE ON public.confirmations FOR EACH ROW EXECUTE FUNCTION public.protect_work_confirmation()",
            "CREATE CONSTRAINT TRIGGER work_proof_target AFTER UPDATE ON public.confirmations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_work_confirmation()",
            "CREATE TRIGGER work_receipt_guard BEFORE INSERT OR UPDATE OR DELETE ON public.action_receipts FOR EACH ROW EXECUTE FUNCTION public.protect_work_receipt()",
        )
    )
    for table in ("action_receipts", "audit_entries", "outbox_events", "request_keys"):
        statements.append(
            f"CREATE CONSTRAINT TRIGGER work_member_atom AFTER INSERT ON public.{table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_work_member()"
        )
        if table != "action_receipts":
            statements.append(
                f"CREATE TRIGGER work_member_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.protect_work_member()"
            )
    return tuple(statements)


def upgrade_sql():
    return (
        *table_sql(),
        *function_sql(),
        *(
            f"REVOKE ALL ON FUNCTION public.{name} FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"
            for name in signatures()
        ),
        *policy_sql(),
        *trigger_sql(),
    )


def downgrade_sql():
    return (
        "LOCK TABLE "
        + ",".join(f"public.{t.name}" for t in TABLES)
        + ",public.confirmations,public.action_receipts IN ACCESS EXCLUSIVE MODE",
        "DO $work_management$ BEGIN IF "
        + " OR ".join(f"EXISTS(SELECT 1 FROM public.{t.name})" for t in TABLES)
        + f" OR EXISTS(SELECT 1 FROM public.confirmations WHERE operation IN {T1}) OR EXISTS(SELECT 1 FROM public.action_receipts WHERE operation IN {OPS} OR subject_type IN {SUBJECTS}) THEN RAISE EXCEPTION 'Work history retained; downgrade refused' USING ERRCODE='23514'; END IF; END; $work_management$",
        "DROP TRIGGER work_proof_guard ON public.confirmations",
        "DROP TRIGGER work_proof_target ON public.confirmations",
        "DROP TRIGGER work_receipt_guard ON public.action_receipts",
        *(
            f"DROP TRIGGER work_member_atom ON public.{name}"
            for name in ("action_receipts", "audit_entries", "outbox_events", "request_keys")
        ),
        *(
            f"DROP TRIGGER work_member_guard ON public.{name}"
            for name in ("audit_entries", "outbox_events", "request_keys")
        ),
        *(f"DROP TABLE public.{t.name}" for t in reversed(TABLES)),
        *(f"DROP FUNCTION public.{name}" for name in reversed(signatures())),
    )
