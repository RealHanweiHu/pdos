"""Business transitions preserve responsibility, commitments and real outcomes."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.work_management import rules
from pdos_next.domain.work_management.constants import (
    ACCEPT,
    ASSIGN,
    COMMIT,
    CREATE,
    REVIEW,
    START,
    STATUS,
    SUBMIT,
)
from pdos_next.domain.work_management.schemas import PAYLOADS, Result
from pdos_next.errors import DomainError

AT = datetime(2026, 10, 17, 10, tzinfo=UTC)
OWNER, PERSON, RECIPIENT, OTHER, PROJECT, TASK, SOURCE = (uuid4() for _ in range(7))
BASE = {
    "project_id": str(PROJECT),
    "sources": [
        {
            "id": str(SOURCE),
            "revision": 1,
            "kind": "artifact",
            "position": "line:1;quote_sha256:" + "a" * 64,
        }
    ],
    "reason": "实际会议原件",
}
CREATE_DATA = {
    "title": "提交复测记录",
    "goal": "完成固定范围复查",
    "outcomes": [{"key": "report", "text": "原始复测记录", "required": True}],
    "plan_task": None,
}


def payload(operation, **value):
    return PAYLOADS[operation].model_validate({**BASE, **value})


def ref(task):
    return {"id": str(task.task_id), "revision": task.revision}


def step(operation, current=None, actor=OWNER, **value):
    if current is not None:
        value.setdefault("task", ref(current))
    return rules.transition(
        operation,
        payload(operation, **value),
        current=current,
        actor_id=actor,
        at=AT,
        task_id=TASK if current is None else None,
    )


def accepted():
    proposed = step(CREATE, **CREATE_DATA)
    assigned = step(ASSIGN, proposed, assignee_id=str(PERSON), recipient_id=str(RECIPIENT))
    return step(ACCEPT, assigned, actor=PERSON)


def clock(minute=0):
    return {
        "actual_at": AT - timedelta(minutes=10 - minute),
        "original_timezone": "Asia/Shanghai",
        "calendar_id": None,
    }


def submitted(status="present"):
    start = step(START, accepted(), actor=PERSON, **clock())
    return step(
        SUBMIT,
        start,
        actor=PERSON,
        results=[
            {"key": "report", "text": "实际交付", "status": status, "sources": BASE["sources"]}
        ],
        **clock(1),
    )


def test_schema_has_only_closed_operation_fields_and_exact_original_references():
    assert set(PAYLOADS) == {CREATE, ASSIGN, ACCEPT, COMMIT, START, SUBMIT, REVIEW, STATUS}
    for extra in (
        {"visibility": "category"},
        {"owner_id": str(OWNER)},
        {"policy": {"authorized": True}},
    ):
        with pytest.raises(ValidationError):
            payload(CREATE, **CREATE_DATA, **extra)
    for sources in ([], [{**BASE["sources"][0], "kind": "domain"}]):
        with pytest.raises(ValidationError):
            PAYLOADS[CREATE].model_validate({**BASE, **CREATE_DATA, "sources": sources})


def test_present_result_requires_own_source_while_partial_and_missing_keep_their_status():
    data = {"key": "report", "text": "实际结果", "sources": []}
    with pytest.raises(ValidationError, match="own original sources"):
        Result.model_validate({**data, "status": "present"})
    present = Result.model_validate({**data, "status": "present", "sources": BASE["sources"]})
    assert present.status == "present" and present.sources
    for status in ("partial", "missing"):
        result = Result.model_validate({**data, "status": status})
        assert result.status == status and result.sources == ()


def test_assignment_is_not_responsibility_acceptance_or_a_date_commitment():
    proposed = step(CREATE, **CREATE_DATA)
    assigned = step(ASSIGN, proposed, assignee_id=str(PERSON), recipient_id=str(RECIPIENT))
    assert proposed.state == "proposed" and assigned.state == "assigned"
    assert "promised_at" not in assigned.model_dump() and assigned.actual_start is None
    with pytest.raises(DomainError):
        step(ACCEPT, assigned, actor=OWNER)
    actual = step(ACCEPT, assigned, actor=PERSON)
    assert actual.state == "accepted" and assigned.state == "assigned"


def test_accepted_responsibility_cannot_be_silently_reassigned():
    with pytest.raises(DomainError):
        step(ASSIGN, accepted(), assignee_id=str(OTHER), recipient_id=str(RECIPIENT))


def test_exact_task_revision_is_required_for_every_transition():
    task = accepted()
    with pytest.raises(DomainError) as error:
        step(START, task, actor=PERSON, task={"id": str(TASK), "revision": 1}, **clock())
    assert error.value.code == "VERSION_CONFLICT"


def test_partial_submission_is_not_completion_and_return_retains_the_old_fact():
    original = submitted("partial")
    assert original.state == "submitted"
    with pytest.raises(DomainError):
        step(
            REVIEW,
            original,
            actor=RECIPIENT,
            decision="accepted",
            checks=[{"key": "report", "decision": "accepted", "reason": "已看"}],
            **clock(2),
        )
    returned = step(
        REVIEW,
        original,
        actor=RECIPIENT,
        decision="returned",
        checks=[{"key": "report", "decision": "unknown", "reason": "缺原始读数"}],
        **clock(2),
    )
    assert returned.state == "in_progress" and original.state == "submitted"
    assert returned.submission == original.submission
    resubmitted = step(
        SUBMIT,
        returned,
        actor=PERSON,
        results=[
            {"key": "report", "text": "补交原件", "status": "present", "sources": BASE["sources"]}
        ],
        **clock(3),
    )
    done = step(
        REVIEW,
        resubmitted,
        actor=RECIPIENT,
        decision="accepted",
        checks=[{"key": "report", "decision": "accepted", "reason": "对应原件已接受"}],
        **clock(4),
    )
    assert done.state == "completed" and done.revision == 8
    assert returned.review.decision == "returned"


def test_only_assignee_submits_and_explicit_recipient_accepts_without_second_person_rule():
    task = submitted()
    with pytest.raises(DomainError):
        step(
            REVIEW,
            task,
            actor=OTHER,
            decision="accepted",
            checks=[{"key": "report", "decision": "accepted", "reason": "核对"}],
            **clock(2),
        )
    self_task = step(CREATE, **CREATE_DATA)
    self_task = step(ASSIGN, self_task, assignee_id=str(OWNER), recipient_id=str(OWNER))
    self_task = step(ACCEPT, self_task)
    assert self_task.assignee_id == self_task.recipient_id == OWNER


@pytest.mark.parametrize("operation", [START, SUBMIT, REVIEW])
def test_future_actual_times_are_rejected(operation):
    task = (
        accepted()
        if operation == START
        else step(START, accepted(), actor=PERSON, **clock())
        if operation == SUBMIT
        else submitted()
    )
    extra = (
        {
            "results": [
                {"key": "report", "text": "成果", "status": "present", "sources": BASE["sources"]}
            ]
        }
        if operation == SUBMIT
        else {
            "decision": "returned",
            "checks": [{"key": "report", "decision": "unknown", "reason": "待核对"}],
        }
        if operation == REVIEW
        else {}
    )
    with pytest.raises(DomainError):
        step(
            operation,
            task,
            actor=RECIPIENT if operation == REVIEW else PERSON,
            **{**clock(), "actual_at": AT + timedelta(seconds=1)},
            **extra,
        )


def test_start_submission_review_have_monotone_actual_times():
    task = step(START, accepted(), actor=PERSON, **clock(3))
    with pytest.raises(DomainError):
        step(
            SUBMIT,
            task,
            actor=PERSON,
            results=[
                {"key": "report", "text": "成果", "status": "present", "sources": BASE["sources"]}
            ],
            **clock(2),
        )
    with pytest.raises(DomainError):
        step(
            REVIEW,
            submitted(),
            actor=RECIPIENT,
            decision="returned",
            checks=[{"key": "report", "decision": "unknown", "reason": "待核对"}],
            **clock(),
        )


def test_commitments_are_per_recipient_with_explicit_unknown_date():
    task = accepted()

    def make(recipient, **other):
        return payload(
            COMMIT,
            task=ref(task),
            recipient_id=str(recipient),
            outcome_keys=["report"],
            promised_at=None,
            original_timezone="Asia/Shanghai",
            calendar_id=None,
            **other,
        )

    a = rules.commitment_plan(make(RECIPIENT), task=task, actor_id=PERSON, at=AT)
    b = rules.commitment_plan(make(OTHER), task=task, actor_id=PERSON, at=AT)
    assert a.recipient_id != b.recipient_id and a.promised_at is None
    with pytest.raises(DomainError):
        rules.commitment_plan(
            make(OTHER, replaces={"id": str(uuid4()), "revision": 1}),
            task=task,
            actor_id=PERSON,
            previous=a,
            at=AT,
        )
    revised = rules.commitment_plan(
        make(RECIPIENT, replaces={"id": str(uuid4()), "revision": 1}),
        task=task,
        actor_id=PERSON,
        previous=a,
        at=AT,
    )
    assert revised.revision == 2 and a.revision == 1


def test_aware_times_normalize_utc_and_timezone_is_validated_without_inventing_calendar():
    task = accepted()
    value = payload(
        COMMIT,
        task=ref(task),
        recipient_id=str(RECIPIENT),
        outcome_keys=["report"],
        promised_at="2026-10-18T18:30:00+08:00",
        original_timezone="Asia/Shanghai",
        calendar_id=None,
    )
    assert value.promised_at.isoformat() == "2026-10-18T10:30:00+00:00"
    for change in ({"promised_at": "2026-10-18T18:30:00"}, {"original_timezone": "Made/Up"}):
        with pytest.raises(ValidationError):
            PAYLOADS[COMMIT].model_validate({**value.model_dump(), **change})


def test_named_status_update_only_references_actual_fixed_tasks():
    task = accepted()
    data = payload(
        STATUS, fact_summary="已有本人承接", next_steps="下周核对成果", task_refs=[ref(task)]
    )
    before = task.model_dump()
    plan = rules.status_plan(data, tasks=(task,), actor_id=OWNER, at=AT)
    assert plan.task_refs[0].revision == task.revision and task.model_dump() == before
    assert not {"promised_at", "state", "assigned_to"} & set(plan.model_dump())
    with pytest.raises(DomainError):
        rules.status_plan(data, tasks=(), actor_id=OWNER, at=AT)


def test_semantic_removes_only_confirmation_token():
    task = accepted()
    value = payload(ACCEPT, task=ref(task), confirmation_token="x" * 32)
    assert "confirmation_token" not in rules.semantic(value)
    assert rules.semantic(value)["reason"] == BASE["reason"]
