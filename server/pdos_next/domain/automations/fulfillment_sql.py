"""New helper plus an insertion hook for root's captured actual start function.

No old migration/function module is imported. The migration host must restore its
captured start definition before rollback_sql(), and freezes both definitions.
"""

# ruff: noqa: E501 -- retain complete PostgreSQL predicates.

import re

SIGNATURE = "automation_commitment_source_state(uuid)"
START_ANCHOR = " SELECT x.error_code INTO reason FROM public.automation_service_attempts x WHERE x.tenant_id=t AND x.service_grant_id=g.id\n"

SOURCE_STATE = r"""
DECLARE t uuid=nullif(current_setting('pdos.tenant_id',true),'')::uuid;
 a public.automation_service_attempts; g public.automation_service_grants; v public.automation_rule_versions;
 promise public.work_commitment_versions; config jsonb;
BEGIN
 SELECT * INTO STRICT a FROM public.automation_service_attempts WHERE tenant_id=t AND id=target;
 SELECT * INTO STRICT g FROM public.automation_service_grants WHERE tenant_id=t AND id=a.service_grant_id;
 IF NOT COALESCE(public.automation_service_identity(t,g.owner_id,g.writer_id),false)
  OR g.category_id IS DISTINCT FROM nullif(current_setting('pdos.category_id',true),'')::uuid
  OR ROW(a.category_id,a.owner_id,a.writer_id,a.rule_id,a.published_version_id)
    IS DISTINCT FROM ROW(g.category_id,g.owner_id,g.writer_id,g.rule_id,g.published_version_id) THEN
  RAISE EXCEPTION 'Promise source requires the actual stored service identity' USING ERRCODE='42501'; END IF;
 SELECT * INTO STRICT v FROM public.automation_rule_versions WHERE tenant_id=t AND id=g.published_version_id;
 IF v.spec->>'trigger_kind' IS DISTINCT FROM 'relative_milestone'
  OR v.spec#>>'{trigger_config,source_kind}' IS DISTINCT FROM 'commitment' THEN RETURN NULL; END IF;
 config=v.spec->'trigger_config';
 SELECT w.* INTO promise FROM public.work_commitment_currents current_promise
 JOIN public.work_commitment_versions w ON
  ROW(w.tenant_id,w.category_id,w.product_id,w.project_id,w.owner_id,w.visibility,w.task_id,w.promisor_id,w.recipient_id,w.series_id,w.id,w.revision)
  =ROW(current_promise.tenant_id,current_promise.category_id,current_promise.product_id,current_promise.project_id,current_promise.owner_id,current_promise.visibility,current_promise.task_id,current_promise.promisor_id,current_promise.recipient_id,current_promise.series_id,current_promise.version_id,current_promise.revision)
 WHERE current_promise.tenant_id=t AND current_promise.category_id=g.category_id
  AND current_promise.product_id=(v.spec->>'product_id')::uuid
  AND current_promise.project_id=(config->>'project_id')::uuid
  AND current_promise.task_id=(config->>'task_id')::uuid
  AND current_promise.promisor_id=(config->>'promisor_id')::uuid
  AND current_promise.recipient_id=(config->>'recipient_id')::uuid;
 IF NOT FOUND OR NOT public.work_receipt_project_visible(t,g.category_id,promise.product_id,'work_commitment',promise.id,promise.revision,promise.receipt_id,promise.actor_id) THEN
  RETURN 'SCOPE_INVALID'; END IF;
 IF a.trigger_kind IS DISTINCT FROM 'relative_milestone' OR a.origin->>'kind' IS DISTINCT FROM 'relative_milestone'
  OR a.origin->>'source_kind' IS DISTINCT FROM 'commitment'
  OR ROW(a.origin->>'category_id',a.origin->>'product_id',a.origin->>'project_id',a.origin->>'task_id',a.origin->>'task_revision',a.origin->>'commitment_id',a.origin->>'commitment_revision',a.origin->>'series_id',a.origin->>'promisor_id',a.origin->>'recipient_id')
   IS DISTINCT FROM ROW(g.category_id::text,promise.product_id::text,promise.project_id::text,promise.task_id::text,promise.task_revision::text,promise.id::text,promise.revision::text,promise.series_id::text,promise.promisor_id::text,promise.recipient_id::text)
  OR a.origin->>'clock' IS DISTINCT FROM 'promised_at'
  OR (a.origin->>'source_at')::timestamptz IS DISTINCT FROM promise.promised_at
  OR a.origin->>'original_timezone' IS DISTINCT FROM promise.original_timezone
  OR a.origin->>'calendar_id' IS DISTINCT FROM promise.calendar_id::text
  OR a.origin->>'offset_seconds' IS DISTINCT FROM config->>'offset_seconds'
  OR a.due_at IS DISTINCT FROM promise.promised_at+make_interval(secs=>(config->>'offset_seconds')::integer) THEN
  RETURN 'SOURCE_SUPERSEDED'; END IF;
 IF EXISTS(SELECT 1 FROM public.work_commitment_review_currents current_review
  JOIN public.work_commitment_reviews review ON
   ROW(review.tenant_id,review.category_id,review.product_id,review.project_id,review.owner_id,review.visibility,review.commitment_id,review.id,review.revision,review.state)
   =ROW(current_review.tenant_id,current_review.category_id,current_review.product_id,current_review.project_id,current_review.owner_id,current_review.visibility,current_review.commitment_id,current_review.version_id,current_review.revision,current_review.state)
  WHERE ROW(current_review.tenant_id,current_review.category_id,current_review.product_id,current_review.project_id,current_review.owner_id,current_review.visibility,current_review.commitment_id)
   =ROW(t,g.category_id,promise.product_id,promise.project_id,promise.owner_id,promise.visibility,promise.id)
   AND review.commitment_revision=promise.revision AND review.series_id=promise.series_id AND review.task_id=promise.task_id
   AND review.promisor_id=promise.promisor_id AND review.recipient_id=promise.recipient_id AND current_review.state='fulfilled') THEN
  RETURN 'GOAL_REACHED'; END IF;
 RETURN NULL;
END
"""

START_HOOK = r"""
 -- Category is already locked. Recheck the fixed promise before cooldown/due
 -- early returns and actual Run admission; fulfilled is independent of Task state.
 reason=public.automation_commitment_source_state(a.id);
 IF reason IS NOT NULL THEN
  UPDATE public.automation_service_attempts SET state='suppressed',error_code=reason WHERE tenant_id=t AND id=a.id;
  IF reason IN ('GOAL_REACHED','SCOPE_INVALID') THEN PERFORM public.automation_service_stop(g.id,reason); END IF;
  RETURN NULL;
 END IF;
"""


def function_sql():
    return (
        "CREATE FUNCTION public.automation_commitment_source_state(target uuid) RETURNS text\n"
        "LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp "
        f"AS $automation_fulfillment$\n{SOURCE_STATE.rstrip()};\n$automation_fulfillment$",
    )


def start_hook():
    return START_HOOK


def insert_start_hook(captured_definition):
    """Reject a changed capture instead of silently rewriting another function."""
    if (
        not isinstance(captured_definition, str)
        or not re.search(r"FUNCTION\s+public\.automation_service_start\(", captured_definition)
        or captured_definition.count(START_ANCHOR) != 1
        or "automation_commitment_source_state(" in captured_definition
    ):
        raise ValueError("Expected the reviewed actual automation_service_start capture")
    hooked = captured_definition.replace(START_ANCHOR, START_HOOK + START_ANCHOR, 1)
    if not (
        hooked.index("FROM public.categories WHERE")
        < hooked.index("automation_commitment_source_state(a.id)")
        < hooked.index("point<a.due_at")
        < hooked.index("INSERT INTO public.agent_runs")
    ):
        raise ValueError("Start source check must follow Category lock and precede admission")
    return hooked


def upgrade_sql():
    return (
        *function_sql(),
        f"REVOKE ALL ON FUNCTION public.{SIGNATURE} FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch",
    )


def rollback_sql():
    """Root restores the captured start before removing this private helper."""
    return (f"DROP FUNCTION public.{SIGNATURE}",)
