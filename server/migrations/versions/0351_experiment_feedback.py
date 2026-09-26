"""Versioned named experiment feedback to real related product records."""

# ruff: noqa: E501
from alembic import op

revision = "0351_experiment_feedback"
down_revision = "0350_matrix_outcomes"
branch_labels = None
depends_on = None
DDL = """

CREATE TABLE cehub_product.experiment_feedback (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	market_space_id UUID NOT NULL, 
	experiment_id UUID NOT NULL, 
	target_kind VARCHAR(16) NOT NULL, 
	target_id UUID NOT NULL, 
	opportunity_id UUID, 
	strategy_id UUID, 
	definition_id UUID, 
	version INTEGER NOT NULL, 
	verdict VARCHAR(32) NOT NULL, 
	selected_fields JSONB NOT NULL, 
	reason TEXT NOT NULL, 
	proposed_change TEXT NOT NULL, 
	limitations TEXT NOT NULL, 
	source_snapshot JSONB NOT NULL, 
	source_digest VARCHAR(64) NOT NULL, 
	actor_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_experiment_feedback PRIMARY KEY (id), 
	CONSTRAINT uq_experiment_feedback_version UNIQUE (tenant_id, experiment_id, target_kind, target_id, version), 
	CONSTRAINT uq_experiment_feedback_request UNIQUE (tenant_id, actor_user_id, request_id), 
	CONSTRAINT fk_experiment_feedback_tenant_id_experiments FOREIGN KEY(tenant_id, market_space_id, experiment_id) REFERENCES cehub_product.experiments (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_experiment_feedback_tenant_id_opportunities FOREIGN KEY(tenant_id, market_space_id, opportunity_id) REFERENCES cehub_product.opportunities (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_experiment_feedback_tenant_id_product_strategies FOREIGN KEY(tenant_id, market_space_id, strategy_id) REFERENCES cehub_product.product_strategies (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_experiment_feedback_tenant_id_product_definitions FOREIGN KEY(tenant_id, market_space_id, definition_id) REFERENCES cehub_product.product_definitions (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_experiment_feedback_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT ck_experiment_feedback_shape CHECK (version>0 AND verdict IN ('adopt_for_followup','reject_application','needs_evidence','withdrawn') AND btrim(reason)<>'' AND btrim(proposed_change)<>'' AND btrim(limitations)<>'' AND jsonb_typeof(selected_fields)='array' AND jsonb_array_length(selected_fields) BETWEEN 1 AND 20 AND jsonb_typeof(source_snapshot)='object' AND source_digest ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$' AND (version>1 OR verdict<>'withdrawn') AND ((target_kind='opportunity' AND opportunity_id=target_id AND opportunity_id IS NOT NULL AND strategy_id IS NULL AND definition_id IS NULL) OR (target_kind='strategy' AND strategy_id=target_id AND strategy_id IS NOT NULL AND opportunity_id IS NULL AND definition_id IS NULL) OR (target_kind='definition' AND definition_id=target_id AND definition_id IS NOT NULL AND opportunity_id IS NULL AND strategy_id IS NULL)))
)

;
CREATE INDEX ix_experiment_feedback_target ON cehub_product.experiment_feedback (tenant_id, market_space_id, target_kind, target_id, created_at, id);
"""
GUARDS = """
CREATE FUNCTION cehub_product.guard_experiment_feedback() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog AS $$
DECLARE e cehub_product.experiments; last_version integer;
BEGIN
 PERFORM 1 FROM cehub_product.market_spaces WHERE tenant_id=NEW.tenant_id AND id=NEW.market_space_id FOR UPDATE;
 SELECT * INTO e FROM cehub_product.experiments WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.experiment_id;
 SELECT coalesce(max(version),0) INTO last_version FROM cehub_product.experiment_feedback WHERE tenant_id=NEW.tenant_id AND experiment_id=NEW.experiment_id AND target_kind=NEW.target_kind AND target_id=NEW.target_id;
 IF e.id IS NULL OR e.state<>'concluded' OR e.approval_id IS NULL OR NEW.version<>last_version+1
 OR NEW.source_snapshot->'experiment'->>'id' IS DISTINCT FROM e.id::text
 OR NEW.source_snapshot->'experiment'->>'result' IS DISTINCT FROM e.result
 OR NEW.source_snapshot->'experiment'->>'version' IS DISTINCT FROM e.version::text
 OR NEW.source_snapshot->'approved_plan'->>'id' IS DISTINCT FROM e.approval_id::text
 OR NEW.source_snapshot->>'target_kind' IS DISTINCT FROM NEW.target_kind
 OR NEW.source_snapshot->'target'->>'id' IS DISTINCT FROM NEW.target_id::text
 OR NEW.source_snapshot->'target'->>'market_space_id' IS DISTINCT FROM NEW.market_space_id::text
 OR NEW.source_snapshot->>'digest' IS DISTINCT FROM NEW.source_digest
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.selected_fields) f WHERE NOT NEW.source_snapshot->'fields' @> jsonb_build_array(f))
 OR jsonb_array_length(NEW.selected_fields)<>(SELECT count(DISTINCT f->>'path') FROM jsonb_array_elements(NEW.selected_fields) f)
 THEN RAISE EXCEPTION 'Experiment feedback requires actual result and selected target fields'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_experiment_feedback BEFORE INSERT ON cehub_product.experiment_feedback
 FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_experiment_feedback();
CREATE TRIGGER immutable_experiment_feedback BEFORE UPDATE OR DELETE ON cehub_product.experiment_feedback
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_product.experiment_feedback FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_product.guard_experiment_feedback() FROM PUBLIC;

"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_product.experiment_feedback) THEN RAISE EXCEPTION 'Retain experiment learning history'; END IF; END $$;"
    )
    op.execute("DROP TABLE cehub_product.experiment_feedback")
    op.execute("DROP FUNCTION cehub_product.guard_experiment_feedback()")
