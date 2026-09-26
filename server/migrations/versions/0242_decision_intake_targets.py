"""Attach historical source rows to selected existing decisions and actual issues."""

import sqlalchemy as sa
from alembic import op

revision = "0242_decision_intake_targets"
down_revision = "0241_decision_intake_confirm"
branch_labels = None
depends_on = None

OLD_GUARD = """
    CREATE OR REPLACE FUNCTION cehub_project.guard_decision_intake_source() RETURNS trigger
    LANGUAGE plpgsql SET search_path=pg_catalog AS $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM cehub_project.decisions d
        WHERE d.tenant_id=NEW.tenant_id AND d.project_id=NEW.project_id AND d.id=NEW.decision_id
          AND d.historical_source->>'source_row_id'=NEW.id::text
          AND d.historical_source->>'document_id'=NEW.document_id::text
          AND d.historical_source->>'reviewed_by_user_id'=NEW.created_by_user_id::text
          AND d.historical_source->>'review_note'=NEW.review_note
      ) THEN RAISE EXCEPTION 'Decision source must match its historical record'; END IF;
      RETURN NEW;
    END $$;
    REVOKE ALL ON FUNCTION cehub_project.guard_decision_intake_source() FROM PUBLIC;
"""

NEW_GUARD = """
    CREATE OR REPLACE FUNCTION cehub_project.guard_decision_intake_source() RETURNS trigger
    LANGUAGE plpgsql SET search_path=pg_catalog AS $$
    BEGIN
      IF NEW.link_kind='linked' THEN
        IF NEW.created_snapshot->>'id' IS DISTINCT FROM NEW.decision_id::text THEN
          RAISE EXCEPTION 'Linked decision must preserve its actual target';
        END IF;
      ELSIF NOT EXISTS (
        SELECT 1 FROM cehub_project.decisions d
        WHERE d.tenant_id=NEW.tenant_id AND d.project_id=NEW.project_id AND d.id=NEW.decision_id
          AND d.historical_source->>'source_row_id'=NEW.id::text
          AND d.historical_source->>'document_id'=NEW.document_id::text
          AND d.historical_source->>'reviewed_by_user_id'=NEW.created_by_user_id::text
          AND d.historical_source->>'review_note'=NEW.review_note
      ) THEN RAISE EXCEPTION 'Decision source must match its historical record'; END IF;
      IF NEW.related_issue_id IS NOT NULL AND
        NEW.issue_snapshot->>'id' IS DISTINCT FROM NEW.related_issue_id::text THEN
        RAISE EXCEPTION 'Issue relation must preserve its actual target';
      END IF;
      RETURN NEW;
    END $$;
    REVOKE ALL ON FUNCTION cehub_project.guard_decision_intake_source() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute("""
      ALTER TABLE cehub_project.decision_intake_rows
        ADD COLUMN link_kind VARCHAR(16) NOT NULL DEFAULT 'created',
        ADD COLUMN reuse_reason TEXT,
        ADD COLUMN related_issue_id UUID,
        ADD COLUMN issue_snapshot JSONB,
        ADD COLUMN issue_reason TEXT,
        ADD CONSTRAINT fk_decision_intake_related_issue
          FOREIGN KEY (tenant_id, project_id, related_issue_id)
          REFERENCES cehub_project.issues (tenant_id, project_id, id) ON DELETE RESTRICT,
        ADD CONSTRAINT ck_decision_intake_rows_link_kind CHECK (
          (link_kind='created' AND reuse_reason IS NULL) OR
          (link_kind='linked' AND reuse_reason IS NOT NULL AND btrim(reuse_reason)<>'')),
        ADD CONSTRAINT ck_decision_intake_rows_related_issue CHECK (
          (related_issue_id IS NULL AND issue_snapshot IS NULL AND issue_reason IS NULL) OR
          (related_issue_id IS NOT NULL AND issue_snapshot IS NOT NULL
           AND jsonb_typeof(issue_snapshot)='object' AND issue_reason IS NOT NULL
           AND btrim(issue_reason)<>''));
      CREATE INDEX ix_decision_intake_related_issue ON cehub_project.decision_intake_rows
        (tenant_id, project_id, related_issue_id);
    """)
    op.execute(NEW_GUARD)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("""
      SELECT EXISTS(SELECT 1 FROM cehub_project.decision_intake_rows
        WHERE link_kind<>'created' OR related_issue_id IS NOT NULL)
    """)
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard selected Decision or Issue associations")
    op.execute(OLD_GUARD)
    op.execute("""
      DROP INDEX cehub_project.ix_decision_intake_related_issue;
      ALTER TABLE cehub_project.decision_intake_rows
        DROP CONSTRAINT ck_decision_intake_rows_related_issue,
        DROP CONSTRAINT ck_decision_intake_rows_link_kind,
        DROP CONSTRAINT fk_decision_intake_related_issue,
        DROP COLUMN issue_reason, DROP COLUMN issue_snapshot, DROP COLUMN related_issue_id,
        DROP COLUMN reuse_reason, DROP COLUMN link_kind;
    """)
