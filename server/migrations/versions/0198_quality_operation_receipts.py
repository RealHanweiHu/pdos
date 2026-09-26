"""Immutable, same-transaction receipts for original human quality operations."""

import sqlalchemy as sa
from alembic import op

revision = "0198_quality_operation_receipts"
down_revision = "0197_quality_issue_links"
branch_labels = None
depends_on = None

DDL = """
CREATE TABLE cehub_quality.quality_operation_receipts (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        ncr_id UUID NOT NULL,
        request_id UUID NOT NULL,
        request_digest VARCHAR(64) NOT NULL,
        created_by_user_id UUID NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        command JSONB NOT NULL,
        result JSONB NOT NULL,
        before_digest VARCHAR(64) NOT NULL,
        after_digest VARCHAR(64) NOT NULL,
        CONSTRAINT pk_quality_operation_receipts PRIMARY KEY (id),
        CONSTRAINT uq_quality_operation_request UNIQUE (tenant_id, created_by_user_id,
request_id),
        CONSTRAINT fk_quality_operation_receipts_tenant_id_nonconformance_reports FOREIGN
KEY(tenant_id, project_id, ncr_id) REFERENCES cehub_quality.nonconformance_reports (tenant_id,
project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_quality_operation_receipts_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_quality_operation_receipts_shape CHECK (request_digest ~ '^[a-f0-9]{64}$'
AND before_digest ~ '^[a-f0-9]{64}$' AND after_digest ~ '^[a-f0-9]{64}$' AND
jsonb_typeof(command)='object' AND jsonb_typeof(result)='object')
)
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute("""CREATE TRIGGER protect_quality_operation_receipt BEFORE UPDATE OR DELETE
      ON cehub_quality.quality_operation_receipts FOR EACH ROW
      EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
      REVOKE ALL ON cehub_quality.quality_operation_receipts FROM PUBLIC;""")


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_quality.quality_operation_receipts)"))
        .scalar()
    ):
        raise RuntimeError("Refusing to discard quality operation history")
    op.drop_table("quality_operation_receipts", schema="cehub_quality")
