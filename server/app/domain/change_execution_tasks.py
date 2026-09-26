"""Batch assignment of original project tasks against the approved change scope."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.project_access import ProjectAccessService, SqlProjectAccessRepository
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.change_execution_evidence import scope_changes
from app.domain.change_impact_scope import _ecr, current_basis
from app.domain.firmware_package_tasks import NewTask
from app.domain.npi_execution import NpiExecutionService, _snapshot
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.tasks import (
    TERMINAL_TASK_STATUSES,
    TaskDateOrderError,
    TaskDraft,
    TaskNotFoundError,
    TaskScopeError,
    TaskService,
)
from app.domain.test_verification_paths import _authorize


class Assignment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    item_key: UUID
    completion_criteria: str = Field(min_length=1, max_length=10000)
    new_task: NewTask | None = None
    existing_task_id: UUID | None = None
    existing_task_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def target(self) -> Assignment:
        if (self.new_task is None) == (self.existing_task_id is None):
            raise ValueError("每项要求请选择创建实际任务或关联未结束原任务")
        if self.existing_task_id and not self.existing_task_digest:
            raise ValueError("请核对原任务当前版本")
        return self


class BatchDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    scope_version_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=4000)
    assignments: list[Assignment] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_items(self) -> BatchDraft:
        if len({a.item_key for a in self.assignments}) != len(self.assignments):
            raise ValueError("同一范围条目不可重复安排")
        return self


def _access(engine: Engine, context: AuthContext, project_id: UUID, *, edit: bool) -> None:
    _authorize(engine, context, project_id, edit=False)
    service = ProjectAccessService(SqlProjectAccessRepository(engine))
    service.authorize(
        context=context,
        project_id=project_id,
        action=Action.CHANGE_EDIT if edit else Action.CHANGE_VIEW,
    )
    if edit:
        service.authorize(context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT)


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
        raise ProductWorkError("原任务不可用或不属于本项目")
    return _plain(dict(row))


def _existing_ready(c: Connection, tenant_id: UUID, project_id: UUID, task: dict[str, Any]) -> bool:
    if (
        not task["assignee_user_id"]
        or not task["due_date"]
        or not task["stage_id"]
        or not (task["expected_output"] or "").strip()
    ):
        return False
    u, m = tables.users, tables.project_members
    return (
        c.execute(
            select(u.c.id)
            .join(m, (m.c.tenant_id == u.c.tenant_id) & (m.c.user_id == u.c.id))
            .where(
                u.c.tenant_id == tenant_id,
                m.c.project_id == project_id,
                u.c.id == UUID(task["assignee_user_id"]),
                u.c.is_active.is_(True),
                u.c.role.in_(["owner", "admin", "project_manager", "engineer", "quality"]),
            )
        ).scalar_one_or_none()
        is not None
    )


def _state(c: Connection, tenant_id: UUID, project_id: UUID, ecr_id: UUID) -> dict[str, Any]:
    ecr = _ecr(c, tenant_id, project_id, ecr_id)
    approved = ((ecr["impact_analysis"] or {}).get("impact_scope") or {}).get("basis")
    current = current_basis(c, tenant_id, project_id, ecr_id)
    changes = scope_changes(c, tenant_id, project_id, approved) if approved else []
    ready = bool(
        ecr["status"] == "approved"
        and approved
        and current
        and current["version"]["id"] == approved["version"]["id"]
        and not any(change["blocking"] for change in changes)
    )
    return {
        "ecr": _plain(
            {
                k: ecr[k]
                for k in (
                    "id",
                    "code",
                    "title",
                    "status",
                    "approval_decision_id",
                    "approved_by_user_id",
                    "approved_at",
                )
            }
        ),
        "approved_scope": approved,
        "current_scope": current,
        "can_assign": ready,
        "source_changes": changes,
    }


def _bindings(
    c: Connection, tenant_id: UUID, project_id: UUID, ecr_id: UUID, *, batch_id: UUID | None = None
) -> list[dict[str, Any]]:
    t = tables.change_execution_tasks
    q = select(t).where(
        t.c.tenant_id == tenant_id, t.c.project_id == project_id, t.c.ecr_id == ecr_id
    )
    if batch_id:
        q = q.where(t.c.batch_id == batch_id)
    links = [dict(r) for r in c.execute(q.order_by(t.c.id)).mappings()]
    if not links:
        return []
    tasks = tables.tasks
    actual = {
        r["id"]: _plain(dict(r))
        for r in c.execute(
            select(tasks).where(
                tasks.c.tenant_id == tenant_id,
                tasks.c.project_id == project_id,
                tasks.c.id.in_({link["task_id"] for link in links}),
            )
        ).mappings()
    }
    return [{**_plain(link), "task": actual[link["task_id"]]} for link in links]


def read(engine: Engine, *, context: AuthContext, project_id: UUID, ecr_id: UUID) -> dict[str, Any]:
    _access(engine, context, project_id, edit=False)
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        state = _state(c, context.tenant.id, project_id, ecr_id)
        bindings = _bindings(c, context.tenant.id, project_id, ecr_id)
        p, s = tables.projects, tables.stages
        stages = [
            _plain(dict(r))
            for r in c.execute(
                select(s.c.id, s.c.name, s.c.code)
                .join(p, (p.c.tenant_id == s.c.tenant_id) & (p.c.workflow_id == s.c.workflow_id))
                .where(p.c.tenant_id == context.tenant.id, p.c.id == project_id)
                .order_by(s.c.sequence)
            ).mappings()
        ]
        u, m = tables.users, tables.project_members
        members = [
            _plain(dict(r))
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
    return {
        **state,
        "digest": digest(state),
        "bindings": bindings,
        "stages": stages,
        "members": members,
    }


def choices(
    engine: Engine,
    *,
    context: AuthContext,
    project_id: UUID,
    ecr_id: UUID,
    after_id: UUID | None = None,
) -> dict[str, Any]:
    _access(engine, context, project_id, edit=False)
    with engine.connect() as c:
        _ecr(c, context.tenant.id, project_id, ecr_id)
        t = tables.tasks
        u, m = tables.users, tables.project_members
        q = (
            select(t)
            .join(u, (u.c.tenant_id == t.c.tenant_id) & (u.c.id == t.c.assignee_user_id))
            .join(
                m,
                (m.c.tenant_id == t.c.tenant_id)
                & (m.c.project_id == t.c.project_id)
                & (m.c.user_id == u.c.id),
            )
            .where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project_id,
                t.c.kind == "task",
                t.c.status.not_in(TERMINAL_TASK_STATUSES),
                u.c.is_active.is_(True),
                u.c.role.in_(["owner", "admin", "project_manager", "engineer", "quality"]),
                t.c.due_date.is_not(None),
                t.c.stage_id.is_not(None),
                t.c.expected_output.is_not(None),
                t.c.expected_output != "",
            )
        )
        if after_id:
            q = q.where(t.c.id > after_id)
        rows = c.execute(q.order_by(t.c.id).limit(51)).mappings().all()
        values = [_plain(dict(r)) for r in rows[:50]]
        return {
            "tasks": [{"task": r, "digest": digest(r)} for r in values],
            "next_after_id": str(rows[49]["id"]) if len(rows) > 50 else None,
        }


def save(
    engine: Engine, *, context: AuthContext, project_id: UUID, ecr_id: UUID, draft: BatchDraft
) -> dict[str, Any]:
    _access(engine, context, project_id, edit=True)
    fingerprint = digest(
        {"project_id": str(project_id), "ecr_id": str(ecr_id), **draft.model_dump(mode="json")}
    )
    b, t = tables.change_execution_batches, tables.change_execution_tasks
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project_id):
            raise ProductWorkError("项目不可用")
        _access(engine, context, project_id, edit=True)
        prior = (
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
        if prior:
            if prior["request_digest"] != fingerprint:
                raise ProductWorkError("同一办理请求不能修改任务安排")
            return {
                "batch": _plain(dict(prior)),
                "bindings": _bindings(
                    c, context.tenant.id, project_id, ecr_id, batch_id=prior["id"]
                ),
            }
        state = _state(c, context.tenant.id, project_id, ecr_id)
        if (
            not state["can_assign"]
            or digest(state) != draft.expected_digest
            or state["approved_scope"]["version"]["id"] != str(draft.scope_version_id)
        ):
            raise ProductWorkError(
                "仅可按已批准且来源仍有效的范围安排正式执行，请核对批准版本和原资料"
            )
        items = {
            UUID(item["key"]): item
            for item in state["approved_scope"]["version"]["snapshot"]["items"]
        }
        existing = set(
            c.execute(
                select(t.c.item_key).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.scope_version_id == draft.scope_version_id,
                )
            ).scalars()
        )
        for assignment in draft.assignments:
            if assignment.item_key in existing:
                raise ProductWorkError("所选条目已有关联任务，请刷新办理回执，避免重复创建")
            item = items.get(assignment.item_key)
            if item is None or item["conclusion"] == "unknown" or item["action"] == "none":
                raise ProductWorkError("条目不在获批执行范围内或未要求后续行动")
        batch_id = uuid4()
        batch = (
            c.execute(
                b.insert()
                .values(
                    id=batch_id,
                    tenant_id=context.tenant.id,
                    project_id=project_id,
                    ecr_id=ecr_id,
                    scope_version_id=draft.scope_version_id,
                    request_id=draft.request_id,
                    request_digest=fingerprint,
                    created_by_user_id=context.user.id,
                    created_at=datetime.now(UTC),
                    reason=draft.reason,
                    snapshot={
                        "ecr": state["ecr"],
                        "scope_digest": digest(state["approved_scope"]),
                        "source_changes_at_assignment": state["source_changes"],
                        "scope_revision": state["approved_scope"]["version"]["revision_number"],
                        "item_keys": [str(a.item_key) for a in draft.assignments],
                    },
                )
                .returning(b)
            )
            .mappings()
            .one()
        )
        for assignment in draft.assignments:
            item = items[assignment.item_key]
            if assignment.new_task:
                try:
                    actual = TaskService(engine).create(
                        tenant_id=context.tenant.id,
                        actor_user_id=context.user.id,
                        project_id=project_id,
                        draft=TaskDraft(
                            **assignment.new_task.model_dump(),
                            parent_task_id=None,
                            dependency_task_ids=(),
                        ),
                        connection=c,
                    )
                except (TaskScopeError, TaskNotFoundError, TaskDateOrderError) as error:
                    raise ProductWorkError(
                        "阶段、负责人或日期已不满足原任务要求，请重新核对本批安排"
                    ) from error
                task_id = actual.id
            else:
                assert assignment.existing_task_id is not None
                task_id = assignment.existing_task_id
                task = _task(c, context.tenant.id, project_id, task_id)
                if (
                    task["kind"] != "task"
                    or task["status"] in TERMINAL_TASK_STATUSES
                    or digest(task) != assignment.existing_task_digest
                    or not _existing_ready(c, context.tenant.id, project_id, task)
                ):
                    raise ProductWorkError(
                        "原任务已变化、已结束或缺少有效负责人/日期/交付要求，请在原任务补齐后关联"
                    )
            c.execute(
                t.insert().values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    project_id=project_id,
                    ecr_id=ecr_id,
                    scope_version_id=draft.scope_version_id,
                    batch_id=batch_id,
                    item_key=assignment.item_key,
                    task_id=task_id,
                    snapshot={
                        "item": item,
                        "completion_criteria": assignment.completion_criteria,
                        "mode": "created" if assignment.new_task else "linked",
                        "scope_revision": state["approved_scope"]["version"]["revision_number"],
                        "task_at_assignment": _task(c, context.tenant.id, project_id, task_id),
                    },
                )
            )
        NpiExecutionService._record_change(
            c,
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            record_id=batch_id,
            record_type="change_execution_batch",
            action="assigned",
            before=None,
            after=_snapshot(dict(batch)),
        )
        return {
            "batch": _plain(dict(batch)),
            "bindings": _bindings(c, context.tenant.id, project_id, ecr_id, batch_id=batch_id),
        }


def task_context(
    c: Connection, tenant_id: UUID, project_id: UUID, task_id: UUID
) -> list[dict[str, Any]]:
    t, e = tables.change_execution_tasks, tables.engineering_change_requests
    rows = (
        c.execute(
            select(
                t,
                e.c.code.label("ecr_code"),
                e.c.title.label("ecr_title"),
                e.c.status.label("ecr_status"),
            )
            .join(
                e,
                (e.c.tenant_id == t.c.tenant_id)
                & (e.c.project_id == t.c.project_id)
                & (e.c.id == t.c.ecr_id),
            )
            .where(t.c.tenant_id == tenant_id, t.c.project_id == project_id, t.c.task_id == task_id)
            .order_by(t.c.id)
        )
        .mappings()
        .all()
    )
    values = [_plain(dict(row)) for row in rows]
    f = tables.change_execution_followups
    extra = c.execute(
        select(
            t,
            e.c.code.label("ecr_code"),
            e.c.title.label("ecr_title"),
            e.c.status.label("ecr_status"),
            f.c.id.label("followup_id"),
            f.c.snapshot.label("followup_snapshot"),
        )
        .join(
            f,
            (f.c.tenant_id == t.c.tenant_id)
            & (f.c.project_id == t.c.project_id)
            & (f.c.binding_id == t.c.id),
        )
        .join(
            e,
            (e.c.tenant_id == t.c.tenant_id)
            & (e.c.project_id == t.c.project_id)
            & (e.c.id == t.c.ecr_id),
        )
        .where(f.c.tenant_id == tenant_id, f.c.project_id == project_id, f.c.task_id == task_id)
        .order_by(f.c.created_at, f.c.id)
    ).mappings()
    for row in extra:
        value = _plain(dict(row))
        value["original_task_id"] = value["task_id"]
        value["task_id"] = str(task_id)
        values.append(value)
    return values
