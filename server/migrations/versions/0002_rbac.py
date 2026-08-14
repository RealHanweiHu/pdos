"""add frozen roles and tenant-safe project memberships

Revision ID: 0002_rbac
Revises: 0001_initial_entities
Create Date: 2026-08-10 23:01:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "0002_rbac"
down_revision: str | Sequence[str] | None = "0001_initial_entities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CORE_SCHEMA = "cehub_core"
PROJECT_SCHEMA = "cehub_project"
ROLE_CHECK = (
    "role IN ('owner', 'admin', 'project_manager', 'engineer', 'quality', 'supplier', 'customer')"
)


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=32), nullable=True),
        schema=CORE_SCHEMA,
    )
    op.execute(
        sa.text(
            """
            WITH ranked_users AS (
                SELECT
                    id,
                    tenant_id,
                    row_number() OVER (
                        PARTITION BY tenant_id
                        ORDER BY created_at ASC, id ASC
                    ) AS tenant_rank
                FROM cehub_core.users
            )
            UPDATE cehub_core.users AS users
            SET role = CASE
                WHEN ranked_users.tenant_rank = 1 THEN 'owner'
                ELSE 'engineer'
            END
            FROM ranked_users
            WHERE users.id = ranked_users.id
              AND users.tenant_id = ranked_users.tenant_id
            """
        )
    )
    op.alter_column(
        "users",
        "role",
        existing_type=sa.String(length=32),
        nullable=False,
        schema=CORE_SCHEMA,
    )
    op.create_check_constraint(
        op.f("ck_users_role_allowed"),
        "users",
        ROLE_CHECK,
        schema=CORE_SCHEMA,
    )

    op.create_table(
        "project_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("added_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "added_by_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_project_members_tenant_added_by",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["cehub_project.projects.tenant_id", "cehub_project.projects.id"],
            name="fk_project_members_tenant_project",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_project_members_tenant_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["cehub_core.tenants.id"],
            name="fk_project_members_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_project_members"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_project_members_tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "user_id",
            name="uq_project_members_tenant_project_user",
        ),
        schema=PROJECT_SCHEMA,
    )
    op.create_index(
        "ix_project_members_tenant_project",
        "project_members",
        ["tenant_id", "project_id"],
        unique=False,
        schema=PROJECT_SCHEMA,
    )
    op.create_index(
        "ix_project_members_tenant_user",
        "project_members",
        ["tenant_id", "user_id"],
        unique=False,
        schema=PROJECT_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_members_tenant_user",
        table_name="project_members",
        schema=PROJECT_SCHEMA,
    )
    op.drop_index(
        "ix_project_members_tenant_project",
        table_name="project_members",
        schema=PROJECT_SCHEMA,
    )
    op.drop_table("project_members", schema=PROJECT_SCHEMA)
    op.drop_constraint(
        op.f("ck_users_role_allowed"),
        "users",
        type_="check",
        schema=CORE_SCHEMA,
    )
    op.drop_column("users", "role", schema=CORE_SCHEMA)
