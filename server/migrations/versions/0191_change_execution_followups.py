"""Actual remedial tasks bound to the latest execution result.
Revision ID: 0191_change_execution_followups
Revises: 0190_change_execution_results
"""

import sqlalchemy as sa
from alembic import op

revision = "0191_change_execution_followups"
down_revision = "0190_change_execution_results"
branch_labels = None
depends_on = None
DDL = [
    """
CREATE TABLE cehub_product.change_execution_followups (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
binding_id UUID NOT NULL,
source_result_id UUID NOT NULL,
task_id UUID NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
created_by_user_id UUID NOT NULL,
created_at TIMESTAMP WITH TIME ZONE NOT NULL,
snapshot JSONB NOT NULL,
CONSTRAINT pk_change_execution_followups PRIMARY KEY (id),
CONSTRAINT uq_change_followup_task UNIQUE (tenant_id, binding_id, task_id),
CONSTRAINT uq_change_followup_request UNIQUE (tenant_id, created_by_user_id, request_id),
CONSTRAINT fk_change_execution_followups_tenant_id_tasks FOREIGN KEY(tenant_id, project_id,
task_id) REFERENCES cehub_project.tasks (tenant_id, project_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_change_execution_followups_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_change_execution_followups_change_followup_shape CHECK (request_digest ~
'^[a-f0-9]{64}$' AND jsonb_typeof(snapshot)='object'),
CONSTRAINT fk_change_execution_followups_binding_id_change_execution_tasks FOREIGN
KEY(binding_id) REFERENCES cehub_product.change_execution_tasks (id) ON DELETE RESTRICT,
CONSTRAINT fk_change_execution_followups_source_result_id_change_e_4b71 FOREIGN
KEY(source_result_id) REFERENCES cehub_product.change_execution_results (id) ON DELETE RESTRICT
)
""",
    """
CREATE INDEX ix_change_followup_binding ON cehub_product.change_execution_followups (tenant_id,
project_id, binding_id)
""",
    """
CREATE INDEX ix_change_followup_task ON cehub_product.change_execution_followups (tenant_id,
project_id, task_id)
""",
    """
CREATE FUNCTION cehub_product.guard_change_execution_followup() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE source_binding uuid; source_revision integer;
BEGIN
IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Execution followup history is immutable' USING
ERRCODE='23514'; END IF;
PERFORM 1 FROM cehub_product.change_execution_tasks WHERE tenant_id=NEW.tenant_id AND
project_id=NEW.project_id AND id=NEW.binding_id FOR UPDATE;
IF NOT FOUND THEN RAISE EXCEPTION 'Followup requires actual project execution item' USING
ERRCODE='23514'; END IF;
SELECT binding_id,revision_number INTO source_binding,source_revision FROM
cehub_product.change_execution_results WHERE tenant_id=NEW.tenant_id AND
project_id=NEW.project_id AND id=NEW.source_result_id;
IF NOT FOUND OR source_binding<>NEW.binding_id THEN RAISE EXCEPTION 'Followup source must belong
to execution item' USING ERRCODE='23514'; END IF;
IF EXISTS (SELECT 1 FROM cehub_product.change_execution_results WHERE tenant_id=NEW.tenant_id
AND binding_id=NEW.binding_id AND revision_number>source_revision) THEN RAISE EXCEPTION
'Followup must bind latest result' USING ERRCODE='23514'; END IF;
RETURN NEW;
END $$
""",
    """
CREATE TRIGGER guard_change_execution_followups BEFORE INSERT OR UPDATE OR DELETE ON
cehub_product.change_execution_followups FOR EACH ROW EXECUTE FUNCTION
cehub_product.guard_change_execution_followup()
""",
]


def upgrade() -> None:
    for statement in DDL:
        op.execute(sa.text(statement))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_product.change_execution_followups)"))
        .scalar()
    ):
        raise RuntimeError("Refusing to discard execution followup history")
    op.execute("DROP TABLE cehub_product.change_execution_followups")
    op.execute("DROP FUNCTION cehub_product.guard_change_execution_followup()")
