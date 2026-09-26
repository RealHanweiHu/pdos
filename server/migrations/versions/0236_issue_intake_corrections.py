"""Append source-association corrections without rewriting original Issues or receipts."""

import sqlalchemy as sa
from alembic import op

revision = "0236_issue_intake_corrections"
down_revision = "0235_issue_intake_reuse"
branch_labels = None
depends_on = None

DDL = """
CREATE TABLE cehub_project.issue_intake_corrections (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	source_row_id UUID NOT NULL, 
	revision INTEGER NOT NULL, 
	action VARCHAR(16) NOT NULL, 
	previous_issue_id UUID, 
	target_issue_id UUID, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	reason TEXT NOT NULL, 
	impact_note TEXT NOT NULL, 
	before_snapshot JSONB NOT NULL, 
	after_snapshot JSONB NOT NULL, 
	created_by_user_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_issue_intake_corrections PRIMARY KEY (id), 
	CONSTRAINT uq_issue_intake_correction_revision UNIQUE (tenant_id, source_row_id, revision), 
	CONSTRAINT uq_issue_intake_correction_request UNIQUE (tenant_id, source_row_id, request_id), 
        CONSTRAINT fk_issue_intake_corrections_tenant_id_issue_intake_rows FOREIGN
        KEY(tenant_id, project_id, source_row_id) REFERENCES cehub_project.issue_intake_rows
        (tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_issue_intake_corrections_tenant_id_issues FOREIGN KEY(tenant_id,
        project_id, previous_issue_id) REFERENCES cehub_project.issues (tenant_id, project_id,
        id) ON DELETE RESTRICT,
        CONSTRAINT fk_issue_intake_correction_target FOREIGN KEY(tenant_id,
        project_id, target_issue_id) REFERENCES cehub_project.issues (tenant_id, project_id, id)
        ON DELETE RESTRICT,
        CONSTRAINT fk_issue_intake_corrections_tenant_id_users FOREIGN KEY(tenant_id,
        created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_issue_intake_corrections_revision_digest CHECK (revision>0 AND
        request_digest ~ '^[0-9a-f]{64}$'),
        CONSTRAINT ck_issue_intake_corrections_reason CHECK (btrim(reason)<>'' AND
        btrim(impact_note)<>''),
        CONSTRAINT ck_issue_intake_corrections_snapshots CHECK
        (jsonb_typeof(before_snapshot)='object' AND jsonb_typeof(after_snapshot)='object'),
        CONSTRAINT ck_issue_intake_corrections_action CHECK ((action='withdraw' AND
        target_issue_id IS NULL AND previous_issue_id IS NOT NULL) OR (action='reassign' AND
        target_issue_id IS NOT NULL AND target_issue_id IS DISTINCT FROM previous_issue_id))
)

;
CREATE INDEX ix_issue_intake_correction_target ON cehub_project.issue_intake_corrections
        (tenant_id, project_id, target_issue_id);
"""


def upgrade() -> None:
    op.execute("""
        ALTER TABLE cehub_project.issue_intake_rows ADD CONSTRAINT uq_issue_intake_row_project
          UNIQUE (tenant_id, project_id, id);
    """)
    op.execute(DDL)
    op.execute("""
        CREATE FUNCTION cehub_project.guard_issue_intake_correction() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE current_revision integer; current_issue uuid; original_issue uuid;
        BEGIN
          IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Source correction is immutable'; END IF;
          SELECT issue_id INTO original_issue FROM cehub_project.issue_intake_rows
            WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.source_row_id
            FOR UPDATE;
          IF NOT FOUND THEN RAISE EXCEPTION 'Original source is unavailable'; END IF;
          SELECT revision, target_issue_id INTO current_revision, current_issue
            FROM cehub_project.issue_intake_corrections
            WHERE tenant_id=NEW.tenant_id AND source_row_id=NEW.source_row_id
            ORDER BY revision DESC LIMIT 1;
          IF NOT FOUND THEN current_revision:=0; current_issue:=original_issue; END IF;
          IF NEW.revision<>current_revision+1 OR
            NEW.previous_issue_id IS DISTINCT FROM current_issue
            THEN RAISE EXCEPTION 'Source correction predecessor changed'; END IF;
          RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION cehub_project.guard_issue_intake_correction() FROM PUBLIC;
        CREATE TRIGGER guard_issue_intake_correction BEFORE INSERT OR UPDATE OR DELETE
          ON cehub_project.issue_intake_corrections FOR EACH ROW
          EXECUTE FUNCTION cehub_project.guard_issue_intake_correction();
    """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("""
        SELECT EXISTS(SELECT 1 FROM cehub_project.issue_intake_corrections)
    """)
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard source correction history")
    op.drop_table("issue_intake_corrections", schema="cehub_project")
    op.execute("""
        DROP FUNCTION cehub_project.guard_issue_intake_correction();
        ALTER TABLE cehub_project.issue_intake_rows DROP CONSTRAINT uq_issue_intake_row_project;
    """)
