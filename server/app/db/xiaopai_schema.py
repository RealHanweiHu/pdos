"""Persistent project delegation state and append-only follow-up receipts."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB


def define_xiaopai_tables(metadata: MetaData) -> tuple[Table, Table, Table]:
    delegations = Table(
        "xiaopai_delegations",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("tenant_id", Uuid, nullable=False),
        Column("project_id", Uuid, nullable=False),
        Column("created_by_user_id", Uuid, nullable=False),
        Column("conversation_id", Uuid, nullable=False),
        Column("request_id", Uuid, nullable=False),
        Column("goal", Text, nullable=False),
        Column("status", String(16), nullable=False, server_default=text("'active'")),
        Column("calendar", JSONB, nullable=False),
        Column("digest_hour", Integer, nullable=False, server_default=text("9")),
        Column("expires_at", DateTime(timezone=True)),
        Column("checked_at", DateTime(timezone=True)),
        Column("result", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
        Column("version", Integer, nullable=False, server_default=text("1")),
        Column(
            "created_at",
            DateTime(timezone=True),
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
        Column(
            "updated_at",
            DateTime(timezone=True),
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
        UniqueConstraint("tenant_id", "project_id", "id", name="uq_xiaopai_delegation_scope"),
        UniqueConstraint(
            "tenant_id", "created_by_user_id", "request_id", name="uq_xiaopai_delegation_request"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "project_id", "conversation_id"],
            [f"cehub_ai.conversations.{k}" for k in ("tenant_id", "project_id", "id")],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            [f"cehub_core.users.{k}" for k in ("tenant_id", "id")],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('active','paused','stopped','completed','blocked')", name="status"
        ),
        CheckConstraint(
            "char_length(btrim(goal)) BETWEEN 1 AND 2000 "
            "AND version>0 AND digest_hour BETWEEN 0 AND 23",
            name="bounds",
        ),
        schema="cehub_ai",
    )
    followups = Table(
        "xiaopai_followups",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("tenant_id", Uuid, nullable=False),
        Column("project_id", Uuid, nullable=False),
        Column("delegation_id", Uuid, nullable=False),
        Column("task_id", Uuid, nullable=False),
        Column("recipient_user_id", Uuid, nullable=False),
        Column("source_digest", String(64), nullable=False),
        Column("status", String(24), nullable=False),
        Column("requested_at", DateTime(timezone=True), nullable=False),
        Column("delivered_at", DateTime(timezone=True)),
        Column("reply_due_at", DateTime(timezone=True)),
        Column("checkpoint_at", DateTime(timezone=True)),
        Column("reply", Text),
        Column("reply_request_id", Uuid),
        Column("replied_at", DateTime(timezone=True)),
        Column("updated_at", DateTime(timezone=True), nullable=False),
        UniqueConstraint("tenant_id", "project_id", "id", name="uq_xiaopai_followup_scope"),
        UniqueConstraint(
            "delegation_id", "task_id", "source_digest", name="uq_xiaopai_followup_source"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "project_id", "delegation_id"],
            [f"cehub_ai.xiaopai_delegations.{k}" for k in ("tenant_id", "project_id", "id")],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "project_id", "task_id"],
            [f"cehub_project.tasks.{k}" for k in ("tenant_id", "project_id", "id")],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "recipient_user_id"],
            [f"cehub_core.users.{k}" for k in ("tenant_id", "id")],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('pending','waiting_reply','waiting_progress','no_reply',"
            "'no_progress','resolved','cancelled','blocked')",
            name="status",
        ),
        CheckConstraint("source_digest ~ '^[a-f0-9]{64}$'", name="digest"),
        schema="cehub_ai",
    )
    receipts = Table(
        "xiaopai_receipts",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("tenant_id", Uuid, nullable=False),
        Column("project_id", Uuid, nullable=False),
        Column("delegation_id", Uuid, nullable=False),
        Column("kind", String(24), nullable=False),
        Column("request_key", String(160), nullable=False),
        Column("content", JSONB, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        UniqueConstraint("delegation_id", "request_key", name="uq_xiaopai_receipt_request"),
        ForeignKeyConstraint(
            ["tenant_id", "project_id", "delegation_id"],
            [f"cehub_ai.xiaopai_delegations.{k}" for k in ("tenant_id", "project_id", "id")],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "kind IN ('created','state','reply','daily_digest','observation')", name="kind"
        ),
        schema="cehub_ai",
    )
    return delegations, followups, receipts
