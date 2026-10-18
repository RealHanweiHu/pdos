"""Promise scope and recipient authority are separate from task acceptance."""

from copy import deepcopy
from types import SimpleNamespace as Row
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.work_fulfillment.rules import review_state
from pdos_next.domain.work_fulfillment.schemas import CommitmentReviewPayload
from pdos_next.errors import DomainError


@pytest.fixture
def case():
    actor, promisor = uuid4(), uuid4()
    results = [
        Row(key="drawing", status="present", sources=[object()]),
        Row(key="inspection", status="present", sources=[object()]),
    ]
    submission = Row(submission=Row(results=results))
    promise = Row(recipient_id=actor, promisor_id=promisor, outcome_keys=["drawing", "inspection"])
    task = Row(assignee_id=promisor, submission=submission.submission, state="in_progress")
    payload = Row(
        expected_review_revision=0,
        decision="accepted",
        checks=[Row(key=key, decision="accepted") for key in promise.outcome_keys],
    )
    return Row(actor=actor, promise=promise, task=task, submission=submission, payload=payload)


def evaluate(c, previous=None):
    return review_state(
        c.payload, c.promise, c.task, c.submission, actor_id=c.actor, previous=previous
    )


def test_all_promised_outcomes_can_be_fulfilled_without_task_completion(case):
    assert evaluate(case) == "fulfilled"
    assert case.task.state == "in_progress"


@pytest.mark.parametrize("missing", ["partial", "missing"])
def test_even_optional_but_promised_result_must_be_present(case, missing):
    case.submission.submission.results[1].status = missing
    with pytest.raises(DomainError):
        evaluate(case)


def test_no_task_required_set_shortcut(case):
    case.payload.checks.pop()
    with pytest.raises(DomainError):
        evaluate(case)


def test_recipient_and_promisor_may_be_same_person(case):
    case.promise.promisor_id = case.actor
    case.task.assignee_id = case.actor
    assert evaluate(case) == "fulfilled"


def test_return_preserves_open_and_can_be_reviewed_again(case):
    case.payload.decision = "returned"
    case.payload.checks[0].decision = "unknown"
    assert evaluate(case) == "open"
    case.payload.decision = "accepted"
    case.payload.checks[0].decision = "accepted"
    case.payload.expected_review_revision = 1
    assert evaluate(case, Row(revision=1, state="open")) == "fulfilled"


@pytest.mark.parametrize("change", ["actor", "assignee", "submission", "watermark", "terminal"])
def test_stale_or_different_owner_cannot_confirm(case, change):
    previous = None
    if change == "actor":
        case.actor = uuid4()
    elif change == "assignee":
        case.task.assignee_id = uuid4()
    elif change == "submission":
        case.task.submission = None
    elif change == "watermark":
        case.payload.expected_review_revision = 1
    else:
        previous = Row(revision=0, state="fulfilled")
    with pytest.raises(DomainError):
        evaluate(case, previous)


def test_client_cannot_supply_fulfilled_state_or_fabricated_actual_time():
    ref = {"id": str(uuid4()), "revision": 1}
    value = {
        "project_id": str(uuid4()),
        "commitment": ref,
        "task": ref,
        "submission": ref,
        "expected_review_revision": 0,
        "decision": "accepted",
        "checks": [{"key": "drawing", "decision": "accepted", "reason": "Actual result"}],
        "sources": [{**ref, "kind": "artifact", "position": "line:1"}],
        "reason": "Recipient check",
    }
    CommitmentReviewPayload.model_validate(value)
    for key, extra in (
        ("state", "fulfilled"),
        ("actual_at", "2026-10-18T00:00:00Z"),
        ("recipient_id", str(uuid4())),
        ("expected_review_revision", True),
    ):
        with pytest.raises(ValidationError):
            CommitmentReviewPayload.model_validate({**deepcopy(value), key: extra})
