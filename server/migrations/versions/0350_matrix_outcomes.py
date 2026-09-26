"""Actual matrix disposition results and scoped publication references."""

# ruff: noqa: E501
from alembic import op

revision = "0350_matrix_outcomes"
down_revision = "0349_matrix_dispositions"
branch_labels = None
depends_on = None
DDL = """

CREATE TABLE cehub_product.product_matrix_outcomes (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	market_space_id UUID NOT NULL, 
	disposition_id UUID NOT NULL, 
	version INTEGER NOT NULL, 
	state VARCHAR(24) NOT NULL, 
	checked_product_ids JSONB NOT NULL, 
	reason TEXT NOT NULL, 
	verification JSONB NOT NULL, 
	source_snapshot JSONB NOT NULL, 
	source_digest VARCHAR(64) NOT NULL, 
	actor_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_product_matrix_outcomes PRIMARY KEY (id), 
	CONSTRAINT uq_matrix_outcome_scope UNIQUE (tenant_id, market_space_id, id), 
	CONSTRAINT uq_matrix_outcome_version UNIQUE (tenant_id, disposition_id, version), 
	CONSTRAINT uq_matrix_outcome_request UNIQUE (tenant_id, actor_user_id, request_id), 
	CONSTRAINT fk_product_matrix_outcomes_tenant_id_product_matrix_dis_7c64 FOREIGN KEY(tenant_id, market_space_id, disposition_id) REFERENCES cehub_product.product_matrix_dispositions (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_product_matrix_outcomes_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT ck_product_matrix_outcomes_shape CHECK (version>0 AND state IN ('progress','verified','not_implemented','withdrawn') AND btrim(reason)<>'' AND jsonb_typeof(checked_product_ids)='array' AND jsonb_array_length(checked_product_ids) BETWEEN 1 AND 8 AND jsonb_typeof(verification)='object' AND jsonb_typeof(source_snapshot)='object' AND source_digest ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$' AND (version>1 OR state<>'withdrawn'))
)

;

CREATE TABLE cehub_product.product_matrix_outcome_versions (
	tenant_id UUID NOT NULL, 
	market_space_id UUID NOT NULL, 
	outcome_id UUID NOT NULL, 
	product_id UUID NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	definition_release_id UUID, 
	roadmap_revision_id UUID, 
	snapshot JSONB NOT NULL, 
	CONSTRAINT pk_product_matrix_outcome_versions PRIMARY KEY (tenant_id, outcome_id, product_id, kind), 
	CONSTRAINT fk_product_matrix_outcome_versions_tenant_id_product_ma_3f5b FOREIGN KEY(tenant_id, market_space_id, outcome_id) REFERENCES cehub_product.product_matrix_outcomes (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_product_matrix_outcome_versions_tenant_id_product_nodes FOREIGN KEY(tenant_id, market_space_id, product_id) REFERENCES cehub_product.product_nodes (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_product_matrix_outcome_versions_tenant_id_definition_8dbf FOREIGN KEY(tenant_id, market_space_id, definition_release_id) REFERENCES cehub_product.definition_releases (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_product_matrix_outcome_versions_tenant_id_product_ro_f8ca FOREIGN KEY(tenant_id, market_space_id, roadmap_revision_id) REFERENCES cehub_product.product_roadmap_revisions (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT ck_product_matrix_outcome_versions_shape CHECK (jsonb_typeof(snapshot)='object' AND ((kind='definition' AND definition_release_id IS NOT NULL AND roadmap_revision_id IS NULL) OR (kind='roadmap' AND roadmap_revision_id IS NOT NULL AND definition_release_id IS NULL)))
)

;
"""
GUARDS = """
CREATE FUNCTION cehub_product.guard_matrix_outcome() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog AS $$
DECLARE original cehub_product.product_matrix_dispositions; last_version integer;
BEGIN
 PERFORM 1 FROM cehub_product.market_spaces WHERE tenant_id=NEW.tenant_id AND id=NEW.market_space_id FOR UPDATE;
 SELECT * INTO original FROM cehub_product.product_matrix_dispositions WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.disposition_id;
 SELECT coalesce(max(version),0) INTO last_version FROM cehub_product.product_matrix_outcomes WHERE tenant_id=NEW.tenant_id AND disposition_id=NEW.disposition_id;
 IF original.id IS NULL OR NEW.version<>last_version+1
  OR (NEW.source_snapshot->'disposition' - 'created_at') IS DISTINCT FROM (to_jsonb(original) - 'created_at')
  OR (NEW.source_snapshot->'disposition'->>'created_at')::timestamptz IS DISTINCT FROM original.created_at
  OR NEW.source_snapshot->>'digest' IS DISTINCT FROM NEW.source_digest
  OR NOT original.product_ids @> NEW.checked_product_ids
  OR jsonb_array_length(NEW.checked_product_ids)<>(SELECT count(DISTINCT v) FROM jsonb_array_elements_text(NEW.checked_product_ids) v)
 THEN RAISE EXCEPTION 'Matrix result requires original disposition, scope and ordered version'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_matrix_outcome BEFORE INSERT ON cehub_product.product_matrix_outcomes
 FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_matrix_outcome();
CREATE FUNCTION cehub_product.guard_matrix_outcome_version() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog AS $$
DECLARE original cehub_product.product_matrix_outcomes;
BEGIN
 SELECT * INTO original FROM cehub_product.product_matrix_outcomes WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.outcome_id;
 IF original.id IS NULL OR NOT original.checked_product_ids @> jsonb_build_array(NEW.product_id::text)
  OR NEW.snapshot->>'product_id' IS DISTINCT FROM NEW.product_id::text
  OR NEW.snapshot->>'kind' IS DISTINCT FROM NEW.kind
  OR NOT original.source_snapshot->'selected_versions' @> jsonb_build_array(NEW.snapshot)
  OR (NEW.kind='definition' AND (NEW.snapshot->>'ref_id' IS DISTINCT FROM NEW.definition_release_id::text OR NOT EXISTS(
    SELECT 1 FROM cehub_product.definition_releases r WHERE r.tenant_id=NEW.tenant_id AND r.market_space_id=NEW.market_space_id AND r.id=NEW.definition_release_id AND r.product_id=NEW.product_id AND r.action='publish')))
  OR (NEW.kind='roadmap' AND (NEW.snapshot->>'ref_id' IS DISTINCT FROM NEW.roadmap_revision_id::text OR NOT EXISTS(
    SELECT 1 FROM cehub_product.product_roadmap_revisions r WHERE r.tenant_id=NEW.tenant_id AND r.market_space_id=NEW.market_space_id AND r.id=NEW.roadmap_revision_id AND r.product_id=NEW.product_id AND r.state='published')))
 THEN RAISE EXCEPTION 'Matrix result version requires its actual product publication'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_matrix_outcome_version BEFORE INSERT ON cehub_product.product_matrix_outcome_versions
 FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_matrix_outcome_version();
CREATE FUNCTION cehub_product.complete_matrix_outcome_versions() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog AS $$
BEGIN
 IF (SELECT count(*) FROM cehub_product.product_matrix_outcome_versions WHERE tenant_id=NEW.tenant_id AND outcome_id=NEW.id)
 <> jsonb_array_length(NEW.source_snapshot->'selected_versions') THEN
  RAISE EXCEPTION 'Matrix result must retain all selected publication references'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER complete_matrix_outcome_versions AFTER INSERT ON cehub_product.product_matrix_outcomes
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cehub_product.complete_matrix_outcome_versions();
CREATE TRIGGER immutable_matrix_outcomes BEFORE UPDATE OR DELETE ON cehub_product.product_matrix_outcomes
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
CREATE TRIGGER immutable_matrix_outcome_versions BEFORE UPDATE OR DELETE ON cehub_product.product_matrix_outcome_versions
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_product.product_matrix_outcomes,cehub_product.product_matrix_outcome_versions FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_product.guard_matrix_outcome(),cehub_product.guard_matrix_outcome_version(),cehub_product.complete_matrix_outcome_versions() FROM PUBLIC;

"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_product.product_matrix_outcomes) THEN RAISE EXCEPTION 'Retain matrix result history'; END IF; END $$;"
    )
    op.execute("DROP TABLE cehub_product.product_matrix_outcome_versions")
    op.execute("DROP TABLE cehub_product.product_matrix_outcomes")
    op.execute(
        "DROP FUNCTION cehub_product.guard_matrix_outcome_version(),cehub_product.guard_matrix_outcome(),cehub_product.complete_matrix_outcome_versions()"
    )
