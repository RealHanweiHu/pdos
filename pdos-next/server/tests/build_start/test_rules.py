"""No DB fixtures: execution boundaries and current-proof guards."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

import pdos_next.models  # noqa: F401 - initialize shared metadata first
from pdos_next.domain.build_start import service
from pdos_next.domain.build_start.rules import (
    CONTROLS,
    PROFESSIONAL_RULES,
    readiness_result,
    require_candidate,
    validate_professional_review,
    validate_scope,
    validate_start_event,
    validate_start_time,
)
from pdos_next.domain.build_start.schemas import (
    BuildAssessmentPayload,
    BuildAuthorizationPayload,
    BuildExecutionScope,
)
from pdos_next.errors import DomainError

AT = datetime(2026, 10, 2, 15, tzinfo=UTC)
PID, BID, ENG, MFG, SOURCE = [uuid4() for _ in range(5)]


def scope():
    return BuildExecutionScope(
        purpose="内部原型验证制造",
        quantity="10",
        unit="ea",
        site="实验线A",
        window_start=AT - timedelta(hours=1),
        window_end=AT + timedelta(hours=1),
        window_timezone="America/Los_Angeles",
    )


def evidence():
    return {
        "artifact_id": str(SOURCE),
        "expected_revision": 1,
        "line": 1,
        "quote": "Synthetic professional source",
    }


def approval(role="engineering", **changes):
    value = {
        "assessment_id": str(uuid4()),
        "expected_assessment_revision": 1,
        "expected_assessment_sha256": "a" * 64,
        "action": "approve",
        "valid_until": AT + timedelta(hours=2),
        "sources": [evidence()],
        "reason": "具名适用性核对",
        "accepted_controls": sorted(CONTROLS),
        "professional_assessments": [
            {
                "rule_id": key,
                "status": "applicable",
                "sources": [evidence()],
                "valid_until": AT + timedelta(hours=2),
                "reason": "固定范围适用",
            }
            for key in PROFESSIONAL_RULES[role]
        ],
    }
    value.update(changes)
    return BuildAuthorizationPayload.model_validate(value)


def event(**changes):
    value = {
        "build_id": str(BID),
        "occurred_at": AT.isoformat(),
        "purpose": scope().purpose,
        "engineering_configuration_id": str(ENG),
        "manufacturing_configuration_id": str(MFG),
    }
    value.update(changes)
    return json.dumps(value, ensure_ascii=False)


def check_event(quote):
    validate_start_event(
        quote, build_id=BID, scope=scope(), engineering_id=ENG, manufacturing_id=MFG, occurred_at=AT
    )


def operational(state="READY"):
    return {
        "state": state,
        "facts_revision": "b" * 64,
        "fact_refs": [],
        "valid_until": (AT + timedelta(hours=4)).isoformat(),
        "nature": "synthetic",
        "checks": [
            {
                "dimension": "materials",
                "code": "COVERAGE",
                "status": state,
                "detail": "固定纯核结果",
            }
        ],
    }


def test_three_professional_dimensions_pending_never_implicitly_ready():
    result = readiness_result(operational(), build_type="prototype", purpose=scope().purpose)
    assert (
        result["state"] == "UNKNOWN"
        and result["operational_state"] == "READY"
        and result["candidate_ready"] is True
    )
    assert {item["dimension"] for item in result["checks"]} >= {
        "product_verification",
        "manufacturing_applicability",
        "delivery_applicability",
    }
    pending = [
        item
        for item in result["checks"]
        if item["code"] in {key for rules in PROFESSIONAL_RULES.values() for key in rules}
    ]
    assert len(pending) == 4 and all(item["status"] == "UNKNOWN" for item in pending)
    assert all(
        item["waivable"] is False and item["allowed_purpose"] == scope().purpose
        for item in result["checks"]
    )


@pytest.mark.parametrize("state", ["UNKNOWN", "BLOCKED", "READY_WITH_CONDITIONS"])
def test_operational_unknown_conditions_or_blocked_cannot_enter_bypass(state):
    with pytest.raises(DomainError) as denied:
        require_candidate(
            readiness_result(operational(state), build_type="prototype", purpose=scope().purpose)
        )
    assert denied.value.reason == "BUILD_NOT_REVIEWABLE"


def test_pilot_manufacturing_baseline_missing_is_hard_unknown():
    result = readiness_result(operational(), build_type="pilot", purpose=scope().purpose)
    assert result["candidate_ready"] is False and result["state"] == "UNKNOWN"
    assert any(
        item["code"] == "PILOT_MANUFACTURING_BASELINE_UNCONNECTED" and item["waivable"] is False
        for item in result["checks"]
    )


@pytest.mark.parametrize("role", ["engineering", "manufacturing"])
def test_exact_professional_pair_and_all_controls_can_be_reviewed(role):
    validate_professional_review(approval(role), role, scope(), AT)


@pytest.mark.parametrize("role", ["engineering", "manufacturing"])
def test_ordinary_named_applicability_has_no_forced_expiry(role):
    raw = approval(role).model_dump(mode="json")
    raw.pop("valid_until")
    for review in raw["professional_assessments"]:
        review.pop("valid_until")
    value = BuildAuthorizationPayload.model_validate(raw)
    validate_professional_review(value, role, scope(), AT)
    assert value.valid_until is None


@pytest.mark.parametrize(
    "change,code",
    [
        ({"accepted_controls": sorted(CONTROLS)[:-1]}, "EXECUTION_CONTROLS_REQUIRED"),
        ({"professional_assessments": []}, "PROFESSIONAL_REVIEW_INCOMPLETE"),
    ],
)
def test_partial_controls_or_missing_professional_pair_rejected(change, code):
    with pytest.raises(DomainError) as denied:
        validate_professional_review(approval(**change), "engineering", scope(), AT)
    assert denied.value.reason == code


@pytest.mark.parametrize(
    "change,code",
    [
        ({"status": "unknown"}, "PROFESSIONAL_REVIEW_NOT_APPLICABLE"),
        ({"status": "blocked"}, "PROFESSIONAL_REVIEW_NOT_APPLICABLE"),
        ({"sources": []}, "PROFESSIONAL_REVIEW_NOT_APPLICABLE"),
        ({"valid_until": AT.isoformat()}, "PROFESSIONAL_REVIEW_EXPIRED"),
    ],
)
def test_professional_unknown_no_source_and_expired_do_not_pass(change, code):
    raw = approval().model_dump(mode="json")
    raw["professional_assessments"][0].update(change)
    with pytest.raises(DomainError) as denied:
        validate_professional_review(
            BuildAuthorizationPayload.model_validate(raw), "engineering", scope(), AT
        )
    assert denied.value.reason == code


@pytest.mark.parametrize("value", [True, 10.0, "0", "-1", "NaN"])
def test_quantity_rejects_boolean_binary_float_and_nonpositive(value):
    raw = scope().model_dump(mode="json")
    raw["quantity"] = value
    with pytest.raises(ValidationError):
        BuildExecutionScope.model_validate(raw)


def test_quantity_cannot_shrink_fixed_authoritative_demand():
    validate_scope(SimpleNamespace(planned_quantity="10", unit="ea"), scope())
    for build in (
        SimpleNamespace(planned_quantity="5", unit="ea"),
        SimpleNamespace(planned_quantity="10", unit="piece"),
    ):
        with pytest.raises(DomainError):
            validate_scope(build, scope())


@pytest.mark.parametrize(
    "change",
    [
        {"window_start": "2026-10-02T12:00:00"},
        {"window_timezone": "madeup/timezone"},
        {"window_end": AT - timedelta(hours=1)},
    ],
)
def test_naive_invalid_timezone_and_empty_window_rejected(change):
    raw = scope().model_dump(mode="json")
    raw.update(change)
    with pytest.raises(ValidationError):
        BuildExecutionScope.model_validate(raw)


@pytest.mark.parametrize(
    "change",
    [
        {"expected_previous_revision": 1},
        {"previous_assessment_id": str(uuid4())},
        {"expected_build_revision": True},
        {"expected_previous_revision": 1.0},
    ],
)
def test_assessment_cas_pair_is_strict(change):
    with pytest.raises(ValidationError):
        BuildAssessmentPayload.model_validate(
            {
                "build_id": BID,
                "expected_build_revision": 1,
                "execution_scope": scope(),
                "reason": "固定执行评估",
                **change,
            }
        )


def test_event_allows_actual_equivalent_offset_not_recording_time():
    check_event(
        event(occurred_at=(AT - timedelta(hours=7)).replace(tzinfo=None).isoformat() + "-07:00")
    )


@pytest.mark.parametrize(
    "change",
    [
        {"build_id": str(uuid4())},
        {"purpose": "另一个用途"},
        {"engineering_configuration_id": str(uuid4())},
        {"manufacturing_configuration_id": str(uuid4())},
        {"occurred_at": (AT + timedelta(seconds=1)).isoformat()},
        {"occurred_at": AT.replace(tzinfo=None).isoformat()},
        {"approved": True},
    ],
)
def test_event_binds_exact_actual_and_fixed_build(change):
    with pytest.raises(DomainError) as denied:
        check_event(event(**change))
    assert denied.value.reason == "START_EVENT_MISMATCH"


def test_duplicate_json_field_cannot_override_event():
    with pytest.raises(DomainError):
        check_event(event()[:-1] + ',"build_id":"' + str(BID) + '"}')


@pytest.mark.parametrize(
    "instant,created,code",
    [
        (AT + timedelta(seconds=1), AT - timedelta(minutes=1), "FUTURE_ACTUAL"),
        (AT - timedelta(hours=2), AT - timedelta(hours=3), "START_OUTSIDE_WINDOW"),
        (AT, AT + timedelta(seconds=1), "START_PRECEDES_AUTHORIZATION"),
    ],
)
def test_clock_future_outside_scope_and_before_signoff_rejected(instant, created, code):
    with pytest.raises(DomainError) as denied:
        validate_start_time(
            scope(),
            instant,
            AT,
            [
                SimpleNamespace(created_at=created),
                SimpleNamespace(created_at=AT - timedelta(hours=3)),
            ],
        )
    assert denied.value.reason == code


def test_end_exclusive_and_equal_approval_time():
    validate_start_time(scope(), AT, AT, [SimpleNamespace(created_at=AT)] * 2)
    with pytest.raises(DomainError):
        validate_start_time(
            scope(), scope().window_end, scope().window_end, [SimpleNamespace(created_at=AT)] * 2
        )


def test_late_recording_does_not_create_past_reservations_from_current_facts():
    with pytest.raises(DomainError) as denied:
        validate_start_time(scope(), AT, scope().window_end, [SimpleNamespace(created_at=AT)] * 2)
    assert denied.value.reason == "CURRENT_EXECUTION_WINDOW_REQUIRED"


@pytest.mark.parametrize(
    "change",
    [
        {"facts_revision": "c" * 64},
        {"actual_configuration_binding": [{"id": str(uuid4()), "deviation": True}]},
    ],
)
def test_epoch_aba_or_actual_configuration_drift_blocks_old_assessment(change):
    result = {**operational(), "actual_configuration_binding": []}
    assessment = SimpleNamespace(result=deepcopy(result))
    service._match_bundle(assessment, result, AT)
    with pytest.raises(DomainError) as denied:
        service._match_bundle(assessment, {**result, **change}, AT)
    assert denied.value.reason == "OPERATIONAL_FACTS_CHANGED"


@pytest.mark.parametrize(
    "qualified,roles",
    [(None, ["manufacturing"]), (False, ["manufacturing"]), (True, ["engineering"])],
)
def test_product_write_or_wrong_role_without_qualification_never_authorizes(qualified, roles):
    with pytest.raises(DomainError) as denied:
        service._require_authority(
            {"authorized": True, "roles": roles, "qualified": qualified}, "manufacturing"
        )
    assert denied.value.reason == "PROFESSIONAL_AUTHORITY_REQUIRED"


def test_historical_signature_is_checked_under_actual_reader_context(monkeypatch):
    import pdos_next.domain.professional_authority.service as authority

    calls = []

    def recheck(*args, retained=False):
        assert retained is False
        calls.append(args)
        return {"current": False}

    monkeypatch.setattr(authority, "recheck_snapshot", recheck)
    person = uuid4()
    ctx = SimpleNamespace(tenant_id=uuid4(), actor_id=uuid4(), requester_id=uuid4())
    with pytest.raises(DomainError) as denied:
        service._recheck_authority(None, ctx, PID, uuid4(), {"subject_id": str(person)}, AT)
    assert denied.value.reason == "PROFESSIONAL_AUTHORITY_CHANGED"
    assert calls[0][1] is ctx


def test_semantic_tokens_and_order_do_not_duplicate_business_intent():
    first = approval(approval_token="x" * 30)
    second = first.model_copy(
        update={
            "approval_token": "y" * 30,
            "professional_assessments": tuple(reversed(first.professional_assessments)),
            "accepted_controls": tuple(reversed(first.accepted_controls)),
        }
    )
    assert service.semantic(first) == service.semantic(second)


def test_old_assessment_cas_cannot_move_new_pointer(monkeypatch):
    monkeypatch.setattr(
        service,
        "_current_assessment",
        lambda *a, **kw: (object(), SimpleNamespace(id=uuid4(), revision=2)),
    )
    with pytest.raises(DomainError) as denied:
        service._assessment_cas(
            None,
            None,
            PID,
            SimpleNamespace(id=BID),
            SimpleNamespace(previous_assessment_id=uuid4(), expected_previous_revision=1),
        )
    assert denied.value.reason == "ASSESSMENT_VERSION_CONFLICT"


def test_revoke_cannot_target_different_current_assessment(monkeypatch):
    identity = uuid4()
    monkeypatch.setattr(
        service,
        "_current_decision",
        lambda *a, **kw: (
            object(),
            SimpleNamespace(id=identity, revision=1, assessment_id=uuid4()),
        ),
    )
    payload = SimpleNamespace(
        previous_decision_id=identity,
        expected_previous_revision=1,
        action="revoke",
        assessment_id=uuid4(),
    )
    with pytest.raises(DomainError) as denied:
        service._decision_cas(None, None, PID, SimpleNamespace(id=BID), "engineering", payload)
    assert denied.value.reason == "AUTHORIZATION_SCOPE_MISMATCH"
