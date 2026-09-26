"""Named actual test and service learning against inherited definitions."""

# ruff: noqa: E501
from alembic import op

revision = "0352_product_result_feedback"
down_revision = "0351_experiment_feedback"
branch_labels = None
depends_on = None
DDL = """

CREATE TABLE cehub_product.product_result_feedback (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	market_space_id UUID NOT NULL, 
	definition_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	source_kind VARCHAR(16) NOT NULL, 
	source_id UUID NOT NULL, 
	test_run_id UUID, 
	complaint_id UUID, 
	version INTEGER NOT NULL, 
	verdict VARCHAR(32) NOT NULL, 
	selected_fields JSONB NOT NULL, 
	finding TEXT NOT NULL, 
	proposed_change TEXT NOT NULL, 
	limitations TEXT NOT NULL, 
	applicability_basis TEXT NOT NULL, 
	source_snapshot JSONB NOT NULL, 
	source_digest VARCHAR(64) NOT NULL, 
	actor_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_product_result_feedback PRIMARY KEY (id), 
	CONSTRAINT uq_product_result_feedback_version UNIQUE (tenant_id, definition_id, project_id, source_kind, source_id, version), 
	CONSTRAINT uq_product_result_feedback_request UNIQUE (tenant_id, actor_user_id, request_id), 
	CONSTRAINT fk_product_result_feedback_tenant_id_product_definitions FOREIGN KEY(tenant_id, market_space_id, definition_id) REFERENCES cehub_product.product_definitions (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_product_result_feedback_tenant_id_test_runs FOREIGN KEY(tenant_id, project_id, test_run_id) REFERENCES cehub_quality.test_runs (tenant_id, project_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_product_result_feedback_tenant_id_complaints FOREIGN KEY(tenant_id, complaint_id) REFERENCES cehub_quality.complaints (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_product_result_feedback_tenant_id_projects FOREIGN KEY(tenant_id, project_id) REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_product_result_feedback_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT ck_product_result_feedback_shape CHECK (version>0 AND verdict IN ('adopt_for_followup','reject_application','needs_evidence','withdrawn') AND btrim(finding)<>'' AND btrim(proposed_change)<>'' AND btrim(limitations)<>'' AND btrim(applicability_basis)<>'' AND jsonb_typeof(selected_fields)='array' AND jsonb_array_length(selected_fields) BETWEEN 1 AND 20 AND jsonb_typeof(source_snapshot)='object' AND source_digest ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$' AND (version>1 OR verdict<>'withdrawn') AND ((source_kind='test_run' AND test_run_id=source_id AND test_run_id IS NOT NULL AND complaint_id IS NULL) OR (source_kind='complaint' AND complaint_id=source_id AND complaint_id IS NOT NULL AND test_run_id IS NULL)))
)

;
CREATE INDEX ix_product_result_feedback_definition ON cehub_product.product_result_feedback (tenant_id, market_space_id, definition_id, created_at, id);
"""
GUARDS = """
CREATE FUNCTION cehub_product.guard_product_result_feedback() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog AS $$
DECLARE source_row jsonb; d cehub_product.product_definitions; last_version integer;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR UPDATE;
 PERFORM 1 FROM cehub_product.market_spaces WHERE tenant_id=NEW.tenant_id AND id=NEW.market_space_id FOR UPDATE;
 SELECT * INTO d FROM cehub_product.product_definitions WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.definition_id;
 IF NEW.source_kind='test_run' THEN
  SELECT to_jsonb(t) INTO source_row FROM cehub_quality.test_runs t WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.test_run_id AND draft_state='confirmed' AND status IN ('passed','failed','aborted');
 ELSE
  SELECT to_jsonb(t) INTO source_row FROM cehub_quality.complaints t WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.complaint_id;
 END IF;
 SELECT coalesce(max(version),0) INTO last_version FROM cehub_product.product_result_feedback WHERE tenant_id=NEW.tenant_id AND definition_id=NEW.definition_id AND project_id=NEW.project_id AND source_kind=NEW.source_kind AND source_id=NEW.source_id;
 IF source_row IS NULL OR d.id IS NULL OR d.state<>'published' OR NEW.version<>last_version+1
 OR NEW.source_snapshot->'definition'->>'id' IS DISTINCT FROM d.id::text
 OR NEW.source_snapshot->'definition'->>'version' IS DISTINCT FROM d.version::text
 OR NEW.source_snapshot->'source'->>'kind' IS DISTINCT FROM NEW.source_kind
 OR NEW.source_snapshot->'source'->'record'->>'id' IS DISTINCT FROM NEW.source_id::text
 OR NEW.source_snapshot->'source'->'record'->>'project_id' IS DISTINCT FROM NEW.project_id::text
 OR NEW.source_snapshot->'source'->'record'->>'status' IS DISTINCT FROM source_row->>'status'
 OR (NEW.source_snapshot->'source'->'record'->>'updated_at')::timestamptz IS DISTINCT FROM (source_row->>'updated_at')::timestamptz
 OR NEW.source_snapshot->>'digest' IS DISTINCT FROM NEW.source_digest
 OR NEW.source_snapshot->>'policy_version' IS DISTINCT FROM 'product-result-learning.v1'
 OR NEW.source_snapshot->>'inheritance_current' IS DISTINCT FROM 'true'
 OR jsonb_typeof(NEW.source_snapshot->'fields') IS DISTINCT FROM 'array'
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.selected_fields) f WHERE NOT NEW.source_snapshot->'fields' @> jsonb_build_array(f))
 OR jsonb_array_length(NEW.selected_fields)<>(SELECT count(DISTINCT f->>'path') FROM jsonb_array_elements(NEW.selected_fields) f)
 THEN RAISE EXCEPTION 'Feedback must preserve the actual scoped result and definition fields'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_product_result_feedback BEFORE INSERT ON cehub_product.product_result_feedback
 FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_product_result_feedback();
CREATE TRIGGER immutable_product_result_feedback BEFORE UPDATE OR DELETE ON cehub_product.product_result_feedback
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_product.product_result_feedback FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_product.guard_product_result_feedback() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_product.product_result_feedback) THEN RAISE EXCEPTION 'Retain actual result feedback history'; END IF; END $$;"
    )
    op.execute("DROP TABLE cehub_product.product_result_feedback")
    op.execute("DROP FUNCTION cehub_product.guard_product_result_feedback()")
