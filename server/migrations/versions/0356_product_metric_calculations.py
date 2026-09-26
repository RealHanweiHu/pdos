"""Immutable measurement mapping, formula, source and result versions."""

# ruff: noqa: E501
from alembic import op

revision = "0356_product_metric_calculations"
down_revision = "0355_retirement_feedback"
branch_labels = None
depends_on = None
DDL = """

CREATE TABLE cehub_product.product_metric_calculations (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	market_space_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	definition_id UUID NOT NULL, 
	test_run_id UUID NOT NULL, 
	version INTEGER NOT NULL, 
	previous_id UUID, 
	formula_version VARCHAR(64) NOT NULL, 
	configuration JSONB NOT NULL, 
	source_snapshot JSONB NOT NULL, 
	source_digest VARCHAR(64) NOT NULL, 
	result JSONB NOT NULL, 
	preview_digest VARCHAR(64) NOT NULL, 
	reason TEXT NOT NULL, 
	actor_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_product_metric_calculations PRIMARY KEY (id), 
	CONSTRAINT uq_product_metric_calculation_version UNIQUE (tenant_id, definition_id, project_id, test_run_id, version), 
	CONSTRAINT uq_product_metric_calculation_request UNIQUE (tenant_id, actor_user_id, request_id), 
	CONSTRAINT uq_product_metric_calculation_scope UNIQUE (tenant_id, market_space_id, id), 
	CONSTRAINT fk_product_metric_calculations_tenant_id_product_metric_e930 FOREIGN KEY(tenant_id, market_space_id, previous_id) REFERENCES cehub_product.product_metric_calculations (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_product_metric_calculations_tenant_id_product_definitions FOREIGN KEY(tenant_id, market_space_id, definition_id) REFERENCES cehub_product.product_definitions (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_product_metric_calculations_tenant_id_test_runs FOREIGN KEY(tenant_id, project_id, test_run_id) REFERENCES cehub_quality.test_runs (tenant_id, project_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_product_metric_calculations_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT ck_product_metric_calculations_shape CHECK (version>0 AND ((version=1 AND previous_id IS NULL) OR (version>1 AND previous_id IS NOT NULL)) AND btrim(reason)<>'' AND btrim(formula_version)<>'' AND jsonb_typeof(configuration)='object' AND jsonb_typeof(source_snapshot)='object' AND jsonb_typeof(result)='object' AND source_digest ~ '^[a-f0-9]{64}$' AND preview_digest ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$')
)

;
CREATE INDEX ix_product_metric_calculation_history ON cehub_product.product_metric_calculations (tenant_id, definition_id, project_id, test_run_id, version);
"""
GUARDS = """
CREATE FUNCTION cehub_product.guard_product_metric_calculation() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog AS $$
DECLARE previous cehub_product.product_metric_calculations; r cehub_quality.test_runs; d cehub_product.product_definitions;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR UPDATE;
 PERFORM 1 FROM cehub_product.market_spaces WHERE tenant_id=NEW.tenant_id AND id=NEW.market_space_id FOR UPDATE;
 SELECT * INTO previous FROM cehub_product.product_metric_calculations WHERE tenant_id=NEW.tenant_id AND definition_id=NEW.definition_id AND project_id=NEW.project_id AND test_run_id=NEW.test_run_id ORDER BY version DESC LIMIT 1;
 SELECT * INTO r FROM cehub_quality.test_runs WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.test_run_id;
 SELECT * INTO d FROM cehub_product.product_definitions WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.definition_id;
 IF NEW.version<>coalesce(previous.version,0)+1 OR NEW.previous_id IS DISTINCT FROM previous.id
 OR r.id IS NULL OR r.draft_state<>'confirmed' OR r.status NOT IN ('passed','failed','aborted')
 OR d.id IS NULL OR d.state<>'published'
 OR NEW.source_snapshot->'definition'->>'id' IS DISTINCT FROM d.id::text
 OR NEW.source_snapshot->'definition'->>'version' IS DISTINCT FROM d.version::text
 OR NEW.source_snapshot->'source'->>'kind' IS DISTINCT FROM 'test_run'
 OR NEW.source_snapshot->'source'->'record'->>'id' IS DISTINCT FROM r.id::text
 OR NEW.source_snapshot->'source'->'record'->>'status' IS DISTINCT FROM r.status
 OR (NEW.source_snapshot->'source'->'record'->>'updated_at')::timestamptz IS DISTINCT FROM r.updated_at
 OR NEW.source_snapshot->>'digest' IS DISTINCT FROM NEW.source_digest
 OR NEW.source_snapshot->>'inheritance_current' IS DISTINCT FROM 'true'
 OR NEW.configuration->>'formula_version' IS DISTINCT FROM NEW.formula_version
 OR NEW.result->>'formula_version' IS DISTINCT FROM NEW.formula_version
 OR jsonb_typeof(NEW.configuration->'mappings') IS DISTINCT FROM 'array'
 OR jsonb_array_length(NEW.configuration->'mappings') NOT BETWEEN 1 AND 20
 OR jsonb_typeof(NEW.result->'items') IS DISTINCT FROM 'array'
 OR jsonb_array_length(NEW.result->'items')<>jsonb_array_length(NEW.configuration->'mappings')
 THEN RAISE EXCEPTION 'Measurement calculations require actual inputs, fixed formula and sequential versions'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_product_metric_calculation BEFORE INSERT ON cehub_product.product_metric_calculations
 FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_product_metric_calculation();
CREATE TRIGGER immutable_product_metric_calculation BEFORE UPDATE OR DELETE ON cehub_product.product_metric_calculations
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_product.product_metric_calculations FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_product.guard_product_metric_calculation() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_product.product_metric_calculations) THEN RAISE EXCEPTION 'Retain measured result calculations'; END IF; END $$;"
    )
    op.execute("DROP TABLE cehub_product.product_metric_calculations")
    op.execute("DROP FUNCTION cehub_product.guard_product_metric_calculation()")
