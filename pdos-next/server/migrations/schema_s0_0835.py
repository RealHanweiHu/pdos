"""Require actual Human retrieval feedback coupled to its work-state exclusion.

Read policies and all other event kinds are unchanged.
Installed after root rechecked head s0_0834 on 2026-10-29.
"""

SCHEMA_SQL = (
    """CREATE FUNCTION public.require_retrieval_feedback_human() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE
 t uuid=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid;
 actor uuid=public.scope_actor(); requester uuid=public.scope_requester();
 r public.agent_runs; w public.agent_work_states; wx xid; choice jsonb; expected text;
BEGIN
 IF NEW.body->>'type' IS DISTINCT FROM 'retrieval_feedback' THEN RETURN NEW; END IF;
 SELECT * INTO r FROM public.agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id;
 IF t IS NULL OR NEW.tenant_id IS DISTINCT FROM t OR actor IS NULL
  OR actor IS DISTINCT FROM requester OR r.id IS NULL
  OR r.requester_id IS DISTINCT FROM actor
  OR r.category_id IS DISTINCT FROM NULLIF(current_setting('pdos.category_id',true),'')::uuid
  OR (r.category_id IS NOT NULL
      AND public.category_access(t,r.category_id,false) IS DISTINCT FROM true)
  OR NOT EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=t AND p.id=actor
                AND p.kind='human' AND p.active)
  OR NEW.body->>'recorded_by' IS DISTINCT FROM actor::text THEN
  RAISE EXCEPTION 'Retrieval feedback requires the actual readable Human owner'
   USING ERRCODE='42501';
 END IF;
 choice=NEW.body->'selection';
 IF NEW.body->>'feedback_id' IS DISTINCT FROM NEW.id::text
  OR NEW.body->>'version' IS DISTINCT FROM 'retrieval-feedback/v1'
  OR NEW.body->>'action' IS DISTINCT FROM 'not_relevant'
  OR jsonb_typeof(choice) IS DISTINCT FROM 'object'
  OR NOT COALESCE(choice->>'kind' IN ('artifact','citation'),false)
  OR NOT COALESCE(choice->>'id' ~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$',false)
  OR NOT COALESCE(NEW.body->>'work_state_id' ~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$',false)
  OR NOT COALESCE(NEW.body->>'request_key'
                 ~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$',false) THEN
  RAISE EXCEPTION 'Retrieval feedback requires its exact exclusion identity'
   USING ERRCODE='23514';
 END IF;
 SELECT * INTO w FROM public.agent_work_states
  WHERE tenant_id=t AND id=(NEW.body->>'work_state_id')::uuid;
 SELECT xmin INTO wx FROM public.agent_work_states WHERE tenant_id=t AND id=w.id;
 expected=encode(sha256(convert_to(public.kernel_read_canonical_json(jsonb_build_object(
  'expected_revision',w.revision-1,'action','exclude_source','item_id',choice->>'id')),'UTF8')),'hex');
 IF w.id IS NULL OR w.origin IS DISTINCT FROM 'human' OR w.owner_id IS DISTINCT FROM actor
  OR w.session_id IS DISTINCT FROM r.session_id
  OR w.request_key IS DISTINCT FROM (NEW.body->>'request_key')::uuid
  OR w.request_sha256 IS DISTINCT FROM NEW.body->>'request_digest'
  OR w.request_sha256 IS DISTINCT FROM expected
  OR NEW.body->'work_state_revision' IS DISTINCT FROM to_jsonb(w.revision)
  OR w.body#>>'{current_goal,run_id}' IS DISTINCT FROM r.id::text
  OR wx::text::bigint IS DISTINCT FROM txid_current()%4294967296
  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(w.body->'exclusions') entry
                WHERE entry->>'id'=choice->>'id' AND entry->>'kind'=choice->>'kind'
                  AND entry->>'reason'='用户标记不相关') THEN
  RAISE EXCEPTION 'Retrieval feedback and its actual Human exclusion must commit together'
   USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;""",
    "CREATE TRIGGER kernel_retrieval_feedback_human BEFORE INSERT ON public.agent_run_events "
    "FOR EACH ROW WHEN (NEW.body->>'type'='retrieval_feedback') "
    "EXECUTE FUNCTION public.require_retrieval_feedback_human()",
    "REVOKE ALL ON FUNCTION public.require_retrieval_feedback_human() "
    "FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch",
    "GRANT EXECUTE ON FUNCTION public.require_retrieval_feedback_human() TO pdos_next_app",
)

DOWNGRADE_SQL = (
    "DROP TRIGGER kernel_retrieval_feedback_human ON public.agent_run_events",
    "DROP FUNCTION public.require_retrieval_feedback_human()",
)
