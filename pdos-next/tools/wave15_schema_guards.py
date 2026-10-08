"""Offline Wave15 SQL draft; importing this file does not open a database."""
# ruff: noqa: E501

FUNCTIONS = {
    "assert_quality_change_receipt": r"""
CREATE FUNCTION assert_quality_change_receipt(tid uuid, pid uuid, sid uuid, rev integer,
  op_name text, subject_name text, actor uuid, audience text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE receipt action_receipts%ROWTYPE; expected_event text;
BEGIN
  SELECT * INTO receipt FROM action_receipts WHERE tenant_id=tid AND product_id=pid
    AND subject_id=sid AND subject_revision=rev AND operation=op_name
    AND subject_type=subject_name AND actor_id=actor AND requester_id=actor AND run_id IS NULL
    AND visibility=audience;
  expected_event := CASE op_name
    WHEN 'quality.issue.create' THEN 'issue.created'
    WHEN 'quality.issue.merge' THEN 'issues.merged'
    WHEN 'quality.issue.triage' THEN 'issue.triaged'
    WHEN 'quality.issue.containment.record' THEN 'issue.contained'
    WHEN 'quality.capa.draft' THEN 'capa.drafted'
    WHEN 'quality.policy.import' THEN 'quality.policy_imported'
    WHEN 'change.request.create' THEN 'change.requested'
    WHEN 'change.impact.compute' THEN 'change.impact_created' END;
  IF receipt.id IS NULL OR expected_event IS NULL
    OR (SELECT count(*) FROM action_receipts WHERE tenant_id=tid AND product_id=pid
      AND subject_id=sid AND subject_revision=rev AND operation=op_name)<>1
    OR (SELECT count(*) FROM audit_entries WHERE tenant_id=tid AND receipt_id=receipt.id)<>1
    OR NOT EXISTS (SELECT 1 FROM audit_entries WHERE tenant_id=tid AND receipt_id=receipt.id
      AND actor_id=actor AND operation=op_name)
    OR (SELECT count(*) FROM outbox_events WHERE tenant_id=tid AND receipt_id=receipt.id)<>1
    OR NOT EXISTS (SELECT 1 FROM outbox_events WHERE tenant_id=tid AND receipt_id=receipt.id
      AND type=expected_event AND actor_id=actor AND subject_id=sid AND subject_revision=rev
      AND correlation_id=receipt.command_id AND schema_version=1) THEN
    RAISE EXCEPTION 'Quality/change write requires exactly one named receipt, audit and event';
  END IF;
END $$;
""",
    "protect_quality_current": r"""
CREATE FUNCTION protect_quality_current() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target quality_issue_versions%ROWTYPE;
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Issue identity pointer cannot be deleted'; END IF;
  SELECT * INTO target FROM quality_issue_versions WHERE tenant_id=NEW.tenant_id
    AND id=NEW.issue_version_id;
  IF target.id IS NULL OR ROW(target.product_id,target.project_id,target.issue_id,target.revision)
    IS DISTINCT FROM ROW(NEW.product_id,NEW.project_id,NEW.issue_id,NEW.issue_revision) THEN
    RAISE EXCEPTION 'Issue current requires its exact scoped version'; END IF;
  IF TG_OP='INSERT' THEN
    IF NEW.issue_revision<>1 OR NEW.epoch<>1 THEN
      RAISE EXCEPTION 'Issue identity starts only at revision and epoch one'; END IF;
  ELSE
    IF ROW(NEW.id,NEW.tenant_id,NEW.product_id,NEW.project_id,NEW.issue_id,NEW.created_at)
      IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.product_id,OLD.project_id,OLD.issue_id,OLD.created_at)
      OR NEW.issue_revision<>OLD.issue_revision+1 OR NEW.epoch<>OLD.epoch+1
      OR target.previous_issue_version_id IS DISTINCT FROM OLD.issue_version_id
      OR target.previous_revision IS DISTINCT FROM OLD.issue_revision THEN
      RAISE EXCEPTION 'Issue current requires a continuous exact predecessor'; END IF;
  END IF;
  RETURN NEW;
END $$;
""",
    "protect_quality_policy_current": r"""
CREATE FUNCTION protect_quality_policy_current() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target quality_policy_facts%ROWTYPE;
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Policy series pointer cannot be deleted'; END IF;
  SELECT * INTO target FROM quality_policy_facts WHERE tenant_id=NEW.tenant_id AND id=NEW.fact_id;
  IF target.id IS NULL OR ROW(target.product_id,target.project_id,target.purpose,target.series_id,
    target.revision,target.issuer_key,target.external_id) IS DISTINCT FROM
    ROW(NEW.product_id,NEW.project_id,NEW.purpose,NEW.series_id,NEW.fact_revision,
      NEW.issuer_key,NEW.external_id) THEN
    RAISE EXCEPTION 'Policy current requires its exact scoped fact'; END IF;
  IF TG_OP='INSERT' THEN
    IF NEW.fact_revision<>1 OR NEW.epoch<>1 THEN
      RAISE EXCEPTION 'Policy series starts at revision and epoch one'; END IF;
  ELSE
    IF ROW(NEW.id,NEW.tenant_id,NEW.product_id,NEW.project_id,NEW.purpose,NEW.series_id,
      NEW.issuer_key,NEW.external_id,NEW.created_at) IS DISTINCT FROM
      ROW(OLD.id,OLD.tenant_id,OLD.product_id,OLD.project_id,OLD.purpose,OLD.series_id,
        OLD.issuer_key,OLD.external_id,OLD.created_at)
      OR NEW.fact_revision<>OLD.fact_revision+1 OR NEW.epoch<>OLD.epoch+1
      OR target.previous_id IS DISTINCT FROM OLD.fact_id
      OR target.previous_revision IS DISTINCT FROM OLD.fact_revision THEN
      RAISE EXCEPTION 'Policy pointer requires a continuous exact predecessor'; END IF;
  END IF;
  RETURN NEW;
END $$;
""",
    "protect_change_current": r"""
CREATE FUNCTION protect_change_current() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target change_request_versions%ROWTYPE;
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Change pointer cannot be deleted'; END IF;
  SELECT * INTO target FROM change_request_versions WHERE tenant_id=NEW.tenant_id AND id=NEW.version_id;
  IF target.id IS NULL OR ROW(target.product_id,target.change_id,target.revision)
    IS DISTINCT FROM ROW(NEW.product_id,NEW.change_id,NEW.revision) THEN
    RAISE EXCEPTION 'Change current requires its exact scoped version'; END IF;
  IF TG_OP='INSERT' THEN
    IF NEW.revision<>1 THEN RAISE EXCEPTION 'Change starts at revision one'; END IF;
  ELSE
    IF ROW(NEW.id,NEW.tenant_id,NEW.product_id,NEW.change_id,NEW.created_at)
      IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.product_id,OLD.change_id,OLD.created_at)
      OR NEW.revision<>OLD.revision+1 OR target.previous_version_id IS DISTINCT FROM OLD.version_id
      OR target.previous_revision IS DISTINCT FROM OLD.revision THEN
      RAISE EXCEPTION 'Change pointer requires a continuous exact predecessor'; END IF;
  END IF;
  RETURN NEW;
END $$;
""",
    "protect_quality_failure_alias": r"""
CREATE FUNCTION protect_quality_failure_alias() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target quality_issue_versions%ROWTYPE; source quality_issue_versions%ROWTYPE;
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Failure identity cannot be deleted'; END IF;
  SELECT v.* INTO target FROM quality_current_issues c JOIN quality_issue_versions v
    ON v.tenant_id=c.tenant_id AND v.id=c.issue_version_id
    WHERE c.tenant_id=NEW.tenant_id AND c.product_id=NEW.product_id
      AND c.project_id=NEW.project_id AND c.issue_id=NEW.issue_id;
  IF target.id IS NULL OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(target.issue_snapshot->'failures') f
      WHERE f=NEW.failure) THEN
    RAISE EXCEPTION 'Failure alias requires the exact retained failure in its current Issue'; END IF;
  IF TG_OP='INSERT' THEN
    IF NEW.epoch<>1 THEN RAISE EXCEPTION 'Failure identity starts at epoch one'; END IF;
  ELSE
    SELECT v.* INTO source FROM quality_current_issues c JOIN quality_issue_versions v
      ON v.tenant_id=c.tenant_id AND v.id=c.issue_version_id
      WHERE c.tenant_id=OLD.tenant_id AND c.product_id=OLD.product_id
        AND c.project_id=OLD.project_id AND c.issue_id=OLD.issue_id;
    IF ROW(NEW.id,NEW.tenant_id,NEW.product_id,NEW.project_id,NEW.failure_identity,NEW.failure,NEW.created_at)
      IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.product_id,OLD.project_id,OLD.failure_identity,OLD.failure,OLD.created_at)
      OR NEW.issue_id=OLD.issue_id OR NEW.epoch<>OLD.epoch+1 OR source.id IS NULL
      OR source.operation<>'quality.issue.merge' OR target.operation<>'quality.issue.merge'
      OR source.intent_digest<>target.intent_digest
      OR source.issue_snapshot->>'merged_into' IS DISTINCT FROM NEW.issue_id::text THEN
      RAISE EXCEPTION 'Failure alias can move only through the exact preserved merge'; END IF;
  END IF;
  RETURN NEW;
END $$;
""",
    "require_quality_change_atom": r"""
CREATE FUNCTION require_quality_change_atom() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target quality_issue_versions%ROWTYPE; prior quality_issue_versions%ROWTYPE;
  merge_source quality_issue_versions%ROWTYPE; selected jsonb;
  change_before change_request_versions%ROWTYPE; capture change_graph_captures%ROWTYPE;
  receipt action_receipts%ROWTYPE; event outbox_events%ROWTYPE; projection test_result_projections%ROWTYPE;
BEGIN
  IF TG_TABLE_NAME='quality_issue_versions' THEN
    target := NEW;
    IF (NEW.revision=1 AND NEW.operation<>'quality.issue.create')
      OR (NEW.revision>1 AND NEW.operation='quality.issue.create')
      OR NOT EXISTS (SELECT 1 FROM quality_current_issues c WHERE c.tenant_id=NEW.tenant_id
        AND c.issue_version_id=NEW.id AND c.issue_revision=NEW.revision) THEN
      RAISE EXCEPTION 'Issue version must be the exact canonical creation or successor'; END IF;
    IF NEW.previous_issue_version_id IS NOT NULL THEN
      SELECT * INTO prior FROM quality_issue_versions WHERE tenant_id=NEW.tenant_id AND id=NEW.previous_issue_version_id;
      IF prior.id IS NULL OR ROW(prior.product_id,prior.project_id,prior.issue_id,prior.owner_id,prior.visibility,prior.purpose)
        IS DISTINCT FROM ROW(NEW.product_id,NEW.project_id,NEW.issue_id,NEW.owner_id,NEW.visibility,NEW.purpose)
        OR prior.revision<>NEW.previous_revision THEN
        RAISE EXCEPTION 'Issue successor must retain its exact owner, audience and scope'; END IF;
    END IF;
    IF NEW.operation='quality.issue.merge' THEN
      SELECT * INTO target FROM quality_issue_versions WHERE tenant_id=NEW.tenant_id
        AND product_id=NEW.product_id AND project_id=NEW.project_id
        AND issue_id::text=NEW.input_snapshot->>'issue_id' AND operation=NEW.operation
        AND intent_digest=NEW.intent_digest AND writer_id=NEW.writer_id;
      IF target.id IS NULL THEN RAISE EXCEPTION 'Merge requires one exact target version'; END IF;
      IF COALESCE(jsonb_typeof(target.input_snapshot->'sources'),'')<>'array'
        OR COALESCE(jsonb_array_length(target.input_snapshot->'sources'),0) NOT BETWEEN 1 AND 30
        OR EXISTS (SELECT 1 FROM jsonb_array_elements(target.input_snapshot->'sources') r
          WHERE r->>'id'=target.issue_id::text)
        OR (SELECT count(DISTINCT r->>'id') FROM jsonb_array_elements(target.input_snapshot->'sources') r)
          <>jsonb_array_length(target.input_snapshot->'sources')
        OR (NEW.id<>target.id AND NOT EXISTS (
          SELECT 1 FROM jsonb_array_elements(target.input_snapshot->'sources') r
          WHERE r->>'id'=NEW.issue_id::text AND (r->>'revision')::integer=NEW.previous_revision)) THEN
        RAISE EXCEPTION 'Merge requires explicit unique sources and only its exact listed successors'; END IF;
      IF target.previous_revision IS DISTINCT FROM
        (target.input_snapshot->>'expected_issue_revision')::integer THEN
        RAISE EXCEPTION 'Merge must retain its exact target precondition'; END IF;
      FOR selected IN SELECT * FROM jsonb_array_elements(target.input_snapshot->'sources') LOOP
        SELECT * INTO merge_source FROM quality_issue_versions WHERE tenant_id=target.tenant_id
          AND product_id=target.product_id AND project_id=target.project_id
          AND issue_id::text=selected->>'id' AND previous_revision=(selected->>'revision')::integer
          AND revision=(selected->>'revision')::integer+1 AND operation=target.operation
          AND intent_digest=target.intent_digest AND writer_id=target.writer_id;
        IF merge_source.id IS NULL
          OR merge_source.issue_snapshot->>'merged_into' IS DISTINCT FROM target.issue_id::text
          OR NOT COALESCE((target.issue_snapshot->'failures') @> (merge_source.issue_snapshot->'failures'),false)
          OR NOT EXISTS (SELECT 1 FROM quality_current_issues c WHERE c.tenant_id=target.tenant_id
            AND c.issue_version_id=merge_source.id AND c.issue_revision=merge_source.revision) THEN
          RAISE EXCEPTION 'Merge must preserve every exact source successor and failure'; END IF;
      END LOOP;
      IF EXISTS (SELECT 1 FROM jsonb_array_elements(target.issue_snapshot->'failures') f
        WHERE NOT EXISTS (SELECT 1 FROM quality_failure_maps m WHERE m.tenant_id=target.tenant_id
          AND m.product_id=target.product_id AND m.project_id=target.project_id
          AND m.issue_id=target.issue_id AND m.failure=f)) THEN
        RAISE EXCEPTION 'Merge requires all stable failure aliases to retain their exact target'; END IF;
    END IF;
    PERFORM assert_quality_change_receipt(target.tenant_id,target.product_id,target.id,target.revision,
      target.operation,'quality_issue',target.writer_id,target.visibility);
  ELSIF TG_TABLE_NAME='quality_policy_facts' THEN
    IF NOT EXISTS (SELECT 1 FROM quality_current_policies c WHERE c.tenant_id=NEW.tenant_id
      AND c.fact_id=NEW.id AND c.fact_revision=NEW.revision) THEN
      RAISE EXCEPTION 'Policy fact requires its exact canonical series pointer'; END IF;
    PERFORM assert_quality_change_receipt(NEW.tenant_id,NEW.product_id,NEW.id,NEW.revision,
      'quality.policy.import','quality_policy_fact',NEW.owner_id,NEW.visibility);
  ELSIF TG_TABLE_NAME='change_request_versions' THEN
    IF NOT EXISTS (SELECT 1 FROM change_request_currents c WHERE c.tenant_id=NEW.tenant_id
      AND c.version_id=NEW.id AND c.revision=NEW.revision)
      OR (NEW.operation='change.request.create' AND (NEW.revision<>1
        OR NEW.request_snapshot->'assessments' IS DISTINCT FROM '[]'::jsonb))
      OR (NEW.operation='change.impact.compute' AND NEW.revision<2) THEN
      RAISE EXCEPTION 'Change creation and impact must advance the exact canonical pointer'; END IF;
    IF NEW.previous_version_id IS NOT NULL THEN
      SELECT * INTO change_before FROM change_request_versions WHERE tenant_id=NEW.tenant_id AND id=NEW.previous_version_id;
      IF change_before.id IS NULL OR ROW(change_before.product_id,change_before.project_id,change_before.change_id,
        change_before.owner_id,change_before.visibility) IS DISTINCT FROM
        ROW(NEW.product_id,NEW.project_id,NEW.change_id,NEW.owner_id,NEW.visibility)
        OR change_before.revision<>NEW.previous_revision THEN
        RAISE EXCEPTION 'Change successor must retain exact owner, audience and scope'; END IF;
    END IF;
    IF NEW.operation='change.impact.compute' THEN
      SELECT * INTO capture FROM change_graph_captures WHERE tenant_id=NEW.tenant_id
        AND id::text=(NEW.request_snapshot->'assessments'->-1)->'graph'->>'id';
      IF capture.id IS NULL OR ROW(capture.product_id,capture.project_id,capture.change_id,
        capture.change_version_id,capture.change_revision) IS DISTINCT FROM
        ROW(NEW.product_id,NEW.project_id,NEW.change_id,NEW.previous_version_id,NEW.previous_revision)
        OR capture.graph_snapshot IS DISTINCT FROM (NEW.request_snapshot->'assessments'->-1)->'graph'
        OR jsonb_array_length(NEW.request_snapshot->'assessments')
          <>jsonb_array_length(change_before.request_snapshot->'assessments')+1
        OR ((NEW.request_snapshot->'assessments')
          - (jsonb_array_length(NEW.request_snapshot->'assessments')-1))
          IS DISTINCT FROM (change_before.request_snapshot->'assessments')
        OR capture.expires_at<=NEW.created_at THEN
        RAISE EXCEPTION 'Impact successor requires its exact unexpired committed graph capture'; END IF;
    END IF;
    PERFORM assert_quality_change_receipt(NEW.tenant_id,NEW.product_id,NEW.id,NEW.revision,
      NEW.operation,'change_request',(NEW.authority_snapshot->>'subject_id')::uuid,NEW.visibility);
  ELSIF TG_TABLE_NAME='quality_event_failure_links' THEN
    IF NOT EXISTS (SELECT 1 FROM quality_issue_versions v,
      LATERAL jsonb_array_elements(v.issue_snapshot->'failures') f
      WHERE v.tenant_id=NEW.tenant_id AND v.id=NEW.issue_version_id
        AND (f-'run')=(NEW.failure-'run') AND f->'run'->>'id'=NEW.run_id::text) THEN
      RAISE EXCEPTION 'Event delivery must retain the stable failure and its actual event Run revision'; END IF;
    SELECT * INTO event FROM outbox_events WHERE tenant_id=NEW.tenant_id AND id=NEW.event_id;
    SELECT * INTO receipt FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=event.receipt_id;
    SELECT * INTO projection FROM test_result_projections WHERE tenant_id=NEW.tenant_id AND id=NEW.projection_id;
    IF receipt.id IS NULL OR receipt.product_id<>NEW.product_id OR event.subject_id<>receipt.subject_id
      OR event.subject_revision<>receipt.subject_revision OR event.actor_id<>receipt.actor_id
      OR event.schema_version<>1 OR event.correlation_id<>receipt.command_id
      OR projection.basis_sha256<>NEW.basis_sha256
      OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(projection.computed_results) r
        WHERE r->>'measurement_id'=NEW.measurement_id::text AND r->>'result'='fail')
      OR NOT ((receipt.operation='test.result.compute' AND receipt.subject_type='test_result_projection'
          AND receipt.subject_id=NEW.projection_id AND receipt.subject_revision=NEW.projection_revision
          AND event.type='test.result_computed' AND projection.run_version_id=NEW.run_version_id)
        OR (receipt.operation IN ('test.results.import','test.run.review','test.disposition.decide')
          AND receipt.subject_type='test_run' AND receipt.subject_id=NEW.run_version_id
          AND receipt.subject_revision=NEW.run_revision
          AND EXISTS (SELECT 1 FROM test_result_actions a WHERE a.tenant_id=NEW.tenant_id
            AND a.product_id=NEW.product_id AND a.project_id=NEW.project_id
            AND a.build_id=NEW.build_id AND a.request_id=NEW.request_id AND a.run_id=NEW.run_id
            AND a.next_run_version_id=NEW.run_version_id AND a.next_run_revision=NEW.run_revision
            AND a.operation=receipt.operation AND a.projection_id=NEW.projection_id)
          AND event.type=CASE receipt.operation WHEN 'test.results.import' THEN 'test.results_imported'
            WHEN 'test.run.review' THEN 'test.run_reviewed' ELSE 'test.disposition_decided' END)) THEN
      RAISE EXCEPTION 'Failure link requires its exact actual result event and fixed failing projection'; END IF;
  END IF;
  RETURN NULL;
END $$;
""",
}

IMMUTABLE = (
    "quality_issue_versions",
    "quality_policy_facts",
    "quality_event_failure_links",
    "change_request_versions",
    "change_graph_captures",
)
POINTERS = {
    "quality_current_issues": "protect_quality_current",
    "quality_current_policies": "protect_quality_policy_current",
    "quality_failure_maps": "protect_quality_failure_alias",
    "change_request_currents": "protect_change_current",
}
ATOMIC = (
    "quality_issue_versions",
    "quality_policy_facts",
    "quality_event_failure_links",
    "change_request_versions",
)
