CREATE OR REPLACE FUNCTION public.require_quality_followup_atom()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE prior quality_issue_versions%ROWTYPE; c confirmations%ROWTYPE; r action_receipts%ROWTYPE;
  normalized jsonb; old_action jsonb; new_action jsonb; supplied jsonb; observation jsonb; assessment jsonb;
  submitted integer; actual_changed integer := 0; final_status text; basis jsonb;
BEGIN
  IF NEW.operation NOT IN ('quality.issue.root_cause.decide','quality.capa.actions.complete') THEN RETURN NULL; END IF;
  SELECT * INTO prior FROM quality_issue_versions WHERE tenant_id=NEW.tenant_id
    AND id=NEW.previous_issue_version_id;
  IF prior.id IS NULL OR NEW.previous_revision IS DISTINCT FROM prior.revision
    OR NEW.revision IS DISTINCT FROM prior.revision+1 OR prior.status<>'actioning'
    OR ROW(prior.product_id,prior.project_id,prior.issue_id,prior.owner_id,prior.visibility,prior.purpose)
      IS DISTINCT FROM ROW(NEW.product_id,NEW.project_id,NEW.issue_id,NEW.owner_id,NEW.visibility,NEW.purpose)
    OR NOT COALESCE(jsonb_typeof(NEW.required_source_read_set)='array'
      AND jsonb_array_length(NEW.required_source_read_set) BETWEEN 1 AND 20
      AND NEW.required_source_read_set @> prior.required_source_read_set
      AND NEW.required_source_read_set @> (NEW.authority_snapshot->'required_source_read_set')
      AND NEW.required_source_read_set @> (NEW.policy_snapshot->'required_source_read_set')
      AND jsonb_typeof(NEW.source_basis->'artifact_sources')='array',false)
    OR NOT COALESCE(NEW.input_snapshot->>'issue_id'=NEW.issue_id::text
      AND (NEW.input_snapshot->>'expected_issue_revision')::integer=prior.revision,false)
    OR NEW.input_snapshot ? 'approval_token' OR NEW.input_snapshot ? 'confirmation_token'
    OR NOT EXISTS (SELECT 1 FROM quality_current_issues WHERE tenant_id=NEW.tenant_id
      AND product_id=NEW.product_id AND project_id=NEW.project_id AND issue_id=NEW.issue_id
      AND issue_version_id=NEW.id AND issue_revision=NEW.revision) THEN
    RAISE EXCEPTION 'Followup must append the exact current actioning Issue predecessor'; END IF;
  c := assert_quality_followup_proof(NEW.tenant_id,NEW.product_id,NEW.writer_id,NEW.operation,
    NEW.source_basis->'shared_proof',NEW.created_at);
  r := assert_quality_followup_receipt(NEW.tenant_id,NEW.product_id,NEW.id,NEW.revision,
    NEW.operation,'quality_issue',NEW.writer_id,NEW.visibility,NEW.status);
  IF NOT COALESCE(NEW.authority_snapshot->>'subject_id'=NEW.writer_id::text
    AND NEW.authority_snapshot->>'operation'=NEW.operation
    AND NEW.authority_snapshot->>'purpose'=NEW.purpose
    AND NEW.authority_snapshot->'scope'->>'tenant_id'=NEW.tenant_id::text
    AND NEW.authority_snapshot->'scope'->>'product_id'=NEW.product_id::text
    AND NEW.authority_snapshot->'scope'->>'project_id'=NEW.project_id::text
    AND NEW.authority_snapshot->'authorized'='true'::jsonb
    AND NEW.authority_snapshot->'qualified'='true'::jsonb
    AND (NEW.authority_snapshot->>'valid_until')::timestamptz>NEW.created_at
    AND (NEW.policy_snapshot->>'valid_until')::timestamptz>NEW.created_at,false)
    OR NOT COALESCE(jsonb_typeof(prior.issue_snapshot->'history')='array'
      AND jsonb_typeof(NEW.issue_snapshot->'history')='array'
      AND jsonb_array_length(NEW.issue_snapshot->'history')=jsonb_array_length(prior.issue_snapshot->'history')+1,false)
    OR (NEW.issue_snapshot->'history' - (jsonb_array_length(NEW.issue_snapshot->'history')-1))
      IS DISTINCT FROM prior.issue_snapshot->'history'
    OR NOT COALESCE(NEW.issue_snapshot->'history'->-1->>'command_id'=r.command_id::text
      AND NEW.issue_snapshot->'history'->-1->>'operation'=NEW.operation
      AND NEW.issue_snapshot->'history'->-1->>'actor_id'=NEW.writer_id::text
      AND NEW.issue_snapshot->'history'->-1->>'actor_kind'='human'
      AND (NEW.issue_snapshot->'history'->-1->>'at')::timestamptz<=NEW.created_at,false)
    OR (EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.source_basis->'artifact_sources') x
      WHERE x->>'visibility'='private') AND NEW.visibility<>'private') THEN
    RAISE EXCEPTION 'Followup must retain old history and one exact named command history'; END IF;
  normalized := jsonb_set(NEW.issue_snapshot,
    ARRAY['history',(jsonb_array_length(NEW.issue_snapshot->'history')-1)::text,'at'],'null'::jsonb,false);
  IF NEW.operation='quality.issue.root_cause.decide' THEN
    IF prior.issue_snapshot->'root_cause' IS DISTINCT FROM 'null'::jsonb
      OR NEW.status<>'actioning'
      OR (NEW.issue_snapshot-ARRAY['revision','history','root_cause'])
        IS DISTINCT FROM (prior.issue_snapshot-ARRAY['revision','history','root_cause'])
      OR NOT COALESCE(NEW.issue_snapshot->'root_cause'->>'actor_id'=NEW.writer_id::text
        AND NEW.issue_snapshot->'root_cause'->>'text'=NEW.input_snapshot->>'text'
        AND NEW.issue_snapshot->'root_cause'->'sources'=NEW.input_snapshot->'sources'
        AND jsonb_typeof(NEW.issue_snapshot->'root_cause'->'at')='string'
        AND (NEW.issue_snapshot->'root_cause'->>'at')::timestamptz<=NEW.created_at,false) THEN
      RAISE EXCEPTION 'Root cause adds one named conclusion and never changes earlier CAPA or failures'; END IF;
    normalized := jsonb_set(normalized,ARRAY['root_cause','at'],'null'::jsonb,false);
  ELSE
    IF jsonb_typeof(prior.issue_snapshot->'capa') IS DISTINCT FROM 'object'
      OR (NEW.issue_snapshot-ARRAY['revision','history','capa','status'])
        IS DISTINCT FROM (prior.issue_snapshot-ARRAY['revision','history','capa','status'])
      OR (NEW.issue_snapshot->'capa'-'actions') IS DISTINCT FROM (prior.issue_snapshot->'capa'-'actions')
      OR jsonb_typeof(NEW.input_snapshot->'completions') IS DISTINCT FROM 'array'
      OR COALESCE(jsonb_array_length(NEW.input_snapshot->'completions'),0) NOT BETWEEN 1 AND 1000
      OR jsonb_typeof(NEW.issue_snapshot->'capa'->'actions') IS DISTINCT FROM 'array'
      OR jsonb_array_length(NEW.issue_snapshot->'capa'->'actions')
        IS DISTINCT FROM jsonb_array_length(prior.issue_snapshot->'capa'->'actions') THEN
      RAISE EXCEPTION 'Completion only appends actual completions to the original CAPA actions'; END IF;
    submitted := jsonb_array_length(NEW.input_snapshot->'completions');
    IF (SELECT count(DISTINCT x->>'id') FROM jsonb_array_elements(NEW.input_snapshot->'completions') x)<>submitted
      OR NOT COALESCE(jsonb_typeof(NEW.source_basis->'completion_observations')='array'
        AND jsonb_array_length(NEW.source_basis->'completion_observations')=submitted
        AND jsonb_typeof(NEW.source_basis->'completion_assessments')='array'
        AND jsonb_array_length(NEW.source_basis->'completion_assessments')=submitted,false)
      OR (SELECT count(DISTINCT x->'fact'->>'action_id')
        FROM jsonb_array_elements(NEW.source_basis->'completion_observations') x)<>submitted
      OR (SELECT count(DISTINCT x->>'action_id')
        FROM jsonb_array_elements(NEW.source_basis->'completion_assessments') x)<>submitted THEN
      RAISE EXCEPTION 'Every completion must have one unique actual fact and host assessment'; END IF;
    FOR old_action,new_action IN SELECT o.value,n.value FROM
      jsonb_array_elements(prior.issue_snapshot->'capa'->'actions') WITH ORDINALITY o(value,ord)
      JOIN jsonb_array_elements(NEW.issue_snapshot->'capa'->'actions') WITH ORDINALITY n(value,ord) USING (ord)
    LOOP
      IF (old_action-'completion') IS DISTINCT FROM (new_action-'completion') THEN
        RAISE EXCEPTION 'Completion cannot change action identity, executor, text or ordering'; END IF;
      SELECT x INTO supplied FROM jsonb_array_elements(NEW.input_snapshot->'completions') x
        WHERE x->>'id'=old_action->>'id';
      IF supplied IS NULL THEN
        IF old_action->'completion' IS DISTINCT FROM new_action->'completion' THEN
          RAISE EXCEPTION 'Unselected original action completion cannot change'; END IF;
      ELSE
        actual_changed := actual_changed+1;
        IF old_action->'completion' IS DISTINCT FROM 'null'::jsonb
          OR new_action->'completion' IS DISTINCT FROM supplied
          OR supplied->>'executor_id' IS DISTINCT FROM NEW.writer_id::text
          OR old_action->>'executor_id' IS DISTINCT FROM NEW.writer_id::text
          OR NOT COALESCE(jsonb_typeof(supplied->'evidence')='array'
            AND jsonb_array_length(supplied->'evidence') BETWEEN 1 AND 20
            AND (supplied->'evidence') @> jsonb_build_array(supplied->'at'->'source'),false)
          OR (supplied->'at'->>'occurred_at')::timestamptz>NEW.created_at THEN
          RAISE EXCEPTION 'Completion requires original executor, exact event evidence and an already observed clock'; END IF;
        SELECT x INTO observation FROM jsonb_array_elements(NEW.source_basis->'completion_observations') x
          WHERE x->'fact'->>'action_id'=old_action->>'id';
        IF NOT COALESCE(observation->'fact'->>'issue_id'=NEW.issue_id::text
          AND observation->'fact'->>'capa_id'=NEW.issue_snapshot->'capa'->>'id'
          AND observation->'fact'->>'executor_id'=NEW.writer_id::text
          AND observation->'fact'->>'operation'=NEW.operation
          AND observation->'fact'->>'purpose'=NEW.purpose
          AND observation->'fact'->>'text'=supplied->>'text'
          AND observation->'fact'->>'original_timezone'=supplied->'at'->>'original_timezone'
          AND (observation->'fact'->>'occurred_at')::timestamptz=(supplied->'at'->>'occurred_at')::timestamptz
          AND jsonb_typeof(observation->'received_at')='string'
          AND (observation->>'received_at')::timestamptz<=NEW.created_at
          AND (observation->>'received_at')::timestamptz>=(supplied->'at'->>'occurred_at')::timestamptz,false) THEN
          RAISE EXCEPTION 'Saved completion must bind the exact separately received structured fact'; END IF;
        SELECT x INTO assessment FROM jsonb_array_elements(NEW.source_basis->'completion_assessments') x
          WHERE x->>'action_id'=old_action->>'id';
        IF NOT COALESCE(assessment->>'issue_id'=NEW.issue_id::text
          AND assessment->>'capa_id'=NEW.issue_snapshot->'capa'->>'id'
          AND assessment->>'executor_id'=NEW.writer_id::text
          AND assessment->>'purpose'=NEW.purpose
          AND assessment->'scope'->>'tenant_id'=NEW.tenant_id::text
          AND assessment->'scope'->>'product_id'=NEW.product_id::text
          AND assessment->'scope'->>'project_id'=NEW.project_id::text
          AND assessment->>'basis_sha256'=NEW.source_basis->'followup_basis'->>'basis_sha256'
          AND assessment->>'nature'=NEW.source_basis->'followup_basis'->>'nature'
          AND assessment->'event_source'=supplied->'at'->'source'
          AND assessment->'allowed'='true'::jsonb AND assessment->'current'='true'::jsonb
          AND assessment->>'classification' IN ('investigation','formal_change')
          AND (assessment->>'valid_until')::timestamptz>NEW.created_at
          AND NEW.required_source_read_set @> (assessment->'required_source_read_set')
          AND (assessment->>'classification'<>'formal_change'
            OR (jsonb_typeof(assessment->'owner_proofs')='array'
              AND jsonb_array_length(assessment->'owner_proofs')>0)),false) THEN
          RAISE EXCEPTION 'Completion must retain its exact positive host binding and formal owner proof shape'; END IF;
      END IF;
    END LOOP;
    IF actual_changed<>submitted THEN RAISE EXCEPTION 'Every submitted completion must belong to an original action'; END IF;
    final_status := CASE WHEN EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.issue_snapshot->'capa'->'actions') x
      WHERE x->'completion'='null'::jsonb) THEN 'actioning' ELSE 'awaiting_verification' END;
    IF NEW.status<>final_status THEN RAISE EXCEPTION 'Complete CAPA changes to awaiting verification only, never effectiveness or closed'; END IF;
    IF c.snapshot->'completion_assessments' IS DISTINCT FROM NEW.source_basis->'completion_assessments'
      OR c.snapshot->'completion_observations' IS DISTINCT FROM (SELECT jsonb_agg(x->'fact' ORDER BY ord)
        FROM jsonb_array_elements(NEW.source_basis->'completion_observations') WITH ORDINALITY v(x,ord)) THEN
      RAISE EXCEPTION 'Completion actual facts and host assessments must match the consumed review'; END IF;
  END IF;
  basis := NEW.source_basis-'shared_proof'-'completion_observations';
  IF c.snapshot->'before'->(NEW.issue_id::text) IS DISTINCT FROM prior.issue_snapshot
    OR c.snapshot->'after'->(NEW.issue_id::text) IS DISTINCT FROM normalized
    OR c.snapshot->'read_basis'->'authority' IS DISTINCT FROM NEW.authority_snapshot
    OR c.snapshot->'read_basis'->'policy' IS DISTINCT FROM NEW.policy_snapshot
    OR c.snapshot->'read_basis'->'source_basis' IS DISTINCT FROM basis
    OR c.snapshot->'read_basis'->'read_set' IS DISTINCT FROM NEW.required_source_read_set
    OR c.snapshot->>'event_effect' IS DISTINCT FROM (CASE NEW.operation
      WHEN 'quality.issue.root_cause.decide' THEN 'issue.root_cause_decided' ELSE 'capa.actions_completed' END)
    OR c.snapshot->>'clock_basis' IS DISTINCT FROM 'server_on_save' THEN
    RAISE EXCEPTION 'Issue successor, exact evidence and consumed material review must match'; END IF;
  RETURN NULL;
END $function$
