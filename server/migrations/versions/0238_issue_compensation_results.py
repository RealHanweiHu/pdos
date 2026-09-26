"""Record named source-compensation results and actual original Issue versions."""

import sqlalchemy as sa
from alembic import op

revision = "0238_issue_compensation_results"
down_revision = "0237_issue_intake_compensations"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_project.issue_intake_compensation_results (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	binding_id UUID NOT NULL, 
	source_row_id UUID NOT NULL, 
	source_revision INTEGER NOT NULL, 
	revision INTEGER NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	outcome VARCHAR(32) NOT NULL, 
	summary TEXT NOT NULL, 
	criteria_response TEXT NOT NULL, 
	remaining TEXT NOT NULL, 
	before_snapshot JSONB NOT NULL, 
	after_snapshot JSONB NOT NULL, 
	context_snapshot JSONB NOT NULL, 
	evidence_snapshot JSONB NOT NULL, 
	created_by_user_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_issue_intake_compensation_results PRIMARY KEY (id), 
	CONSTRAINT uq_issue_compensation_result_revision UNIQUE (tenant_id, binding_id, revision), 
	CONSTRAINT uq_issue_compensation_result_request UNIQUE (tenant_id, binding_id, request_id), 
        CONSTRAINT fk_issue_intake_compensation_results_tenant_id_issue_in_7f69 FOREIGN
        KEY(tenant_id, project_id, binding_id) REFERENCES
        cehub_project.issue_intake_compensations (tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_issue_intake_compensation_results_tenant_id_issue_in_9cca FOREIGN
        KEY(tenant_id, source_row_id, source_revision) REFERENCES
        cehub_project.issue_intake_corrections (tenant_id, source_row_id, revision) ON DELETE
        RESTRICT,
        CONSTRAINT fk_issue_intake_compensation_results_tenant_id_users FOREIGN KEY(tenant_id,
        created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_issue_intake_compensation_results_version_digest CHECK (revision>0 AND
        source_revision>0 AND request_digest ~ '^[0-9a-f]{64}$'),
        CONSTRAINT ck_issue_intake_compensation_results_outcome CHECK (outcome IN
        ('recorded','issue_corrected','no_change_needed','needs_follow_up')),
        CONSTRAINT ck_issue_intake_compensation_results_notes CHECK (btrim(summary)<>'' AND
        btrim(criteria_response)<>'' AND btrim(remaining)<>''),
        CONSTRAINT ck_issue_intake_compensation_results_snapshots CHECK
        (jsonb_typeof(before_snapshot)='object' AND jsonb_typeof(after_snapshot)='object' AND
        jsonb_typeof(context_snapshot)='object' AND jsonb_typeof(evidence_snapshot)='array')
)

"""


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_issue_compensation_project",
        "issue_intake_compensations",
        ["tenant_id", "project_id", "id"],
        schema="cehub_project",
    )
    op.execute(DDL)
    op.execute("""
        CREATE FUNCTION cehub_project.guard_issue_compensation_result() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE binding_source uuid; current_revision integer; result_revision integer;
        BEGIN
          IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Compensation results are immutable'; END IF;
          SELECT source_row_id INTO binding_source FROM cehub_project.issue_intake_compensations
            WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.binding_id
            FOR UPDATE;
          IF binding_source IS DISTINCT FROM NEW.source_row_id THEN
            RAISE EXCEPTION 'Result must reference the original compensation source'; END IF;
          PERFORM 1 FROM cehub_project.issue_intake_rows WHERE tenant_id=NEW.tenant_id
            AND project_id=NEW.project_id AND id=NEW.source_row_id FOR UPDATE;
          SELECT max(revision) INTO current_revision FROM cehub_project.issue_intake_corrections
            WHERE tenant_id=NEW.tenant_id AND source_row_id=NEW.source_row_id;
          IF current_revision IS DISTINCT FROM NEW.source_revision THEN
            RAISE EXCEPTION 'Source correction version changed'; END IF;
          SELECT coalesce(max(revision),0) INTO result_revision
            FROM cehub_project.issue_intake_compensation_results
            WHERE tenant_id=NEW.tenant_id AND binding_id=NEW.binding_id;
          IF NEW.revision <> result_revision+1 THEN
            RAISE EXCEPTION 'Compensation result version must advance continuously'; END IF;
          RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION cehub_project.guard_issue_compensation_result() FROM PUBLIC;
        CREATE TRIGGER guard_issue_compensation_result BEFORE INSERT OR UPDATE OR DELETE
          ON cehub_project.issue_intake_compensation_results FOR EACH ROW
          EXECUTE FUNCTION cehub_project.guard_issue_compensation_result();
    """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("SELECT EXISTS(SELECT 1 FROM cehub_project.issue_intake_compensation_results)")
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard original Issue repair versions and evidence")
    op.drop_table("issue_intake_compensation_results", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.guard_issue_compensation_result()")
    op.drop_constraint(
        "uq_issue_compensation_project",
        "issue_intake_compensations",
        schema="cehub_project",
        type_="unique",
    )
