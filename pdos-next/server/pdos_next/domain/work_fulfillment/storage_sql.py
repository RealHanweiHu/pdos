"""Offline SQL declarations for a recipient's independent promise fulfillment review.

The migration host owns lifecycle catalogs and common subject registration. Only
new facts check live task/promise Current; retained reviews keep their fixed refs.
"""

# ruff: noqa: E501 -- PostgreSQL predicates stay intact.

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from .models import (
    CURRENT,
    OPERATION,
    REVIEW,
    SUBJECT,
    WorkCommitmentReview,
    WorkCommitmentReviewCurrent,
)

TABLES = (WorkCommitmentReview.__table__, WorkCommitmentReviewCurrent.__table__)


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
    return f"CREATE FUNCTION public.{name}({args}) RETURNS {returns}\nLANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $work_fulfillment$\n{body.rstrip()};\n$work_fulfillment$"


MEMBERS = r"""
DECLARE v public.work_commitment_reviews; r public.action_receipts; c public.confirmations; expected_result jsonb;
BEGIN
 SELECT * INTO STRICT v FROM public.work_commitment_reviews WHERE tenant_id=t AND id=target;
 SELECT * INTO STRICT r FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;
 SELECT * INTO STRICT c FROM public.confirmations WHERE tenant_id=t AND id=v.confirmation_id;
 expected_result=jsonb_build_object('id',v.id,'revision',v.revision,'status',v.state,
  'commitment_id',v.commitment_id,'task_id',v.task_id,'recipient_id',v.recipient_id,'project_id',v.project_id);
 IF ROW(r.category_id,r.product_id,r.command_id,r.confirmation_id,r.actor_id,r.requester_id,r.operation,r.subject_type,r.subject_id,r.subject_revision,r.visibility,r.request_digest,r.intent_digest)
  IS DISTINCT FROM ROW(v.category_id,v.product_id,v.command_id,v.confirmation_id,v.actor_id,v.requester_id,v.operation,'work_commitment_review'::varchar,v.id,v.revision,v.visibility,v.request_digest,v.intent_digest)
  OR r.result IS DISTINCT FROM expected_result OR r.created_at<v.created_at
  OR (SELECT count(*) FROM public.action_receipts x WHERE x.tenant_id=t AND x.operation=v.operation AND x.subject_type='work_commitment_review' AND x.subject_id=v.id AND x.subject_revision=v.revision)<>1
  OR (SELECT count(*) FROM public.audit_entries a WHERE a.tenant_id=t AND a.receipt_id=r.id)<>1
  OR NOT EXISTS(SELECT 1 FROM public.audit_entries a WHERE a.tenant_id=t AND a.receipt_id=r.id AND a.category_id=v.category_id AND a.actor_id=v.actor_id AND a.operation=v.operation AND a.created_at>=v.created_at)
  OR (SELECT count(*) FROM public.outbox_events e WHERE e.tenant_id=t AND e.receipt_id=r.id)<>1
  OR NOT EXISTS(SELECT 1 FROM public.outbox_events e WHERE e.tenant_id=t AND e.receipt_id=r.id AND e.category_id=v.category_id AND e.actor_id=v.actor_id AND e.type='commitment.reviewed' AND e.subject_id=v.id AND e.subject_revision=v.revision AND e.schema_version=1 AND e.correlation_id=coalesce(r.agent_run_id,r.run_id,v.command_id) AND e.created_at>=v.created_at)
  OR v.command->>'original_key_sha256' IS NULL OR v.command->>'original_key_sha256' !~ '^[a-f0-9]{64}$'
  OR v.command->'envelope' ? 'idempotency_key' OR v.command->'envelope'->'payload' ? 'confirmation_token'
  OR NOT EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=t AND k.category_id=v.category_id AND k.actor_id=v.actor_id AND k.receipt_id=r.id AND k.digest=v.request_digest AND encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.command->>'original_key_sha256')
  OR c.consumed IS DISTINCT FROM true
  OR ROW(c.category_id,c.product_id,c.actor_id,c.operation) IS DISTINCT FROM ROW(v.category_id,v.product_id,v.actor_id,v.operation)
  OR c.subject_type IS DISTINCT FROM 'product' OR c.subject_id IS DISTINCT FROM v.product_id
  OR c.revision::text IS DISTINCT FROM v.command->'envelope'->>'expected_revision'
  OR c.snapshot IS DISTINCT FROM v.command->'review' OR c.created_at>v.created_at
  OR c.expires_at IS NULL OR v.created_at>=c.expires_at OR r.created_at>=c.expires_at
  OR r.run_id IS NOT NULL OR r.agent_run_id IS NOT NULL THEN
  RAISE EXCEPTION 'Commitment review requires its original consumed T1 common group' USING ERRCODE='23514'; END IF;
END
"""


WRITE_ATOM = r"""
DECLARE v public.work_commitment_reviews; p public.projects; envelope jsonb; review jsonb; ref jsonb; basis jsonb; vx xid; rx xid; cx xid;
BEGIN
 SELECT * INTO STRICT v FROM public.work_commitment_reviews WHERE tenant_id=t AND id=target;
 SELECT xmin INTO vx FROM public.work_commitment_reviews WHERE tenant_id=t AND id=target;
 SELECT * INTO STRICT p FROM public.projects WHERE tenant_id=t AND id=v.project_id;
 SELECT xmin INTO rx FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;
 SELECT xmin INTO cx FROM public.confirmations WHERE tenant_id=t AND id=v.confirmation_id;
 PERFORM public.assert_work_fulfillment_members(t,target);
 envelope=v.command->'envelope'; review=v.command->'review';
 IF ROW(p.category_id,p.product_id,p.owner_id,p.visibility) IS DISTINCT FROM ROW(v.category_id,v.product_id,v.owner_id,v.visibility)
  OR v.actor_id IS DISTINCT FROM public.scope_actor() OR v.requester_id IS DISTINCT FROM public.scope_requester()
  OR v.writer_id<>v.actor_id OR v.actor_id<>v.requester_id OR v.actor_id<>v.recipient_id
  OR vx IS DISTINCT FROM rx OR vx IS DISTINCT FROM cx OR NOT public.category_access(t,v.category_id,true)
  OR NOT EXISTS(SELECT 1 FROM public.principals a WHERE a.tenant_id=t AND a.id=v.actor_id AND a.kind='human' AND a.active)
  OR envelope->>'operation' IS DISTINCT FROM v.operation OR envelope->>'command_id' IS DISTINCT FROM v.command_id::text
  OR envelope->>'category_id' IS DISTINCT FROM v.category_id::text OR envelope->>'product_id' IS DISTINCT FROM v.product_id::text
  OR envelope->'payload'->>'project_id' IS DISTINCT FROM v.project_id::text
  OR review->'declaration' IS DISTINCT FROM envelope->'payload' OR review->>'operation' IS DISTINCT FROM v.operation
  OR review->'sources' IS DISTINCT FROM v.sources OR review->'source_basis' IS DISTINCT FROM v.source_basis
  OR review->'project' IS DISTINCT FROM jsonb_build_object('id',p.id,'revision',p.revision,'name',p.name,'owner_id',p.owner_id,'visibility',p.visibility)
  OR review->>'effect' IS DISTINCT FROM '仅登记本接收者对固定承诺成果的核对；不改变任务、承诺原文或日期。'
  OR (v.body #- '{time,recorded_at}') IS DISTINCT FROM review->'after'
  OR NOT EXISTS(SELECT 1 FROM public.products x WHERE x.tenant_id=t AND x.category_id=v.category_id AND x.id=v.product_id AND x.revision::text=envelope->>'expected_revision')
  OR NOT COALESCE(envelope->'source_read_set' @> v.reads,false) OR NOT COALESCE(v.reads @> (envelope->'source_read_set'),false)
  OR jsonb_array_length(envelope->'source_read_set')<>jsonb_array_length(v.reads)
  OR NOT public.direct_source_set_visible(t,v.category_id,v.product_id,v.reads)
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(v.reads) rd WHERE NOT EXISTS(SELECT 1 FROM jsonb_array_elements(v.sources) src WHERE src->>'id'=rd->>'artifact_id' AND src->'revision'=rd->'expected_revision'))
  OR EXISTS(SELECT 1 FROM public.audit_entries x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT FROM vx)
  OR EXISTS(SELECT 1 FROM public.outbox_events x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT FROM vx)
  OR NOT EXISTS(SELECT 1 FROM public.request_keys k WHERE k.tenant_id=t AND k.receipt_id=v.receipt_id AND k.actor_id=v.actor_id AND k.digest=v.request_digest AND k.xmin=vx AND encode(sha256(convert_to(k.key,'UTF8')),'hex')=v.command->>'original_key_sha256') THEN
  RAISE EXCEPTION 'Commitment review requires actual recipient, project and one transaction' USING ERRCODE='23514'; END IF;
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
"""


REVIEW_ATOM = r"""
DECLARE v public.work_commitment_reviews; prior public.work_commitment_reviews; promise public.work_commitment_versions;
 promise_cur public.work_commitment_currents; task public.work_task_versions; task_cur public.work_task_currents;
 submission public.work_task_versions; cur public.work_commitment_review_currents; payload jsonb; expected_before jsonb;
 vx xid; cx xid;
BEGIN
 SELECT * INTO STRICT v FROM public.work_commitment_reviews WHERE tenant_id=t AND id=target;
 SELECT xmin INTO vx FROM public.work_commitment_reviews WHERE tenant_id=t AND id=target;
 PERFORM public.assert_work_fulfillment_write(t,target);
 SELECT * INTO STRICT promise FROM public.work_commitment_versions WHERE tenant_id=t AND id=v.commitment_id;
 SELECT * INTO STRICT promise_cur FROM public.work_commitment_currents WHERE tenant_id=t AND product_id=v.product_id AND task_id=v.task_id AND promisor_id=v.promisor_id AND recipient_id=v.recipient_id;
 SELECT * INTO STRICT task FROM public.work_task_versions WHERE tenant_id=t AND id=v.task_version_id;
 SELECT * INTO STRICT task_cur FROM public.work_task_currents WHERE tenant_id=t AND product_id=v.product_id AND task_id=v.task_id;
 SELECT * INTO STRICT submission FROM public.work_task_versions WHERE tenant_id=t AND id=v.submission_id;
 SELECT * INTO STRICT cur FROM public.work_commitment_review_currents WHERE tenant_id=t AND product_id=v.product_id AND commitment_id=v.commitment_id;
 SELECT xmin INTO cx FROM public.work_commitment_review_currents WHERE tenant_id=t AND id=cur.id;
 payload=v.command->'envelope'->'payload';
 IF ROW(promise.category_id,promise.product_id,promise.project_id,promise.owner_id,promise.visibility,promise.task_id,promise.promisor_id,promise.recipient_id,promise.series_id,promise.revision)
  IS DISTINCT FROM ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.task_id,v.promisor_id,v.recipient_id,v.series_id,v.commitment_revision)
  OR ROW(promise_cur.category_id,promise_cur.project_id,promise_cur.owner_id,promise_cur.visibility,promise_cur.series_id,promise_cur.version_id,promise_cur.revision)
   IS DISTINCT FROM ROW(v.category_id,v.project_id,v.owner_id,v.visibility,v.series_id,v.commitment_id,v.commitment_revision)
  OR ROW(task.category_id,task.product_id,task.project_id,task.owner_id,task.visibility,task.task_id,task.revision)
   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.task_id,v.task_revision)
  OR ROW(task_cur.category_id,task_cur.project_id,task_cur.owner_id,task_cur.visibility,task_cur.version_id,task_cur.revision)
   IS DISTINCT FROM ROW(v.category_id,v.project_id,v.owner_id,v.visibility,v.task_version_id,v.task_revision)
  OR ROW(submission.category_id,submission.product_id,submission.project_id,submission.owner_id,submission.visibility,submission.task_id,submission.revision)
   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.task_id,v.submission_revision)
  OR submission.action IS DISTINCT FROM 'submit' OR submission.operation IS DISTINCT FROM 'work.task.submit' OR submission.actor_id IS DISTINCT FROM v.promisor_id
  OR task.body->>'assignee_id' IS DISTINCT FROM v.promisor_id::text
  OR submission.revision>task.revision OR task.body->'submission' IS NULL OR task.body->'submission'='null'::jsonb
  OR submission.body->'submission' IS DISTINCT FROM task.body->'submission'
  OR vx IS DISTINCT FROM cx
  OR ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.commitment_id,cur.version_id,cur.revision,cur.state)
   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.commitment_id,v.id,v.revision,v.state) THEN
  RAISE EXCEPTION 'Commitment review needs exact current promise/task and actual current submission' USING ERRCODE='23514'; END IF;
 IF v.revision=1 THEN
  expected_before=jsonb_build_object('review',null,'state','open');
 ELSE
  SELECT * INTO STRICT prior FROM public.work_commitment_reviews WHERE tenant_id=t AND id=v.previous_id;
  IF prior.state IS DISTINCT FROM 'open' OR prior.commitment_id IS DISTINCT FROM v.commitment_id OR prior.revision<>v.previous_revision THEN
   RAISE EXCEPTION 'Fulfilled commitment review is terminal' USING ERRCODE='23514'; END IF;
  expected_before=jsonb_build_object('review',jsonb_build_object('id',prior.id,'revision',prior.revision),'state',prior.state);
 END IF;
 IF payload->'commitment' IS DISTINCT FROM jsonb_build_object('id',v.commitment_id,'revision',v.commitment_revision)
  OR payload->'task' IS DISTINCT FROM jsonb_build_object('id',v.task_id,'revision',v.task_revision)
  OR payload->'submission' IS DISTINCT FROM jsonb_build_object('id',v.submission_id,'revision',v.submission_revision)
  OR payload->>'expected_review_revision' IS DISTINCT FROM (v.revision-1)::text
  OR v.command->'review'->'before' IS DISTINCT FROM expected_before
  OR payload->>'decision' IS DISTINCT FROM v.decision OR payload->'checks' IS DISTINCT FROM v.body->'checks'
  OR NOT COALESCE(payload->'sources' @> v.sources,false) OR NOT COALESCE(v.sources @> (payload->'sources'),false)
  OR (SELECT count(DISTINCT src) FROM jsonb_array_elements(v.sources) src)<>jsonb_array_length(v.sources)
  OR payload->>'reason' IS DISTINCT FROM v.body->>'reason'
  OR v.body IS DISTINCT FROM jsonb_build_object(
   'commitment',jsonb_build_object('id',v.commitment_id,'revision',v.commitment_revision),'series_id',v.series_id,
   'task',jsonb_build_object('id',v.task_id,'revision',v.task_revision),'task_version_id',v.task_version_id,
   'submission',jsonb_build_object('id',v.submission_id,'revision',v.submission_revision),
   'promisor_id',v.promisor_id,'recipient_id',v.recipient_id,'decision',v.decision,'state',v.state,'checks',payload->'checks',
   'previous',CASE WHEN v.previous_id IS NULL THEN 'null'::jsonb ELSE jsonb_build_object('id',v.previous_id,'revision',v.previous_revision) END,
   'time',v.body->'time','reason',payload->>'reason')
  OR jsonb_typeof(v.body->'time') IS DISTINCT FROM 'object'
  OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(v.body->'time') key) IS DISTINCT FROM ARRAY['actor_id','recorded_at']
  OR v.body->'time'->>'actor_id' IS DISTINCT FROM v.actor_id::text
  OR v.body->'time'->>'recorded_at' IS NULL OR (v.body->'time'->>'recorded_at')::timestamptz>v.created_at
  OR jsonb_typeof(v.body->'checks') IS DISTINCT FROM 'array'
  OR jsonb_array_length(v.body->'checks')<>jsonb_array_length(promise.outcome_keys)
  OR (SELECT count(DISTINCT check_item->>'key') FROM jsonb_array_elements(v.body->'checks') check_item)<>jsonb_array_length(promise.outcome_keys)
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(v.body->'checks') check_item WHERE
   NOT(promise.outcome_keys ? (check_item->>'key')) OR check_item->>'decision' IS NULL OR check_item->>'decision' NOT IN ('accepted','rejected','unknown')
   OR check_item->>'reason' IS NULL OR length(btrim(check_item->>'reason'))=0)
  OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(promise.outcome_keys) AS outcomes(outcome_key) WHERE NOT EXISTS(
   SELECT 1 FROM jsonb_array_elements(v.body->'checks') check_item WHERE check_item->>'key'=outcome_key)) THEN
  RAISE EXCEPTION 'Commitment review body must bind exact refs, recipient and every promised outcome' USING ERRCODE='23514'; END IF;
 IF v.decision='accepted' AND (
  EXISTS(SELECT 1 FROM jsonb_array_elements(v.body->'checks') check_item WHERE check_item->>'decision'<>'accepted')
  OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(promise.outcome_keys) AS outcomes(outcome_key) WHERE NOT EXISTS(
   SELECT 1 FROM jsonb_array_elements(submission.body->'submission'->'results') result_item WHERE result_item->>'key'=outcome_key AND result_item->>'status'='present' AND jsonb_typeof(result_item->'sources')='array' AND jsonb_array_length(result_item->'sources')>0)))
  OR (v.decision='returned' AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(v.body->'checks') check_item WHERE check_item->>'decision' IN ('rejected','unknown'))) THEN
  RAISE EXCEPTION 'Accepted promise needs all present accepted outcomes; returned retains an unresolved check' USING ERRCODE='23514'; END IF;
END
"""


CURRENT_GUARD = r"""
BEGIN
 IF TG_OP='INSERT' AND NEW.revision=1 THEN RETURN NEW;
 ELSIF TG_OP='UPDATE' AND OLD.state='open' AND NEW.revision=OLD.revision+1
  AND (to_jsonb(NEW)-ARRAY['version_id','revision','state']) IS NOT DISTINCT FROM (to_jsonb(OLD)-ARRAY['version_id','revision','state'])
  AND EXISTS(SELECT 1 FROM public.work_commitment_reviews v WHERE v.tenant_id=NEW.tenant_id AND v.id=NEW.version_id AND v.revision=NEW.revision AND v.previous_id=OLD.version_id AND v.previous_revision=OLD.revision) THEN RETURN NEW;
 END IF;
 RAISE EXCEPTION 'Commitment review Current requires one exact open-state CAS' USING ERRCODE='23514';
END
"""

CURRENT_ATOM = r"""
DECLARE cur public.work_commitment_review_currents; cx xid; vx xid;
BEGIN
 SELECT * INTO STRICT cur FROM public.work_commitment_review_currents WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
 SELECT xmin INTO cx FROM public.work_commitment_review_currents WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
 SELECT xmin INTO vx FROM public.work_commitment_reviews WHERE tenant_id=NEW.tenant_id AND id=cur.version_id;
 IF vx IS DISTINCT FROM cx THEN RAISE EXCEPTION 'Commitment review Current requires its same-transaction immutable fact' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END
"""

PROOF = r"""
DECLARE old_scoped boolean=false; new_scoped boolean=false;
BEGIN
 IF TG_OP<>'INSERT' THEN old_scoped=OLD.operation='work.commitment.review'; END IF;
 IF TG_OP<>'DELETE' THEN new_scoped=NEW.operation='work.commitment.review'; END IF;
 IF old_scoped OR new_scoped THEN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Commitment review confirmation history retained' USING ERRCODE='23514';
  ELSIF TG_OP='INSERT' THEN
   IF NEW.consumed IS DISTINCT FROM false THEN RAISE EXCEPTION 'Commitment review confirmation starts unconsumed' USING ERRCODE='23514'; END IF;
  ELSIF NOT(old_scoped AND new_scoped) OR OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS DISTINCT FROM true
   OR (to_jsonb(NEW)-'consumed') IS DISTINCT FROM (to_jsonb(OLD)-'consumed') THEN
   RAISE EXCEPTION 'Commitment review confirmation only consumes original false to true' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END
"""

TRANSITION = r"""
BEGIN
 IF NEW.operation='work.commitment.review' AND (
  (SELECT count(*) FROM public.work_commitment_reviews v WHERE v.tenant_id=NEW.tenant_id AND v.confirmation_id=NEW.id AND v.operation=NEW.operation)<>1
  OR OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS DISTINCT FROM true) THEN
  RAISE EXCEPTION 'Consumed commitment review confirmation requires exactly one fact' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END
"""

RECEIPT_GUARD = r"""
DECLARE scoped boolean=false;
BEGIN
 IF TG_OP<>'INSERT' THEN scoped=OLD.operation='work.commitment.review' OR OLD.subject_type='work_commitment_review'; END IF;
 IF TG_OP<>'DELETE' THEN scoped=scoped OR NEW.operation='work.commitment.review' OR NEW.subject_type='work_commitment_review'; END IF;
 IF scoped AND TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Commitment review receipt immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END
"""

MEMBER_GUARD = r"""
DECLARE scoped boolean=false; old_scoped boolean=false;
BEGIN
 IF TG_OP<>'DELETE' THEN SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.receipt_id AND (r.operation='work.commitment.review' OR r.subject_type='work_commitment_review')) INTO scoped; END IF;
 IF TG_OP<>'INSERT' THEN SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=OLD.tenant_id AND r.id=OLD.receipt_id AND (r.operation='work.commitment.review' OR r.subject_type='work_commitment_review')) INTO old_scoped; END IF;
 IF TG_OP<>'INSERT' AND (scoped OR old_scoped) THEN
  IF TG_OP='UPDATE' AND TG_TABLE_NAME='outbox_events' AND (to_jsonb(NEW)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) IS NOT DISTINCT FROM (to_jsonb(OLD)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Commitment review audit event or original key immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END
"""

MEMBER_TARGET = r"""
DECLARE r public.action_receipts;
BEGIN
 IF TG_TABLE_NAME='action_receipts' THEN r=NEW; ELSE SELECT * INTO r FROM public.action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id; END IF;
 IF r.operation='work.commitment.review' OR r.subject_type='work_commitment_review' THEN PERFORM public.assert_work_fulfillment_members(r.tenant_id,r.subject_id); END IF;
 RETURN NULL;
END
"""


def functions():
    return (
        ("assert_work_fulfillment_members", "t uuid,target uuid", MEMBERS, "void"),
        ("assert_work_fulfillment_write", "t uuid,target uuid", WRITE_ATOM, "void"),
        ("assert_work_commitment_review", "t uuid,target uuid", REVIEW_ATOM, "void"),
        ("protect_commitment_review_current", "", CURRENT_GUARD, "trigger"),
        ("require_commitment_review_current", "", CURRENT_ATOM, "trigger"),
        ("protect_commitment_review_confirmation", "", PROOF, "trigger"),
        ("require_commitment_review_confirmation", "", TRANSITION, "trigger"),
        ("protect_commitment_review_receipt", "", RECEIPT_GUARD, "trigger"),
        ("protect_commitment_review_member", "", MEMBER_GUARD, "trigger"),
        ("require_commitment_review_member", "", MEMBER_TARGET, "trigger"),
        (
            "reject_commitment_review_mutation",
            "",
            "BEGIN RAISE EXCEPTION 'Commitment review facts are immutable' USING ERRCODE='23514'; END",
            "trigger",
        ),
        (
            "require_work_commitment_review",
            "",
            "BEGIN PERFORM public.assert_work_commitment_review(NEW.tenant_id,NEW.id); RETURN NULL; END",
            "trigger",
        ),
    )


def function_sql():
    return tuple(_function(name, args, body, returns) for name, args, body, returns in functions())


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
        write = "public.category_access(tenant_id,category_id,true) AND public.scope_actor()=public.scope_requester() AND EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND h.id=public.scope_actor() AND h.kind='human' AND h.active)"
        statements.extend(
            (
                f'ALTER TABLE public."{name}" ENABLE ROW LEVEL SECURITY',
                f'ALTER TABLE public."{name}" FORCE ROW LEVEL SECURITY',
                f'CREATE POLICY owner_internal ON public."{name}" TO pdos_next_owner USING(true) WITH CHECK(true)',
                f'CREATE POLICY commitment_review_read ON public."{name}" FOR SELECT TO pdos_next_app USING({read})',
                f'CREATE POLICY commitment_review_insert ON public."{name}" FOR INSERT TO pdos_next_app WITH CHECK({write} AND {read})',
                f'REVOKE ALL ON public."{name}" FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
                f'GRANT SELECT,INSERT ON public."{name}" TO pdos_next_app',
            )
        )
        if name == CURRENT:
            statements.extend(
                (
                    f'CREATE POLICY commitment_review_advance ON public."{name}" FOR UPDATE TO pdos_next_app USING({write} AND {read}) WITH CHECK({write} AND {read})',
                    f'GRANT UPDATE(version_id,revision,state) ON public."{name}" TO pdos_next_app',
                )
            )
    return tuple(statements)


def trigger_sql():
    statements = []
    for table in TABLES:
        statements.extend(
            (
                f"CREATE TRIGGER commitment_review_category BEFORE INSERT ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.bind_model_category()",
                f"CREATE TRIGGER commitment_review_category_immutable BEFORE UPDATE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.protect_category_binding()",
                f"CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.lifecycle_reference_gate()",
                f"CREATE TRIGGER category_lifecycle_clock AFTER INSERT OR UPDATE OR DELETE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.category_lifecycle_clock()",
            )
        )
    statements.extend(
        (
            f"CREATE TRIGGER commitment_review_immutable BEFORE UPDATE OR DELETE ON public.{REVIEW} FOR EACH ROW EXECUTE FUNCTION public.reject_commitment_review_mutation()",
            f"CREATE CONSTRAINT TRIGGER commitment_review_fact_atom AFTER INSERT ON public.{REVIEW} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_work_commitment_review()",
            f"CREATE TRIGGER commitment_review_current_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{CURRENT} FOR EACH ROW EXECUTE FUNCTION public.protect_commitment_review_current()",
            f"CREATE CONSTRAINT TRIGGER commitment_review_current_atom AFTER INSERT OR UPDATE ON public.{CURRENT} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_commitment_review_current()",
            "CREATE TRIGGER commitment_review_proof_guard BEFORE INSERT OR UPDATE OR DELETE ON public.confirmations FOR EACH ROW EXECUTE FUNCTION public.protect_commitment_review_confirmation()",
            "CREATE CONSTRAINT TRIGGER commitment_review_proof_target AFTER UPDATE ON public.confirmations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_commitment_review_confirmation()",
            "CREATE TRIGGER commitment_review_receipt_guard BEFORE INSERT OR UPDATE OR DELETE ON public.action_receipts FOR EACH ROW EXECUTE FUNCTION public.protect_commitment_review_receipt()",
        )
    )
    for name in ("action_receipts", "audit_entries", "outbox_events", "request_keys"):
        statements.append(
            f"CREATE CONSTRAINT TRIGGER commitment_review_member_atom AFTER INSERT ON public.{name} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_commitment_review_member()"
        )
        if name != "action_receipts":
            statements.append(
                f"CREATE TRIGGER commitment_review_member_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.protect_commitment_review_member()"
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
        f"LOCK TABLE public.{REVIEW},public.{CURRENT},public.confirmations,public.action_receipts IN ACCESS EXCLUSIVE MODE",
        f"DO $work_fulfillment$ BEGIN IF EXISTS(SELECT 1 FROM public.{REVIEW}) OR EXISTS(SELECT 1 FROM public.{CURRENT}) OR EXISTS(SELECT 1 FROM public.confirmations WHERE operation='{OPERATION}') OR EXISTS(SELECT 1 FROM public.action_receipts WHERE operation='{OPERATION}' OR subject_type='{SUBJECT}') THEN RAISE EXCEPTION 'Commitment review history retained; downgrade refused' USING ERRCODE='23514'; END IF; END; $work_fulfillment$",
        "DROP TRIGGER commitment_review_proof_guard ON public.confirmations",
        "DROP TRIGGER commitment_review_proof_target ON public.confirmations",
        "DROP TRIGGER commitment_review_receipt_guard ON public.action_receipts",
        *(
            f"DROP TRIGGER commitment_review_member_atom ON public.{name}"
            for name in ("action_receipts", "audit_entries", "outbox_events", "request_keys")
        ),
        *(
            f"DROP TRIGGER commitment_review_member_guard ON public.{name}"
            for name in ("audit_entries", "outbox_events", "request_keys")
        ),
        *(f"DROP TABLE public.{t.name}" for t in reversed(TABLES)),
        *(f"DROP FUNCTION public.{name}" for name in reversed(signatures())),
    )
