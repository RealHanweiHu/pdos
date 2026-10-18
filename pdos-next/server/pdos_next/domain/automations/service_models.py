"""Fixed T1 service grants, causal budgets and one-terminal-state host attempts."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row

GRANT = "automation_service_grants"
CHAIN = "automation_causal_chains"
ATTEMPT = "automation_service_attempts"
RULE_BINDING = ("tenant_id", "category_id", "owner_id", "rule_id", "published_version_id")
SERVICE_BINDING = (*RULE_BINDING, "writer_id")


def _fk(local, table, remote, **options):
    return ForeignKeyConstraint(list(local), [f"{table}.{key}" for key in remote], **options)


def _scope():
    return (
        _fk(("tenant_id", "category_id"), "categories", ("tenant_id", "id")),
        _fk(("tenant_id", "owner_id"), "principals", ("tenant_id", "id")),
    )


class AutomationServiceGrant(Row, Base):
    __tablename__ = GRANT
    category_id: Mapped[UUID] = mapped_column(index=True)
    owner_id: Mapped[UUID]
    writer_id: Mapped[UUID]
    rule_id: Mapped[UUID]
    published_version_id: Mapped[UUID]
    receipt_id: Mapped[UUID]
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "published_version_id"),
        UniqueConstraint(*SERVICE_BINDING, "id"),
        UniqueConstraint("tenant_id", "category_id", "owner_id", "id"),
        _fk(
            RULE_BINDING,
            "automation_rule_versions",
            ("tenant_id", "category_id", "owner_id", "rule_id", "id"),
        ),
        _fk(("tenant_id", "writer_id"), "principals", ("tenant_id", "id")),
        _fk(
            ("tenant_id", "receipt_id"),
            "action_receipts",
            ("tenant_id", "id"),
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("owner_id<>writer_id"),
    )


class AutomationCausalChain(Row, Base):
    __tablename__ = CHAIN
    category_id: Mapped[UUID] = mapped_column(index=True)
    owner_id: Mapped[UUID]
    root_grant_id: Mapped[UUID]
    budget: Mapped[dict] = mapped_column(JSONB)
    max_depth: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "id"),
        _fk(
            ("tenant_id", "category_id", "owner_id", "root_grant_id"),
            GRANT,
            ("tenant_id", "category_id", "owner_id", "id"),
        ),
        CheckConstraint("max_depth>=0 AND jsonb_typeof(budget)='object'"),
    )


class AutomationServiceAttempt(Row, Base):
    __tablename__ = ATTEMPT
    category_id: Mapped[UUID] = mapped_column(index=True)
    owner_id: Mapped[UUID]
    writer_id: Mapped[UUID]
    rule_id: Mapped[UUID]
    published_version_id: Mapped[UUID]
    service_grant_id: Mapped[UUID]
    chain_id: Mapped[UUID]
    parent_run_id: Mapped[UUID | None]
    depth: Mapped[int] = mapped_column(Integer)
    trigger_kind: Mapped[str] = mapped_column(String(32))
    trigger_key: Mapped[str] = mapped_column(String(200))
    origin: Mapped[dict] = mapped_column(JSONB)
    request_digest: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(80))
    run_id: Mapped[UUID | None]
    admitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "service_grant_id", "trigger_key"),
        UniqueConstraint("tenant_id", "run_id"),
        _fk((*SERVICE_BINDING, "service_grant_id"), GRANT, (*SERVICE_BINDING, "id")),
        _fk(("tenant_id", "chain_id"), CHAIN, ("tenant_id", "id")),
        _fk(("tenant_id", "parent_run_id"), "agent_runs", ("tenant_id", "id")),
        _fk(
            ("tenant_id", "run_id"),
            "agent_runs",
            ("tenant_id", "id"),
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("depth>=0 AND length(trigger_key)>0"),
        CheckConstraint("trigger_kind IN ('schedule','domain_event','relative_milestone')"),
        CheckConstraint("jsonb_typeof(origin)='object' AND request_digest ~ '^[a-f0-9]{64}$'"),
        CheckConstraint(
            "(state='queued' AND run_id IS NULL AND admitted_at IS NULL AND error_code IS NULL) OR "
            "(state='admitted' AND run_id IS NOT NULL AND admitted_at IS NOT NULL "
            "AND error_code IS NULL) OR (state='suppressed' AND run_id IS NULL "
            "AND admitted_at IS NULL AND error_code IS NOT NULL "
            "AND error_code ~ '^[A-Z][A-Z0-9_]{0,79}$')"
        ),
        CheckConstraint(
            "(depth=0 AND parent_run_id IS NULL) OR (depth>0 AND parent_run_id IS NOT NULL)"
        ),
        Index("ix_automation_service_queue", "tenant_id", "state", "due_at", "id"),
        Index("ix_automation_service_chain", "tenant_id", "chain_id", "state", "run_id"),
    )
