"""Named matrix dispositions and actual follow-up work."""

# ruff: noqa: E501
from alembic import op

revision = "0349_matrix_dispositions"
down_revision = "0348_product_matrix_runs"
branch_labels = None
depends_on = None
DDL = """

CREATE TABLE cehub_product.product_matrix_dispositions (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	market_space_id UUID NOT NULL, 
	record_id UUID NOT NULL, 
	series_id UUID NOT NULL, 
	supersedes_id UUID, 
	version INTEGER NOT NULL, 
	topic VARCHAR(32) NOT NULL, 
	product_ids JSONB NOT NULL, 
	criterion_keys JSONB NOT NULL, 
	title TEXT NOT NULL, 
	outcome VARCHAR(32) NOT NULL, 
	reason TEXT NOT NULL, 
	source_snapshot JSONB NOT NULL, 
	source_digest VARCHAR(64) NOT NULL, 
	work_item_id UUID, 
	work_snapshot JSONB, 
	actor_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_product_matrix_dispositions PRIMARY KEY (id), 
	CONSTRAINT uq_matrix_disposition_scope UNIQUE (tenant_id, market_space_id, id), 
	CONSTRAINT uq_matrix_disposition_version UNIQUE (tenant_id, series_id, version), 
	CONSTRAINT uq_matrix_disposition_successor UNIQUE (tenant_id, supersedes_id), 
	CONSTRAINT uq_matrix_disposition_request UNIQUE (tenant_id, actor_user_id, request_id), 
	CONSTRAINT fk_product_matrix_dispositions_tenant_id_product_matrix_records FOREIGN KEY(tenant_id, market_space_id, record_id) REFERENCES cehub_product.product_matrix_records (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_matrix_disposition_series FOREIGN KEY(tenant_id, market_space_id, series_id) REFERENCES cehub_product.product_matrix_dispositions (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_matrix_disposition_previous FOREIGN KEY(tenant_id, market_space_id, supersedes_id) REFERENCES cehub_product.product_matrix_dispositions (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_product_matrix_dispositions_tenant_id_scoped_work_items FOREIGN KEY(tenant_id, market_space_id, work_item_id) REFERENCES cehub_project.scoped_work_items (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_product_matrix_dispositions_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT ck_product_matrix_dispositions_shape CHECK (version>0 AND btrim(title)<>'' AND btrim(reason)<>'' AND topic IN ('coverage_gap','positioning_overlap','platform_reuse') AND outcome IN ('investigate','retain','revise_definition','revise_roadmap','not_applicable','withdrawn') AND jsonb_typeof(product_ids)='array' AND jsonb_array_length(product_ids) BETWEEN 1 AND 8 AND jsonb_typeof(criterion_keys)='array' AND jsonb_array_length(criterion_keys) BETWEEN 1 AND 20 AND jsonb_typeof(source_snapshot)='object' AND source_digest ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$' AND ((work_item_id IS NULL AND work_snapshot IS NULL) OR (work_item_id IS NOT NULL AND jsonb_typeof(work_snapshot)='object')) AND ((version=1 AND series_id=id AND supersedes_id IS NULL AND outcome<>'withdrawn') OR (version>1 AND series_id<>id AND supersedes_id IS NOT NULL)))
)

;
CREATE INDEX ix_matrix_dispositions_history ON cehub_product.product_matrix_dispositions (tenant_id, market_space_id, record_id, created_at, id);
"""
GUARDS = """
CREATE FUNCTION cehub_product.guard_matrix_disposition() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog AS $$
DECLARE original cehub_product.product_matrix_records; prior cehub_product.product_matrix_dispositions;
BEGIN
 PERFORM 1 FROM cehub_product.market_spaces WHERE tenant_id=NEW.tenant_id AND id=NEW.market_space_id FOR UPDATE;
 SELECT * INTO original FROM cehub_product.product_matrix_records WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.record_id;
 IF original.id IS NULL OR NEW.source_snapshot->>'record_id' IS DISTINCT FROM NEW.record_id::text
 OR NEW.source_snapshot->>'result_digest' IS DISTINCT FROM original.result_digest
 OR NEW.source_snapshot->>'digest' IS DISTINCT FROM NEW.source_digest
 OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(NEW.product_ids) p WHERE NOT EXISTS(
 SELECT 1 FROM cehub_product.product_matrix_record_products rp WHERE rp.tenant_id=NEW.tenant_id AND rp.record_id=NEW.record_id AND rp.product_id::text=p))
 OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(NEW.criterion_keys) k WHERE NOT EXISTS(
 SELECT 1 FROM jsonb_array_elements(original.result->'criteria') v WHERE v->'criterion'->>'key'=k))
 OR jsonb_array_length(NEW.product_ids)<>(SELECT count(DISTINCT p) FROM jsonb_array_elements_text(NEW.product_ids) p)
 OR jsonb_array_length(NEW.criterion_keys)<>(SELECT count(DISTINCT k) FROM jsonb_array_elements_text(NEW.criterion_keys) k)
 OR (NEW.topic<>'coverage_gap' AND jsonb_array_length(NEW.product_ids)<2)
 OR (NEW.outcome IN ('investigate','revise_definition','revise_roadmap') AND NEW.work_item_id IS NULL)
 THEN RAISE EXCEPTION 'Matrix disposition requires actual record and selected scope'; END IF;
 IF NEW.supersedes_id IS NOT NULL THEN
  SELECT * INTO prior FROM cehub_product.product_matrix_dispositions WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.supersedes_id;
  IF prior.id IS NULL OR NEW.series_id<>prior.series_id OR NEW.version<>prior.version+1
   OR NEW.created_at<prior.created_at OR NEW.record_id<>prior.record_id OR NEW.topic<>prior.topic
   OR NOT (NEW.product_ids @> prior.product_ids AND prior.product_ids @> NEW.product_ids)
   OR NOT (NEW.criterion_keys @> prior.criterion_keys AND prior.criterion_keys @> NEW.criterion_keys)
   OR (NEW.outcome='withdrawn' AND NEW.work_item_id IS DISTINCT FROM prior.work_item_id)
  THEN RAISE EXCEPTION 'Matrix disposition revision retains original topic'; END IF;
 END IF;
 IF NEW.work_item_id IS NOT NULL AND (NEW.work_snapshot->>'id' IS DISTINCT FROM NEW.work_item_id::text
  OR NEW.work_snapshot->>'market_space_id' IS DISTINCT FROM NEW.market_space_id::text
  OR NEW.work_snapshot->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text) THEN
  RAISE EXCEPTION 'Matrix work receipt retains actual work scope'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_matrix_disposition BEFORE INSERT ON cehub_product.product_matrix_dispositions
 FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_matrix_disposition();
CREATE TRIGGER immutable_matrix_dispositions BEFORE UPDATE OR DELETE ON cehub_product.product_matrix_dispositions
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_product.product_matrix_dispositions FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_product.guard_matrix_disposition() FROM PUBLIC;

"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_product.product_matrix_dispositions) THEN RAISE EXCEPTION 'Retain named matrix dispositions'; END IF; END $$;"
    )
    op.execute("DROP TABLE cehub_product.product_matrix_dispositions")
    op.execute("DROP FUNCTION cehub_product.guard_matrix_disposition()")
