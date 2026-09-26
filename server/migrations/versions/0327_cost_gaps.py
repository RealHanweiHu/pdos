"""Actual Issue bindings and immutable scoped cost-gap observations."""

from alembic import op

revision = "0327_cost_gaps"
down_revision = "0326_cost_imports"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_cost.cost_gap_cases (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        rollup_id UUID NOT NULL,
        issue_id UUID NOT NULL,
        bom_id UUID NOT NULL,
        stage VARCHAR(16) NOT NULL,
        subsystem VARCHAR(128) NOT NULL,
        basis VARCHAR(8) NOT NULL,
        scope_key VARCHAR(64) NOT NULL,
        payload JSONB NOT NULL,
        snapshot JSONB NOT NULL,
        created_by_user_id UUID NOT NULL,
        request_id UUID NOT NULL,
        request_digest VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        CONSTRAINT pk_cost_gap_cases PRIMARY KEY (id),
        CONSTRAINT fk_cost_gap_cases_tenant_id_cost_rollups FOREIGN KEY(tenant_id, project_id,
rollup_id) REFERENCES cehub_cost.cost_rollups (tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_cost_gap_cases_tenant_id_issues FOREIGN KEY(tenant_id, project_id,
issue_id) REFERENCES cehub_project.issues (tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_cost_gap_cases_tenant_id_development_boms FOREIGN KEY(tenant_id,
project_id, bom_id) REFERENCES cehub_product.development_boms (tenant_id, project_id, id) ON
DELETE RESTRICT,
        CONSTRAINT fk_cost_gap_cases_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT uq_cost_gap_scope UNIQUE (tenant_id, project_id, id),
        CONSTRAINT uq_cost_gap_key UNIQUE (tenant_id, project_id, scope_key),
        CONSTRAINT uq_cost_gap_request UNIQUE (tenant_id, created_by_user_id, request_id),
        CONSTRAINT ck_cost_gap_cases_shape CHECK (basis IN ('unit','nre') AND stage IN
('estimate','quote','actual') AND btrim(subsystem)<>'' AND scope_key ~ '^[0-9a-f]{64}$' AND
request_digest ~ '^[0-9a-f]{64}$' AND jsonb_typeof(snapshot)='object' AND
jsonb_typeof(payload)='object')
)

;
CREATE INDEX ix_cost_gap_issue ON cehub_cost.cost_gap_cases (tenant_id, project_id, issue_id);
CREATE INDEX ix_cost_gap_rollup_scope ON cehub_cost.cost_gap_cases (tenant_id, project_id,
bom_id, stage);
CREATE INDEX ix_cost_gap_history ON cehub_cost.cost_gap_cases (tenant_id, project_id,
created_at, id);
CREATE TABLE cehub_cost.cost_gap_observations (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        case_id UUID NOT NULL,
        rollup_id UUID NOT NULL,
        version INTEGER NOT NULL,
        state VARCHAR(24) NOT NULL,
        snapshot JSONB NOT NULL,
        created_by_user_id UUID NOT NULL,
        request_id UUID NOT NULL,
        request_digest VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        CONSTRAINT pk_cost_gap_observations PRIMARY KEY (id),
        CONSTRAINT fk_cost_gap_observations_tenant_id_cost_gap_cases FOREIGN KEY(tenant_id,
project_id, case_id) REFERENCES cehub_cost.cost_gap_cases (tenant_id, project_id, id) ON
DELETE RESTRICT,
        CONSTRAINT fk_cost_gap_observations_tenant_id_cost_rollups FOREIGN KEY(tenant_id,
project_id, rollup_id) REFERENCES cehub_cost.cost_rollups (tenant_id, project_id, id) ON
DELETE RESTRICT,
        CONSTRAINT fk_cost_gap_observations_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT uq_cgo_scope UNIQUE (tenant_id, project_id, id),
        CONSTRAINT uq_cgo_rollup UNIQUE (tenant_id, case_id, rollup_id),
        CONSTRAINT uq_cgo_version UNIQUE (tenant_id, case_id, version),
        CONSTRAINT uq_cgo_request UNIQUE (tenant_id, created_by_user_id, request_id),
        CONSTRAINT ck_cost_gap_observations_shape CHECK (version>0 AND state IN
('exceeded','within_target','needs_review') AND request_digest ~ '^[0-9a-f]{64}$' AND
jsonb_typeof(snapshot)='object')
)

;
"""

GUARD = """
CREATE FUNCTION cehub_cost.guard_cost_gap_case() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE calculation cehub_cost.cost_rollups; issue cehub_project.issues; metric jsonb;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id
 FOR UPDATE;
 SELECT * INTO calculation FROM cehub_cost.cost_rollups WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND id=NEW.rollup_id;
 SELECT * INTO issue FROM cehub_project.issues WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND id=NEW.issue_id;
 SELECT v->NEW.basis INTO metric FROM jsonb_array_elements(calculation.result->'comparisons') v
 WHERE v->>'subsystem'=NEW.subsystem;
 IF (NEW.snapshot->>'algorithm'='cost-gap.v1'
  AND NEW.snapshot->'command'=NEW.payload-'request_id'-'expected_digest'
  AND NEW.snapshot#>>'{calculation,id}'=calculation.id::text
  AND NEW.snapshot#>'{calculation,command}'=calculation.command
  AND NEW.snapshot#>'{calculation,result}'=calculation.result
  AND NEW.snapshot#>'{calculation,snapshot}'=calculation.snapshot
  AND NEW.payload->>'expected_calculation_digest'=calculation.calculation_digest
  AND NEW.payload->>'rollup_id'=NEW.rollup_id::text
  AND NEW.payload->>'subsystem'=NEW.subsystem AND NEW.payload->>'basis'=NEW.basis
  AND NEW.snapshot#>>'{source_state,current}'='true'
  AND NEW.snapshot#>'{metric,comparison}'=metric AND (metric->>'gap')::numeric>0
  AND NEW.snapshot#>>'{metric,scope_key}'=NEW.scope_key
  AND NEW.snapshot#>>'{metric,scope,bom_id}'=NEW.bom_id::text
  AND NEW.snapshot#>>'{metric,scope,stage}'=NEW.stage
  AND NEW.bom_id=calculation.bom_id AND calculation.command->>'stage'=NEW.stage
  AND issue.status<>'closed') IS NOT TRUE THEN
  RAISE EXCEPTION 'Cost gap requires the current positive metric and original issue'; END IF;
 IF NEW.payload->>'mode'='create' AND
  (issue.issue_type='engineering' AND issue.title=NEW.payload->>'title'
   AND issue.owner_user_id::text=NEW.payload->>'owner_user_id'
   AND issue.verifier_user_id::text=NEW.payload->>'verifier_user_id'
   AND issue.target_date::text=NEW.payload->>'target_date'
   AND issue.closure_criteria=NEW.payload->>'closure_criteria'
   AND issue.severity=NEW.payload->>'severity'
   AND issue.reported_by_user_id=NEW.created_by_user_id
   AND issue.stage_id::text IS NOT DISTINCT FROM NEW.payload->>'stage_id') IS NOT TRUE THEN
  RAISE EXCEPTION 'Cost gap must retain its actual created issue responsibility and criteria';
 END IF;
 IF NEW.payload->>'mode'='link' AND NEW.payload->>'issue_id' IS DISTINCT FROM NEW.issue_id::text
 THEN RAISE EXCEPTION 'Cost gap must link the selected original issue'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_cost.guard_cost_gap_observation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE parent cehub_cost.cost_gap_cases; calculation cehub_cost.cost_rollups;
 previous cehub_cost.cost_gap_observations; prior_day text; metric jsonb;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id
 FOR UPDATE;
 SELECT * INTO parent FROM cehub_cost.cost_gap_cases WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND id=NEW.case_id;
 SELECT * INTO calculation FROM cehub_cost.cost_rollups WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND id=NEW.rollup_id;
 SELECT * INTO previous FROM cehub_cost.cost_gap_observations WHERE tenant_id=NEW.tenant_id
 AND case_id=NEW.case_id ORDER BY version DESC LIMIT 1;
 SELECT snapshot#>>'{calculation,command,as_of}' INTO prior_day
 FROM cehub_cost.cost_gap_observations WHERE tenant_id=NEW.tenant_id AND case_id=NEW.case_id
 AND state<>'needs_review' ORDER BY version DESC LIMIT 1;
 SELECT v->parent.basis INTO metric FROM jsonb_array_elements(calculation.result->'comparisons') v
 WHERE v->>'subsystem'=parent.subsystem;
 metric:=coalesce(metric,'{"total": null,"target": null,"gap": null}'::jsonb);
 IF (NEW.version=coalesce(previous.version,0)+1
  AND NEW.snapshot->>'algorithm'='cost-gap.v1'
  AND NEW.snapshot#>>'{calculation,id}'=calculation.id::text
  AND NEW.snapshot#>'{calculation,command}'=calculation.command
  AND NEW.snapshot#>'{calculation,result}'=calculation.result
  AND NEW.snapshot#>'{calculation,snapshot}'=calculation.snapshot
  AND NEW.snapshot->'case_scope'=parent.snapshot#>'{metric,scope}'
  AND NEW.snapshot#>>'{assessment,state}'=NEW.state
  AND NEW.snapshot#>'{assessment,metric,comparison}'=metric
  AND NEW.snapshot->>'previous_state' IS NOT DISTINCT FROM previous.state
  AND (NEW.snapshot->>'state_changed')::boolean=(previous.id IS NULL OR NEW.state<>previous.state)
  AND NEW.snapshot->>'mode' IN ('registered','calculation_saved','manual_observation')
  AND btrim(NEW.snapshot->>'reason')<>'') IS NOT TRUE THEN
  RAISE EXCEPTION 'Cost observation must retain its actual metric and ordered predecessor';
 END IF;
 IF NEW.state<>'needs_review' AND
  (NEW.snapshot#>>'{assessment,same_scope}'='true'
   AND NEW.snapshot#>>'{assessment,source_state,current}'='true'
   AND NEW.snapshot#>>'{assessment,metric,scope_key}'=parent.scope_key
   AND NEW.snapshot#>'{assessment,metric,scope}'=parent.snapshot#>'{metric,scope}'
   AND jsonb_array_length(NEW.snapshot#>'{assessment,reasons}')=0
   AND calculation.command->>'as_of'>=
     coalesce(prior_day,parent.snapshot#>>'{calculation,command,as_of}')
   AND ((NEW.state='exceeded' AND (metric->>'gap')::numeric>0)
    OR (NEW.state='within_target' AND (metric->>'gap')::numeric<=0))) IS NOT TRUE THEN
  RAISE EXCEPTION 'Cost recovery requires complete current figures in the same fixed scope';
 END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_cost.require_cost_gap_origin() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_cost.cost_gap_observations WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND case_id=NEW.id AND rollup_id=NEW.rollup_id
 AND version=1 AND state='exceeded') THEN
  RAISE EXCEPTION 'Cost gap and its first exceeded observation must commit together'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER cost_gap_case_guard BEFORE INSERT ON cehub_cost.cost_gap_cases
FOR EACH ROW EXECUTE FUNCTION cehub_cost.guard_cost_gap_case();
CREATE TRIGGER cost_gap_observation_guard BEFORE INSERT ON cehub_cost.cost_gap_observations
FOR EACH ROW EXECUTE FUNCTION cehub_cost.guard_cost_gap_observation();
CREATE CONSTRAINT TRIGGER cost_gap_origin AFTER INSERT ON cehub_cost.cost_gap_cases
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION cehub_cost.require_cost_gap_origin();
CREATE TRIGGER cost_gap_case_immutable BEFORE UPDATE OR DELETE ON cehub_cost.cost_gap_cases
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
CREATE TRIGGER cost_gap_observation_immutable BEFORE UPDATE OR DELETE
ON cehub_cost.cost_gap_observations FOR EACH ROW
EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
REVOKE ALL ON cehub_cost.cost_gap_cases, cehub_cost.cost_gap_observations FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_cost.guard_cost_gap_case(),
cehub_cost.guard_cost_gap_observation(), cehub_cost.require_cost_gap_origin() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
     IF EXISTS(SELECT 1 FROM cehub_cost.cost_gap_cases) THEN
      RAISE EXCEPTION 'Retain cost gap issues and cost recovery observations'; END IF;
    END $$;
    DROP TABLE cehub_cost.cost_gap_observations;
    DROP TABLE cehub_cost.cost_gap_cases;
    DROP FUNCTION cehub_cost.require_cost_gap_origin();
    DROP FUNCTION cehub_cost.guard_cost_gap_observation();
    DROP FUNCTION cehub_cost.guard_cost_gap_case();
    """)
