"""Actual service ledger/SQL over explicit synthetic host causal inputs.

Root alone executes this PG case. HTTP saves and real T1 activations create both
rules, ticks create actual schedule roots, and enqueue/start create real children.
The synthetic child origin is not a business Outbox event or a provider request.
This case covers different rules under the same named delegator, not cross-owner
event admission. All business facts are written through their existing owners.
"""

from copy import deepcopy
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.models import AgentRun, AgentToolCall, ValidationBudget
from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.domain.automations import service_runtime
from pdos_next.domain.automations.schemas import DRAFT_SAVE
from pdos_next.domain.automations.service_models import (
    AutomationCausalChain,
    AutomationServiceAttempt,
    AutomationServiceGrant,
)
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation, now
from tests.agent_kernel import test_skill_management as skills
from tests.automations_pg.test_manual_workflow import assert_common_group, reading, save
from tests.automations_pg.test_service_automation_pg import (
    _activate,
    _control,
    _ready,
    _spec,
    _state,
)


def _activate_second(setup, spec):
    """Use the same real command flow without assuming this tenant has no first grant."""
    draft_command, draft_receipt = save(
        setup, DRAFT_SAVE, {"expected_rule_revision": 0, "spec": deepcopy(spec)}
    )
    rule_id = draft_receipt["result"]["rule_id"]
    command = _control(setup, reading(setup, rule_id)["rule"])
    prepared = skills.preview(setup, command)
    authority = prepared["review"]["service_authorization"]
    assert authority["service_principal_id"] == str(setup.agent)
    assert authority["delegator_id"] == str(setup.human)
    assert authority["budget"] == spec["budget"]
    command = prepared["command"]
    assert command["payload"]["confirmation_token"]
    response = skills.post(setup, command)
    assert response.status_code == 200, response.text
    with Session(setup.admin) as session:
        assert_common_group(session, setup, draft_command, draft_receipt)
        version = assert_common_group(session, setup, command, response.json())
        grant = session.scalar(
            select(AutomationServiceGrant).where(
                AutomationServiceGrant.tenant_id == setup.tenant,
                AutomationServiceGrant.published_version_id == version.id,
            )
        )
        assert grant is not None and grant.rule_id == UUID(rule_id)
        assert grant.owner_id == setup.human and grant.writer_id == setup.agent
        proof = session.get(Confirmation, version.confirmation_id)
        assert proof.consumed and proof.actor_id == setup.human
        assert proof.snapshot["service_authorization"] == authority
        ref = service_runtime.reference(grant)
    return rule_id, ref


def _schedule_root(setup, ref):
    assert service_runtime.tick(setup.engine, ref)["state"] == "active"
    with Session(setup.admin) as session:
        row = session.scalar(
            select(AutomationServiceAttempt).where(
                AutomationServiceAttempt.tenant_id == setup.tenant,
                AutomationServiceAttempt.service_grant_id == UUID(ref["grant_id"]),
                AutomationServiceAttempt.depth == 0,
                AutomationServiceAttempt.origin["kind"].astext == "schedule",
            )
        )
        assert row is not None and row.state == "admitted"
        assert row.parent_run_id is None and row.run_id is not None
        return row.id, row.run_id, row.chain_id


def _synthetic_child(setup, ref, parent_run_id, key):
    """Trusted fixture invokes the host owner; it does not fabricate an Outbox receipt."""
    with service_runtime.session(setup.engine, ref) as session:
        grant, _, spec = service_runtime.saved(session, ref, admission=True)
        point = now()
        attempt = service_runtime.enqueue(
            session,
            grant,
            spec,
            key=key,
            origin={
                "kind": "synthetic_host_cause",
                "source_trigger_kind": "schedule",
                "recorded_at": point.isoformat(),
                "original_timezone": "UTC",
                "synthetic_causal_fixture": True,
                "evidence": "Host test cause only; no business Outbox or provider call",
                "parent_run_id": str(parent_run_id),
            },
            due_at=point,
            parent_run_id=parent_run_id,
        )
        attempt_id = attempt.id
        run_id = session.scalar(
            text("SELECT automation_service_start(:attempt)"), {"attempt": attempt_id}
        )
        session.expire(attempt)
        assert attempt.parent_run_id == parent_run_id and attempt.depth == 1
        return attempt_id, run_id, attempt.chain_id, attempt.state, attempt.error_code


def test_actual_service_chain_keeps_unknown_cost_across_rules_and_suppresses_depth(setup):
    wallet = _ready(setup)
    first_spec = _spec(setup, wallet)
    first_spec["name"] = "Synthetic root chain with ten cost units"
    first_spec["budget"]["limit_micro_usd"] = 10
    first_spec["max_cascade_depth"] = 3
    first_rule, first_ref = _activate(setup, first_spec)
    second_spec = _spec(setup, wallet)
    second_spec["name"] = "Synthetic child rule with its own larger envelope"
    second_spec["budget"]["limit_micro_usd"] = 100
    # This limit applies to B's own root, not to a child that inherits A's chain.
    second_spec["max_cascade_depth"] = 0
    second_rule, second_ref = _activate_second(setup, second_spec)
    assert first_rule != second_rule

    _, first_run, root_chain = _schedule_root(setup, first_ref)
    store = KernelStore(setup.engine)
    first_scope = store.scope(
        tenant_id=setup.tenant,
        requester_id=setup.human,
        writer_id=setup.agent,
        category_id=setup.category,
        run_id=first_run,
    )
    # Only the host's real ledger API is exercised. No model/client is dispatched.
    pricing = {"source": "Synthetic service-chain fee fixture; no provider request"}
    call_id, prior = store.claim(
        first_scope,
        "synthetic-service-root-unknown",
        "model",
        {"synthetic": True, "purpose": "chain estimate retention"},
        reservation=10,
        cost_lease=(8, 5, 5, pricing),
    )
    assert prior is None
    assert store.release_call(first_scope, call_id, unknown=True, error="EXTERNAL_OUTCOME_UNKNOWN")

    child_id, child_run, child_chain, state, error = _synthetic_child(
        setup, second_ref, first_run, "synthetic-cause:first-to-second"
    )
    assert state == "admitted" and error is None and child_run is not None
    assert child_chain == root_chain
    with Session(setup.admin) as session:
        chain = session.get(AutomationCausalChain, root_chain)
        child = session.get(AutomationServiceAttempt, child_id)
        assert chain.root_grant_id == UUID(first_ref["grant_id"])
        assert chain.budget == first_spec["budget"] and chain.max_depth == 3
        assert child.rule_id == UUID(second_rule) and child.parent_run_id == first_run
        assert child.service_grant_id == UUID(second_ref["grant_id"])
        assert child.depth == 1 and child.origin["synthetic_causal_fixture"] is True
        for run_id in (first_run, child_run):
            run = session.get(AgentRun, run_id)
            assert run.trigger == "automation_service"
            assert run.writer_id == setup.agent and run.requester_id == setup.human
            assert run.writer_id != run.requester_id
        call = session.get(AgentToolCall, call_id)
        assert call.state == "unknown" and call.cost_state == "estimated_unknown"
        assert call.cost_reserved_micro_usd == 0 and call.cost_charged_micro_usd == 8
        assert call.actual_input_tokens == call.actual_output_tokens == 5
        assert call.provider_request_id is None and call.receipt_id is None
        actual = session.get(ValidationBudget, UUID(wallet["subject_id"]))
        assert actual.calls == 1 and actual.spent_micro_usd == 8 and actual.held_micro_usd == 0

    child_scope = store.scope(
        tenant_id=setup.tenant,
        requester_id=setup.human,
        writer_id=setup.agent,
        category_id=setup.category,
        run_id=child_run,
    )
    before = _state(setup)
    with pytest.raises(DomainError) as denied:
        store.claim(
            child_scope,
            "synthetic-child-exceeds-parent-chain",
            "model",
            {"synthetic": True, "purpose": "three fits B but exceeds inherited chain"},
            reservation=2,
            cost_lease=(3, 1, 1, pricing),
        )
    assert denied.value.code == "RATE_LIMITED"
    assert _state(setup) == before

    # B's separate real schedule root has depth cap zero. The next synthetic A
    # child keeps that root/parent/depth and is suppressed, never reset to a root.
    _, second_root_run, shallow_chain = _schedule_root(setup, second_ref)
    assert shallow_chain != root_chain
    with Session(setup.admin) as session:
        assert session.get(AutomationCausalChain, shallow_chain).max_depth == 0
        runs_before = session.scalar(
            select(func.count()).select_from(AgentRun).where(AgentRun.tenant_id == setup.tenant)
        )
    blocked_id, blocked_run, blocked_chain, state, error = _synthetic_child(
        setup, first_ref, second_root_run, "synthetic-cause:depth-one-under-zero"
    )
    assert blocked_run is None and blocked_chain == shallow_chain
    assert state == "suppressed" and error == "CASCADE_DEPTH_EXCEEDED"
    assert reading(setup, first_rule)["rule"]["admitted_count"] == 1
    assert reading(setup, second_rule)["rule"]["admitted_count"] == 2
    with Session(setup.admin) as session:
        assert (
            session.scalar(
                select(func.count()).select_from(AgentRun).where(AgentRun.tenant_id == setup.tenant)
            )
            == runs_before
            == 3
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AgentToolCall)
                .where(AgentToolCall.tenant_id == setup.tenant)
            )
            == 1
        )
        blocked = session.get(AutomationServiceAttempt, blocked_id)
        assert blocked.depth == 1 and blocked.parent_run_id == second_root_run
        assert blocked.run_id is None and blocked.admitted_at is None
        retained = session.get(AgentToolCall, call_id)
        assert retained.cost_state == "estimated_unknown" and retained.cost_charged_micro_usd == 8
        actual = session.get(ValidationBudget, UUID(wallet["subject_id"]))
        assert actual.calls == 1 and actual.spent_micro_usd == 8 and actual.held_micro_usd == 0
    frozen = _state(setup)
    with service_runtime.session(setup.engine, first_ref) as session:
        assert (
            session.scalar(
                text("SELECT automation_service_start(:attempt)"), {"attempt": blocked_id}
            )
            is None
        )
    assert _state(setup) == frozen
