"""Keep preregistered AI trial protocols and immutable collection receipts."""

# ruff: noqa: E501
from alembic import op

revision = "0381_ai_write_trial_protocols"
down_revision = "0380_ai_meeting_work_drafts"
branch_labels = None
depends_on = None

DDL = """
CREATE TABLE cehub_ai.ai_write_trial_protocols (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	policy_id UUID NOT NULL,
	actor_user_id UUID NOT NULL,
	request_id UUID NOT NULL,
	request_digest VARCHAR(64) NOT NULL,
	protocol JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_ai_write_trial_protocols PRIMARY KEY (id),
	CONSTRAINT fk_ai_write_trial_protocols_tenant_id_ai_write_policies FOREIGN KEY(tenant_id, policy_id) REFERENCES cehub_ai.ai_write_policies (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_ai_write_trial_protocols_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT ck_ai_write_trial_protocols_shape CHECK (request_digest ~ '^[a-f0-9]{64}$' AND jsonb_typeof(protocol)='object'),
	CONSTRAINT uq_ai_trial_protocol_scope UNIQUE (tenant_id, id),
	CONSTRAINT uq_ai_trial_protocol_request UNIQUE (tenant_id, actor_user_id, request_id),
	CONSTRAINT fk_ai_write_trial_protocols_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES cehub_core.tenants (id) ON DELETE RESTRICT
);
CREATE INDEX ix_ai_trial_protocol_history ON cehub_ai.ai_write_trial_protocols (tenant_id, created_at, id);
CREATE TABLE cehub_ai.ai_write_trial_receipts (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	protocol_id UUID NOT NULL,
	actor_user_id UUID NOT NULL,
	request_id UUID NOT NULL,
	request_digest VARCHAR(64) NOT NULL,
	as_of TIMESTAMP WITH TIME ZONE NOT NULL,
	receipt JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_ai_write_trial_receipts PRIMARY KEY (id),
	CONSTRAINT fk_ai_write_trial_receipts_tenant_id_ai_write_trial_protocols FOREIGN KEY(tenant_id, protocol_id) REFERENCES cehub_ai.ai_write_trial_protocols (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_ai_write_trial_receipts_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT ck_ai_write_trial_receipts_shape CHECK (request_digest ~ '^[a-f0-9]{64}$' AND jsonb_typeof(receipt)='object' AND as_of<=created_at),
	CONSTRAINT uq_ai_trial_receipt_scope UNIQUE (tenant_id, id),
	CONSTRAINT uq_ai_trial_receipt_request UNIQUE (tenant_id, actor_user_id, request_id),
	CONSTRAINT fk_ai_write_trial_receipts_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES cehub_core.tenants (id) ON DELETE RESTRICT
);
CREATE INDEX ix_ai_trial_receipt_history ON cehub_ai.ai_write_trial_receipts (tenant_id, protocol_id, created_at, id);
"""

TABLES = ("ai_write_trial_protocols", "ai_write_trial_receipts")


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
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.ai_write_trial_protocols) OR EXISTS(SELECT 1 FROM cehub_ai.ai_write_trial_receipts) THEN RAISE EXCEPTION 'Retain AI trial protocols and collection history'; END IF; END $$"
    )
    for name in reversed(TABLES):
        op.execute(f"DROP TABLE cehub_ai.{name}")
