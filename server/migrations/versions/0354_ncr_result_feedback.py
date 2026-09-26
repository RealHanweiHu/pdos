"""Actual NCR quality-chain feedback to inherited product definitions."""

# ruff: noqa: E501
from alembic import op

revision = "0354_ncr_result_feedback"
down_revision = "0353_quality_learning"
branch_labels = None
depends_on = None

OLD_GUARD = """
CREATE OR REPLACE FUNCTION cehub_product.guard_product_result_feedback() RETURNS trigger LANGUAGE plpgsql
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
"""

NEW_GUARD = """
CREATE OR REPLACE FUNCTION cehub_product.guard_product_result_feedback() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog AS $$
DECLARE source_row jsonb; d cehub_product.product_definitions; last_version integer;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR UPDATE;
 PERFORM 1 FROM cehub_product.market_spaces WHERE tenant_id=NEW.tenant_id AND id=NEW.market_space_id FOR UPDATE;
 SELECT * INTO d FROM cehub_product.product_definitions WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.definition_id;
 IF NEW.source_kind='test_run' THEN
  SELECT to_jsonb(t) INTO source_row FROM cehub_quality.test_runs t WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.test_run_id AND draft_state='confirmed' AND status IN ('passed','failed','aborted');
 ELSIF NEW.source_kind='ncr' THEN
  SELECT to_jsonb(t) INTO source_row FROM cehub_quality.nonconformance_reports t WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.ncr_id;
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
"""

NEW_SHAPE = """ALTER TABLE cehub_product.product_result_feedback ADD CONSTRAINT ck_product_result_feedback_shape CHECK (version>0 AND verdict IN ('adopt_for_followup','reject_application','needs_evidence','withdrawn') AND btrim(finding)<>'' AND btrim(proposed_change)<>'' AND btrim(limitations)<>'' AND btrim(applicability_basis)<>'' AND jsonb_typeof(selected_fields)='array' AND jsonb_array_length(selected_fields) BETWEEN 1 AND 20 AND jsonb_typeof(source_snapshot)='object' AND source_digest ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$' AND (version>1 OR verdict<>'withdrawn') AND ((source_kind='test_run' AND test_run_id=source_id AND test_run_id IS NOT NULL AND complaint_id IS NULL AND ncr_id IS NULL) OR (source_kind='complaint' AND complaint_id=source_id AND complaint_id IS NOT NULL AND test_run_id IS NULL AND ncr_id IS NULL) OR (source_kind='ncr' AND ncr_id=source_id AND ncr_id IS NOT NULL AND complaint_id IS NULL AND test_run_id IS NULL)))"""

NEW_FK = """ALTER TABLE cehub_product.product_result_feedback ADD CONSTRAINT fk_product_result_feedback_ncr FOREIGN KEY(tenant_id, project_id, ncr_id) REFERENCES cehub_quality.nonconformance_reports (tenant_id, project_id, id) ON DELETE RESTRICT"""

OLD_SHAPE = """ALTER TABLE cehub_product.product_result_feedback ADD CONSTRAINT ck_product_result_feedback_shape CHECK (version>0 AND verdict IN ('adopt_for_followup','reject_application','needs_evidence','withdrawn') AND btrim(finding)<>'' AND btrim(proposed_change)<>'' AND btrim(limitations)<>'' AND btrim(applicability_basis)<>'' AND jsonb_typeof(selected_fields)='array' AND jsonb_array_length(selected_fields) BETWEEN 1 AND 20 AND jsonb_typeof(source_snapshot)='object' AND source_digest ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$' AND (version>1 OR verdict<>'withdrawn') AND ((source_kind='test_run' AND test_run_id=source_id AND test_run_id IS NOT NULL AND complaint_id IS NULL) OR (source_kind='complaint' AND complaint_id=source_id AND complaint_id IS NOT NULL AND test_run_id IS NULL)))"""


def upgrade() -> None:
    op.execute("ALTER TABLE cehub_product.product_result_feedback ADD COLUMN ncr_id uuid")
    op.execute(NEW_FK)
    op.execute(
        "ALTER TABLE cehub_product.product_result_feedback DROP CONSTRAINT ck_product_result_feedback_shape"
    )
    op.execute(NEW_SHAPE)
    op.execute(NEW_GUARD)


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_product.product_result_feedback WHERE ncr_id IS NOT NULL) THEN RAISE EXCEPTION 'Retain NCR learning feedback'; END IF; END $$;"
    )
    op.execute(OLD_GUARD)
    op.execute(
        "ALTER TABLE cehub_product.product_result_feedback DROP CONSTRAINT ck_product_result_feedback_shape"
    )
    op.execute(OLD_SHAPE)
    op.execute(
        "ALTER TABLE cehub_product.product_result_feedback DROP CONSTRAINT fk_product_result_feedback_ncr"
    )
    op.execute("ALTER TABLE cehub_product.product_result_feedback DROP COLUMN ncr_id")
