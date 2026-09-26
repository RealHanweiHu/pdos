"""Published six-dimension health thresholds and missing-source rules."""

from alembic import op

revision = "0342_portfolio_health_policy"
down_revision = "0341_portfolio_explanation_runs"
branch_labels = None
depends_on = None
DDL = """
CREATE TABLE cehub_project.portfolio_health_policies (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	version INTEGER NOT NULL, 
	body JSONB NOT NULL, 
	formula_version VARCHAR(80) NOT NULL, 
	created_by_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_portfolio_health_policies PRIMARY KEY (id), 
	CONSTRAINT uq_portfolio_health_policy_scope UNIQUE (tenant_id, id), 
	CONSTRAINT uq_portfolio_health_policy_version UNIQUE (tenant_id, version), 
        CONSTRAINT uq_portfolio_health_policy_request UNIQUE (tenant_id, created_by_user_id,
request_id),
        CONSTRAINT fk_portfolio_health_policies_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_portfolio_health_policies_shape CHECK (version>0 AND
jsonb_typeof(body)='object' AND request_digest ~ '^[a-f0-9]{64}$' AND
formula_version='health.v1')
);
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute("REVOKE ALL ON cehub_project.portfolio_health_policies FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER immutable_portfolio_health_policies BEFORE UPDATE OR DELETE "
        "ON cehub_project.portfolio_health_policies FOR EACH ROW "
        "EXECUTE FUNCTION cehub_ai.protect_checkpoint_history()"
    )


def downgrade() -> None:
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_project.portfolio_health_policies)
    THEN RAISE EXCEPTION 'Retain published health policy history'; END IF; END $$;""")
    op.execute("DROP TABLE cehub_project.portfolio_health_policies")
