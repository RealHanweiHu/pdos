"""A G0 risk keeps its real responsibility and its separate follow-up state."""

from copy import deepcopy
from types import SimpleNamespace as Row
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.project_risk.rules import next_state
from pdos_next.domain.project_risk.schemas import RiskFollowupPayload
from pdos_next.errors import DomainError


@pytest.fixture
def case():
    actor = uuid4()
    data = {
        "project_id": str(uuid4()),
        "risk": {"id": str(uuid4()), "decision_id": str(uuid4())},
        "current": None,
        "action": "close",
        "summary": "Actual named internal investigation completed",
        "sources": [{"kind": "artifact", "id": str(uuid4()), "revision": 1, "position": "line:1"}],
        "reason": "Record internal follow-up only",
    }
    return Row(
        actor=actor,
        basis={"kind": "risk", "owner_id": str(actor)},
        data=data,
        legacy_status="open",
    )


def evaluate(case, *, previous=None, **changes):
    payload = RiskFollowupPayload.model_validate({**case.data, **changes})
    return next_state(
        payload,
        case.basis,
        actor_id=case.actor,
        legacy_status=case.legacy_status,
        previous=previous,
    )


def test_named_followup_closes_independently_without_mutating_native_basis(case):
    original = deepcopy(case.basis)
    assert evaluate(case) == "closed"
    assert case.basis == original and case.legacy_status == "open"
    assert "task" not in case.data and "approval" not in case.data


def test_reopen_then_close_requires_each_exact_prior_followup_version(case):
    closed = Row(id=uuid4(), revision=1, state="closed")
    assert (
        evaluate(case, previous=closed, action="reopen", current={"id": closed.id, "revision": 1})
        == "open"
    )
    reopened = Row(id=uuid4(), revision=2, state="open")
    assert evaluate(case, previous=reopened, current={"id": reopened.id, "revision": 2}) == "closed"
    assert closed.state == "closed" and reopened.state == "open"


def test_project_owner_or_reviewer_identity_does_not_replace_named_g0_followup_person(case):
    case.actor = uuid4()
    with pytest.raises(DomainError) as raised:
        evaluate(case)
    assert raised.value.reason == "FORBIDDEN_SCOPE" and raised.value.status == 403


def test_task_kind_cannot_be_treated_as_risk(case):
    case.basis["kind"] = "task"
    with pytest.raises(DomainError) as raised:
        evaluate(case)
    assert raised.value.reason == "VALIDATION_FAILED"


@pytest.mark.parametrize("status", ["closed", "assigned", "unknown", None])
def test_missing_or_nonopen_native_state_is_not_assumed_open(case, status):
    case.legacy_status = status
    with pytest.raises(DomainError) as raised:
        evaluate(case)
    assert raised.value.reason == "VERSION_CONFLICT"


@pytest.mark.parametrize("change", ["missing", "different_id", "stale_revision", "unexpected"])
def test_stale_or_unexpected_current_cannot_close(case, change):
    previous = Row(id=uuid4(), revision=2, state="open")
    current = {"id": previous.id, "revision": previous.revision}
    if change == "missing":
        current = None
    elif change == "different_id":
        current["id"] = uuid4()
    elif change == "stale_revision":
        current["revision"] = 1
    else:
        previous = None
    with pytest.raises(DomainError) as raised:
        evaluate(case, previous=previous, current=current)
    assert raised.value.reason == "VERSION_CONFLICT"


@pytest.mark.parametrize(
    "state,action", [("closed", "close"), ("open", "reopen"), ("unknown", "close")]
)
def test_followup_transition_cannot_infer_missing_state_or_repeat_terminal_action(
    case, state, action
):
    previous = Row(id=uuid4(), revision=1, state=state)
    with pytest.raises(DomainError) as raised:
        evaluate(case, previous=previous, current={"id": previous.id, "revision": 1}, action=action)
    assert raised.value.reason == "VERSION_CONFLICT"


def test_initial_risk_is_open_not_implicitly_closed(case):
    with pytest.raises(DomainError):
        evaluate(case, action="reopen")


@pytest.mark.parametrize(
    "change",
    [
        {"sources": []},
        {"summary": "   "},
        {"action": "accept_risk"},
        {"state": "closed"},
        {"owner_id": str(uuid4())},
        {"professional_approval": True},
    ],
)
def test_sources_and_closed_payload_prevent_claimed_authority_or_empty_followup(case, change):
    with pytest.raises(ValidationError):
        RiskFollowupPayload.model_validate({**case.data, **change})
