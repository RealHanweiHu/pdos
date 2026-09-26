"""Human preparation of verification links before a test case is executed."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, exists, select

from app.auth.errors import ObjectPermissionDeniedError
from app.auth.project_access import ProjectAccessService, SqlProjectAccessRepository
from app.auth.repository import AuthContext, AuthRepository
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.npi_execution import NpiExecutionService, _snapshot
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope


class VerificationPathError(ValueError):
    pass


def _authorize(engine: Engine, context: AuthContext, project_id: UUID, *, edit: bool) -> None:
    current = AuthRepository(engine).find_user_context(context.user.id)
    if (
        current is None
        or not current.user.is_active
        or current.tenant.status != "active"
        or current.tenant.id != context.tenant.id
        or current.user.auth_version != context.user.auth_version
    ):
        raise ObjectPermissionDeniedError
    ProjectAccessService(SqlProjectAccessRepository(engine)).authorize(
        context=current,
        project_id=project_id,
        action=Action.PRODUCT_ENGINEERING_EDIT if edit else Action.PRODUCT_ENGINEERING_VIEW,
    )


def _state(c: Connection, tenant_id: UUID, project_id: UUID, case_id: UUID) -> dict[str, Any]:
    case = (
        c.execute(
            select(tables.test_cases).where(
                tables.test_cases.c.tenant_id == tenant_id,
                tables.test_cases.c.project_id == project_id,
                tables.test_cases.c.id == case_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if case is None:
        raise VerificationPathError("测试项不存在或已不属于本项目")
    plan = (
        c.execute(
            select(tables.test_plans).where(
                tables.test_plans.c.tenant_id == tenant_id,
                tables.test_plans.c.project_id == project_id,
                tables.test_plans.c.id == case["plan_id"],
            )
        )
        .mappings()
        .one()
    )
    has_runs = c.execute(
        select(
            exists().where(
                tables.test_runs.c.tenant_id == tenant_id,
                tables.test_runs.c.project_id == project_id,
                tables.test_runs.c.test_case_id == case_id,
            )
        )
    ).scalar_one()
    has_successor = c.execute(
        select(
            exists().where(
                tables.test_plans.c.tenant_id == tenant_id,
                tables.test_plans.c.project_id == project_id,
                tables.test_plans.c.parent_plan_id == plan["id"],
            )
        )
    ).scalar_one()
    return _plain(
        dict(
            case=dict(case),
            plan=dict(plan),
            can_edit=not has_runs
            and not has_successor
            and case["status"] == "planned"
            and plan["status"] != "completed",
        )
    )


def _specifications(c: Connection, tenant_id: UUID, project_id: UUID) -> list[dict[str, Any]]:
    specs, requirements = tables.specifications, tables.requirements
    return [
        dict(row)
        for row in c.execute(
            select(
                specs,
                requirements.c.title.label("requirement_title"),
                requirements.c.code.label("requirement_code"),
            )
            .outerjoin(
                requirements,
                (requirements.c.tenant_id == specs.c.tenant_id)
                & (requirements.c.id == specs.c.requirement_id),
            )
            .where(
                specs.c.tenant_id == tenant_id,
                specs.c.project_id == project_id,
            )
            .order_by(specs.c.code, specs.c.id)
        ).mappings()
    ]


def options(
    engine: Engine, *, context: AuthContext, project_id: UUID, case_id: UUID
) -> dict[str, Any]:
    _authorize(engine, context, project_id, edit=False)
    with engine.connect() as c:
        state = _state(c, context.tenant.id, project_id, case_id)
        specs = _specifications(c, context.tenant.id, project_id)
    return {
        **state,
        "digest": digest(state),
        "specifications": [{**_plain(spec), "digest": digest(_plain(spec))} for spec in specs],
    }


def save(
    engine: Engine,
    *,
    context: AuthContext,
    project_id: UUID,
    case_id: UUID,
    expected_digest: str,
    specification_id: UUID | None,
    specification_digest: str | None,
    method: str,
    acceptance_criteria: str,
    reason: str,
) -> dict[str, Any]:
    _authorize(engine, context, project_id, edit=True)
    if (
        not 1 <= len(reason.strip()) <= 2000
        or not method.strip()
        or not acceptance_criteria.strip()
    ):
        raise VerificationPathError("请填写方法、判据和规格关联的核对依据")
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project_id):
            raise VerificationPathError("项目不可用")
        _authorize(engine, context, project_id, edit=True)
        state = _state(c, context.tenant.id, project_id, case_id)
        specs = _specifications(c, context.tenant.id, project_id)
        selected = next((s for s in specs if s["id"] == specification_id), None)
        if specification_id is not None and (
            selected is None or digest(_plain(selected)) != specification_digest
        ):
            raise VerificationPathError("规格或客户要求已变化，请重新读取并核对当前版本")
        before = state["case"]
        desired = {
            "specification_id": str(specification_id) if specification_id else None,
            "method": method.strip(),
            "acceptance_criteria": acceptance_criteria.strip(),
        }
        if all(before[key] == value for key, value in desired.items()):
            return state  # No duplicate write or audit for an uncertain response.
        if not state["can_edit"]:
            raise VerificationPathError(
                "已有逐次测试、结果或后续计划版本，请通过计划修订办理并保留原验证关系"
            )
        if digest(state) != expected_digest:
            raise VerificationPathError("测试项已变化，请刷新后重新核对")
        after = (
            c.execute(
                tables.test_cases.update()
                .where(
                    tables.test_cases.c.tenant_id == context.tenant.id,
                    tables.test_cases.c.project_id == project_id,
                    tables.test_cases.c.id == case_id,
                )
                .values(
                    specification_id=specification_id,
                    method=method.strip(),
                    acceptance_criteria=acceptance_criteria.strip(),
                    updated_at=datetime.now(UTC),
                )
                .returning(tables.test_cases)
            )
            .mappings()
            .one()
        )
        NpiExecutionService._record_change(
            c,
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            record_id=case_id,
            record_type="test_case",
            action="verification_path_prepared",
            before=_snapshot(before),
            after=_snapshot(
                {
                    **dict(after),
                    "verification_reason": reason.strip(),
                    "specification_snapshot": selected,
                }
            ),
        )
    return options(engine, context=context, project_id=project_id, case_id=case_id)
