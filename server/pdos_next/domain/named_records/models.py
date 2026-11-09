"""Shared columns and constraints for D47 human-decided version chains.

Each loop declares its own two tables (append-only versions plus one exact
Current per record) and its own scope; this module only keeps the common
lineage, authorship, receipt and digest columns identical across them. Every
row here is written by a named person (T1 one confirmation or T2 named
decision), so writer, actor and requester are the same human.
"""

# ruff: noqa: E501 -- PostgreSQL predicates remain readable as full expressions.

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


def fk(local, table, remote, **options):
    return ForeignKeyConstraint(list(local), [f"{table}.{name}" for name in remote], **options)


def product_fk():
    return fk(
        ("tenant_id", "category_id", "product_id"), "products", ("tenant_id", "category_id", "id")
    )


def quoted(values):
    return ",".join(repr(value) for value in values)


class VersionColumns:
    record_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(24))
    state: Mapped[str] = mapped_column(String(24))
    writer_id: Mapped[UUID]
    actor_id: Mapped[UUID]
    requester_id: Mapped[UUID]
    operation: Mapped[str] = mapped_column(String(80))
    command_id: Mapped[UUID]
    command: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    reads: Mapped[list] = mapped_column(JSONB)
    body: Mapped[dict] = mapped_column(JSONB)
    body_sha256: Mapped[str] = mapped_column(String(64))
    intent_digest: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))
    receipt_id: Mapped[UUID]

    @property
    def status(self):
        return self.state


class CurrentColumns:
    record_id: Mapped[UUID]
    version_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(24))


VERSION_COLUMNS = (
    "record_id",
    "revision",
    "previous_id",
    "previous_revision",
    "action",
    "state",
    "writer_id",
    "actor_id",
    "requester_id",
    "operation",
    "command_id",
    "command",
    "sources",
    "reads",
    "body",
    "body_sha256",
    "intent_digest",
    "request_digest",
    "receipt_id",
    "id",
    "tenant_id",
    "created_at",
    "category_id",
)
CURRENT_COLUMNS = (
    "record_id",
    "version_id",
    "revision",
    "state",
    "id",
    "tenant_id",
    "created_at",
    "category_id",
)


def version_args(
    table,
    binding,
    *,
    operations,
    actions,
    states,
    prefix,
    create_states=None,
    body_check="",
    first_actions=None,
    later_actions=None,
):
    """Lineage, authorship, receipt and digest constraints shared by every chain."""
    first = create_states or states
    extra = f" AND {body_check}" if body_check else ""
    opening = f"action IN ({quoted(first_actions)})" if first_actions else "action='create'"
    following = f"action IN ({quoted(later_actions)})" if later_actions else "action<>'create'"
    return (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "receipt_id"),
        UniqueConstraint("tenant_id", "command_id"),
        UniqueConstraint("tenant_id", "product_id", "record_id", "revision"),
        UniqueConstraint(*binding, "record_id", "id", "revision"),
        *(
            fk(("tenant_id", name), "principals", ("tenant_id", "id"))
            for name in ("writer_id", "actor_id", "requester_id")
        ),
        fk(
            ("tenant_id", "receipt_id"),
            "action_receipts",
            ("tenant_id", "id"),
            deferrable=True,
            initially="DEFERRED",
        ),
        fk(
            (*binding, "record_id", "previous_id", "previous_revision"),
            table,
            (*binding, "record_id", "id", "revision"),
        ),
        CheckConstraint(
            f"(revision=1 AND record_id=id AND {opening} AND state IN ({quoted(first)}) AND previous_id IS NULL AND previous_revision IS NULL) OR "
            f"(revision>1 AND {following} AND previous_id IS NOT NULL AND previous_id<>id AND previous_revision=revision-1)",
            name=f"{prefix}_chain",
        ),
        CheckConstraint(
            f"operation IN ({quoted(operations)}) AND writer_id=actor_id AND actor_id=requester_id",
            name=f"{prefix}_named_person",
        ),
        CheckConstraint(f"state IN ({quoted(states)})", name=f"{prefix}_state"),
        CheckConstraint(f"action IN ({quoted(actions)})", name=f"{prefix}_action"),
        CheckConstraint(
            "jsonb_typeof(command)='object' AND jsonb_typeof(body)='object' AND jsonb_typeof(sources)='array' "
            "AND jsonb_typeof(reads)='array' AND body->>'record_id'=record_id::text "
            f"AND (body->>'revision')::integer=revision AND body->>'state'=state{extra}",
            name=f"{prefix}_body",
        ),
        CheckConstraint(
            "body_sha256 ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$' AND intent_digest ~ '^[a-f0-9]{64}$'",
            name=f"{prefix}_digests",
        ),
    )


def current_args(versions, binding, *, states, prefix):
    return (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "record_id"),
        fk(
            (*binding, "record_id", "version_id", "revision"),
            versions,
            (*binding, "record_id", "id", "revision"),
        ),
        CheckConstraint(
            f"revision>0 AND state IN ({quoted(states)})", name=f"{prefix}_current_state"
        ),
    )
