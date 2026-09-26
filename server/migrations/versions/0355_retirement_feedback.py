"""Named feedback bound to actual product-retirement audits and original definitions."""

# ruff: noqa: E501
from alembic import op

revision = "0355_retirement_feedback"
down_revision = "0354_ncr_result_feedback"
branch_labels = None
depends_on = None
DDL = """

CREATE TABLE cehub_product.retirement_feedback (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	market_space_id UUID NOT NULL, 
	product_id UUID NOT NULL, 
	retirement_audit_id BIGINT NOT NULL, 
	target_id UUID NOT NULL, 
	definition_id UUID, 
	strategy_id UUID, 
	opportunity_id UUID, 
	version INTEGER NOT NULL, 
	verdict VARCHAR(32) NOT NULL, 
	selected_fields JSONB NOT NULL, 
	finding TEXT NOT NULL, 
	follow_up TEXT NOT NULL, 
	limitations TEXT NOT NULL, 
	sources JSONB NOT NULL, 
	source_snapshot JSONB NOT NULL, 
	source_digest VARCHAR(64) NOT NULL, 
	actor_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_retirement_feedback PRIMARY KEY (id), 
	CONSTRAINT uq_retirement_feedback_version UNIQUE (tenant_id, retirement_audit_id, target_id, version), 
	CONSTRAINT uq_retirement_feedback_request UNIQUE (tenant_id, actor_user_id, request_id), 
	CONSTRAINT fk_retirement_feedback_tenant_id_product_nodes FOREIGN KEY(tenant_id, market_space_id, product_id) REFERENCES cehub_product.product_nodes (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_retirement_feedback_tenant_id_product_definitions FOREIGN KEY(tenant_id, market_space_id, definition_id) REFERENCES cehub_product.product_definitions (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_retirement_feedback_tenant_id_product_strategies FOREIGN KEY(tenant_id, market_space_id, strategy_id) REFERENCES cehub_product.product_strategies (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_retirement_feedback_tenant_id_opportunities FOREIGN KEY(tenant_id, market_space_id, opportunity_id) REFERENCES cehub_product.opportunities (tenant_id, market_space_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_retirement_feedback_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT ck_retirement_feedback_shape CHECK (version>0 AND verdict IN ('adopt_for_followup','retain_assumption','needs_evidence','withdrawn') AND btrim(finding)<>'' AND btrim(follow_up)<>'' AND btrim(limitations)<>'' AND jsonb_typeof(selected_fields)='array' AND jsonb_array_length(selected_fields) BETWEEN 1 AND 20 AND jsonb_typeof(sources)='array' AND jsonb_array_length(sources)<=20 AND jsonb_typeof(source_snapshot)='object' AND source_digest ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$' AND (version>1 OR verdict<>'withdrawn') AND ((definition_id IS NULL AND target_id=product_id AND strategy_id IS NULL AND opportunity_id IS NULL) OR (definition_id IS NOT NULL AND target_id=definition_id AND strategy_id IS NOT NULL AND opportunity_id IS NOT NULL))), 
	CONSTRAINT fk_retirement_feedback_retirement_audit_id_audit_log FOREIGN KEY(retirement_audit_id) REFERENCES cehub_audit.audit_log (id) ON DELETE RESTRICT
)

;
CREATE INDEX ix_retirement_feedback_product ON cehub_product.retirement_feedback (tenant_id, market_space_id, product_id, created_at, id);
"""
GUARDS = """
CREATE FUNCTION cehub_product.guard_retirement_feedback() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog AS $$
DECLARE a cehub_audit.audit_log; d cehub_product.product_definitions; s cehub_product.product_strategies; last_version integer;
BEGIN
 PERFORM 1 FROM cehub_product.market_spaces WHERE tenant_id=NEW.tenant_id AND id=NEW.market_space_id FOR UPDATE;
 SELECT * INTO a FROM cehub_audit.audit_log WHERE id=NEW.retirement_audit_id AND tenant_id=NEW.tenant_id;
 SELECT coalesce(max(version),0) INTO last_version FROM cehub_product.retirement_feedback WHERE tenant_id=NEW.tenant_id AND retirement_audit_id=NEW.retirement_audit_id AND target_id=NEW.target_id;
 IF a.id IS NULL OR a.entity_id IS DISTINCT FROM NEW.product_id OR a.project_id IS NOT NULL
 OR a.action<>'product_node.updated' OR a.after_snapshot->>'market_space_id' IS DISTINCT FROM NEW.market_space_id::text
 OR a.before_snapshot->>'lifecycle' IS NULL OR a.before_snapshot->>'lifecycle'='retired'
 OR a.after_snapshot->>'lifecycle' IS DISTINCT FROM 'retired' OR NEW.version<>last_version+1
 OR NEW.source_snapshot->'retirement'->>'audit_id' IS DISTINCT FROM a.id::text
 OR NEW.source_snapshot->'retirement'->'after' IS DISTINCT FROM a.after_snapshot
 OR NEW.source_snapshot->'retirement'->'before' IS DISTINCT FROM a.before_snapshot
 OR NEW.source_snapshot->'retirement'->>'reason' IS DISTINCT FROM a.context->>'reason'
 OR NEW.source_snapshot->'current_product'->>'id' IS DISTINCT FROM NEW.product_id::text
 OR NEW.source_snapshot->>'digest' IS DISTINCT FROM NEW.source_digest
 OR NEW.source_snapshot->>'policy_version' IS DISTINCT FROM 'retirement-learning.v1'
 OR jsonb_typeof(NEW.source_snapshot->'fields') IS DISTINCT FROM 'array'
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.selected_fields) f WHERE NOT NEW.source_snapshot->'fields' @> jsonb_build_array(f))
 OR jsonb_array_length(NEW.selected_fields)<>(SELECT count(DISTINCT f->>'path') FROM jsonb_array_elements(NEW.selected_fields) f)
 THEN RAISE EXCEPTION 'Retirement feedback requires the actual scoped lifecycle audit'; END IF;
 IF NEW.definition_id IS NOT NULL THEN
  SELECT * INTO d FROM cehub_product.product_definitions WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.definition_id;
  SELECT * INTO s FROM cehub_product.product_strategies WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.strategy_id;
  IF d.id IS NULL OR d.product_id<>NEW.product_id OR d.state<>'published' OR d.published_at>a.timestamp
   OR d.strategy_id IS DISTINCT FROM NEW.strategy_id OR s.id IS NULL OR s.opportunity_id IS DISTINCT FROM NEW.opportunity_id
   OR NEW.source_snapshot->'linked_records'->'definition'->>'id' IS DISTINCT FROM d.id::text
   OR NEW.source_snapshot->'linked_records'->'strategy'->>'id' IS DISTINCT FROM s.id::text
   OR NEW.source_snapshot->'linked_records'->'opportunity'->>'id' IS DISTINCT FROM NEW.opportunity_id::text
  THEN RAISE EXCEPTION 'Feedback must follow the original published product-definition chain'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_retirement_feedback BEFORE INSERT ON cehub_product.retirement_feedback
 FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_retirement_feedback();
CREATE TRIGGER immutable_retirement_feedback BEFORE UPDATE OR DELETE ON cehub_product.retirement_feedback
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_product.retirement_feedback FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_product.guard_retirement_feedback() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_product.retirement_feedback) THEN RAISE EXCEPTION 'Retain retirement feedback history'; END IF; END $$;"
    )
    op.execute("DROP TABLE cehub_product.retirement_feedback")
    op.execute("DROP FUNCTION cehub_product.guard_retirement_feedback()")
