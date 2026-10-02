"""Preserve independent AI Issue creators without impersonating human reporters.

This is identity storage and read compatibility, not an AI write grant. The
runtime adapter, source/run receipts and qualification remain separately gated.
"""

from alembic import op

revision = "0384_issue_ai_identity"
down_revision = "0383_ai_meeting_event_receipts"
branch_labels = None
depends_on = None

UP = """
ALTER TABLE cehub_project.issues ADD COLUMN created_by_ai_principal_id uuid;
ALTER TABLE cehub_project.issues ADD CONSTRAINT fk_issues_tenant_ai_creator
 FOREIGN KEY (tenant_id, created_by_ai_principal_id)
 REFERENCES cehub_ai.ai_principals(tenant_id,id) ON DELETE RESTRICT;
ALTER TABLE cehub_project.issues ADD CONSTRAINT ck_issues_creator_exclusive
 CHECK (reported_by_user_id IS NULL OR created_by_ai_principal_id IS NULL);
CREATE FUNCTION cehub_project.protect_issue_creator() RETURNS trigger
 LANGUAGE plpgsql AS $$ BEGIN
 IF NEW.created_by_ai_principal_id IS DISTINCT FROM OLD.created_by_ai_principal_id
  OR NEW.reported_by_user_id IS DISTINCT FROM OLD.reported_by_user_id THEN
  RAISE EXCEPTION 'Retain the original Issue creator';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER immutable_issue_creator BEFORE UPDATE ON cehub_project.issues
 FOR EACH ROW EXECUTE FUNCTION cehub_project.protect_issue_creator();
"""

DOWN = """
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM cehub_project.issues WHERE created_by_ai_principal_id IS NOT NULL)
 THEN RAISE EXCEPTION 'Retain AI Issue creator history'; END IF;
END $$;
DROP TRIGGER immutable_issue_creator ON cehub_project.issues;
DROP FUNCTION cehub_project.protect_issue_creator();
ALTER TABLE cehub_project.issues DROP CONSTRAINT ck_issues_creator_exclusive;
ALTER TABLE cehub_project.issues DROP CONSTRAINT fk_issues_tenant_ai_creator;
ALTER TABLE cehub_project.issues DROP COLUMN created_by_ai_principal_id;
"""


def upgrade() -> None:
    op.execute(UP)


def downgrade() -> None:
    op.execute(DOWN)
