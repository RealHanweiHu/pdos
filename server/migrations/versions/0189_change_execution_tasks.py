"""Actual project tasks assigned in batches against the approved change scope.
Revision ID: 0189_change_execution_tasks
Revises: 0188_change_impact_scope
"""

import sqlalchemy as sa
from alembic import op

revision = "0189_change_execution_tasks"
down_revision = "0188_change_impact_scope"
branch_labels = None
depends_on = None

DDL = [
    """
CREATE TABLE cehub_product.change_execution_batches (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
ecr_id UUID NOT NULL,
scope_version_id UUID NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
created_by_user_id UUID NOT NULL,
created_at TIMESTAMP WITH TIME ZONE NOT NULL,
reason TEXT NOT NULL,
snapshot JSONB NOT NULL,
CONSTRAINT pk_change_execution_batches PRIMARY KEY (id),
CONSTRAINT uq_change_execution_batch_scope UNIQUE (tenant_id, project_id, id),
CONSTRAINT uq_change_execution_batch_request UNIQUE (tenant_id, created_by_user_id, request_id),
CONSTRAINT fk_change_execution_batches_tenant_id_engineering_chang_7c64 FOREIGN KEY(tenant_id,
project_id, ecr_id) REFERENCES cehub_product.engineering_change_requests (tenant_id, project_id,
id) ON DELETE RESTRICT,
CONSTRAINT fk_change_execution_batches_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_change_execution_batches_change_execution_batch_shape CHECK (request_digest ~
'^[a-f0-9]{64}$' AND btrim(reason)<>'' AND jsonb_typeof(snapshot)='object'),
CONSTRAINT fk_change_execution_batches_scope_version_id_change_imp_be79 FOREIGN
KEY(scope_version_id) REFERENCES cehub_product.change_impact_scope_versions (id) ON DELETE
RESTRICT
)
""",
    """
CREATE INDEX ix_change_execution_batch_ecr ON cehub_product.change_execution_batches (tenant_id,
project_id, ecr_id)
""",
    """
CREATE TABLE cehub_product.change_execution_tasks (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
ecr_id UUID NOT NULL,
scope_version_id UUID NOT NULL,
batch_id UUID NOT NULL,
item_key UUID NOT NULL,
task_id UUID NOT NULL,
snapshot JSONB NOT NULL,
CONSTRAINT pk_change_execution_tasks PRIMARY KEY (id),
CONSTRAINT uq_change_execution_scope_item UNIQUE (tenant_id, scope_version_id, item_key),
CONSTRAINT fk_change_execution_tasks_tenant_id_change_execution_batches FOREIGN KEY(tenant_id,
project_id, batch_id) REFERENCES cehub_product.change_execution_batches (tenant_id, project_id,
id) ON DELETE RESTRICT,
CONSTRAINT fk_change_execution_tasks_tenant_id_tasks FOREIGN KEY(tenant_id, project_id, task_id)
REFERENCES cehub_project.tasks (tenant_id, project_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_change_execution_tasks_change_execution_task_shape CHECK
(jsonb_typeof(snapshot)='object'),
CONSTRAINT fk_change_execution_tasks_scope_version_id_change_impac_a9b2 FOREIGN
KEY(scope_version_id) REFERENCES cehub_product.change_impact_scope_versions (id) ON DELETE
RESTRICT
)
""",
    """
CREATE INDEX ix_change_execution_task_ecr ON cehub_product.change_execution_tasks (tenant_id,
project_id, ecr_id)
""",
    """
CREATE INDEX ix_change_execution_task_origin ON cehub_product.change_execution_tasks (tenant_id,
project_id, task_id)
""",
    """
CREATE FUNCTION cehub_product.guard_change_execution_assignment() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE scope jsonb;
BEGIN
IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Change execution assignment is immutable' USING
ERRCODE='23514'; END IF;
SELECT v.snapshot INTO scope FROM cehub_product.change_impact_scope_versions v
JOIN cehub_product.engineering_change_requests e ON e.tenant_id=v.tenant_id AND
e.project_id=v.project_id AND e.id=v.ecr_id
WHERE v.tenant_id=NEW.tenant_id AND v.project_id=NEW.project_id AND v.ecr_id=NEW.ecr_id AND
v.id=NEW.scope_version_id
AND e.status='approved' AND e.impact_analysis #>> '{impact_scope,version_id}' =
NEW.scope_version_id::text;
IF NOT FOUND THEN RAISE EXCEPTION 'Execution must bind the approved ECR scope' USING
ERRCODE='23514'; END IF;
IF TG_TABLE_NAME='change_execution_tasks' THEN
IF NOT EXISTS (SELECT 1 FROM cehub_product.change_execution_batches b WHERE
b.tenant_id=NEW.tenant_id AND b.project_id=NEW.project_id
AND b.id=NEW.batch_id AND b.ecr_id=NEW.ecr_id AND b.scope_version_id=NEW.scope_version_id)
OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(scope->'items') item WHERE
item->>'key'=NEW.item_key::text
AND item->>'conclusion'<>'unknown' AND item->>'action'<>'none')
THEN RAISE EXCEPTION 'Assignment item must belong to approved batch scope' USING
ERRCODE='23514'; END IF;
END IF;
RETURN NEW;
END $$
""",
    """
CREATE TRIGGER guard_change_execution_batches BEFORE INSERT OR UPDATE OR DELETE ON
cehub_product.change_execution_batches FOR EACH ROW EXECUTE FUNCTION
cehub_product.guard_change_execution_assignment()
""",
    """
CREATE TRIGGER guard_change_execution_tasks BEFORE INSERT OR UPDATE OR DELETE ON
cehub_product.change_execution_tasks FOR EACH ROW EXECUTE FUNCTION
cehub_product.guard_change_execution_assignment()
""",
]


def upgrade() -> None:
    for statement in DDL:
        op.execute(sa.text(statement))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_product.change_execution_batches)"))
        .scalar()
    ):
        raise RuntimeError("Refusing to discard change execution assignment history")
    op.execute("DROP TABLE cehub_product.change_execution_tasks")
    op.execute("DROP TABLE cehub_product.change_execution_batches")
    op.execute("DROP FUNCTION cehub_product.guard_change_execution_assignment()")
