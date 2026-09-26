"""Allow Project Intelligence to read bounded Issue evidence through get_issue_evidence.

N7-02 real-model evaluation showed the Project Agent could not see the triggering Issue's
title or description. The read runs through cehub_ai.agent_issue_evidence_projection
(infra/postgres/security/agent-runtime.sql); this revision only adds the tool to the two
receipt whitelists, redefined from their latest bodies (0076/0077, identical to the
security script copies).
"""

# ruff: noqa: E501
from alembic import op

revision = "0377_issue_evidence_tool"
down_revision = "0376_readable_audit_reports"
branch_labels = None
depends_on = None

APPEND_OBSERVATION = r"""CREATE OR REPLACE FUNCTION cehub_ai.append_agent_tool_observation(
 wanted_key varchar,wanted_tool varchar,input_text text,output_text text,metadata_text text
) RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; old cehub_ai.agent_tool_observations%ROWTYPE;
 args jsonb; result jsonb; meta jsonb; observation_id uuid:=gen_random_uuid();
 next_sequence integer;
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid FOR UPDATE;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent observation lease is invalid' USING ERRCODE='42501';
 END IF;
 IF wanted_key IS NULL OR length(wanted_key) NOT BETWEEN 1 AND 128
  OR input_text IS NULL OR output_text IS NULL OR metadata_text IS NULL
  OR octet_length(input_text)+octet_length(output_text)+octet_length(metadata_text)>262144 THEN
  RAISE EXCEPTION 'AGENT_OBSERVATION_INVALID' USING ERRCODE='22023';
 END IF;
 IF (wanted_tool IN ('get_project_context','get_recent_events','search_memory') OR
  wanted_tool='get_issue_evidence' AND r.agent_key='project_intelligence' OR
  wanted_tool='get_engineering_evidence' AND r.agent_key='engineering_intelligence' OR
  wanted_tool='get_quality_evidence' AND r.agent_key='quality_intelligence' OR
  wanted_tool='get_supplier_delay_evidence' AND r.agent_key='supplier_intelligence' OR
  wanted_tool='get_portfolio_brief' AND r.agent_key='executive_intelligence') IS NOT TRUE THEN
  RAISE EXCEPTION 'AGENT_OBSERVATION_TOOL_INVALID' USING ERRCODE='22023';
 END IF;
 args:=input_text::jsonb; result:=output_text::jsonb; meta:=metadata_text::jsonb;
 IF jsonb_typeof(args) IS DISTINCT FROM 'object' OR jsonb_typeof(result) IS DISTINCT FROM 'object'
  OR jsonb_typeof(meta) IS DISTINCT FROM 'object'
  OR args->>'project_id' IS DISTINCT FROM r.project_id::text
  OR meta->>'tenant_id' IS DISTINCT FROM r.tenant_id::text
  OR meta->>'run_id' IS DISTINCT FROM r.id::text
  OR jsonb_typeof(meta->'sources') IS DISTINCT FROM 'array'
  OR (meta->>'status' IN ('completed','partial','unavailable','failed','cancelled')) IS NOT TRUE
  OR meta->>'input_digest' !~ '^[a-f0-9]{64}$' OR meta->>'input_digest' IS NULL
  OR meta->>'output_digest' !~ '^[a-f0-9]{64}$' OR meta->>'output_digest' IS NULL THEN
  RAISE EXCEPTION 'AGENT_OBSERVATION_INVALID' USING ERRCODE='22023';
 END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(meta->'sources') s
   WHERE s->>'tenant_id' IS DISTINCT FROM r.tenant_id::text) THEN
  RAISE EXCEPTION 'AGENT_OBSERVATION_SOURCE_SCOPE' USING ERRCODE='22023';
 END IF;
 meta:=meta || jsonb_build_object(
  'input_digest',encode(sha256(convert_to(args::text,'UTF8')),'hex'),
  'output_digest',encode(sha256(convert_to(result::text,'UTF8')),'hex'));
 SELECT * INTO old FROM cehub_ai.agent_tool_observations
  WHERE tenant_id=r.tenant_id AND run_id=r.id AND call_key=wanted_key;
 IF FOUND THEN
  IF old.tool_key IS DISTINCT FROM wanted_tool OR old.input_body IS DISTINCT FROM args
   OR old.output_body IS DISTINCT FROM result OR
   (old.metadata - 'id' - 'sequence' - 'observed_at' - 'as_of' - 'sources') IS DISTINCT FROM
   (meta - 'id' - 'sequence' - 'observed_at' - 'as_of' - 'sources') OR
   (SELECT jsonb_agg(s - 'as_of') FROM jsonb_array_elements(old.metadata->'sources') s)
   IS DISTINCT FROM
   (SELECT jsonb_agg(s - 'as_of') FROM jsonb_array_elements(meta->'sources') s) THEN
   RAISE EXCEPTION 'AGENT_OBSERVATION_CONFLICT' USING ERRCODE='22023';
  END IF;
  RETURN old.metadata;
 END IF;
 SELECT coalesce(max(sequence),0)+1 INTO next_sequence FROM cehub_ai.agent_tool_observations
  WHERE tenant_id=r.tenant_id AND run_id=r.id;
 meta:=meta || jsonb_build_object('id',observation_id,'sequence',next_sequence,
                                 'observed_at',clock_timestamp());
 IF NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent observation lease expired' USING ERRCODE='42501';
 END IF;
 INSERT INTO cehub_ai.agent_tool_observations VALUES(observation_id,r.tenant_id,r.id,
  next_sequence,wanted_key,wanted_tool,args,result,meta,clock_timestamp());
 RETURN meta;
END $body$;"""

PREPARE_TOOL_CALL = r"""CREATE OR REPLACE FUNCTION cehub_ai.prepare_agent_tool_call(
 wanted_call uuid,wanted_key varchar,wanted_tool varchar,input_text text
) RETURNS uuid LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; old cehub_ai.agent_tool_intents%ROWTYPE;
 lineage cehub_ai.budget_lineages%ROWTYPE; args jsonb; used bigint; allowance bigint;
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent tool lease is invalid' USING ERRCODE='42501';
 END IF;
 -- Same order as model admission: tenant budget lock, then the run row.
 PERFORM pg_advisory_xact_lock(hashtextextended('pdos-budget:' || r.tenant_id::text,0));
 PERFORM 1 FROM cehub_ai.agent_runs WHERE id=r.id FOR UPDATE;
 IF NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent tool lease expired' USING ERRCODE='42501';
 END IF;
 IF wanted_call IS NULL OR wanted_key IS NULL OR length(wanted_key) NOT BETWEEN 1 AND 128
  OR btrim(wanted_key)='' OR input_text IS NULL OR octet_length(input_text)>65536 THEN
  RAISE EXCEPTION 'AGENT_TOOL_INTENT_INVALID' USING ERRCODE='22023';
 END IF;
 IF (wanted_tool IN ('get_project_context','get_recent_events','search_memory') OR
  wanted_tool='get_issue_evidence' AND r.agent_key='project_intelligence' OR
  wanted_tool='get_engineering_evidence' AND r.agent_key='engineering_intelligence' OR
  wanted_tool='get_quality_evidence' AND r.agent_key='quality_intelligence' OR
  wanted_tool='get_supplier_delay_evidence' AND r.agent_key='supplier_intelligence' OR
  wanted_tool='get_portfolio_brief' AND r.agent_key='executive_intelligence') IS NOT TRUE THEN
  RAISE EXCEPTION 'AGENT_TOOL_INTENT_TOOL_INVALID' USING ERRCODE='22023';
 END IF;
 args:=input_text::jsonb;
 IF jsonb_typeof(args) IS DISTINCT FROM 'object'
   OR args->>'project_id' IS DISTINCT FROM r.project_id::text THEN
  RAISE EXCEPTION 'AGENT_TOOL_INTENT_SCOPE' USING ERRCODE='22023';
 END IF;
 SELECT * INTO old FROM cehub_ai.agent_tool_intents
  WHERE tenant_id=r.tenant_id AND run_id=r.id AND call_key=wanted_key;
 IF FOUND THEN
  IF old.id IS DISTINCT FROM wanted_call OR old.tool_key IS DISTINCT FROM wanted_tool
    OR old.input_body IS DISTINCT FROM args THEN
   RAISE EXCEPTION 'AGENT_TOOL_INTENT_CONFLICT' USING ERRCODE='22023';
  END IF;
  RETURN old.id;
 END IF;
 IF EXISTS(SELECT 1 FROM cehub_ai.agent_tool_observations
    WHERE tenant_id=r.tenant_id AND run_id=r.id AND call_key=wanted_key) THEN
  RAISE EXCEPTION 'AGENT_TOOL_HISTORICAL_CALL' USING ERRCODE='22023';
 END IF;
 SELECT l.* INTO lineage FROM cehub_ai.budget_lineages l
  JOIN cehub_ai.budget_run_links b ON b.tenant_id=l.tenant_id AND b.lineage_id=l.id
  WHERE b.tenant_id=r.tenant_id AND b.run_id=r.id;
 IF lineage.id IS NOT NULL THEN
  PERFORM cehub_ai.check_run_active_budget(r.tenant_id,r.id);
  allowance:=(lineage.profile->>'tool_call_limit')::bigint;
  IF allowance IS NULL OR allowance<1 THEN
   RAISE EXCEPTION 'BUDGET_TOOL_PROFILE_INVALID' USING ERRCODE='22023';
  END IF;
  SELECT count(*) INTO used FROM (
   SELECT DISTINCT ON(attempt_id) reservation_status FROM cehub_ai.budget_journal
    WHERE tenant_id=r.tenant_id AND lineage_id=lineage.id AND call_kind='tool'
    ORDER BY attempt_id,revision DESC) latest WHERE reservation_status<>'cancelled_before_dispatch';
  used:=used+cehub_ai.tool_intent_call_count(r.tenant_id,lineage.id);
  IF used>=allowance THEN
   RAISE EXCEPTION 'BUDGET_TOOL_CALL_COUNT_EXHAUSTED' USING ERRCODE='22023';
  END IF;
 END IF;
 IF NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent tool lease expired' USING ERRCODE='42501';
 END IF;
 INSERT INTO cehub_ai.agent_tool_intents VALUES(wanted_call,r.tenant_id,r.id,lineage.id,
   wanted_key,wanted_tool,args,clock_timestamp());
 RETURN wanted_call;
END $body$;"""

OLD_APPEND_OBSERVATION = r"""CREATE OR REPLACE FUNCTION cehub_ai.append_agent_tool_observation(
 wanted_key varchar,wanted_tool varchar,input_text text,output_text text,metadata_text text
) RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; old cehub_ai.agent_tool_observations%ROWTYPE;
 args jsonb; result jsonb; meta jsonb; observation_id uuid:=gen_random_uuid();
 next_sequence integer;
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid FOR UPDATE;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent observation lease is invalid' USING ERRCODE='42501';
 END IF;
 IF wanted_key IS NULL OR length(wanted_key) NOT BETWEEN 1 AND 128
  OR input_text IS NULL OR output_text IS NULL OR metadata_text IS NULL
  OR octet_length(input_text)+octet_length(output_text)+octet_length(metadata_text)>262144 THEN
  RAISE EXCEPTION 'AGENT_OBSERVATION_INVALID' USING ERRCODE='22023';
 END IF;
 IF (wanted_tool IN ('get_project_context','get_recent_events','search_memory') OR
  wanted_tool='get_engineering_evidence' AND r.agent_key='engineering_intelligence' OR
  wanted_tool='get_quality_evidence' AND r.agent_key='quality_intelligence' OR
  wanted_tool='get_supplier_delay_evidence' AND r.agent_key='supplier_intelligence' OR
  wanted_tool='get_portfolio_brief' AND r.agent_key='executive_intelligence') IS NOT TRUE THEN
  RAISE EXCEPTION 'AGENT_OBSERVATION_TOOL_INVALID' USING ERRCODE='22023';
 END IF;
 args:=input_text::jsonb; result:=output_text::jsonb; meta:=metadata_text::jsonb;
 IF jsonb_typeof(args) IS DISTINCT FROM 'object' OR jsonb_typeof(result) IS DISTINCT FROM 'object'
  OR jsonb_typeof(meta) IS DISTINCT FROM 'object'
  OR args->>'project_id' IS DISTINCT FROM r.project_id::text
  OR meta->>'tenant_id' IS DISTINCT FROM r.tenant_id::text
  OR meta->>'run_id' IS DISTINCT FROM r.id::text
  OR jsonb_typeof(meta->'sources') IS DISTINCT FROM 'array'
  OR (meta->>'status' IN ('completed','partial','unavailable','failed','cancelled')) IS NOT TRUE
  OR meta->>'input_digest' !~ '^[a-f0-9]{64}$' OR meta->>'input_digest' IS NULL
  OR meta->>'output_digest' !~ '^[a-f0-9]{64}$' OR meta->>'output_digest' IS NULL THEN
  RAISE EXCEPTION 'AGENT_OBSERVATION_INVALID' USING ERRCODE='22023';
 END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(meta->'sources') s
   WHERE s->>'tenant_id' IS DISTINCT FROM r.tenant_id::text) THEN
  RAISE EXCEPTION 'AGENT_OBSERVATION_SOURCE_SCOPE' USING ERRCODE='22023';
 END IF;
 meta:=meta || jsonb_build_object(
  'input_digest',encode(sha256(convert_to(args::text,'UTF8')),'hex'),
  'output_digest',encode(sha256(convert_to(result::text,'UTF8')),'hex'));
 SELECT * INTO old FROM cehub_ai.agent_tool_observations
  WHERE tenant_id=r.tenant_id AND run_id=r.id AND call_key=wanted_key;
 IF FOUND THEN
  IF old.tool_key IS DISTINCT FROM wanted_tool OR old.input_body IS DISTINCT FROM args
   OR old.output_body IS DISTINCT FROM result OR
   (old.metadata - 'id' - 'sequence' - 'observed_at' - 'as_of' - 'sources') IS DISTINCT FROM
   (meta - 'id' - 'sequence' - 'observed_at' - 'as_of' - 'sources') OR
   (SELECT jsonb_agg(s - 'as_of') FROM jsonb_array_elements(old.metadata->'sources') s)
   IS DISTINCT FROM
   (SELECT jsonb_agg(s - 'as_of') FROM jsonb_array_elements(meta->'sources') s) THEN
   RAISE EXCEPTION 'AGENT_OBSERVATION_CONFLICT' USING ERRCODE='22023';
  END IF;
  RETURN old.metadata;
 END IF;
 SELECT coalesce(max(sequence),0)+1 INTO next_sequence FROM cehub_ai.agent_tool_observations
  WHERE tenant_id=r.tenant_id AND run_id=r.id;
 meta:=meta || jsonb_build_object('id',observation_id,'sequence',next_sequence,
                                 'observed_at',clock_timestamp());
 IF NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent observation lease expired' USING ERRCODE='42501';
 END IF;
 INSERT INTO cehub_ai.agent_tool_observations VALUES(observation_id,r.tenant_id,r.id,
  next_sequence,wanted_key,wanted_tool,args,result,meta,clock_timestamp());
 RETURN meta;
END $body$;"""

OLD_PREPARE_TOOL_CALL = r"""CREATE OR REPLACE FUNCTION cehub_ai.prepare_agent_tool_call(
 wanted_call uuid,wanted_key varchar,wanted_tool varchar,input_text text
) RETURNS uuid LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE; old cehub_ai.agent_tool_intents%ROWTYPE;
 lineage cehub_ai.budget_lineages%ROWTYPE; args jsonb; used bigint; allowance bigint;
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent tool lease is invalid' USING ERRCODE='42501';
 END IF;
 -- Same order as model admission: tenant budget lock, then the run row.
 PERFORM pg_advisory_xact_lock(hashtextextended('pdos-budget:' || r.tenant_id::text,0));
 PERFORM 1 FROM cehub_ai.agent_runs WHERE id=r.id FOR UPDATE;
 IF NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent tool lease expired' USING ERRCODE='42501';
 END IF;
 IF wanted_call IS NULL OR wanted_key IS NULL OR length(wanted_key) NOT BETWEEN 1 AND 128
  OR btrim(wanted_key)='' OR input_text IS NULL OR octet_length(input_text)>65536 THEN
  RAISE EXCEPTION 'AGENT_TOOL_INTENT_INVALID' USING ERRCODE='22023';
 END IF;
 IF (wanted_tool IN ('get_project_context','get_recent_events','search_memory') OR
  wanted_tool='get_engineering_evidence' AND r.agent_key='engineering_intelligence' OR
  wanted_tool='get_quality_evidence' AND r.agent_key='quality_intelligence' OR
  wanted_tool='get_supplier_delay_evidence' AND r.agent_key='supplier_intelligence' OR
  wanted_tool='get_portfolio_brief' AND r.agent_key='executive_intelligence') IS NOT TRUE THEN
  RAISE EXCEPTION 'AGENT_TOOL_INTENT_TOOL_INVALID' USING ERRCODE='22023';
 END IF;
 args:=input_text::jsonb;
 IF jsonb_typeof(args) IS DISTINCT FROM 'object'
   OR args->>'project_id' IS DISTINCT FROM r.project_id::text THEN
  RAISE EXCEPTION 'AGENT_TOOL_INTENT_SCOPE' USING ERRCODE='22023';
 END IF;
 SELECT * INTO old FROM cehub_ai.agent_tool_intents
  WHERE tenant_id=r.tenant_id AND run_id=r.id AND call_key=wanted_key;
 IF FOUND THEN
  IF old.id IS DISTINCT FROM wanted_call OR old.tool_key IS DISTINCT FROM wanted_tool
    OR old.input_body IS DISTINCT FROM args THEN
   RAISE EXCEPTION 'AGENT_TOOL_INTENT_CONFLICT' USING ERRCODE='22023';
  END IF;
  RETURN old.id;
 END IF;
 IF EXISTS(SELECT 1 FROM cehub_ai.agent_tool_observations
    WHERE tenant_id=r.tenant_id AND run_id=r.id AND call_key=wanted_key) THEN
  RAISE EXCEPTION 'AGENT_TOOL_HISTORICAL_CALL' USING ERRCODE='22023';
 END IF;
 SELECT l.* INTO lineage FROM cehub_ai.budget_lineages l
  JOIN cehub_ai.budget_run_links b ON b.tenant_id=l.tenant_id AND b.lineage_id=l.id
  WHERE b.tenant_id=r.tenant_id AND b.run_id=r.id;
 IF lineage.id IS NOT NULL THEN
  PERFORM cehub_ai.check_run_active_budget(r.tenant_id,r.id);
  allowance:=(lineage.profile->>'tool_call_limit')::bigint;
  IF allowance IS NULL OR allowance<1 THEN
   RAISE EXCEPTION 'BUDGET_TOOL_PROFILE_INVALID' USING ERRCODE='22023';
  END IF;
  SELECT count(*) INTO used FROM (
   SELECT DISTINCT ON(attempt_id) reservation_status FROM cehub_ai.budget_journal
    WHERE tenant_id=r.tenant_id AND lineage_id=lineage.id AND call_kind='tool'
    ORDER BY attempt_id,revision DESC) latest WHERE reservation_status<>'cancelled_before_dispatch';
  used:=used+cehub_ai.tool_intent_call_count(r.tenant_id,lineage.id);
  IF used>=allowance THEN
   RAISE EXCEPTION 'BUDGET_TOOL_CALL_COUNT_EXHAUSTED' USING ERRCODE='22023';
  END IF;
 END IF;
 IF NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent tool lease expired' USING ERRCODE='42501';
 END IF;
 INSERT INTO cehub_ai.agent_tool_intents VALUES(wanted_call,r.tenant_id,r.id,lineage.id,
   wanted_key,wanted_tool,args,clock_timestamp());
 RETURN wanted_call;
END $body$;"""


def upgrade() -> None:
    op.execute(APPEND_OBSERVATION)
    op.execute(PREPARE_TOOL_CALL)


def downgrade() -> None:
    op.execute(OLD_PREPARE_TOOL_CALL)
    op.execute(OLD_APPEND_OBSERVATION)
