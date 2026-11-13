"""Fixture acceptance versions and one exact Current per fixture × purpose × operation."""

# ruff: noqa: E501 -- PostgreSQL predicates remain readable as full expressions.

from uuid import UUID

from sqlalchemy import String, UniqueConstraint
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

from .schemas import ACTIONS, OPERATION, STATES

VERSIONS = "fixture_acceptance_versions"
CURRENTS = "fixture_acceptance_currents"
BINDING = (
    "tenant_id",
    "category_id",
    "product_id",
    "project_id",
    "resource_id",
    "purpose",
    "operation_id",
    "owner_id",
    "visibility",
)


def _scope():
    return (
        product_fk(),
        fk(
            ("tenant_id", "product_id", "project_id"), "projects", ("tenant_id", "product_id", "id")
        ),
        fk(("tenant_id", "owner_id"), "principals", ("tenant_id", "id")),
    )


class _Scope(Row):
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    resource_id: Mapped[UUID]
    purpose: Mapped[str] = mapped_column(String(200))
    operation_id: Mapped[str] = mapped_column(String(200))
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))


class FixtureAcceptanceVersion(VersionColumns, _Scope, Base):
    __tablename__ = VERSIONS
    __table_args__ = (
        *_scope(),
        *version_args(
            VERSIONS,
            BINDING,
            operations=(OPERATION,),
            actions=ACTIONS,
            states=STATES,
            create_states=("accepted", "rejected"),
            first_actions=("accept", "reject"),
            later_actions=ACTIONS,
            prefix="fixture_acceptance",
            body_check="body->>'resource_id'=resource_id::text AND body->>'project_id'=project_id::text "
            "AND body->>'purpose'=purpose AND body->>'operation_id'=operation_id",
        ),
    )


class FixtureAcceptanceCurrent(CurrentColumns, _Scope, Base):
    __tablename__ = CURRENTS
    __table_args__ = (
        *_scope(),
        *current_args(VERSIONS, BINDING, states=STATES, prefix="fixture_acceptance"),
        # One decision chain per fixture, purpose and operation in a project.
        UniqueConstraint(
            "tenant_id", "product_id", "project_id", "resource_id", "purpose", "operation_id"
        ),
    )
