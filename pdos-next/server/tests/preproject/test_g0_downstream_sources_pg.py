"""Real human G0 downstream source regression; root runs the verified PG target.

No source/definition/receipt rows are fabricated or rewritten. Only public human
commands build the chain; no model call, T0 qualification or manufacturing issuer
is needed to exercise the first-plan and engineering-configuration boundaries.
"""
# ruff: noqa: F811 -- pytest injects the explicitly imported real G0 fixture.

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest
from security_fixture import secured_parse
from sqlalchemy import func, select
from test_durable_evidence import upload_input

from pdos_next.domain.configurations.models import EngineeringConfiguration
from pdos_next.domain.preproject.evidence_models import ClaimWithdrawal
from pdos_next.domain.preproject.schemas import Reference
from pdos_next.domain.products.models import DefinitionSource, DefinitionSpecRow
from pdos_next.domain.projects.models import PlanRevision, Project, ProjectTask, ProjectWorkPackage
from pdos_next.models import Artifact, Claim, Confirmation, Consumption, OriginalSecurity, Receipt
from pdos_next.service import digest
from tests.agent_kernel.test_transactions import human_session
from tests.preproject.test_category_context_pg import add_knowledge
from tests.preproject.test_evidence_commands_pg import (
    evidence_request,
    record_claim,
    withdraw_request,
)
from tests.preproject.test_g0 import create, decide_request, payload, save, submit
from tests.preproject.test_g0 import work as work
from tests.test_configurations import accepted, bom_payload, command, post
from tests.test_original_security import security_work as security_work
from tests.test_project_first_plan import application, proposal_command


def parsed_category_source(work, security_work):
    # Real upload and parser with the explicit synthetic scanner test port. This
    # establishes a withdrawable original; native registered text has no such API.
    response = security_work.client.post(
        f"/v1/categories/{work.category}/originals",
        headers=work.headers,
        json=upload_input(
            b"Synthetic exact public source\n", visibility="category"
        ).model_dump(mode="json"),
    )
    assert response.status_code == 200, response.text
    original_id = UUID(response.json()["subject_id"])
    parsed = secured_parse(work.engine, {
        "tenant_id": str(work.tenant), "category_id": str(work.category),
        "product_id": None, "actor_id": str(work.human),
        "requester_id": str(work.human), "subject_id": str(original_id),
    }, security_work.store)
    assert parsed["status"] == "parsed", parsed
    with human_session(work) as session:
        source_id = session.scalar(select(Artifact.id).where(Artifact.original_id == original_id))
        assert source_id is not None
    return original_id, source_id


def claim_only_project(work, security_work, *, nested):
    original_id, source_id = parsed_category_source(work, security_work)
    claim = record_claim(work, source_id)
    claim_ref = {"type": "claim", "id": claim["subject_id"], "version": 1}
    fixed_ref = claim_ref
    if nested:
        # Only the schema-declared nested price reference retains this Claim.
        # Top-level knowledge.source_refs and DefinitionSource both remain empty.
        entry = add_knowledge(
            work,
            kind="competitor",
            source_refs=[],
            content={
                "brand": "Synthetic observed brand",
                "model": "Synthetic priced model",
                "prices": [{
                    "amount": "19.5", "currency": "CNY", "price_type": "retail",
                    "observed_on": "2026-10-10", "source_ref": claim_ref,
                }],
            },
        )
        fixed_ref = {"type": "knowledge", "id": entry["entry_id"], "version": 1}
    body = payload(work)
    spec = next(
        item for item in body["groups"]["items"]
        if item["kind"] == "spec" and item["content"]["key"] == "display"
    )
    spec["source_refs"] = [fixed_ref]
    proposal_id, _ = create(work, body)
    submit(work, proposal_id)
    decision = decide_request(work, proposal_id)
    decision["payload"]["project"]["owner_id"] = str(work.human)
    receipt, _ = save(work, decision, actor=work.peer)
    result = receipt["result"]
    work.product = UUID(result["product_id"])
    with human_session(work) as session:
        assert session.scalar(select(func.count()).select_from(DefinitionSource).where(
            DefinitionSource.definition_id == UUID(result["definition_id"]),
        )) == 0
        stored_spec = session.scalar(select(DefinitionSpecRow).where(
            DefinitionSpecRow.definition_id == UUID(result["definition_id"]),
            DefinitionSpecRow.key == "display",
        ))
        assert stored_spec.source_refs == [
            Reference.model_validate(fixed_ref).model_dump(mode="json")
        ]
        actual_project = session.get(Project, UUID(result["project_id"]))
        assert actual_project.owner_id == work.human and actual_project.g0_decision_id is not None
        consumed = session.scalars(select(Consumption).where(
            Consumption.claim_id == UUID(claim["subject_id"]),
        )).all()
        assert len(consumed) == 1
        assert consumed[0].claim_version == 1
        assert consumed[0].consumer_type == "proposal_decision"
        assert consumed[0].consumer_id == consumed[0].decision_id == actual_project.g0_decision_id
        assert str(consumed[0].definition_id) == result["definition_id"]
        assert str(consumed[0].receipt_id) == receipt["id"]
        assert consumed[0].product_id == work.product
    return SimpleNamespace(
        claim_id=claim["subject_id"], proposal_id=proposal_id,
        definition_id=result["definition_id"], project_id=result["project_id"],
        original_id=original_id, source_id=source_id,
    )


def prepare_consumers(work, g0):
    # No Artifact is smuggled into the already sealed G0 definition. The plan's
    # source set really is empty; its typed source closure lives in the definition.
    definition = (None, g0.definition_id)
    proposed = post(work, proposal_command(work, definition, g0.project_id))
    assert proposed.status_code == 200, proposed.text
    plan = application(work, definition, g0.project_id, proposed.json()["subject_id"])
    assert plan["source_read_set"] == []
    plan_preview = post(work, plan, preview=True)
    assert plan_preview.status_code == 200, plan_preview.text

    # Configuration owns a distinct operational source, which stays active after
    # the G0 Claim's original is withdrawn. Checking only the configuration's
    # own Artifact inputs therefore cannot catch the stale fixed definition.
    text = "Synthetic independent BOM and engineering source"
    registered = post(work, command(work, "evidence.artifact.register", {
        "title": "Synthetic engineering preparation",
        "source_label": "Isolated human regression", "content": text, "visibility": "private",
    }, []))
    assert registered.status_code == 200, registered.text
    ref = {
        "artifact_id": registered.json()["subject_id"], "expected_revision": 1,
        "line": 1, "quote": text,
    }
    reads = [{"artifact_id": ref["artifact_id"], "expected_revision": 1}]
    bom, _, _ = accepted(work, command(work, "engineering.bom.revise", bom_payload(ref), reads))
    engineering = command(work, "engineering.configuration.create", {
        "name": "Typed G0 source consumer", "reason": "Pin actual G0 and independent BOM",
        "sources": [ref], "visibility": "private", "definition_id": g0.definition_id,
        "expected_definition_revision": 1, "bom_id": bom["subject_id"],
        "expected_bom_revision": 1,
    }, reads)
    engineering_preview = post(work, engineering, preview=True)
    assert engineering_preview.status_code == 200, engineering_preview.text
    return [
        (plan, plan_preview.json()["command"]),
        (engineering, engineering_preview.json()["command"]),
    ]


def effect_counts(work):
    with human_session(work) as session:
        return tuple(session.scalar(select(func.count()).select_from(model)) for model in (
            PlanRevision, ProjectWorkPackage, ProjectTask, EngineeringConfiguration, Receipt,
        ))


def historical_reads(work, g0):
    root = f"/v1/categories/{work.category}/products/{work.product}"
    definitions = work.client.get(root + "/definitions", headers=work.headers)
    assert definitions.status_code == 200, definitions.text
    fixed = next(item for item in definitions.json()["items"] if item["id"] == g0.definition_id)
    assert fixed["sealed"] is True and fixed["revision"] == 1 and fixed["sources"] == []
    assert any(spec["source_refs"] for spec in fixed["specs"])
    projects = work.client.get(root + "/projects", headers=work.headers)
    assert projects.status_code == 200, projects.text
    project = next(item for item in projects.json()["items"] if item["id"] == g0.project_id)
    assert project["definition"]["id"] == g0.definition_id
    assert project["plan"] is None


@pytest.mark.parametrize("nested", [False, True], ids=["claim-only", "nested-knowledge-claim"])
def test_withdrawn_g0_source_blocks_new_consumers_but_keeps_actual_history_readable(
    work, security_work, nested,
):
    g0 = claim_only_project(work, security_work, nested=nested)
    consumers = prepare_consumers(work, g0)
    historical_reads(work, g0)

    # G0 permanently records both direct and schema-declared indirect Claim
    # consumption. A named user cannot undo that signed evidence fact.
    before = effect_counts(work)
    with human_session(work) as session:
        confirmations_before = session.scalar(select(func.count()).select_from(Confirmation))
    rejected_withdrawal = post(work, withdraw_request(work, g0.claim_id), preview=True)
    assert rejected_withdrawal.status_code == 409, rejected_withdrawal.text
    assert rejected_withdrawal.json()["code"] == "UNDO_BLOCKED_BY_DEPENDENCY"
    assert rejected_withdrawal.json()["detail"]["reason"] == "consumed_by_decision"
    assert effect_counts(work) == before
    with human_session(work) as session:
        claim = session.get(Claim, UUID(g0.claim_id))
        assert claim.status == "active" and claim.revision == 1
        assert session.scalar(select(func.count()).select_from(ClaimWithdrawal).where(
            ClaimWithdrawal.claim_id == claim.id,
        )) == 0
        assert (
            session.scalar(select(func.count()).select_from(Confirmation)) == confirmations_before
        )
        state = session.scalar(select(OriginalSecurity).where(
            OriginalSecurity.original_id == g0.original_id,
        ))
        assert state.source_state == "active"
        epoch = state.epoch

    # Original withdrawal is a separate, supported action: preserve the signed
    # Claim and history while prohibiting fresh use of its underlying source.
    save(work, evidence_request(work, "evidence.original.withdraw", {
        "original_id": str(g0.original_id), "expected_epoch": epoch,
        "reason": "Synthetic original is no longer usable for new work",
    }))
    with human_session(work) as session:
        source = session.get(Artifact, g0.source_id)
        assert source.status == "withdrawn" and source.content
        claim = session.get(Claim, UUID(g0.claim_id))
        assert claim.status == "active" and claim.revision == 1
    before = effect_counts(work)
    for unconfirmed, confirmed in consumers:
        rejected_preview = post(work, deepcopy(unconfirmed), preview=True)
        assert rejected_preview.status_code == 409, rejected_preview.text
        assert rejected_preview.json()["code"] == "SOURCE_UNAVAILABLE"
        # A real confirmation obtained while the source was valid cannot retain
        # permission to consume that source after its withdrawal.
        rejected_apply = post(work, deepcopy(confirmed))
        assert rejected_apply.status_code == 409, rejected_apply.text
        assert rejected_apply.json()["code"] == "SOURCE_UNAVAILABLE"
        with human_session(work) as session:
            proof = session.scalar(select(Confirmation).where(
                Confirmation.token_hash == digest(confirmed["payload"]["confirmation_token"]),
            ))
            assert proof is not None and proof.consumed is False
    assert effect_counts(work) == before
    historical_reads(work, g0)
