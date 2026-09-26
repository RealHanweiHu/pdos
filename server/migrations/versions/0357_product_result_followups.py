"""Named actual-result feedback implementation against actual definition revisions."""

# ruff: noqa: E501
from alembic import op

revision = "0357_product_result_followups"
down_revision = "0356_product_metric_calculations"
branch_labels = None
depends_on = None
DDL = """
ALTER TABLE cehub_product.product_result_feedback ADD CONSTRAINT uq_product_result_feedback_scope UNIQUE (tenant_id, market_space_id, id);

CREATE TABLE cehub_product.product_result_followups (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	market_space_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	definition_id UUID NOT NULL, 
	feedback_id UUID NOT NULL, 
	revision_id UUID, 
	version INTEGER NOT NULL, 
	previous_id UUID, 
	action VARCHAR(32) NOT NULL, 
	snapshot JSONB NOT NULL, 
	preview_digest VARCHAR(64) NOT NULL, 
	actor_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_product_result_followups PRIMARY KEY (id), 
	CONSTRAINT uq_product_result_followup_version UNIQUE (tenant_id, feedback_id, version), 
	CONSTRAINT uq_product_result_followup_request UNIQUE (tenant_id, actor_user_id, request_id), 
	CONSTRAINT uq_product_result_followup_scope UNIQUE (tenant_id, market_space_id, id), 
	CONSTRAINT fk_product_result_followups_tenant_id_product_result_followups FOREIGN KEY(tenant_id, market_space_id, previous_id) REFERENCES cehub_product.product_result_followups (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_product_result_followups_tenant_id_product_result_feedback FOREIGN KEY(tenant_id, market_space_id, feedback_id) REFERENCES cehub_product.product_result_feedback (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_result_followup_definition FOREIGN KEY(tenant_id, market_space_id, definition_id) REFERENCES cehub_product.product_definitions (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_result_followup_revision FOREIGN KEY(tenant_id, market_space_id, revision_id) REFERENCES cehub_product.product_definitions (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_product_result_followups_tenant_id_projects FOREIGN KEY(tenant_id, project_id) REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_product_result_followups_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT ck_product_result_followups_shape CHECK (version>0 AND ((version=1 AND previous_id IS NULL AND action<>'withdrawn') OR (version>1 AND previous_id IS NOT NULL)) AND action IN ('link_revision','no_change','needs_evidence','withdrawn') AND ((action='link_revision' AND revision_id IS NOT NULL) OR (action<>'link_revision' AND revision_id IS NULL)) AND jsonb_typeof(snapshot)='object' AND preview_digest ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$')
)

;
CREATE INDEX ix_product_result_followup_history ON cehub_product.product_result_followups (tenant_id, feedback_id, version);
CREATE INDEX ix_product_result_followup_revision ON cehub_product.product_result_followups (tenant_id, market_space_id, revision_id, id);
"""
GUARDS = """
CREATE FUNCTION cehub_product.guard_product_result_followup() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog AS $$
DECLARE f cehub_product.product_result_feedback; d cehub_product.product_definitions; r cehub_product.product_definitions;
 p cehub_product.product_result_followups; latest integer; b jsonb;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR UPDATE;
 PERFORM 1 FROM cehub_product.market_spaces WHERE tenant_id=NEW.tenant_id AND id=NEW.market_space_id FOR UPDATE;
 SELECT * INTO f FROM cehub_product.product_result_feedback WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.feedback_id;
 SELECT * INTO d FROM cehub_product.product_definitions WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.definition_id;
 SELECT * INTO p FROM cehub_product.product_result_followups WHERE tenant_id=NEW.tenant_id AND feedback_id=NEW.feedback_id ORDER BY version DESC LIMIT 1;
 SELECT max(version) INTO latest FROM cehub_product.product_result_feedback WHERE tenant_id=f.tenant_id AND definition_id=f.definition_id AND project_id=f.project_id AND source_kind=f.source_kind AND source_id=f.source_id;
 b=NEW.snapshot->'basis';
 IF f.id IS NULL OR d.id IS NULL OR f.project_id<>NEW.project_id OR f.definition_id<>NEW.definition_id
 OR NEW.version<>coalesce(p.version,0)+1 OR NEW.previous_id IS DISTINCT FROM p.id
 OR (NEW.action<>'withdrawn' AND (f.version<>latest OR f.verdict='withdrawn'))
 OR b->'feedback'->>'id' IS DISTINCT FROM f.id::text
 OR b->'feedback'->>'version' IS DISTINCT FROM f.version::text
 OR b->'feedback'->'selected_fields' IS DISTINCT FROM f.selected_fields
 OR NEW.snapshot->>'action' IS DISTINCT FROM NEW.action
 OR NEW.snapshot->>'digest' IS DISTINCT FROM NEW.preview_digest
 OR coalesce(btrim(NEW.snapshot->>'reason'),'')='' OR coalesce(btrim(NEW.snapshot->>'limitations'),'')=''
 OR jsonb_typeof(NEW.snapshot->'responses') IS DISTINCT FROM 'array'
 OR jsonb_array_length(NEW.snapshot->'responses')<>jsonb_array_length(f.selected_fields)
 OR EXISTS (SELECT 1 FROM jsonb_array_elements(f.selected_fields) field WHERE
   (SELECT count(*) FROM jsonb_array_elements(NEW.snapshot->'responses') response WHERE response->'response'->>'original_path'=field->>'path' AND response->'original'=field)<>1)
 THEN RAISE EXCEPTION 'Feedback followup requires actual feedback scope, complete responses and sequential versions'; END IF;
 IF NEW.action='link_revision' THEN
  SELECT * INTO r FROM cehub_product.product_definitions WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.revision_id;
  IF f.verdict<>'adopt_for_followup' OR b->>'sources_current' IS DISTINCT FROM 'true'
  OR b->'current_source'->>'digest' IS DISTINCT FROM f.source_digest
  OR b->'current_source'->>'inheritance_current' IS DISTINCT FROM 'true'
  OR r.id IS NULL OR r.series_id<>d.series_id OR r.revision_number<=d.revision_number
  OR b->'revision'->>'id' IS DISTINCT FROM r.id::text
  OR b->'revision'->>'version' IS DISTINCT FROM r.version::text
  OR b->'revision'->'content' IS DISTINCT FROM r.content OR b->'revision'->>'state' IS DISTINCT FROM r.state
  THEN RAISE EXCEPTION 'Feedback implementation requires current adoption and actual later definition revision'; END IF;
 ELSE
  IF b->'revision' IS DISTINCT FROM 'null'::jsonb THEN RAISE EXCEPTION 'Non-revision followup cannot claim a revision'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_product_result_followup BEFORE INSERT ON cehub_product.product_result_followups
FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_product_result_followup();
CREATE TRIGGER immutable_product_result_followup BEFORE UPDATE OR DELETE ON cehub_product.product_result_followups
FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_product.product_result_followups FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_product.guard_product_result_followup() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_product.product_result_followups) THEN RAISE EXCEPTION 'Retain actual-result followup history'; END IF; END $$;"
    )
    op.execute("DROP TABLE cehub_product.product_result_followups")
    op.execute("DROP FUNCTION cehub_product.guard_product_result_followup()")
    op.execute(
        "ALTER TABLE cehub_product.product_result_feedback DROP CONSTRAINT uq_product_result_feedback_scope"
    )
