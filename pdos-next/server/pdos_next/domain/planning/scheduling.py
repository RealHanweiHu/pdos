"""Forward FS forecasts under declared duration bounds; performs no writes or reservations."""

from datetime import datetime

from pydantic import ValidationError

from pdos_next.schemas.planning import CalendarRef, ScheduleInput, ScheduleResult, TaskSchedule

from .calendar import ScheduleError, WorkingCalendar, ceil_minute


def _validated(request: ScheduleInput | dict) -> ScheduleInput:
    try:
        return ScheduleInput.model_validate(request)
    except ValidationError as exc:
        errors = exc.errors()
        code = "INVALID_INPUT"
        for item in errors:
            message = item["msg"]
            for known in (
                "INVALID_TIMEZONE",
                "INVALID_CALENDAR",
                "INVALID_DURATION",
                "INVALID_DEPENDENCY",
                "INVALID_START",
            ):
                if known in message:
                    code = known
                    break
            if code != "INVALID_INPUT":
                break
            path = item["loc"]
            if "duration_min_minutes" in path or "duration_max_minutes" in path:
                code = "INVALID_DURATION"
            elif path and path[0] == "start":
                code = "INVALID_START"
            elif path and path[0] == "calendar":
                code = "INVALID_CALENDAR"
        raise ScheduleError(code, "Plan calculation input is invalid") from exc


def schedule(request: ScheduleInput | dict) -> ScheduleResult:
    """Return earliest/minimum and latest/maximum duration forecasts in UTC.

    Both are forward predictions under one versioned calendar, not float or approval.
    A missing bound stays None and prevents predicting that side of downstream tasks.
    Zero-duration milestones retain a valid boundary instant, including outside shifts.
    """
    request = _validated(request)
    tasks = {task.key: task for task in request.tasks}
    if len(tasks) != len(request.tasks):
        raise ScheduleError("DUPLICATE_TASK", "Task keys must be unique")
    outgoing = {key: [] for key in tasks}
    pending = {key: len(task.depends_on) for key, task in tasks.items()}
    for key, task in tasks.items():
        missing = tuple(dependency for dependency in task.depends_on if dependency not in tasks)
        if missing:
            raise ScheduleError(
                "MISSING_DEPENDENCY",
                "A task references an absent dependency",
                task_keys=(key, *missing),
            )
        for dependency in task.depends_on:
            outgoing[dependency].append(key)
    queue = sorted(key for key, amount in pending.items() if amount == 0)
    order = []
    while queue:
        key = queue.pop(0)
        order.append(key)
        for successor in sorted(outgoing[key]):
            pending[successor] -= 1
            if pending[successor] == 0:
                queue.append(successor)
                queue.sort()
    if len(order) != len(tasks):
        unresolved = tuple(sorted(key for key in tasks if pending[key] > 0))
        raise ScheduleError(
            "DEPENDENCY_CYCLE", "Task dependencies contain a cycle", task_keys=unresolved
        )
    origin = ceil_minute(request.start)
    engine = WorkingCalendar(request.calendar)
    calendar_ref = CalendarRef(
        key=request.calendar.key,
        version=request.calendar.version,
        timezone=request.calendar.timezone,
        timezone_rules_sha256=engine.timezone_rules_sha256,
    )
    result: dict[str, TaskSchedule] = {}

    def prediction(task, maximum: bool) -> tuple[datetime | None, datetime | None, tuple[str, ...]]:
        side = "latest" if maximum else "earliest"
        missing = tuple(
            dependency
            for dependency in task.depends_on
            if getattr(result[dependency], f"{side}_finish") is None
        )
        if missing:
            return None, None, missing
        point = max([origin, *(getattr(result[key], f"{side}_finish") for key in task.depends_on)])
        duration = task.duration_max_minutes if maximum else task.duration_min_minutes
        milestone = task.duration_min_minutes == task.duration_max_minutes == 0
        begin = ceil_minute(point) if milestone else engine.snap(point)
        finish = None if duration is None else engine.advance(begin, duration)
        if finish is not None and (finish - origin).days > engine.horizon_days:
            raise ScheduleError("HORIZON_EXCEEDED", "Plan exceeds the ten-year calculation window")
        return begin, finish, ()

    for key in order:
        task = tasks[key]
        earliest_start, earliest_finish, lower_blocked = prediction(task, False)
        latest_start, latest_finish, upper_blocked = prediction(task, True)
        reasons = []
        if task.duration_min_minutes is None:
            reasons.append("DURATION_MIN_UNKNOWN")
        if task.duration_max_minutes is None:
            reasons.append("DURATION_MAX_UNKNOWN")
        if lower_blocked:
            reasons.append("DEPENDENCY_MIN_UNKNOWN")
        if upper_blocked:
            reasons.append("DEPENDENCY_MAX_UNKNOWN")
        result[key] = TaskSchedule(
            **task.model_dump(),
            earliest_start=earliest_start,
            earliest_finish=earliest_finish,
            latest_start=latest_start,
            latest_finish=latest_finish,
            calendar_ref=calendar_ref,
            unknown_reasons=tuple(reasons),
            blocked_by=tuple(sorted(set(lower_blocked + upper_blocked))),
        )
    warnings = []
    if origin != request.start:
        warnings.append("START_ROUNDED_UP_TO_MINUTE")
    if any(
        task.estimate_source is None
        and (task.duration_min_minutes is not None or task.duration_max_minutes is not None)
        for task in request.tasks
    ):
        warnings.append("ESTIMATE_SOURCE_UNSPECIFIED")

    def finish(side):
        endpoints = [getattr(item, f"{side}_finish") for item in result.values()]
        return None if any(point is None for point in endpoints) else max(endpoints)

    return ScheduleResult(
        input_start=request.start,
        calendar_ref=calendar_ref,
        tasks=tuple(result[key] for key in order),
        earliest_finish=finish("earliest"),
        latest_finish=finish("latest"),
        warnings=tuple(warnings),
    )
