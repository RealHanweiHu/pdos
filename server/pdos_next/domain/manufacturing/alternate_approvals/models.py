"""Alternate approval versions and one exact Current per Build × BOM line × alternate."""

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

VERSIONS = "alternate_approval_versions"
CURRENTS = "alternate_approval_currents"
BINDING = (
    "tenant_id",
    "category_id",
    "product_id",
    "project_id",
    "build_id",
    "item_id",
    "alternate_material_id",
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
    item_id: Mapped[str] = mapped_column(String(200))
    alternate_material_id: Mapped[str] = mapped_column(String(200))
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))


class AlternateApprovalVersion(VersionColumns, _Scope, Base):
    __tablename__ = VERSIONS
    __table_args__ = (
        *_scope(),
        *version_args(
            VERSIONS,
            BINDING,
            operations=(OPERATION,),
            actions=ACTIONS,
            states=STATES,
            create_states=("approved",),
            first_actions=("approve",),
            later_actions=ACTIONS,
            prefix="alternate_approval",
            body_check="body->>'build_id'=build_id::text AND body->>'item_id'=item_id "
            "AND body->>'alternate_material_id'=alternate_material_id "
            "AND body->>'bom_sha256' ~ '^[a-f0-9]{64}$' AND body->>'configuration_sha256' ~ '^[a-f0-9]{64}$' "
            "AND (state<>'approved' OR jsonb_typeof(body->'evidence_run')='object')",
        ),
    )


class AlternateApprovalCurrent(CurrentColumns, _Scope, Base):
    __tablename__ = CURRENTS
    __table_args__ = (
        *_scope(),
        *current_args(VERSIONS, BINDING, states=STATES, prefix="alternate_approval"),
        UniqueConstraint("tenant_id", "build_id", "item_id", "alternate_material_id"),
    )
