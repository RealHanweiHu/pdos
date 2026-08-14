"""add event stream and immutable audit log

Revision ID: 0003_events_audit
Revises: 0002_rbac
Create Date: 2026-08-10 23:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision: str = "0003_events_audit"
down_revision: str | Sequence[str] | None = "0002_rbac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVENT_SCHEMA = "cehub_event"
AUDIT_SCHEMA = "cehub_audit"


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.SmallInteger(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("entity", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "schema_version > 0",
            name=op.f("ck_events_schema_version_positive"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name=op.f("ck_events_payload_object"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["cehub_project.projects.tenant_id", "cehub_project.projects.id"],
            name="fk_events_tenant_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["cehub_core.tenants.id"],
            name="fk_events_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_events"),
        sa.UniqueConstraint("source", "event_id", name="uq_events_source_event_id"),
        schema=EVENT_SCHEMA,
    )
    op.create_index(
        "ix_events_event_type_id",
        "events",
        ["event_type", "id"],
        unique=False,
        schema=EVENT_SCHEMA,
    )
    op.create_index(
        "ix_events_tenant_id",
        "events",
        ["tenant_id", "id"],
        unique=False,
        schema=EVENT_SCHEMA,
    )
    op.create_index(
        "ix_events_tenant_project_id",
        "events",
        ["tenant_id", "project_id", "id"],
        unique=False,
        schema=EVENT_SCHEMA,
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("entity", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column(
            "before_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "after_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "context",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(before_snapshot IS NOT NULL AND jsonb_typeof(before_snapshot) = 'object') "
            "OR (after_snapshot IS NOT NULL AND jsonb_typeof(after_snapshot) = 'object')",
            name=op.f("ck_audit_log_snapshot_present"),
        ),
        sa.CheckConstraint(
            "before_snapshot IS NULL OR jsonb_typeof(before_snapshot) = 'object'",
            name=op.f("ck_audit_log_before_snapshot_object"),
        ),
        sa.CheckConstraint(
            "after_snapshot IS NULL OR jsonb_typeof(after_snapshot) = 'object'",
            name=op.f("ck_audit_log_after_snapshot_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(context) = 'object'",
            name=op.f("ck_audit_log_context_object"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_audit_log_tenant_actor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["cehub_project.projects.tenant_id", "cehub_project.projects.id"],
            name="fk_audit_log_tenant_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["cehub_core.tenants.id"],
            name="fk_audit_log_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
        schema=AUDIT_SCHEMA,
    )
    op.create_index(
        "ix_audit_log_entity_id",
        "audit_log",
        ["entity", "entity_id", "id"],
        unique=False,
        schema=AUDIT_SCHEMA,
    )
    op.create_index(
        "ix_audit_log_tenant_id",
        "audit_log",
        ["tenant_id", "id"],
        unique=False,
        schema=AUDIT_SCHEMA,
    )
    op.create_index(
        "ix_audit_log_tenant_project_id",
        "audit_log",
        ["tenant_id", "project_id", "id"],
        unique=False,
        schema=AUDIT_SCHEMA,
    )
    op.execute(
        sa.text(
            """
            CREATE FUNCTION cehub_audit.reject_audit_log_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'cehub_audit.audit_log is append-only';
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER audit_log_immutable
            BEFORE UPDATE OR DELETE ON cehub_audit.audit_log
            FOR EACH ROW EXECUTE FUNCTION cehub_audit.reject_audit_log_mutation()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER audit_log_immutable ON cehub_audit.audit_log"))
    op.execute(sa.text("DROP FUNCTION cehub_audit.reject_audit_log_mutation()"))
    op.drop_index(
        "ix_audit_log_tenant_project_id",
        table_name="audit_log",
        schema=AUDIT_SCHEMA,
    )
    op.drop_index(
        "ix_audit_log_tenant_id",
        table_name="audit_log",
        schema=AUDIT_SCHEMA,
    )
    op.drop_index(
        "ix_audit_log_entity_id",
        table_name="audit_log",
        schema=AUDIT_SCHEMA,
    )
    op.drop_table("audit_log", schema=AUDIT_SCHEMA)
    op.drop_index(
        "ix_events_tenant_project_id",
        table_name="events",
        schema=EVENT_SCHEMA,
    )
    op.drop_index(
        "ix_events_tenant_id",
        table_name="events",
        schema=EVENT_SCHEMA,
    )
    op.drop_index(
        "ix_events_event_type_id",
        table_name="events",
        schema=EVENT_SCHEMA,
    )
    op.drop_table("events", schema=EVENT_SCHEMA)
