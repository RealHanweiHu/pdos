"""Interface contract versions and one exact Current, under an engineering configuration.

Rows bind the configuration series and take its owner and visibility, so an
interface is readable exactly when its configuration is. Each version names the
exact configuration version it was written against.
"""

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

from .schemas import ACTIONS, OPERATION, STATES

VERSIONS = "engineering_interface_versions"
CURRENTS = "engineering_interface_currents"
BINDING = (
    "tenant_id",
    "category_id",
    "product_id",
    "project_id",
    "configuration_series_id",
    "owner_id",
    "visibility",
)


def _scope():
    return (
        product_fk(),
        fk(
            ("tenant_id", "product_id", "project_id"), "projects", ("tenant_id", "product_id", "id")
        ),
        fk(
            ("tenant_id", "product_id", "configuration_series_id"),
            "engineering_configurations",
            ("tenant_id", "product_id", "id"),
        ),
        fk(("tenant_id", "owner_id"), "principals", ("tenant_id", "id")),
    )


class _Scope(Row):
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    configuration_series_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))


class InterfaceVersion(VersionColumns, _Scope, Base):
    __tablename__ = VERSIONS
    configuration_id: Mapped[UUID]
    __table_args__ = (
        *_scope(),
        fk(
            ("tenant_id", "product_id", "configuration_id"),
            "engineering_configurations",
            ("tenant_id", "product_id", "id"),
        ),
        *version_args(
            VERSIONS,
            BINDING,
            operations=(OPERATION,),
            actions=ACTIONS,
            states=STATES,
            create_states=("pending",),
            prefix="engineering_interface",
            body_check="body->>'configuration_id'=configuration_id::text AND body->>'project_id'=project_id::text "
            "AND visibility IN ('private','category','audience')",
        ),
    )


class InterfaceCurrent(CurrentColumns, _Scope, Base):
    __tablename__ = CURRENTS
    __table_args__ = (
        *_scope(),
        *current_args(VERSIONS, BINDING, states=STATES, prefix="engineering_interface"),
    )
