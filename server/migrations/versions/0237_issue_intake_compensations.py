"""Bind source-correction batches to actual Issue action tasks."""

import sqlalchemy as sa
from alembic import op

revision = "0237_issue_intake_compensations"
down_revision = "0236_issue_intake_corrections"
branch_labels = None
depends_on = None

DDL = """
CREATE TABLE cehub_project.issue_intake_compensation_batches (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	request_snapshot JSONB NOT NULL, 
	results JSONB NOT NULL, 
	created_by_user_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_issue_intake_compensation_batches PRIMARY KEY (id), 
	CONSTRAINT uq_issue_compensation_batch_project UNIQUE (tenant_id, project_id, id), 
	CONSTRAINT uq_issue_compensation_batch_request UNIQUE (tenant_id, project_id, request_id), 
        CONSTRAINT fk_issue_intake_compensation_batches_tenant_id_projects FOREIGN
        KEY(tenant_id, project_id) REFERENCES cehub_project.projects (tenant_id, id) ON DELETE
        RESTRICT,
        CONSTRAINT fk_issue_intake_compensation_batches_tenant_id_users FOREIGN KEY(tenant_id,
        created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_issue_intake_compensation_batches_request CHECK (request_digest ~
        '^[0-9a-f]{64}$' AND jsonb_typeof(request_snapshot)='object'),
        CONSTRAINT ck_issue_intake_compensation_batches_results CHECK
        (jsonb_typeof(results)='array' AND jsonb_array_length(results) BETWEEN 1 AND 50)
)

;

CREATE TABLE cehub_project.issue_intake_compensations (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	batch_id UUID NOT NULL, 
	source_row_id UUID NOT NULL, 
	source_revision INTEGER NOT NULL, 
	issue_id UUID NOT NULL, 
	task_id UUID NOT NULL, 
	assignment_digest VARCHAR(64) NOT NULL, 
	snapshot JSONB NOT NULL, 
	created_by_user_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_issue_intake_compensations PRIMARY KEY (id), 
        CONSTRAINT uq_issue_compensation_scope UNIQUE (tenant_id, source_row_id,
        source_revision, issue_id),
        CONSTRAINT fk_issue_intake_compensations_tenant_id_issue_intake_co_c90a FOREIGN
        KEY(tenant_id, project_id, batch_id) REFERENCES
        cehub_project.issue_intake_compensation_batches (tenant_id, project_id, id) ON DELETE
        RESTRICT DEFERRABLE INITIALLY DEFERRED,
        CONSTRAINT fk_issue_intake_compensations_tenant_id_issue_intake_rows FOREIGN
        KEY(tenant_id, project_id, source_row_id) REFERENCES cehub_project.issue_intake_rows
        (tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_issue_intake_compensations_tenant_id_issue_intake_co_83c6 FOREIGN
        KEY(tenant_id, source_row_id, source_revision) REFERENCES
        cehub_project.issue_intake_corrections (tenant_id, source_row_id, revision) ON DELETE
        RESTRICT,
        CONSTRAINT fk_issue_intake_compensations_tenant_id_issues FOREIGN KEY(tenant_id,
        project_id, issue_id) REFERENCES cehub_project.issues (tenant_id, project_id, id) ON
        DELETE RESTRICT,
        CONSTRAINT fk_issue_intake_compensations_tenant_id_tasks FOREIGN KEY(tenant_id,
        project_id, task_id) REFERENCES cehub_project.tasks (tenant_id, project_id, id) ON
        DELETE RESTRICT,
        CONSTRAINT fk_issue_intake_compensations_tenant_id_users FOREIGN KEY(tenant_id,
        created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_issue_intake_compensations_version_digest CHECK (source_revision>0 AND
        assignment_digest ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_issue_intake_compensations_snapshot CHECK (jsonb_typeof(snapshot)='object')
)

;
CREATE INDEX ix_issue_compensation_task ON cehub_project.issue_intake_compensations (tenant_id,
        project_id, task_id);
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute("""
        CREATE FUNCTION cehub_project.guard_issue_intake_compensation() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE current_revision integer;
        BEGIN
          IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Compensation binding is immutable'; END IF;
          PERFORM 1 FROM cehub_project.issue_intake_rows WHERE tenant_id=NEW.tenant_id
            AND project_id=NEW.project_id AND id=NEW.source_row_id FOR UPDATE;
          SELECT max(revision) INTO current_revision FROM cehub_project.issue_intake_corrections
            WHERE tenant_id=NEW.tenant_id AND source_row_id=NEW.source_row_id;
          IF current_revision IS DISTINCT FROM NEW.source_revision THEN
            RAISE EXCEPTION 'Source correction version changed'; END IF;
          IF NOT EXISTS(SELECT 1 FROM cehub_project.tasks WHERE tenant_id=NEW.tenant_id
            AND project_id=NEW.project_id AND id=NEW.task_id AND kind='issue_action'
            AND source_entity_id=NEW.issue_id) THEN
            RAISE EXCEPTION 'Compensation must use the original Issue task contract'; END IF;
          RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION cehub_project.guard_issue_intake_compensation() FROM PUBLIC;
        CREATE TRIGGER guard_issue_intake_compensation BEFORE INSERT OR UPDATE OR DELETE
          ON cehub_project.issue_intake_compensations FOR EACH ROW
          EXECUTE FUNCTION cehub_project.guard_issue_intake_compensation();
        CREATE TRIGGER guard_issue_intake_compensation_batch BEFORE UPDATE OR DELETE
          ON cehub_project.issue_intake_compensation_batches FOR EACH ROW
          EXECUTE FUNCTION cehub_ai.guard_issue_intake_confirmation();
    """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("""
        SELECT EXISTS(SELECT 1 FROM cehub_project.issue_intake_compensation_batches)
          OR EXISTS(SELECT 1 FROM cehub_project.issue_intake_compensations)
    """)
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard source compensation tasks and receipts")
    op.drop_table("issue_intake_compensations", schema="cehub_project")
    op.drop_table("issue_intake_compensation_batches", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.guard_issue_intake_compensation()")
