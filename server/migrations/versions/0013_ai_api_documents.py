"""add document metadata and lossless extraction pointers

Revision ID: 0013_ai_api_documents
Revises: 0012_phase_one_agents
Create Date: 2026-08-12 02:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_ai_api_documents"
down_revision: str | Sequence[str] | None = "0012_phase_one_agents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CORE_SCHEMA = "cehub_core"
PROJECT_SCHEMA = "cehub_project"


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("extraction_status", sa.String(length=32), nullable=False),
        sa.Column("fragment_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("btrim(filename) <> ''", name=op.f("ck_documents_filename_nonblank")),
        sa.CheckConstraint(
            "fragment_count >= 0",
            name=op.f("ck_documents_fragment_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "btrim(media_type) <> ''", name=op.f("ck_documents_media_type_nonblank")
        ),
        sa.CheckConstraint(
            "btrim(object_key) <> ''", name=op.f("ck_documents_object_key_nonblank")
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_documents_sha256_hex")),
        sa.CheckConstraint("size_bytes > 0", name=op.f("ck_documents_size_positive")),
        sa.CheckConstraint(
            "classification IN ('internal', 'confidential', 'restricted')",
            name=op.f("ck_documents_classification_allowed"),
        ),
        sa.CheckConstraint(
            "extraction_status IN ('extracted', 'ocr_required')",
            name=op.f("ck_documents_extraction_status_allowed"),
        ),
        sa.CheckConstraint(
            "(extraction_status = 'extracted' AND fragment_count > 0) OR "
            "(extraction_status = 'ocr_required' AND fragment_count = 0)",
            name=op.f("ck_documents_extraction_fragment_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{CORE_SCHEMA}.tenants.id"],
            name=op.f("fk_documents_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
            name="fk_documents_tenant_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "uploaded_by_user_id"],
            [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
            name="fk_documents_tenant_uploader",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_documents_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "project_id", "id", name="uq_documents_tenant_project_id"),
        sa.UniqueConstraint("tenant_id", "object_key", name="uq_documents_tenant_object_key"),
        schema=PROJECT_SCHEMA,
    )
    op.create_index(
        "ix_documents_tenant_project_created",
        "documents",
        ["tenant_id", "project_id", "created_at", "id"],
        unique=False,
        schema=PROJECT_SCHEMA,
    )
    op.create_table(
        "document_fragments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("locator", sa.String(length=256), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(locator) <> ''",
            name=op.f("ck_document_fragments_locator_nonblank"),
        ),
        sa.CheckConstraint("ordinal > 0", name=op.f("ck_document_fragments_ordinal_positive")),
        sa.CheckConstraint("btrim(text) <> ''", name=op.f("ck_document_fragments_text_nonblank")),
        sa.CheckConstraint(
            "char_length(text) <= 20000",
            name=op.f("ck_document_fragments_text_size"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{CORE_SCHEMA}.tenants.id"],
            name=op.f("fk_document_fragments_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "document_id"],
            [
                f"{PROJECT_SCHEMA}.documents.tenant_id",
                f"{PROJECT_SCHEMA}.documents.project_id",
                f"{PROJECT_SCHEMA}.documents.id",
            ],
            name="fk_document_fragments_tenant_project_document",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_fragments")),
        sa.UniqueConstraint(
            "tenant_id",
            "document_id",
            "ordinal",
            name="uq_document_fragments_tenant_document_ordinal",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_document_fragments_tenant_id_id"),
        schema=PROJECT_SCHEMA,
    )
    op.create_index(
        "ix_document_fragments_tenant_project_document",
        "document_fragments",
        ["tenant_id", "project_id", "document_id", "ordinal"],
        unique=False,
        schema=PROJECT_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_fragments_tenant_project_document",
        table_name="document_fragments",
        schema=PROJECT_SCHEMA,
    )
    op.drop_table("document_fragments", schema=PROJECT_SCHEMA)
    op.drop_index(
        "ix_documents_tenant_project_created",
        table_name="documents",
        schema=PROJECT_SCHEMA,
    )
    op.drop_table("documents", schema=PROJECT_SCHEMA)
