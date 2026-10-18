"""Narrow SQL extensions over captured, installed work guards; no executor.

The native item is an existing project result, not a new artifact or permission.
Only task facts may use that exact immutable association without artifact reads.
The migration supplies actual predecessor definitions and owns column/check DDL.
"""

# ruff: noqa: E501 -- PostgreSQL comparisons stay readable as complete expressions.

from collections.abc import Mapping

WRITE_SIGNATURE = "assert_work_management_write(uuid,uuid,text)"
TASK_SIGNATURE = "assert_work_task(uuid,uuid)"

NATIVE_GUARD = r"""
CREATE FUNCTION public.assert_work_task_g0_source(t uuid,target uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $g0_work$
DECLARE v public.work_task_versions; prior public.work_task_versions; oi public.project_open_items;
 native jsonb; expected jsonb; binding jsonb;
BEGIN
 SELECT * INTO STRICT v FROM public.work_task_versions WHERE tenant_id=t AND id=target;
 native=v.source_basis->'g0_open_item';
 IF (v.g0_open_item_id IS NULL)<>(v.g0_decision_id IS NULL) THEN
  RAISE EXCEPTION 'Task G0 association requires both identities' USING ERRCODE='23514'; END IF;
 IF v.g0_open_item_id IS NULL THEN
  IF coalesce(v.body->'g0_open_item','null'::jsonb)<>'null'::jsonb
   OR coalesce(native,'null'::jsonb)<>'null'::jsonb
   OR jsonb_array_length(v.sources)=0 OR jsonb_array_length(v.reads)=0
   OR (v.revision=1 AND coalesce(v.command->'envelope'->'payload'->'g0_open_item','null'::jsonb)<>'null'::jsonb) THEN
   RAISE EXCEPTION 'Ordinary task requires its original artifact sources' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT * INTO oi FROM public.project_open_items x WHERE x.tenant_id=t AND x.id=v.g0_open_item_id
   AND x.category_id=v.category_id AND x.product_id=v.product_id AND x.project_id=v.project_id
   AND x.g0_decision_id=v.g0_decision_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'Task G0 item is outside its exact project' USING ERRCODE='23514'; END IF;
  expected=jsonb_build_object('id',oi.id,'decision_id',oi.g0_decision_id,'kind',oi.kind,
   'title',oi.title,'note',oi.note,'owner_id',oi.owner_id,'due_date',oi.due_date::text,
   'source_question_id',oi.source_question_id,'source_spec_item_id',oi.source_spec_item_id,
   'category_id',oi.category_id,'product_id',oi.product_id,'project_id',oi.project_id);
  binding=jsonb_build_object('id',v.g0_open_item_id,'decision_id',v.g0_decision_id);
  IF oi.kind NOT IN ('task','risk') OR jsonb_typeof(native) IS DISTINCT FROM 'object'
   OR (native-'digest') IS DISTINCT FROM expected OR native->>'digest' IS NULL
   OR native->>'digest' !~ '^[a-f0-9]{64}$'
   OR v.body->'g0_open_item' IS DISTINCT FROM binding
   OR (v.revision=1 AND v.command->'envelope'->'payload'->'g0_open_item' IS DISTINCT FROM binding)
   OR (jsonb_array_length(v.sources)=0)<>(jsonb_array_length(v.reads)=0)
   OR NOT EXISTS(SELECT 1 FROM public.projects p JOIN public.proposal_decisions d
    ON d.tenant_id=p.tenant_id AND d.category_id=p.category_id AND d.id=p.g0_decision_id
    WHERE p.tenant_id=t AND p.category_id=v.category_id AND p.product_id=v.product_id
     AND p.id=v.project_id AND p.g0_decision_id=v.g0_decision_id
     AND d.outcome='approved' AND d.created_project_id=p.id AND d.created_product_id=p.product_id) THEN
   RAISE EXCEPTION 'Task G0 source must match its actual fixed project result' USING ERRCODE='23514'; END IF;
 END IF;
 IF v.revision>1 THEN
  SELECT * INTO STRICT prior FROM public.work_task_versions WHERE tenant_id=t AND id=v.previous_id;
  IF ROW(v.g0_open_item_id,v.g0_decision_id) IS DISTINCT FROM ROW(prior.g0_open_item_id,prior.g0_decision_id)
   OR coalesce(native,'null'::jsonb) IS DISTINCT FROM coalesce(prior.source_basis->'g0_open_item','null'::jsonb) THEN
   RAISE EXCEPTION 'Task continuation cannot replace its fixed G0 source' USING ERRCODE='23514'; END IF;
 END IF;
END;
$g0_work$
""".strip()

OPEN_ITEM_GUARD = r"""
CREATE FUNCTION public.protect_g0_open_item_source() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $g0_work$
BEGIN
 IF TG_OP='UPDATE' AND (to_jsonb(NEW)-'status') IS NOT DISTINCT FROM (to_jsonb(OLD)-'status') THEN
  RETURN NEW; END IF;
 RAISE EXCEPTION 'G0 source fields are immutable; status is not task completion' USING ERRCODE='23514';
END;
$g0_work$
""".strip()

WRITE_ANCHOR = " envelope=v.command->'envelope';"
WRITE_EXTENSION = r"""
 IF kind='work_task' THEN PERFORM public.assert_work_task_g0_source(t,target);
 ELSIF v.source_basis ? 'g0_open_item' THEN
  RAISE EXCEPTION 'Only a task may use a native G0 source basis' USING ERRCODE='23514'; END IF;
""".rstrip()
BASE_ANCHOR = "(v.body-allowed) IS DISTINCT FROM (prior.body-allowed)"
BASE_EXTENSION = (
    "(v.body-allowed-'g0_open_item') IS DISTINCT FROM (prior.body-allowed-'g0_open_item')"
    " OR coalesce(v.body->'g0_open_item','null'::jsonb)"
    " IS DISTINCT FROM coalesce(prior.body->'g0_open_item','null'::jsonb)"
)


def _once(value: str, anchor: str, replacement: str) -> str:
    if value.count(anchor) != 1:
        raise ValueError(f"Captured work guard must contain one exact anchor: {anchor}")
    return value.replace(anchor, replacement, 1)


def _captured(definitions: Mapping[str, str], signature: str) -> str:
    value = definitions.get(signature)
    name = signature.partition("(")[0]
    if not isinstance(value, str) or f"FUNCTION public.{name}(" not in value:
        raise ValueError(f"Missing actual captured function: {signature}")
    if "SECURITY DEFINER" not in value or "SET search_path" not in value:
        raise ValueError(f"Captured function lost its owner/search-path contract: {signature}")
    return value


def upgraded_functions(definitions: Mapping[str, str]) -> dict[str, str]:
    """Preserve actual predecessor guards except these two explicit insertions."""
    write = _captured(definitions, WRITE_SIGNATURE)
    task = _captured(definitions, TASK_SIGNATURE)
    if "public.assert_work_task_g0_source(" in write or BASE_EXTENSION in task:
        raise ValueError("Captured work guards already contain the G0 extension")
    write = _once(write, WRITE_ANCHOR, WRITE_ANCHOR + "\n" + WRITE_EXTENSION)
    task = _once(task, BASE_ANCHOR, BASE_EXTENSION)
    return {WRITE_SIGNATURE: write, TASK_SIGNATURE: task}


def upgrade_sql(definitions: Mapping[str, str]) -> tuple[str, ...]:
    """Declarations only; the root migration supplies verified live predecessors."""
    upgraded = upgraded_functions(definitions)
    return (
        NATIVE_GUARD,
        upgraded[WRITE_SIGNATURE],
        upgraded[TASK_SIGNATURE],
        OPEN_ITEM_GUARD,
        "CREATE TRIGGER protect_g0_open_item_source BEFORE UPDATE OR DELETE ON public.project_open_items "
        "FOR EACH ROW EXECUTE FUNCTION public.protect_g0_open_item_source()",
        "REVOKE ALL ON FUNCTION public.assert_work_task_g0_source(uuid,uuid),"
        "public.protect_g0_open_item_source() FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch",
    )
