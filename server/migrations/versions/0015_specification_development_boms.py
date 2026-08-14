"""add specification and development BOM boundaries

Revision ID: 0015_specification_boms
Revises: 0014_finding_quality_controls
Create Date: 2026-08-12 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_specification_boms"
down_revision: str | Sequence[str] | None = "0014_finding_quality_controls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CORE_SCHEMA = "cehub_core"
COST_SCHEMA = "cehub_cost"
PRODUCT_SCHEMA = "cehub_product"
PROJECT_SCHEMA = "cehub_project"


def upgrade() -> None:
    op.create_table(
        "specifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "content",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
        sa.CheckConstraint("btrim(code) <> ''", name=op.f("ck_specifications_code_nonblank")),
        sa.CheckConstraint("btrim(title) <> ''", name=op.f("ck_specifications_title_nonblank")),
        sa.CheckConstraint("version > 0", name=op.f("ck_specifications_version_positive")),
        sa.CheckConstraint(
            "jsonb_typeof(content) = 'object'",
            name=op.f("ck_specifications_content_object"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{CORE_SCHEMA}.tenants.id"],
            name="fk_specifications_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
            name="fk_specifications_tenant_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
            name="fk_specifications_tenant_creator",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_specifications"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_specifications_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "id",
            name="uq_specifications_tenant_project_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "code",
            "version",
            name="uq_specifications_tenant_project_code_version",
        ),
        schema=PRODUCT_SCHEMA,
    )
    op.create_index(
        "ix_specifications_tenant_project_updated",
        "specifications",
        ["tenant_id", "project_id", "updated_at", "id"],
        unique=False,
        schema=PRODUCT_SCHEMA,
    )

    op.create_table(
        "development_boms",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("specification_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("bom_type", sa.String(length=32), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
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
            "bom_type IN ('ebom', 'prototype', 'cost')",
            name=op.f("ck_development_boms_type_allowed"),
        ),
        sa.CheckConstraint("btrim(code) <> ''", name=op.f("ck_development_boms_code_nonblank")),
        sa.CheckConstraint("btrim(name) <> ''", name=op.f("ck_development_boms_name_nonblank")),
        sa.CheckConstraint("version > 0", name=op.f("ck_development_boms_version_positive")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{CORE_SCHEMA}.tenants.id"],
            name="fk_development_boms_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
            name="fk_development_boms_tenant_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "specification_id"],
            [
                f"{PRODUCT_SCHEMA}.specifications.tenant_id",
                f"{PRODUCT_SCHEMA}.specifications.project_id",
                f"{PRODUCT_SCHEMA}.specifications.id",
            ],
            name="fk_development_boms_tenant_project_specification",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
            name="fk_development_boms_tenant_creator",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_development_boms"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_development_boms_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "id",
            name="uq_development_boms_tenant_project_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            "bom_type",
            name="uq_development_boms_tenant_id_type",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "code",
            "version",
            name="uq_development_boms_tenant_project_code_version",
        ),
        schema=PRODUCT_SCHEMA,
    )
    op.create_index(
        "ix_development_boms_tenant_project_type",
        "development_boms",
        ["tenant_id", "project_id", "bom_type", "updated_at", "id"],
        unique=False,
        schema=PRODUCT_SCHEMA,
    )

    op.create_table(
        "development_bom_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("bom_id", sa.Uuid(), nullable=False),
        sa.Column("parent_item_id", sa.Uuid(), nullable=True),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("part_number", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("material_reference", sa.String(length=256), nullable=True),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
            "line_number > 0",
            name=op.f("ck_development_bom_items_line_number_positive"),
        ),
        sa.CheckConstraint(
            "btrim(part_number) <> ''",
            name=op.f("ck_development_bom_items_part_number_nonblank"),
        ),
        sa.CheckConstraint(
            "btrim(description) <> ''",
            name=op.f("ck_development_bom_items_description_nonblank"),
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name=op.f("ck_development_bom_items_quantity_positive"),
        ),
        sa.CheckConstraint(
            "btrim(unit) <> ''",
            name=op.f("ck_development_bom_items_unit_nonblank"),
        ),
        sa.CheckConstraint(
            "parent_item_id IS NULL OR parent_item_id <> id",
            name=op.f("ck_development_bom_items_parent_not_self"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(attributes) = 'object'",
            name=op.f("ck_development_bom_items_attributes_object"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{CORE_SCHEMA}.tenants.id"],
            name="fk_development_bom_items_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "bom_id"],
            [
                f"{PRODUCT_SCHEMA}.development_boms.tenant_id",
                f"{PRODUCT_SCHEMA}.development_boms.project_id",
                f"{PRODUCT_SCHEMA}.development_boms.id",
            ],
            name="fk_development_bom_items_tenant_project_bom",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "bom_id", "parent_item_id"],
            [
                f"{PRODUCT_SCHEMA}.development_bom_items.tenant_id",
                f"{PRODUCT_SCHEMA}.development_bom_items.bom_id",
                f"{PRODUCT_SCHEMA}.development_bom_items.id",
            ],
            name="fk_development_bom_items_tenant_bom_parent",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_development_bom_items"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_development_bom_items_tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "bom_id",
            "id",
            name="uq_development_bom_items_tenant_bom_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "bom_id",
            "line_number",
            name="uq_development_bom_items_tenant_bom_line",
        ),
        schema=PRODUCT_SCHEMA,
    )
    op.create_index(
        "ix_development_bom_items_tenant_bom_parent",
        "development_bom_items",
        ["tenant_id", "bom_id", "parent_item_id", "line_number"],
        unique=False,
        schema=PRODUCT_SCHEMA,
    )

    op.create_table(
        "erp_bom_references",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("bom_id", sa.Uuid(), nullable=True),
        sa.Column("reference_type", sa.String(length=32), nullable=False),
        sa.Column("source_system", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=256), nullable=False),
        sa.Column("external_url", sa.String(length=2048), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "reference_type IN ('mbom', 'routing', 'production_version')",
            name=op.f("ck_erp_bom_references_type_allowed"),
        ),
        sa.CheckConstraint(
            "btrim(source_system) <> ''",
            name=op.f("ck_erp_bom_references_source_system_nonblank"),
        ),
        sa.CheckConstraint(
            "btrim(external_id) <> ''",
            name=op.f("ck_erp_bom_references_external_id_nonblank"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name=op.f("ck_erp_bom_references_metadata_object"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{CORE_SCHEMA}.tenants.id"],
            name="fk_erp_bom_references_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
            name="fk_erp_bom_references_tenant_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "bom_id"],
            [
                f"{PRODUCT_SCHEMA}.development_boms.tenant_id",
                f"{PRODUCT_SCHEMA}.development_boms.project_id",
                f"{PRODUCT_SCHEMA}.development_boms.id",
            ],
            name="fk_erp_bom_references_tenant_project_bom",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_erp_bom_references"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_erp_bom_references_tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "source_system",
            "reference_type",
            "external_id",
            name="uq_erp_bom_references_tenant_source_type_external",
        ),
        schema=PRODUCT_SCHEMA,
    )
    op.create_index(
        "ix_erp_bom_references_tenant_project_type",
        "erp_bom_references",
        ["tenant_id", "project_id", "reference_type", "id"],
        unique=False,
        schema=PRODUCT_SCHEMA,
    )

    op.create_table(
        "cost_bom_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("bom_id", sa.Uuid(), nullable=False),
        sa.Column("bom_type", sa.String(length=32), nullable=False),
        sa.Column("bom_item_id", sa.Uuid(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("unit_cost", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("cost_category", sa.String(length=64), nullable=True),
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
        sa.CheckConstraint("bom_type = 'cost'", name=op.f("ck_cost_bom_items_cost_bom_only")),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name=op.f("ck_cost_bom_items_currency_iso_like"),
        ),
        sa.CheckConstraint(
            "unit_cost >= 0",
            name=op.f("ck_cost_bom_items_unit_cost_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{CORE_SCHEMA}.tenants.id"],
            name="fk_cost_bom_items_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "bom_id"],
            [
                f"{PRODUCT_SCHEMA}.development_boms.tenant_id",
                f"{PRODUCT_SCHEMA}.development_boms.project_id",
                f"{PRODUCT_SCHEMA}.development_boms.id",
            ],
            name="fk_cost_bom_items_tenant_project_bom",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "bom_id", "bom_type"],
            [
                f"{PRODUCT_SCHEMA}.development_boms.tenant_id",
                f"{PRODUCT_SCHEMA}.development_boms.id",
                f"{PRODUCT_SCHEMA}.development_boms.bom_type",
            ],
            name="fk_cost_bom_items_tenant_bom_type",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "bom_id", "bom_item_id"],
            [
                f"{PRODUCT_SCHEMA}.development_bom_items.tenant_id",
                f"{PRODUCT_SCHEMA}.development_bom_items.bom_id",
                f"{PRODUCT_SCHEMA}.development_bom_items.id",
            ],
            name="fk_cost_bom_items_tenant_bom_item",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cost_bom_items"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_cost_bom_items_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "bom_item_id",
            name="uq_cost_bom_items_tenant_bom_item",
        ),
        schema=COST_SCHEMA,
    )
    op.create_index(
        "ix_cost_bom_items_tenant_project_bom",
        "cost_bom_items",
        ["tenant_id", "project_id", "bom_id", "bom_item_id"],
        unique=False,
        schema=COST_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cost_bom_items_tenant_project_bom",
        table_name="cost_bom_items",
        schema=COST_SCHEMA,
    )
    op.drop_table("cost_bom_items", schema=COST_SCHEMA)
    op.drop_index(
        "ix_erp_bom_references_tenant_project_type",
        table_name="erp_bom_references",
        schema=PRODUCT_SCHEMA,
    )
    op.drop_table("erp_bom_references", schema=PRODUCT_SCHEMA)
    op.drop_index(
        "ix_development_bom_items_tenant_bom_parent",
        table_name="development_bom_items",
        schema=PRODUCT_SCHEMA,
    )
    op.drop_table("development_bom_items", schema=PRODUCT_SCHEMA)
    op.drop_index(
        "ix_development_boms_tenant_project_type",
        table_name="development_boms",
        schema=PRODUCT_SCHEMA,
    )
    op.drop_table("development_boms", schema=PRODUCT_SCHEMA)
    op.drop_index(
        "ix_specifications_tenant_project_updated",
        table_name="specifications",
        schema=PRODUCT_SCHEMA,
    )
    op.drop_table("specifications", schema=PRODUCT_SCHEMA)
