"""Actual tasks and immutable preparation receipts from firmware work packages.
Revision ID: 0184_firmware_package_tasks
Revises: 0183_firmware_work_packages
"""

import sqlalchemy as sa
from alembic import op

revision = "0184_firmware_package_tasks"
down_revision = "0183_firmware_work_packages"
branch_labels = None
depends_on = None

DDL = [
    """
ALTER TABLE cehub_product.firmware_work_packages ADD CONSTRAINT
uq_firmware_package_project_scope UNIQUE (tenant_id, project_id, id)
""",
    """
CREATE TABLE cehub_product.firmware_package_tasks (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
package_id UUID NOT NULL,
task_id UUID NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
created_by_user_id UUID NOT NULL,
snapshot JSONB NOT NULL,
created_at TIMESTAMP WITH TIME ZONE NOT NULL,
CONSTRAINT pk_firmware_package_tasks PRIMARY KEY (id),
CONSTRAINT uq_firmware_package_task UNIQUE (tenant_id, package_id, task_id),
CONSTRAINT uq_firmware_task_request UNIQUE (tenant_id, created_by_user_id, request_id),
CONSTRAINT fk_firmware_package_tasks_tenant_id_firmware_work_packages FOREIGN KEY(tenant_id,
project_id, package_id) REFERENCES cehub_product.firmware_work_packages (tenant_id, project_id,
id) ON DELETE RESTRICT,
CONSTRAINT fk_firmware_package_tasks_tenant_id_tasks FOREIGN KEY(tenant_id, project_id, task_id)
REFERENCES cehub_project.tasks (tenant_id, project_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_firmware_package_tasks_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_firmware_package_tasks_firmware_task_shape CHECK (request_digest ~
'^[a-f0-9]{64}$' AND jsonb_typeof(snapshot)='object')
)
""",
    """
CREATE INDEX ix_firmware_package_task_scope ON cehub_product.firmware_package_tasks (tenant_id,
project_id, task_id)
""",
    """
CREATE FUNCTION cehub_product.guard_firmware_package_task() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE release_id uuid;
BEGIN
IF TG_OP <> 'INSERT' THEN
RAISE EXCEPTION 'Firmware task preparation receipts are immutable' USING ERRCODE='23514';
END IF;
PERFORM 1 FROM cehub_project.tasks WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id
AND id=NEW.task_id AND kind='task' FOR UPDATE;
IF NOT FOUND THEN RAISE EXCEPTION 'Actual project task required' USING ERRCODE='23514'; END IF;
SELECT fw_release_id INTO release_id FROM cehub_product.firmware_work_packages
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.package_id;
IF EXISTS(SELECT 1 FROM cehub_product.firmware_package_tasks b JOIN
cehub_product.firmware_work_packages p
ON p.tenant_id=b.tenant_id AND p.id=b.package_id
WHERE b.tenant_id=NEW.tenant_id AND b.task_id=NEW.task_id AND p.fw_release_id<>release_id) THEN
RAISE EXCEPTION 'Carry a task only within the same firmware version' USING ERRCODE='23514';
END IF;
RETURN NEW;
END $$
""",
    """
CREATE TRIGGER guard_firmware_package_task BEFORE INSERT OR UPDATE OR DELETE
ON cehub_product.firmware_package_tasks FOR EACH ROW
EXECUTE FUNCTION cehub_product.guard_firmware_package_task()
""",
]


def upgrade() -> None:
    for statement in DDL:
        op.execute(sa.text(statement))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_product.firmware_package_tasks)"))
        .scalar()
    ):
        raise RuntimeError("Refusing to discard firmware task preparation receipts")
    op.execute("DROP TABLE cehub_product.firmware_package_tasks")
    op.execute("DROP FUNCTION cehub_product.guard_firmware_package_task()")
    op.execute(
        "ALTER TABLE cehub_product.firmware_work_packages "
        "DROP CONSTRAINT uq_firmware_package_project_scope"
    )
