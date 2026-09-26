from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.contracts.runtime_adoption import (
    TRIGGER_POLICIES,
    ActivationRequirement,
    ComponentSource,
    TriggerPolicy,
)
from app.domain.findings import FindingService
from app.events.catalog import EVENT_REGISTRY
from scripts.runtime_adoption_inventory import component, events, inventory


@pytest.mark.parametrize("origin", ["user", "control"])
def test_explicit_user_and_revocation_never_wait_for_event_debounce(origin: str) -> None:
    with pytest.raises(ValidationError, match="user_and_control_are_immediate"):
        TriggerPolicy.model_validate(
            {
                "key": "test",
                "origin": origin,
                "priority": "control",
                "coalesce_seconds": 900,
                "outcome_deadline_seconds": None,
                "model_allowed": False,
            }
        )


def test_milestone_clock_includes_queue_and_merge_wait() -> None:
    milestone = next(policy for policy in TRIGGER_POLICIES if policy.key == "milestone")
    assert milestone.outcome_deadline_seconds == 180
    assert milestone.coalesce_seconds == 0
    with pytest.raises(ValidationError, match="trigger_wait_exhausts_outcome_deadline"):
        TriggerPolicy.model_validate({**milestone.model_dump(), "coalesce_seconds": 180})
    control = next(policy for policy in TRIGGER_POLICIES if policy.key == "control")
    with pytest.raises(ValidationError, match="control_cleanup_cannot_call_model"):
        TriggerPolicy.model_validate({**control.model_dump(), "model_allowed": True})


def test_component_evidence_verifies_real_symbol_and_does_not_accept_fake_path() -> None:
    evidence = component("readiness", "server/app/domain/gates.py", "GateService._readiness")
    assert evidence["status"] == "present" and evidence["line"] > 0
    with pytest.raises(ValueError, match="component symbol missing"):
        component("fake", "server/app/domain/gates.py", "GateService.no_such_handler")
    with pytest.raises(ValueError, match="repository Python or JSON"):
        component("outside", "../outside.py")
    with pytest.raises(ValidationError, match="planned_component_cannot_claim_file_evidence"):
        ComponentSource.model_validate(
            {
                k: v
                for k, v in {**evidence, "status": "planned"}.items()
                if k not in {"line", "evidence_level"}
            }
        )


def test_live_adoption_cannot_be_claimed_with_only_an_existing_provider_qualification() -> None:
    planned = {
        "key": "domain.handler",
        "status": "planned",
        "path": None,
        "symbol": None,
        "sha256": None,
        "version": None,
        "implementation_work": "N1-01",
    }
    doc = {
        "key": "domain",
        "component_sources": [planned],
        "required_scope_tests": ["current_acl"],
        "current_rollout": "disabled",
        "requested_rollout": "live",
        "qualification_evidence": "old-provider-passed",
        "regression_evidence": None,
        "adoption_approval": None,
    }
    with pytest.raises(ValidationError, match="live_adoption_requires_components"):
        ActivationRequirement.model_validate(doc)
    ActivationRequirement.model_validate({**doc, "requested_rollout": "disabled"})
    with pytest.raises(ValidationError):
        ActivationRequirement.model_validate({**doc, "qualification_scope": "provider_only"})


def test_every_current_event_has_explicit_adoption_policy_and_no_new_routes() -> None:
    rows = events()
    assert {row["event"] for row in rows} == set(EVENT_REGISTRY)
    assert len(rows) == len(EVENT_REGISTRY)
    assert (
        next(r for r in rows if r["event"] == "TEST_FAILED")["proposed_trigger_policy"]
        == "milestone"
    )
    assert (
        next(r for r in rows if r["event"] == "DEVELOPMENT_BOM_ITEM_ADDED")[
            "proposed_trigger_policy"
        ]
        == "frequent_edit"
    )
    assert (
        next(r for r in rows if r["event"] == "USER_DELEGATION_REVOKED")["proposed_trigger_policy"]
        == "control"
    )
    assert (
        next(r for r in rows if r["event"] == "AI_FINDING_CREATED")["proposed_trigger_policy"]
        == "no_model_route"
    )


def test_adoption_inventory_matches_real_adapters_and_all_existing_components() -> None:
    result = inventory()
    assert len(result["legacy_components"]) == 13
    assert len(result["target_components"]) == 27
    assert {row["payload"] for row in result["apply_adapters"]} == {
        model.__name__ for model in FindingService._APPLY_ADAPTERS
    }
    assert all(row["model_qualification"] is None for row in result["target_components"])
    for row in result["legacy_components"]:
        assert row["handler"]["status"] == row["prompt"]["status"] == "present"
        assert row["model_output"]["line"] > 0
    # Static source evidence is not accidentally transformed into live adoption.
    copy = deepcopy(result)
    assert all(
        row["candidate_activation"].startswith("disabled") for row in copy["target_components"]
    )
