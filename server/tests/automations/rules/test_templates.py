"""Minimal rule templates (D75) and the project-bound status-update cadence spec."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.agent.kernel.skills import SkillCatalog
from pdos_next.domain.automations.schemas import AutomationSpec
from pdos_next.domain.automations.templates import STATUS_UPDATE, TEMPLATES, catalog
from pdos_next.domain.automations.trigger_time import Schedule

PROJECT, PRODUCT = str(uuid4()), str(uuid4())


def skill(key):
    actual = SkillCatalog().configuration(key)
    return {"key": actual.key, "version": actual.version, "digest": actual.digest}


def spec(**changes):
    defaults = next(t for t in TEMPLATES if t["key"] == STATUS_UPDATE)["defaults"]
    value = {
        "name": defaults["name"],
        "goal": defaults["goal"],
        "purpose": defaults["purpose"],
        "stop_condition": defaults["stop_condition"],
        "trigger_kind": "schedule",
        "trigger_config": {
            "first_at": "2026-11-12T17:00:00+08:00",
            "original_timezone": "Asia/Shanghai",
            "interval_seconds": defaults["interval_seconds"],
            "expires_at": None,
            "project_id": PROJECT,
        },
        "product_id": PRODUCT,
        "skill_keys": [skill("work_management")],
        "validation_budget_id": str(uuid4()),
        "token_limit": 4000,
        "budget": {
            "limit_micro_usd": 100_000,
            "input_token_limit": 4000,
            "output_token_limit": 2000,
            "call_limit": 4,
        },
        "cooldown_seconds": defaults["cooldown_seconds"],
        "max_runs": 52,
        "template": STATUS_UPDATE,
    }
    value.update(changes)
    return value


def test_catalog_lists_three_d75_templates_and_the_two_followups():
    keys = [item["key"] for item in catalog()["templates"]]
    assert keys == [
        "followup_unanswered",
        "followup_not_progressed",
        "commitment_due",
        "external_wait_overdue",
        STATUS_UPDATE,
    ]
    for item in catalog()["templates"]:
        assert item["rule_owner"] == item["recipient"] == "project_owner"
        assert item["queue"] == "decide"
        assert item["basis_label"] == "按周一至周五估算，未扣节假日与停线"
        if item["key"] == STATUS_UPDATE:
            assert item["model_calls"] and item["instantiable"] and item["tier"] == "T1"
            assert item["operation"] == "work.status_update.create"
        else:
            assert not item["model_calls"] and item["always_on"] and not item["instantiable"]


def test_status_update_cadence_is_a_project_schedule_with_the_work_skill():
    parsed = AutomationSpec.model_validate(spec())
    assert parsed.template == STATUS_UPDATE
    assert parsed.trigger_config["project_id"] == PROJECT
    assert parsed.model_dump(mode="json")["template"] == STATUS_UPDATE


@pytest.mark.parametrize(
    "changes",
    [
        {"trigger_kind": "manual", "trigger_config": None},
        {"skill_keys": [skill("public_research")]},
        {"product_id": None},
    ],
)
def test_status_update_template_shape_is_fixed(changes):
    with pytest.raises(ValidationError):
        AutomationSpec.model_validate(spec(**changes))


def test_status_update_template_needs_its_project():
    config = dict(spec()["trigger_config"])
    config.pop("project_id")
    with pytest.raises(ValidationError):
        AutomationSpec.model_validate(spec(trigger_config=config))


def test_only_the_cadence_binds_a_schedule_to_a_project():
    with pytest.raises(ValidationError):
        AutomationSpec.model_validate(spec(template=None))


def test_existing_schedule_and_spec_digests_are_unchanged_without_the_new_fields():
    first = datetime(2026, 11, 12, 9, tzinfo=UTC)
    plain = Schedule(first_at=first, original_timezone="UTC", interval_seconds=60)
    assert "project_id" not in plain.model_dump(mode="json")
    config = {"first_at": first.isoformat(), "original_timezone": "UTC", "interval_seconds": 60}
    plain_spec = spec(template=None, trigger_config=config, skill_keys=[skill("public_research")])
    dumped = AutomationSpec.model_validate(plain_spec).model_dump(mode="json")
    assert "template" not in dumped and "project_id" not in dumped["trigger_config"]


def _guard(monkeypatch, parsed, **call):
    from types import SimpleNamespace

    from pdos_next.domain.automations import runtime

    monkeypatch.setattr(runtime, "scope_binding", lambda store, scope: (None, parsed))
    scope = SimpleNamespace(project_id=call.pop("project_id", PROJECT))
    return runtime.guard_tool(None, scope, call.pop("name", None), **call)


def test_cadence_run_may_only_prepare_the_status_update_candidate(monkeypatch):
    from pdos_next.errors import DomainError

    cadence = AutomationSpec.model_validate(spec())
    allowed = {"name": "work.status_update.create", "writing": True, "preparing": True}
    assert _guard(monkeypatch, cadence, **allowed) is None
    refused = [
        {**allowed, "name": "work.task.create"},
        {**allowed, "preparing": False},  # T0 write path stays closed
        {"name": "work.status_update.create", "writing": True},
        {**allowed, "project_id": str(uuid4())},  # another project
        {**allowed, "project_id": None},
    ]
    for call in refused:
        with pytest.raises(DomainError) as error:
            _guard(monkeypatch, cadence, **call)
        assert error.value.code == "FORBIDDEN_SCOPE"
    config = {"first_at": "2026-11-12T09:00:00+00:00", "original_timezone": "UTC"}
    other = AutomationSpec.model_validate(spec(template=None, trigger_config=config))
    with pytest.raises(DomainError):
        _guard(monkeypatch, other, **allowed)
