"""Immutable correspondence of firmware task scope and actual test evidence.
Revision ID: 0185_firmware_task_results
Revises: 0184_firmware_package_tasks
"""

import sqlalchemy as sa
from alembic import op

revision = "0185_firmware_task_results"
down_revision = "0184_firmware_package_tasks"
branch_labels = None
depends_on = None

DDL = [
    """
ALTER TABLE cehub_product.firmware_package_tasks ADD CONSTRAINT uq_firmware_task_binding_scope
UNIQUE (tenant_id, project_id, id)
""",
    """
CREATE TABLE cehub_product.firmware_task_results (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
binding_id UUID NOT NULL,
revision_number INTEGER NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
created_by_user_id UUID NOT NULL,
snapshot JSONB NOT NULL,
created_at TIMESTAMP WITH TIME ZONE NOT NULL,
CONSTRAINT pk_firmware_task_results PRIMARY KEY (id),
CONSTRAINT uq_firmware_task_result_revision UNIQUE (tenant_id, binding_id, revision_number),
CONSTRAINT uq_firmware_task_result_request UNIQUE (tenant_id, created_by_user_id, request_id),
CONSTRAINT fk_firmware_task_results_tenant_id_firmware_package_tasks FOREIGN KEY(tenant_id,
project_id, binding_id) REFERENCES cehub_product.firmware_package_tasks (tenant_id, project_id,
id) ON DELETE RESTRICT,
CONSTRAINT fk_firmware_task_results_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_firmware_task_results_firmware_result_shape CHECK (revision_number > 0 AND
request_digest ~ '^[a-f0-9]{64}$' AND jsonb_typeof(snapshot)='object')
)
""",
    """
CREATE FUNCTION cehub_product.guard_firmware_task_result() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
IF TG_OP <> 'INSERT' THEN
RAISE EXCEPTION 'Firmware task result versions are immutable' USING ERRCODE='23514';
END IF;
PERFORM 1 FROM cehub_product.firmware_package_tasks
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.binding_id FOR UPDATE;
IF NEW.revision_number <> COALESCE((SELECT max(r.revision_number)
FROM cehub_product.firmware_task_results r
WHERE r.tenant_id=NEW.tenant_id AND r.binding_id=NEW.binding_id),0)+1 THEN
RAISE EXCEPTION 'Firmware task result revision must be contiguous' USING ERRCODE='23514';
END IF;
RETURN NEW;
END $$
""",
    """
CREATE TRIGGER guard_firmware_task_result BEFORE INSERT OR UPDATE OR DELETE
ON cehub_product.firmware_task_results FOR EACH ROW
EXECUTE FUNCTION cehub_product.guard_firmware_task_result()
""",
]


def upgrade() -> None:
    for statement in DDL:
        op.execute(sa.text(statement))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_product.firmware_task_results)"))
        .scalar()
    ):
        raise RuntimeError("Refusing to discard firmware task result records")
    op.execute("DROP TABLE cehub_product.firmware_task_results")
    op.execute("DROP FUNCTION cehub_product.guard_firmware_task_result()")
    op.execute(
        "ALTER TABLE cehub_product.firmware_package_tasks "
        "DROP CONSTRAINT uq_firmware_task_binding_scope"
    )
