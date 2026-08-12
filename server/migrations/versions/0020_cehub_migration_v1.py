"""add audited CEHub v1 migration boundaries

Revision ID: 0020_cehub_migration_v1
Revises: 0019_deliverable_checks
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020_cehub_migration_v1"
down_revision: str | Sequence[str] | None = "0019_deliverable_checks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_file_references",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("source_system", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("stage_code", sa.String(length=64), nullable=True),
        sa.Column("task_source_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "classification IN ('internal', 'confidential', 'restricted')",
            name=op.f("ck_external_file_references_classification_allowed"),
        ),
        sa.CheckConstraint(
            "btrim(filename) <> ''",
            name=op.f("ck_external_file_references_filename_nonblank"),
        ),
        sa.CheckConstraint(
            "btrim(media_type) <> ''",
            name=op.f("ck_external_file_references_media_type_nonblank"),
        ),
        sa.CheckConstraint(
            "btrim(object_key) <> ''",
            name=op.f("ck_external_file_references_object_key_nonblank"),
        ),
        sa.CheckConstraint(
            "size_bytes >= 0",
            name=op.f("ck_external_file_references_size_nonnegative"),
        ),
        sa.CheckConstraint(
            "source_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_external_file_references_source_hash_hex"),
        ),
        sa.CheckConstraint(
            "btrim(source_id) <> ''",
            name=op.f("ck_external_file_references_source_id_nonblank"),
        ),
        sa.CheckConstraint(
            "btrim(source_system) <> ''",
            name=op.f("ck_external_file_references_source_system_nonblank"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["cehub_core.tenants.id"],
            name=op.f("fk_external_file_references_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["cehub_project.projects.tenant_id", "cehub_project.projects.id"],
            name="fk_external_file_references_tenant_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "uploaded_by_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_external_file_references_tenant_uploader",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_file_references")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_external_file_references_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "source_system",
            "source_id",
            name="uq_external_file_references_tenant_source",
        ),
        schema="cehub_project",
    )
    op.create_index(
        "ix_external_file_references_tenant_project_created",
        "external_file_references",
        ["tenant_id", "project_id", "created_at", "id"],
        unique=False,
        schema="cehub_project",
    )

    op.create_table(
        "gate_history_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("gate_id", sa.Uuid(), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("source_system", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("participants", sa.Text(), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("conditions", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('approved', 'conditional', 'rejected')",
            name=op.f("ck_gate_history_records_decision_allowed"),
        ),
        sa.CheckConstraint(
            "round_number > 0",
            name=op.f("ck_gate_history_records_round_number_positive"),
        ),
        sa.CheckConstraint(
            "source_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_gate_history_records_source_hash_hex"),
        ),
        sa.CheckConstraint(
            "btrim(source_id) <> ''",
            name=op.f("ck_gate_history_records_source_id_nonblank"),
        ),
        sa.CheckConstraint(
            "btrim(source_system) <> ''",
            name=op.f("ck_gate_history_records_source_system_nonblank"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["cehub_core.tenants.id"],
            name=op.f("fk_gate_history_records_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "gate_id"],
            [
                "cehub_project.gates.tenant_id",
                "cehub_project.gates.project_id",
                "cehub_project.gates.id",
            ],
            name="fk_gate_history_records_tenant_project_gate",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reviewed_by_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_gate_history_records_tenant_reviewer",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gate_history_records")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_gate_history_records_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "source_system",
            "source_id",
            name="uq_gate_history_records_tenant_source",
        ),
        schema="cehub_project",
    )
    op.create_index(
        "ix_gate_history_records_tenant_project_gate_round",
        "gate_history_records",
        ["tenant_id", "project_id", "gate_id", "round_number"],
        unique=False,
        schema="cehub_project",
    )

    op.create_table(
        "migration_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("source_system", sa.String(length=64), nullable=False),
        sa.Column("source_schema", sa.String(length=64), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "selected_project_ids",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "stats",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(selected_project_ids) = 'array'",
            name=op.f("ck_migration_runs_project_ids_array"),
        ),
        sa.CheckConstraint(
            "source_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_migration_runs_source_fingerprint_hex"),
        ),
        sa.CheckConstraint(
            "btrim(source_schema) <> ''",
            name=op.f("ck_migration_runs_source_schema_nonblank"),
        ),
        sa.CheckConstraint(
            "source_system = 'cehub-v3'",
            name=op.f("ck_migration_runs_source_system_allowed"),
        ),
        sa.CheckConstraint(
            "status = 'completed'",
            name=op.f("ck_migration_runs_status_allowed"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(stats) = 'object'",
            name=op.f("ck_migration_runs_stats_object"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["cehub_core.tenants.id"],
            name=op.f("fk_migration_runs_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_migration_runs_tenant_actor",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_migration_runs")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_migration_runs_tenant_id_id"),
        schema="cehub_audit",
    )
    op.create_index(
        "ix_migration_runs_tenant_created",
        "migration_runs",
        ["tenant_id", "created_at", "id"],
        unique=False,
        schema="cehub_audit",
    )

    op.create_table(
        "migration_mappings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("source_system", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "entity_type IN ('user', 'project', 'task', 'gate_review', 'file_reference')",
            name=op.f("ck_migration_mappings_entity_type_allowed"),
        ),
        sa.CheckConstraint(
            "source_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_migration_mappings_source_hash_hex"),
        ),
        sa.CheckConstraint(
            "btrim(source_id) <> ''",
            name=op.f("ck_migration_mappings_source_id_nonblank"),
        ),
        sa.CheckConstraint(
            "source_system = 'cehub-v3'",
            name=op.f("ck_migration_mappings_source_system_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["cehub_core.tenants.id"],
            name=op.f("fk_migration_mappings_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["cehub_audit.migration_runs.tenant_id", "cehub_audit.migration_runs.id"],
            name="fk_migration_mappings_tenant_run",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_migration_mappings")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_migration_mappings_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "source_system",
            "entity_type",
            "source_id",
            name="uq_migration_mappings_tenant_source_entity",
        ),
        schema="cehub_audit",
    )
    op.create_index(
        "ix_migration_mappings_tenant_target",
        "migration_mappings",
        ["tenant_id", "entity_type", "target_id"],
        unique=False,
        schema="cehub_audit",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_migration_mappings_tenant_target",
        table_name="migration_mappings",
        schema="cehub_audit",
    )
    op.drop_table("migration_mappings", schema="cehub_audit")
    op.drop_index(
        "ix_migration_runs_tenant_created",
        table_name="migration_runs",
        schema="cehub_audit",
    )
    op.drop_table("migration_runs", schema="cehub_audit")
    op.drop_index(
        "ix_gate_history_records_tenant_project_gate_round",
        table_name="gate_history_records",
        schema="cehub_project",
    )
    op.drop_table("gate_history_records", schema="cehub_project")
    op.drop_index(
        "ix_external_file_references_tenant_project_created",
        table_name="external_file_references",
        schema="cehub_project",
    )
    op.drop_table("external_file_references", schema="cehub_project")
