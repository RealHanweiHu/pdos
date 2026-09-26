"""Immutable corrections to historical Decision and Issue source associations."""

import sqlalchemy as sa
from alembic import op

revision = "0243_decision_source_corrections"
down_revision = "0242_decision_intake_targets"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_project.decision_intake_corrections (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    project_id UUID NOT NULL,
    source_row_id UUID NOT NULL,
    revision INTEGER NOT NULL,
    action VARCHAR(16) NOT NULL,
    previous_decision_id UUID,
    previous_issue_id UUID,
    target_decision_id UUID,
    target_issue_id UUID,
    request_id UUID NOT NULL,
    request_digest VARCHAR(64) NOT NULL,
    reason TEXT NOT NULL,
    impact_note TEXT NOT NULL,
    before_snapshot JSONB NOT NULL,
    after_snapshot JSONB NOT NULL,
    created_by_user_id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_decision_intake_corrections PRIMARY KEY (id),
    CONSTRAINT uq_decision_intake_correction_revision UNIQUE (tenant_id, source_row_id,
    revision),
    CONSTRAINT uq_decision_intake_correction_request UNIQUE (tenant_id, source_row_id,
    request_id),
    CONSTRAINT fk_decision_intake_corrections_tenant_id_decision_intake_rows FOREIGN
    KEY(tenant_id, project_id, source_row_id) REFERENCES cehub_project.decision_intake_rows
    (tenant_id, project_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_decision_correction_previous_issue_id FOREIGN KEY(tenant_id, project_id,
    previous_issue_id) REFERENCES cehub_project.issues (tenant_id, project_id, id) ON DELETE
    RESTRICT,
    CONSTRAINT fk_decision_correction_target_issue_id FOREIGN KEY(tenant_id, project_id,
    target_issue_id) REFERENCES cehub_project.issues (tenant_id, project_id, id) ON DELETE
    RESTRICT,
    CONSTRAINT fk_decision_intake_corrections_tenant_id_users FOREIGN KEY(tenant_id,
    created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_decision_correction_previous_decision_id FOREIGN KEY(tenant_id, project_id,
    previous_decision_id) REFERENCES cehub_project.decisions (tenant_id, project_id, id) ON
    DELETE RESTRICT,
    CONSTRAINT fk_decision_correction_target_decision_id FOREIGN KEY(tenant_id, project_id,
    target_decision_id) REFERENCES cehub_project.decisions (tenant_id, project_id, id) ON DELETE
    RESTRICT,
    CONSTRAINT ck_decision_intake_corrections_revision_digest CHECK (revision>0 AND
    request_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_decision_intake_corrections_reason CHECK (btrim(reason)<>'' AND
    btrim(impact_note)<>''),
    CONSTRAINT ck_decision_intake_corrections_snapshots CHECK
    (jsonb_typeof(before_snapshot)='object' AND jsonb_typeof(after_snapshot)='object'),
    CONSTRAINT ck_decision_intake_corrections_action CHECK ((action='withdraw' AND
    target_decision_id IS NULL AND target_issue_id IS NULL AND previous_decision_id IS NOT NULL)
    OR (action='reassign' AND target_decision_id IS NOT NULL AND (target_decision_id IS DISTINCT
    FROM previous_decision_id OR target_issue_id IS DISTINCT FROM previous_issue_id)))
)

;
CREATE INDEX ix_decision_intake_correction_target ON cehub_project.decision_intake_corrections
    (tenant_id, project_id, target_issue_id);
CREATE INDEX ix_decision_correction_decision ON cehub_project.decision_intake_corrections
    (tenant_id, project_id, target_decision_id);
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute("""
      CREATE FUNCTION cehub_project.guard_decision_source_correction() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog AS $$
      DECLARE r cehub_project.decision_intake_rows%ROWTYPE;
              prior cehub_project.decision_intake_corrections%ROWTYPE;
              expected_decision uuid; expected_issue uuid; expected_revision integer;
      BEGIN
        IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Source corrections are immutable'; END IF;
        SELECT * INTO r FROM cehub_project.decision_intake_rows
          WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.source_row_id
          FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'Source does not belong to this project'; END IF;
        SELECT * INTO prior FROM cehub_project.decision_intake_corrections
          WHERE tenant_id=NEW.tenant_id AND source_row_id=NEW.source_row_id
          ORDER BY revision DESC LIMIT 1;
        IF FOUND THEN
          expected_decision:=prior.target_decision_id; expected_issue:=prior.target_issue_id;
          expected_revision:=prior.revision+1;
        ELSE
          expected_decision:=r.decision_id; expected_issue:=r.related_issue_id;
          expected_revision:=1;
        END IF;
        IF NEW.revision<>expected_revision
          OR NEW.previous_decision_id IS DISTINCT FROM expected_decision
          OR NEW.previous_issue_id IS DISTINCT FROM expected_issue THEN
          RAISE EXCEPTION 'Source correction must follow its current association';
        END IF;
        IF NEW.before_snapshot->'decision'->>'id' IS DISTINCT FROM NEW.previous_decision_id::text
          OR NEW.before_snapshot->'issue'->>'id' IS DISTINCT FROM NEW.previous_issue_id::text
          OR NEW.after_snapshot->'decision'->>'id' IS DISTINCT FROM NEW.target_decision_id::text
          OR NEW.after_snapshot->'issue'->>'id' IS DISTINCT FROM NEW.target_issue_id::text THEN
          RAISE EXCEPTION 'Source correction must retain its actual target snapshots';
        END IF;
        RETURN NEW;
      END $$;
      REVOKE ALL ON FUNCTION cehub_project.guard_decision_source_correction() FROM PUBLIC;
      CREATE TRIGGER guard_decision_source_correction BEFORE INSERT OR UPDATE OR DELETE
        ON cehub_project.decision_intake_corrections FOR EACH ROW
        EXECUTE FUNCTION cehub_project.guard_decision_source_correction();
    """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_project.decision_intake_corrections)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard historical source corrections")
    op.drop_table("decision_intake_corrections", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.guard_decision_source_correction()")
