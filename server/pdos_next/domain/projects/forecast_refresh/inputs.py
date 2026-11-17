"""Deterministic forecast inputs and composition; no write, model or reservation.

Inputs are the current applied plan's fixed schedule input (durations, FS
dependencies, calendar) and the actual start/submission facts of work tasks
linked to its planned tasks. A finished planned task is fixed at its actual
times and releases its successors at its actual finish; every unfinished task
is computed by the planning engine, which yields ranges, float and the
critical path only when the data allows it (AT-18). Nothing here changes a
plan, a baseline or a commitment (I08, P58).
"""

from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select

from pdos_next.core.service import digest
from pdos_next.domain.projects.models import PlanProposal, PlanRevision, ProjectTask
from pdos_next.domain.projects.planning.engine import ALGORITHM_VERSION, calculate_forecast
from pdos_next.domain.projects.planning.engine.dto import (
    CalendarException,
    CalendarSnapshot,
    Dependency,
    DurationEstimate,
    ForecastInput,
    NodeSnapshot,
    Reference,
    TimeRecord,
    WeekdaySchedule,
)
from pdos_next.domain.projects.planning.engine.dto import WorkInterval as EngineInterval
from pdos_next.domain.projects.work.rules import require
from pdos_next.schemas.planning import ScheduleInput

COMPOSITION = "pdos.forecast_refresh.v1"
NO_CALENDAR_LABEL = "未扣节假日与停线"


@dataclass(frozen=True)
class Inputs:
    plan: object
    proposal: object
    schedule: ScheduleInput
    task_ids: dict
    facts: dict
    as_of: datetime
    as_of_day: str
    input_sha256: str
    commitments: list
    calendar_basis: dict | None = None


def _iso(value):
    return value.astimezone(UTC).isoformat() if value is not None else None


def _instant(value):
    return datetime.fromisoformat(value).astimezone(UTC) if value else None


def _work_facts(s, ctx, product_id, project_id, keys_by_task):
    """Actual start/submission per planned key from current work-task versions."""
    from pdos_next.domain.projects.work.models import WorkTaskCurrent, WorkTaskVersion

    rows = (
        s.execute(
            select(WorkTaskVersion)
            .join(
                WorkTaskCurrent,
                (WorkTaskCurrent.tenant_id == WorkTaskVersion.tenant_id)
                & (WorkTaskCurrent.version_id == WorkTaskVersion.id),
            )
            .where(
                WorkTaskVersion.tenant_id == ctx.tenant_id,
                WorkTaskVersion.product_id == product_id,
                WorkTaskVersion.project_id == project_id,
            )
            .order_by(WorkTaskVersion.task_id)
        )
        .scalars()
        .all()
    )
    linked = {}
    unknown_ids = set()
    for row in rows:
        ref = (row.body or {}).get("plan_task")
        if not ref:
            continue
        identity = UUID(ref["id"])
        if identity not in keys_by_task:
            unknown_ids.add(identity)
        linked.setdefault(identity, []).append(row)
    if unknown_ids:
        # Work linked to an earlier plan revision keeps its planned key.
        for task in s.scalars(
            select(ProjectTask).where(
                ProjectTask.tenant_id == ctx.tenant_id,
                ProjectTask.product_id == product_id,
                ProjectTask.project_id == project_id,
                ProjectTask.id.in_(sorted(unknown_ids)),
            )
        ):
            keys_by_task[task.id] = task.key
    facts = {}
    for identity, versions in linked.items():
        key = keys_by_task.get(identity)
        if key is None:
            continue
        bucket = facts.setdefault(key, [])
        for row in versions:
            body = row.body
            start = (body.get("actual_start") or {}).get("actual_at")
            submission = body.get("submission")
            finish = (
                submission["time"]["actual_at"]
                if submission
                and row.state
                in (
                    "submitted",
                    "completed",
                )
                else None
            )
            bucket.append(
                {
                    "task_id": str(row.task_id),
                    "version_id": str(row.id),
                    "revision": row.revision,
                    "state": row.state,
                    "start": start,
                    "finish": finish,
                    "timezone": (body.get("actual_start") or {}).get("original_timezone"),
                }
            )
    result = {}
    for key, items in sorted(facts.items()):
        items.sort(key=lambda item: item["task_id"])
        starts = [_instant(item["start"]) for item in items if item["start"]]
        finished = all(item["finish"] for item in items)
        result[key] = {
            "start": _iso(min(starts)) if starts else None,
            "finish": _iso(max(_instant(item["finish"]) for item in items)) if finished else None,
            "work_tasks": items,
        }
    return result


def gather(s, ctx, product_id, project, *, at):
    from pdos_next.domain.projects.governance.service import promise_facts

    require(project.current_plan_id is not None, "项目还没有应用的计划，无法重算预测。")
    plan = s.scalar(
        select(PlanRevision).where(
            PlanRevision.tenant_id == ctx.tenant_id,
            PlanRevision.product_id == product_id,
            PlanRevision.project_id == project.id,
            PlanRevision.id == project.current_plan_id,
        )
    )
    require(
        plan is not None and plan.status == "applied", "当前计划不可读。", "FORBIDDEN_SCOPE", 403
    )
    proposal = s.get(PlanProposal, plan.proposal_id)
    require(proposal is not None, "当前计划的固定输入不可读。", "INTEGRITY_MISMATCH")
    schedule = ScheduleInput.model_validate({
        key: proposal.input_snapshot[key] for key in ("start", "calendar", "tasks")
    })
    calendar_basis = None
    if "npi" in proposal.input_snapshot:
        from pdos_next.domain.projects.npi.planning import scheduling_calendar

        schedule, calendar_basis = scheduling_calendar(s, ctx, schedule)
    tasks = s.scalars(
        select(ProjectTask).where(
            ProjectTask.tenant_id == ctx.tenant_id,
            ProjectTask.product_id == product_id,
            ProjectTask.project_id == project.id,
            ProjectTask.plan_id == plan.id,
        )
    ).all()
    task_ids = {task.key: task.id for task in tasks}
    require(
        set(task_ids) == {task.key for task in schedule.tasks},
        "计划任务与固定输入不一致。",
        "INTEGRITY_MISMATCH",
    )
    facts = _work_facts(s, ctx, product_id, project.id, {task.id: task.key for task in tasks})
    zone = ZoneInfo(schedule.calendar.timezone)
    local_day = at.astimezone(zone).date()
    # The refresh is "as of today" in the plan calendar: the same facts on the
    # same calendar day are the same intent and give the same exact result. A
    # fact already recorded today moves the snapshot to that fact, never later.
    recorded = [
        _instant(value)
        for fact in facts.values()
        for value in (fact["start"], fact["finish"])
        if value is not None
    ]
    as_of = max([datetime.combine(local_day, time.min, tzinfo=zone).astimezone(UTC), *recorded])
    commitments = [
        {
            "commitment_id": item["id"],
            "task_id": item["task_id"],
            "plan_task_id": item["plan_task"]["id"] if item["plan_task"] else None,
            "promised_at": item["promised_at"],
            "fulfilled": item["fulfilled"],
        }
        for item in sorted(promise_facts(s, ctx, product_id, project.id), key=lambda row: row["id"])
    ]
    keys = {str(identity): key for key, identity in task_ids.items()}
    for item in commitments:
        item["key"] = keys.get(item["plan_task_id"]) if item["plan_task_id"] else None
        if item["plan_task_id"] and item["key"] is None:
            old = s.get(ProjectTask, UUID(item["plan_task_id"]))
            item["key"] = old.key if old is not None and old.project_id == project.id else None
    material = {
        "composition": COMPOSITION,
        "algorithm_version": ALGORITHM_VERSION,
        "plan": {"id": str(plan.id), "revision": plan.revision},
        "proposal": {"id": str(proposal.id), "revision": proposal.revision},
        "schedule": schedule.model_dump(mode="json"),
        "facts": facts,
        "commitments": commitments,
        "as_of_day": local_day.isoformat(),
        **({"calendar_basis": calendar_basis} if calendar_basis else {}),
    }
    return Inputs(
        plan=plan,
        proposal=proposal,
        schedule=schedule,
        task_ids=task_ids,
        facts=facts,
        as_of=as_of,
        as_of_day=local_day.isoformat(),
        input_sha256=digest(material),
        commitments=commitments,
        calendar_basis=calendar_basis,
    )


def _calendar(schedule, reference):
    calendar = schedule.calendar
    intervals = tuple(
        EngineInterval(start_minute=item.start_minute, end_minute=item.end_minute)
        for item in sorted(calendar.intervals, key=lambda item: item.start_minute)
    )
    return CalendarSnapshot(
        calendar_id=calendar.key,
        version=calendar.version,
        timezone=calendar.timezone,
        weekly=tuple(
            WeekdaySchedule(weekday=day, intervals=intervals)
            for day in sorted(calendar.working_weekdays)
        ),
        exceptions=tuple(
            CalendarException(day=day, intervals=(), source=reference)
            for day in sorted(calendar.holidays)
        ) + tuple(
            CalendarException(day=day, intervals=intervals, source=reference)
            for day in sorted(calendar.makeup_workdays)
        ),
    )


def _estimate(minimum, maximum, reference, measure="total"):
    return DurationEstimate(
        minimum=Decimal(minimum) if minimum is not None else None,
        maximum=Decimal(maximum) if maximum is not None else None,
        measure=measure,
        source=reference,
        confidence="unknown",
    )


def compute(inputs):
    """Compose fixed actual tasks with one engine run over the unfinished tasks."""
    schedule, plan = inputs.schedule, inputs.plan
    reference = Reference(source_id=f"plan:{plan.id}", version=str(plan.revision))
    tasks = {task.key: task for task in schedule.tasks}
    finished = {key: fact for key, fact in inputs.facts.items() if fact["finish"]}
    started = {
        key: fact for key, fact in inputs.facts.items() if fact["start"] and not fact["finish"]
    }
    plan_start = schedule.start.astimezone(UTC)
    rows = {}
    for key, fact in finished.items():
        rows[key] = {
            "key": key,
            "origin": "actual_anchor",
            "status": "exact",
            "start": {"earliest": fact["start"], "latest": fact["start"]},
            "finish": {"earliest": fact["finish"], "latest": fact["finish"]},
            "float_minutes": None,
            "working_float_minutes": None,
            "critical": None,
            "issues": [] if fact["start"] else ["actual_start_unknown"],
        }
    unfinished = [key for key in tasks if key not in finished]
    engine = None
    if unfinished:
        calendar = _calendar(schedule, reference)
        nodes = []
        for key in unfinished:
            task = tasks[key]
            source = Reference(
                source_id=f"plan_task:{inputs.task_ids[key]}", version=str(plan.revision)
            )
            release = max(
                [
                    plan_start,
                    *([task.not_before.astimezone(UTC)] if task.not_before else []),
                    *(
                        _instant(finished[pred]["finish"])
                        for pred in task.depends_on
                        if pred in finished
                    ),
                ]
            )
            fact = started.get(key)
            nodes.append(
                NodeSnapshot(
                    node_id=key,
                    calendar_id=calendar.calendar_id,
                    work=_estimate(task.duration_min_minutes, task.duration_max_minutes, source),
                    # The plan registers no separate waiting time: an explicit sourced zero.
                    waiting=_estimate(0, 0, reference, "remaining" if fact else "total"),
                    allocation_basis="plan_task",
                    not_before=release,
                    time_records=(
                        TimeRecord(
                            time_kind="Actual",
                            version=fact["work_tasks"][0]["version_id"],
                            original_timezone=fact["work_tasks"][0]["timezone"]
                            or schedule.calendar.timezone,
                            source=Reference(
                                source_id=f"work_task:{fact['work_tasks'][0]['task_id']}",
                                version=str(fact["work_tasks"][0]["revision"]),
                            ),
                            start=_instant(fact["start"]),
                        ),
                    )
                    if fact
                    else (),
                )
            )
        dependencies = tuple(
            Dependency(predecessor_id=pred, successor_id=key, relation="FS", source=reference)
            for key in unfinished
            for pred in tasks[key].depends_on
            if pred not in finished
        )
        engine = calculate_forecast(
            ForecastInput(
                snapshot_id=f"forecast:{plan.id}",
                version=inputs.input_sha256,
                as_of=inputs.as_of,
                calendars=(calendar,),
                nodes=tuple(nodes),
                dependencies=dependencies,
            )
        )
        for node in engine.nodes:
            rows[node.node_id] = {
                "key": node.node_id,
                "origin": node.origin,
                "status": node.status,
                "start": node.start.model_dump(mode="json"),
                "finish": node.finish.model_dump(mode="json"),
                "float_minutes": node.float_minutes,
                "working_float_minutes": node.working_float_minutes,
                "critical": node.critical,
                "issues": sorted({issue.code for issue in node.issues}),
            }
        if not engine.nodes:
            # A structural engine refusal is shown as unknown, never as a date.
            codes = sorted({issue.code for issue in engine.issues})
            for key in unfinished:
                rows[key] = {
                    "key": key,
                    "origin": "actual_and_remaining" if key in started else "estimate",
                    "status": "unknown",
                    "start": {"earliest": None, "latest": None},
                    "finish": {"earliest": None, "latest": None},
                    "float_minutes": None,
                    "working_float_minutes": None,
                    "critical": None,
                    "issues": codes,
                }
    planned = {item["key"]: item for item in plan.forecast.get("tasks", [])}
    ordered = []
    for task in schedule.tasks:
        row = rows[task.key]
        baseline = planned.get(task.key, {})
        planned_finish = baseline.get("earliest_finish")
        forecast_finish = row["finish"]["earliest"]
        row.update(
            {
                "task_id": str(inputs.task_ids[task.key]),
                "depends_on": list(task.depends_on),
                "planned_start": baseline.get("earliest_start"),
                "planned_finish": planned_finish,
                "planned_latest_finish": baseline.get("latest_finish"),
                "shift_minutes": int(
                    (_instant(forecast_finish) - _instant(planned_finish)).total_seconds() // 60
                )
                if forecast_finish and planned_finish
                else None,
                "actual": inputs.facts.get(task.key),
            }
        )
        ordered.append(row)
    latest = [row["finish"]["latest"] for row in ordered]
    earliest = [row["finish"]["earliest"] for row in ordered]
    project_finish = {
        "earliest": _iso(max(_instant(value) for value in earliest)) if all(earliest) else None,
        "latest": _iso(max(_instant(value) for value in latest)) if all(latest) else None,
    }
    by_key = {row["key"]: row for row in ordered}
    commitments = []
    for item in inputs.commitments:
        row = by_key.get(item["key"]) if item["key"] else None
        forecast = row["finish"]["latest"] if row else None
        commitments.append(
            {
                **item,
                "forecast_finish": forecast,
                "impact": "unknown"
                if not forecast or not item["promised_at"]
                else "later"
                if _instant(forecast) > _instant(item["promised_at"])
                else "within",
            }
        )
    issues = sorted({code for row in ordered for code in row["issues"]})
    status = (
        "complete"
        if project_finish["latest"] and not (engine and engine.status != "complete")
        else "partial"
    )
    float_status = engine.float_status if engine else "not_calculated"
    return {
        "composition": COMPOSITION,
        "algorithm_version": ALGORITHM_VERSION,
        "input_sha256": inputs.input_sha256,
        "engine_input_sha256": engine.input_sha256 if engine else None,
        "engine_candidate_sha256": engine.candidate_sha256 if engine else None,
        "as_of": inputs.as_of.isoformat(),
        "as_of_day": inputs.as_of_day,
        "plan": {"id": str(plan.id), "revision": plan.revision},
        "calendar": {
            "key": schedule.calendar.key,
            "version": schedule.calendar.version,
            "timezone": schedule.calendar.timezone,
            "label": (
                inputs.calendar_basis["basis_label"] if inputs.calendar_basis
                else NO_CALENDAR_LABEL if not schedule.calendar.holidays else None
            ),
            **(inputs.calendar_basis or {}),
        },
        "status": status,
        "float_status": float_status,
        "critical_path": [row["key"] for row in ordered if row["critical"]],
        "project_finish": project_finish,
        "planned_finish": plan.forecast.get("earliest_finish"),
        "tasks": ordered,
        "commitments": commitments,
        "issues": issues,
        "effect": (
            "系统重算：只写新的预测；计划版本、计划任务、基线与承诺都不变。"
            "预测晚于承诺时只显示差异。"
        ),
    }
