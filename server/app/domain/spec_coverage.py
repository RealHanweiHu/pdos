"""Deterministic requirement/spec verification coverage (vNext V1-B1).

Four buckets, all derived from object state with plain SQL — no model calls:
requirements without any spec, key specs without a verification path, specs
with failed verification, and specs changed after their last test execution.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, Row, select

from app.db.schema import tables


@dataclass(frozen=True)
class CoverageItem:
    id: UUID
    code: str
    title: str


@dataclass(frozen=True)
class SpecCoverage:
    requirements_without_spec: tuple[CoverageItem, ...]
    key_specs_unverified: tuple[CoverageItem, ...]
    failed_verification: tuple[CoverageItem, ...]
    retest_needed: tuple[CoverageItem, ...]


def _items(rows: Sequence[Row[Any]]) -> tuple[CoverageItem, ...]:
    return tuple(CoverageItem(id=row.id, code=row.code, title=row.title) for row in rows)


class SpecCoverageService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def compute(self, *, tenant_id: UUID, project_id: UUID) -> SpecCoverage:
        specs = tables.specifications.c
        requirements = tables.requirements.c
        cases = tables.test_cases.c
        with self._engine.connect() as connection:
            root_requirement_id = connection.execute(
                select(tables.development_cases.c.requirement_id)
                .join(
                    tables.projects,
                    (tables.projects.c.tenant_id == tables.development_cases.c.tenant_id)
                    & (tables.projects.c.development_case_id == tables.development_cases.c.id),
                )
                .where(
                    tables.projects.c.tenant_id == tenant_id,
                    tables.projects.c.id == project_id,
                )
            ).scalar_one_or_none()

            requirement_scope = [root_requirement_id] if root_requirement_id else []
            if root_requirement_id is not None:
                children = connection.execute(
                    select(requirements.id).where(
                        requirements.tenant_id == tenant_id,
                        requirements.parent_requirement_id == root_requirement_id,
                    )
                ).scalars()
                requirement_scope.extend(children)

            spec_backed = set(
                connection.execute(
                    select(specs.requirement_id).where(
                        specs.tenant_id == tenant_id,
                        specs.project_id == project_id,
                        specs.requirement_id.is_not(None),
                    )
                ).scalars()
            )
            requirements_without_spec = (
                connection.execute(
                    select(requirements.id, requirements.code, requirements.title).where(
                        requirements.tenant_id == tenant_id,
                        requirements.id.in_(
                            [rid for rid in requirement_scope if rid not in spec_backed]
                        ),
                    )
                ).all()
                if requirement_scope
                else []
            )

            linked_case_specs = (
                select(cases.specification_id)
                .where(
                    cases.tenant_id == tenant_id,
                    cases.project_id == project_id,
                    cases.specification_id.is_not(None),
                )
                .scalar_subquery()
            )
            key_specs_unverified = connection.execute(
                select(specs.id, specs.code, specs.title).where(
                    specs.tenant_id == tenant_id,
                    specs.project_id == project_id,
                    specs.criticality == "key",
                    (specs.verification_method.is_(None)) | (specs.id.not_in(linked_case_specs)),
                )
            ).all()

            failed_verification = connection.execute(
                select(specs.id, specs.code, specs.title)
                .join(
                    tables.test_cases,
                    (cases.tenant_id == specs.tenant_id) & (cases.specification_id == specs.id),
                )
                .where(
                    specs.tenant_id == tenant_id,
                    specs.project_id == project_id,
                    cases.status == "failed",
                )
                .distinct()
            ).all()

            retest_needed = connection.execute(
                select(specs.id, specs.code, specs.title)
                .join(
                    tables.test_cases,
                    (cases.tenant_id == specs.tenant_id) & (cases.specification_id == specs.id),
                )
                .where(
                    specs.tenant_id == tenant_id,
                    specs.project_id == project_id,
                    cases.executed_at.is_not(None),
                    cases.executed_at < specs.updated_at,
                )
                .distinct()
            ).all()

        return SpecCoverage(
            requirements_without_spec=_items(requirements_without_spec),
            key_specs_unverified=_items(key_specs_unverified),
            failed_verification=_items(failed_verification),
            retest_needed=_items(retest_needed),
        )
