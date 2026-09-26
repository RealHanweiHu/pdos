"""Keep STEP/Gerber originals without claiming text extraction or OCR."""

import sqlalchemy as sa
from alembic import op

revision = "0219_drawing_originals"
down_revision = "0218_field_capture_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_documents_extraction_status_allowed"), "documents", schema="cehub_project"
    )
    op.drop_constraint(
        op.f("ck_documents_extraction_fragment_consistent"), "documents", schema="cehub_project"
    )
    op.create_check_constraint(
        op.f("ck_documents_extraction_status_allowed"),
        "documents",
        "extraction_status IN ('extracted','ocr_required','preview_only')",
        schema="cehub_project",
    )
    op.create_check_constraint(
        op.f("ck_documents_extraction_fragment_consistent"),
        "documents",
        "(extraction_status='extracted' AND fragment_count>0) OR "
        "(extraction_status IN ('ocr_required','preview_only') AND fragment_count=0)",
        schema="cehub_project",
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_project.documents "
                "WHERE extraction_status='preview_only')"
            )
        )
        .scalar()
    ):
        raise RuntimeError("Refusing to misclassify engineering drawing originals as OCR input")
    op.drop_constraint(
        op.f("ck_documents_extraction_status_allowed"), "documents", schema="cehub_project"
    )
    op.drop_constraint(
        op.f("ck_documents_extraction_fragment_consistent"), "documents", schema="cehub_project"
    )
    op.create_check_constraint(
        op.f("ck_documents_extraction_status_allowed"),
        "documents",
        "extraction_status IN ('extracted','ocr_required')",
        schema="cehub_project",
    )
    op.create_check_constraint(
        op.f("ck_documents_extraction_fragment_consistent"),
        "documents",
        "(extraction_status='extracted' AND fragment_count>0) OR "
        "(extraction_status='ocr_required' AND fragment_count=0)",
        schema="cehub_project",
    )
