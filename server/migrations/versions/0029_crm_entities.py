"""add CRM intake and final Supplier Cost Resource entities

Revision ID: 0029_crm_entities
Revises: 0028_erp_handoff_executor
Create Date: 2026-08-13 08:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029_crm_entities"
down_revision: str | Sequence[str] | None = "0028_erp_handoff_executor"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_events_tenant_id_id",
        "events",
        ["tenant_id", "id"],
        schema="cehub_event",
    )
    op.create_table(
        "suppliers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'active'"), nullable=False
        ),
        sa.Column("external_reference", sa.String(length=256), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
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
            "btrim(code) <> '' AND btrim(name) <> ''",
            name=op.f("ck_suppliers_required_text_nonblank"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name=op.f("ck_suppliers_status_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["cehub_core.tenants.id"],
            name=op.f("fk_suppliers_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_suppliers")),
        sa.UniqueConstraint("tenant_id", "code", name="uq_suppliers_tenant_code"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_suppliers_tenant_id_id"),
        schema="cehub_supplier",
    )
    op.create_index(
        "ix_suppliers_tenant_status",
        "suppliers",
        ["tenant_id", "status", "code"],
        unique=False,
        schema="cehub_supplier",
    )
    op.create_table(
        "crm_requirement_intakes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("source_event_row_id", sa.BigInteger(), nullable=False),
        sa.Column("external_requirement_id", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default=sa.text("'pending_review'"),
            nullable=False,
        ),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_rationale", sa.Text(), nullable=True),
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
            "btrim(external_requirement_id) <> ''",
            name=op.f("ck_crm_requirement_intakes_external_id_nonblank"),
        ),
        sa.CheckConstraint(
            "(status = 'pending_review' AND reviewed_by_user_id IS NULL "
            "AND reviewed_at IS NULL AND review_rationale IS NULL) OR "
            "(status IN ('established', 'rejected') AND reviewed_by_user_id IS NOT NULL "
            "AND reviewed_at IS NOT NULL AND review_rationale IS NOT NULL "
            "AND btrim(review_rationale) <> '')",
            name=op.f("ck_crm_requirement_intakes_review_consistent"),
        ),
        sa.CheckConstraint(
            "status IN ('pending_review', 'established', 'rejected')",
            name=op.f("ck_crm_requirement_intakes_status_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["cehub_project.projects.tenant_id", "cehub_project.projects.id"],
            name="fk_crm_intakes_tenant_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requirement_id"],
            ["cehub_project.requirements.tenant_id", "cehub_project.requirements.id"],
            name="fk_crm_intakes_tenant_requirement",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reviewed_by_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_crm_intakes_tenant_reviewer",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_event_row_id"],
            ["cehub_event.events.tenant_id", "cehub_event.events.id"],
            name="fk_crm_intakes_tenant_source_event",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["cehub_core.tenants.id"],
            name=op.f("fk_crm_requirement_intakes_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_crm_requirement_intakes")),
        sa.UniqueConstraint(
            "tenant_id",
            "external_requirement_id",
            name="uq_crm_intakes_tenant_external_requirement",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_intakes_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "requirement_id",
            name="uq_crm_intakes_tenant_requirement",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "source_event_row_id",
            name="uq_crm_intakes_tenant_source_event",
        ),
        schema="cehub_project",
    )
    op.create_index(
        "ix_crm_intakes_tenant_status",
        "crm_requirement_intakes",
        ["tenant_id", "status", "created_at"],
        unique=False,
        schema="cehub_project",
    )
    op.create_table(
        "costs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("cost_type", sa.String(length=24), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'estimate'"), nullable=False
        ),
        sa.Column("incurred_on", sa.Date(), nullable=True),
        sa.Column(
            "details",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
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
        sa.CheckConstraint("amount >= 0", name=op.f("ck_costs_amount_nonnegative")),
        sa.CheckConstraint("btrim(code) <> ''", name=op.f("ck_costs_code_nonblank")),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_costs_currency_iso_like")),
        sa.CheckConstraint(
            "jsonb_typeof(details) = 'object'", name=op.f("ck_costs_details_object")
        ),
        sa.CheckConstraint(
            "status IN ('estimate', 'approved', 'actual')",
            name=op.f("ck_costs_status_allowed"),
        ),
        sa.CheckConstraint(
            "cost_type IN ('material', 'labor', 'tooling', 'logistics', 'other')",
            name=op.f("ck_costs_type_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["cehub_project.projects.tenant_id", "cehub_project.projects.id"],
            name="fk_costs_tenant_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["cehub_supplier.suppliers.tenant_id", "cehub_supplier.suppliers.id"],
            name="fk_costs_tenant_supplier",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["cehub_core.tenants.id"],
            name=op.f("fk_costs_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_costs")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_costs_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "project_id", "code", name="uq_costs_tenant_project_code"),
        schema="cehub_cost",
    )
    op.create_index(
        "ix_costs_tenant_project_status",
        "costs",
        ["tenant_id", "project_id", "status"],
        unique=False,
        schema="cehub_cost",
    )
    op.create_table(
        "resources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_user_id", sa.Uuid(), nullable=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("resource_type", sa.String(length=24), nullable=False),
        sa.Column(
            "allocation_percent",
            sa.Numeric(precision=5, scale=2),
            server_default=sa.text("100"),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'planned'"), nullable=False
        ),
        sa.Column(
            "details",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
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
            "allocation_percent > 0 AND allocation_percent <= 100",
            name=op.f("ck_resources_allocation_range"),
        ),
        sa.CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name=op.f("ck_resources_date_order"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(details) = 'object'", name=op.f("ck_resources_details_object")
        ),
        sa.CheckConstraint(
            "btrim(code) <> '' AND btrim(name) <> ''",
            name=op.f("ck_resources_required_text_nonblank"),
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'active', 'released')",
            name=op.f("ck_resources_status_allowed"),
        ),
        sa.CheckConstraint(
            "resource_type IN ('person', 'equipment', 'facility', 'capability')",
            name=op.f("ck_resources_type_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "assigned_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_resources_tenant_user",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["cehub_project.projects.tenant_id", "cehub_project.projects.id"],
            name="fk_resources_tenant_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["cehub_core.tenants.id"],
            name=op.f("fk_resources_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resources")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_resources_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id", "project_id", "code", name="uq_resources_tenant_project_code"
        ),
        schema="cehub_project",
    )
    op.create_index(
        "ix_resources_tenant_project_status",
        "resources",
        ["tenant_id", "project_id", "status"],
        unique=False,
        schema="cehub_project",
    )


def downgrade() -> None:
    connection = op.get_bind()
    populated_tables = connection.execute(
        sa.text(
            """
            SELECT
                (SELECT count(*) FROM cehub_project.crm_requirement_intakes)
              + (SELECT count(*) FROM cehub_supplier.suppliers)
              + (SELECT count(*) FROM cehub_cost.costs)
              + (SELECT count(*) FROM cehub_project.resources)
            """
        )
    ).scalar_one()
    if populated_tables:
        raise RuntimeError(
            "refusing lossy downgrade while CRM, Supplier, Cost, or Resource rows exist"
        )

    op.drop_index(
        "ix_resources_tenant_project_status", table_name="resources", schema="cehub_project"
    )
    op.drop_table("resources", schema="cehub_project")
    op.drop_index("ix_costs_tenant_project_status", table_name="costs", schema="cehub_cost")
    op.drop_table("costs", schema="cehub_cost")
    op.drop_index(
        "ix_crm_intakes_tenant_status",
        table_name="crm_requirement_intakes",
        schema="cehub_project",
    )
    op.drop_table("crm_requirement_intakes", schema="cehub_project")
    op.drop_index("ix_suppliers_tenant_status", table_name="suppliers", schema="cehub_supplier")
    op.drop_table("suppliers", schema="cehub_supplier")
    op.drop_constraint(
        "uq_events_tenant_id_id",
        "events",
        schema="cehub_event",
        type_="unique",
    )
