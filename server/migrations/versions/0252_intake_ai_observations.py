"""Independent adoption of reviewed observations into actual project intake versions."""

from alembic import op

revision = "0252_intake_ai_observations"
down_revision = "0251_intake_ai_review"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_ai.intake_ai_observation_applications (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	project_id UUID NOT NULL,
	finding_id UUID NOT NULL,
	proposal_number INTEGER NOT NULL,
	proposal_id UUID NOT NULL,
	created_by_user_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	request_id UUID NOT NULL,
	request_digest VARCHAR(64) NOT NULL,
	source_snapshot JSONB NOT NULL,
	observation_keys JSONB NOT NULL,
	review_note TEXT NOT NULL,
	CONSTRAINT pk_intake_ai_observation_applications PRIMARY KEY (id),
	CONSTRAINT uq_intake_ai_observation_number UNIQUE (tenant_id, finding_id, proposal_number),
        CONSTRAINT fk_intake_ai_observation_applications_tenant_id_findings FOREIGN KEY(tenant_id,
project_id, finding_id) REFERENCES cehub_ai.findings (tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_intake_ai_observation_applications_tenant_id_project_cddb FOREIGN
KEY(tenant_id, project_id, proposal_id) REFERENCES cehub_project.project_intake_proposals
(tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_intake_ai_observation_applications_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_intake_ai_observation_applications_identity CHECK (proposal_number BETWEEN 1
AND 30 AND request_digest ~ '^[0-9a-f]{64}$' AND btrim(review_note)<>''),
        CONSTRAINT ck_intake_ai_observation_applications_shape CHECK
(jsonb_typeof(source_snapshot)='object' AND jsonb_typeof(observation_keys)='array' AND
jsonb_array_length(observation_keys) BETWEEN 1 AND 7)
)

;
ALTER TABLE cehub_ai.findings DROP CONSTRAINT ck_findings_apply_lifecycle_consistent;
ALTER TABLE cehub_ai.findings ADD CONSTRAINT ck_findings_apply_lifecycle_consistent CHECK ((status
<> 'applied' AND applied_by_user_id IS NULL AND applied_at IS NULL AND applied_entity_type IS NULL
AND applied_entity_id IS NULL) OR (status = 'applied' AND applied_by_user_id IS NOT NULL AND
applied_at IS NOT NULL AND applied_entity_type IN ('risk', 'memory', 'issue', 'task', 'test_run',
'sample_build_configuration', 'knowledge_candidate', 'schedule_change_proposal',
'material_exception', 'test_plan', 'meeting_minutes', 'decision', 'ecr', 'change_impact_scope',
'quality_work_package', 'process_template_revision', 'project_intake_proposal') AND
applied_entity_id IS NOT NULL AND reviewed_at < applied_at));
"""
GUARD = """

CREATE FUNCTION cehub_ai.guard_intake_ai_observation_application() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE f cehub_ai.findings; p cehub_project.project_intake_proposals; v jsonb; k jsonb;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Intake adoption receipt is immutable'; END IF;
 SELECT * INTO f FROM cehub_ai.findings WHERE tenant_id=NEW.tenant_id
  AND project_id=NEW.project_id AND id=NEW.finding_id FOR UPDATE;
 SELECT * INTO p FROM cehub_project.project_intake_proposals WHERE tenant_id=NEW.tenant_id
  AND project_id=NEW.project_id AND id=NEW.proposal_id;
 SELECT value INTO v FROM jsonb_array_elements(f.accepted_payload->'proposals')
  WHERE (value->>'number')::integer=NEW.proposal_number;
 IF f.id IS NULL OR f.finding_type<>'intake_organization' OR f.status<>'accepted'
  OR NEW.created_by_user_id IS DISTINCT FROM f.reviewed_by_user_id
  OR p.id IS NULL OR p.created_by_user_id IS DISTINCT FROM NEW.created_by_user_id
  OR NEW.review_note IS DISTINCT FROM p.draft->>'review_note'
  OR v IS NULL OR v->>'kind' IS DISTINCT FROM 'project_observation'
  OR NEW.source_snapshot->'proposal' IS DISTINCT FROM v THEN
  RAISE EXCEPTION 'Intake adoption requires the accepted proposal and actual project version';
 END IF;
 FOR k IN SELECT value FROM jsonb_array_elements(NEW.observation_keys) LOOP
  IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p.sources) source
    WHERE source->'key'=k) THEN
   RAISE EXCEPTION 'Adoption source key must exist in the saved project version'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_intake_ai_observation_application() FROM PUBLIC;
CREATE TRIGGER guard_intake_ai_observation_application BEFORE INSERT OR UPDATE OR DELETE ON
 cehub_ai.intake_ai_observation_applications FOR EACH ROW EXECUTE FUNCTION
 cehub_ai.guard_intake_ai_observation_application();

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
OLD = """
ALTER TABLE cehub_ai.findings DROP CONSTRAINT ck_findings_apply_lifecycle_consistent;
ALTER TABLE cehub_ai.findings ADD CONSTRAINT ck_findings_apply_lifecycle_consistent CHECK ((status
<> 'applied' AND applied_by_user_id IS NULL AND applied_at IS NULL AND applied_entity_type IS NULL
AND applied_entity_id IS NULL) OR (status = 'applied' AND applied_by_user_id IS NOT NULL AND
applied_at IS NOT NULL AND applied_entity_type IN ('risk', 'memory', 'issue', 'task', 'test_run',
'sample_build_configuration', 'knowledge_candidate', 'schedule_change_proposal',
'material_exception', 'test_plan', 'meeting_minutes', 'decision', 'ecr', 'change_impact_scope',
'quality_work_package', 'process_template_revision') AND applied_entity_id IS NOT NULL AND
reviewed_at < applied_at));
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


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
    IF EXISTS(SELECT 1 FROM cehub_ai.intake_ai_observation_applications) THEN
      RAISE EXCEPTION 'Intake adoption history must be retained'; END IF;
    END $$""")
    op.execute(OLD)
    op.execute("DROP TABLE cehub_ai.intake_ai_observation_applications")
    op.execute("DROP FUNCTION cehub_ai.guard_intake_ai_observation_application()")
