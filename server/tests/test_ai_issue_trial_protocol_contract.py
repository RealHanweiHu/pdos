"""Pure Issue preregistration boundaries; no database, provider or qualification."""

import socket
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.contracts.ai_issue_evaluation import IssueEvaluationBinding
from app.contracts.ai_issue_trial_protocol import IssueTrialChoices, RegisterIssueTrial

START = datetime(2026, 9, 27, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Issue trial contract tests must not access DB or network")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def binding(**changes: Any) -> dict[str, Any]:
    return {
        "operation_key": "event.issue.create",
        "provider": "openai",
        "model": "synthetic-contract-model",
        "model_version": "synthetic-contract-v1",
        "release_bundle_version": "sha256:" + "a" * 64,
        "suite_version": "synthetic-gateway-v1",
        "suite_digest": "b" * 64,
        "adapter_version": "event-issue-reader-v1",
        "policy_version": "synthetic-policy-v1",
        "policy_revision": 1,
        **changes,
    }


def choices(**changes: Any) -> dict[str, Any]:
    return {
        "minimum_handled_runs": 1,
        "minimum_followup_seconds": 1,
        "sampling_basis_points": 1,
        "confirmation_basis": "ever_confirmed",
        "recovery_protocol_version": "synthetic-recovery-v1",
        "recovery_conditions": "模拟合同：原回执核对后恢复。",
        **changes,
    }


def request(**changes: Any) -> dict[str, Any]:
    return {
        "request_id": UUID(int=1),
        "preparation_digest": "c" * 64,
        "binding": binding(),
        "window_start": START,
        "window_end": START + timedelta(days=1),
        "evidence_kind": "synthetic",
        "configuration": choices(),
        "reason": "仅纯合同验证，不代表真实试运行。",
        **changes,
    }


@pytest.mark.parametrize(
    "duration", [timedelta(0), -timedelta(seconds=1), timedelta(days=366, microseconds=1)]
)
def test_window_rejects_empty_reverse_and_over_limit(duration: timedelta) -> None:
    with pytest.raises(ValidationError, match="366"):
        RegisterIssueTrial.model_validate(request(window_end=START + duration))


@pytest.mark.parametrize("duration", [timedelta(microseconds=1), timedelta(days=366)])
def test_window_accepts_positive_and_exact_maximum(duration: timedelta) -> None:
    registered = RegisterIssueTrial.model_validate(request(window_end=START + duration))
    assert registered.window_end - registered.window_start == duration


@pytest.mark.parametrize("field", ["window_start", "window_end"])
def test_both_window_bounds_require_timezone(field: str) -> None:
    value = request()
    value[field] = value[field].replace(tzinfo=None)
    with pytest.raises(ValidationError, match="timezone_aware"):
        RegisterIssueTrial.model_validate(value)


def test_offset_window_is_compared_by_instant_and_roundtrips() -> None:
    end = (START + timedelta(days=366)).astimezone(timezone(timedelta(hours=8)))
    registered = RegisterIssueTrial.model_validate(request(window_end=end))
    assert registered.window_end - registered.window_start == timedelta(days=366)
    assert RegisterIssueTrial.model_validate_json(registered.model_dump_json()) == registered
    same_instant = START.astimezone(timezone(timedelta(hours=-7)))
    with pytest.raises(ValidationError):
        RegisterIssueTrial.model_validate(request(window_end=same_instant))


@pytest.mark.parametrize(
    "field", ["minimum_handled_runs", "minimum_followup_seconds", "policy_revision"]
)
@pytest.mark.parametrize("value", [0, -1, True, 1.0, "1"])
def test_positive_counts_and_policy_revision_are_strict_integers(field: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        if field == "policy_revision":
            IssueEvaluationBinding.model_validate(binding(**{field: value}))
        else:
            IssueTrialChoices.model_validate(choices(**{field: value}))


@pytest.mark.parametrize("value", [1, 10000])
def test_sampling_accepts_inclusive_bounds(value: int) -> None:
    assert (
        IssueTrialChoices.model_validate(choices(sampling_basis_points=value)).sampling_basis_points
        == value
    )


@pytest.mark.parametrize("value", [0, -1, 10001, True, 1.0, "1"])
def test_sampling_rejects_outside_bounds_and_coercion(value: Any) -> None:
    with pytest.raises(ValidationError):
        IssueTrialChoices.model_validate(choices(sampling_basis_points=value))


@pytest.mark.parametrize(
    "target,field,value",
    [
        ("configuration", "minimum_confirmation_basis_points", 9000),
        ("configuration", "maximum_retraction_basis_points", 500),
        ("configuration", "fixed_at", START),
        ("configuration", "qualification_granted", True),
        ("request", "qualification_granted", True),
        ("request", "created_at", START),
        ("request", "as_of", START),
        ("request", "minimum_confirmation_basis_points", 9000),
        ("binding", "qualification_granted", True),
    ],
)
def test_client_cannot_supply_server_thresholds_qualification_or_capture_time(
    target: str, field: str, value: Any
) -> None:
    payload = request()
    if target == "request":
        payload[field] = value
    else:
        payload[target][field] = value
    with pytest.raises(ValidationError, match="extra_forbidden"):
        RegisterIssueTrial.model_validate(payload)


@pytest.mark.parametrize(
    "operation", ["meeting.minutes.draft", "event.issue.update", "", "EVENT.ISSUE.CREATE"]
)
def test_only_issue_create_operation_can_be_registered(operation: str) -> None:
    with pytest.raises(ValidationError, match="literal_error"):
        RegisterIssueTrial.model_validate(request(binding=binding(operation_key=operation)))


def test_issue_operation_default_does_not_add_qualification() -> None:
    value = binding()
    value.pop("operation_key")
    registered = RegisterIssueTrial.model_validate(request(binding=value))
    assert registered.binding.operation_key == "event.issue.create"
    assert registered.configuration.minimum_handled_runs == 1
    assert registered.configuration.minimum_followup_seconds == 1
    assert "qualification_granted" not in registered.model_dump()
