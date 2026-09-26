"""Mechanical and hardware review versions, citations, and actual verification tasks.
Revision ID: 0186_engineering_review_packages
Revises: 0185_firmware_task_results
"""

import sqlalchemy as sa
from alembic import op

revision = "0186_engineering_review_packages"
down_revision = "0185_firmware_task_results"
branch_labels = None
depends_on = None

DDL = [
    """
CREATE TABLE cehub_product.engineering_review_packages (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
root_id UUID NOT NULL,
parent_id UUID,
revision_number INTEGER NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
created_by_user_id UUID NOT NULL,
snapshot JSONB NOT NULL,
created_at TIMESTAMP WITH TIME ZONE NOT NULL,
CONSTRAINT pk_engineering_review_packages PRIMARY KEY (id),
CONSTRAINT uq_engineering_review_scope UNIQUE (tenant_id, project_id, id),
CONSTRAINT uq_engineering_review_revision UNIQUE (tenant_id, root_id, revision_number),
CONSTRAINT uq_engineering_review_request UNIQUE (tenant_id, created_by_user_id, request_id),
CONSTRAINT fk_engineering_review_packages_tenant_id_projects FOREIGN KEY(tenant_id, project_id)
REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_engineering_review_packages_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_engineering_review_root FOREIGN KEY(tenant_id, project_id, root_id) REFERENCES
cehub_product.engineering_review_packages (tenant_id, project_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_engineering_review_parent FOREIGN KEY(tenant_id, project_id, parent_id) REFERENCES
cehub_product.engineering_review_packages (tenant_id, project_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_engineering_review_packages_engineering_review_shape CHECK (revision_number > 0
AND request_digest ~ '^[a-f0-9]{64}$' AND jsonb_typeof(snapshot)='object')
)
""",
    """
CREATE INDEX ix_engineering_review_project ON cehub_product.engineering_review_packages
(tenant_id, project_id, created_at, id)
""",
    """
CREATE TABLE cehub_product.engineering_review_tasks (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
package_id UUID NOT NULL,
line_key UUID NOT NULL,
task_id UUID NOT NULL,
created_at TIMESTAMP WITH TIME ZONE NOT NULL,
CONSTRAINT pk_engineering_review_tasks PRIMARY KEY (id),
CONSTRAINT uq_engineering_review_task_line UNIQUE (tenant_id, package_id, line_key),
CONSTRAINT fk_engineering_review_tasks_tenant_id_engineering_revie_36b7 FOREIGN KEY(tenant_id,
project_id, package_id) REFERENCES cehub_product.engineering_review_packages (tenant_id,
project_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_engineering_review_tasks_tenant_id_tasks FOREIGN KEY(tenant_id, project_id,
task_id) REFERENCES cehub_project.tasks (tenant_id, project_id, id) ON DELETE RESTRICT
)
""",
    """
CREATE INDEX ix_engineering_review_task ON cehub_product.engineering_review_tasks (tenant_id,
project_id, task_id)
""",
    """
CREATE FUNCTION cehub_product.guard_engineering_review() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE previous cehub_product.engineering_review_packages%ROWTYPE;
BEGIN
IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Engineering review is immutable' USING
ERRCODE='23514'; END IF;
PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR
UPDATE;
IF NEW.revision_number=1 THEN
IF NEW.root_id<>NEW.id OR NEW.parent_id IS NOT NULL THEN
RAISE EXCEPTION 'Invalid first review version' USING ERRCODE='23514'; END IF;
ELSE
SELECT * INTO previous FROM cehub_product.engineering_review_packages WHERE
tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND root_id=NEW.root_id ORDER BY revision_number DESC LIMIT 1;
IF previous.id IS NULL OR previous.id IS DISTINCT FROM NEW.parent_id
OR NEW.revision_number<>previous.revision_number+1 OR previous.snapshot->>'kind' IS DISTINCT
FROM NEW.snapshot->>'kind' THEN
RAISE EXCEPTION 'Review must follow its current parent' USING ERRCODE='23514'; END IF;
END IF;
RETURN NEW;
END $$
""",
    """
CREATE TRIGGER guard_engineering_review BEFORE INSERT OR UPDATE OR DELETE
ON cehub_product.engineering_review_packages FOR EACH ROW
EXECUTE FUNCTION cehub_product.guard_engineering_review()
""",
    """
CREATE FUNCTION cehub_product.guard_engineering_review_task() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Review task binding is immutable' USING
ERRCODE='23514'; END IF;
IF NOT EXISTS(SELECT 1 FROM cehub_product.engineering_review_packages p,
jsonb_array_elements(p.snapshot->'lines') item
WHERE p.tenant_id=NEW.tenant_id AND p.project_id=NEW.project_id AND p.id=NEW.package_id
AND item->>'key'=NEW.line_key::text AND item->>'task_id'=NEW.task_id::text) THEN
RAISE EXCEPTION 'Review task must match its prepared line' USING ERRCODE='23514'; END IF;
RETURN NEW;
END $$
""",
    """
CREATE TRIGGER guard_engineering_review_task BEFORE INSERT OR UPDATE OR DELETE
ON cehub_product.engineering_review_tasks FOR EACH ROW
EXECUTE FUNCTION cehub_product.guard_engineering_review_task()
""",
]


def upgrade() -> None:
    for statement in DDL:
        op.execute(sa.text(statement))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_product.engineering_review_packages)"))
        .scalar()
    ):
        raise RuntimeError("Refusing to discard engineering review records")
    op.execute("DROP TABLE cehub_product.engineering_review_tasks")
    op.execute("DROP TABLE cehub_product.engineering_review_packages")
    op.execute("DROP FUNCTION cehub_product.guard_engineering_review_task()")
    op.execute("DROP FUNCTION cehub_product.guard_engineering_review()")
