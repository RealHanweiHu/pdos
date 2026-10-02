"""Immutable automatic-draft authorization and latched quality stops."""

# ruff: noqa: E501
from alembic import op

revision = "0382_ai_meeting_direct_writes"
down_revision = "0381_ai_write_trial_protocols"
branch_labels = None
depends_on = None

UP = "ALTER TABLE cehub_ai.ai_meeting_drafts ADD COLUMN write_receipt JSONB;\nALTER TABLE cehub_ai.ai_meeting_drafts DROP CONSTRAINT ck_ai_meeting_drafts_shape;\nALTER TABLE cehub_ai.ai_meeting_drafts ADD CONSTRAINT ck_ai_meeting_drafts_shape CHECK (origin='ai' AND capture_mode IN ('trial','direct') AND draft_kind IN ('minutes','actions','decisions') AND jsonb_typeof(payload)='object' AND jsonb_typeof(source_snapshot)='object' AND (write_receipt IS NULL OR jsonb_typeof(write_receipt)='object') AND (capture_mode='trial' OR (write_receipt IS NOT NULL AND write_receipt->>'route'='direct' AND jsonb_typeof(write_receipt->'sampled')='boolean' AND write_receipt->>'binding_digest' ~ '^[a-f0-9]{64}$') IS TRUE));\n\nCREATE TABLE cehub_ai.ai_write_runtime_stops (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\tpolicy_id UUID NOT NULL, \n\toperation_key VARCHAR(80) NOT NULL, \n\tbinding_digest VARCHAR(64) NOT NULL, \n\treceipt JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_ai_write_runtime_stops PRIMARY KEY (id), \n\tCONSTRAINT fk_ai_write_runtime_stops_tenant_id_projects FOREIGN KEY(tenant_id, project_id) REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_ai_write_runtime_stops_tenant_id_ai_write_policies FOREIGN KEY(tenant_id, policy_id) REFERENCES cehub_ai.ai_write_policies (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_ai_write_runtime_stops_shape CHECK (operation_key IN ('meeting.minutes.draft','meeting.actions.draft','meeting.decisions.draft') AND binding_digest ~ '^[a-f0-9]{64}$' AND jsonb_typeof(receipt)='object'), \n\tCONSTRAINT uq_ai_write_runtime_stop UNIQUE (tenant_id, project_id, policy_id, operation_key, binding_digest)\n)\n\n;\nCREATE TRIGGER immutable_ai_write_runtime_stops BEFORE UPDATE OR DELETE ON cehub_ai.ai_write_runtime_stops FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();\nREVOKE ALL ON cehub_ai.ai_write_runtime_stops FROM PUBLIC;\nDO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pdos_agent') THEN REVOKE ALL ON cehub_ai.ai_write_runtime_stops FROM pdos_agent; END IF; END $$;"

DOWN = "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.ai_write_runtime_stops) OR EXISTS(SELECT 1 FROM cehub_ai.ai_meeting_drafts WHERE write_receipt IS NOT NULL OR capture_mode='direct') THEN RAISE EXCEPTION 'Retain automatic write authorization and stop history'; END IF; END $$;\nDROP TABLE cehub_ai.ai_write_runtime_stops;\nALTER TABLE cehub_ai.ai_meeting_drafts DROP CONSTRAINT ck_ai_meeting_drafts_shape;\nALTER TABLE cehub_ai.ai_meeting_drafts ADD CONSTRAINT ck_ai_meeting_drafts_shape CHECK (origin='ai' AND capture_mode='trial' AND draft_kind IN ('minutes','actions','decisions') AND jsonb_typeof(payload)='object' AND jsonb_typeof(source_snapshot)='object');\nALTER TABLE cehub_ai.ai_meeting_drafts DROP COLUMN write_receipt;"


def upgrade() -> None:
    op.execute(UP)


def downgrade() -> None:
    op.execute(DOWN)
