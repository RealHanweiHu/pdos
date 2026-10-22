"""Append-only work facts; Current rows project one exact accepted transition."""

# ruff: noqa: E501 -- PostgreSQL predicates remain readable as full expressions.

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row

TASK = "work_task_versions"
TASK_CURRENT = "work_task_currents"
COMMITMENT = "work_commitment_versions"
COMMITMENT_CURRENT = "work_commitment_currents"
STATUS = "project_status_updates"
SCOPE = ("tenant_id", "category_id", "product_id", "project_id")
BINDING = (*SCOPE, "owner_id", "visibility")


def _fk(local, table, remote, **options):
    return ForeignKeyConstraint(list(local), [f"{table}.{name}" for name in remote], **options)


def _scope():
    return (
        _fk(
            ("tenant_id", "category_id", "product_id"),
            "products",
            ("tenant_id", "category_id", "id"),
        ),
        _fk(
            ("tenant_id", "product_id", "project_id"), "projects", ("tenant_id", "product_id", "id")
        ),
        _fk(("tenant_id", "owner_id"), "principals", ("tenant_id", "id")),
        CheckConstraint("visibility IN ('private','category','audience')"),
    )


def _fact(*, g0_task=False):
    source_requirement = "jsonb_array_length(sources)>0 AND jsonb_array_length(reads)>0"
    if g0_task:
        source_requirement = (
            f"(({source_requirement}) OR (sources='[]'::jsonb AND reads='[]'::jsonb "
            "AND g0_open_item_id IS NOT NULL AND g0_decision_id IS NOT NULL "
            "AND COALESCE(jsonb_typeof(source_basis->'g0_open_item')='object' "
            "AND source_basis->'g0_open_item'->>'id'=g0_open_item_id::text "
            "AND source_basis->'g0_open_item'->>'decision_id'=g0_decision_id::text "
            "AND source_basis->'g0_open_item'->>'digest' ~ '^[a-f0-9]{64}$',false)))"
        )
    return (
        *_scope(),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "receipt_id"),
        UniqueConstraint("tenant_id", "command_id"),
        UniqueConstraint("tenant_id", "product_id", "actor_id", "operation", "intent_digest"),
        *(
            _fk(("tenant_id", name), "principals", ("tenant_id", "id"))
            for name in ("writer_id", "actor_id", "requester_id")
        ),
        *(
            _fk(
                ("tenant_id", name),
                table,
                ("tenant_id", "id"),
                deferrable=True,
                initially="DEFERRED",
            )
            for name, table in (
                ("receipt_id", "action_receipts"),
                ("confirmation_id", "confirmations"),
            )
        ),
        CheckConstraint("writer_id=actor_id AND revision>0"),
        CheckConstraint(
            "jsonb_typeof(command)='object' AND jsonb_typeof(body)='object' AND jsonb_typeof(source_basis)='object' AND jsonb_typeof(sources)='array' AND jsonb_typeof(reads)='array' AND "
            + source_requirement,
            name="work_task_g0_sources" if g0_task else None,
        ),
        CheckConstraint(
            "body_sha256 ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$' AND intent_digest ~ '^[a-f0-9]{64}$'"
        ),
    )


class _Scope(Row):
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))


class _Fact(_Scope):
    revision: Mapped[int] = mapped_column(Integer)
    writer_id: Mapped[UUID]
    actor_id: Mapped[UUID]
    requester_id: Mapped[UUID]
    operation: Mapped[str] = mapped_column(String(80))
    command_id: Mapped[UUID]
    command: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    reads: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    body: Mapped[dict] = mapped_column(JSONB)
    body_sha256: Mapped[str] = mapped_column(String(64))
    intent_digest: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))
    receipt_id: Mapped[UUID]
    confirmation_id: Mapped[UUID | None]


class WorkTaskVersion(_Fact, Base):
    __tablename__ = TASK
    task_id: Mapped[UUID]
    previous_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(16))
    g0_open_item_id: Mapped[UUID | None]
    g0_decision_id: Mapped[UUID | None]

    @property
    def status(self):
        return self.state

    __table_args__ = (
        *_fact(g0_task=True),
        UniqueConstraint("tenant_id", "product_id", "task_id", "revision"),
        UniqueConstraint(*BINDING, "task_id", "id", "revision"),
        _fk(
            (*BINDING, "task_id", "previous_id", "previous_revision"),
            TASK,
            (*BINDING, "task_id", "id", "revision"),
        ),
        _fk(("g0_open_item_id",), "project_open_items", ("id",), name="work_task_g0_item_fk"),
        _fk(
            ("tenant_id", "category_id", "g0_decision_id"),
            "proposal_decisions",
            ("tenant_id", "category_id", "id"),
            name="work_task_g0_decision_fk",
        ),
        CheckConstraint(
            "(g0_open_item_id IS NULL)=(g0_decision_id IS NULL)", name="work_task_g0_identity"
        ),
        Index(
            "uq_work_task_g0_open_item_first",
            "tenant_id",
            "g0_open_item_id",
            unique=True,
            postgresql_where=text("revision=1 AND g0_open_item_id IS NOT NULL"),
        ),
        CheckConstraint(
            "(revision=1 AND action='create' AND state='proposed' AND previous_id IS NULL AND previous_revision IS NULL) OR (revision>1 AND previous_id IS NOT NULL AND previous_id<>id AND previous_revision=revision-1)"
        ),
        CheckConstraint(
            "(action='create' AND operation='work.task.create' AND confirmation_id IS NULL) OR (action IN ('assign','accept','start','submit','review') AND operation='work.task.'||action AND confirmation_id IS NOT NULL AND actor_id=requester_id)"
        ),
        CheckConstraint(
            "state IN ('proposed','assigned','accepted','in_progress','submitted','completed')"
        ),
    )


class WorkTaskCurrent(_Scope, Base):
    __tablename__ = TASK_CURRENT
    task_id: Mapped[UUID]
    version_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16))
    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "product_id", "task_id"),
        _fk(
            (*BINDING, "task_id", "version_id", "revision"),
            TASK,
            (*BINDING, "task_id", "id", "revision"),
        ),
        CheckConstraint(
            "revision>0 AND state IN ('proposed','assigned','accepted','in_progress','submitted','completed')"
        ),
    )


class WorkCommitmentVersion(_Fact, Base):
    __tablename__ = COMMITMENT
    series_id: Mapped[UUID]
    replaces_id: Mapped[UUID | None]
    replaces_revision: Mapped[int | None] = mapped_column(Integer)
    task_id: Mapped[UUID]
    task_revision: Mapped[int] = mapped_column(Integer)
    promisor_id: Mapped[UUID]
    recipient_id: Mapped[UUID]
    outcome_keys: Mapped[list] = mapped_column(JSONB)
    promised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_timezone: Mapped[str] = mapped_column(Text)
    calendar_id: Mapped[UUID | None]

    @property
    def status(self):
        return "recorded"

    __table_args__ = (
        *_fact(),
        UniqueConstraint("tenant_id", "product_id", "series_id", "revision"),
        UniqueConstraint(
            *BINDING, "task_id", "promisor_id", "recipient_id", "series_id", "id", "revision"
        ),
        _fk(
            ("tenant_id", "product_id", "task_id", "task_revision"),
            TASK,
            ("tenant_id", "product_id", "task_id", "revision"),
        ),
        _fk(
            (
                *BINDING,
                "task_id",
                "promisor_id",
                "recipient_id",
                "series_id",
                "replaces_id",
                "replaces_revision",
            ),
            COMMITMENT,
            (*BINDING, "task_id", "promisor_id", "recipient_id", "series_id", "id", "revision"),
        ),
        *(
            _fk(("tenant_id", name), "principals", ("tenant_id", "id"))
            for name in ("promisor_id", "recipient_id")
        ),
        CheckConstraint(
            "(revision=1 AND series_id=id AND replaces_id IS NULL AND replaces_revision IS NULL) OR (revision>1 AND replaces_id IS NOT NULL AND replaces_id<>id AND replaces_revision=revision-1)"
        ),
        CheckConstraint(
            "operation='work.commitment.accept' AND confirmation_id IS NOT NULL AND actor_id=requester_id AND promisor_id=actor_id"
        ),
        CheckConstraint(
            "task_revision>0 AND jsonb_typeof(outcome_keys)='array' AND jsonb_array_length(outcome_keys)>0 AND length(original_timezone)>0"
        ),
    )


class WorkCommitmentCurrent(_Scope, Base):
    __tablename__ = COMMITMENT_CURRENT
    task_id: Mapped[UUID]
    promisor_id: Mapped[UUID]
    recipient_id: Mapped[UUID]
    series_id: Mapped[UUID]
    version_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "product_id", "task_id", "promisor_id", "recipient_id"),
        _fk(
            (
                *BINDING,
                "task_id",
                "promisor_id",
                "recipient_id",
                "series_id",
                "version_id",
                "revision",
            ),
            COMMITMENT,
            (*BINDING, "task_id", "promisor_id", "recipient_id", "series_id", "id", "revision"),
        ),
        CheckConstraint("revision>0"),
    )


class ProjectStatusUpdate(_Fact, Base):
    __tablename__ = STATUS
    fact_summary: Mapped[str] = mapped_column(Text)
    next_steps: Mapped[str] = mapped_column(Text)
    task_refs: Mapped[list] = mapped_column(JSONB)

    @property
    def status(self):
        return "recorded"

    __table_args__ = (
        *_fact(),
        CheckConstraint(
            "revision=1 AND operation='work.status_update.create' AND confirmation_id IS NOT NULL AND actor_id=requester_id"
        ),
        CheckConstraint(
            "length(fact_summary)>0 AND length(next_steps)>0 AND jsonb_typeof(task_refs)='array'"
        ),
    )
