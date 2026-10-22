"""Frozen SQL checks and root-run PostgreSQL probes for signed nested consumption."""
# ruff: noqa: F811 -- explicit shared PG fixture export

import hashlib
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from migrations import schema_s0_0750 as migration
from pdos_next.domain.preproject.schemas import Reference
from pdos_next.models import Consumption
from tests.preproject.test_evidence_commands_pg import (
    artifact,
    human_session,
    record_claim,
    withdraw_request,
)
from tests.preproject.test_g0 import create, decide_request, payload, post, request, save, submit
from tests.preproject.test_g0 import work as work  # noqa: F401
from tests.preproject.test_material_commands_pg import parameter


def test_consumption_authority_and_same_transaction_checks_are_literal_predecessor():
    boundary = " -- The queue is derived only"
    predecessor_boundary = " IF NOT EXISTS(SELECT 1 FROM (\n"
    assert (
        migration.CONSUMPTION_ATOM.split(boundary)[0]
        == (migration.PREDECESSOR_CONSUMPTION_ATOM.split(predecessor_boundary)[0])
    )
    assert "sub.frozen_document->'baseline_claim_refs'" in migration.CONSUMPTION_ATOM
    assert "(ref->>'version')::integer=NEW.claim_version" in migration.CONSUMPTION_ATOM
    assert "refs IS NULL OR NOT EXISTS" in migration.CONSUMPTION_ATOM


def test_private_graph_contract_has_no_generic_content_or_uuid_traversal():
    sql = migration.REFERENCE_GRAPH
    assert "knowledge.kind='voice'" in sql and "knowledge.kind='competitor'" in sql
    for key in ("representative_refs", "metrics", "features", "prices"):
        assert f"knowledge.content->'{key}'" in sql
    assert "knowledge.version=(ref->>'version')::integer" in sql
    assert "d.revision=(ref->>'version')::integer" in sql
    assert "path ? token" in sql
    assert "jsonb_each" not in sql
    assert "SET search_path TO 'pg_catalog', 'public', 'pg_temp'" in sql
    assert migration.SCHEMA_SQL[-1] == (
        "REVOKE ALL ON FUNCTION public.m3_reference_graph(uuid,uuid,jsonb) "
        "FROM PUBLIC,pdos_next_app,pdos_next_auth,pdos_next_dispatch,pdos_agent"
    )


def test_down_restores_frozen_actual_predecessor_and_drops_only_new_helper():
    assert migration.DOWNGRADE_SQL == (
        migration.PREDECESSOR_CONSUMPTION_ATOM,
        migration.PREDECESSOR_BASELINE_GRAPH,
        "DROP FUNCTION public.m3_reference_graph(uuid,uuid,jsonb)",
    )
    # Actual pg_get_functiondef bytes captured from the verified pre-0750 head.
    assert (
        hashlib.sha256(migration.PREDECESSOR_BASELINE_GRAPH.encode()).hexdigest()
        == "e696394c2acd33c626f692b689c06bea687f4b184eac6fc7ef212af0e00236c2"
    )
    assert (
        hashlib.sha256(migration.PREDECESSOR_CONSUMPTION_ATOM.encode()).hexdigest()
        == "0dc6b5231f2e31d806e443afdc2aaa3b775878d8d70177ce78f88188570e093b"
    )


def knowledge_with_claim(work, container, claim_id):
    reference = {"type": "claim", "id": claim_id, "version": 1}
    if container == "voice":
        body = {
            "kind": "voice",
            "content": {
                "label": "Synthetic reported observation",
                "source_platform": "Synthetic fixture",
                "representative_refs": [reference],
            },
        }
    else:
        item = {"source_ref": reference}
        if container in {"metrics", "features"}:
            parameter_input = parameter()
            registered, _ = save(work, request(work, "category.parameter.publish", parameter_input))
            item.update(
                parameter_id=registered["result"]["parameter_id"],
                parameter_version=1,
                unit=parameter_input["unit"],
                condition_note=parameter_input["standard_condition"],
                nature="unknown",
            )
        body = {
            "kind": "competitor",
            "content": {"brand": "Synthetic", "model": "Synthetic", container: [item]},
        }
    receipt, _ = save(work, request(work, "category.knowledge.add", body))
    return {"type": "knowledge", "id": receipt["result"]["entry_id"], "version": 1}


@pytest.mark.parametrize("container", ["voice", "metrics", "features", "prices"])
@pytest.mark.parametrize("item_kind", ["spec", "option"])
def test_pg_signed_nested_knowledge_consumption_blocks_claim_withdrawal(work, container, item_kind):
    source = artifact(work)
    claim = record_claim(work, source)
    knowledge_ref = knowledge_with_claim(work, container, claim["subject_id"])
    document = payload(work)
    item = next(item for item in document["groups"]["items"] if item["kind"] == item_kind)
    item["source_refs"] = [knowledge_ref]
    proposal_id, _ = create(work, document)
    submit(work, proposal_id)
    approved, _ = save(work, decide_request(work, proposal_id), actor=work.peer)
    with human_session(work) as session:
        consumed = session.scalar(
            select(Consumption).where(Consumption.claim_id == UUID(claim["subject_id"]))
        )
        assert consumed is not None and consumed.claim_version == 1
        assert str(consumed.receipt_id) == approved["id"]
        assert str(consumed.definition_id) == approved["result"]["definition_id"]
    denied = post(work, withdraw_request(work, claim["subject_id"]), preview=True)
    assert denied.status_code == 409, denied.text
    assert denied.json()["detail"]["reason"] == "consumed_by_decision"


def test_pg_graph_retains_exact_fixed_version_scope_and_private_acl(work):
    claim = record_claim(work, artifact(work))
    knowledge_ref = knowledge_with_claim(work, "prices", claim["subject_id"])
    statement = text("SELECT m3_reference_graph(:t,:c,CAST(:seeds AS jsonb))")
    with Session(work.admin) as session:
        args = {"t": work.tenant, "c": work.category, "seeds": json.dumps([knowledge_ref])}
        refs = session.scalar(statement, args)
        expected = Reference(type="claim", id=claim["subject_id"], version=1).model_dump(
            mode="json"
        )
        assert expected in refs
        assert session.scalar(statement, {**args, "c": uuid4()}) is None
        assert (
            session.scalar(
                statement, {**args, "seeds": json.dumps([{**knowledge_ref, "version": 2}])}
            )
            is None
        )
        for role in ("pdos_next_app", "pdos_next_auth", "pdos_next_dispatch", "pdos_agent"):
            assert (
                session.scalar(
                    text(
                        "SELECT has_function_privilege(:role,"
                        "'m3_reference_graph(uuid,uuid,jsonb)','EXECUTE')"
                    ),
                    {"role": role},
                )
                is False
            )


def test_pg_opaque_knowledge_material_does_not_make_unrelated_claim_reachable(work):
    claim = record_claim(work, artifact(work))
    receipt, _ = save(
        work,
        request(
            work,
            "category.knowledge.add",
            {
                "kind": "boundary",
                "content": {
                    "definition": "Synthetic boundary",
                    "material": {
                        "source_ref": {"type": "claim", "id": claim["subject_id"], "version": 1}
                    },
                },
            },
        ),
    )
    with Session(work.admin) as session:
        refs = session.scalar(
            text("SELECT m3_reference_graph(:t,:c,CAST(:seeds AS jsonb))"),
            {
                "t": work.tenant,
                "c": work.category,
                "seeds": json.dumps(
                    [{"type": "knowledge", "id": receipt["result"]["entry_id"], "version": 1}]
                ),
            },
        )
        assert not any(ref["type"] == "claim" for ref in refs)


def test_pg_unrelated_claim_cannot_be_injected_into_same_g0_transaction(work, monkeypatch):
    from pdos_next.domain.preproject import root_sources

    claim = record_claim(work, artifact(work))
    proposal_id, _ = create(work)
    submit(work, proposal_id)
    consume = root_sources.consume_claims

    def inject(s, ctx, refs, decision):
        consume(s, ctx, refs, decision)
        s.add(
            Consumption(
                tenant_id=ctx.tenant_id,
                category_id=ctx.category_id,
                product_id=decision.created_product_id,
                claim_id=UUID(claim["subject_id"]),
                claim_version=1,
                decision_id=decision.id,
                definition_id=decision.created_definition_id,
                receipt_id=decision.receipt_id,
                consumer_type="proposal_decision",
                consumer_id=decision.id,
            )
        )

    checked = post(work, decide_request(work, proposal_id), actor=work.peer, preview=True)
    assert checked.status_code == 200, checked.text
    monkeypatch.setattr(root_sources, "consume_claims", inject)
    denied = post(work, checked.json()["command"], actor=work.peer)
    assert denied.status_code == 422, denied.text
    with human_session(work) as session:
        assert (
            session.scalar(
                select(Consumption.id).where(Consumption.claim_id == UUID(claim["subject_id"]))
            )
            is None
        )
