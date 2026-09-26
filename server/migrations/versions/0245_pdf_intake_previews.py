"""Allow immutable PDF passage drafts in the existing intake flows."""

from alembic import op

revision = "0245_pdf_intake_previews"
down_revision = "0244_decision_history_amendments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for kind in ("issue", "decision"):
        op.execute(
            f"ALTER TABLE cehub_ai.{kind}_intake_previews DROP CONSTRAINT "
            f"ck_{kind}_intake_previews_purpose_and_parser"
        )
        op.execute(
            f"ALTER TABLE cehub_ai.{kind}_intake_previews ADD CONSTRAINT "
            f"ck_{kind}_intake_previews_purpose_and_parser "
            "CHECK (btrim(permission_basis)<>'' AND btrim(purpose)<>'' "
            f"AND parser_version IN ('{kind}-list-extracted-v1', '{kind}-pdf-extracted-v1'))"
        )


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM cehub_ai.issue_intake_previews
            WHERE parser_version='issue-pdf-extracted-v1')
        OR EXISTS (SELECT 1 FROM cehub_ai.decision_intake_previews
            WHERE parser_version='decision-pdf-extracted-v1')
        THEN RAISE EXCEPTION 'PDF intake history must be retained'; END IF;
        END $$""")
    for kind in ("issue", "decision"):
        op.execute(
            f"ALTER TABLE cehub_ai.{kind}_intake_previews DROP CONSTRAINT "
            f"ck_{kind}_intake_previews_purpose_and_parser"
        )
        op.execute(
            f"ALTER TABLE cehub_ai.{kind}_intake_previews ADD CONSTRAINT "
            f"ck_{kind}_intake_previews_purpose_and_parser "
            "CHECK (btrim(permission_basis)<>'' AND btrim(purpose)<>'' "
            f"AND parser_version='{kind}-list-extracted-v1')"
        )
