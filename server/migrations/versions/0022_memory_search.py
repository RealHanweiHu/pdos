"""add verified memory and pgvector embeddings

Revision ID: 0022_memory_search
Revises: 0021_quality_capa
Create Date: 2026-08-12 21:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.vector import Vector

# Revision identifiers, used by Alembic.
revision: str = "0022_memory_search"
down_revision: str | Sequence[str] | None = "0021_quality_capa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_finding_id", sa.Uuid(), nullable=True),
        sa.Column("source_ncr_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("verified_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("archived_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("applicability", sa.Text(), nullable=True),
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "source_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'draft'"),
            nullable=False,
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_memories_content_sha256_hex"),
        ),
        sa.CheckConstraint(
            "(status = 'draft' AND verified_by_user_id IS NULL AND verified_at IS NULL "
            "AND archived_by_user_id IS NULL AND archived_at IS NULL) OR "
            "(status = 'verified' AND verified_by_user_id IS NOT NULL AND verified_at IS NOT NULL "
            "AND archived_by_user_id IS NULL AND archived_at IS NULL) OR "
            "(status = 'archived' AND verified_by_user_id IS NOT NULL AND verified_at IS NOT NULL "
            "AND archived_by_user_id IS NOT NULL AND archived_at IS NOT NULL)",
            name=op.f("ck_memories_lifecycle_consistent"),
        ),
        sa.CheckConstraint(
            "btrim(title) <> '' AND btrim(content) <> ''",
            name=op.f("ck_memories_required_text_nonblank"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source_refs) = 'array'", name=op.f("ck_memories_source_refs_array")
        ),
        sa.CheckConstraint(
            "source_finding_id IS NULL OR source_ncr_id IS NULL",
            name=op.f("ck_memories_source_mutually_exclusive"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'verified', 'archived')",
            name=op.f("ck_memories_status_allowed"),
        ),
        sa.CheckConstraint("jsonb_typeof(tags) = 'array'", name=op.f("ck_memories_tags_array")),
        sa.CheckConstraint(
            "verified_by_user_id IS NULL OR verified_by_user_id <> created_by_user_id",
            name=op.f("ck_memories_verification_four_eyes"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "archived_by_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_memories_tenant_archiver",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_memories_tenant_creator",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "source_finding_id"],
            ["cehub_ai.findings.tenant_id", "cehub_ai.findings.project_id", "cehub_ai.findings.id"],
            name="fk_memories_tenant_project_finding",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "source_ncr_id"],
            [
                "cehub_quality.nonconformance_reports.tenant_id",
                "cehub_quality.nonconformance_reports.project_id",
                "cehub_quality.nonconformance_reports.id",
            ],
            name="fk_memories_tenant_project_ncr",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["cehub_project.projects.tenant_id", "cehub_project.projects.id"],
            name="fk_memories_tenant_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "verified_by_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_memories_tenant_verifier",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["cehub_core.tenants.id"],
            name=op.f("fk_memories_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memories")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_memories_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "project_id", "id", name="uq_memories_tenant_project_id"),
        sa.UniqueConstraint("tenant_id", "source_finding_id", name="uq_memories_tenant_finding"),
        sa.UniqueConstraint("tenant_id", "source_ncr_id", name="uq_memories_tenant_ncr"),
        schema="cehub_memory",
    )
    op.create_index(
        "ix_memories_tenant_project_status",
        "memories",
        ["tenant_id", "project_id", "status", "updated_at"],
        unique=False,
        schema="cehub_memory",
    )
    op.create_table(
        "memory_embeddings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=256), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("embedding", Vector(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_memory_embeddings_content_sha256_hex"),
        ),
        sa.CheckConstraint(
            "dimensions BETWEEN 1 AND 4096",
            name=op.f("ck_memory_embeddings_dimensions_range"),
        ),
        sa.CheckConstraint(
            "btrim(provider) <> '' AND btrim(model) <> ''",
            name=op.f("ck_memory_embeddings_route_nonblank"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_memory_embeddings_tenant_creator",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "memory_id"],
            [
                "cehub_memory.memories.tenant_id",
                "cehub_memory.memories.project_id",
                "cehub_memory.memories.id",
            ],
            name="fk_memory_embeddings_tenant_project_memory",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["cehub_core.tenants.id"],
            name=op.f("fk_memory_embeddings_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory_embeddings")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_memory_embeddings_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "memory_id",
            "provider",
            "model",
            "dimensions",
            "content_sha256",
            name="uq_memory_embeddings_route_content",
        ),
        schema="cehub_memory",
    )
    op.create_index(
        "ix_memory_embeddings_tenant_project_route",
        "memory_embeddings",
        ["tenant_id", "project_id", "provider", "model", "dimensions"],
        unique=False,
        schema="cehub_memory",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_memory_embeddings_tenant_project_route",
        table_name="memory_embeddings",
        schema="cehub_memory",
    )
    op.drop_table("memory_embeddings", schema="cehub_memory")
    op.drop_index(
        "ix_memories_tenant_project_status",
        table_name="memories",
        schema="cehub_memory",
    )
    op.drop_table("memories", schema="cehub_memory")
