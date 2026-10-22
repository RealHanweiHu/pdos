"""Manual declarations and new-run limits; no database or service authority substitutes."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from pdos_next.domain.automations.rules import validate_admission
from pdos_next.domain.automations.schemas import (
    ACTIVATE,
    DRAFT_SAVE,
    MAX_INTEGER,
    PAUSE,
    PAYLOADS,
    AutomationSpec,
    Control,
    DraftSave,
    Trigger,
)
from pdos_next.errors import DomainError

AT = datetime(2026, 10, 18, 10, tzinfo=UTC)
VERSION = uuid4()
SPEC = {
    "name": "读取当前项目资料",
    "goal": "保留未知项并生成只读归纳",
    "purpose": "本人核对项目工作",
    "stop_condition": "完成本次归纳或当前授权失效",
    "trigger_kind": "manual",
    "skill_keys": [{"key": "gap_check", "version": "1", "digest": "a" * 64}],
    "validation_budget_id": str(uuid4()),
    "token_limit": 1000,
    "budget": {
        "limit_micro_usd": 0,
        "input_token_limit": 500,
        "output_token_limit": 500,
        "call_limit": 1,
    },
    "cooldown_seconds": 60,
    "max_runs": 2,
}


def spec(**values):
    return AutomationSpec.model_validate({**deepcopy(SPEC), **values})


def trigger(**values):
    return Trigger.model_validate(
        {"expected_rule_revision": 3, "version_id": VERSION, "idempotency_key": "manual-001"}
        | values
    )


def current(**values):
    return {
        "state": "active",
        "revision": 3,
        "published_version_id": VERSION,
        "admitted_count": 0,
        "last_admitted_at": None,
    } | values


def rejected(state, *, code, reason=None, **kwargs):
    with pytest.raises(DomainError) as error:
        validate_admission(state, kwargs.pop("trigger", trigger()), spec=spec(), at=AT, **kwargs)
    assert error.value.code == code
    if reason is not None:
        assert error.value.reason == reason
    return error.value


def test_closed_commands_keep_server_authority_and_trigger_fields_out_of_public_payloads():
    assert PAYLOADS == {DRAFT_SAVE: DraftSave, ACTIVATE: Control, PAUSE: Control}
    saved = DraftSave.model_validate({"expected_rule_revision": 0, "spec": SPEC})
    assert saved.rule_id is None and saved.restored_from is None
    assert saved.spec.product_id is None
    assert saved.spec.allow_network is False and saved.spec.cross_object_write is False
    assert saved.spec.mcp_tools == []
    for field in ("owner_id", "actor_id", "scope", "authorized", "qualified", "state"):
        with pytest.raises(ValidationError):
            DraftSave.model_validate({"expected_rule_revision": 0, "spec": SPEC, field: True})
    with pytest.raises(ValidationError):
        trigger(rule_id=str(uuid4()))
    control = Control(rule_id=uuid4(), expected_rule_revision=3, version_id=VERSION)
    assert control.confirmation_token is None
    with pytest.raises(ValidationError):
        Control.model_validate({**control.model_dump(), "spec": SPEC})


@pytest.mark.parametrize("kind", ["schedule", "domain_event", "relative_milestone"])
def test_unimplemented_trigger_cannot_be_published_as_manual(kind):
    with pytest.raises(ValidationError):
        spec(trigger_kind=kind)


@pytest.mark.parametrize(
    "change",
    [
        {"allow_network": True},
        {"allow_network": 0},
        {"allow_network": "false"},
        {"cross_object_write": True},
        {"cross_object_write": 0},
        {"mcp_tools": ["connector.read"]},
        {"allow_write": False},
    ],
)
def test_read_only_slice_does_not_accept_enabled_or_coerced_capabilities(change):
    with pytest.raises(ValidationError):
        spec(**change)


def test_skills_pin_one_version_per_key_without_claiming_catalog_or_qualification():
    ref = SPEC["skill_keys"][0]
    for refs in ([], [ref, {**ref, "version": "2"}], [{**ref, "digest": "A" * 64}]):
        with pytest.raises(ValidationError):
            spec(skill_keys=refs)
    declared = spec(skill_keys=[{**ref, "key": "not_registered"}])
    assert declared.skill_keys[0].key == "not_registered"
    # Existence, enabled status and qualification belong to the actual server catalog.
    with pytest.raises(ValidationError):
        spec(skill_keys=[{**ref, "qualified": True}])


@pytest.mark.parametrize(
    "change",
    [
        {"token_limit": True},
        {"token_limit": 0},
        {"max_runs": "2"},
        {"max_runs": MAX_INTEGER + 1},
        {"cooldown_seconds": -1},
        {"budget": {**SPEC["budget"], "call_limit": False}},
    ],
)
def test_resource_limits_reject_coercion_and_invalid_boundaries(change):
    with pytest.raises(ValidationError):
        spec(**change)


def test_stale_revision_or_different_published_version_precedes_state_and_rate_limits():
    stale = current(state="paused", revision=4, admitted_count=2, last_admitted_at=AT)
    rejected(stale, code="VERSION_CONFLICT")
    rejected(current(published_version_id=uuid4()), code="VERSION_CONFLICT")
    rejected(current(published_version_id=None, state="draft"), code="VERSION_CONFLICT")


@pytest.mark.parametrize("state", ["draft", "paused", "retired"])
def test_only_active_rule_can_admit_a_new_run(state):
    rejected(current(state=state), code="VALIDATION_FAILED", reason="INVALID_STATE")


def test_first_and_exact_cooldown_boundary_admit_without_mutating_owner_watermarks():
    initial = current()
    original = deepcopy(initial)
    assert validate_admission(initial, trigger(), spec=spec(), at=AT) is None
    assert initial == original
    cooling = current(admitted_count=1, last_admitted_at=AT - timedelta(seconds=60))
    assert validate_admission(cooling, trigger(), spec=spec(), at=AT) is None
    rejected(
        current(admitted_count=1, last_admitted_at=AT - timedelta(seconds=60, microseconds=-1)),
        code="RATE_LIMITED",
    )


def test_all_admitted_runs_count_even_with_no_success_and_no_cooldown():
    state = current(admitted_count=2, last_admitted_at=AT - timedelta(days=1))
    with pytest.raises(DomainError) as error:
        validate_admission(state, trigger(), spec=spec(cooldown_seconds=0), at=AT)
    assert error.value.code == "RATE_LIMITED" and error.value.status == 429
    assert state["admitted_count"] == 2


def test_cooldown_uses_real_utc_elapsed_time_across_a_daylight_saving_fold():
    zone = ZoneInfo("America/Los_Angeles")
    before_fold = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
    after_fold = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1)
    state = current(admitted_count=1, last_admitted_at=before_fold)
    assert (
        validate_admission(state, trigger(), spec=spec(cooldown_seconds=3600), at=after_fold)
        is None
    )
    with pytest.raises(DomainError) as error:
        validate_admission(state, trigger(), spec=spec(cooldown_seconds=3601), at=after_fold)
    assert error.value.code == "RATE_LIMITED"


def test_owner_watermarks_and_server_clock_cannot_default_missing_or_invalid_facts():
    for invalid in (
        {key: value for key, value in current().items() if key != "admitted_count"},
        current(admitted_count=True),
        current(admitted_count=1),
        current(last_admitted_at=AT),
    ):
        rejected(invalid, code="VALIDATION_FAILED", reason="INTEGRITY_MISMATCH")
    rejected(
        current(admitted_count=1, last_admitted_at=AT + timedelta(seconds=1)),
        code="VERSION_CONFLICT",
    )
    with pytest.raises(DomainError) as error:
        validate_admission(current(), trigger(), spec=spec(), at=AT.replace(tzinfo=None))
    assert error.value.code == "VALIDATION_FAILED"
