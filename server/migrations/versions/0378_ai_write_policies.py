"""DC-11 independent AI principal and immutable tenant policy revisions."""

# ruff: noqa: E501
from alembic import op

revision = "0378_ai_write_policies"
down_revision = "0377_issue_evidence_tool"
branch_labels = None
depends_on = None

DDL = """
CREATE TABLE cehub_ai.ai_principals (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	principal_key VARCHAR(64) NOT NULL,
	display_name VARCHAR(128) NOT NULL,
	principal_kind VARCHAR(16) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_ai_principals PRIMARY KEY (id),
	CONSTRAINT ck_ai_principals_identity CHECK (principal_kind='ai' AND principal_key='pdos-agent' AND display_name='PDOS Agent'),
	CONSTRAINT uq_ai_principal_scope UNIQUE (tenant_id, id),
	CONSTRAINT uq_ai_principal_key UNIQUE (tenant_id, principal_key),
	CONSTRAINT fk_ai_principals_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES cehub_core.tenants (id) ON DELETE RESTRICT
);
CREATE TABLE cehub_ai.ai_write_policies (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	principal_id UUID NOT NULL,
	revision INTEGER NOT NULL,
	mode VARCHAR(16) NOT NULL,
	contract_version VARCHAR(64) NOT NULL,
	operation_settings JSONB NOT NULL,
	request_id UUID NOT NULL,
	request_digest VARCHAR(64) NOT NULL,
	actor_user_id UUID NOT NULL,
	reason VARCHAR(1000) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_ai_write_policies PRIMARY KEY (id),
	CONSTRAINT fk_ai_write_policies_tenant_id_ai_principals FOREIGN KEY(tenant_id, principal_id) REFERENCES cehub_ai.ai_principals (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_ai_write_policies_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT ck_ai_write_policies_shape CHECK (revision>0 AND mode IN ('legacy','tiered') AND btrim(reason)<>'' AND request_digest ~ '^[a-f0-9]{64}$'),
	CONSTRAINT ck_ai_write_policies_contract CHECK (contract_version='dc11-write-policy.v1' AND jsonb_typeof(operation_settings)='object'),
	CONSTRAINT ck_ai_write_policies_operation_settings CHECK (coalesce(operation_settings ?& ARRAY['meeting.minutes.draft','meeting.actions.draft','meeting.decisions.draft','event.issue.create','record.ai_fields.update','report.weekly.draft','test_report.rows.confirm'] AND operation_settings - ARRAY['meeting.minutes.draft','meeting.actions.draft','meeting.decisions.draft','event.issue.create','record.ai_fields.update','report.weekly.draft','test_report.rows.confirm'] = '{}'::jsonb AND jsonb_typeof((operation_settings->'meeting.minutes.draft'))='object' AND (operation_settings->'meeting.minutes.draft') - ARRAY['mode','minimum_confirmation_basis_points','maximum_retraction_basis_points']='{}'::jsonb AND (operation_settings->'meeting.minutes.draft')->>'mode' IN ('disabled','confirm','automatic') AND jsonb_typeof((operation_settings->'meeting.minutes.draft')->'minimum_confirmation_basis_points')='number' AND (operation_settings->'meeting.minutes.draft')->>'minimum_confirmation_basis_points' ~ '^[0-9]+$' AND ((operation_settings->'meeting.minutes.draft')->>'minimum_confirmation_basis_points')::numeric BETWEEN 9000 AND 10000 AND jsonb_typeof((operation_settings->'meeting.minutes.draft')->'maximum_retraction_basis_points')='number' AND (operation_settings->'meeting.minutes.draft')->>'maximum_retraction_basis_points' ~ '^[0-9]+$' AND ((operation_settings->'meeting.minutes.draft')->>'maximum_retraction_basis_points')::numeric BETWEEN 0 AND 500 AND jsonb_typeof((operation_settings->'meeting.actions.draft'))='object' AND (operation_settings->'meeting.actions.draft') - ARRAY['mode','minimum_confirmation_basis_points','maximum_retraction_basis_points']='{}'::jsonb AND (operation_settings->'meeting.actions.draft')->>'mode' IN ('disabled','confirm','automatic') AND jsonb_typeof((operation_settings->'meeting.actions.draft')->'minimum_confirmation_basis_points')='number' AND (operation_settings->'meeting.actions.draft')->>'minimum_confirmation_basis_points' ~ '^[0-9]+$' AND ((operation_settings->'meeting.actions.draft')->>'minimum_confirmation_basis_points')::numeric BETWEEN 9000 AND 10000 AND jsonb_typeof((operation_settings->'meeting.actions.draft')->'maximum_retraction_basis_points')='number' AND (operation_settings->'meeting.actions.draft')->>'maximum_retraction_basis_points' ~ '^[0-9]+$' AND ((operation_settings->'meeting.actions.draft')->>'maximum_retraction_basis_points')::numeric BETWEEN 0 AND 500 AND jsonb_typeof((operation_settings->'meeting.decisions.draft'))='object' AND (operation_settings->'meeting.decisions.draft') - ARRAY['mode','minimum_confirmation_basis_points','maximum_retraction_basis_points']='{}'::jsonb AND (operation_settings->'meeting.decisions.draft')->>'mode' IN ('disabled','confirm','automatic') AND jsonb_typeof((operation_settings->'meeting.decisions.draft')->'minimum_confirmation_basis_points')='number' AND (operation_settings->'meeting.decisions.draft')->>'minimum_confirmation_basis_points' ~ '^[0-9]+$' AND ((operation_settings->'meeting.decisions.draft')->>'minimum_confirmation_basis_points')::numeric BETWEEN 9000 AND 10000 AND jsonb_typeof((operation_settings->'meeting.decisions.draft')->'maximum_retraction_basis_points')='number' AND (operation_settings->'meeting.decisions.draft')->>'maximum_retraction_basis_points' ~ '^[0-9]+$' AND ((operation_settings->'meeting.decisions.draft')->>'maximum_retraction_basis_points')::numeric BETWEEN 0 AND 500 AND jsonb_typeof((operation_settings->'event.issue.create'))='object' AND (operation_settings->'event.issue.create') - ARRAY['mode','minimum_confirmation_basis_points','maximum_retraction_basis_points']='{}'::jsonb AND (operation_settings->'event.issue.create')->>'mode' IN ('disabled','confirm','automatic') AND jsonb_typeof((operation_settings->'event.issue.create')->'minimum_confirmation_basis_points')='number' AND (operation_settings->'event.issue.create')->>'minimum_confirmation_basis_points' ~ '^[0-9]+$' AND ((operation_settings->'event.issue.create')->>'minimum_confirmation_basis_points')::numeric BETWEEN 9000 AND 10000 AND jsonb_typeof((operation_settings->'event.issue.create')->'maximum_retraction_basis_points')='number' AND (operation_settings->'event.issue.create')->>'maximum_retraction_basis_points' ~ '^[0-9]+$' AND ((operation_settings->'event.issue.create')->>'maximum_retraction_basis_points')::numeric BETWEEN 0 AND 500 AND jsonb_typeof((operation_settings->'record.ai_fields.update'))='object' AND (operation_settings->'record.ai_fields.update') - ARRAY['mode','minimum_confirmation_basis_points','maximum_retraction_basis_points']='{}'::jsonb AND (operation_settings->'record.ai_fields.update')->>'mode' IN ('disabled','confirm','automatic') AND jsonb_typeof((operation_settings->'record.ai_fields.update')->'minimum_confirmation_basis_points')='number' AND (operation_settings->'record.ai_fields.update')->>'minimum_confirmation_basis_points' ~ '^[0-9]+$' AND ((operation_settings->'record.ai_fields.update')->>'minimum_confirmation_basis_points')::numeric BETWEEN 9000 AND 10000 AND jsonb_typeof((operation_settings->'record.ai_fields.update')->'maximum_retraction_basis_points')='number' AND (operation_settings->'record.ai_fields.update')->>'maximum_retraction_basis_points' ~ '^[0-9]+$' AND ((operation_settings->'record.ai_fields.update')->>'maximum_retraction_basis_points')::numeric BETWEEN 0 AND 500 AND jsonb_typeof((operation_settings->'report.weekly.draft'))='object' AND (operation_settings->'report.weekly.draft') - ARRAY['mode','minimum_confirmation_basis_points','maximum_retraction_basis_points']='{}'::jsonb AND (operation_settings->'report.weekly.draft')->>'mode' IN ('disabled','confirm','automatic') AND jsonb_typeof((operation_settings->'report.weekly.draft')->'minimum_confirmation_basis_points')='number' AND (operation_settings->'report.weekly.draft')->>'minimum_confirmation_basis_points' ~ '^[0-9]+$' AND ((operation_settings->'report.weekly.draft')->>'minimum_confirmation_basis_points')::numeric BETWEEN 9000 AND 10000 AND jsonb_typeof((operation_settings->'report.weekly.draft')->'maximum_retraction_basis_points')='number' AND (operation_settings->'report.weekly.draft')->>'maximum_retraction_basis_points' ~ '^[0-9]+$' AND ((operation_settings->'report.weekly.draft')->>'maximum_retraction_basis_points')::numeric BETWEEN 0 AND 500 AND jsonb_typeof((operation_settings->'test_report.rows.confirm'))='object' AND (operation_settings->'test_report.rows.confirm') - ARRAY['mode','minimum_confirmation_basis_points','maximum_retraction_basis_points']='{}'::jsonb AND (operation_settings->'test_report.rows.confirm')->>'mode' IN ('disabled','confirm') AND jsonb_typeof((operation_settings->'test_report.rows.confirm')->'minimum_confirmation_basis_points')='number' AND (operation_settings->'test_report.rows.confirm')->>'minimum_confirmation_basis_points' ~ '^[0-9]+$' AND ((operation_settings->'test_report.rows.confirm')->>'minimum_confirmation_basis_points')::numeric BETWEEN 9000 AND 10000 AND jsonb_typeof((operation_settings->'test_report.rows.confirm')->'maximum_retraction_basis_points')='number' AND (operation_settings->'test_report.rows.confirm')->>'maximum_retraction_basis_points' ~ '^[0-9]+$' AND ((operation_settings->'test_report.rows.confirm')->>'maximum_retraction_basis_points')::numeric BETWEEN 0 AND 500, false)),
	CONSTRAINT uq_ai_write_policy_scope UNIQUE (tenant_id, id),
	CONSTRAINT uq_ai_write_policy_revision UNIQUE (tenant_id, revision),
	CONSTRAINT uq_ai_write_policy_request UNIQUE (tenant_id, actor_user_id, request_id),
	CONSTRAINT fk_ai_write_policies_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES cehub_core.tenants (id) ON DELETE RESTRICT
);
"""


def upgrade() -> None:
    op.execute(DDL)
    for name in ("ai_principals", "ai_write_policies"):
        op.execute(
            f"CREATE TRIGGER immutable_{name} BEFORE UPDATE OR DELETE ON cehub_ai.{name} FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history()"
        )
        op.execute(f"REVOKE ALL ON cehub_ai.{name} FROM PUBLIC")
        op.execute(
            f"DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pdos_agent') THEN REVOKE ALL ON cehub_ai.{name} FROM pdos_agent; END IF; END $$"
        )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.ai_write_policies) OR EXISTS(SELECT 1 FROM cehub_ai.ai_principals) THEN RAISE EXCEPTION 'Retain AI identity and write policy history'; END IF; END $$"
    )
    op.execute("DROP TABLE cehub_ai.ai_write_policies")
    op.execute("DROP TABLE cehub_ai.ai_principals")
