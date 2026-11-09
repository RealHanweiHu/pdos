"""Customer acceptance versions and one exact Current per acceptance record, under a Build."""

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

from .schemas import OPERATION, STATES

VERSIONS = "customer_acceptance_versions"
CURRENTS = "customer_acceptance_currents"
BINDING = (
    "tenant_id",
    "category_id",
    "product_id",
    "project_id",
    "build_id",
    "owner_id",
    "visibility",
)


def _scope():
    return (
        product_fk(),
        fk(
            ("tenant_id", "product_id", "project_id", "build_id"),
            "builds",
            ("tenant_id", "product_id", "project_id", "id"),
        ),
        fk(("tenant_id", "owner_id"), "principals", ("tenant_id", "id")),
    )


class _Scope(Row):
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    build_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))


class CustomerAcceptanceVersion(VersionColumns, _Scope, Base):
    __tablename__ = VERSIONS
    __table_args__ = (
        *_scope(),
        *version_args(
            VERSIONS,
            BINDING,
            operations=(OPERATION,),
            actions=("create", "revise"),
            states=STATES,
            prefix="customer_acceptance",
            body_check="body->>'build_id'=build_id::text AND jsonb_array_length(body->'scopes')=5 "
            "AND jsonb_typeof(sources)='array' AND jsonb_array_length(sources)=1",
        ),
    )


class CustomerAcceptanceCurrent(CurrentColumns, _Scope, Base):
    __tablename__ = CURRENTS
    __table_args__ = (
        *_scope(),
        *current_args(VERSIONS, BINDING, states=STATES, prefix="customer_acceptance"),
    )
