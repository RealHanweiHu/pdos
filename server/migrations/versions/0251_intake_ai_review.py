"""Separate private human review from original intake model suggestions."""

from alembic import op

revision = "0251_intake_ai_review"
down_revision = "0250_intake_ai_runs"
branch_labels = None
depends_on = None

REVIEW = """
CREATE OR REPLACE FUNCTION cehub_ai.guard_intake_ai_finding() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r cehub_ai.agent_runs; cp cehub_ai.application_result_checkpoints;
 b cehub_ai.intake_ai_briefs; conv cehub_ai.conversations;
BEGIN
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
CREATE OR REPLACE FUNCTION cehub_ai.guard_intake_ai_finding() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r cehub_ai.agent_runs; cp cehub_ai.application_result_checkpoints;
BEGIN
 IF TG_OP='UPDATE' AND OLD.finding_type='intake_organization' THEN
  IF NEW IS DISTINCT FROM OLD THEN
   RAISE EXCEPTION 'Intake review and application are not yet enabled'; END IF;
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
    op.execute(REVIEW)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
    IF EXISTS(SELECT 1 FROM cehub_ai.findings WHERE finding_type='intake_organization'
      AND status<>'pending_review') THEN
      RAISE EXCEPTION 'Intake human review history must be retained'; END IF;
    END $$""")
    op.execute(OLD)
