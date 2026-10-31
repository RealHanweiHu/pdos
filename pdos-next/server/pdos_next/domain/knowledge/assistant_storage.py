"""Unnumbered schema proposal. Root allocates/applies only after its real-head check."""

# ruff: noqa: E501 -- auditable SQL literals preserve complete predicates

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from .assistant_models import KnowledgeAnswerReview, KnowledgeGapAttribution, KnowledgeGapSubmission

TABLES = (
    KnowledgeAnswerReview.__table__,
    KnowledgeGapSubmission.__table__,
    KnowledgeGapAttribution.__table__,
)
HUMAN = """tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid
 AND public.scope_actor()=public.scope_requester()
 AND EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid
 AND h.id=public.scope_actor() AND h.kind='human' AND h.active)"""
MANAGER = """EXISTS(SELECT 1 FROM public.categories c WHERE c.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid
 AND c.id=category_id AND c.owner_id=public.scope_requester())"""
SUBJECT_READ = """((subject_kind='category' AND EXISTS(SELECT 1 FROM public.category_knowledge_entries k
 WHERE k.tenant_id=knowledge_answer_reviews.tenant_id AND k.category_id=knowledge_answer_reviews.category_id AND k.id=subject_id))
 OR (subject_kind='candidate' AND EXISTS(SELECT 1 FROM public.knowledge_candidate_versions k
 WHERE k.tenant_id=knowledge_answer_reviews.tenant_id AND k.category_id=knowledge_answer_reviews.category_id AND k.id=subject_id))
 OR (subject_kind='rule' AND EXISTS(SELECT 1 FROM public.knowledge_rule_versions k
 WHERE k.tenant_id=knowledge_answer_reviews.tenant_id AND k.category_id=knowledge_answer_reviews.category_id AND k.id=subject_id)))"""


def function(name, args, body, returns="trigger"):
    return (
        f"CREATE FUNCTION public.{name}({args}) RETURNS {returns} LANGUAGE plpgsql "
        "SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $knowledge_assistant$\n"
        + body
        + "\n$knowledge_assistant$"
    )


GUARD = r"""
DECLARE subject jsonb; sx xid; rx xid; nx xid; receipt public.action_receipts; origin public.agent_runs;
 category public.categories; actual_owner uuid; field_name text;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Knowledge contribution facts are append-only' USING ERRCODE='23514'; END IF;
 IF NEW.tenant_id IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid
 OR public.scope_actor() IS DISTINCT FROM public.scope_requester()
 OR NOT EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id=NEW.tenant_id AND h.id=public.scope_actor() AND h.active AND h.kind='human')
 OR NOT public.category_access(NEW.tenant_id,NEW.category_id,false) THEN
  RAISE EXCEPTION 'Only the actual authorized Human may append knowledge contributions' USING ERRCODE='42501'; END IF;
 SELECT * INTO STRICT category FROM public.categories WHERE tenant_id=NEW.tenant_id AND id=NEW.category_id;
 IF TG_TABLE_NAME='knowledge_answer_reviews' THEN
  IF NOT public.category_access(NEW.tenant_id,NEW.category_id,true) THEN
   RAISE EXCEPTION 'Knowledge review uses its native category write authority' USING ERRCODE='42501'; END IF;
  IF NOT EXISTS(SELECT 1 FROM public.principals p JOIN public.grants g ON g.tenant_id=p.tenant_id AND g.principal_id=p.id
   WHERE p.tenant_id=NEW.tenant_id AND p.id=NEW.responsible_id AND p.kind='human' AND p.active
   AND g.category_id=NEW.category_id AND (g.expires_at IS NULL OR g.expires_at>transaction_timestamp())) THEN
   RAISE EXCEPTION 'Review responsible person must be an active actual category reader' USING ERRCODE='23514'; END IF;
  EXECUTE format('SELECT to_jsonb(x),xmin FROM public.%I x WHERE tenant_id=$1 AND category_id=$2 AND id=$3',
   CASE NEW.subject_kind WHEN 'category' THEN 'category_knowledge_entries' WHEN 'candidate' THEN 'knowledge_candidate_versions' WHEN 'rule' THEN 'knowledge_rule_versions' END)
   INTO STRICT subject,sx USING NEW.tenant_id,NEW.category_id,NEW.subject_id;
  SELECT * INTO STRICT receipt FROM public.action_receipts r WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.receipt_id;
  SELECT xmin INTO rx FROM public.action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id;
  SELECT xmin INTO nx FROM public.knowledge_answer_reviews WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
  IF sx IS DISTINCT FROM rx OR nx IS DISTINCT FROM sx OR subject->>'receipt_id' IS DISTINCT FROM NEW.receipt_id::text
   OR receipt.command_id<>NEW.command_id OR receipt.actor_id<>public.scope_actor()
   OR receipt.requester_id<>public.scope_requester()
   OR (NEW.verified_by IS NOT NULL AND NEW.verified_by<>public.scope_requester())
   OR (NEW.subject_kind='candidate' AND NEW.verified_by IS NOT NULL)
   OR (NEW.subject_kind='rule' AND (receipt.operation<>'knowledge.rule.publish' OR receipt.confirmation_id IS NULL OR NEW.verified_by IS NULL)) THEN
   RAISE EXCEPTION 'Review must share its real native version and Human receipt transaction' USING ERRCODE='23514'; END IF;
  IF NEW.source_proof IS DISTINCT FROM (CASE WHEN NEW.subject_kind='category'
      THEN subject->'answer_sources' ELSE subject#>'{source_basis,answer_sources}' END) THEN
   RAISE EXCEPTION 'Native proof and review must be identical' USING ERRCODE='23514'; END IF;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.source_proof) ref WHERE ref->>'source_type'='knowledge' AND (
    EXISTS(SELECT 1 FROM public.category_knowledge_entries k WHERE k.tenant_id=NEW.tenant_id
      AND k.id::text=ref->>'source_id' AND coalesce(jsonb_array_length(k.answer_sources),0)>0)
    OR EXISTS(SELECT 1 FROM public.knowledge_rule_versions k WHERE k.tenant_id=NEW.tenant_id
      AND k.id::text=ref->>'source_id' AND coalesce(jsonb_array_length(k.source_basis->'answer_sources'),0)>0))) THEN
   RAISE EXCEPTION 'Reviewed knowledge proofs must flatten existing answer-derived parents' USING ERRCODE='23514'; END IF;
  IF NEW.origin_run_id IS NOT NULL THEN
   SELECT * INTO STRICT origin FROM public.agent_runs WHERE tenant_id=NEW.tenant_id AND (category_id=NEW.category_id OR category_id IS NULL) AND id=NEW.origin_run_id;
   IF origin.state NOT IN ('completed','partial') OR origin.reverted_at IS NOT NULL
    OR NOT public.knowledge_answer_sources_known(NEW.origin_run_id,NEW.source_proof) THEN
    RAISE EXCEPTION 'Answer origin is not an actual retained completed answer' USING ERRCODE='23514'; END IF;
   IF origin.requester_id<>public.scope_requester() AND NOT EXISTS(
    SELECT 1 FROM public.knowledge_answer_reviews prior WHERE prior.tenant_id=NEW.tenant_id
    AND prior.origin_run_id=NEW.origin_run_id AND prior.answer_digest=NEW.answer_digest
    AND prior.source_proof=NEW.source_proof AND (
     (NEW.subject_kind='rule' AND prior.subject_id::text=subject->>'candidate_version_id')
     OR (NEW.subject_kind='candidate' AND prior.subject_id::text=subject->>'previous_id')
     OR (NEW.subject_kind='category' AND EXISTS(SELECT 1 FROM public.category_knowledge_entries p
         WHERE p.id=prior.subject_id AND p.lineage_id::text=subject->>'lineage_id'
         AND p.version<(subject->>'version')::integer)))) THEN
    RAISE EXCEPTION 'A new answer origin must belong to the actual Human; inherited native evidence stays fixed' USING ERRCODE='23514'; END IF;
  END IF;
 ELSE
  IF TG_TABLE_NAME='knowledge_gap_submissions' THEN
   IF NEW.owner_id<>public.scope_requester() OR NEW.recipient_id<>category.owner_id THEN
    RAISE EXCEPTION 'Gap sharing binds the actual owner and current category recipient' USING ERRCODE='23514'; END IF;
   SELECT * INTO STRICT origin FROM public.agent_runs WHERE tenant_id=NEW.tenant_id AND (category_id=NEW.category_id OR category_id IS NULL) AND id=NEW.run_id;
   IF origin.requester_id<>NEW.owner_id OR origin.state NOT IN ('completed','partial') OR origin.reverted_at IS NOT NULL
    OR (NEW.kind='missing_material' AND (NEW.answer IS NOT NULL OR jsonb_array_length(NEW.source_proof)<>0))
    OR (NEW.kind='shared_feedback' AND NOT public.knowledge_answer_sources_known(NEW.run_id,NEW.source_proof))
    OR (NEW.kind='shared_feedback' AND NOT EXISTS(SELECT 1 FROM public.agent_run_events e
        WHERE e.id=NEW.feedback_id AND e.tenant_id=NEW.tenant_id AND e.run_id=NEW.run_id
        AND e.body->>'type'='run_feedback' AND e.body->>'recorded_by'=NEW.owner_id::text)) THEN
    RAISE EXCEPTION 'Only an actual explicit owner submission or actual private feedback may be shared' USING ERRCODE='23514'; END IF;
  ELSE
   IF NEW.actor_id<>public.scope_requester() OR category.owner_id<>NEW.actor_id
    OR NOT EXISTS(SELECT 1 FROM public.knowledge_gap_submissions g WHERE g.tenant_id=NEW.tenant_id AND g.category_id=NEW.category_id AND g.id=NEW.submission_id) THEN
    RAISE EXCEPTION 'Only the current actual category owner may attribute a submitted gap' USING ERRCODE='42501'; END IF;
  END IF;
 END IF;
 RETURN NULL;
END
"""


SOURCES_KNOWN = r"""
DECLARE valid boolean;
BEGIN
 WITH RECURSIVE
 -- Only the actual linked conversation is eligible. Merely sharing an owner or
 -- session is insufficient, and unrelated Runs are never scanned for UUIDs.
 origin AS MATERIALIZED (
  SELECT r.* FROM public.agent_runs r WHERE r.id=origin_id
   AND r.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid
 ), lineage(id,path) AS (
  SELECT id,ARRAY[id] FROM origin
  UNION ALL
  SELECT p.id,l.path||p.id FROM lineage l JOIN public.agent_runs child ON child.id=l.id
   JOIN public.agent_runs p ON p.id=child.continued_from_id
   JOIN origin o ON p.tenant_id=o.tenant_id AND p.session_id=o.session_id
    AND p.requester_id=o.requester_id
   WHERE NOT p.id=ANY(l.path)
 ), retained_runs AS MATERIALIZED (
  SELECT r.* FROM public.agent_runs r JOIN lineage l ON l.id=r.id
   WHERE r.reverted_at IS NULL
 ), sealed_reads AS MATERIALIZED (
  -- kernel_read_guard sealed these exact bindings at claim/settle; terminal
  -- guards prohibit changing their results. Recheck the retained identity and
  -- completed model position, rather than trusting a read_kind tag or prose.
  SELECT c.*,r.session_id,r.requester_id FROM retained_runs r
   JOIN public.agent_tool_calls c ON c.tenant_id=r.tenant_id AND c.run_id=r.id
   JOIN public.agent_tool_calls m ON m.tenant_id=r.tenant_id AND m.run_id=r.id
    AND m.id::text=c.execution_binding->>'model_call_id'
   WHERE c.state='completed' AND c.error_code IS NULL AND c.receipt_id IS NULL
    AND c.tool IN ('assistant.search','assistant.materials.read',
      'assistant.citations.read','conversation.history')
    AND m.tool='model' AND m.state='completed' AND m.error_code IS NULL
    AND m.receipt_id IS NULL AND m.execution_binding->>'kind'='model'
    AND m.execution_binding->>'isolation'='main'
    AND c.execution_binding=jsonb_build_object(
      'kind','read','read_kind','ordinary/v1','proof_version',1,'graph','xiaopai','step','tools',
      'isolation','main','tenant_id',r.tenant_id,'category_id',r.category_id,
      'run_id',r.id,'session_id',r.session_id,'requester_id',r.requester_id,'writer_id',r.writer_id,
      'product_id',r.product_id,'proposal_id',r.proposal_id,
      'cancel_epoch',r.cancel_epoch-CASE WHEN r.state='cancelled' THEN 1 ELSE 0 END,
      'private_context',r.private_context,
      'data_categories',(SELECT coalesce(jsonb_agg(value ORDER BY value COLLATE "C"),'[]'::jsonb)
        FROM jsonb_array_elements_text(r.data_categories)),
      'customer_identities',r.customer_identities,'tool',c.tool,'call_key',c.call_key,
      'model_call_id',m.id,'response_index',c.execution_binding->'response_index',
      'model_version',m.execution_binding->'model_version',
      'model_route_digest',m.execution_binding->'model_route_digest',
      'tool_definitions_digest',m.execution_binding->'tool_definitions_digest',
      'prompt_digest',m.execution_binding->'prompt_digest')
    AND c.execution_binding->'cancel_epoch'=m.execution_binding->'cancel_epoch'
    AND m.execution_binding->'model_version'=r.versions->'model_version'
    AND m.execution_binding->'model_route_digest'=r.versions->'model_route_digest'
    AND m.execution_binding->'prompt_digest'=r.versions->'prompt_prefixes'->'main'
    AND (m.execution_binding->'tool_definitions_digest'=r.versions->'tool_definitions'->'main'
      OR coalesce(r.versions#>'{tool_disclosures,main,chain}','[]'::jsonb)
       @>jsonb_build_array(m.execution_binding->'tool_definitions_digest'))
    AND c.call_key='agent:'||r.id::text||':model:'||m.id::text||':'
      ||(c.execution_binding->>'response_index')
    AND m.result->'calls'->(c.execution_binding->>'response_index')::integer->>'name'=c.tool
    AND c.input_digest=encode(sha256(convert_to(public.kernel_read_canonical_json(
      jsonb_build_array(c.tool,m.result->'calls'->(c.execution_binding->>'response_index')::integer
       ->'arguments')),'UTF8')),'hex')
 ), disclosed_pages(value) AS (
  SELECT o.versions->'conversation_memory' FROM origin o
  UNION ALL
  SELECT c.result FROM sealed_reads c JOIN origin o ON c.run_id=o.id
   WHERE c.tool='conversation.history'
 ), carried_runs(id) AS (
  SELECT id FROM origin
  UNION
  SELECT r.id FROM disclosed_pages page
   CROSS JOIN LATERAL jsonb_array_elements(coalesce(page.value->'turns','[]'::jsonb)) turn
   JOIN retained_runs r ON r.id::text=turn->>'run_id'
   WHERE turn->'historical_outcome' IS NOT NULL AND turn->'historical_outcome'<>'null'::jsonb
    AND NOT EXISTS(SELECT 1 FROM origin o WHERE coalesce(
      o.versions#>'{work_state,context_selection}',o.versions->'requested_context_selection',
      'null'::jsonb)<>'null'::jsonb)
  UNION
  SELECT r.id FROM origin o JOIN public.agent_work_states state
   ON state.tenant_id=o.tenant_id AND state.session_id=o.session_id
    AND state.revision::text=o.versions#>>'{work_state,revision}'
   JOIN retained_runs r ON r.id::text=state.body#>>'{current_goal,run_id}'
   WHERE (coalesce(jsonb_array_length(o.versions#>'{work_state,unfinished}'),0)>0
    OR coalesce(jsonb_array_length(o.versions#>'{work_state,questions}'),0)>0)
    AND coalesce(o.versions#>'{work_state,context_selection}',
      o.versions->'requested_context_selection','null'::jsonb)='null'::jsonb
 ), root_items AS MATERIALIZED (
  SELECT c.run_id,item FROM sealed_reads c
   CROSS JOIN LATERAL jsonb_array_elements(coalesce(c.result->'items','[]'::jsonb)) item
   WHERE c.tool IN ('assistant.search','assistant.materials.read')
 ), inherited_refs(run_id,ref) AS (
  SELECT r.id,ref FROM retained_runs r JOIN carried_runs carried ON carried.id=r.id
   CROSS JOIN LATERAL jsonb_array_elements(coalesce(r.versions#>'{work_state,citations}','[]'::jsonb)) ref
  UNION ALL
  SELECT c.run_id,ref FROM sealed_reads c JOIN carried_runs carried ON carried.id=c.run_id
   CROSS JOIN LATERAL jsonb_array_elements(coalesce(c.result->'items','[]'::jsonb)) ref
   WHERE c.tool='assistant.citations.read'
 ), disclosed_sources(value) AS (
  SELECT item FROM root_items root JOIN carried_runs carried ON carried.id=root.run_id
  UNION ALL
  -- A preview/reissued CID supplies no content identity itself: match it to the
  -- original completed root read in this same linked conversation.
  SELECT root.item FROM inherited_refs inherited JOIN root_items root
   ON root.run_id::text=inherited.ref->>'origin_run_id'
    AND root.item->>'citation_id'=inherited.ref->>'origin_citation_id'
 ),
 initial(value) AS (
  SELECT value FROM disclosed_sources
  UNION ALL
  SELECT value FROM public.agent_runs r,
   LATERAL jsonb_array_elements(coalesce(r.result#>'{result,assistant,sources}','[]'::jsonb)) entry(value)
   WHERE r.id=origin_id AND r.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid
  UNION ALL
  SELECT jsonb_build_object('source_type','artifact','source_id',a.id,'source_revision',a.revision,
   'content_hash',a.content_hash,'category_id',a.category_id)
   FROM public.agent_runs r CROSS JOIN LATERAL jsonb_array_elements(r.read_sources) ref(value)
   JOIN public.artifact_versions a ON a.tenant_id=r.tenant_id AND (r.category_id IS NULL OR a.category_id=r.category_id)
    AND a.id::text=ref.value->>'artifact_id' AND a.revision::text=ref.value->>'expected_revision'
   WHERE r.id=origin_id AND r.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid
 ), closure(value,seen) AS (
  SELECT value,ARRAY[value->>'source_id'] FROM initial
  UNION ALL
  SELECT child.value,parent.seen||(child.value->>'source_id') FROM closure parent
   JOIN public.knowledge_answer_reviews prior ON prior.subject_id::text=parent.value->>'source_id'
     AND prior.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid
     AND parent.value->>'source_type'='knowledge'
   CROSS JOIN LATERAL jsonb_array_elements(prior.source_proof) child(value)
   WHERE NOT (child.value->>'source_id'=ANY(parent.seen))
 ) SELECT NOT EXISTS(SELECT 1 FROM jsonb_array_elements(proof) p WHERE NOT EXISTS(
  SELECT 1 FROM closure c WHERE c.value->>'source_type'=p->>'source_type'
   AND c.value->>'source_id'=p->>'source_id'
   AND c.value->>'source_revision'=p->>'source_revision'
   AND c.value->>'content_hash'=p->>'content_hash'
   AND c.value->>'category_id'=p->>'category_id')) INTO valid;
 RETURN jsonb_typeof(proof)='array' AND coalesce(valid,false);
EXCEPTION WHEN data_exception THEN RETURN false;
END
"""

NATIVE_ORIGIN = r"""
DECLARE payload jsonb; review public.knowledge_answer_reviews; needs boolean;
BEGIN
 IF TG_TABLE_NAME='category_knowledge_entries' THEN
  needs=NEW.kind='verified_answer' AND NEW.action<>'withdraw';
 ELSE
  payload=NEW.command->'envelope'->'payload';
  needs=(payload->'answer_origin' IS NOT NULL AND payload->'answer_origin'<>'null'::jsonb)
   OR jsonb_array_length(NEW.sources)=0 OR jsonb_array_length(NEW.reads)=0;
  IF TG_TABLE_NAME='knowledge_rule_versions' THEN
   needs=needs OR EXISTS(SELECT 1 FROM public.knowledge_answer_reviews p
     WHERE p.tenant_id=NEW.tenant_id AND p.subject_id=NEW.candidate_version_id AND p.subject_kind='candidate');
  ELSE
   needs=needs OR EXISTS(SELECT 1 FROM public.knowledge_answer_reviews p
     WHERE p.tenant_id=NEW.tenant_id AND p.subject_id=NEW.previous_id AND p.subject_kind='candidate');
  END IF;
 END IF;
 IF needs THEN
  SELECT * INTO review FROM public.knowledge_answer_reviews r WHERE r.tenant_id=NEW.tenant_id
   AND r.subject_id=NEW.id AND r.subject_kind=CASE TG_TABLE_NAME
    WHEN 'category_knowledge_entries' THEN 'category' WHEN 'knowledge_candidate_versions' THEN 'candidate' ELSE 'rule' END;
  IF review.id IS NULL OR (TG_TABLE_NAME<>'category_knowledge_entries' AND payload->'answer_origin' IS NOT NULL AND payload->'answer_origin'<>'null'::jsonb AND (
   review.origin_run_id::text IS DISTINCT FROM payload->'answer_origin'->>'run_id'
   OR review.answer_digest IS DISTINCT FROM payload->'answer_origin'->>'answer_digest')) THEN
   RAISE EXCEPTION 'Answer-derived knowledge requires its exact real native provenance in this transaction' USING ERRCODE='23514'; END IF;
  IF TG_TABLE_NAME='category_knowledge_entries' AND review.origin_run_id IS NULL THEN
   RAISE EXCEPTION 'Verified answer must retain its actual answer origin' USING ERRCODE='23514'; END IF;
  IF TG_TABLE_NAME='category_knowledge_entries' AND jsonb_array_length(review.source_proof)=0
   AND NOT EXISTS(SELECT 1 FROM public.promotion_proofs p WHERE p.tenant_id=NEW.tenant_id
     AND p.knowledge_entry_id=NEW.id AND p.receipt_id=NEW.receipt_id) THEN
   RAISE EXCEPTION 'Shared answer requires fixed sources or the native deidentification proof' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NULL;
END
"""

RATE = r"""
DECLARE n bigint; missed bigint;
BEGIN
 IF t IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid
 OR c IS DISTINCT FROM nullif(current_setting('pdos.category_id',true),'')::uuid
 OR public.scope_actor() IS DISTINCT FROM public.scope_requester()
 OR NOT public.category_access(t,c,false)
 OR NOT EXISTS(SELECT 1 FROM public.categories x JOIN public.principals p ON p.tenant_id=x.tenant_id AND p.id=x.owner_id
 WHERE x.tenant_id=t AND x.id=c AND p.id=public.scope_requester() AND p.kind='human' AND p.active)
 OR extract(isodow FROM a AT TIME ZONE 'UTC')<>1
 OR (a AT TIME ZONE 'UTC')::time<>'00:00:00'::time OR z<>a+interval '7 days' THEN
 RAISE EXCEPTION 'Knowledge rates are fixed weekly category-owner aggregates' USING ERRCODE='42501'; END IF;
 SELECT count(*),count(*) FILTER(WHERE r.result#>>'{result,assistant,lookup}'='no_match') INTO n,missed
 FROM public.agent_runs r WHERE r.tenant_id=t AND r.category_id=c AND r.created_at>=a AND r.created_at<z
 AND r.state IN ('completed','partial') AND r.reverted_at IS NULL
 AND r.result#>>'{result,assistant,lookup}' IN ('no_match','uncited','cited')
 AND EXISTS(SELECT 1 FROM public.agent_tool_calls call WHERE call.tenant_id=t AND call.run_id=r.id
   AND call.tool='assistant.search' AND call.state='completed'
   AND call.execution_binding->>'read_kind'='ordinary/v1');
 RETURN QUERY SELECT CASE WHEN n>=5 THEN n ELSE NULL END,
 CASE WHEN n>=5 THEN missed ELSE NULL END,
 CASE WHEN n>=5 THEN missed::numeric/n ELSE NULL END,n<5;
END
"""


def upgrade_sql():
    from pdos_next.agent_kernel import models as _kernel_models  # noqa: F401

    from .models import KnowledgeCandidateVersion

    dialect = postgresql.dialect()
    statements = [
        "ALTER TABLE public.category_knowledge_entries ADD COLUMN answer_sources jsonb",
        "ALTER TABLE public.category_knowledge_entries ADD CONSTRAINT knowledge_answer_proof_shape CHECK (answer_sources IS NULL OR jsonb_typeof(answer_sources)='array')",
        "ALTER TABLE public.category_knowledge_entries ADD CONSTRAINT verified_answer_has_proof CHECK (kind<>'verified_answer' OR answer_sources IS NOT NULL)",
        r"""DO $$ DECLARE item record; BEGIN
 FOR item IN SELECT conname FROM pg_constraint WHERE conrelid='public.category_knowledge_entries'::regclass
 AND contype='c' AND pg_get_constraintdef(oid) LIKE '%research_question%' LOOP
 EXECUTE format('ALTER TABLE public.category_knowledge_entries DROP CONSTRAINT %I',item.conname); END LOOP;
 END $$""",
        "ALTER TABLE public.category_knowledge_entries ADD CONSTRAINT category_knowledge_kind CHECK (kind IN ('boundary','segment','competitor','voice','regulation','research_question','verified_answer'))",
    ]
    check = next(
        constraint
        for constraint in KnowledgeCandidateVersion.__table__.constraints
        if constraint.name == "knowledge_source_body_shape"
    )
    for native in ("knowledge_candidate_versions", "knowledge_rule_versions"):
        statements += [
            f"""DO $$ DECLARE item record; BEGIN
 FOR item IN SELECT conname FROM pg_constraint WHERE conrelid='public.{native}'::regclass
 AND contype='c' AND pg_get_constraintdef(oid) LIKE '%jsonb_typeof(command)%'
 AND pg_get_constraintdef(oid) LIKE '%jsonb_array_length%' LOOP
 EXECUTE format('ALTER TABLE public.{native} DROP CONSTRAINT %I',item.conname); END LOOP;
 END $$""",
            f"ALTER TABLE public.{native} ADD CONSTRAINT knowledge_source_body_shape CHECK ({check.sqltext})",
        ]
    from .assistant_acl import upgrade_sql as acl_upgrade

    statements.extend(acl_upgrade())
    for table in TABLES:
        statements.append(str(CreateTable(table).compile(dialect=dialect)))
        statements.extend(
            str(CreateIndex(index).compile(dialect=dialect)) for index in table.indexes
        )
        name = table.name
        ordinary = f"{HUMAN} AND public.category_access(tenant_id,category_id,false)"
        read = (
            (
                "tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND public.category_access(tenant_id,category_id,false)"
                if name == "knowledge_answer_reviews"
                else ordinary
            )
            + " AND "
            + (
                SUBJECT_READ
                if name == "knowledge_answer_reviews"
                else f"(owner_id=public.scope_requester() OR {MANAGER})"
                if name == "knowledge_gap_submissions"
                else MANAGER
            )
        )
        if name == "knowledge_gap_submissions":
            read += " AND (kind='missing_material' OR public.knowledge_answer_sources_visible(tenant_id,category_id,source_proof))"
        statements.extend(
            [
                f"ALTER TABLE public.{name} ENABLE ROW LEVEL SECURITY",
                f"ALTER TABLE public.{name} FORCE ROW LEVEL SECURITY",
                f"CREATE POLICY owner_internal ON public.{name} TO pdos_next_owner USING(true) WITH CHECK(true)",
                f"CREATE POLICY contribution_read ON public.{name} FOR SELECT TO pdos_next_app USING({read})",
                f"CREATE POLICY contribution_append ON public.{name} FOR INSERT TO pdos_next_app WITH CHECK({ordinary})",
                f"REVOKE ALL ON public.{name} FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch",
                f"GRANT SELECT,INSERT ON public.{name} TO pdos_next_app",
            ]
        )
    statements += [
        function(
            "knowledge_answer_sources_known", "origin_id uuid,proof jsonb", SOURCES_KNOWN, "boolean"
        ),
        "REVOKE ALL ON FUNCTION public.knowledge_answer_sources_known(uuid,jsonb) FROM PUBLIC,pdos_next_app,pdos_agent",
        function("assert_knowledge_assistant_fact", "", GUARD),
        function("require_knowledge_answer_origin", "", NATIVE_ORIGIN),
        "REVOKE ALL ON FUNCTION public.require_knowledge_answer_origin() FROM PUBLIC,pdos_next_app,pdos_agent",
    ]
    for native in (
        "category_knowledge_entries",
        "knowledge_candidate_versions",
        "knowledge_rule_versions",
    ):
        statements.append(
            f"CREATE CONSTRAINT TRIGGER knowledge_answer_origin AFTER INSERT ON public.{native} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_knowledge_answer_origin()"
        )
    for table in TABLES:
        statements += [
            f"CREATE CONSTRAINT TRIGGER knowledge_assistant_atom AFTER INSERT ON public.{table.name} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.assert_knowledge_assistant_fact()",
            f"CREATE TRIGGER knowledge_assistant_immutable BEFORE UPDATE OR DELETE ON public.{table.name} FOR EACH ROW EXECUTE FUNCTION public.assert_knowledge_assistant_fact()",
        ]
    statements += [
        function(
            "knowledge_weekly_lookup_stats",
            "t uuid,c uuid,a timestamptz,z timestamptz",
            RATE,
            "TABLE(total bigint,not_found bigint,rate numeric,suppressed boolean)",
        ),
        "REVOKE ALL ON FUNCTION public.knowledge_weekly_lookup_stats(uuid,uuid,timestamptz,timestamptz) FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch",
        "GRANT EXECUTE ON FUNCTION public.knowledge_weekly_lookup_stats(uuid,uuid,timestamptz,timestamptz) TO pdos_next_app",
        "REVOKE ALL ON FUNCTION public.assert_knowledge_assistant_fact() FROM PUBLIC,pdos_next_app,pdos_agent",
    ]
    return tuple(statements)


def downgrade_sql():
    old_shape = (
        "jsonb_typeof(command)='object' AND jsonb_typeof(body)='object' "
        "AND jsonb_typeof(source_basis)='object' AND jsonb_typeof(sources)='array' "
        "AND jsonb_typeof(reads)='array' AND jsonb_array_length(sources)>0 "
        "AND jsonb_array_length(reads)>0"
    )
    statements = [
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.knowledge_answer_reviews) OR EXISTS(SELECT 1 FROM public.knowledge_gap_submissions) OR EXISTS(SELECT 1 FROM public.knowledge_gap_attributions) OR EXISTS(SELECT 1 FROM public.category_knowledge_entries WHERE kind='verified_answer') THEN RAISE EXCEPTION 'Cannot discard recorded knowledge contributions'; END IF; END $$",
        "DROP FUNCTION public.knowledge_weekly_lookup_stats(uuid,uuid,timestamptz,timestamptz)",
    ]
    from .assistant_acl import downgrade_sql as acl_downgrade

    acl_statements = list(acl_downgrade())
    visible_function = acl_statements.pop()
    statements.extend(acl_statements)
    for native in (
        "category_knowledge_entries",
        "knowledge_candidate_versions",
        "knowledge_rule_versions",
    ):
        statements.append(f"DROP TRIGGER knowledge_answer_origin ON public.{native}")
    statements += [
        "DROP FUNCTION public.require_knowledge_answer_origin()",
        *(f"DROP TABLE public.{table.name}" for table in reversed(TABLES)),
        visible_function,
        "DROP FUNCTION public.assert_knowledge_assistant_fact()",
        "DROP FUNCTION public.knowledge_answer_sources_known(uuid,jsonb)",
        "ALTER TABLE public.category_knowledge_entries DROP CONSTRAINT category_knowledge_kind",
        "ALTER TABLE public.category_knowledge_entries ADD CONSTRAINT category_knowledge_kind CHECK (kind IN ('boundary','segment','competitor','voice','regulation','research_question'))",
    ]
    for native in ("knowledge_candidate_versions", "knowledge_rule_versions"):
        statements += [
            f"ALTER TABLE public.{native} DROP CONSTRAINT knowledge_source_body_shape",
            f"ALTER TABLE public.{native} ADD CONSTRAINT knowledge_source_body_shape CHECK ({old_shape})",
        ]
    statements += ["ALTER TABLE public.category_knowledge_entries DROP COLUMN answer_sources"]
    return tuple(statements)
