"""Mixed real domain writes with synthetic model history; never provider calls.

Only Model/Skill/Run records are seeded. Artifacts, Claims, specifications,
EvidenceLinks and receipts come from normal HTTP or the registered command port.
"""

from copy import deepcopy
from types import SimpleNamespace
from pdos_next.agent_kernel.qualification_binding import model_identity, tool_identity

from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bindings import SkillBinding, WriteSource, execution_key
from pdos_next.agent_kernel.models import (
    AgentEvent,
    AgentRun,
    AgentToolCall,
    TenantSkillEnablement,
)
from pdos_next.domain.preproject.evidence_models import EvidenceLink
from pdos_next.domain.products.models import DefinitionSpecRow
from pdos_next.models import Artifact, Audit, Claim, Confirmation, Outbox, Receipt
from pdos_next.service import digest
from tests.products import test_definition_item_revert_pg as item_history
from tests.products.test_definition_item_commands_pg import current_items, draft, upsert
from tests.products.test_definition_transactions import command, post, source


def actual_model(setup, fixture, operation, arguments, *, skill_key="gap_check"):
    """Persist an actual selected skill and completed synthetic Model response."""
    skill = fixture.catalog._skills[skill_key]
    assert operation in skill.operations
    if not hasattr(fixture, "mixed_skills"):
        fixture.mixed_skills = {fixture.source.skill.key: fixture.source.skill}
    bound = fixture.mixed_skills.get(skill_key)
    if bound is None:
        bound = SkillBinding(
            key=skill.key,
            version=skill.version,
            digest=skill.digest,
            load_event_id=uuid4(),
        )
        with Session(setup.admin) as session, session.begin():
            session.add(
                AgentEvent(
                    id=bound.load_event_id,
                    tenant_id=setup.tenant,
                    run_id=fixture.scope.run_id,
                    sequence=2,
                    body={
                        "type": "skill_loaded",
                        "key": skill.key,
                        "version": skill.version,
                        "digest": skill.digest,
                        "isolation": "main",
                    },
                )
            )
            enabled = session.scalar(
                select(TenantSkillEnablement).where(
                    TenantSkillEnablement.tenant_id == setup.tenant,
                    TenantSkillEnablement.skill_key == skill.key,
                )
            )
            if enabled is None:
                template = fixture.qualification
                session.add(
                    TenantSkillEnablement(
                        id=uuid4(),
                        tenant_id=setup.tenant,
                        skill_key=skill.key,
                        enabled=True,
                        pilot=True,
                        qualification_revoked=False,
                        qualified_skill_version=skill.version,
                        qualified_model_version=fixture.route.version,
                        qualified_skill_digest=skill.digest,
                        qualified_tool_digest=tool_identity(skill, fixture.registry),
                        qualified_model_digest=model_identity(fixture.route),
                        review_case_refs=deepcopy(template.review_case_refs),
                        reviewed_by=setup.human,
                        reviewed_at=template.reviewed_at,
                    )
                )
        fixture.mixed_skills[skill_key] = bound
    binding = deepcopy(fixture.model.execution_binding)
    binding["loaded_skills"] = [
        value.model_dump(mode="json") for value in fixture.mixed_skills.values()
    ]
    identity = uuid4()
    with Session(setup.admin) as session, session.begin():
        session.add(
            AgentToolCall(
                id=identity,
                tenant_id=setup.tenant,
                run_id=fixture.scope.run_id,
                call_key=str(uuid4()),
                input_digest=digest(arguments),
                tool="model",
                state="completed",
                execution_binding=binding,
                result={"calls": [{"name": operation, "arguments": arguments}]},
            )
        )
    write_source = WriteSource(skill=bound, model_call_id=identity, response_index=0)
    return fixture.adapter.execute(
        fixture.scope,
        operation,
        arguments,
        execution_key(fixture.scope.run_id, identity, 0),
        source=write_source,
    )


def mixed_history(setup, monkeypatch):
    definition_id, _ = draft(setup)
    artifact_id = UUID(source(setup, visibility="category"))
    original_ledger = item_history.ledger

    def source_bound_ledger():
        fixture = original_ledger()
        fixture.run.read_sources = [
            {
                "artifact_id": str(artifact_id),
                "expected_revision": 1,
                "product_id": str(setup.product),
            }
        ]
        return fixture

    class SourceReaderSession(Session):
        """Seed the synthetic ledger under its actual human source reader."""

    @event.listens_for(SourceReaderSession, "after_begin")
    def bind_reader(session, _transaction, connection):
        connection.execute(
            text(
                "SELECT set_config('pdos.tenant_id', :tenant, true), "
                "set_config('pdos.actor_id', :actor, true), "
                "set_config('pdos.requester_id', :actor, true), "
                "set_config('pdos.category_id', :category, true)"
            ),
            {
                "tenant": str(setup.tenant),
                "actor": str(setup.human),
                "category": str(setup.category),
            },
        )
        session.info["scope"] = (
            setup.tenant,
            setup.human,
            setup.human,
            setup.category,
        )

    initial_arguments = item_history.ai_arguments(
        definition_id, upsert(key="noise", item_status="ai_draft")
    )
    # The immutable Run read set is bound before INSERT, rather than retrofitted.
    with monkeypatch.context() as patch:
        patch.setattr(item_history, "ledger", source_bound_ledger)
        patch.setattr(item_history, "Session", SourceReaderSession)
        fixture = item_history.agent_fixture(setup, initial_arguments)
    claim = actual_model(
        setup,
        fixture,
        "evidence.claim.record",
        {
            "source": {
                "kind": "artifact",
                "id": str(artifact_id),
                "version": 1,
                "locator": "line:2",
                "quote": "Pressure: 150 PSI",
            },
            "nature": "extracted",
            "availability": "known",
            "content": {"text": "Synthetic pressure source only; no verified condition"},
        },
        skill_key="public_research",
    )
    operation = upsert(key="noise", item_status="ai_draft")
    operation["source_refs"] = [{"type": "claim", "id": claim["subject_id"], "version": 1}]
    item = actual_model(
        setup,
        fixture,
        item_history.OPERATION,
        item_history.ai_arguments(definition_id, operation),
    )
    current = current_items(setup, definition_id)["noise"]
    link = actual_model(
        setup,
        fixture,
        "evidence.link.create",
        {
            "evidence": {"type": "claim", "id": claim["subject_id"], "version": 1},
            "target": {"type": "definition_spec", "id": str(current.id), "version": 1},
            "relation": "supports",
        },
    )
    return SimpleNamespace(
        fixture=fixture,
        definition_id=definition_id,
        artifact_id=artifact_id,
        current=current,
        claim_id=UUID(claim["subject_id"]),
        link_id=UUID(link["subject_id"]),
        receipt_ids={claim["id"], item["id"], link["id"]},
    )


def assert_unchanged(setup, history):
    assert current_items(setup, history.definition_id)["noise"].id == history.current.id
    with Session(setup.admin) as session:
        assert session.get(Artifact, history.artifact_id).status == "active"
        assert session.get(Claim, history.claim_id).status == "active"
        assert session.get(EvidenceLink, history.link_id).reverted_by_receipt_id is None
        run = session.get(AgentRun, history.fixture.scope.run_id)
        assert run.reverted_at is None and run.cancel_epoch == 0


def test_mixed_claim_item_link_run_reverts_once_with_actual_receipts(setup, monkeypatch):
    history = mixed_history(setup, monkeypatch)
    preview = item_history.revert_preview(setup, history.fixture)
    assert preview.status_code == 200, preview.text
    assert {row["id"] for row in preview.json()["review"]["receipts"]} == history.receipt_ids
    result = post(setup, preview.json()["command"])
    assert result.status_code == 200, result.text
    receipt_id = UUID(result.json()["id"])
    assert post(setup, preview.json()["command"]).json() == result.json()
    final = current_items(setup, history.definition_id)["noise"]
    assert final.item_id == history.current.item_id and final.item_version == 2
    assert final.removed and final.receipt_id == receipt_id
    assert set(result.json()["result"]["receipt_ids"]) == history.receipt_ids
    with Session(setup.admin) as session:
        assert session.get(Artifact, history.artifact_id).status == "active"
        assert session.get(Claim, history.claim_id).status == "reverted"
        assert session.get(EvidenceLink, history.link_id).reverted_by_receipt_id == receipt_id
        assert not session.get(DefinitionSpecRow, history.current.id).removed
        run = session.get(AgentRun, history.fixture.scope.run_id)
        assert run.reverted_at is not None and run.revert_receipt_id == receipt_id
        receipt = session.get(Receipt, receipt_id)
        assert receipt.actor_id == setup.human and receipt.agent_run_id is None
        for model in (Audit, Outbox):
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.receipt_id == receipt_id)
                )
                == 1
            )


def test_mixed_revert_finish_failure_rolls_back_and_original_confirmation_retries(
    setup, monkeypatch
):
    from pdos_next.agent_kernel import persistence

    history = mixed_history(setup, monkeypatch)
    preview = item_history.revert_preview(setup, history.fixture)
    assert preview.status_code == 200, preview.text
    request = preview.json()["command"]
    original_finish = persistence.finish_run_revert

    def failing_finish(*args, **kwargs):
        original_finish(*args, **kwargs)
        raise RuntimeError("synthetic mixed revert finish failure")

    with monkeypatch.context() as patch:
        patch.setattr(persistence, "finish_run_revert", failing_finish)
        with pytest.raises(RuntimeError, match="synthetic mixed revert finish failure"):
            post(setup, request)
    assert_unchanged(setup, history)
    with Session(setup.admin) as session:
        confirmation = session.scalar(
            select(Confirmation).where(
                Confirmation.token_hash == digest(request["payload"]["confirmation_token"])
            )
        )
        assert confirmation is not None and not confirmation.consumed
        assert not session.scalar(
            select(Receipt.id).where(
                Receipt.operation == "ai.run.revert",
                Receipt.subject_id == history.fixture.scope.run_id,
            )
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(DefinitionSpecRow)
                .where(DefinitionSpecRow.item_id == history.current.item_id)
            )
            == 1
        )
    retried = post(setup, request)
    assert retried.status_code == 200, retried.text
    assert current_items(setup, history.definition_id)["noise"].removed


def test_mixed_run_fixed_definition_dependency_blocks_all_effects(setup, monkeypatch):
    history = mixed_history(setup, monkeypatch)
    continuation = post(
        setup,
        command(
            setup,
            "product.definition.draft",
            {
                "mode": "inherit_parent",
                "parent_definition_id": str(history.definition_id),
                "expected_parent_revision": 1,
                "change_reason": "Synthetic fixed consumer retains the original definition",
            },
        ),
    )
    assert continuation.status_code == 200, continuation.text
    denied = item_history.revert_preview(setup, history.fixture)
    assert denied.status_code == 409, denied.text
    assert denied.json()["code"] == "UNDO_BLOCKED_BY_DEPENDENCY"
    assert_unchanged(setup, history)
