"""Preserve named Decision impact reviews with initialization work results."""

from alembic import op

revision = "0256_decision_reference_reviews"
down_revision = "0255_decision_correction_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""ALTER TABLE cehub_project.project_intake_work_results
    ADD COLUMN business_reviews jsonb NOT NULL DEFAULT '[]'::jsonb;
    ALTER TABLE cehub_project.project_intake_work_results ADD CONSTRAINT
    ck_project_intake_work_results_business_reviews CHECK
    (jsonb_typeof(business_reviews)='array' AND jsonb_array_length(business_reviews)<=50);
    """)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_project.project_intake_work_results
               WHERE business_reviews<>'[]'::jsonb) THEN
      RAISE EXCEPTION 'Decision impact review history must be retained';
    END IF;
    END $$;
    ALTER TABLE cehub_project.project_intake_work_results DROP COLUMN business_reviews;
    """)
