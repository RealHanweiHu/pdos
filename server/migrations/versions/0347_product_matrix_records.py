"""Immutable market coverage inputs, results and scoped product references."""

# ruff: noqa: E501
from alembic import op

revision = "0347_product_matrix_records"
down_revision = "0346_product_roadmaps"
branch_labels = None
depends_on = None
DDL = """

CREATE TABLE cehub_product.product_matrix_records (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	market_space_id UUID NOT NULL, 
	product_line_id UUID, 
	segment_id UUID NOT NULL, 
	series_id UUID NOT NULL, 
	supersedes_id UUID, 
	version INTEGER NOT NULL, 
	title TEXT NOT NULL, 
	reason TEXT NOT NULL, 
	inputs JSONB NOT NULL, 
	result JSONB NOT NULL, 
	result_digest VARCHAR(64) NOT NULL, 
	formula_version VARCHAR(80) NOT NULL, 
	actor_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_product_matrix_records PRIMARY KEY (id), 
	CONSTRAINT uq_matrix_record_scope UNIQUE (tenant_id, market_space_id, id), 
	CONSTRAINT uq_matrix_record_version UNIQUE (tenant_id, series_id, version), 
	CONSTRAINT uq_matrix_record_successor UNIQUE (tenant_id, supersedes_id), 
	CONSTRAINT uq_matrix_record_request UNIQUE (tenant_id, actor_user_id, request_id), 
	CONSTRAINT fk_product_matrix_records_tenant_id_market_segments FOREIGN KEY(tenant_id, market_space_id, segment_id) REFERENCES cehub_product.market_segments (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_matrix_record_series FOREIGN KEY(tenant_id, market_space_id, series_id) REFERENCES cehub_product.product_matrix_records (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_matrix_record_previous FOREIGN KEY(tenant_id, market_space_id, supersedes_id) REFERENCES cehub_product.product_matrix_records (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_product_matrix_records_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT ck_product_matrix_records_shape CHECK (version>0 AND btrim(title)<>'' AND btrim(reason)<>'' AND jsonb_typeof(inputs)='object' AND jsonb_typeof(result)='object' AND result_digest ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$' AND ((version=1 AND series_id=id AND supersedes_id IS NULL) OR (version>1 AND series_id<>id AND supersedes_id IS NOT NULL)))
)

;

CREATE TABLE cehub_product.product_matrix_record_products (
	tenant_id UUID NOT NULL, 
	market_space_id UUID NOT NULL, 
	record_id UUID NOT NULL, 
	product_id UUID NOT NULL, 
	definition_id UUID NOT NULL, 
	release_id UUID NOT NULL, 
	CONSTRAINT pk_product_matrix_record_products PRIMARY KEY (tenant_id, record_id, product_id), 
	CONSTRAINT fk_product_matrix_record_products_tenant_id_product_mat_76b2 FOREIGN KEY(tenant_id, market_space_id, record_id) REFERENCES cehub_product.product_matrix_records (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_product_matrix_record_products_tenant_id_product_nodes FOREIGN KEY(tenant_id, market_space_id, product_id) REFERENCES cehub_product.product_nodes (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_product_matrix_record_products_tenant_id_product_definitions FOREIGN KEY(tenant_id, market_space_id, definition_id) REFERENCES cehub_product.product_definitions (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_product_matrix_record_products_tenant_id_definition_releases FOREIGN KEY(tenant_id, market_space_id, release_id) REFERENCES cehub_product.definition_releases (tenant_id, market_space_id, id) ON DELETE RESTRICT
)

;
CREATE INDEX ix_matrix_records_history ON cehub_product.product_matrix_records (tenant_id, market_space_id, created_at, id);
"""
GUARDS = """
CREATE FUNCTION cehub_product.guard_matrix_record() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prior cehub_product.product_matrix_records%ROWTYPE;
BEGIN
 PERFORM 1 FROM cehub_product.market_spaces WHERE tenant_id=NEW.tenant_id AND id=NEW.market_space_id FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM cehub_product.market_segments WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.segment_id AND product_line_id IS NOT DISTINCT FROM NEW.product_line_id) THEN
  RAISE EXCEPTION 'Matrix record must retain market source scope';
 END IF;
 IF NEW.supersedes_id IS NOT NULL THEN
  SELECT * INTO prior FROM cehub_product.product_matrix_records WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.supersedes_id;
  IF prior.id IS NULL OR NEW.series_id<>prior.series_id OR NEW.version<>prior.version+1 OR NEW.created_at<prior.created_at THEN RAISE EXCEPTION 'Matrix revisions require the original chain'; END IF;
 END IF;
 IF NEW.inputs->>'segment_id' IS DISTINCT FROM NEW.segment_id::text OR NEW.result->'snapshot'->'segment'->>'id' IS DISTINCT FROM NEW.segment_id::text OR NEW.result->>'result_digest' IS DISTINCT FROM NEW.result_digest OR NEW.result->>'formula_version' IS DISTINCT FROM NEW.formula_version THEN
  RAISE EXCEPTION 'Matrix result does not match fixed input identity';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_matrix_record BEFORE INSERT ON cehub_product.product_matrix_records FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_matrix_record();
CREATE FUNCTION cehub_product.validate_matrix_record_products() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual_count integer; expected_count integer;
BEGIN
 SELECT count(*) INTO actual_count FROM cehub_product.product_matrix_record_products WHERE tenant_id=NEW.tenant_id AND record_id=NEW.id;
 expected_count:=jsonb_array_length(NEW.inputs->'choices');
 IF expected_count NOT BETWEEN 2 AND 8 OR actual_count<>expected_count OR actual_count<>jsonb_array_length(NEW.result->'snapshot'->'products') THEN
  RAISE EXCEPTION 'Matrix product references must be complete';
 END IF;
 IF EXISTS(SELECT 1 FROM cehub_product.product_matrix_record_products p JOIN cehub_product.definition_releases r ON r.tenant_id=p.tenant_id AND r.id=p.release_id WHERE p.tenant_id=NEW.tenant_id AND p.record_id=NEW.id AND (r.product_id<>p.product_id OR r.definition_id<>p.definition_id OR r.action<>'publish' OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.inputs->'choices') x WHERE x->>'product_id'=p.product_id::text AND x->>'release_id'=p.release_id::text) OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.result->'snapshot'->'products') x WHERE x->>'id'=p.product_id::text AND x->>'release_id'=p.release_id::text AND x->>'definition_id'=p.definition_id::text))) THEN
  RAISE EXCEPTION 'Matrix references must match each original product release';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER validate_matrix_record_products AFTER INSERT ON cehub_product.product_matrix_records DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cehub_product.validate_matrix_record_products();
CREATE FUNCTION cehub_product.guard_matrix_record_product() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_product.product_matrix_records r JOIN cehub_product.definition_releases d ON d.tenant_id=r.tenant_id AND d.market_space_id=r.market_space_id WHERE r.tenant_id=NEW.tenant_id AND r.market_space_id=NEW.market_space_id AND r.id=NEW.record_id AND d.id=NEW.release_id AND d.product_id=NEW.product_id AND d.definition_id=NEW.definition_id AND d.action='publish' AND EXISTS(SELECT 1 FROM jsonb_array_elements(r.inputs->'choices') x WHERE x->>'product_id'=NEW.product_id::text AND x->>'release_id'=NEW.release_id::text) AND EXISTS(SELECT 1 FROM jsonb_array_elements(r.result->'snapshot'->'products') x WHERE x->>'id'=NEW.product_id::text AND x->>'definition_id'=NEW.definition_id::text AND x->>'release_id'=NEW.release_id::text)) THEN
  RAISE EXCEPTION 'Cannot append references outside frozen matrix inputs';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_matrix_record_product BEFORE INSERT ON cehub_product.product_matrix_record_products FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_matrix_record_product();
CREATE TRIGGER immutable_matrix_records BEFORE UPDATE OR DELETE ON cehub_product.product_matrix_records FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
CREATE TRIGGER immutable_matrix_record_products BEFORE UPDATE OR DELETE ON cehub_product.product_matrix_record_products FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)
    op.execute(
        "REVOKE ALL ON cehub_product.product_matrix_records, cehub_product.product_matrix_record_products FROM PUBLIC"
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_product.product_matrix_records) THEN RAISE EXCEPTION 'Retain matrix comparison history'; END IF; END $$;"
    )
    op.execute("DROP TABLE cehub_product.product_matrix_record_products")
    op.execute("DROP TABLE cehub_product.product_matrix_records")
    op.execute("DROP FUNCTION cehub_product.validate_matrix_record_products()")
    op.execute("DROP FUNCTION cehub_product.guard_matrix_record()")
    op.execute("DROP FUNCTION cehub_product.guard_matrix_record_product()")
