"""Named internal escalation requests and immutable follow-up receipts."""

# ruff: noqa: E501
from alembic import op

revision = "0343_portfolio_escalations"
down_revision = "0342_portfolio_health_policy"
branch_labels = None
depends_on = None
DDL = """

CREATE TABLE cehub_project.portfolio_escalations (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	source_kind VARCHAR(64) NOT NULL, 
	source_id UUID NOT NULL, 
	source_digest VARCHAR(64) NOT NULL, 
	snapshot JSONB NOT NULL, 
	recipient_user_id UUID NOT NULL, 
	due_date DATE NOT NULL, 
	reason TEXT NOT NULL, 
	requested_outcome TEXT NOT NULL, 
	created_by_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_portfolio_escalations PRIMARY KEY (id), 
	CONSTRAINT uq_portfolio_escalation_scope UNIQUE (tenant_id, project_id, id), 
	CONSTRAINT uq_portfolio_escalation_request UNIQUE (tenant_id, created_by_user_id, request_id), 
	CONSTRAINT fk_portfolio_escalations_tenant_id_projects FOREIGN KEY(tenant_id, project_id) REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_portfolio_escalations_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_portfolio_escalation_recipient FOREIGN KEY(tenant_id, recipient_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT ck_portfolio_escalations_shape CHECK (created_by_user_id<>recipient_user_id AND btrim(reason)<>'' AND btrim(requested_outcome)<>'' AND jsonb_typeof(snapshot)='object' AND source_digest ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$')
)

;
CREATE INDEX ix_portfolio_escalation_recipient ON cehub_project.portfolio_escalations (tenant_id, recipient_user_id, created_at);
CREATE INDEX ix_portfolio_escalation_source ON cehub_project.portfolio_escalations (tenant_id, project_id, source_kind, source_id);

CREATE TABLE cehub_project.portfolio_escalation_replies (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	escalation_id UUID NOT NULL, 
	version INTEGER NOT NULL, 
	action VARCHAR(16) NOT NULL, 
	note TEXT NOT NULL, 
	evidence TEXT, 
	due_date DATE, 
	source_digest VARCHAR(64), 
	created_by_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_portfolio_escalation_replies PRIMARY KEY (id), 
	CONSTRAINT uq_portfolio_escalation_reply_version UNIQUE (tenant_id, escalation_id, version), 
	CONSTRAINT uq_portfolio_escalation_reply_request UNIQUE (tenant_id, created_by_user_id, request_id), 
	CONSTRAINT fk_portfolio_escalation_replies_tenant_id_portfolio_escalations FOREIGN KEY(tenant_id, project_id, escalation_id) REFERENCES cehub_project.portfolio_escalations (tenant_id, project_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_portfolio_escalation_replies_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT ck_portfolio_escalation_replies_shape CHECK (version>0 AND action IN ('accept','update','return','close','withdraw') AND btrim(note)<>'' AND request_digest ~ '^[a-f0-9]{64}$' AND (source_digest IS NULL OR source_digest ~ '^[a-f0-9]{64}$') AND ((action IN ('accept','update') AND due_date IS NOT NULL) OR (action NOT IN ('accept','update') AND due_date IS NULL)) AND (action<>'close' OR (evidence IS NOT NULL AND btrim(evidence)<>'')))
)

;

"""
GUARDS = """

CREATE FUNCTION cehub_project.guard_portfolio_escalation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('portfolio-escalation-source:'||NEW.tenant_id::text||':'||NEW.project_id::text||':'||NEW.source_kind||':'||NEW.source_id::text,0));
 IF NOT (CASE NEW.source_kind
WHEN 'gate_signoff' THEN EXISTS(SELECT 1 FROM cehub_project.gate_signoffs s WHERE s.tenant_id=NEW.tenant_id AND s.project_id=NEW.project_id AND s.id=NEW.source_id)
WHEN 'gate_decision' THEN EXISTS(SELECT 1 FROM cehub_project.gates s WHERE s.tenant_id=NEW.tenant_id AND s.project_id=NEW.project_id AND s.id=NEW.source_id)
WHEN 'gate_condition' THEN EXISTS(SELECT 1 FROM cehub_project.tasks s WHERE s.tenant_id=NEW.tenant_id AND s.project_id=NEW.project_id AND s.id=NEW.source_id)
WHEN 'blocked_task' THEN EXISTS(SELECT 1 FROM cehub_project.tasks s WHERE s.tenant_id=NEW.tenant_id AND s.project_id=NEW.project_id AND s.id=NEW.source_id)
WHEN 'execution_approval' THEN EXISTS(SELECT 1 FROM cehub_project.project_execution_requests s WHERE s.tenant_id=NEW.tenant_id AND s.project_id=NEW.project_id AND s.id=NEW.source_id)
WHEN 'execution_application' THEN EXISTS(SELECT 1 FROM cehub_project.project_execution_requests s WHERE s.tenant_id=NEW.tenant_id AND s.project_id=NEW.project_id AND s.id=NEW.source_id)
WHEN 'baseline_approval' THEN EXISTS(SELECT 1 FROM cehub_project.baseline_change_requests s WHERE s.tenant_id=NEW.tenant_id AND s.project_id=NEW.project_id AND s.id=NEW.source_id)
WHEN 'baseline_application' THEN EXISTS(SELECT 1 FROM cehub_project.baseline_change_requests s WHERE s.tenant_id=NEW.tenant_id AND s.project_id=NEW.project_id AND s.id=NEW.source_id)
WHEN 'discussion_brief' THEN EXISTS(SELECT 1 FROM cehub_ai.agent_runs s WHERE s.tenant_id=NEW.tenant_id AND s.project_id=NEW.project_id AND s.id=NEW.source_id)
WHEN 'decision_followup' THEN EXISTS(SELECT 1 FROM cehub_project.decisions s WHERE s.tenant_id=NEW.tenant_id AND s.project_id=NEW.project_id AND s.id=NEW.source_id)
WHEN 'severe_issue' THEN EXISTS(SELECT 1 FROM cehub_project.issues s WHERE s.tenant_id=NEW.tenant_id AND s.project_id=NEW.project_id AND s.id=NEW.source_id)
WHEN 'risk' THEN EXISTS(SELECT 1 FROM cehub_project.risks s WHERE s.tenant_id=NEW.tenant_id AND s.project_id=NEW.project_id AND s.id=NEW.source_id)
WHEN 'ecr_approval' THEN EXISTS(SELECT 1 FROM cehub_product.engineering_change_requests s WHERE s.tenant_id=NEW.tenant_id AND s.project_id=NEW.project_id AND s.id=NEW.source_id)
WHEN 'ecn_effectivity' THEN EXISTS(SELECT 1 FROM cehub_product.engineering_change_notices s WHERE s.tenant_id=NEW.tenant_id AND s.project_id=NEW.project_id AND s.id=NEW.source_id)
WHEN 'cost_approval' THEN EXISTS(SELECT 1 FROM cehub_cost.cost_freeze_requests s WHERE s.tenant_id=NEW.tenant_id AND s.project_id=NEW.project_id AND s.id=NEW.source_id)
WHEN 'cost_gap' THEN EXISTS(SELECT 1 FROM cehub_cost.cost_gap_observations s WHERE s.tenant_id=NEW.tenant_id AND s.project_id=NEW.project_id AND s.id=NEW.source_id)
WHEN 'id_freeze_product' THEN EXISTS(SELECT 1 FROM cehub_product.id_design_freeze_requests s WHERE s.tenant_id=NEW.tenant_id AND s.project_id=NEW.project_id AND s.id=NEW.source_id)
WHEN 'id_freeze_me' THEN EXISTS(SELECT 1 FROM cehub_product.id_design_freeze_requests s WHERE s.tenant_id=NEW.tenant_id AND s.project_id=NEW.project_id AND s.id=NEW.source_id)
WHEN 'id_freeze_hw' THEN EXISTS(SELECT 1 FROM cehub_product.id_design_freeze_requests s WHERE s.tenant_id=NEW.tenant_id AND s.project_id=NEW.project_id AND s.id=NEW.source_id)
WHEN 'id_freeze_application' THEN EXISTS(SELECT 1 FROM cehub_product.id_design_freeze_requests s WHERE s.tenant_id=NEW.tenant_id AND s.project_id=NEW.project_id AND s.id=NEW.source_id)
WHEN 'cross_predecessor_approval' THEN EXISTS(SELECT 1 FROM cehub_project.cross_project_schedule_proposals s WHERE s.tenant_id=NEW.tenant_id AND s.predecessor_project_id=NEW.project_id AND s.id=NEW.source_id)
WHEN 'cross_successor_approval' THEN EXISTS(SELECT 1 FROM cehub_project.cross_project_schedule_proposals s WHERE s.tenant_id=NEW.tenant_id AND s.successor_project_id=NEW.project_id AND s.id=NEW.source_id)
 ELSE false END) THEN RAISE EXCEPTION 'Escalation requires actual same-project source' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM cehub_project.portfolio_escalations e
 WHERE e.tenant_id=NEW.tenant_id AND e.project_id=NEW.project_id
 AND e.source_kind=NEW.source_kind AND e.source_id=NEW.source_id
 AND COALESCE((SELECT r.action FROM cehub_project.portfolio_escalation_replies r
 WHERE r.tenant_id=e.tenant_id AND r.escalation_id=e.id ORDER BY r.version DESC LIMIT 1),'pending')
 NOT IN ('return','close','withdraw')) THEN
 RAISE EXCEPTION 'An open escalation already exists for this source' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER portfolio_escalation_source BEFORE INSERT ON cehub_project.portfolio_escalations
FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_portfolio_escalation();
CREATE FUNCTION cehub_project.guard_portfolio_escalation_reply() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE original cehub_project.portfolio_escalations%ROWTYPE; prior_state text; prior_version integer;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('portfolio-escalation:'||NEW.escalation_id::text,0));
 SELECT * INTO STRICT original FROM cehub_project.portfolio_escalations
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.escalation_id;
 SELECT action, version INTO prior_state, prior_version FROM cehub_project.portfolio_escalation_replies
 WHERE tenant_id=NEW.tenant_id AND escalation_id=NEW.escalation_id ORDER BY version DESC LIMIT 1;
 prior_state:=COALESCE(prior_state,'pending'); prior_version:=COALESCE(prior_version,0);
 IF NEW.version<>prior_version+1 OR prior_state IN ('return','close','withdraw') THEN
 RAISE EXCEPTION 'Escalation response version or state conflict' USING ERRCODE='23514'; END IF;
 IF NOT ((NEW.action='withdraw' AND NEW.created_by_user_id=original.created_by_user_id)
 OR (NEW.created_by_user_id=original.recipient_user_id AND
 (NEW.action='return' OR (NEW.action='accept' AND prior_state='pending')
 OR (NEW.action IN ('update','close') AND prior_state IN ('accept','update'))))) THEN
 RAISE EXCEPTION 'Escalation response actor or action conflict' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER portfolio_escalation_reply_state BEFORE INSERT ON cehub_project.portfolio_escalation_replies
FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_portfolio_escalation_reply();

"""
TABLES = ("portfolio_escalations", "portfolio_escalation_replies")


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)
    for name in TABLES:
        op.execute(f"REVOKE ALL ON cehub_project.{name} FROM PUBLIC")
        op.execute(
            f"CREATE TRIGGER immutable_{name} BEFORE UPDATE OR DELETE ON cehub_project.{name} FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history()"
        )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_project.portfolio_escalations) THEN RAISE EXCEPTION 'Retain escalation requests and receipts'; END IF; END $$;"
    )
    for name in reversed(TABLES):
        op.execute(f"DROP TABLE cehub_project.{name}")
    op.execute("DROP FUNCTION cehub_project.guard_portfolio_escalation_reply()")
    op.execute("DROP FUNCTION cehub_project.guard_portfolio_escalation()")
