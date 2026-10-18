"""Actual rule-budget SQL over synthetic ledger entries, without any provider call."""

from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.models import AgentRun, AgentToolCall, ValidationBudget
from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.agent_kernel.skills import SkillCatalog
from pdos_next.domain.automations.models import AutomationTriggerOccurrence
from pdos_next.domain.automations.schemas import ACTIVATE, DRAFT_SAVE
from pdos_next.errors import DomainError
from pdos_next.safety import verify_test_target
from tests.agent_kernel import test_budget_management as budgets
from tests.agent_kernel import test_skill_management as skills
from tests.automations_pg.test_manual_workflow import new_trigger, reading, save, snapshot, trigger


def test_actual_rule_budget_sums_settled_usage_and_other_run_reservation_once(setup):
    verify_test_target(setup.admin)
    verify_test_target(setup.engine)
    verify_test_target(setup.dispatch)
    skills.promote(setup)
    enabled = skills.post(setup, skills.preview(setup, skills.command(setup))["command"])
    assert enabled.status_code == 200, enabled.text
    _, wallet = budgets.allocate(setup)
    skill = SkillCatalog().configuration("public_research")
    spec = {
        "name": "Synthetic shared rule budget",
        "goal": "Verify local synthetic ledger admission without dispatching any model or tool",
        "purpose": "Actual rule-wide budget SQL and RLS verification",
        "stop_condition": "Finish the bounded synthetic accounting assertions",
        "trigger_kind": "manual",
        "product_id": str(setup.product),
        "skill_keys": [{"key": skill.key, "version": skill.version, "digest": skill.digest}],
        "validation_budget_id": wallet["subject_id"],
        "token_limit": 1000,
        "budget": {
            "limit_micro_usd": 10,
            "input_token_limit": 100,
            "output_token_limit": 100,
            # The third attempted call fits this count; only the cost cap rejects it.
            "call_limit": 3,
        },
        "cooldown_seconds": 0,
        "max_runs": 2,
        "allow_network": False,
        "mcp_tools": [],
        "cross_object_write": False,
    }
    _, draft = save(setup, DRAFT_SAVE, {"expected_rule_revision": 0, "spec": spec})
    rule_id = draft["result"]["rule_id"]
    current = reading(setup, rule_id)["rule"]
    save(
        setup,
        ACTIVATE,
        {
            "rule_id": rule_id,
            "expected_rule_revision": current["revision"],
            "version_id": current["draft"]["id"],
        },
    )
    current = reading(setup, rule_id)["rule"]
    admitted = [trigger(setup, rule_id, new_trigger(current)) for _ in range(2)]
    assert admitted[0]["run_id"] != admitted[1]["run_id"]
    store = KernelStore(setup.engine)
    first, second = (
        store.scope(
            tenant_id=setup.tenant,
            requester_id=setup.human,
            writer_id=setup.agent,
            category_id=setup.category,
            run_id=UUID(value["run_id"]),
        )
        for value in admitted
    )
    # These are host-created accounting fixtures, not model output or provider pricing.
    # The actual Run/call/wallet RLS and settlement triggers execute normally.
    pricing = {"source": "Synthetic accounting fixture only; no provider request dispatched"}
    payload = {"synthetic": True, "purpose": "rule-budget-ledger-only"}
    first_lease = (8, 5, 5, pricing)
    first_call, prior = store.claim(
        first,
        "synthetic-cost-first",
        "model",
        payload,
        reservation=10,
        cost_lease=first_lease,
    )
    assert prior is None
    with Session(setup.admin) as session:
        actual = session.get(ValidationBudget, UUID(wallet["subject_id"]))
        assert actual.calls == 1 and actual.held_micro_usd == 8 and actual.spent_micro_usd == 0
    result = {"synthetic": True, "completed": "accounting fixture; inference was never invoked"}
    store.settle(
        first,
        first_call,
        result=result,
        usage=3,
        cost_usage=SimpleNamespace(micro_usd=3, input_tokens=2, output_tokens=1),
    )
    with Session(setup.admin) as session:
        actual = session.get(ValidationBudget, UUID(wallet["subject_id"]))
        settled = session.get(AgentToolCall, first_call)
        assert actual.calls == 1 and actual.held_micro_usd == 0 and actual.spent_micro_usd == 3
        assert actual.used_input_tokens == 2 and actual.used_output_tokens == 1
        assert settled.state == "completed" and settled.cost_state == "actual"
        assert settled.cost_charged_micro_usd == 3
    second_call, prior = store.claim(
        second,
        "synthetic-cost-second",
        "model",
        payload,
        reservation=10,
        cost_lease=(7, 5, 5, pricing),
    )
    assert prior is None and second_call != first_call
    with Session(setup.admin) as session:
        actual = session.get(ValidationBudget, UUID(wallet["subject_id"]))
        assert actual.calls == 2
        assert actual.spent_micro_usd == 3 and actual.held_micro_usd == 7
        assert actual.used_input_tokens == 2 and actual.held_input_tokens == 5
        assert actual.used_output_tokens == 1 and actual.held_output_tokens == 5
        reserved = session.get(AgentToolCall, second_call)
        assert reserved.state == "started" and reserved.cost_state == "reserved"
        assert reserved.cost_reserved_micro_usd == 7
    before = snapshot(setup)
    with pytest.raises(DomainError) as denied:
        store.claim(
            second,
            "synthetic-cost-over-cap",
            "model",
            payload,
            reservation=2,
            cost_lease=(1, 1, 1, pricing),
        )
    assert denied.value.code == "RATE_LIMITED"
    assert snapshot(setup) == before
    replayed, restored = store.claim(
        first,
        "synthetic-cost-first",
        "model",
        payload,
        reservation=10,
        cost_lease=first_lease,
    )
    assert replayed == first_call and restored == result
    assert snapshot(setup) == before
    store.settle(
        second,
        second_call,
        result={"synthetic": True, "completed": "second accounting fixture; no provider call"},
        usage=10,
        cost_usage=SimpleNamespace(micro_usd=7, input_tokens=5, output_tokens=5),
    )
    assert reading(setup, rule_id)["rule"]["admitted_count"] == 2
    with Session(setup.admin) as session:
        actual = session.get(ValidationBudget, UUID(wallet["subject_id"]))
        assert actual.calls == 2 and actual.spent_micro_usd == 10 and actual.held_micro_usd == 0
        assert actual.used_input_tokens == 7 and actual.used_output_tokens == 6
        assert actual.held_input_tokens == actual.held_output_tokens == 0
        for model in (AgentRun, AgentToolCall, AutomationTriggerOccurrence):
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.tenant_id == setup.tenant)
                )
                == 2
            )
        calls = session.scalars(
            select(AgentToolCall).where(AgentToolCall.tenant_id == setup.tenant)
        ).all()
        assert all(call.state == "completed" and call.cost_state == "actual" for call in calls)
        assert all(call.execution_binding == {"kind": "unbound"} for call in calls)
        assert all(call.receipt_id is None and call.provider_request_id is None for call in calls)
