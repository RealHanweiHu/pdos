"""Actual relative clocks and task conditions in the caller's ordinary read scope."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, TypeAdapter, ValidationError
from sqlalchemy import select

from pdos_next.domain.projects.models import PlanRevision, ProjectTask
from pdos_next.domain.work_management import owner
from pdos_next.domain.work_management.models import WorkTaskCurrent
from pdos_next.errors import DomainError
from pdos_next.schemas.planning import CalendarRef
from pdos_next.service import digest, require_access

from .fulfillment_sources import commitment_fulfilled
from .schemas import Conditions, RelativeTrigger

_INSTANT = TypeAdapter(AwareDatetime)


def _require(condition, message, code="FORBIDDEN_SCOPE", status=403):
    if not condition:
        raise DomainError(code, message, status)


def _scope(row, ctx, product_id, project_id=None):
    _require(
        row is not None
        and (row.tenant_id, row.category_id, row.product_id)
        == (ctx.tenant_id, ctx.category_id, product_id)
        and (project_id is None or row.project_id == project_id),
        "自动化时间来源不在当前实际范围内。",
    )


def _instant(value):
    if value is None:
        return None
    _require(
        isinstance(value, (str, datetime)),
        "时间来源不是原始的明确时区时刻。",
        "INTEGRITY_MISMATCH",
        409,
    )
    try:
        return _INSTANT.validate_python(value).astimezone(UTC)
    except (ValidationError, OverflowError, ValueError):
        raise DomainError("INTEGRITY_MISMATCH", "时间来源缺少可核对的明确时区。") from None


def _timezone(value):
    try:
        ZoneInfo(value)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        raise DomainError("INTEGRITY_MISMATCH", "实际时间来源的原时区无法核对。") from None
    return value


def _result(config, origin, source_at):
    identity = {key: value for key, value in origin.items() if key != "offset_seconds"}
    try:
        scheduled = (
            source_at + timedelta(seconds=config.offset_seconds) if source_at is not None else None
        )
    except OverflowError:
        raise DomainError("VALIDATION_FAILED", "相对时间偏移超过支持的时间范围。", 422) from None
    return {
        "scheduled_at": scheduled,
        "origin": origin,
        "target_key": config.source_kind + ":" + digest(identity),
    }


def relative_due(s, ctx, spec):
    """Read a selected real clock; an explicit null stays unknown, never a fabricated due date."""
    config = RelativeTrigger.model_validate(spec.trigger_config)
    pid = spec.product_id
    _require(pid is not None, "相对时间来源须绑定实际型号。")
    project = owner.project(s, ctx, pid, config.project_id)
    _scope(project, ctx, pid)
    _require(project.id == config.project_id, "时间来源项目与所选项目不一致。")
    goal_reached = False
    if config.source_kind == "plan_task":
        _require(
            project.current_plan_id is not None, "项目尚无当前实际计划。", "SOURCE_UNAVAILABLE"
        )
        plan = s.get(PlanRevision, project.current_plan_id)
        _scope(plan, ctx, pid, project.id)
        _require(
            plan.id == project.current_plan_id and plan.status == "applied",
            "时间来源须属于当前实际应用计划。",
            "VERSION_CONFLICT",
            409,
        )
        task = s.scalar(
            select(ProjectTask).where(
                ProjectTask.tenant_id == ctx.tenant_id,
                ProjectTask.category_id == ctx.category_id,
                ProjectTask.product_id == pid,
                ProjectTask.project_id == project.id,
                ProjectTask.plan_id == plan.id,
                ProjectTask.id == config.task_id,
            )
        )
        _scope(task, ctx, pid, project.id)
        _require(task.id == config.task_id and task.plan_id == plan.id, "计划任务不属于当前计划。")
        forecast = task.forecast
        _require(
            isinstance(forecast, dict)
            and forecast.get("key") == task.key
            and config.clock in forecast
            and "calendar_ref" in forecast,
            "实际计划任务缺少指定预测字段或固定日历引用。",
            "INTEGRITY_MISMATCH",
            409,
        )
        try:
            calendar = CalendarRef.model_validate(forecast["calendar_ref"]).model_dump(mode="json")
        except ValidationError:
            raise DomainError("INTEGRITY_MISMATCH", "实际计划日历引用无法核对。") from None
        source_at = _instant(forecast[config.clock])
        origin = {
            "source_kind": "plan_task",
            "category_id": str(ctx.category_id),
            "product_id": str(pid),
            "project_id": str(project.id),
            "plan_id": str(plan.id),
            "plan_revision": plan.revision,
            "task_id": str(task.id),
            "task_key": task.key,
            "clock": config.clock,
            "calendar_ref": calendar,
            "original_timezone": _timezone(calendar["timezone"]),
            "source_at": source_at.isoformat() if source_at is not None else None,
            "offset_seconds": config.offset_seconds,
        }
    else:
        row, snapshot, pointer = owner.commitment(
            s, ctx, pid, config.task_id, config.promisor_id, config.recipient_id
        )
        _scope(row, ctx, pid, project.id)
        _scope(pointer, ctx, pid, project.id)
        _require(
            snapshot is not None
            and pointer.version_id == row.id
            and pointer.revision == row.revision == snapshot.revision
            and pointer.series_id == row.series_id
            and pointer.task_id == row.task_id == snapshot.task_id == config.task_id
            and pointer.promisor_id == row.promisor_id == snapshot.promisor_id == config.promisor_id
            and pointer.recipient_id
            == row.recipient_id
            == snapshot.recipient_id
            == config.recipient_id,
            "承诺时间须来自所选任务、承诺人和接收者的当前实际记录。",
        )
        goal_reached = commitment_fulfilled(s, ctx, row)
        source_at = _instant(snapshot.promised_at)
        _require(
            _instant(row.promised_at) == source_at
            and row.original_timezone == snapshot.original_timezone
            and row.calendar_id == snapshot.calendar_id
            and row.task_revision == snapshot.task_revision,
            "实际承诺时钟与固定快照不一致。",
            "INTEGRITY_MISMATCH",
            409,
        )
        origin = {
            "source_kind": "commitment",
            "category_id": str(ctx.category_id),
            "product_id": str(pid),
            "project_id": str(project.id),
            "task_id": str(row.task_id),
            "task_revision": row.task_revision,
            "commitment_id": str(row.id),
            "commitment_revision": row.revision,
            "series_id": str(pointer.series_id),
            "promisor_id": str(row.promisor_id),
            "recipient_id": str(row.recipient_id),
            "clock": "promised_at",
            "calendar_id": str(snapshot.calendar_id) if snapshot.calendar_id is not None else None,
            "original_timezone": _timezone(snapshot.original_timezone),
            "source_at": source_at.isoformat() if source_at is not None else None,
            "offset_seconds": config.offset_seconds,
        }
    return {**_result(config, origin, source_at), "goal_reached": goal_reached}


def condition_state(s, ctx, spec):
    """Evaluate only the declared actual task lifecycle, retaining errors and current scope."""
    conditions = Conditions.model_validate(spec.conditions)
    if conditions.task_id is None:
        return "eligible"
    query = select(WorkTaskCurrent).where(
        WorkTaskCurrent.tenant_id == ctx.tenant_id,
        WorkTaskCurrent.category_id == ctx.category_id,
        WorkTaskCurrent.task_id == conditions.task_id,
    )
    if spec.product_id is not None:
        query = query.where(WorkTaskCurrent.product_id == spec.product_id)
    selected = s.scalar(query)
    _require(selected is not None, "自动化条件任务不存在或不在当前受众内。")
    pid = spec.product_id if spec.product_id is not None else selected.product_id
    _scope(selected, ctx, pid)
    _require(selected.task_id == conditions.task_id, "条件任务与实际当前记录不一致。")
    require_access(s, ctx, pid)
    row, snapshot, pointer = owner.task(s, ctx, pid, conditions.task_id)
    _scope(row, ctx, pid)
    _scope(pointer, ctx, pid)
    _require(
        snapshot.task_id == pointer.task_id == row.task_id == conditions.task_id
        and pointer.version_id == row.id
        and pointer.revision == row.revision == snapshot.revision
        and pointer.state == row.state == snapshot.state,
        "条件须使用实际当前任务状态。",
        "VERSION_CONFLICT",
        409,
    )
    if snapshot.state in conditions.stop_states:
        return "goal_reached"
    if not conditions.only_states or snapshot.state in conditions.only_states:
        return "eligible"
    return "waiting"
