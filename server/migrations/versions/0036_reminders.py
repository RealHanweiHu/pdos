"""in-app reminder objects with idempotent dedupe keys (vNext V1-A7)

Revision ID: 0036_reminders
Revises: 0035_risk_candidates
Create Date: 2026-08-25 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036_reminders"
down_revision: str | Sequence[str] | None = "0035_risk_candidates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVENT_SCHEMA = "cehub_event"


def upgrade() -> None:
    op.create_table(
        "reminders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("cehub_core.tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(), nullable=False),
        sa.Column("policy_key", sa.String(length=64), nullable=False),
        sa.Column("target_entity", sa.String(length=64), nullable=False),
        sa.Column("target_entity_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("dedupe_key", sa.String(length=160), nullable=False),
        sa.Column("fire_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default=sa.text("'scheduled'")
        ),
        sa.Column(
            "escalation_level", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('scheduled', 'fired', 'acknowledged', 'suppressed', 'cancelled')",
            name=op.f("ck_reminders_status_allowed"),
        ),
        sa.CheckConstraint(
            "(status IN ('fired', 'acknowledged')) = (fired_at IS NOT NULL)",
            name=op.f("ck_reminders_fired_at_consistent"),
        ),
        sa.CheckConstraint(
            "(status = 'acknowledged') = (acknowledged_at IS NOT NULL)",
            name=op.f("ck_reminders_acknowledged_at_consistent"),
        ),
        sa.CheckConstraint("btrim(title) <> ''", name=op.f("ck_reminders_title_nonblank")),
        sa.CheckConstraint(
            "escalation_level >= 0", name=op.f("ck_reminders_escalation_level_nonnegative")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["cehub_project.projects.tenant_id", "cehub_project.projects.id"],
            name="fk_reminders_tenant_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "recipient_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_reminders_tenant_recipient",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_reminders_tenant_id"),
        sa.UniqueConstraint("tenant_id", "dedupe_key", name="uq_reminders_tenant_dedupe"),
        schema=EVENT_SCHEMA,
    )
    op.create_index(
        "ix_reminders_tenant_recipient_status",
        "reminders",
        ["tenant_id", "recipient_user_id", "status", "fire_at"],
        schema=EVENT_SCHEMA,
    )
    op.create_index(
        "ix_reminders_tenant_project_status",
        "reminders",
        ["tenant_id", "project_id", "status"],
        schema=EVENT_SCHEMA,
    )


def downgrade() -> None:
    connection = op.get_bind()
    reminder_rows = connection.execute(
        sa.text(f"SELECT count(*) FROM {EVENT_SCHEMA}.reminders")
    ).scalar_one()
    if reminder_rows:
        raise RuntimeError("refusing lossy downgrade while reminder rows exist")

    op.drop_index("ix_reminders_tenant_project_status", table_name="reminders", schema=EVENT_SCHEMA)
    op.drop_index(
        "ix_reminders_tenant_recipient_status", table_name="reminders", schema=EVENT_SCHEMA
    )
    op.drop_table("reminders", schema=EVENT_SCHEMA)
