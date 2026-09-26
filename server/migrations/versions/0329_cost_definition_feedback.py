"""Cost feedback and named product definition revision dispositions."""

from alembic import op

revision = "0329_cost_definition_feedback"
down_revision = "0328_cost_alternatives"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_cost.cost_definition_feedback (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        market_space_id UUID NOT NULL,
        definition_id UUID NOT NULL,
        source_kind VARCHAR(32) NOT NULL,
        source_id UUID NOT NULL,
        payload JSONB NOT NULL,
        snapshot JSONB NOT NULL,
        created_by_user_id UUID NOT NULL,
        request_id UUID NOT NULL,
        request_digest VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        CONSTRAINT pk_cost_definition_feedback PRIMARY KEY (id),
        CONSTRAINT uq_cdf_scope UNIQUE (tenant_id, project_id, id),
        CONSTRAINT uq_cdf_request UNIQUE (tenant_id, created_by_user_id, request_id),
        CONSTRAINT ck_cost_definition_feedback_shape CHECK (jsonb_typeof(payload)='object' AND
jsonb_typeof(snapshot)='object' AND request_digest ~ '^[a-f0-9]{64}$'),
        CONSTRAINT uq_cdf_source UNIQUE (tenant_id, project_id, definition_id, source_kind,
source_id),
        CONSTRAINT ck_cost_definition_feedback_source_kind CHECK (source_kind IN
('gap_observation','cost_alternative','cost_backtest')),
        CONSTRAINT fk_cost_definition_feedback_tenant_id_projects FOREIGN KEY(tenant_id, project_id)
REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_cost_definition_feedback_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_cost_definition_feedback_tenant_id_product_definitions FOREIGN KEY(tenant_id,
market_space_id, definition_id) REFERENCES cehub_product.product_definitions (tenant_id,
market_space_id, id) ON DELETE RESTRICT
)

;
CREATE INDEX ix_cdf_history ON cehub_cost.cost_definition_feedback (tenant_id, project_id,
created_at, id);
CREATE INDEX ix_cdf_definition ON cehub_cost.cost_definition_feedback (tenant_id, market_space_id,
definition_id, created_at, id);

CREATE TABLE cehub_cost.cost_definition_dispositions (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        market_space_id UUID NOT NULL,
        feedback_id UUID NOT NULL,
        revision_id UUID,
        version INTEGER NOT NULL,
        action VARCHAR(32) NOT NULL,
        payload JSONB NOT NULL,
        snapshot JSONB NOT NULL,
        created_by_user_id UUID NOT NULL,
        request_id UUID NOT NULL,
        request_digest VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        CONSTRAINT pk_cost_definition_dispositions PRIMARY KEY (id),
        CONSTRAINT uq_cdd_scope UNIQUE (tenant_id, project_id, id),
        CONSTRAINT uq_cdd_request UNIQUE (tenant_id, created_by_user_id, request_id),
        CONSTRAINT ck_cost_definition_dispositions_shape CHECK (jsonb_typeof(payload)='object' AND
jsonb_typeof(snapshot)='object' AND request_digest ~ '^[a-f0-9]{64}$'),
        CONSTRAINT uq_cdd_version UNIQUE (tenant_id, feedback_id, version),
        CONSTRAINT ck_cost_definition_dispositions_action CHECK (version>0 AND action IN
('needs_information','no_change','link_revision') AND ((action='link_revision')=(revision_id IS NOT
NULL))),
        CONSTRAINT fk_cost_definition_dispositions_tenant_id_projects FOREIGN KEY(tenant_id,
project_id) REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_cost_definition_dispositions_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_cost_definition_dispositions_tenant_id_cost_definiti_a25a FOREIGN
KEY(tenant_id, project_id, feedback_id) REFERENCES cehub_cost.cost_definition_feedback (tenant_id,
project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_cost_definition_dispositions_tenant_id_product_definitions FOREIGN
KEY(tenant_id, market_space_id, revision_id) REFERENCES cehub_product.product_definitions
(tenant_id, market_space_id, id) ON DELETE RESTRICT
)

;
CREATE INDEX ix_cdd_history ON cehub_cost.cost_definition_dispositions (tenant_id, project_id,
created_at, id);
"""

GUARD = """
CREATE FUNCTION cehub_cost.guard_cost_definition_feedback() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE target cehub_product.product_definitions; origin jsonb; command jsonb;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id
 FOR UPDATE;
 SELECT * INTO target FROM cehub_product.product_definitions WHERE tenant_id=NEW.tenant_id
 AND market_space_id=NEW.market_space_id AND id=NEW.definition_id;
 IF NEW.source_kind='gap_observation' THEN
  SELECT to_jsonb(o) INTO origin FROM cehub_cost.cost_gap_observations o
  WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.source_id;
 ELSIF NEW.source_kind='cost_alternative' THEN
  SELECT to_jsonb(a) INTO origin FROM cehub_cost.cost_alternatives a
  WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.source_id;
 ELSIF NEW.source_kind='cost_backtest' THEN
  SELECT to_jsonb(b) INTO origin FROM cehub_cost.cost_backtests b
  WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.source_id;
 END IF;
 command:=NEW.payload->'draft';
 IF (origin IS NOT NULL AND target.state='published'
  AND NEW.payload->>'checked'='true' AND command=NEW.snapshot->'command'
  AND command->>'definition_id'=NEW.definition_id::text
  AND command->>'source_kind'=NEW.source_kind AND command->>'source_id'=NEW.source_id::text
  AND NEW.snapshot#>>'{source,kind}'=NEW.source_kind
  AND NEW.snapshot#>>'{source,id}'=NEW.source_id::text
  AND NEW.snapshot#>'{source,record}' @> jsonb_build_object(
   'id',origin->'id','snapshot',origin->'snapshot')
  AND NEW.snapshot#>>'{definition,id}'=target.id::text
  AND NEW.snapshot#>'{definition,content}'=target.content
  AND NEW.snapshot#>'{definition,strategy_ref}'=target.strategy_ref) IS NOT TRUE THEN
  RAISE EXCEPTION 'Feedback requires scoped original costs and actual published definition'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_cost.guard_cost_definition_disposition() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE parent cehub_cost.cost_definition_feedback; prior cehub_cost.cost_definition_dispositions;
 target cehub_product.product_definitions; revision cehub_product.product_definitions; command
jsonb;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id
 FOR UPDATE;
 SELECT * INTO parent FROM cehub_cost.cost_definition_feedback WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND id=NEW.feedback_id;
 SELECT * INTO prior FROM cehub_cost.cost_definition_dispositions WHERE tenant_id=NEW.tenant_id
 AND feedback_id=NEW.feedback_id ORDER BY version DESC LIMIT 1;
 SELECT * INTO target FROM cehub_product.product_definitions WHERE tenant_id=NEW.tenant_id
 AND market_space_id=parent.market_space_id AND id=parent.definition_id;
 command:=NEW.payload->'draft';
 IF (NEW.market_space_id=parent.market_space_id AND NEW.version=coalesce(prior.version,0)+1
  AND command->>'expected_decision_id' IS NOT DISTINCT FROM prior.id::text
  AND command->>'action'=NEW.action AND command->>'revision_id' IS NOT DISTINCT FROM
NEW.revision_id::text
  AND NEW.snapshot->'command'=command AND NEW.payload->>'checked'='true'
  AND NEW.snapshot->>'feedback_id'=parent.id::text
  AND NEW.snapshot->'original_feedback'=parent.snapshot
  AND (NEW.snapshot->>'version')::int=NEW.version
  AND (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(command->'response_by_topic') k)
    =(SELECT array_agg(v ORDER BY v) FROM
jsonb_array_elements_text(parent.payload#>'{draft,topics}') v)
 ) IS NOT TRUE THEN RAISE EXCEPTION 'Disposition must respond to original feedback and latest
decision';
 END IF;
 IF NEW.revision_id IS NOT NULL THEN
  SELECT * INTO revision FROM cehub_product.product_definitions WHERE tenant_id=NEW.tenant_id
  AND market_space_id=NEW.market_space_id AND id=NEW.revision_id FOR SHARE;
  IF (revision.series_id=target.series_id AND revision.revision_number>target.revision_number
   AND NEW.snapshot#>>'{revision,id}'=revision.id::text
   AND NEW.snapshot#>'{revision,content}'=revision.content
   AND NEW.snapshot#>'{revision,strategy_ref}'=revision.strategy_ref
   AND (NEW.snapshot#>>'{revision,version}')::int=revision.version) IS NOT TRUE THEN
   RAISE EXCEPTION 'Disposition requires the actual subsequent definition content'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER cost_definition_feedback_guard BEFORE INSERT ON cehub_cost.cost_definition_feedback
FOR EACH ROW EXECUTE FUNCTION cehub_cost.guard_cost_definition_feedback();
CREATE TRIGGER cost_definition_disposition_guard BEFORE INSERT ON
cehub_cost.cost_definition_dispositions
FOR EACH ROW EXECUTE FUNCTION cehub_cost.guard_cost_definition_disposition();
CREATE TRIGGER cost_definition_feedback_immutable BEFORE UPDATE OR DELETE
ON cehub_cost.cost_definition_feedback FOR EACH ROW
EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
CREATE TRIGGER cost_definition_disposition_immutable BEFORE UPDATE OR DELETE
ON cehub_cost.cost_definition_dispositions FOR EACH ROW
EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_cost.cost_definition_feedback) THEN
      RAISE EXCEPTION 'Retain original cost feedback and product definition dispositions'; END IF;
    END $$;
    DROP TABLE cehub_cost.cost_definition_dispositions;
    DROP TABLE cehub_cost.cost_definition_feedback;
    DROP FUNCTION cehub_cost.guard_cost_definition_disposition();
    DROP FUNCTION cehub_cost.guard_cost_definition_feedback();
    """)
