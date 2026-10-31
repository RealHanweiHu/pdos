"""Finite work transitions; IO, project membership and source proof stay with the owner."""

from datetime import UTC

from pdos_next.domain.release.rules import digest as digest
from pdos_next.errors import DomainError

from .constants import ACCEPT, ASSIGN, CREATE, REVIEW, START, SUBMIT
from .schemas import (
    PAYLOADS,
    CommitmentAcceptPayload,
    CommitmentSnapshot,
    Review,
    StatusPlan,
    StatusUpdatePayload,
    Submission,
    TaskSnapshot,
    TimeFact,
)


def require(test, message, code="INVALID_STATE", status=409):
    if not test:
        raise DomainError(code, message, status)


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token"})


def _at(at):
    require(at.utcoffset() is not None, "须使用服务器aware时钟。", "VALIDATION_FAILED", 422)
    return at.astimezone(UTC)


def _time(payload, actor_id, at):
    require(
        payload.actual_at <= at, "实际发生时间不能晚于服务器登记时点。", "VALIDATION_FAILED", 422
    )
    return TimeFact(
        actual_at=payload.actual_at,
        original_timezone=payload.original_timezone,
        calendar_id=payload.calendar_id,
        actor_id=actor_id,
        recorded_at=at,
    )


def transition(operation, payload, *, current=None, actor_id, at, task_id=None):
    """Return one new snapshot, never mutate the old plan or create a commitment."""
    payload = PAYLOADS[operation].model_validate(payload)
    at = _at(at)
    if operation == CREATE:
        require(current is None and task_id is not None, "新任务须由实际owner分配身份。")
        return TaskSnapshot(
            task_id=task_id,
            revision=1,
            state="proposed",
            title=payload.title,
            goal=payload.goal,
            outcomes=payload.outcomes,
            plan_task=payload.plan_task,
            npi_template=payload.npi_template,
            g0_open_item=payload.g0_open_item,
        )
    current = TaskSnapshot.model_validate(current)
    require(
        payload.task.id == current.task_id and payload.task.revision == current.revision,
        "任务版本已变化，请重新核对。",
        "VERSION_CONFLICT",
    )
    data = current.model_dump()
    data["revision"] += 1
    if operation == ASSIGN:
        require(current.state in {"proposed", "assigned"}, "已承接的责任不能被静默转交。")
        data.update(
            state="assigned", assignee_id=payload.assignee_id, recipient_id=payload.recipient_id
        )
    elif operation == ACCEPT:
        require(current.state == "assigned", "须先明确分派任务。")
        require(
            current.assignee_id == actor_id, "只有实际受派人可承接责任。", "FORBIDDEN_SCOPE", 403
        )
        data["state"] = "accepted"
    elif operation == START:
        require(current.state == "accepted", "须本人承接后再登记实际开始。")
        require(current.assignee_id == actor_id, "只有承接人可登记开始。", "FORBIDDEN_SCOPE", 403)
        data.update(state="in_progress", actual_start=_time(payload, actor_id, at))
    elif operation == SUBMIT:
        require(current.state == "in_progress", "只有进行中的任务可以提交成果。")
        require(current.assignee_id == actor_id, "只有承接人可提交成果。", "FORBIDDEN_SCOPE", 403)
        require(
            current.actual_start is not None
            and current.actual_start.actual_at <= payload.actual_at,
            "提交不能早于实际开始。",
            "VALIDATION_FAILED",
            422,
        )
        if current.review is not None:
            require(
                current.review.time.actual_at <= payload.actual_at,
                "重新提交不能早于上次退回。",
                "VALIDATION_FAILED",
                422,
            )
        require(
            {value.key for value in payload.results} <= {value.key for value in current.outcomes},
            "成果不能指向任务之外的结果要求。",
            "VALIDATION_FAILED",
            422,
        )
        data.update(
            state="submitted",
            submission=Submission(time=_time(payload, actor_id, at), results=payload.results),
            review=None,
        )
    elif operation == REVIEW:
        require(
            current.state == "submitted" and current.submission is not None, "须有实际已提交成果。"
        )
        require(
            current.recipient_id == actor_id, "只有明确的成果接收人可验收。", "FORBIDDEN_SCOPE", 403
        )
        require(
            current.submission.time.actual_at <= payload.actual_at,
            "验收不能早于实际提交。",
            "VALIDATION_FAILED",
            422,
        )
        keys = {value.key for value in current.outcomes}
        require(
            {value.key for value in payload.checks} <= keys,
            "验收项不属于此任务。",
            "VALIDATION_FAILED",
            422,
        )
        if payload.decision == "accepted":
            required = {value.key for value in current.outcomes if value.required}
            present = {
                value.key for value in current.submission.results if value.status == "present"
            }
            accepted = {value.key for value in payload.checks if value.decision == "accepted"}
            require(
                required <= present & accepted,
                "必需成果仍有缺失、部分结果或未接受项。",
                "MISSING_REQUIRED_EVIDENCE",
            )
        data.update(
            state="completed" if payload.decision == "accepted" else "in_progress",
            review=Review(
                time=_time(payload, actor_id, at), decision=payload.decision, checks=payload.checks
            ),
        )
    else:
        raise DomainError("VALIDATION_FAILED", "此操作不是任务状态迁移。", 422)
    return TaskSnapshot.model_validate(data)


def commitment_plan(payload, *, task, actor_id, previous=None, at):
    payload = CommitmentAcceptPayload.model_validate(payload)
    task = TaskSnapshot.model_validate(task)
    at = _at(at)
    require(
        payload.task.id == task.task_id and payload.task.revision == task.revision,
        "任务版本已变化。",
        "VERSION_CONFLICT",
    )
    require(task.assignee_id == actor_id, "只有已承接的本人可作出承诺。", "FORBIDDEN_SCOPE", 403)
    require(
        task.state in {"accepted", "in_progress", "submitted"},
        "先承接责任；已完成任务不新增未结承诺。",
    )
    require(
        set(payload.outcome_keys) <= {value.key for value in task.outcomes},
        "承诺结果范围超出任务。",
        "VALIDATION_FAILED",
        422,
    )
    revision = 1
    if previous is None:
        require(payload.replaces is None, "没有原承诺不能声明替代版本。", "VERSION_CONFLICT")
    else:
        previous = CommitmentSnapshot.model_validate(previous)
        require(
            payload.replaces is not None and payload.replaces.revision == previous.revision,
            "必须精确替代当前承诺。",
            "VERSION_CONFLICT",
        )
        require(
            (previous.task_id, previous.promisor_id, previous.recipient_id)
            == (task.task_id, actor_id, payload.recipient_id),
            "不同任务、承诺人或接收人的承诺不能合并。",
            "FORBIDDEN_SCOPE",
            403,
        )
        revision = previous.revision + 1
    return CommitmentSnapshot(
        revision=revision,
        task_id=task.task_id,
        task_revision=task.revision,
        promisor_id=actor_id,
        recipient_id=payload.recipient_id,
        outcome_keys=payload.outcome_keys,
        promised_at=payload.promised_at,
        original_timezone=payload.original_timezone,
        calendar_id=payload.calendar_id,
        replaces=payload.replaces,
        recorded_at=at,
    )


def status_plan(payload, *, tasks=(), actor_id, at):
    payload = StatusUpdatePayload.model_validate(payload)
    tasks = tuple(TaskSnapshot.model_validate(value) for value in tasks)
    require(
        {(value.task_id, value.revision) for value in tasks}
        == {(value.id, value.revision) for value in payload.task_refs},
        "状态更新须引用实际读取的固定任务版本。",
        "VERSION_CONFLICT",
    )
    return StatusPlan(
        fact_summary=payload.fact_summary,
        next_steps=payload.next_steps,
        task_refs=payload.task_refs,
        actor_id=actor_id,
        recorded_at=_at(at),
    )
