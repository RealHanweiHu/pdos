"""Named business milestone designations and immutable history."""

# ruff: noqa: E501
from alembic import op

revision = "0344_milestone_designations"
down_revision = "0343_portfolio_escalations"
branch_labels = None
depends_on = None
DDL = """

CREATE TABLE cehub_project.schedule_milestone_designations (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	node_id UUID NOT NULL, 
	baseline_id UUID NOT NULL, 
	version INTEGER NOT NULL, 
	is_key BOOLEAN NOT NULL, 
	reason TEXT NOT NULL, 
	snapshot JSONB NOT NULL, 
	actor_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_schedule_milestone_designations PRIMARY KEY (id), 
	CONSTRAINT uq_milestone_designation_version UNIQUE (tenant_id, node_id, version), 
	CONSTRAINT uq_milestone_designation_request UNIQUE (tenant_id, actor_user_id, request_id), 
	CONSTRAINT fk_schedule_milestone_designations_tenant_id_schedule_nodes FOREIGN KEY(tenant_id, project_id, node_id) REFERENCES cehub_project.schedule_nodes (tenant_id, project_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_milestone_designation_baseline_node FOREIGN KEY(tenant_id, baseline_id, node_id) REFERENCES cehub_project.schedule_time_nodes (tenant_id, record_id, node_id) ON DELETE RESTRICT, 
	CONSTRAINT fk_milestone_designation_baseline_scope FOREIGN KEY(tenant_id, project_id, baseline_id) REFERENCES cehub_project.schedule_time_records (tenant_id, project_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_schedule_milestone_designations_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT ck_schedule_milestone_designations_shape CHECK (version>0 AND length(btrim(reason))>0 AND jsonb_typeof(snapshot)='object' AND request_digest ~ '^[a-f0-9]{64}$')
)

;
"""
GUARDS = """
CREATE FUNCTION cehub_project.guard_milestone_designation() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous_version integer; previous_time timestamptz;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM cehub_project.schedule_nodes n JOIN cehub_project.schedule_time_records r ON r.tenant_id=n.tenant_id AND r.project_id=n.project_id WHERE n.tenant_id=NEW.tenant_id AND n.project_id=NEW.project_id AND n.id=NEW.node_id AND n.node_kind='milestone' AND r.id=NEW.baseline_id AND r.time_kind='baseline') THEN
  RAISE EXCEPTION 'Designation requires an actual milestone and baseline';
 END IF;
 SELECT version,created_at INTO previous_version,previous_time FROM cehub_project.schedule_milestone_designations WHERE tenant_id=NEW.tenant_id AND node_id=NEW.node_id ORDER BY version DESC LIMIT 1;
 IF NEW.version<>COALESCE(previous_version,0)+1 OR (previous_time IS NOT NULL AND NEW.created_at<previous_time) THEN
  RAISE EXCEPTION 'Designation revisions must be ordered';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_milestone_designation BEFORE INSERT ON cehub_project.schedule_milestone_designations FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_milestone_designation();
CREATE TRIGGER immutable_milestone_designations BEFORE UPDATE OR DELETE ON cehub_project.schedule_milestone_designations FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)
    op.execute("REVOKE ALL ON cehub_project.schedule_milestone_designations FROM PUBLIC")


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_project.schedule_milestone_designations) THEN RAISE EXCEPTION 'Retain milestone designation history'; END IF; END $$;"
    )
    op.execute("DROP TABLE cehub_project.schedule_milestone_designations")
    op.execute("DROP FUNCTION cehub_project.guard_milestone_designation()")
