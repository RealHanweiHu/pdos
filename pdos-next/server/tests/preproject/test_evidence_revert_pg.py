"""Real Claim + Link T0 commands and all-or-none named whole-run reversal."""
# ruff: noqa: F811 -- pytest injects the explicitly re-exported shared fixture

from copy import deepcopy
from types import SimpleNamespace
from pdos_next.agent_kernel.qualification_binding import model_identity, tool_identity

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bindings import SkillBinding, WriteSource, execution_key
from pdos_next.agent_kernel.models import (
    AgentEvent,
    AgentRun,
    AgentToolCall,
    TenantSkillEnablement,
)
from pdos_next.domain.preproject.evidence_models import EvidenceLink
from pdos_next.models import Artifact, Audit, Claim, Confirmation, Consumption, Outbox, Receipt, now
from pdos_next.service import digest
from tests.preproject.test_evidence_commands_pg import (
    artifact,
    claim_fixture,
    evidence_request,
    source_rows,
)
from tests.preproject.test_g0 import create, decide_request, post, read, save, submit
from tests.preproject.test_g0 import work as work
from tests.preproject.test_material_proofs_pg import human_session


def drafting_model_source(work, fixture, arguments):
    """Bootstrap only synthetic execution facts, with the real registered skill digest."""
    skill = fixture.catalog._skills["proposal_drafting"]
    assert "evidence.link.create" in skill.operations
    bound = SkillBinding(
        key=skill.key, version=skill.version, digest=skill.digest, load_event_id=uuid4()
    )
    model_id = uuid4()
    with Session(work.admin) as session, session.begin():
        sequence = (
            session.scalar(
                select(func.coalesce(func.max(AgentEvent.sequence), 0)).where(
                    AgentEvent.run_id == fixture.scope.run_id
                )
            )
            + 1
        )
        session.add(
            AgentEvent(
                id=bound.load_event_id,
                tenant_id=work.tenant,
                run_id=fixture.scope.run_id,
                sequence=sequence,
                body={
                    "type": "skill_loaded",
                    "key": skill.key,
                    "version": skill.version,
                    "digest": skill.digest,
                    "isolation": fixture.scope.isolation,
                },
            )
        )
        enabled = session.scalar(
            select(TenantSkillEnablement).where(
                TenantSkillEnablement.tenant_id == work.tenant,
                TenantSkillEnablement.skill_key == skill.key,
            )
        )
        if enabled is None:
            session.add(
                TenantSkillEnablement(
                    tenant_id=work.tenant,
                    skill_key=skill.key,
                    enabled=True,
                    pilot=True,
                    qualification_revoked=False,
                    qualified_skill_version=skill.version,
                    qualified_model_version=fixture.route.version,
                    qualified_skill_digest=skill.digest,
                    qualified_tool_digest=tool_identity(skill, fixture.registry),
                    qualified_model_digest=model_identity(fixture.route),
                    review_case_refs=[str(uuid4()) for _ in range(10)],
                    reviewed_by=work.human,
                    reviewed_at=now(),
                )
            )
        else:
            assert enabled.enabled and not enabled.qualification_revoked
            assert enabled.qualified_skill_version == skill.version
            assert enabled.qualified_model_version == fixture.route.version
        session.add(
            AgentToolCall(
                id=model_id,
                tenant_id=work.tenant,
                run_id=fixture.scope.run_id,
                call_key=str(uuid4()),
                input_digest=digest(arguments),
                tool="model",
                state="completed",
                execution_binding={
                    **fixture.model.execution_binding,
                    "loaded_skills": [
                        fixture.source.skill.model_dump(mode="json"),
                        bound.model_dump(mode="json"),
                    ],
                },
                result={"calls": [{"name": "evidence.link.create", "arguments": arguments}]},
            )
        )
    return WriteSource(skill=bound, model_call_id=model_id, response_index=0)


def ai_evidence_run(work, monkeypatch):
    source = artifact(work)
    proposal_id, _ = create(work)
    human_item = deepcopy(read(work, proposal_id).json()["items"][0])
    before_sources = source_rows(work, proposal_id)
    assert before_sources == [] and human_item["origin"] == "human"
    fixture, arguments = claim_fixture(work, monkeypatch, source, proposal_id)
    claim = fixture.adapter.execute(
        fixture.scope,
        "evidence.claim.record",
        arguments,
        execution_key(fixture.scope.run_id, fixture.source.model_call_id, 0),
        source=fixture.source,
    )
    arguments = {
        "evidence": {"type": "claim", "id": claim["subject_id"], "version": 1},
        "target": {
            "type": "proposal_item",
            "id": human_item["item_id"],
            "version": human_item["version"],
        },
        "relation": "supports",
    }
    model_source = drafting_model_source(work, fixture, arguments)
    link = fixture.adapter.execute(
        fixture.scope,
        "evidence.link.create",
        arguments,
        execution_key(fixture.scope.run_id, model_source.model_call_id, 0),
        source=model_source,
    )
    assert source_rows(work, proposal_id) == [(str(source), 1, 1, "shared")]
    with human_session(work) as session:
        actual_link = session.get(EvidenceLink, UUID(link["subject_id"]))
        assert actual_link.origin == "ai_draft" and actual_link.run_id == fixture.scope.run_id
        assert actual_link.writer_id == work.agent and actual_link.confirmed_by is None
        actual_claim = session.get(Claim, UUID(claim["subject_id"]))
        assert actual_claim.run_id == actual_link.run_id and actual_claim.origin == "ai_draft"
        assert actual_claim.confirmed_by is None
    return SimpleNamespace(
        fixture=fixture,
        run_id=fixture.scope.run_id,
        source=source,
        proposal_id=proposal_id,
        human_item=human_item,
        before_sources=before_sources,
        claim=claim,
        link=link,
    )


def revert_preview(work, evidence):
    return work.client.post(
        f"/v1/categories/{work.category}/agent-runs/{evidence.run_id}/revert-preview",
        headers=work.headers,
    )


def saved_proof(work, command):
    with human_session(work) as session:
        proof = session.scalar(
            select(Confirmation).where(
                Confirmation.token_hash == digest(command["payload"]["confirmation_token"])
            )
        )
        assert proof is not None and not proof.consumed
        return proof.id


def assert_human_item_unchanged(work, evidence):
    current = next(
        row
        for row in read(work, evidence.proposal_id).json()["items"]
        if row["item_id"] == evidence.human_item["item_id"]
    )
    for field in (
        "item_id",
        "version",
        "kind",
        "content",
        "origin",
        "writer_id",
        "run_id",
        "confirmed_by",
        "human_value",
        "removed",
    ):
        assert current[field] == evidence.human_item[field]
    return current


def assert_nothing_reverted(work, evidence, proof_id):
    with human_session(work) as session:
        claim = session.get(Claim, UUID(evidence.claim["subject_id"]))
        link = session.get(EvidenceLink, UUID(evidence.link["subject_id"]))
        run = session.get(AgentRun, evidence.run_id)
        assert claim.status == "active" and claim.revision == 1
        assert link.reverted_by_receipt_id is None
        assert run.reverted_at is None and run.revert_receipt_id is None and run.cancel_epoch == 0
        assert session.get(Confirmation, proof_id).consumed is False
        assert (
            session.scalar(
                select(func.count())
                .select_from(Receipt)
                .where(
                    Receipt.operation == "ai.run.revert",
                    Receipt.subject_id == evidence.run_id,
                )
            )
            == 0
        )
        assert session.get(Artifact, evidence.source).status == "active"


def test_t0_claim_and_link_whole_run_revert_is_one_named_confirmation_and_replay(work, monkeypatch):
    evidence = ai_evidence_run(work, monkeypatch)
    checked = revert_preview(work, evidence)
    assert checked.status_code == 200, checked.text
    command = checked.json()["command"]
    proof_id = saved_proof(work, command)
    assert {row["id"] for row in checked.json()["review"]["receipts"]} == {
        evidence.claim["id"],
        evidence.link["id"],
    }
    without_confirmation = deepcopy(command)
    without_confirmation["payload"].pop("confirmation_token")
    denied = post(work, without_confirmation)
    assert denied.status_code == 409 and denied.json()["code"] == "CONFIRMATION_REQUIRED"
    done = post(work, command)
    assert done.status_code == 200, done.text
    assert post(work, command).json() == done.json()
    receipt_id = UUID(done.json()["id"])
    with human_session(work) as session:
        run = session.get(AgentRun, evidence.run_id)
        assert run.reverted_at is not None and run.reverted_by == work.human
        assert run.revert_receipt_id == receipt_id and run.cancel_epoch == 1
        assert run.state == "running"  # Original execution state is historical, not rewritten.
        receipt = session.get(Receipt, receipt_id)
        assert receipt.actor_id == work.human and receipt.requester_id == work.human
        assert receipt.agent_run_id is None and receipt.run_id is None
        assert receipt.confirmation_id == proof_id
        assert session.get(Confirmation, proof_id).consumed is True
        claim = session.get(Claim, UUID(evidence.claim["subject_id"]))
        assert claim.status == "reverted" and claim.revision == 2
        assert (
            session.get(EvidenceLink, UUID(evidence.link["subject_id"])).reverted_by_receipt_id
            == receipt_id
        )
        assert session.get(Artifact, evidence.source).status == "active"
        for model in (Audit, Outbox):
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.receipt_id == receipt_id)
                )
                == 1
            )
    assert source_rows(work, evidence.proposal_id) == evidence.before_sources
    current = assert_human_item_unchanged(work, evidence)
    assert current["source_refs"] == evidence.human_item["source_refs"]
    assert current["evidence_links"][0]["status"] == "reverted"


@pytest.mark.parametrize("dependency", ["human_edit", "submitted", "signed"])
def test_whole_run_revert_blocks_changed_or_frozen_target_without_partial_undo(
    work, monkeypatch, dependency
):
    evidence = ai_evidence_run(work, monkeypatch)
    checked = revert_preview(work, evidence)
    assert checked.status_code == 200, checked.text
    command = checked.json()["command"]
    proof_id = saved_proof(work, command)
    if dependency == "human_edit":
        item = evidence.human_item
        response = post(
            work,
            evidence_request(
                work,
                "proposal.item.patch",
                {
                    "proposal_id": evidence.proposal_id,
                    "ops": [
                        {
                            "kind": item["kind"],
                            "item_id": item["item_id"],
                            "base_version": item["version"],
                            "content": {**item["content"], "text": "人工独立新版，保留其事实"},
                            "source_refs": [],
                        }
                    ],
                },
            ),
        )
        assert response.status_code == 200, response.text
        expected_sources = []
    else:
        submit(work, evidence.proposal_id)
        expected_sources = [(str(evidence.source), 1, 1, "shared")]
        if dependency == "signed":
            receipt, _ = save(work, decide_request(work, evidence.proposal_id), actor=work.peer)
            with human_session(work) as session:
                consumed = session.scalar(
                    select(Consumption).where(
                        Consumption.claim_id == UUID(evidence.claim["subject_id"])
                    )
                )
                assert consumed is not None and consumed.claim_version == 1
                assert str(consumed.receipt_id) == receipt["id"]
                assert consumed.decision_id is not None
    before = deepcopy(read(work, evidence.proposal_id).json())
    for response in (post(work, command), revert_preview(work, evidence)):
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "UNDO_BLOCKED_BY_DEPENDENCY"
    assert_nothing_reverted(work, evidence, proof_id)
    assert source_rows(work, evidence.proposal_id) == expected_sources
    assert read(work, evidence.proposal_id).json() == before


def test_whole_run_revert_tail_failure_rolls_back_claim_link_counter_and_proof(work, monkeypatch):
    from pdos_next.agent_kernel import persistence

    evidence = ai_evidence_run(work, monkeypatch)
    checked = revert_preview(work, evidence)
    assert checked.status_code == 200, checked.text
    command = checked.json()["command"]
    proof_id = saved_proof(work, command)
    before = deepcopy(read(work, evidence.proposal_id).json())
    finish = persistence.finish_run_revert

    def fail_tail(*args, **kwargs):
        finish(*args, **kwargs)
        raise RuntimeError("synthetic evidence whole-run tail failure")

    with monkeypatch.context() as patch:
        patch.setattr(persistence, "finish_run_revert", fail_tail)
        with pytest.raises(RuntimeError, match="synthetic evidence whole-run tail failure"):
            post(work, command)
    assert_nothing_reverted(work, evidence, proof_id)
    assert source_rows(work, evidence.proposal_id) == [(str(evidence.source), 1, 1, "shared")]
    assert read(work, evidence.proposal_id).json() == before
    retried = post(work, command)
    assert retried.status_code == 200, retried.text
    assert source_rows(work, evidence.proposal_id) == evidence.before_sources
    assert_human_item_unchanged(work, evidence)
