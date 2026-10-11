"""No DB fixture: event clocks and purpose qualification never imply quality acceptance."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.sample_handoff.rules import (
    availability,
    require_manufacturing,
    validate_event,
    validate_time,
)
from pdos_next.domain.sample_handoff.schemas import SampleReadinessPayload
from pdos_next.domain.sample_handoff.service import semantic
from pdos_next.errors import DomainError

AT = datetime(2026, 10, 2, 16, 0, tzinfo=UTC)


def payload(**changes):
    sample, lot, actual, build, source = (uuid4() for _ in range(5))
    event = {
        "sample_id": str(sample),
        "lot_id": str(lot),
        "actual_configuration_id": str(actual),
        "build_id": str(build),
        "state": "ready",
        "purpose": "Internal verification",
        "occurred_at": AT.isoformat(),
    }
    line = json.dumps(event, ensure_ascii=False)
    reference = {
        "artifact_id": str(source),
        "expected_revision": 1,
        "line": 1,
        "quote": line,
    }
    raw = {
        "sample_id": str(sample),
        "expected_sample_revision": 1,
        "state": "ready",
        "purpose": event["purpose"],
        "occurred_at": AT.isoformat(),
        "occurred_timezone": "America/Los_Angeles",
        "event_source": reference,
        "sources": [reference],
        "reason": "Recorded physical event",
        **changes,
    }
    return raw, event, (lot, actual, build)


def assert_event(raw, line, identities):
    value = SampleReadinessPayload.model_validate(raw)
    validate_event(
        value,
        lot_id=identities[0],
        actual_configuration_id=identities[1],
        build_id=identities[2],
        line=line,
    )


def test_exact_whole_event_in_offset_normalizes_same_utc_instant():
    raw, event, identities = payload()
    event["occurred_at"] = "2026-10-02T09:00:00-07:00"
    line = json.dumps(event)
    raw["event_source"]["quote"] = line
    assert_event(raw, line, identities)
    value = SampleReadinessPayload.model_validate(raw)
    assert value.occurred_at == AT
    assert value.occurred_timezone == "America/Los_Angeles"


@pytest.mark.parametrize(
    "field",
    ["sample_id", "lot_id", "actual_configuration_id", "build_id", "state", "purpose"],
)
def test_event_identity_cannot_be_an_unrelated_source_line(field):
    raw, event, identities = payload()
    event[field] = (
        "hold" if field == "state" else "Other purpose" if field == "purpose" else str(uuid4())
    )
    line = json.dumps(event)
    raw["event_source"]["quote"] = line
    with pytest.raises(DomainError, match="原文须") as error:
        assert_event(raw, line, identities)
    assert error.value.reason == "SAMPLE_EVENT_MISMATCH"


@pytest.mark.parametrize(
    "kind", ["duplicate", "extra", "missing", "naive", "time_drift", "partial", "array"]
)
def test_closed_full_line_event_rejects_ambiguity(kind):
    raw, event, identities = payload()
    if kind == "duplicate":
        line = json.dumps(event)[:-1] + ', "state": "ready"}'
    elif kind == "extra":
        line = json.dumps({**event, "approved": True})
    elif kind == "missing":
        event.pop("build_id")
        line = json.dumps(event)
    elif kind == "naive":
        line = json.dumps({**event, "occurred_at": "2026-10-02T16:00:00"})
    elif kind == "time_drift":
        line = json.dumps({**event, "occurred_at": (AT + timedelta(seconds=1)).isoformat()})
    elif kind == "array":
        line = json.dumps([event])
    else:
        line = json.dumps(event)
    raw["event_source"]["quote"] = line if kind != "partial" else '"ready"'
    with pytest.raises(DomainError) as error:
        assert_event(raw, line, identities)
    assert error.value.reason == "SAMPLE_EVENT_MISMATCH"


@pytest.mark.parametrize(
    "parameters,code",
    [
        ({"at": AT - timedelta(seconds=1)}, "SAMPLE_EVENT_IN_FUTURE"),
        ({"actual_at": AT + timedelta(seconds=1)}, "SAMPLE_EVENT_BEFORE_OUTPUT"),
        ({"lot_at": AT + timedelta(seconds=1)}, "SAMPLE_EVENT_BEFORE_OUTPUT"),
        ({"start_at": AT + timedelta(seconds=1)}, "SAMPLE_EVENT_BEFORE_START"),
        ({"previous_at": AT}, "SAMPLE_EVENT_NOT_NEWER"),
        ({"previous_at": AT + timedelta(seconds=1)}, "SAMPLE_EVENT_NOT_NEWER"),
    ],
)
def test_event_clock_boundaries(parameters, code):
    inputs = {"at": AT, "actual_at": AT, "lot_at": AT, "start_at": AT, **parameters}
    with pytest.raises(DomainError) as error:
        validate_time(AT, **inputs)
    assert error.value.reason == code


def test_exact_ready_clock_allows_same_output_start_instant_and_newer_transition():
    validate_time(
        AT, at=AT, actual_at=AT, lot_at=AT, start_at=AT, previous_at=AT - timedelta(microseconds=1)
    )


def test_hold_does_not_require_a_start_but_still_requires_real_output_and_now():
    validate_time(AT, at=AT, actual_at=AT, lot_at=AT)
    assert availability("hold", "Purpose A", "Purpose B", current=True) == "hold"
    assert availability("hold", "Purpose A", "Purpose B", current=False) == "unknown"


def test_ready_is_not_global_and_lost_source_or_authority_returns_unknown():
    assert availability("ready", "Purpose A", "Purpose A", current=True) == "ready"
    assert availability("ready", "Purpose A", "Purpose B", current=True) == "unknown"
    assert availability("ready", "Purpose A", "Purpose A", current=False) == "unknown"


@pytest.mark.parametrize(
    "changes",
    [
        {"authorized": False},
        {"qualified": None},
        {"qualified": False},
        {"qualified": 1},
        {"roles": ["quality"]},
    ],
)
def test_product_write_or_other_professional_role_does_not_grant_manufacturing(changes):
    value = {"authorized": True, "qualified": True, "roles": ["manufacturing"], **changes}
    with pytest.raises(DomainError) as error:
        require_manufacturing(value)
    assert error.value.reason == "MANUFACTURING_AUTHORITY_REQUIRED"
    assert error.value.status == 403


def test_current_named_manufacturing_authority_is_required():
    require_manufacturing({"authorized": True, "qualified": True, "roles": ["manufacturing"]})


@pytest.mark.parametrize(
    "changes",
    [
        {"expected_sample_revision": True},
        {"expected_previous_revision": True},
        {"previous_readiness_id": str(uuid4())},
        {"expected_previous_revision": 1},
        {"received_at": AT.isoformat()},
        {"availability": "ready"},
        {"occurred_at": "2026-10-02T16:00:00"},
        {"occurred_timezone": "Unknown/Calendar"},
        {"purpose": " Internal verification "},
    ],
)
def test_server_facts_and_invalid_versions_times_are_not_client_policy(changes):
    raw, _, _ = payload(**changes)
    with pytest.raises(ValidationError):
        SampleReadinessPayload.model_validate(raw)


def test_semantic_source_order_and_confirmation_replay_share_one_intent():
    raw, _, _ = payload()
    second = deepcopy(raw["sources"][0])
    second.update(artifact_id=str(uuid4()), quote="Independent current manufacturing basis")
    raw["sources"].append(second)
    first = SampleReadinessPayload.model_validate(raw)
    raw["sources"].reverse()
    raw["confirmation_token"] = "this-is-a-different-confirmation-token"
    assert semantic(first) == semantic(SampleReadinessPayload.model_validate(raw))


def test_duplicate_source_references_rejected_instead_of_silently_losing_input():
    raw, _, _ = payload()
    raw["sources"] *= 2
    with pytest.raises(ValidationError):
        SampleReadinessPayload.model_validate(raw)


def test_preview_exposes_no_server_receive_clock_or_acceptance():
    from pdos_next.domain.sample_handoff.service import _view

    raw, _, _ = payload()
    value = SampleReadinessPayload.model_validate(raw)
    keys = {
        "id",
        "product_id",
        "project_id",
        "build_id",
        "build_revision",
        "sample_id",
        "sample_revision",
        "lot_id",
        "lot_revision",
        "actual_configuration_id",
        "actual_configuration_revision",
        "revision",
        "previous_readiness_id",
        "previous_revision",
        "owner_id",
        "visibility",
        "status",
        "purpose",
        "occurred_at",
        "occurred_timezone",
        "received_at",
        "nature",
        "event_source",
        "sources",
        "required_source_read_set",
        "fixed_snapshot",
        "authority_snapshot",
        "source_basis",
        "intent_digest",
        "reason",
    }
    row = SimpleNamespace(**{key: None for key in keys})
    row.status, row.purpose = value.state, value.purpose
    row.occurred_at, row.occurred_timezone = value.occurred_at, value.occurred_timezone
    row.created_at, row.snapshot_sha256 = None, None
    row.fixed_snapshot = {"sample": {"label": "Synthetic physical identity"}}
    result = _view(row, source_status="current", is_current=True)
    assert result["received_at"] is None
    assert result["created_at"] is None
    assert result["clocks"]["received_at"] is None
    assert result["reservation"] is result["consumption"] is None
    assert result["quality_accepted"] is False
