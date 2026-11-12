"""No-DB rules for D305 (P95 补充确认 2026-11-09 与 2026-11-10)."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.core.command_handlers import T1_OPERATIONS, handler
from pdos_next.core.contracts import PAYLOADS
from pdos_next.domain.builds.professional_authority.service import OPERATION_ROLES
from pdos_next.domain.manufacturing.tool_trials import service as trials
from pdos_next.domain.manufacturing.tool_trials.schemas import OPERATION, Payload
from pdos_next.domain.verification.preparation import service as preparation
from pdos_next.domain.verification.results.schemas import DispositionPayload
from pdos_next.domain.verification.results.service import semantic as result_semantic
from pdos_next.errors import DomainError


def payload(**changes):
    value = {
        "build": {"id": str(uuid4()), "revision": 1},
        "tooling_new": {"part": "P", "version": "A0", "supplier_ref": "S", "cavities": 2},
        "trial": {"round": "T0", "purpose": "Synthetic"},
        "verification": {
            "request_id": str(uuid4()),
            "preparation_id": str(uuid4()),
            "expected_preparation_revision": 1,
            "preparation_sha256": "a" * 64,
            "reason": "Synthetic",
        },
        "reason": "Synthetic",
    }
    value.update(changes)
    return value


def test_registered_as_t1_with_trial_duties():
    assert OPERATION in T1_OPERATIONS and PAYLOADS[OPERATION] is Payload
    assert handler(OPERATION) is trials
    assert OPERATION_ROLES[OPERATION] == frozenset({"engineering", "manufacturing"})
    # Standalone request creation keeps engineering or quality (P95, 2026-11-10).
    assert OPERATION_ROLES["verification.request.create"] == frozenset({"engineering", "quality"})


def test_trial_duty_entry_is_open_to_the_tool_trial_only():
    for caller in ("verification.request.create", "npi.fixture.accept", ""):
        with pytest.raises(DomainError) as failed:
            preparation.trial_request_review(None, None, None, None, None, caller=caller)
        assert failed.value.reason == "FORBIDDEN_OPERATION"
        with pytest.raises(DomainError):
            preparation.create_trial_request(None, None, None, None, None, caller=caller)
    assert preparation.TRIAL_OPERATION == OPERATION
    assert preparation.TRIAL_ROLES == OPERATION_ROLES[OPERATION]


def test_payload_takes_new_tooling_or_a_reference_never_both():
    Payload.model_validate(payload())
    with pytest.raises(ValidationError):
        Payload.model_validate(payload(tooling={"id": str(uuid4()), "revision": 1}))
    with pytest.raises(ValidationError):
        Payload.model_validate(payload(tooling_new=None))
    with pytest.raises(ValidationError):
        Payload.model_validate(
            payload(tooling_new=None, tooling={"id": str(uuid4()), "revision": 1, "changes": {}})
        )
    with pytest.raises(ValidationError):
        Payload.model_validate(
            payload(tooling_new={"part": "P", "version": "A", "supplier_ref": "S", "cavities": 0})
        )


def test_disposition_result_maps_to_tooling_acceptance():
    assert trials.tooling_status("accept") == "accepted"
    assert trials.tooling_status("reject") == "rejected"
    assert trials.tooling_status(None) == "unknown"


def test_disposition_outcome_is_optional_and_keeps_old_digests():
    base = {
        "request_id": str(uuid4()),
        "expected_request_revision": 3,
        "run_id": str(uuid4()),
        "expected_run_revision": 2,
        "projection_id": str(uuid4()),
        "expected_projection_revision": 1,
        "expected_basis_sha256": "b" * 64,
        "text": "Synthetic conclusion",
        "at": {
            "occurred_at": "2026-11-10T08:00:00+00:00",
            "original_timezone": "UTC",
            "source": {"id": str(uuid4()), "revision": 1, "position": "line:1"},
        },
        "sources": [
            {"artifact_id": str(uuid4()), "expected_revision": 1, "line": 1, "quote": "Synthetic"}
        ],
        "reason": "Synthetic",
    }
    without = DispositionPayload.model_validate(base)
    assert without.outcome is None and "outcome" not in result_semantic(without)
    accepted = DispositionPayload.model_validate({**base, "outcome": "accept"})
    assert result_semantic(accepted)["outcome"] == "accept"
    with pytest.raises(ValidationError):
        DispositionPayload.model_validate({**base, "outcome": "conditional"})
