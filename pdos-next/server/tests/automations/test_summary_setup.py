"""Walletless declarations narrow the actual deterministic branch, never authority."""

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from pdos_next.agent_kernel import gateway
from pdos_next.domain.automations import runtime, service
from pdos_next.domain.automations.schemas import ZERO_MODEL_BUDGET, AutomationSpec
from pdos_next.errors import DomainError
from pdos_next.service import Context, digest
from pydantic import ValidationError
from sqlalchemy import Engine


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("summary setup pure checks cannot connect to a database")

    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(Engine, "raw_connection", forbidden)


def summary_spec(**changes):
    return {
        "name": "本人结构摘要",
        "goal": "Read owner facts",
        "purpose": "Personal summary",
        "stop_condition": "Return structured facts or visible unavailability",
        "trigger_kind": "schedule",
        "trigger_config": {
            "first_at": datetime(2030, 10, 21, 9, tzinfo=UTC).isoformat(),
            "original_timezone": "UTC",
            "calendar": "weekly_monday",
        },
        "personal_summary": {},
        "skill_keys": [],
        "validation_budget_id": None,
        "token_limit": 1,
        "budget": dict(ZERO_MODEL_BUDGET),
        "cooldown_seconds": 0,
        "max_runs": 52,
        **changes,
    }


def test_actual_summary_declaration_has_no_fabricated_skill_or_model_capacity():
    spec = AutomationSpec.model_validate(summary_spec())
    assert spec.walletless_summary and not spec.skill_keys
    assert spec.validation_budget_id is None and spec.budget.model_dump() == ZERO_MODEL_BUDGET
    saved = spec.model_dump(mode="json")
    assert "walletless_summary" not in saved and "mode" not in saved
    assert saved == AutomationSpec.model_validate(saved).model_dump(mode="json")


@pytest.mark.parametrize(
    "change",
    [
        {"personal_summary": None},
        {"personal_summary": {"owner_id": str(uuid4())}},
        {"skill_keys": [{"key": "public_research", "version": "1", "digest": "a" * 64}]},
        {"token_limit": 1000},
        {"budget": {**ZERO_MODEL_BUDGET, "call_limit": 1}},
        {"budget": {**ZERO_MODEL_BUDGET, "input_token_limit": 1}},
        {"budget": {**ZERO_MODEL_BUDGET, "output_token_limit": 1}},
        {"budget": {**ZERO_MODEL_BUDGET, "limit_micro_usd": 1}},
        {"trigger_kind": "manual", "trigger_config": None},
        {"allow_network": True},
        {"mcp_tools": ["arbitrary"]},
        {"max_runs": 0},
    ],
)
def test_summary_field_cannot_be_used_to_obtain_generic_capacity_or_skip_real_run_limits(change):
    with pytest.raises(ValidationError):
        AutomationSpec.model_validate(summary_spec(**change))


def test_original_model_and_legacy_summary_canonical_versions_keep_their_exact_digest():
    model = summary_spec(
        personal_summary=None,
        validation_budget_id=uuid4(),
        token_limit=1000,
        skill_keys=[{"key": "gap_check", "version": "v1", "digest": "b" * 64}],
        budget={
            "limit_micro_usd": 10,
            "input_token_limit": 100,
            "output_token_limit": 100,
            "call_limit": 2,
        },
    )
    for summary in (None, {}):
        original = AutomationSpec.model_validate({**model, "personal_summary": summary})
        saved = original.model_dump(mode="json")
        checked = AutomationSpec.model_validate(deepcopy(saved))
        assert checked.walletless_summary is False
        assert checked.model_dump(mode="json") == saved
        assert digest(checked.model_dump(mode="json")) == digest(saved)


def test_native_scope_and_actual_writer_are_still_checked_before_skipping_model_requirements(
    monkeypatch,
):
    from pdos_next.agent_kernel.bootstrap import Bootstrap
    from pdos_next.domain.automations import trigger_sources

    observed = []
    ctx = Context(uuid4(), uuid4(), uuid4(), category_id=uuid4())
    spec = AutomationSpec.model_validate(summary_spec())
    monkeypatch.setattr(service, "require_access", lambda *_a, **_k: observed.append("scope"))
    monkeypatch.setattr(
        trigger_sources, "condition_state", lambda *_a: observed.append("condition")
    )
    monkeypatch.setattr(Bootstrap, "binding_for", lambda *_a: observed.append("actual_writer"))

    def no_model_configuration(*_args):
        raise AssertionError("a model skill or wallet must not be manufactured for summary")

    monkeypatch.setattr(service, "SkillCatalog", no_model_configuration)
    service.spec_current(NS(bind=NS()), ctx, spec, enabled=True)
    assert observed == ["scope", "condition", "actual_writer"]


@pytest.mark.parametrize(
    "name",
    ["model", "assistant.search", "assistant.extract", "mcp.read", "business.anything", None],
)
def test_bound_summary_rejects_every_generic_dispatch_before_model_or_query_embedding(
    monkeypatch,
    name,
):
    spec = AutomationSpec.model_validate(summary_spec())
    monkeypatch.setattr(runtime, "scope_binding", lambda *_a: (NS(), spec))
    with pytest.raises(DomainError) as error:
        runtime.guard_tool(NS(), NS(), name)
    assert error.value.code == "FORBIDDEN_SCOPE"


@pytest.mark.parametrize("cost_lease", [None, (0, 0, 0, {})])
def test_generic_claim_cannot_mint_even_an_unmetered_call_for_a_summary(monkeypatch, cost_lease):
    spec = AutomationSpec.model_validate(summary_spec())
    monkeypatch.setattr(runtime, "binding", lambda *_a: (NS(), spec))
    with pytest.raises(DomainError) as error:
        runtime.reserve(NS(), NS(), reservation=0, cost_lease=cost_lease)
    assert error.value.code == "FORBIDDEN_SCOPE"


def test_model_gateway_rejects_registered_summary_before_route_secrets_or_provider(monkeypatch):
    spec = AutomationSpec.model_validate(summary_spec())
    monkeypatch.setattr(runtime, "scope_binding", lambda *_a: (NS(), spec))
    monkeypatch.setattr(gateway, "in_registered_agent_graph", lambda: True)

    def forbidden(*_a, **_k):
        raise AssertionError("summary must be refused before any generic model setup")

    client = gateway.AgentGateway(
        NS(current=forbidden), route_for=forbidden, client=NS(turn=forbidden)
    )
    with pytest.raises(DomainError) as error:
        client.turn(NS(), system="", messages=[], tools=[], output_schema={})
    assert error.value.code == "FORBIDDEN_SCOPE"
