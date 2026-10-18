"""Synthetic unknown-cost ledger keeps its estimate in the actual rule-wide SQL budget."""

from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.models import AgentRun, AgentToolCall, ValidationBudget
from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.agent_kernel.skills import SkillCatalog
from pdos_next.domain.automations.models import AutomationTriggerOccurrence
from pdos_next.domain.automations.schemas import ACTIVATE, DRAFT_SAVE, AutomationSpec
from pdos_next.errors import DomainError
from pdos_next.safety import verify_test_target
from tests.agent_kernel import test_budget_management as budgets
from tests.agent_kernel import test_skill_management as skills
from tests.automations_pg.test_manual_workflow import new_trigger, reading, save, snapshot, trigger


def test_actual_unknown_estimate_prevents_another_run_exceeding_shared_rule_budget(setup):
    verify_test_target(setup.admin)
    verify_test_target(setup.engine)
    verify_test_target(setup.dispatch)
    skills.promote(setup)
    enabled = skills.post(setup, skills.preview(setup, skills.command(setup))["command"])
    assert enabled.status_code == 200, enabled.text
    _, wallet = budgets.allocate(setup)
    skill = SkillCatalog().configuration("public_research")
    spec = AutomationSpec(
        name="Synthetic unknown fee retention",
        goal="Exercise local ledger accounting without inference or external tool invocation",
        purpose="Actual SQL and RLS unknown-cost budget verification",
        stop_condition="Keep the unknown estimate and stop the over-cap reservation",
        trigger_kind="manual",
        product_id=setup.product,
        skill_keys=[{"key": skill.key, "version": skill.version, "digest": skill.digest}],
        validation_budget_id=UUID(wallet["subject_id"]),
        token_limit=1000,
        budget={
            "limit_micro_usd": 10,
            "input_token_limit": 100,
            "output_token_limit": 100,
            "call_limit": 3,
        },
        cooldown_seconds=0,
        max_runs=2,
    ).model_dump(mode="json")
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
    accepted = [trigger(setup, rule_id, new_trigger(current)) for _ in range(2)]
    assert accepted[0]["run_id"] != accepted[1]["run_id"]
    store = KernelStore(setup.engine)
    first, second = (
        store.scope(
            tenant_id=setup.tenant,
            requester_id=setup.human,
            writer_id=setup.agent,
            category_id=setup.category,
            run_id=UUID(value["run_id"]),
        )
        for value in accepted
    )
    # No request is dispatched. Only the trusted host's synthetic ledger fixture
    # exercises the real reservation and unknown settlement functions.
    pricing = {"source": "Synthetic unknown fee fixture; no provider request dispatched"}
    payload = {"synthetic": True, "purpose": "retain-unknown-rule-cost"}
    call_id, prior = store.claim(
        first,
        "synthetic-unknown-cost",
        "model",
        payload,
        reservation=10,
        cost_lease=(8, 5, 5, pricing),
    )
    assert prior is None
    assert store.release_call(first, call_id, unknown=True, error="EXTERNAL_OUTCOME_UNKNOWN")
    with Session(setup.admin) as session:
        call = session.get(AgentToolCall, call_id)
        actual = session.get(ValidationBudget, UUID(wallet["subject_id"]))
        assert call.state == "unknown" and call.cost_state == "estimated_unknown"
        assert call.cost_reserved_micro_usd == 0 and call.cost_charged_micro_usd == 8
        assert call.actual_input_tokens == call.actual_output_tokens == 5
        assert call.provider_request_id is None and call.receipt_id is None
        assert call.execution_binding == {"kind": "unbound"}
        assert actual.calls == 1 and actual.spent_micro_usd == 8 and actual.held_micro_usd == 0
        assert actual.used_input_tokens == actual.used_output_tokens == 5
        assert actual.held_input_tokens == actual.held_output_tokens == 0
    before = snapshot(setup)
    with pytest.raises(DomainError) as denied:
        store.claim(
            second,
            "synthetic-after-unknown-over-cap",
            "model",
            payload,
            reservation=2,
            cost_lease=(3, 1, 1, pricing),
        )
    assert denied.value.code == "RATE_LIMITED"
    assert snapshot(setup) == before
    with Session(setup.admin) as session:
        for model, amount in (
            (AgentRun, 2),
            (AutomationTriggerOccurrence, 2),
            (AgentToolCall, 1),
        ):
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.tenant_id == setup.tenant)
                )
                == amount
            )
        call = session.get(AgentToolCall, call_id)
        assert call.state == "unknown" and call.cost_state == "estimated_unknown"
        assert call.cost_charged_micro_usd == 8
        actual = session.get(ValidationBudget, UUID(wallet["subject_id"]))
        assert actual.calls == 1 and actual.spent_micro_usd == 8 and actual.held_micro_usd == 0
    # This case deliberately retains its unknown synthetic estimate. It neither
    # retries the old call nor refunds or deletes any of the accounting history.
