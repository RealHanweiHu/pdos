"""Versioned test execution work packages and actual task/run bindings.
Revision ID: 0182_test_execution_preparations
Revises: 0181_report_sample_resolution
"""

import sqlalchemy as sa
from alembic import op

revision = "0182_test_execution_preparations"
down_revision = "0181_report_sample_resolution"
branch_labels = None
depends_on = None

DDL = [
    """
CREATE TABLE cehub_quality.test_execution_preparations (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        test_case_id UUID NOT NULL,
        task_id UUID NOT NULL,
        revision_number INTEGER NOT NULL,
        request_id UUID NOT NULL,
        request_digest VARCHAR(64) NOT NULL,
        created_by_user_id UUID NOT NULL,
        snapshot JSONB NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        CONSTRAINT pk_test_execution_preparations PRIMARY KEY (id),
        CONSTRAINT uq_test_preparation_case_scope UNIQUE (tenant_id, project_id, test_case_id,
id),
        CONSTRAINT uq_test_preparation_revision UNIQUE (tenant_id, test_case_id,
revision_number),
        CONSTRAINT uq_test_preparation_request UNIQUE (tenant_id, created_by_user_id,
request_id),
        CONSTRAINT fk_test_execution_preparations_tenant_id_test_cases FOREIGN KEY(tenant_id,
project_id, test_case_id) REFERENCES cehub_quality.test_cases (tenant_id, project_id, id) ON
DELETE RESTRICT,
        CONSTRAINT fk_test_execution_preparations_tenant_id_tasks FOREIGN KEY(tenant_id,
project_id, task_id) REFERENCES cehub_project.tasks (tenant_id, project_id, id) ON DELETE
RESTRICT,
        CONSTRAINT fk_test_execution_preparations_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_test_execution_preparations_test_preparation_shape CHECK (revision_number
> 0 AND request_digest ~ '^[a-f0-9]{64}$' AND jsonb_typeof(snapshot)='object')
)
""",
    """
CREATE INDEX ix_test_preparation_task ON cehub_quality.test_execution_preparations (tenant_id,
project_id, task_id)
""",
    """
ALTER TABLE cehub_quality.test_runs ADD COLUMN test_preparation_id uuid
""",
    """
ALTER TABLE cehub_quality.test_runs ADD CONSTRAINT fk_test_runs_execution_preparation FOREIGN
KEY(tenant_id, project_id, test_case_id, test_preparation_id) REFERENCES
cehub_quality.test_execution_preparations (tenant_id, project_id, test_case_id, id) ON DELETE
RESTRICT
""",
    """
CREATE FUNCTION cehub_quality.guard_test_preparation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Test preparation versions are immutable' USING
ERRCODE='23514'; END IF;
 PERFORM 1 FROM cehub_project.tasks WHERE tenant_id=NEW.tenant_id AND id=NEW.task_id FOR UPDATE;
 IF NEW.revision_number <> COALESCE((SELECT max(p.revision_number) FROM
cehub_quality.test_execution_preparations p
   WHERE p.tenant_id=NEW.tenant_id AND p.test_case_id=NEW.test_case_id),0)+1
 OR EXISTS(SELECT 1 FROM cehub_quality.test_execution_preparations p WHERE
p.tenant_id=NEW.tenant_id
   AND ((p.test_case_id=NEW.test_case_id AND p.task_id<>NEW.task_id) OR
        (p.task_id=NEW.task_id AND p.test_case_id<>NEW.test_case_id))) THEN
  RAISE EXCEPTION 'Test preparation must retain one actual task and contiguous revisions' USING
ERRCODE='23514';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM cehub_quality.test_cases c JOIN cehub_quality.test_plans p
  ON p.tenant_id=c.tenant_id AND p.project_id=c.project_id AND p.id=c.plan_id
  JOIN cehub_project.tasks t ON t.tenant_id=NEW.tenant_id AND t.project_id=NEW.project_id AND
t.id=NEW.task_id
  WHERE c.tenant_id=NEW.tenant_id AND c.project_id=NEW.project_id AND c.id=NEW.test_case_id
    AND t.stage_id=p.stage_id AND t.kind='task') THEN
  RAISE EXCEPTION 'Test preparation requires its actual project stage task' USING
ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$
""",
    """
CREATE TRIGGER guard_test_preparation BEFORE INSERT OR UPDATE OR DELETE ON
cehub_quality.test_execution_preparations
FOR EACH ROW EXECUTE FUNCTION cehub_quality.guard_test_preparation()
""",
    """
CREATE FUNCTION cehub_quality.guard_test_run_preparation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF OLD.test_preparation_id IS DISTINCT FROM NEW.test_preparation_id THEN
 RAISE EXCEPTION 'Test run preparation is fixed at creation' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$
""",
    """
CREATE TRIGGER guard_test_run_preparation BEFORE UPDATE ON cehub_quality.test_runs
FOR EACH ROW EXECUTE FUNCTION cehub_quality.guard_test_run_preparation()
""",
]


def upgrade() -> None:
    for statement in DDL:
        op.execute(statement)


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text("SELECT EXISTS(SELECT 1 FROM cehub_quality.test_execution_preparations)")
    ).scalar_one():
        raise RuntimeError(
            "Test preparation history must be retained; downgrade requires explicit disposition"
        )
    op.execute("DROP TRIGGER guard_test_run_preparation ON cehub_quality.test_runs")
    op.execute("DROP FUNCTION cehub_quality.guard_test_run_preparation()")
    op.execute(
        "ALTER TABLE cehub_quality.test_runs DROP CONSTRAINT fk_test_runs_execution_preparation"
    )
    op.execute("ALTER TABLE cehub_quality.test_runs DROP COLUMN test_preparation_id")
    op.execute("DROP TRIGGER guard_test_preparation ON cehub_quality.test_execution_preparations")
    op.execute("DROP FUNCTION cehub_quality.guard_test_preparation()")
    op.execute("DROP TABLE cehub_quality.test_execution_preparations")
