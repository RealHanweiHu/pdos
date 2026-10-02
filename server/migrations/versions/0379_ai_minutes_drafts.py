"""Independent project scope, AI minutes trial drafts and immutable human actions."""

# ruff: noqa: E501
from alembic import op

revision = "0379_ai_minutes_drafts"
down_revision = "0378_ai_write_policies"
branch_labels = None
depends_on = None

DDL = """
CREATE TABLE cehub_ai.ai_write_scope_revisions (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	project_id UUID NOT NULL,
	principal_id UUID NOT NULL,
	operation_key VARCHAR(64) NOT NULL,
	revision INTEGER NOT NULL,
	enabled BOOLEAN NOT NULL,
	actor_user_id UUID NOT NULL,
	request_id UUID NOT NULL,
	request_digest VARCHAR(64) NOT NULL,
	reason VARCHAR(1000) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_ai_write_scope_revisions PRIMARY KEY (id),
	CONSTRAINT fk_ai_write_scope_revisions_tenant_id_projects FOREIGN KEY(tenant_id, project_id) REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_ai_write_scope_revisions_tenant_id_ai_principals FOREIGN KEY(tenant_id, principal_id) REFERENCES cehub_ai.ai_principals (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_ai_write_scope_revisions_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT ck_ai_write_scope_revisions_shape CHECK (operation_key='meeting.minutes.draft' AND revision>0 AND btrim(reason)<>'' AND request_digest ~ '^[a-f0-9]{64}$'),
	CONSTRAINT uq_ai_scope_identity UNIQUE (tenant_id, project_id, id),
	CONSTRAINT uq_ai_scope_revision UNIQUE (tenant_id, project_id, principal_id, operation_key, revision),
	CONSTRAINT uq_ai_scope_request UNIQUE (tenant_id, actor_user_id, request_id)
);
CREATE TABLE cehub_ai.ai_meeting_drafts (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	project_id UUID NOT NULL,
	meeting_id UUID NOT NULL,
	principal_id UUID NOT NULL,
	policy_id UUID NOT NULL,
	scope_revision_id UUID NOT NULL,
	finding_id UUID NOT NULL,
	run_id UUID NOT NULL,
	model_invocation_id UUID NOT NULL,
	requested_by_user_id UUID NOT NULL,
	origin VARCHAR(16) NOT NULL,
	capture_mode VARCHAR(16) NOT NULL,
	payload JSONB NOT NULL,
	source_snapshot JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_ai_meeting_drafts PRIMARY KEY (id),
	CONSTRAINT fk_ai_meeting_drafts_tenant_id_projects FOREIGN KEY(tenant_id, project_id) REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_ai_meeting_drafts_tenant_id_meetings FOREIGN KEY(tenant_id, meeting_id) REFERENCES cehub_project.meetings (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_ai_meeting_drafts_tenant_id_ai_principals FOREIGN KEY(tenant_id, principal_id) REFERENCES cehub_ai.ai_principals (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_ai_meeting_drafts_tenant_id_ai_write_policies FOREIGN KEY(tenant_id, policy_id) REFERENCES cehub_ai.ai_write_policies (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_ai_meeting_drafts_tenant_id_ai_write_scope_revisions FOREIGN KEY(tenant_id, project_id, scope_revision_id) REFERENCES cehub_ai.ai_write_scope_revisions (tenant_id, project_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_ai_meeting_drafts_tenant_id_findings FOREIGN KEY(tenant_id, finding_id) REFERENCES cehub_ai.findings (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_ai_meeting_drafts_tenant_id_agent_runs FOREIGN KEY(tenant_id, run_id) REFERENCES cehub_ai.agent_runs (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_ai_meeting_drafts_tenant_id_model_invocations FOREIGN KEY(tenant_id, model_invocation_id) REFERENCES cehub_ai.model_invocations (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_ai_meeting_drafts_tenant_id_users FOREIGN KEY(tenant_id, requested_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT ck_ai_meeting_drafts_shape CHECK (origin='ai' AND capture_mode='trial' AND jsonb_typeof(payload)='object' AND jsonb_typeof(source_snapshot)='object'),
	CONSTRAINT uq_ai_minutes_draft_scope UNIQUE (tenant_id, project_id, id),
	CONSTRAINT uq_ai_minutes_draft_finding UNIQUE (tenant_id, finding_id)
);
CREATE TABLE cehub_ai.ai_meeting_draft_actions (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	project_id UUID NOT NULL,
	draft_id UUID NOT NULL,
	revision INTEGER NOT NULL,
	action VARCHAR(16) NOT NULL,
	actor_user_id UUID NOT NULL,
	request_id UUID NOT NULL,
	request_digest VARCHAR(64) NOT NULL,
	reason VARCHAR(1000) NOT NULL,
	body TEXT NOT NULL,
	unresolved_points TEXT NOT NULL,
	official_minutes_id UUID,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_ai_meeting_draft_actions PRIMARY KEY (id),
	CONSTRAINT fk_ai_meeting_draft_actions_tenant_id_ai_meeting_drafts FOREIGN KEY(tenant_id, project_id, draft_id) REFERENCES cehub_ai.ai_meeting_drafts (tenant_id, project_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_ai_meeting_draft_actions_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_ai_meeting_draft_actions_tenant_id_meeting_minutes_versions FOREIGN KEY(tenant_id, official_minutes_id) REFERENCES cehub_project.meeting_minutes_versions (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT ck_ai_meeting_draft_actions_shape CHECK (revision>0 AND action IN ('confirm','edit','withdraw','publish') AND btrim(reason)<>'' AND request_digest ~ '^[a-f0-9]{64}$' AND length(body) BETWEEN 1 AND 20000 AND length(unresolved_points) BETWEEN 1 AND 5000 AND ((action='publish' AND official_minutes_id IS NOT NULL) OR (action<>'publish' AND official_minutes_id IS NULL))),
	CONSTRAINT uq_ai_minutes_action_revision UNIQUE (tenant_id, draft_id, revision),
	CONSTRAINT uq_ai_minutes_action_request UNIQUE (tenant_id, actor_user_id, request_id)
);
CREATE INDEX ix_ai_minutes_draft_history ON cehub_ai.ai_meeting_drafts (tenant_id, project_id, meeting_id, created_at, id);
"""


TABLES = ("ai_write_scope_revisions", "ai_meeting_drafts", "ai_meeting_draft_actions")


def upgrade() -> None:
    op.execute(DDL)
    for name in TABLES:
        op.execute(
            f"CREATE TRIGGER immutable_{name} BEFORE UPDATE OR DELETE ON cehub_ai.{name} FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history()"
        )
        op.execute(f"REVOKE ALL ON cehub_ai.{name} FROM PUBLIC")
        op.execute(
            f"DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pdos_agent') THEN REVOKE ALL ON cehub_ai.{name} FROM pdos_agent; END IF; END $$"
        )


def downgrade() -> None:
    for name in TABLES:
        op.execute(
            f"DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.{name}) THEN RAISE EXCEPTION 'Retain AI minutes provenance and scope history'; END IF; END $$"
        )
    for name in reversed(TABLES):
        op.execute(f"DROP TABLE cehub_ai.{name}")
