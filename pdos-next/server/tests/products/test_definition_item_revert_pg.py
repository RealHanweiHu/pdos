"""Stored synthetic model ledger → definition T0/T1 → named run compensation.

All model/skill records are explicit synthetic fixtures. No provider call or real
qualification is made, and all commands use the registered domain execution port.
"""

from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bindings import SkillBinding, execution_key
from pdos_next.agent_kernel.disclosure import disclosure, skill_operations
from pdos_next.agent_kernel.domain_adapter import DomainCommands
from pdos_next.agent_kernel.models import (
    AgentRun,
    AgentSession,
    AgentToolCall,
    TenantSkillEnablement,
)
from pdos_next.agent_kernel.qualification_binding import model_identity, tool_identity
from pdos_next.database import tenant_session
from pdos_next.domain.preproject.provenance import prepare_candidate
from pdos_next.domain.products.models import DefinitionRevision, DefinitionSpecRow
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation, Receipt
from pdos_next.service import digest
from tests.agent_kernel.test_execution_binding import ledger
from tests.products.test_definition_item_commands_pg import (
    OPERATION,
    confirmed,
    current_items,
    draft,
    patch,
    upsert,
)
from tests.products.test_definition_transactions import command, post


def agent_fixture(
    setup,
    arguments,
    *,
    operation=OPERATION,
    skill_key="gap_check",
    product_bound=True,
    proposal_id=None,
    parent_id=None,
    goal="Synthetic definition item regression",
):
    fixture = ledger()
    fixture.scope = replace(
        fixture.scope,
        tenant_id=setup.tenant,
        category_id=setup.category,
        product_id=setup.product if product_bound else None,
        proposal_id=proposal_id,
        requester_id=setup.human,
        writer_id=setup.agent,
    )
    for name in (
        "tenant_id",
        "category_id",
        "product_id",
        "proposal_id",
        "requester_id",
        "writer_id",
    ):
        setattr(fixture.run, name, getattr(fixture.scope, name))
    fixture.run.trigger, fixture.run.goal = "page", goal
    fixture.run.intent_key, fixture.run.intent_digest = str(uuid4()), digest(str(uuid4()))
    skill = fixture.catalog._skills[skill_key]
    assert operation in skill.operations
    bound = SkillBinding(
        key=skill.key, version=skill.version, digest=skill.digest, load_event_id=fixture.event.id
    )
    fixture.source = fixture.source.model_copy(update={"skill": bound})
    fixture.model.execution_binding = {
        **fixture.model.execution_binding,
        "loaded_skills": [bound.model_dump(mode="json")],
        "tool_definitions_digest": digest(
            disclosure(fixture.registry, "main", skill_operations([skill]))
        ),
    }
    fixture.run.versions = {
        **fixture.run.versions,
        "tool_definitions": {"main": fixture.model.execution_binding["tool_definitions_digest"]},
    }
    fixture.event.body = {
        "type": "skill_loaded",
        "key": skill.key,
        "version": skill.version,
        "digest": skill.digest,
        "isolation": fixture.scope.isolation,
    }
    fixture.qualification.skill_key = skill.key
    fixture.qualification.qualified_skill_version = skill.version
    fixture.qualification.qualified_skill_digest = skill.digest
    fixture.qualification.qualified_tool_digest = tool_identity(skill, fixture.registry)
    fixture.qualification.qualified_model_digest = model_identity(fixture.route)
    fixture.qualification.reviewed_by = setup.human
    fixture.model.tenant_id = fixture.event.tenant_id = fixture.qualification.tenant_id = (
        setup.tenant
    )
    fixture.model.call_key, fixture.model.input_digest = str(uuid4()), digest(arguments)
    fixture.model.result = {"calls": [{"name": operation, "arguments": arguments}]}
    fixture.arguments, fixture.spec = arguments, fixture.registry.get(operation)
    with Session(setup.admin) as session, session.begin():
        if parent_id is None:
            session.add(
                AgentSession(
                    id=fixture.scope.session_id,
                    tenant_id=setup.tenant,
                    category_id=setup.category,
                    product_id=fixture.scope.product_id,
                    proposal_id=fixture.scope.proposal_id,
                    owner_id=setup.human,
                )
            )
        else:
            parent = session.get(AgentRun, parent_id)
            assert parent is not None and parent.state in {
                "completed", "partial", "failed", "cancelled"
            }
            fixture.scope = replace(fixture.scope, session_id=parent.session_id)
            fixture.run.session_id = parent.session_id
            fixture.run.continued_from_id = parent.id
        session.flush()
        session.add(fixture.run)
        session.flush()
        existing = session.scalar(
            select(TenantSkillEnablement).where(
                TenantSkillEnablement.tenant_id == setup.tenant,
                TenantSkillEnablement.skill_key == skill.key,
            )
        )
        if existing is None:
            session.add(fixture.qualification)
        else:
            fixture.qualification = existing
        session.add_all([fixture.model, fixture.event])
        session.flush()
        session.expunge_all()
    fixture.adapter = DomainCommands(
        setup.engine,
        catalog=fixture.catalog,
        registry=fixture.registry,
        route=lambda *_: fixture.route,
    )
    return fixture


def next_model(setup, fixture, arguments):
    row = AgentToolCall(
        id=uuid4(),
        tenant_id=setup.tenant,
        run_id=fixture.scope.run_id,
        call_key=str(uuid4()),
        input_digest=digest(arguments),
        tool="model",
        state="completed",
        execution_binding=fixture.model.execution_binding,
        result={"calls": [{"name": OPERATION, "arguments": arguments}]},
    )
    identity = row.id
    with Session(setup.admin) as session, session.begin():
        session.add(row)
    return fixture.source.model_copy(update={"model_call_id": identity})


def execute_ai(fixture, arguments=None, source=None):
    arguments, source = arguments or fixture.arguments, source or fixture.source
    return fixture.adapter.execute(
        fixture.scope,
        OPERATION,
        arguments,
        execution_key(fixture.scope.run_id, source.model_call_id, source.response_index),
        source=source,
    )


def ai_arguments(definition_id, *operations):
    return {"definition_id": str(definition_id), "ops": list(operations)}


def revert_preview(setup, fixture):
    cmd = command(setup, "ai.run.revert", {"run_id": str(fixture.scope.run_id)})
    response = setup.client.post(
        f"/v1/categories/{setup.category}/commands/preview", headers=setup.headers, json=cmd
    )
    return response


def test_t0_preserves_human_value_and_forbids_ai_confirmed(setup):
    definition_id, _ = draft(setup)
    human = current_items(setup, definition_id)["pressure"]
    arguments = ai_arguments(
        definition_id, upsert(human, item_status="ai_draft", reason="AI改人工值")
    )
    fixture = agent_fixture(setup, arguments)
    with pytest.raises(DomainError) as error:
        execute_ai(fixture)
    assert error.value.code == "CONFIRMATION_REQUIRED"
    assert current_items(setup, definition_id)["pressure"].id == human.id
    forbidden = upsert(
        key="noise", availability="known", item_status="confirmed", value="3", unit="dB"
    )
    forbidden["source_refs"] = [
        {"type": "human", "id": str(setup.human), "version": 1, "statement": "实际具名合成来源"}
    ]
    arguments = ai_arguments(definition_id, forbidden)
    with pytest.raises(DomainError) as error:
        execute_ai(fixture, arguments, next_model(setup, fixture, arguments))
    assert error.value.detail["reason"] == "ai_cannot_confirm"
    assert set(current_items(setup, definition_id)) == {"pressure"}


def test_t1_actual_candidate_keeps_ai_writer_and_cancellation_blocks_reuse(setup):
    definition_id, _ = draft(setup)
    before = current_items(setup, definition_id)["pressure"]
    arguments = ai_arguments(
        definition_id, upsert(before, item_status="ai_draft", reason="候选修订")
    )
    fixture = agent_fixture(setup, arguments)
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.agent,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        prepared = prepare_candidate(
            session,
            fixture.scope,
            OPERATION,
            arguments,
            fixture.source,
            catalog=fixture.catalog,
            registry=fixture.registry,
            route=fixture.route,
        )
    cmd = command(setup, OPERATION, prepared)
    denied = post(setup, cmd)
    assert denied.status_code == 409 and denied.json()["code"] == "CONFIRMATION_REQUIRED"
    receipt, confirmed_command = confirmed(setup, cmd)
    row = current_items(setup, definition_id)["pressure"]
    assert row.origin == "ai_draft" and row.writer_id == setup.agent
    assert row.confirmed_by == setup.human and row.run_id == fixture.scope.run_id
    assert row.prepared_candidate_id is not None
    assert receipt["agent_run_id"] == str(fixture.scope.run_id)
    assert post(setup, confirmed_command).json()["id"] == receipt["id"]
    next_arguments = ai_arguments(
        definition_id, upsert(row, item_status="ai_draft", reason="待取消候选")
    )
    model_source = next_model(setup, fixture, next_arguments)
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.agent,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        prepared = prepare_candidate(
            session,
            fixture.scope,
            OPERATION,
            next_arguments,
            model_source,
            catalog=fixture.catalog,
            registry=fixture.registry,
            route=fixture.route,
        )
    preview = setup.client.post(
        f"/v1/categories/{setup.category}/commands/preview",
        headers=setup.headers,
        json=command(setup, OPERATION, prepared),
    )
    assert preview.status_code == 200, preview.text
    with Session(setup.admin) as session, session.begin():
        run = session.get(AgentRun, fixture.scope.run_id)
        run.state, run.cancel_epoch = "cancelled", run.cancel_epoch + 1
    rejected = post(setup, preview.json()["command"])
    assert rejected.status_code == 403 and rejected.json()["code"] == "FORBIDDEN_SCOPE"
    assert current_items(setup, definition_id)["pressure"].id == row.id


def test_revert_compensates_entire_same_run_chain_and_preserves_history(setup):
    definition_id, _ = draft(setup)
    fixture = agent_fixture(
        setup, ai_arguments(definition_id, upsert(key="noise", item_status="ai_draft"))
    )
    first_receipt = execute_ai(fixture)
    initial = current_items(setup, definition_id)["noise"]
    arguments = ai_arguments(
        definition_id,
        upsert(initial, key="noise", item_status="expert_pending", reason="待专业核对"),
    )
    second_receipt = execute_ai(fixture, arguments, next_model(setup, fixture, arguments))
    second = current_items(setup, definition_id)["noise"]
    assert second.item_version == 2 and second.run_id == fixture.scope.run_id
    preview = revert_preview(setup, fixture)
    assert preview.status_code == 200, preview.text
    assert {row["id"] for row in preview.json()["review"]["receipts"]} == {
        first_receipt["id"],
        second_receipt["id"],
    }
    result = post(setup, preview.json()["command"])
    assert result.status_code == 200, result.text
    assert post(setup, preview.json()["command"]).json()["id"] == result.json()["id"]
    restored = current_items(setup, definition_id)["noise"]
    assert restored.removed and restored.item_version == 3 and restored.item_id == initial.item_id
    assert str(restored.receipt_id) == result.json()["id"]
    with Session(setup.admin) as session:
        assert session.get(DefinitionSpecRow, initial.id).removed is False
        assert session.get(DefinitionSpecRow, second.id).removed is False
        assert session.get(AgentRun, fixture.scope.run_id).reverted_at is not None
        assert session.get(DefinitionRevision, definition_id).revision == 1


def test_revert_restores_value_before_this_run_not_previous_run(setup):
    definition_id, _ = draft(setup)
    first_run = agent_fixture(
        setup,
        ai_arguments(
            definition_id, upsert(key="noise", item_status="ai_draft", reason="第一运行的草稿")
        ),
    )
    execute_ai(first_run)
    baseline = current_items(setup, definition_id)["noise"]
    second_run = agent_fixture(
        setup,
        ai_arguments(
            definition_id,
            upsert(baseline, key="noise", item_status="expert_pending", reason="第二运行修改"),
        ),
    )
    execute_ai(second_run)
    preview = revert_preview(setup, second_run)
    assert preview.status_code == 200, preview.text
    result = post(setup, preview.json()["command"])
    assert result.status_code == 200, result.text
    restored = current_items(setup, definition_id)["noise"]
    assert restored.item_version == 3 and not restored.removed
    assert restored.reason == baseline.reason and restored.item_status == baseline.item_status
    assert restored.source_refs == baseline.source_refs
    for field in ("origin", "writer_id", "run_id", "confirmed_by", "prepared_candidate_id"):
        assert getattr(restored, field) == getattr(baseline, field)
    assert str(restored.receipt_id) == result.json()["id"]
    with Session(setup.admin) as session:
        assert session.get(AgentRun, first_run.scope.run_id).reverted_at is None


def test_revert_keeps_human_changed_item_and_reverts_unmodified_sibling(setup):
    definition_id, _ = draft(setup)
    fixture = agent_fixture(
        setup,
        ai_arguments(
            definition_id,
            upsert(key="noise", item_status="ai_draft"),
            upsert(key="weight", item_status="ai_draft"),
        ),
    )
    execute_ai(fixture)
    old = current_items(setup, definition_id)["noise"]
    human = post(setup, patch(setup, definition_id, upsert(old, key="noise", reason="人工保留")))
    assert human.status_code == 200, human.text
    protected = current_items(setup, definition_id)["noise"]
    preview = revert_preview(setup, fixture)
    assert preview.status_code == 200, preview.text
    result = post(setup, preview.json()["command"])
    assert result.status_code == 200, result.text
    final = current_items(setup, definition_id)
    assert final["noise"].id == protected.id and not final["noise"].removed
    assert final["weight"].removed
    assert any(
        item["item_id"] == str(protected.item_id)
        for item in result.json()["result"]["retained_items"]
    )


def test_revert_receipt_failure_is_atomic_and_confirmation_reusable(setup, monkeypatch):
    import pdos_next.service as common

    definition_id, _ = draft(setup)
    fixture = agent_fixture(
        setup, ai_arguments(definition_id, upsert(key="noise", item_status="ai_draft"))
    )
    execute_ai(fixture)
    before = current_items(setup, definition_id)["noise"]
    preview = revert_preview(setup, fixture)
    assert preview.status_code == 200, preview.text
    cmd = deepcopy(preview.json()["command"])
    original = common.append_receipt

    def fail_receipt(*args, **kwargs):
        raise RuntimeError("synthetic revert receipt failure")

    monkeypatch.setattr(common, "append_receipt", fail_receipt)
    with pytest.raises(RuntimeError, match="synthetic revert receipt failure"):
        post(setup, cmd)
    assert current_items(setup, definition_id)["noise"].id == before.id
    with Session(setup.admin) as session:
        assert session.get(AgentRun, fixture.scope.run_id).reverted_at is None
        proof = session.scalar(
            select(Confirmation).where(
                Confirmation.token_hash == digest(cmd["payload"]["confirmation_token"])
            )
        )
        assert not proof.consumed
        assert not session.scalar(
            select(Receipt.id).where(
                Receipt.operation == "ai.run.revert", Receipt.subject_id == fixture.scope.run_id
            )
        )
    monkeypatch.setattr(common, "append_receipt", original)
    assert post(setup, cmd).status_code == 200


def test_revert_cannot_change_fixed_definition_consumed_by_private_proposal(setup):
    from tests.preproject.test_g0 import create, payload

    definition_id, _ = draft(setup)
    fixture = agent_fixture(
        setup, ai_arguments(definition_id, upsert(key="noise", item_status="ai_draft"))
    )
    execute_ai(fixture)
    before = current_items(setup, definition_id)["noise"]
    data = payload(setup)
    data["source_refs"] = [{"type": "definition", "id": str(definition_id), "version": 1}]
    create(setup, data)
    denied = revert_preview(setup, fixture)
    assert denied.status_code == 409, denied.text
    assert denied.json()["code"] == "UNDO_BLOCKED_BY_DEPENDENCY"
    assert current_items(setup, definition_id)["noise"].id == before.id
    with Session(setup.admin) as session:
        assert session.get(AgentRun, fixture.scope.run_id).reverted_at is None


def test_actual_t0_remove_keeps_sparse_request_and_reverts_whole_chain(setup):
    definition_id, _ = draft(setup)
    arguments = ai_arguments(definition_id, upsert(key="ai_remove", item_status="ai_draft"))
    fixture = agent_fixture(setup, arguments)
    first = execute_ai(fixture)
    before = current_items(setup, definition_id)["ai_remove"]
    removal = ai_arguments(
        definition_id,
        {
            "op": "remove",
            "item_id": str(before.item_id),
            "base_version": before.item_version,
        },
    )
    source = next_model(setup, fixture, removal)
    removed = execute_ai(fixture, removal, source)
    assert removed["id"] != first["id"]
    assert execute_ai(fixture, removal, source) == removed
    current = current_items(setup, definition_id)["ai_remove"]
    assert current.removed and current.item_version == 2
    preview = revert_preview(setup, fixture)
    assert preview.status_code == 200, preview.text
    reverted = post(setup, preview.json()["command"])
    assert reverted.status_code == 200, reverted.text
    current = current_items(setup, definition_id)["ai_remove"]
    assert current.removed and current.item_version == 3
    assert len(reverted.json()["result"]["receipt_ids"]) == 2
