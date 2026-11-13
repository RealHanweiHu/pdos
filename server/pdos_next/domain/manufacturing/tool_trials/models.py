"""Tooling record and tool-trial version chains (D305)."""

# ruff: noqa: E501 -- PostgreSQL predicates remain readable as full expressions.

from uuid import UUID

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.core.models import Base, Row
from pdos_next.domain.named_records.models import (
    CurrentColumns,
    VersionColumns,
    current_args,
    fk,
    product_fk,
    version_args,
)

from .schemas import OPERATION

TOOLING_VERSIONS = "tooling_versions"
TOOLING_CURRENTS = "tooling_currents"
TRIAL_VERSIONS = "tool_trial_versions"
TRIAL_CURRENTS = "tool_trial_currents"
TOOLING_BINDING = ("tenant_id", "category_id", "product_id", "project_id", "owner_id", "visibility")
TRIAL_BINDING = (
    "tenant_id",
    "category_id",
    "product_id",
    "project_id",
    "build_id",
    "owner_id",
    "visibility",
)


def _project_scope():
    return (
        product_fk(),
        fk(
            ("tenant_id", "product_id", "project_id"), "projects", ("tenant_id", "product_id", "id")
        ),
        fk(("tenant_id", "owner_id"), "principals", ("tenant_id", "id")),
    )


def _build_scope():
    return (
        product_fk(),
        fk(
            ("tenant_id", "product_id", "project_id", "build_id"),
            "builds",
            ("tenant_id", "product_id", "project_id", "id"),
        ),
        fk(("tenant_id", "owner_id"), "principals", ("tenant_id", "id")),
    )


class _ToolingScope(Row):
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))


class _TrialScope(Row):
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))


class ToolingVersion(VersionColumns, _ToolingScope, Base):
    __tablename__ = TOOLING_VERSIONS
    resource_id: Mapped[UUID | None]
    __table_args__ = (
        *_project_scope(),
        *version_args(
            TOOLING_VERSIONS,
            TOOLING_BINDING,
            operations=(OPERATION,),
            actions=("create", "revise"),
            states=("active",),
            prefix="tooling",
            body_check="body->>'project_id'=project_id::text AND (body->>'cavities')::integer>0",
        ),
    )


class ToolingCurrent(CurrentColumns, _ToolingScope, Base):
    __tablename__ = TOOLING_CURRENTS
    __table_args__ = (
        *_project_scope(),
        *current_args(TOOLING_VERSIONS, TOOLING_BINDING, states=("active",), prefix="tooling"),
    )


class ToolTrialVersion(VersionColumns, _TrialScope, Base):
    __tablename__ = TRIAL_VERSIONS
    tooling_id: Mapped[UUID]
    tooling_revision: Mapped[int]
    request_id: Mapped[UUID]
    __table_args__ = (
        *_build_scope(),
        *version_args(
            TRIAL_VERSIONS,
            TRIAL_BINDING,
            operations=(OPERATION,),
            actions=("create",),
            states=("created",),
            prefix="tool_trial",
            body_check="body->>'build_id'=build_id::text AND body->'tooling'->>'id'=tooling_id::text "
            "AND (body->'tooling'->>'revision')::integer=tooling_revision AND body->>'request_id'=request_id::text",
        ),
    )


class ToolTrialCurrent(CurrentColumns, _TrialScope, Base):
    __tablename__ = TRIAL_CURRENTS
    __table_args__ = (
        *_build_scope(),
        *current_args(TRIAL_VERSIONS, TRIAL_BINDING, states=("created",), prefix="tool_trial"),
    )
