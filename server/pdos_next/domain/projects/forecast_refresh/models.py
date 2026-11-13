"""Append-only forecast refreshes and one exact Current per project.

A refresh stores computed times, keys and identities only. It never changes a
plan revision, a planned task, a baseline or any commitment (I08).
"""

# ruff: noqa: E501 -- PostgreSQL predicates remain readable as full expressions.

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

from pdos_next.core.models import Base, Row

from .schemas import OPERATION

REFRESHES = "work_forecast_refreshes"
CURRENTS = "work_forecast_currents"
BINDING = ("tenant_id", "category_id", "product_id", "project_id", "owner_id", "visibility")


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


class _Scope(Row):
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))


class WorkForecastRefresh(_Scope, Base):
    __tablename__ = REFRESHES
    revision: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    plan_id: Mapped[UUID]
    plan_revision: Mapped[int] = mapped_column(Integer)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    input_sha256: Mapped[str] = mapped_column(String(64))
    algorithm_version: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16))
    result: Mapped[dict] = mapped_column(JSONB)
    result_sha256: Mapped[str] = mapped_column(String(64))
    writer_id: Mapped[UUID]
    actor_id: Mapped[UUID]
    requester_id: Mapped[UUID]
    operation: Mapped[str] = mapped_column(String(80))
    command_id: Mapped[UUID]
    request_digest: Mapped[str] = mapped_column(String(64))
    receipt_id: Mapped[UUID]

    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "receipt_id"),
        UniqueConstraint("tenant_id", "command_id"),
        UniqueConstraint("tenant_id", "product_id", "project_id", "revision"),
        UniqueConstraint(*BINDING, "id", "revision"),
        _fk(
            ("tenant_id", "product_id", "project_id", "plan_id"),
            "plan_revisions",
            ("tenant_id", "product_id", "project_id", "id"),
        ),
        *(
            _fk(("tenant_id", name), "principals", ("tenant_id", "id"))
            for name in ("writer_id", "actor_id", "requester_id")
        ),
        _fk(
            ("tenant_id", "receipt_id"),
            "action_receipts",
            ("tenant_id", "id"),
            deferrable=True,
            initially="DEFERRED",
        ),
        _fk(
            (*BINDING, "previous_id", "previous_revision"), REFRESHES, (*BINDING, "id", "revision")
        ),
        CheckConstraint(
            "(revision=1 AND previous_id IS NULL AND previous_revision IS NULL) OR "
            "(revision>1 AND previous_id IS NOT NULL AND previous_id<>id AND previous_revision=revision-1)",
            name="work_forecast_refresh_chain",
        ),
        CheckConstraint(
            f"operation='{OPERATION}' AND writer_id=actor_id AND plan_revision>0 AND as_of<=created_at",
            name="work_forecast_refresh_t0_engine",
        ),
        CheckConstraint(
            "status IN ('complete','partial','invalid')", name="work_forecast_refresh_status"
        ),
        CheckConstraint(
            "jsonb_typeof(result)='object' AND result->>'input_sha256'=input_sha256 "
            "AND result->>'algorithm_version'=algorithm_version AND result->>'status'=status "
            "AND input_sha256 ~ '^[a-f0-9]{64}$' AND result_sha256 ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$'",
            name="work_forecast_refresh_result",
        ),
    )


class WorkForecastCurrent(_Scope, Base):
    __tablename__ = CURRENTS
    version_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "project_id"),
        _fk((*BINDING, "version_id", "revision"), REFRESHES, (*BINDING, "id", "revision")),
        CheckConstraint("revision>0", name="work_forecast_current_revision"),
    )
