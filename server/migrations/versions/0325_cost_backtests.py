"""Retain source-bound frozen-versus-actual cost comparisons."""

from alembic import op

revision = "0325_cost_backtests"
down_revision = "0324_cost_freezes"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_cost.cost_backtests (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        freeze_id UUID NOT NULL,
        actual_rollup_id UUID NOT NULL,
        evidence_id UUID NOT NULL,
        algorithm VARCHAR(64) NOT NULL,
        title VARCHAR(256) NOT NULL,
        purpose VARCHAR(32) NOT NULL,
        payload JSONB NOT NULL,
        snapshot JSONB NOT NULL,
        result JSONB NOT NULL,
        comparison_digest VARCHAR(64) NOT NULL,
        created_by_user_id UUID NOT NULL,
        request_id UUID NOT NULL,
        request_digest VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        CONSTRAINT pk_cost_backtests PRIMARY KEY (id),
        CONSTRAINT fk_cost_backtests_tenant_id_cost_freezes FOREIGN KEY(tenant_id, project_id,
freeze_id) REFERENCES cehub_cost.cost_freezes (tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_cost_backtests_tenant_id_cost_rollups FOREIGN KEY(tenant_id, project_id,
actual_rollup_id) REFERENCES cehub_cost.cost_rollups (tenant_id, project_id, id) ON DELETE
RESTRICT,
        CONSTRAINT fk_cost_backtests_tenant_id_documents FOREIGN KEY(tenant_id, project_id,
evidence_id) REFERENCES cehub_project.documents (tenant_id, project_id, id) ON DELETE
RESTRICT,
        CONSTRAINT fk_cost_backtests_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT uq_cost_backtest_scope UNIQUE (tenant_id, project_id, id),
        CONSTRAINT uq_cost_backtest_request UNIQUE (tenant_id, created_by_user_id,
request_id),
        CONSTRAINT ck_cost_backtests_shape CHECK (btrim(title)<>'' AND purpose IN
('historical_snapshot','production_actual') AND jsonb_typeof(snapshot)='object' AND
jsonb_typeof(result)='object' AND jsonb_typeof(payload)='object'),
        CONSTRAINT ck_cost_backtests_digests CHECK (comparison_digest ~ '^[0-9a-f]{64}$' AND
request_digest ~ '^[0-9a-f]{64}$')
)

;
CREATE INDEX ix_cost_backtests_history ON cehub_cost.cost_backtests (tenant_id, project_id,
created_at, id);
"""

GUARD = """
CREATE FUNCTION cehub_cost.guard_cost_backtest() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE frozen cehub_cost.cost_freezes; actual cehub_cost.cost_rollups;
 item jsonb; original jsonb; observed jsonb; selected jsonb;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id
 FOR UPDATE;
 SELECT * INTO frozen FROM cehub_cost.cost_freezes WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND id=NEW.freeze_id;
 SELECT * INTO actual FROM cehub_cost.cost_rollups WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND id=NEW.actual_rollup_id;
 IF (NEW.algorithm='cost-backtest.v1' AND NEW.snapshot->>'algorithm'=NEW.algorithm
  AND NEW.result->>'algorithm'=NEW.algorithm AND NEW.snapshot->'result'=NEW.result
  AND actual.command->>'stage'='actual' AND actual.result->>'complete'='true'
  AND NEW.snapshot#>>'{freeze,id}'=frozen.id::text
  AND NEW.snapshot#>>'{freeze,version}'=frozen.version::text
  AND NEW.snapshot->'frozen_calculation'=frozen.snapshot->'calculation'
  AND NEW.snapshot#>>'{actual_calculation,id}'=actual.id::text
  AND NEW.snapshot#>'{actual_calculation,command}'=actual.command
  AND NEW.snapshot#>'{actual_calculation,snapshot}'=actual.snapshot
  AND NEW.snapshot#>'{actual_calculation,result}'=actual.result
  AND NEW.snapshot#>>'{actual_calculation,calculation_digest}'=actual.calculation_digest
  AND NEW.snapshot->>'digest'=NEW.comparison_digest
  AND NEW.snapshot#>>'{reviewer,id}'=NEW.created_by_user_id::text
  AND NEW.snapshot#>>'{evidence,id}'=NEW.evidence_id::text
  AND NEW.payload->>'evidence_checked'='true' AND NEW.payload->>'scope_checked'='true'
  AND NEW.payload->>'quantity_checked'='true'
  AND NEW.payload->'draft'=NEW.snapshot->'command'
  AND NEW.snapshot#>>'{command,title}'=NEW.title
  AND NEW.snapshot#>>'{command,purpose}'=NEW.purpose
  AND NEW.snapshot#>>'{command,freeze_id}'=NEW.freeze_id::text
  AND NEW.snapshot#>>'{command,actual_rollup_id}'=NEW.actual_rollup_id::text
  AND NEW.snapshot#>>'{command,evidence_id}'=NEW.evidence_id::text
  AND NEW.snapshot#>>'{command,expected_calculation_digest}'=actual.calculation_digest
  AND (NEW.purpose='historical_snapshot'
       OR NEW.snapshot#>>'{actual_source_state,current}'='true')) IS NOT TRUE THEN
  RAISE EXCEPTION 'Cost backtest requires its actual fixed sources and human reconciliation';
 END IF;
 IF jsonb_array_length(NEW.result->'pairs')<1 OR
  jsonb_array_length(NEW.result->'pairs')<>
    jsonb_array_length(NEW.snapshot#>'{command,pairs}') OR EXISTS(
   SELECT 1 FROM jsonb_array_elements(NEW.result->'pairs') p
   GROUP BY p->>'frozen_input_id' HAVING count(*)>1) OR EXISTS(
   SELECT 1 FROM jsonb_array_elements(NEW.result->'pairs') p
   GROUP BY p->>'actual_input_id' HAVING count(*)>1) THEN
  RAISE EXCEPTION 'Cost comparison requires unique explicitly reconciled pairs'; END IF;
 FOR item IN SELECT * FROM jsonb_array_elements(NEW.result->'pairs') LOOP
  SELECT v INTO original FROM jsonb_array_elements(
   frozen.snapshot#>'{calculation,result,lines}') v
   WHERE v->>'input_id'=item->>'frozen_input_id';
  SELECT v INTO observed FROM jsonb_array_elements(actual.result->'lines') v
   WHERE v->>'input_id'=item->>'actual_input_id';
  SELECT v INTO selected FROM jsonb_array_elements(NEW.snapshot#>'{command,pairs}') v
   WHERE v->>'frozen_input_id'=item->>'frozen_input_id';
  IF (item->'frozen'=original AND item->'actual'=observed
   AND selected->>'actual_input_id'=item->>'actual_input_id'
   AND selected->>'correspondence_basis'=item->>'correspondence_basis'
   AND btrim(item->>'correspondence_basis')<>'') IS NOT TRUE THEN
   RAISE EXCEPTION 'Cost comparison must retain each original fee and correspondence'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER cost_backtest_guard BEFORE INSERT ON cehub_cost.cost_backtests
FOR EACH ROW EXECUTE FUNCTION cehub_cost.guard_cost_backtest();
CREATE TRIGGER cost_backtest_immutable BEFORE UPDATE OR DELETE ON cehub_cost.cost_backtests
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
REVOKE ALL ON cehub_cost.cost_backtests FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_cost.guard_cost_backtest() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
     IF EXISTS(SELECT 1 FROM cehub_cost.cost_backtests) THEN
      RAISE EXCEPTION 'Retain actual cost reconciliation and comparison history'; END IF;
    END $$;
    DROP TABLE cehub_cost.cost_backtests;
    DROP FUNCTION cehub_cost.guard_cost_backtest();
    """)
