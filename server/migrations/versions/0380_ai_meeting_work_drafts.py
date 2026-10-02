"""Share immutable meeting draft lifecycle with action and decision content."""

# ruff: noqa: E501
from alembic import op

revision = "0380_ai_meeting_work_drafts"
down_revision = "0379_ai_minutes_drafts"
branch_labels = None
depends_on = None

UP = """
ALTER TABLE cehub_ai.ai_meeting_drafts ADD COLUMN draft_kind VARCHAR(16) NOT NULL DEFAULT 'minutes';
ALTER TABLE cehub_ai.ai_meeting_draft_actions ADD COLUMN published_task_id UUID, ADD COLUMN published_decision_id UUID, ADD COLUMN payload JSONB;
ALTER TABLE cehub_ai.ai_write_scope_revisions DROP CONSTRAINT ck_ai_write_scope_revisions_shape;
ALTER TABLE cehub_ai.ai_write_scope_revisions ADD CONSTRAINT ck_ai_write_scope_revisions_shape CHECK (operation_key IN ('meeting.minutes.draft','meeting.actions.draft','meeting.decisions.draft') AND revision>0 AND btrim(reason)<>'' AND request_digest ~ '^[a-f0-9]{64}$');
ALTER TABLE cehub_ai.ai_meeting_drafts DROP CONSTRAINT ck_ai_meeting_drafts_shape;
ALTER TABLE cehub_ai.ai_meeting_drafts ADD CONSTRAINT ck_ai_meeting_drafts_shape CHECK (origin='ai' AND capture_mode='trial' AND draft_kind IN ('minutes','actions','decisions') AND jsonb_typeof(payload)='object' AND jsonb_typeof(source_snapshot)='object');
ALTER TABLE cehub_ai.ai_meeting_draft_actions DROP CONSTRAINT ck_ai_meeting_draft_actions_shape;
ALTER TABLE cehub_ai.ai_meeting_draft_actions ADD CONSTRAINT ck_ai_meeting_draft_actions_shape CHECK (revision>0 AND action IN ('confirm','edit','withdraw','publish') AND btrim(reason)<>'' AND request_digest ~ '^[a-f0-9]{64}$' AND length(body) BETWEEN 1 AND 20000 AND length(unresolved_points) BETWEEN 1 AND 5000 AND (payload IS NULL OR jsonb_typeof(payload)='object') AND ((action='publish' AND num_nonnulls(official_minutes_id,published_task_id,published_decision_id)=1) OR (action<>'publish' AND num_nonnulls(official_minutes_id,published_task_id,published_decision_id)=0)));
ALTER TABLE cehub_ai.ai_meeting_draft_actions ADD CONSTRAINT fk_ai_meeting_draft_actions_tenant_id_decisions FOREIGN KEY(tenant_id, project_id, published_decision_id) REFERENCES cehub_project.decisions (tenant_id, project_id, id) ON DELETE RESTRICT;
ALTER TABLE cehub_ai.ai_meeting_draft_actions ADD CONSTRAINT fk_ai_meeting_draft_actions_tenant_id_tasks FOREIGN KEY(tenant_id, project_id, published_task_id) REFERENCES cehub_project.tasks (tenant_id, project_id, id) ON DELETE RESTRICT;
"""

DOWN = """
ALTER TABLE cehub_ai.ai_write_scope_revisions DROP CONSTRAINT ck_ai_write_scope_revisions_shape;
ALTER TABLE cehub_ai.ai_write_scope_revisions ADD CONSTRAINT ck_ai_write_scope_revisions_shape CHECK (operation_key='meeting.minutes.draft' AND revision>0 AND btrim(reason)<>'' AND request_digest ~ '^[a-f0-9]{64}$');
ALTER TABLE cehub_ai.ai_meeting_drafts DROP CONSTRAINT ck_ai_meeting_drafts_shape;
ALTER TABLE cehub_ai.ai_meeting_drafts ADD CONSTRAINT ck_ai_meeting_drafts_shape CHECK (origin='ai' AND capture_mode='trial' AND jsonb_typeof(payload)='object' AND jsonb_typeof(source_snapshot)='object');
ALTER TABLE cehub_ai.ai_meeting_draft_actions DROP CONSTRAINT ck_ai_meeting_draft_actions_shape;
ALTER TABLE cehub_ai.ai_meeting_draft_actions ADD CONSTRAINT ck_ai_meeting_draft_actions_shape CHECK (revision>0 AND action IN ('confirm','edit','withdraw','publish') AND btrim(reason)<>'' AND request_digest ~ '^[a-f0-9]{64}$' AND length(body) BETWEEN 1 AND 20000 AND length(unresolved_points) BETWEEN 1 AND 5000 AND ((action='publish' AND official_minutes_id IS NOT NULL) OR (action<>'publish' AND official_minutes_id IS NULL)));
ALTER TABLE cehub_ai.ai_meeting_draft_actions DROP CONSTRAINT fk_ai_meeting_draft_actions_tenant_id_decisions;
ALTER TABLE cehub_ai.ai_meeting_draft_actions DROP CONSTRAINT fk_ai_meeting_draft_actions_tenant_id_tasks;
ALTER TABLE cehub_ai.ai_meeting_draft_actions DROP COLUMN published_task_id, DROP COLUMN published_decision_id, DROP COLUMN payload;
ALTER TABLE cehub_ai.ai_meeting_drafts DROP COLUMN draft_kind;
"""


def upgrade() -> None:
    op.execute(UP)


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.ai_meeting_drafts WHERE draft_kind<>'minutes') OR EXISTS(SELECT 1 FROM cehub_ai.ai_write_scope_revisions WHERE operation_key<>'meeting.minutes.draft') OR EXISTS(SELECT 1 FROM cehub_ai.ai_meeting_draft_actions WHERE payload IS NOT NULL OR published_task_id IS NOT NULL OR published_decision_id IS NOT NULL) THEN RAISE EXCEPTION 'Retain meeting work drafts and scope history'; END IF; END $$"
    )
    op.execute(DOWN)
