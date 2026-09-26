"""Fixed portfolio scoring policies and source-bound comparison snapshots."""

from alembic import op

revision = "0337_portfolio_comparisons"
down_revision = "0336_resource_reallocations"
branch_labels = None
depends_on = None

TABLES = (
    "portfolio_scoring_policies",
    "portfolio_comparisons",
    "portfolio_comparison_sources",
)

DDL = """
CREATE TABLE cehub_project.portfolio_scoring_policies (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	version INTEGER NOT NULL, 
	formula_version VARCHAR(64) NOT NULL, 
	body JSONB NOT NULL, 
	created_by_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_portfolio_scoring_policies PRIMARY KEY (id), 
	CONSTRAINT uq_portfolio_policy_id UNIQUE (tenant_id, id), 
	CONSTRAINT uq_portfolio_policy_version UNIQUE (tenant_id, version), 
	CONSTRAINT uq_portfolio_policy_request UNIQUE (tenant_id, created_by_user_id, request_id), 
    CONSTRAINT fk_portfolio_scoring_policies_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_portfolio_scoring_policies_shape CHECK (version>0 AND
jsonb_typeof(body)='object' AND request_digest ~ '^[a-f0-9]{64}$')
);

CREATE TABLE cehub_project.portfolio_comparisons (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	policy_id UUID NOT NULL, 
	title TEXT NOT NULL, 
	inputs JSONB NOT NULL, 
	snapshot JSONB NOT NULL, 
	payload_digest VARCHAR(64) NOT NULL, 
	created_by_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_portfolio_comparisons PRIMARY KEY (id), 
	CONSTRAINT uq_portfolio_comparison_id UNIQUE (tenant_id, id), 
	CONSTRAINT uq_portfolio_comparison_request UNIQUE (tenant_id, created_by_user_id, request_id), 
    CONSTRAINT fk_portfolio_comparisons_tenant_id_portfolio_scoring_policies FOREIGN
KEY(tenant_id, policy_id) REFERENCES cehub_project.portfolio_scoring_policies (tenant_id, id) ON
DELETE RESTRICT,
    CONSTRAINT fk_portfolio_comparisons_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_portfolio_comparisons_shape CHECK (jsonb_typeof(inputs)='object' AND
jsonb_typeof(snapshot)='object' AND payload_digest ~ '^[a-f0-9]{64}$')
);

CREATE INDEX ix_portfolio_comparison_history ON cehub_project.portfolio_comparisons (tenant_id,
created_at, id);

CREATE TABLE cehub_project.portfolio_comparison_sources (
	tenant_id UUID NOT NULL, 
	comparison_id UUID NOT NULL, 
	alternative_key VARCHAR(128) NOT NULL, 
	project_id UUID NOT NULL, 
	schedule_id UUID NOT NULL, 
	cost_rollup_id UUID, 
	evidence_id UUID, 
	calendar_version_id UUID NOT NULL, 
    CONSTRAINT pk_portfolio_comparison_sources PRIMARY KEY (tenant_id, comparison_id,
alternative_key, project_id),
    CONSTRAINT fk_portfolio_comparison_sources_tenant_id_portfolio_comparisons FOREIGN
KEY(tenant_id, comparison_id) REFERENCES cehub_project.portfolio_comparisons (tenant_id, id) ON
DELETE RESTRICT,
    CONSTRAINT fk_portfolio_comparison_sources_tenant_id_project_resou_6058 FOREIGN
KEY(tenant_id, project_id, schedule_id) REFERENCES cehub_project.project_resource_schedules
(tenant_id, project_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_portfolio_comparison_sources_tenant_id_cost_rollups FOREIGN KEY(tenant_id,
project_id, cost_rollup_id) REFERENCES cehub_cost.cost_rollups (tenant_id, project_id, id) ON
DELETE RESTRICT,
    CONSTRAINT fk_portfolio_comparison_sources_tenant_id_documents FOREIGN KEY(tenant_id,
project_id, evidence_id) REFERENCES cehub_project.documents (tenant_id, project_id, id) ON
DELETE RESTRICT,
    CONSTRAINT fk_portfolio_comparison_sources_tenant_id_work_calendar_9d5c FOREIGN
KEY(tenant_id, calendar_version_id) REFERENCES cehub_project.work_calendar_versions (tenant_id,
id) ON DELETE RESTRICT
);
"""

GUARDS = """
CREATE FUNCTION cehub_project.guard_portfolio_policy() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE latest_version integer; weights jsonb;
BEGIN
 PERFORM cehub_project.lock_resource_inventory(NEW.tenant_id);
 SELECT coalesce(max(version),0) INTO latest_version
 FROM cehub_project.portfolio_scoring_policies WHERE tenant_id=NEW.tenant_id;
 weights:=NEW.body->'weights';
 IF NEW.version IS DISTINCT FROM latest_version+1
 OR (NEW.body->>'expected_version')::integer IS DISTINCT FROM latest_version
 OR NEW.formula_version IS DISTINCT FROM 'portfolio.relative_utility.v1'
 OR NEW.body->>'request_id' IS DISTINCT FROM NEW.request_id::text
 OR NEW.body->>'status' IS NULL OR NEW.body->>'status' NOT IN ('active','suspended')
 OR jsonb_typeof(weights) IS DISTINCT FROM 'object'
 OR NOT (weights ?& ARRAY['time','cost','quality','capacity'])
 OR (SELECT sum(value::numeric) FROM jsonb_each_text(weights)) IS DISTINCT FROM 1
 OR EXISTS(SELECT 1 FROM jsonb_each_text(weights)
 WHERE value IS NULL OR value::numeric<0 OR value::numeric>1)
 OR NOT coalesce((NEW.body->>'time_scale_hours')::numeric>0,false)
 OR NOT coalesce((NEW.body->>'cost_scale_amount')::numeric>0,false)
 OR NOT coalesce((NEW.body->>'quality_scale')::numeric>0,false)
 OR NOT coalesce((NEW.body->>'capacity_scale')::numeric>0,false)
 OR NOT coalesce((NEW.body->>'max_source_age_hours')::numeric>0,false)
 OR NOT coalesce((NEW.body->>'max_asof_spread_minutes')::integer>=0,false)
 OR NOT coalesce((NEW.body->>'valid_until')::timestamptz>
 (NEW.body->>'valid_from')::timestamptz,false)
 OR (NEW.body->>'status'='active' AND NOT coalesce(
 (NEW.body->>'valid_from')::timestamptz<=clock_timestamp()
 AND (NEW.body->>'valid_until')::timestamptz>clock_timestamp(),false))
 THEN RAISE EXCEPTION 'explicit current portfolio policy required'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION cehub_project.guard_portfolio_comparison() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE policy cehub_project.portfolio_scoring_policies%ROWTYPE;
BEGIN
 PERFORM cehub_project.lock_resource_inventory(NEW.tenant_id);
 SELECT * INTO policy FROM cehub_project.portfolio_scoring_policies
 WHERE tenant_id=NEW.tenant_id ORDER BY version DESC LIMIT 1;
 IF policy.id IS DISTINCT FROM NEW.policy_id
 OR policy.body->>'status' IS DISTINCT FROM 'active'
 OR NOT coalesce((policy.body->>'valid_from')::timestamptz<=clock_timestamp()
 AND (policy.body->>'valid_until')::timestamptz>clock_timestamp(),false)
 OR NEW.inputs->>'title' IS DISTINCT FROM NEW.title
 OR NEW.inputs->>'request_id' IS DISTINCT FROM NEW.request_id::text
 OR NEW.inputs->>'policy_id' IS DISTINCT FROM NEW.policy_id::text
 OR NEW.snapshot->'inputs' IS DISTINCT FROM NEW.inputs
 OR NEW.snapshot->'policy'->>'id' IS DISTINCT FROM policy.id::text
 OR NEW.snapshot->'policy'->'body' IS DISTINCT FROM policy.body
 OR (NEW.snapshot->'policy'->>'version')::integer IS DISTINCT FROM policy.version
 OR NEW.snapshot->'result'->>'formula_version' IS DISTINCT FROM policy.formula_version
 OR NEW.snapshot->'result'->>'applied' IS DISTINCT FROM 'false'
 OR NEW.snapshot->'result'->>'ready_for_application' IS DISTINCT FROM 'false'
 OR NEW.snapshot->'result'->>'reference_key' IS DISTINCT FROM NEW.inputs->>'reference_key'
 OR jsonb_typeof(NEW.inputs->'projects') IS DISTINCT FROM 'array'
 OR jsonb_typeof(NEW.inputs->'alternatives') IS DISTINCT FROM 'array'
 OR jsonb_array_length(NEW.inputs->'projects') NOT BETWEEN 1 AND 10
 OR jsonb_array_length(NEW.inputs->'alternatives') NOT BETWEEN 2 AND 8
 OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.inputs->'alternatives') a
 WHERE a->>'key'=NEW.inputs->>'reference_key')
 OR jsonb_array_length(NEW.snapshot->'result'->'alternatives')
 IS DISTINCT FROM jsonb_array_length(NEW.inputs->'alternatives')
 THEN RAISE EXCEPTION 'fixed portfolio inputs and current policy required'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION cehub_project.guard_portfolio_source() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE saved cehub_project.portfolio_comparisons%ROWTYPE;
 chosen jsonb; scoped jsonb;
BEGIN
 SELECT * INTO saved FROM cehub_project.portfolio_comparisons
 WHERE tenant_id=NEW.tenant_id AND id=NEW.comparison_id;
 SELECT choice INTO chosen FROM jsonb_array_elements(saved.inputs->'alternatives') a
 CROSS JOIN LATERAL jsonb_array_elements(a->'choices') choice
 WHERE a->>'key'=NEW.alternative_key AND choice->>'project_id'=NEW.project_id::text;
 SELECT p INTO scoped FROM jsonb_array_elements(saved.inputs->'projects') p
 WHERE p->>'project_id'=NEW.project_id::text;
 IF chosen IS NULL OR scoped IS NULL
 OR chosen->>'schedule_id' IS DISTINCT FROM NEW.schedule_id::text
 OR chosen->>'cost_rollup_id' IS DISTINCT FROM NEW.cost_rollup_id::text
 OR chosen->>'evidence_id' IS DISTINCT FROM NEW.evidence_id::text
 OR scoped->>'calendar_version_id' IS DISTINCT FROM NEW.calendar_version_id::text
 THEN RAISE EXCEPTION 'portfolio source must match fixed choice'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION cehub_project.require_portfolio_sources() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE expected integer;
BEGIN
 SELECT sum(jsonb_array_length(a->'choices')) INTO expected
 FROM jsonb_array_elements(NEW.inputs->'alternatives') a;
 IF expected IS DISTINCT FROM
 jsonb_array_length(NEW.inputs->'projects')*jsonb_array_length(NEW.inputs->'alternatives')
 OR expected IS DISTINCT FROM (SELECT count(*)::integer
 FROM cehub_project.portfolio_comparison_sources s
 WHERE s.tenant_id=NEW.tenant_id AND s.comparison_id=NEW.id)
 THEN RAISE EXCEPTION 'complete portfolio source bindings required'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_portfolio_policy BEFORE INSERT
ON cehub_project.portfolio_scoring_policies FOR EACH ROW
EXECUTE FUNCTION cehub_project.guard_portfolio_policy();
CREATE TRIGGER guard_portfolio_comparison BEFORE INSERT
ON cehub_project.portfolio_comparisons FOR EACH ROW
EXECUTE FUNCTION cehub_project.guard_portfolio_comparison();
CREATE TRIGGER guard_portfolio_source BEFORE INSERT
ON cehub_project.portfolio_comparison_sources FOR EACH ROW
EXECUTE FUNCTION cehub_project.guard_portfolio_source();
CREATE CONSTRAINT TRIGGER require_portfolio_sources AFTER INSERT
ON cehub_project.portfolio_comparisons DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION cehub_project.require_portfolio_sources();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)
    for name in TABLES:
        op.execute(f"REVOKE ALL ON cehub_project.{name} FROM PUBLIC")
        op.execute(
            f"CREATE TRIGGER immutable_{name} BEFORE UPDATE OR DELETE "
            f"ON cehub_project.{name} FOR EACH ROW "
            "EXECUTE FUNCTION cehub_ai.protect_checkpoint_history()"
        )


def downgrade() -> None:
    for name in TABLES:
        op.execute(
            f"DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_project.{name}) "
            "THEN RAISE EXCEPTION 'portfolio history cannot be discarded'; END IF; END $$"
        )
    for name in reversed(TABLES):
        op.execute(f"DROP TABLE cehub_project.{name}")
    for name in (
        "require_portfolio_sources",
        "guard_portfolio_source",
        "guard_portfolio_comparison",
        "guard_portfolio_policy",
    ):
        op.execute(f"DROP FUNCTION cehub_project.{name}()")
