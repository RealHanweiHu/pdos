"""Current conditions compare exact original controls, not historical success."""

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection

from app.ai.issue_evaluation_publication import WriteEvaluationPublicationError
from app.ai.issue_event_proposal import OPERATION
from app.ai.write_policy import POLICY_VERSION
from app.domain import ai_issue_trial_current as current
from app.domain.product_workspace import digest
from tests.test_issue_evaluation_publication import fixture_document


@pytest.fixture
def setup_controls(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], dict[str, Any]]:
    binding = deepcopy(fixture_document()["evaluations"][0]["evaluation"]["binding"])
    runtime = {"compiled": {"reader": binding["adapter_version"]}}
    binding.update(
        release_bundle_version="sha256:" + digest(runtime), policy_version=POLICY_VERSION
    )
    principal, policy, scope = uuid4(), uuid4(), uuid4()
    cfg = {"minimum_confirmation_basis_points": 9000, "maximum_retraction_basis_points": 500}
    protocol = {
        "policy_id": str(policy),
        "scope_revision_id": str(scope),
        "principal_id": str(principal),
        "binding": binding,
        "configuration": cfg,
        "evaluation_publication": {"pin": "original"},
    }
    state: dict[str, Any] = {
        "policy": {
            "id": policy,
            "principal_id": principal,
            "mode": "tiered",
            "revision": binding["policy_revision"],
            "contract_version": POLICY_VERSION,
            "operation_settings": {OPERATION: {"mode": "confirm", **cfg}},
        },
        "scope": {"id": scope, "principal_id": principal, "enabled": True},
        "runtime": runtime,
        "publication": SimpleNamespace(
            model_dump=lambda **_: deepcopy(protocol["evaluation_publication"]),
            evaluation=SimpleNamespace(outcome="passed"),
        ),
    }
    monkeypatch.setattr(current, "policy", lambda *_: state["policy"])
    monkeypatch.setattr(current, "latest_scope", lambda *_: state["scope"])
    monkeypatch.setattr(current, "_principal", lambda *_: {})
    monkeypatch.setattr(current, "bundle", lambda *_: state["runtime"])
    monkeypatch.setattr(
        current, "configured_issue_evaluation", lambda *_, **__: state["publication"]
    )
    return protocol, state


def check(protocol: dict[str, Any]) -> tuple[set[str], bool]:
    reasons, changed = current.controls(
        cast(Connection, None), UUID(int=1), UUID(int=2), protocol, datetime.now(UTC)
    )
    return {r["code"] for r in reasons}, changed


def test_matching_current_conditions_are_not_a_qualification_grant(setup_controls: Any) -> None:
    protocol, _ = setup_controls
    assert check(protocol) == (set(), False)


@pytest.mark.parametrize("change", ["new_policy", "disabled", "threshold", "principal"])
def test_policy_changes_block_old_registration(setup_controls: Any, change: str) -> None:
    protocol, state = setup_controls
    if change == "new_policy":
        state["policy"]["id"] = uuid4()
    elif change == "disabled":
        state["policy"]["operation_settings"][OPERATION]["mode"] = "disabled"
    elif change == "threshold":
        state["policy"]["operation_settings"][OPERATION]["minimum_confirmation_basis_points"] = 9500
    else:
        state["policy"]["principal_id"] = uuid4()
    assert check(protocol) == ({"policy_changed"}, True)


@pytest.mark.parametrize("change", ["disabled", "new_scope", "principal"])
def test_scope_changes_cannot_restore_old_authority(setup_controls: Any, change: str) -> None:
    protocol, state = setup_controls
    if change == "disabled":
        state["scope"]["enabled"] = False
    elif change == "new_scope":
        state["scope"]["id"] = uuid4()
    else:
        state["scope"]["principal_id"] = uuid4()
    assert check(protocol) == ({"scope_changed"}, True)


def test_runtime_change_requires_new_evidence(setup_controls: Any) -> None:
    protocol, state = setup_controls
    state["runtime"]["compiled"]["reader"] += ".changed"
    assert check(protocol) == ({"runtime_changed"}, True)


def test_publication_missing_is_unknown_not_passed(setup_controls: Any) -> None:
    protocol, state = setup_controls
    state["publication"] = None
    assert check(protocol) == ({"publication_unavailable"}, False)


def test_replacing_publication_does_not_reuse_old_pass(setup_controls: Any) -> None:
    protocol, state = setup_controls
    state["publication"].model_dump = lambda **_: {"pin": "new"}
    assert check(protocol) == ({"publication_changed"}, True)


def test_invalid_publication_is_explicitly_unverifiable(
    setup_controls: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol, _ = setup_controls

    def invalid(*_: Any, **__: Any) -> None:
        raise WriteEvaluationPublicationError("publication_outside_validity_window")

    monkeypatch.setattr(current, "configured_issue_evaluation", invalid)
    assert check(protocol) == ({"publication_unverifiable"}, False)


@pytest.mark.parametrize(
    ("original", "fresh", "expected"),
    [
        ("meets_candidate_criteria", "meets_candidate_criteria", "current"),
        ("does_not_meet_criteria", "meets_candidate_criteria", "blocked"),
        ("insufficient_evidence", "meets_candidate_criteria", "unavailable"),
        ("meets_candidate_criteria", "does_not_meet_criteria", "blocked"),
        ("meets_candidate_criteria", "insufficient_evidence", "unavailable"),
    ],
)
def test_latest_original_and_fresh_both_required(original: str, fresh: str, expected: str) -> None:
    reasons: list[dict[str, str]] = []
    assert (
        current.current_state(
            {"status": original}, {"status": fresh, "reasons": []}, changed=False, reasons=reasons
        )
        == expected
    )
    assert bool(reasons) == (original != "meets_candidate_criteria")


def test_matching_numbers_do_not_override_changed_or_missing_controls() -> None:
    passed = {"status": "meets_candidate_criteria", "reasons": []}
    assert current.current_state(passed, passed, changed=True, reasons=[]) == "blocked"
    assert (
        current.current_state(
            passed,
            passed,
            changed=False,
            reasons=[{"code": "publication_unavailable", "message": "原件不可用"}],
        )
        == "unavailable"
    )
