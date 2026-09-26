"""Immutable human firmware investigation and release preparation dossiers.
Revision ID: 0183_firmware_work_packages
Revises: 0182_test_execution_preparations
"""

import sqlalchemy as sa
from alembic import op

revision = "0183_firmware_work_packages"
down_revision = "0182_test_execution_preparations"
branch_labels = None
depends_on = None

DDL = [
    """
ALTER TABLE cehub_product.fw_releases ADD CONSTRAINT uq_fw_release_project_scope UNIQUE
(tenant_id, project_id, id)
""",
    """
CREATE TABLE cehub_product.firmware_work_packages (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
fw_release_id UUID NOT NULL,
revision_number INTEGER NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
created_by_user_id UUID NOT NULL,
snapshot JSONB NOT NULL,
created_at TIMESTAMP WITH TIME ZONE NOT NULL,
CONSTRAINT pk_firmware_work_packages PRIMARY KEY (id),
CONSTRAINT uq_firmware_package_revision UNIQUE (tenant_id, fw_release_id, revision_number),
CONSTRAINT uq_firmware_package_request UNIQUE (tenant_id, created_by_user_id, request_id),
CONSTRAINT fk_firmware_work_packages_tenant_id_fw_releases FOREIGN KEY(tenant_id, project_id,
fw_release_id) REFERENCES cehub_product.fw_releases (tenant_id, project_id, id) ON DELETE
RESTRICT,
CONSTRAINT fk_firmware_work_packages_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_firmware_work_packages_firmware_package_shape CHECK (revision_number > 0 AND
request_digest ~ '^[a-f0-9]{64}$' AND jsonb_typeof(snapshot)='object' AND
jsonb_typeof(snapshot->'sources')='array')
)
""",
    """
CREATE INDEX ix_firmware_package_project ON cehub_product.firmware_work_packages (tenant_id,
project_id, created_at, id)
""",
    """
CREATE FUNCTION cehub_product.guard_firmware_work_package() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
IF TG_OP <> 'INSERT' THEN
RAISE EXCEPTION 'Firmware work package versions are immutable' USING ERRCODE='23514';
END IF;
PERFORM 1 FROM cehub_product.fw_releases
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.fw_release_id
FOR UPDATE;
IF NEW.revision_number <> COALESCE((SELECT max(p.revision_number)
FROM cehub_product.firmware_work_packages p
WHERE p.tenant_id=NEW.tenant_id AND p.fw_release_id=NEW.fw_release_id),0)+1 THEN
RAISE EXCEPTION 'Firmware package revision must be contiguous' USING ERRCODE='23514';
END IF;
RETURN NEW;
END $$
""",
    """
CREATE TRIGGER guard_firmware_work_package BEFORE INSERT OR UPDATE OR DELETE
ON cehub_product.firmware_work_packages FOR EACH ROW
EXECUTE FUNCTION cehub_product.guard_firmware_work_package()
""",
]


def upgrade() -> None:
    for statement in DDL:
        op.execute(sa.text(statement))


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text("SELECT EXISTS(SELECT 1 FROM cehub_product.firmware_work_packages)")
    ).scalar():
        raise RuntimeError("Refusing to discard saved firmware work packages")
    op.execute("DROP TABLE cehub_product.firmware_work_packages")
    op.execute("DROP FUNCTION cehub_product.guard_firmware_work_package()")
    op.execute("ALTER TABLE cehub_product.fw_releases DROP CONSTRAINT uq_fw_release_project_scope")
