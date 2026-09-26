"""Actual tasks handed off from a fixed human firmware work package."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.project_access import ProjectAccessService, SqlProjectAccessRepository
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.firmware_work_packages import FirmwarePackageError, _latest, _source
from app.domain.npi_execution import NpiExecutionService, _snapshot
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.tasks import TERMINAL_TASK_STATUSES, TaskDraft, TaskService
from app.domain.test_verification_paths import _authorize


class NewTask(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=512)
    stage_id: UUID
    assignee_user_id: UUID
    start_date: date | None = None
    due_date: date
    expected_output: str = Field(min_length=1, max_length=10000)
    description: str = Field(min_length=1, max_length=10000)
    priority: Literal["low", "medium", "high", "critical"] = "medium"

    @model_validator(mode="after")
    def dates(self) -> NewTask:
        if self.start_date and self.start_date > self.due_date:
            raise ValueError("计划结束日期不能早于开始日期")
        return self


class PackageTaskDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    purpose: Literal["investigation", "verification", "regression", "coordination"]
    completion_criteria: str = Field(min_length=1, max_length=10000)
    basis: str = Field(min_length=1, max_length=4000)
    new_task: NewTask | None = None
    existing_task_id: UUID | None = None
    existing_task_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def target(self) -> PackageTaskDraft:
        if (self.new_task is None) == (self.existing_task_id is None):
            raise ValueError("请选择创建实际任务或承接同固件版本的原任务")
        if self.existing_task_id and not self.existing_task_digest:
            raise ValueError("请先读取原任务的当前状态")
        return self


def _task(c: Connection, tenant_id: UUID, project_id: UUID, task_id: UUID) -> dict[str, Any]:
    t = tables.tasks
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == tenant_id, t.c.project_id == project_id, t.c.id == task_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise FirmwarePackageError("任务不存在或已不属于本项目")
    return _plain(dict(row))


def _state(c: Connection, tenant_id: UUID, project_id: UUID, package_id: UUID) -> dict[str, Any]:
    p = tables.firmware_work_packages
    package = (
        c.execute(
            select(p).where(
                p.c.tenant_id == tenant_id, p.c.project_id == project_id, p.c.id == package_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if package is None:
        raise FirmwarePackageError("工作包资料不存在或已不属于本项目")
    latest = _latest(c, tenant_id, project_id, package["fw_release_id"])
    sources = []
    for ref in package["snapshot"]["sources"]:
        try:
            current = _source(c, tenant_id, project_id, ref["kind"], UUID(ref["id"]))
            current_digest = digest(current)
        except FirmwarePackageError:
            current_digest = None
        sources.append(
            {
                "kind": ref["kind"],
                "id": ref["id"],
                "changed": current_digest != ref["expected_digest"],
                "current_digest": current_digest,
            }
        )
    return _plain(
        {
            "package": dict(package),
            "latest_package_id": latest["id"] if latest else None,
            "sources": sources,
            "can_prepare": bool(
                latest and latest["id"] == package_id and not any(s["changed"] for s in sources)
            ),
        }
    )


def task_package(
    c: Connection, tenant_id: UUID, project_id: UUID, task_id: UUID
) -> dict[str, Any] | None:
    t = tables.firmware_package_tasks
    binding = (
        c.execute(
            select(t)
            .where(t.c.tenant_id == tenant_id, t.c.project_id == project_id, t.c.task_id == task_id)
            .order_by(t.c.created_at.desc(), t.c.id.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if binding is None:
        return None
    return _plain(
        {"binding": dict(binding), **_state(c, tenant_id, project_id, binding["package_id"])}
    )


def read(
    engine: Engine, *, context: AuthContext, project_id: UUID, package_id: UUID
) -> dict[str, Any]:
    _authorize(engine, context, project_id, edit=False)
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        state = _state(c, context.tenant.id, project_id, package_id)
        project = (
            c.execute(
                select(tables.projects).where(
                    tables.projects.c.tenant_id == context.tenant.id,
                    tables.projects.c.id == project_id,
                )
            )
            .mappings()
            .one()
        )
        stages = [
            dict(r)
            for r in c.execute(
                select(tables.stages.c.id, tables.stages.c.name, tables.stages.c.code)
                .where(
                    tables.stages.c.tenant_id == context.tenant.id,
                    tables.stages.c.workflow_id == project["workflow_id"],
                )
                .order_by(tables.stages.c.sequence)
            ).mappings()
        ]
        u, m = tables.users, tables.project_members
        members = [
            dict(r)
            for r in c.execute(
                select(u.c.id, u.c.display_name)
                .join(m, (m.c.tenant_id == u.c.tenant_id) & (m.c.user_id == u.c.id))
                .where(
                    u.c.tenant_id == context.tenant.id,
                    m.c.project_id == project_id,
                    u.c.is_active.is_(True),
                    u.c.role.in_(["owner", "admin", "project_manager", "engineer", "quality"]),
                )
                .order_by(u.c.display_name, u.c.id)
            ).mappings()
        ]
        b, p = tables.firmware_package_tasks, tables.firmware_work_packages
        bindings = [
            dict(r)
            for r in c.execute(
                select(b)
                .join(p, (p.c.tenant_id == b.c.tenant_id) & (p.c.id == b.c.package_id))
                .where(
                    b.c.tenant_id == context.tenant.id,
                    b.c.project_id == project_id,
                    p.c.fw_release_id == UUID(state["package"]["fw_release_id"]),
                )
                .order_by(b.c.created_at, b.c.id)
            ).mappings()
        ]
        task_ids = {row["task_id"] for row in bindings}
        tasks = {id: _task(c, context.tenant.id, project_id, id) for id in task_ids}
        current = [
            {**_plain(row), "task": tasks[row["task_id"]]}
            for row in bindings
            if row["package_id"] == package_id
        ]
        current_ids = {row["task_id"] for row in bindings if row["package_id"] == package_id}
        previous = [
            {"task": tasks[id], "digest": digest(tasks[id])}
            for id in sorted(task_ids - current_ids, key=str)
            if tasks[id]["status"] not in TERMINAL_TASK_STATUSES
        ]
    return {
        **state,
        "digest": digest(state),
        "tasks": current,
        "previous_tasks": previous,
        "stages": [_plain(row) for row in stages],
        "members": [_plain(row) for row in members],
    }


def save(
    engine: Engine,
    *,
    context: AuthContext,
    project_id: UUID,
    package_id: UUID,
    draft: PackageTaskDraft,
) -> dict[str, Any]:
    _authorize(engine, context, project_id, edit=True)
    access = ProjectAccessService(SqlProjectAccessRepository(engine))
    access.authorize(context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT)
    fingerprint = digest(
        {
            "project_id": str(project_id),
            "package_id": str(package_id),
            **draft.model_dump(mode="json"),
        }
    )
    b = tables.firmware_package_tasks
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project_id):
            raise FirmwarePackageError("项目不可用")
        _authorize(engine, context, project_id, edit=True)
        access.authorize(context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT)
        receipt = (
            c.execute(
                select(b).where(
                    b.c.tenant_id == context.tenant.id,
                    b.c.created_by_user_id == context.user.id,
                    b.c.request_id == draft.request_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if receipt:
            if receipt["request_digest"] != fingerprint:
                raise FirmwarePackageError("同一办理请求不能改为不同任务，请重新读取后提交")
            return _plain(dict(receipt))
        state = _state(c, context.tenant.id, project_id, package_id)
        if not state["can_prepare"] or digest(state) != draft.expected_digest:
            raise FirmwarePackageError("工作包或引用来源已变，请先修订最新资料后准备任务")
        fw_id = UUID(state["package"]["fw_release_id"])
        if draft.new_task:
            task = TaskService(engine).create(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                draft=TaskDraft(
                    **draft.new_task.model_dump(), parent_task_id=None, dependency_task_ids=()
                ),
                connection=c,
            )
            task_id = task.id
        else:
            assert draft.existing_task_id is not None
            task_id = draft.existing_task_id
            old_task = _task(c, context.tenant.id, project_id, task_id)
            p = tables.firmware_work_packages
            links = (
                c.execute(
                    select(b.c.package_id, p.c.fw_release_id)
                    .join(p, (p.c.tenant_id == b.c.tenant_id) & (p.c.id == b.c.package_id))
                    .where(
                        b.c.tenant_id == context.tenant.id,
                        b.c.project_id == project_id,
                        b.c.task_id == task_id,
                    )
                )
                .mappings()
                .all()
            )
            if not links or any(
                r["fw_release_id"] != fw_id or r["package_id"] == package_id for r in links
            ):
                raise FirmwarePackageError(
                    "只能承接本固件版本此前工作包的任务，且本资料不能重复关联"
                )
            if (
                old_task["status"] in TERMINAL_TASK_STATUSES
                or digest(old_task) != draft.existing_task_digest
            ):
                raise FirmwarePackageError("原任务已结束或已变化，请刷新后重新核对")
        task_snapshot = _task(c, context.tenant.id, project_id, task_id)
        row = (
            c.execute(
                b.insert()
                .values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    project_id=project_id,
                    package_id=package_id,
                    task_id=task_id,
                    request_id=draft.request_id,
                    request_digest=fingerprint,
                    created_by_user_id=context.user.id,
                    created_at=datetime.now(UTC),
                    snapshot={
                        "purpose": draft.purpose,
                        "completion_criteria": draft.completion_criteria,
                        "basis": draft.basis,
                        "mode": "created" if draft.new_task else "carried",
                        "task_at_preparation": task_snapshot,
                        "package_digest": digest(state["package"]),
                    },
                )
                .returning(b)
            )
            .mappings()
            .one()
        )
        NpiExecutionService._record_change(
            c,
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            record_id=row["id"],
            record_type="firmware_package_task",
            action="prepared",
            before=None,
            after=_snapshot(dict(row)),
        )
        return _plain(dict(row))
