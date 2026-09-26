"""Explicit remedial task assignments, preserving the original execution and return trail."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.change_execution_tasks import Assignment, _access, _existing_ready, _task
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


class FollowupDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_result_id: UUID
    reason: str = Field(min_length=1, max_length=4000)
    assignment: Assignment


class FollowupResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    followup_id: UUID
    response: str = Field(min_length=1, max_length=4000)


def records(
    c: Connection,
    tenant_id: UUID,
    project_id: UUID,
    binding_ids: list[UUID],
) -> list[dict[str, Any]]:
    if not binding_ids:
        return []
    f, t = tables.change_execution_followups, tables.tasks
    values = [
        dict(row)
        for row in c.execute(
            select(f)
            .where(
                f.c.tenant_id == tenant_id,
                f.c.project_id == project_id,
                f.c.binding_id.in_(binding_ids),
            )
            .order_by(f.c.created_at, f.c.id)
        ).mappings()
    ]
    task_ids = {row["task_id"] for row in values}
    tasks = (
        {
            row["id"]: _plain(dict(row))
            for row in c.execute(
                select(t).where(
                    t.c.tenant_id == tenant_id,
                    t.c.project_id == project_id,
                    t.c.id.in_(task_ids),
                )
            ).mappings()
        }
        if task_ids
        else {}
    )
    return [{**_plain(row), "task": tasks[row["task_id"]]} for row in values]


def response_gaps(basis: dict[str, Any], snapshot: dict[str, Any]) -> list[str]:
    required = {f["id"] for f in basis.get("follow_ups", [])}
    responses = snapshot.get("follow_up_responses", [])
    supplied = {str(r["followup_id"]) for r in responses if r["response"].strip()}
    if required != supplied or len(responses) != len(supplied):
        return ["后续任务已有新增或缺少逐项补齐回应，请提交涵盖当前后续任务的新结果版本"]
    return []


def followup_allowed(
    result: dict[str, Any] | None, confirmation: dict[str, Any] | None, gaps: list[str]
) -> bool:
    if result is None:
        return False
    if confirmation:
        return confirmation["outcome"] == "returned" or bool(gaps)
    return result["outcome"] in ("recorded", "needs_follow_up")


def save(
    engine: Engine,
    *,
    context: AuthContext,
    project_id: UUID,
    binding_id: UUID,
    draft: FollowupDraft,
) -> dict[str, Any]:
    from app.domain.change_execution_results import (
        _assess_references,
        _basis,
        _confirmation,
        _gaps,
        _latest,
    )

    _access(engine, context, project_id, edit=True)
    fingerprint = digest(
        {
            "project_id": str(project_id),
            "binding_id": str(binding_id),
            **draft.model_dump(mode="json"),
        }
    )
    f = tables.change_execution_followups
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project_id):
            raise ProductWorkError("项目不可用")
        _access(engine, context, project_id, edit=True)
        prior = (
            c.execute(
                select(f).where(
                    f.c.tenant_id == context.tenant.id,
                    f.c.created_by_user_id == context.user.id,
                    f.c.request_id == draft.request_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if prior:
            if prior["request_digest"] != fingerprint:
                raise ProductWorkError("同一后续任务请求不能改写安排")
            return _plain(dict(prior))
        basis = _basis(c, context.tenant.id, project_id, binding_id)
        result = _latest(c, context.tenant.id, binding_id)
        if (
            digest(basis) != draft.expected_digest
            or not result
            or result["id"] != draft.source_result_id
        ):
            raise ProductWorkError("结果、任务或范围已有变化，请刷新后核对")
        if not basis["scope_bound"] or any(change["blocking"] for change in basis["scope_changes"]):
            raise ProductWorkError("原批准范围或设计资料已变化，请先办理原变更范围")
        confirmation = _confirmation(c, context.tenant.id, result["id"])
        refs = _assess_references(
            c, context.tenant.id, project_id, basis, result["snapshot"]["references"]
        )
        gaps = _gaps(basis, refs) + response_gaps(basis, result["snapshot"])
        if not followup_allowed(result, confirmation, gaps):
            raise ProductWorkError(
                "请先由具名确认人退回待确认结果；已确认且证据仍有效的结果无需重复安排"
            )
        assignment = draft.assignment
        if str(assignment.item_key) != basis["binding"]["item_key"]:
            raise ProductWorkError("后续任务须对应原执行条目")
        if assignment.new_task:
            try:
                task = TaskService(engine).create(
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
                raise ProductWorkError("阶段、负责人或日期已变化，请重新核对") from error
            task_id = task.id
        else:
            assert assignment.existing_task_id is not None
            task_id = assignment.existing_task_id
            actual = _task(c, context.tenant.id, project_id, task_id)
            if (
                actual["kind"] != "task"
                or actual["status"] in TERMINAL_TASK_STATUSES
                or digest(actual) != assignment.existing_task_digest
                or not _existing_ready(c, context.tenant.id, project_id, actual)
            ):
                raise ProductWorkError("请选择资料完整、负责人有效且尚未结束的原任务")
        if str(task_id) == basis["task"]["id"] or any(
            value["task_id"] == str(task_id) for value in basis["follow_ups"]
        ):
            raise ProductWorkError("该任务已承担本条要求，请在原安排继续办理或选择新的后续任务")
        row = (
            c.execute(
                f.insert()
                .values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    project_id=project_id,
                    binding_id=binding_id,
                    source_result_id=result["id"],
                    task_id=task_id,
                    request_id=draft.request_id,
                    request_digest=fingerprint,
                    created_by_user_id=context.user.id,
                    created_at=datetime.now(UTC),
                    snapshot={
                        "reason": draft.reason,
                        "completion_criteria": assignment.completion_criteria,
                        "mode": "created" if assignment.new_task else "linked",
                        "source_result": _plain(
                            {
                                k: result[k]
                                for k in (
                                    "id",
                                    "revision_number",
                                    "outcome",
                                    "created_at",
                                    "created_by_user_id",
                                )
                            }
                        ),
                        "source_confirmation": {
                            k: confirmation[k]
                            for k in ("id", "outcome", "note", "created_by_user_id", "created_at")
                        }
                        if confirmation
                        else None,
                        "gaps_at_assignment": gaps,
                        "binding": basis["binding"],
                        "task_at_assignment": _task(c, context.tenant.id, project_id, task_id),
                    },
                )
                .returning(f)
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
            record_type="change_execution_followup",
            action="assigned",
            before=None,
            after=_snapshot(dict(row)),
        )
        return _plain(dict(row))
