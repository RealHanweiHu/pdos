"""Multi-file reviewed intake imports and actual business application receipts."""

from alembic import op

revision = "0253_intake_ai_imports"
down_revision = "0252_intake_ai_observations"
branch_labels = None
depends_on = None

DDL = """
ALTER TABLE cehub_ai.issue_intake_previews DROP CONSTRAINT
ck_issue_intake_previews_purpose_and_parser;
ALTER TABLE cehub_ai.issue_intake_previews ADD CONSTRAINT
ck_issue_intake_previews_purpose_and_parser CHECK (btrim(permission_basis)<>'' AND
btrim(purpose)<>'' AND parser_version IN ('issue-list-extracted-v1', 'issue-pdf-extracted-v1',
'issue-email-extracted-v1', 'issue-ai-cited-v1'));
CREATE INDEX ix_issue_intake_ai_finding ON cehub_ai.issue_intake_previews (tenant_id, (mapping ->>
'finding_id')) WHERE parser_version = 'issue-ai-cited-v1';
ALTER TABLE cehub_ai.decision_intake_previews DROP CONSTRAINT
ck_decision_intake_previews_purpose_and_parser;
ALTER TABLE cehub_ai.decision_intake_previews ADD CONSTRAINT
ck_decision_intake_previews_purpose_and_parser CHECK (btrim(permission_basis)<>'' AND
btrim(purpose)<>'' AND parser_version IN ('decision-list-extracted-v1', 'decision-pdf-extracted-v1',
'decision-email-extracted-v1', 'decision-ai-cited-v1'));
CREATE INDEX ix_decision_intake_ai_finding ON cehub_ai.decision_intake_previews (tenant_id, (mapping
->> 'finding_id')) WHERE parser_version = 'decision-ai-cited-v1';
"""
GUARD = """

CREATE FUNCTION cehub_ai.intake_finding_targets(tenant uuid, finding uuid)
RETURNS TABLE(proposal_number integer,target_kind text,target_id uuid)
LANGUAGE sql STABLE AS $$
 SELECT a.proposal_number, 'project_intake_proposal'::text, a.proposal_id
 FROM cehub_ai.intake_ai_observation_applications a
 WHERE a.tenant_id=tenant AND a.finding_id=finding
 UNION ALL
 SELECT (p.mapping->>'proposal_number')::integer, 'issue'::text, (r->>'issue_id')::uuid
 FROM cehub_ai.issue_intake_previews p JOIN cehub_ai.issue_intake_batches b
 ON b.tenant_id=p.tenant_id AND b.preview_id=p.id
 CROSS JOIN LATERAL jsonb_array_elements(b.results) r
 WHERE p.tenant_id=tenant AND p.parser_version='issue-ai-cited-v1'
  AND p.mapping->>'finding_id'=finding::text
  AND (r->>'row')::integer=(p.mapping->>'proposal_number')::integer
  AND r->>'status' IN ('created','linked','reused')
 UNION ALL
 SELECT (p.mapping->>'proposal_number')::integer, 'decision'::text, (r->>'decision_id')::uuid
 FROM cehub_ai.decision_intake_previews p JOIN cehub_ai.decision_intake_batches b
 ON b.tenant_id=p.tenant_id AND b.preview_id=p.id
 CROSS JOIN LATERAL jsonb_array_elements(b.results) r
 WHERE p.tenant_id=tenant AND p.parser_version='decision-ai-cited-v1'
  AND p.mapping->>'finding_id'=finding::text
  AND (r->>'row')::integer=(p.mapping->>'proposal_number')::integer
  AND r->>'status' IN ('created','linked','reused');
$$;
REVOKE ALL ON FUNCTION cehub_ai.intake_finding_targets(uuid,uuid) FROM PUBLIC;
CREATE FUNCTION cehub_ai.guard_cited_intake_preview() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE f cehub_ai.findings; r cehub_ai.agent_runs; b cehub_ai.intake_ai_briefs;
 p jsonb; v jsonb; item record;
BEGIN
 IF NEW.parser_version NOT IN ('issue-ai-cited-v1','decision-ai-cited-v1') THEN RETURN NEW; END IF;
 SELECT * INTO f FROM cehub_ai.findings WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id
  AND id::text=NEW.mapping->>'finding_id';
 SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND id=f.run_id;
 SELECT * INTO b FROM cehub_ai.intake_ai_briefs WHERE tenant_id=NEW.tenant_id
  AND id::text=r.run_context->>'intake_brief_id';
 SELECT value INTO p FROM jsonb_array_elements(f.accepted_payload->'proposals')
  WHERE value->>'number'=NEW.mapping->>'proposal_number';
 v := NEW.rows->0;
 IF f.id IS NULL OR f.status<>'accepted' OR f.finding_type<>'intake_organization'
  OR f.reviewed_by_user_id IS DISTINCT FROM NEW.created_by_user_id OR p IS NULL
  OR NEW.parser_version IS DISTINCT FROM (p->>'kind')||'-ai-cited-v1'
  OR b.conversation_id IS DISTINCT FROM NEW.conversation_id
  OR b.message_id IS DISTINCT FROM NEW.message_id
  OR NEW.mapping->'proposal' IS DISTINCT FROM p
  OR jsonb_array_length(NEW.rows)<>1
  OR v->'row' IS DISTINCT FROM p->'number'
  OR (v->'anchor')-'cell' IS DISTINCT FROM p->'anchor'
  OR NEW.attachment_id::text IS DISTINCT FROM p->'anchor'->>'attachment_id'
  OR NEW.source_snapshot IS DISTINCT FROM
   b.source_snapshot->'sources'->NEW.attachment_id::text->'identity' THEN
  RAISE EXCEPTION 'Cited import must match the accepted private proposal'; END IF;
 FOR item IN SELECT * FROM jsonb_each(p->'original') LOOP
  IF (v->'original'->item.key)-'cell' IS DISTINCT FROM item.value THEN
   RAISE EXCEPTION 'Cited field must preserve the reviewed literal range'; END IF;
 END LOOP;
 IF (SELECT count(*) FROM jsonb_object_keys(v->'original')) <>
    (SELECT count(*) FROM jsonb_object_keys(p->'original')) THEN
  RAISE EXCEPTION 'Cited import field set must match its accepted proposal'; END IF;
 FOR item IN SELECT * FROM jsonb_each(NEW.mapping->'source_identities') LOOP
  IF item.value IS DISTINCT FROM b.source_snapshot->'sources'->item.key->'identity' THEN
   RAISE EXCEPTION 'Cited sources must match the fixed private originals'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_cited_intake_preview() FROM PUBLIC;
CREATE TRIGGER guard_cited_issue_intake_preview BEFORE INSERT ON cehub_ai.issue_intake_previews
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_cited_intake_preview();
CREATE TRIGGER guard_cited_decision_intake_preview BEFORE INSERT
 ON cehub_ai.decision_intake_previews
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_cited_intake_preview();
CREATE OR REPLACE FUNCTION cehub_ai.guard_intake_ai_finding() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r cehub_ai.agent_runs; cp cehub_ai.application_result_checkpoints;
 b cehub_ai.intake_ai_briefs; conv cehub_ai.conversations;
BEGIN
 IF TG_OP='UPDATE' AND OLD.finding_type='intake_organization'
  AND OLD.status='accepted' AND NEW.status='applied' THEN
  IF (to_jsonb(NEW)-ARRAY['status','applied_by_user_id','applied_at','updated_at',
      'applied_entity_type','applied_entity_id']) IS DISTINCT FROM
     (to_jsonb(OLD)-ARRAY['status','applied_by_user_id','applied_at','updated_at',
      'applied_entity_type','applied_entity_id'])
   OR NEW.applied_by_user_id IS DISTINCT FROM OLD.reviewed_by_user_id
   OR NOT EXISTS(SELECT 1 FROM cehub_ai.intake_finding_targets(NEW.tenant_id,NEW.id) t
       WHERE t.target_kind=NEW.applied_entity_type AND t.target_id=NEW.applied_entity_id)
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(OLD.accepted_payload->'proposals') p
      WHERE NOT EXISTS(SELECT 1 FROM cehub_ai.intake_finding_targets(NEW.tenant_id,NEW.id) t
        WHERE t.proposal_number=(p->>'number')::integer)) THEN
    RAISE EXCEPTION 'Intake application needs all accepted proposals and actual receipts'; END IF;
  RETURN NEW;
 END IF;
 IF TG_OP='UPDATE' AND OLD.finding_type='intake_organization' THEN
  IF NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;
  IF OLD.status<>'pending_review' OR NEW.status NOT IN ('accepted','rejected')
   OR (to_jsonb(NEW)-ARRAY['status','reviewed_by_user_id','reviewed_at',
      'review_comment','accepted_payload','updated_at']) IS DISTINCT FROM
      (to_jsonb(OLD)-ARRAY['status','reviewed_by_user_id','reviewed_at',
      'review_comment','accepted_payload','updated_at']) THEN
   RAISE EXCEPTION 'Intake original result and completed review are immutable'; END IF;
  SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id;
  SELECT * INTO b FROM cehub_ai.intake_ai_briefs WHERE tenant_id=NEW.tenant_id
   AND id::text=r.run_context->>'intake_brief_id';
  SELECT * INTO conv FROM cehub_ai.conversations WHERE tenant_id=NEW.tenant_id
   AND id=b.conversation_id FOR UPDATE;
  IF b.id IS NULL OR conv.id IS NULL OR conv.archived_at IS NOT NULL
   OR NEW.reviewed_by_user_id IS DISTINCT FROM r.requested_by_user_id
   OR NEW.reviewed_by_user_id IS DISTINCT FROM b.created_by_user_id
   OR NEW.reviewed_by_user_id IS DISTINCT FROM conv.created_by_user_id
   OR coalesce(btrim(NEW.review_comment),'')='' THEN
   RAISE EXCEPTION 'Intake review requires its private owner and review note'; END IF;
  IF NEW.status='accepted' AND (
   NEW.accepted_payload->>'version' IS DISTINCT FROM 'intake-human-review-v1'
   OR NEW.accepted_payload->>'brief_id' IS DISTINCT FROM b.id::text
   OR NEW.accepted_payload->>'source_digest' IS DISTINCT FROM b.source_digest
   OR jsonb_typeof(NEW.accepted_payload->'assessment') IS DISTINCT FROM 'object'
   OR jsonb_typeof(NEW.accepted_payload->'proposals') IS DISTINCT FROM 'array'
   OR jsonb_typeof(NEW.accepted_payload->'exclusions') IS DISTINCT FROM 'array'
   OR jsonb_typeof(NEW.accepted_payload->'duplicate_reviews') IS DISTINCT FROM 'array'
  ) THEN RAISE EXCEPTION 'Intake acceptance requires a source-bound human assessment'; END IF;
  RETURN NEW;
 END IF;
 IF NEW.finding_type<>'intake_organization' THEN RETURN NEW; END IF;
 SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id
  AND project_id=NEW.project_id AND context_version='intake-organization-request-v1';
 SELECT * INTO cp FROM cehub_ai.application_result_checkpoints WHERE tenant_id=NEW.tenant_id
  AND run_id=NEW.run_id AND invocation_id=NEW.model_invocation_id;
 IF r.id IS NULL OR NEW.agent_key<>'knowledge_lite' OR NEW.status<>'pending_review'
  OR NEW.origin_key IS DISTINCT FROM 'intake:'||(r.run_context->>'intake_brief_id')
  OR NEW.proposed_payload->>'brief_id' IS DISTINCT FROM r.run_context->>'intake_brief_id'
  OR cp.id IS NULL OR cp.body->'output' IS DISTINCT FROM NEW.proposed_payload->'assessment'
  OR NOT cehub_ai.application_result_receipt_valid(cp.tenant_id,cp.run_id,cp.model_call_id,
    cp.observation_id,cp.manifest_id,cp.invocation_id,cp.owner_lease_id) THEN
  RAISE EXCEPTION 'Intake Finding needs its actual successful model receipt'; END IF;
 RETURN NEW;
END $$;
"""
OLD = """
ALTER TABLE cehub_ai.issue_intake_previews DROP CONSTRAINT
ck_issue_intake_previews_purpose_and_parser;
ALTER TABLE cehub_ai.issue_intake_previews ADD CONSTRAINT
ck_issue_intake_previews_purpose_and_parser CHECK (btrim(permission_basis)<>'' AND
btrim(purpose)<>'' AND parser_version IN ('issue-list-extracted-v1', 'issue-pdf-extracted-v1',
'issue-email-extracted-v1'));
ALTER TABLE cehub_ai.decision_intake_previews DROP CONSTRAINT
ck_decision_intake_previews_purpose_and_parser;
ALTER TABLE cehub_ai.decision_intake_previews ADD CONSTRAINT
ck_decision_intake_previews_purpose_and_parser CHECK (btrim(permission_basis)<>'' AND
btrim(purpose)<>'' AND parser_version IN ('decision-list-extracted-v1', 'decision-pdf-extracted-v1',
'decision-email-extracted-v1'));
CREATE OR REPLACE FUNCTION cehub_ai.guard_intake_ai_finding() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r cehub_ai.agent_runs; cp cehub_ai.application_result_checkpoints;
 b cehub_ai.intake_ai_briefs; conv cehub_ai.conversations;
BEGIN
 IF TG_OP='UPDATE' AND OLD.finding_type='intake_organization'
  AND OLD.status='accepted' AND NEW.status='applied' THEN
  IF (to_jsonb(NEW)-ARRAY['status','applied_by_user_id','applied_at','updated_at',
      'applied_entity_type','applied_entity_id']) IS DISTINCT FROM
     (to_jsonb(OLD)-ARRAY['status','applied_by_user_id','applied_at','updated_at',
      'applied_entity_type','applied_entity_id'])
   OR NEW.applied_by_user_id IS DISTINCT FROM OLD.reviewed_by_user_id
   OR NEW.applied_entity_type IS DISTINCT FROM 'project_intake_proposal'
   OR NOT EXISTS(SELECT 1 FROM cehub_ai.intake_ai_observation_applications a
      WHERE a.tenant_id=NEW.tenant_id AND a.finding_id=NEW.id
       AND a.proposal_id=NEW.applied_entity_id)
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(OLD.accepted_payload->'proposals') p
      WHERE NOT EXISTS(SELECT 1 FROM cehub_ai.intake_ai_observation_applications a
       WHERE a.tenant_id=NEW.tenant_id AND a.finding_id=NEW.id
        AND a.proposal_number=(p->>'number')::integer)) THEN
    RAISE EXCEPTION 'Intake application needs all accepted proposals and actual receipts'; END IF;
  RETURN NEW;
 END IF;
 IF TG_OP='UPDATE' AND OLD.finding_type='intake_organization' THEN
  IF NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;
  IF OLD.status<>'pending_review' OR NEW.status NOT IN ('accepted','rejected')
   OR (to_jsonb(NEW)-ARRAY['status','reviewed_by_user_id','reviewed_at',
      'review_comment','accepted_payload','updated_at']) IS DISTINCT FROM
      (to_jsonb(OLD)-ARRAY['status','reviewed_by_user_id','reviewed_at',
      'review_comment','accepted_payload','updated_at']) THEN
   RAISE EXCEPTION 'Intake original result and completed review are immutable'; END IF;
  SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id;
  SELECT * INTO b FROM cehub_ai.intake_ai_briefs WHERE tenant_id=NEW.tenant_id
   AND id::text=r.run_context->>'intake_brief_id';
  SELECT * INTO conv FROM cehub_ai.conversations WHERE tenant_id=NEW.tenant_id
   AND id=b.conversation_id FOR UPDATE;
  IF b.id IS NULL OR conv.id IS NULL OR conv.archived_at IS NOT NULL
   OR NEW.reviewed_by_user_id IS DISTINCT FROM r.requested_by_user_id
   OR NEW.reviewed_by_user_id IS DISTINCT FROM b.created_by_user_id
   OR NEW.reviewed_by_user_id IS DISTINCT FROM conv.created_by_user_id
   OR coalesce(btrim(NEW.review_comment),'')='' THEN
   RAISE EXCEPTION 'Intake review requires its private owner and review note'; END IF;
  IF NEW.status='accepted' AND (
   NEW.accepted_payload->>'version' IS DISTINCT FROM 'intake-human-review-v1'
   OR NEW.accepted_payload->>'brief_id' IS DISTINCT FROM b.id::text
   OR NEW.accepted_payload->>'source_digest' IS DISTINCT FROM b.source_digest
   OR jsonb_typeof(NEW.accepted_payload->'assessment') IS DISTINCT FROM 'object'
   OR jsonb_typeof(NEW.accepted_payload->'proposals') IS DISTINCT FROM 'array'
   OR jsonb_typeof(NEW.accepted_payload->'exclusions') IS DISTINCT FROM 'array'
   OR jsonb_typeof(NEW.accepted_payload->'duplicate_reviews') IS DISTINCT FROM 'array'
  ) THEN RAISE EXCEPTION 'Intake acceptance requires a source-bound human assessment'; END IF;
  RETURN NEW;
 END IF;
 IF NEW.finding_type<>'intake_organization' THEN RETURN NEW; END IF;
 SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id
  AND project_id=NEW.project_id AND context_version='intake-organization-request-v1';
 SELECT * INTO cp FROM cehub_ai.application_result_checkpoints WHERE tenant_id=NEW.tenant_id
  AND run_id=NEW.run_id AND invocation_id=NEW.model_invocation_id;
 IF r.id IS NULL OR NEW.agent_key<>'knowledge_lite' OR NEW.status<>'pending_review'
  OR NEW.origin_key IS DISTINCT FROM 'intake:'||(r.run_context->>'intake_brief_id')
  OR NEW.proposed_payload->>'brief_id' IS DISTINCT FROM r.run_context->>'intake_brief_id'
  OR cp.id IS NULL OR cp.body->'output' IS DISTINCT FROM NEW.proposed_payload->'assessment'
  OR NOT cehub_ai.application_result_receipt_valid(cp.tenant_id,cp.run_id,cp.model_call_id,
    cp.observation_id,cp.manifest_id,cp.invocation_id,cp.owner_lease_id) THEN
  RAISE EXCEPTION 'Intake Finding needs its actual successful model receipt'; END IF;
 RETURN NEW;
END $$;
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
    IF EXISTS(SELECT 1 FROM cehub_ai.issue_intake_previews WHERE parser_version='issue-ai-cited-v1')
     OR EXISTS(SELECT 1 FROM cehub_ai.decision_intake_previews
      WHERE parser_version='decision-ai-cited-v1') THEN
      RAISE EXCEPTION 'Cited intake history must be retained'; END IF;
    END $$""")
    op.execute(OLD)
    op.execute("DROP TRIGGER guard_cited_issue_intake_preview ON cehub_ai.issue_intake_previews")
    op.execute(
        "DROP TRIGGER guard_cited_decision_intake_preview ON cehub_ai.decision_intake_previews"
    )
    op.execute("DROP FUNCTION cehub_ai.guard_cited_intake_preview()")
    op.execute("DROP FUNCTION cehub_ai.intake_finding_targets(uuid,uuid)")
    op.execute("DROP INDEX cehub_ai.ix_issue_intake_ai_finding")
    op.execute("DROP INDEX cehub_ai.ix_decision_intake_ai_finding")
