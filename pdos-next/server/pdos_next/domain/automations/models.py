"""Owner-managed manual automation versions and actual human run admissions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row

VERSION = "automation_rule_versions"
CURRENT = "automation_rule_currents"
OCCURRENCE = "automation_trigger_occurrences"
SUBJECT = "automation_rule"
OPERATIONS = ("ai.automation.draft.save", "ai.automation.activate", "ai.automation.pause")
BINDING = ("tenant_id", "category_id", "owner_id", "rule_id")


def _fk(local, table, remote, **options):
    return ForeignKeyConstraint(list(local), [f"{table}.{key}" for key in remote], **options)


def _scope():
    return (
        _fk(("tenant_id", "category_id"), "categories", ("tenant_id", "id")),
        _fk(("tenant_id", "owner_id"), "principals", ("tenant_id", "id")),
    )


class AutomationRuleVersion(Row, Base):
    __tablename__ = VERSION
    category_id: Mapped[UUID] = mapped_column(index=True)
    rule_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(16))
    owner_id: Mapped[UUID]
    actor_id: Mapped[UUID]
    requester_id: Mapped[UUID]
    operation: Mapped[str] = mapped_column(String(80))
    spec: Mapped[dict] = mapped_column(JSONB)
    spec_sha256: Mapped[str] = mapped_column(String(64))
    command_id: Mapped[UUID]
    command: Mapped[dict] = mapped_column(JSONB)
    request_digest: Mapped[str] = mapped_column(String(64))
    intent_digest: Mapped[str] = mapped_column(String(64))
    receipt_id: Mapped[UUID]
    confirmation_id: Mapped[UUID | None]

    @property
    def status(self):
        return self.state

    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint(*BINDING, "revision"),
        UniqueConstraint(*BINDING, "id", "revision"),
        UniqueConstraint(*BINDING, "id"),
        UniqueConstraint("tenant_id", "receipt_id"),
        UniqueConstraint("tenant_id", "command_id"),
        _fk(
            (*BINDING, "previous_id", "previous_revision"),
            VERSION,
            (*BINDING, "id", "revision"),
        ),
        *(
            _fk(("tenant_id", key), "principals", ("tenant_id", "id"))
            for key in ("actor_id", "requester_id")
        ),
        *(
            _fk(
                ("tenant_id", key),
                table,
                ("tenant_id", "id"),
                deferrable=True,
                initially="DEFERRED",
            )
            for key, table in (
                ("receipt_id", "action_receipts"),
                ("confirmation_id", "confirmations"),
            )
        ),
        CheckConstraint("owner_id=actor_id AND actor_id=requester_id"),
        CheckConstraint(
            "(revision=1 AND action='draft' AND previous_id IS NULL "
            "AND previous_revision IS NULL) OR (revision>1 AND previous_id IS NOT NULL "
            "AND previous_id<>id AND previous_revision=revision-1)"
        ),
        CheckConstraint(
            "(action='draft' AND state='draft' AND operation='ai.automation.draft.save' "
            "AND confirmation_id IS NULL) OR (action='activate' AND state='active' "
            "AND operation='ai.automation.activate' AND confirmation_id IS NOT NULL) OR "
            "(action='pause' AND state='paused' AND operation='ai.automation.pause' "
            "AND confirmation_id IS NOT NULL)"
        ),
        CheckConstraint("jsonb_typeof(spec)='object' AND jsonb_typeof(command)='object'"),
        CheckConstraint(
            "spec_sha256 ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$' "
            "AND intent_digest ~ '^[a-f0-9]{64}$'"
        ),
    )


class AutomationRuleCurrent(Row, Base):
    __tablename__ = CURRENT
    category_id: Mapped[UUID] = mapped_column(index=True)
    owner_id: Mapped[UUID]
    rule_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    version_id: Mapped[UUID]
    state: Mapped[str] = mapped_column(String(16))
    draft_version_id: Mapped[UUID | None]
    published_version_id: Mapped[UUID | None]
    admitted_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_admitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "rule_id"),
        _fk((*BINDING, "version_id", "revision"), VERSION, (*BINDING, "id", "revision")),
        *(
            _fk((*BINDING, key), VERSION, (*BINDING, "id"))
            for key in ("draft_version_id", "published_version_id")
        ),
        CheckConstraint("revision>0 AND state IN ('draft','active','paused')"),
        CheckConstraint(
            "admitted_count>=0 AND ((admitted_count=0 AND last_admitted_at IS NULL) "
            "OR (admitted_count>0 AND last_admitted_at IS NOT NULL))"
        ),
    )


class AutomationTriggerOccurrence(Row, Base):
    __tablename__ = OCCURRENCE
    category_id: Mapped[UUID] = mapped_column(index=True)
    owner_id: Mapped[UUID]
    rule_id: Mapped[UUID]
    published_version_id: Mapped[UUID]
    run_id: Mapped[UUID]
    requester_id: Mapped[UUID]
    intent_key: Mapped[str] = mapped_column(String(149))
    request_digest: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "run_id"),
        UniqueConstraint("tenant_id", "owner_id", "intent_key"),
        _fk((*BINDING, "published_version_id"), VERSION, (*BINDING, "id")),
        _fk(("tenant_id", "run_id"), "agent_runs", ("tenant_id", "id")),
        _fk(("tenant_id", "requester_id"), "principals", ("tenant_id", "id")),
        CheckConstraint("requester_id=owner_id AND length(intent_key)>0"),
        CheckConstraint("request_digest ~ '^[a-f0-9]{64}$'"),
    )
