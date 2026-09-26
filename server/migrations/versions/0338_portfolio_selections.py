"""Immutable portfolio selections and source-bound named project consent."""

from alembic import op

revision = "0338_portfolio_selections"
down_revision = "0337_portfolio_comparisons"
branch_labels = None
depends_on = None

TABLES = ("portfolio_selections", "portfolio_selection_projects", "portfolio_selection_decisions")

DDL = """
CREATE TABLE cehub_project.portfolio_selections (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	comparison_id UUID NOT NULL, 
	alternative_key VARCHAR(128) NOT NULL, 
	reason TEXT NOT NULL, 
	inputs JSONB NOT NULL, 
	snapshot JSONB NOT NULL, 
	payload_digest VARCHAR(64) NOT NULL, 
	created_by_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_portfolio_selections PRIMARY KEY (id), 
	CONSTRAINT uq_portfolio_selection_id UNIQUE (tenant_id, id), 
	CONSTRAINT uq_portfolio_selection_choice UNIQUE (tenant_id, comparison_id, alternative_key), 
	CONSTRAINT uq_portfolio_selection_request UNIQUE (tenant_id, created_by_user_id, request_id), 
    CONSTRAINT fk_portfolio_selections_tenant_id_portfolio_comparisons FOREIGN KEY(tenant_id,
comparison_id) REFERENCES cehub_project.portfolio_comparisons (tenant_id, id) ON DELETE
RESTRICT,
    CONSTRAINT fk_portfolio_selections_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_portfolio_selections_shape CHECK (jsonb_typeof(inputs)='object' AND
jsonb_typeof(snapshot)='object' AND payload_digest ~ '^[a-f0-9]{64}$' AND request_digest ~
'^[a-f0-9]{64}$')
);

CREATE INDEX ix_portfolio_selection_history ON cehub_project.portfolio_selections (tenant_id,
created_at, id);

CREATE TABLE cehub_project.portfolio_selection_projects (
	tenant_id UUID NOT NULL, 
	selection_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	policy_id UUID NOT NULL, 
	baseline_id UUID NOT NULL, 
	approver_user_id UUID NOT NULL, 
	snapshot JSONB NOT NULL, 
	CONSTRAINT pk_portfolio_selection_projects PRIMARY KEY (tenant_id, selection_id, project_id), 
    CONSTRAINT fk_portfolio_selection_projects_tenant_id_portfolio_selections FOREIGN
KEY(tenant_id, selection_id) REFERENCES cehub_project.portfolio_selections (tenant_id, id) ON
DELETE RESTRICT,
    CONSTRAINT fk_portfolio_selection_projects_tenant_id_baseline_chan_1eb5 FOREIGN
KEY(tenant_id, project_id, policy_id) REFERENCES cehub_project.baseline_change_policies
(tenant_id, project_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_portfolio_selection_projects_tenant_id_schedule_time_records FOREIGN
KEY(tenant_id, project_id, baseline_id) REFERENCES cehub_project.schedule_time_records
(tenant_id, project_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_portfolio_selection_projects_tenant_id_users FOREIGN KEY(tenant_id,
approver_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT ck_portfolio_selection_projects_shape CHECK (jsonb_typeof(snapshot)='object')
);

CREATE INDEX ix_portfolio_selection_project ON cehub_project.portfolio_selection_projects
(tenant_id, project_id, selection_id);

CREATE TABLE cehub_project.portfolio_selection_decisions (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	selection_id UUID NOT NULL, 
	project_id UUID, 
	action VARCHAR(16) NOT NULL, 
	reason TEXT NOT NULL, 
	payload_digest VARCHAR(64) NOT NULL, 
	actor_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_portfolio_selection_decisions PRIMARY KEY (id), 
	CONSTRAINT uq_portfolio_selection_decision_id UNIQUE (tenant_id, id), 
    CONSTRAINT uq_portfolio_selection_decision_request UNIQUE (tenant_id, actor_user_id,
request_id),
    CONSTRAINT fk_portfolio_selection_decisions_tenant_id_portfolio_selections FOREIGN
KEY(tenant_id, selection_id) REFERENCES cehub_project.portfolio_selections (tenant_id, id) ON
DELETE RESTRICT,
    CONSTRAINT fk_portfolio_selection_decisions_tenant_id_portfolio_se_fc23 FOREIGN
KEY(tenant_id, selection_id, project_id) REFERENCES cehub_project.portfolio_selection_projects
(tenant_id, selection_id, project_id) ON DELETE RESTRICT,
    CONSTRAINT fk_portfolio_selection_decisions_tenant_id_users FOREIGN KEY(tenant_id,
actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_portfolio_selection_decisions_shape CHECK (((action='withdraw' AND project_id
IS NULL) OR (action IN ('approve','reject') AND project_id IS NOT NULL)) AND payload_digest ~
'^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$')
);

CREATE UNIQUE INDEX uq_portfolio_selection_project_decision ON
cehub_project.portfolio_selection_decisions (tenant_id, selection_id, project_id) WHERE
project_id IS NOT NULL;

CREATE UNIQUE INDEX uq_portfolio_selection_withdrawal ON
cehub_project.portfolio_selection_decisions (tenant_id, selection_id) WHERE action='withdraw';
"""

GUARDS = """
CREATE FUNCTION cehub_project.guard_portfolio_selection() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE original cehub_project.portfolio_comparisons%ROWTYPE; chosen jsonb;
BEGIN
 SELECT * INTO original FROM cehub_project.portfolio_comparisons
 WHERE tenant_id=NEW.tenant_id AND id=NEW.comparison_id;
 SELECT a INTO chosen FROM jsonb_array_elements(original.snapshot->'result'->'alternatives') a
 WHERE a->>'key'=NEW.alternative_key;
 IF original.id IS NULL OR chosen IS NULL OR chosen->>'score' IS NULL
 OR jsonb_array_length(chosen->'blockers') IS DISTINCT FROM 0
 OR NEW.inputs->>'request_id' IS DISTINCT FROM NEW.request_id::text
 OR NEW.inputs->>'comparison_id' IS DISTINCT FROM NEW.comparison_id::text
 OR NEW.inputs->>'alternative_key' IS DISTINCT FROM NEW.alternative_key
 OR NEW.inputs->>'reason' IS DISTINCT FROM NEW.reason
 OR NEW.inputs->>'expected_comparison_digest' IS DISTINCT FROM original.payload_digest
 OR NEW.snapshot->'inputs' IS DISTINCT FROM NEW.inputs
 OR NEW.snapshot->>'comparison_digest' IS DISTINCT FROM original.payload_digest
 OR NEW.snapshot->>'alternative_key' IS DISTINCT FROM NEW.alternative_key
 OR NEW.snapshot->>'score' IS DISTINCT FROM chosen->>'score'
 OR NEW.snapshot->>'approval_scope' IS DISTINCT FROM 'portfolio_selection_only'
 OR NEW.snapshot->>'applied' IS DISTINCT FROM 'false'
 OR NEW.snapshot->>'baseline_changed' IS DISTINCT FROM 'false'
 OR NEW.snapshot->>'reservations_changed' IS DISTINCT FROM 'false'
 OR jsonb_array_length(NEW.snapshot->'parts')
 IS DISTINCT FROM jsonb_array_length(original.inputs->'projects')
 THEN RAISE EXCEPTION 'fixed feasible portfolio selection required'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION cehub_project.guard_portfolio_selection_project() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE saved cehub_project.portfolio_selections%ROWTYPE;
 policy cehub_project.baseline_change_policies%ROWTYPE; part jsonb;
 original cehub_project.portfolio_comparisons%ROWTYPE; source jsonb;
BEGIN
 SELECT * INTO saved FROM cehub_project.portfolio_selections
 WHERE tenant_id=NEW.tenant_id AND id=NEW.selection_id;
 SELECT * INTO policy FROM cehub_project.baseline_change_policies
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id ORDER BY version DESC LIMIT 1;
 SELECT p INTO part FROM jsonb_array_elements(saved.snapshot->'parts') p
 WHERE p->>'project_id'=NEW.project_id::text;
 SELECT * INTO original FROM cehub_project.portfolio_comparisons
 WHERE tenant_id=NEW.tenant_id AND id=saved.comparison_id;
 SELECT p INTO source FROM jsonb_array_elements(original.snapshot->'result'->'alternatives') a
 CROSS JOIN LATERAL jsonb_array_elements(a->'projects') p
 WHERE a->>'key'=saved.alternative_key AND p->>'project_id'=NEW.project_id::text;
 IF policy.id IS NULL OR part IS NULL OR source IS NULL
 OR NEW.snapshot IS DISTINCT FROM part
 OR NEW.snapshot->'selected' IS DISTINCT FROM source
 OR NEW.snapshot->'scoring_policy' IS DISTINCT FROM original.snapshot->'policy'
 OR NEW.snapshot->>'policy_id' IS DISTINCT FROM NEW.policy_id::text
 OR NEW.snapshot->>'baseline_id' IS DISTINCT FROM NEW.baseline_id::text
 OR NEW.snapshot->>'approver_user_id' IS DISTINCT FROM NEW.approver_user_id::text
 OR NEW.policy_id IS DISTINCT FROM policy.id
 OR NEW.approver_user_id IS DISTINCT FROM policy.approver_user_id
 OR (policy.four_eyes AND saved.created_by_user_id=NEW.approver_user_id)
 OR NEW.baseline_id IS DISTINCT FROM (SELECT id FROM cehub_project.schedule_time_records
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND time_kind='baseline'
 ORDER BY version DESC LIMIT 1)
 THEN RAISE EXCEPTION 'fixed portfolio project authority and source required'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION cehub_project.require_portfolio_selection_projects() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF (SELECT count(*)::integer FROM cehub_project.portfolio_selection_projects
 WHERE tenant_id=NEW.tenant_id AND selection_id=NEW.id)
 IS DISTINCT FROM jsonb_array_length(NEW.snapshot->'parts')
 THEN RAISE EXCEPTION 'all portfolio project approval scopes required'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION cehub_project.guard_portfolio_selection_decision() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE saved cehub_project.portfolio_selections%ROWTYPE;
 part cehub_project.portfolio_selection_projects%ROWTYPE;
 policy cehub_project.baseline_change_policies%ROWTYPE;
BEGIN
 SELECT * INTO saved FROM cehub_project.portfolio_selections
 WHERE tenant_id=NEW.tenant_id AND id=NEW.selection_id FOR UPDATE;
 IF saved.id IS NULL OR NEW.payload_digest IS DISTINCT FROM saved.payload_digest
 OR EXISTS(SELECT 1 FROM cehub_project.portfolio_selection_decisions
 WHERE tenant_id=NEW.tenant_id AND selection_id=NEW.selection_id
 AND (action IN ('reject','withdraw') OR project_id=NEW.project_id))
 THEN RAISE EXCEPTION 'current undecided portfolio approval required'; END IF;
 IF NEW.action='withdraw' THEN
   IF saved.created_by_user_id IS DISTINCT FROM NEW.actor_user_id
   THEN RAISE EXCEPTION 'only original submitter can withdraw selection'; END IF;
 ELSE
   SELECT * INTO part FROM cehub_project.portfolio_selection_projects
   WHERE tenant_id=NEW.tenant_id AND selection_id=NEW.selection_id
   AND project_id=NEW.project_id;
   SELECT * INTO policy FROM cehub_project.baseline_change_policies
   WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id ORDER BY version DESC LIMIT 1;
   IF part.project_id IS NULL OR policy.id IS NULL OR part.policy_id IS DISTINCT FROM policy.id
   OR policy.approver_user_id IS DISTINCT FROM NEW.actor_user_id
   OR (policy.four_eyes AND saved.created_by_user_id=NEW.actor_user_id)
   OR NOT EXISTS(SELECT 1 FROM cehub_core.users u WHERE u.tenant_id=NEW.tenant_id
   AND u.id=NEW.actor_user_id AND u.is_active
   AND u.role IN ('owner','admin','project_manager','engineer','quality'))
   THEN RAISE EXCEPTION 'current named project approver required'; END IF;
   IF NEW.action='approve' AND part.baseline_id IS DISTINCT FROM
   (SELECT id FROM cehub_project.schedule_time_records WHERE tenant_id=NEW.tenant_id
   AND project_id=NEW.project_id AND time_kind='baseline' ORDER BY version DESC LIMIT 1)
   THEN RAISE EXCEPTION 'portfolio project baseline has changed'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_portfolio_selection BEFORE INSERT
ON cehub_project.portfolio_selections FOR EACH ROW
EXECUTE FUNCTION cehub_project.guard_portfolio_selection();
CREATE TRIGGER guard_portfolio_selection_project BEFORE INSERT
ON cehub_project.portfolio_selection_projects FOR EACH ROW
EXECUTE FUNCTION cehub_project.guard_portfolio_selection_project();
CREATE CONSTRAINT TRIGGER require_portfolio_selection_projects AFTER INSERT
ON cehub_project.portfolio_selections DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION cehub_project.require_portfolio_selection_projects();
CREATE TRIGGER guard_portfolio_selection_decision BEFORE INSERT
ON cehub_project.portfolio_selection_decisions FOR EACH ROW
EXECUTE FUNCTION cehub_project.guard_portfolio_selection_decision();
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
            "THEN RAISE EXCEPTION 'portfolio consent history cannot be discarded'; END IF; END $$"
        )
    for name in reversed(TABLES):
        op.execute(f"DROP TABLE cehub_project.{name}")
    for name in (
        "guard_portfolio_selection_decision",
        "require_portfolio_selection_projects",
        "guard_portfolio_selection_project",
        "guard_portfolio_selection",
    ):
        op.execute(f"DROP FUNCTION cehub_project.{name}()")
