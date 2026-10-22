"""Actual RLS/BoundHost comparison drafts; root alone runs the verified test DB.

Business material is created through human commands. Model replies are synthetic
completed ledger rows; no provider is called and no skill qualification is inserted.
"""
# ruff: noqa: F811 -- pytest injects the explicitly imported real G0 fixture.

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from pdos_next.agent_kernel import m3_spec_compare
from pdos_next.agent_kernel.bindings import ModelBinding, execution_key
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.deterministic_proofs import resolve_compute_proof
from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.m3_calculators import ENGINES
from pdos_next.agent_kernel.models import AgentToolCall, TenantSkillEnablement
from pdos_next.agent_kernel.read_execution import ReadBinding, ReadSource
from pdos_next.errors import DomainError
from pdos_next.service import digest
from tests.agent_kernel.test_transactions import run as create_read_run
from tests.g0_fixture import create_g0_project
from tests.preproject.test_category_context_pg import add_knowledge, publish
from tests.preproject.test_evidence_commands_pg import (
    artifact,
    record_claim,
    share_request,
    withdraw_request,
)
from tests.preproject.test_g0 import create, post, read, request, save
from tests.preproject.test_g0 import work as work
from tests.products import test_definition_transactions as definitions

TOOL = "calc.spec_compare"


def comparison(work, subjects, *, proposal_id=None, private_context=False, read_sources=()):
    """Real Run, ordinary model ledger, real production Bootstrap composition."""
    store, scope = create_read_run(
        work,
        proposal_id=UUID(proposal_id) if proposal_id else None,
        private_context=private_context,
        read_sources=read_sources,
    )
    bootstrap = Bootstrap(work.engine)
    route = SimpleNamespace(version="synthetic-spec-read@1", digest=digest("synthetic route"))
    bootstrap.route = lambda *_: route
    binding = ModelBinding(
        model_version=route.version,
        model_route_digest=route.digest,
        tool_definitions_digest=digest(bootstrap.registry.definitions()),
        prompt_digest=digest("synthetic comparison prefix"),
        isolation="main",
        cancel_epoch=scope.cancel_epoch,
        loaded_skills=(),
    )
    with store.transaction(scope) as (session, run):
        run.state = "running"
        run.versions = {
            "model_version": route.version,
            "model_route_digest": route.digest,
            "tool_definitions": {"main": binding.tool_definitions_digest},
            "prompt_prefixes": {"main": binding.prompt_digest},
        }
        assert session.scalar(select(func.count()).select_from(TenantSkillEnablement)) == 0
    arguments = {"subjects": subjects, "parameter_ids": []}
    model_id, _ = store.claim(
        scope,
        "synthetic-spec-model:" + str(uuid4()),
        "model",
        {"fixture": "no provider invocation"},
        execution_binding=binding.model_dump(mode="json"),
    )
    store.settle(scope, model_id, result={"calls": [{"name": TOOL, "arguments": arguments}]})
    adapters = bootstrap.adapters()
    assert TOOL in adapters.read_tools and TOOL in adapters.read_restores
    assert TOOL not in adapters.compute_engines
    return SimpleNamespace(
        work=work,
        store=store,
        scope=scope,
        host=BoundHost(store, adapters),
        spec=bootstrap.registry.get(TOOL),
        arguments=arguments,
        ctx=bootstrap.commands.context(scope),
        source=ReadSource(model_call_id=model_id, response_index=0),
        key=execution_key(scope.run_id, model_id, 0),
    )


def invoke(f):
    return f.host.read(f.scope, f.spec, f.arguments, f.key, source=f.source)


def subject(kind, identity):
    return {"type": kind, "id": str(identity)}


def public_proposal(work):
    identity, _ = create(work)
    save(work, share_request(work, identity))
    return identity


def test_actual_bound_comparison_is_ordinary_read_without_computed_claim_authority(work):
    identity = public_proposal(work)
    f = comparison(work, [subject("proposal", identity)], proposal_id=identity)
    result = invoke(f)
    assert result["subjects"][0]["id"] == identity
    assert result["execution_ref"]["read_kind"] == "ordinary/v1"
    assert invoke(f) == result
    call_id = UUID(result["execution_ref"]["call_id"])
    with f.store.transaction(f.scope) as (session, run):
        call = session.get(AgentToolCall, call_id)
        actual = ReadBinding.model_validate(call.execution_binding)
        assert call.state == "completed" and call.receipt_id is None
        assert actual.read_kind == "ordinary/v1" and actual.tool == TOOL
        assert actual.model_call_id == f.source.model_call_id and actual.response_index == 0
        assert actual.run_id == run.id and actual.session_id == run.session_id
        assert actual.requester_id == work.human and actual.writer_id == work.agent
        assert actual.engine_version is None and actual.result_digest is None
        assert call.input_digest == digest([TOOL, f.arguments])
        assert call.result == {k: v for k, v in result.items() if k != "execution_ref"}
        assert session.scalar(select(func.count()).select_from(TenantSkillEnablement)) == 0
        with pytest.raises(DomainError) as denied:
            resolve_compute_proof(
                session,
                f.ctx,
                run,
                {"call_id": str(call.id), "result_path": ["subjects", 0]},
                result["subjects"][0],
                engines=ENGINES,
            )
        assert denied.value.code == "SOURCE_UNAVAILABLE"
        assert denied.value.detail["reason"] == "compute_binding_invalid"


@pytest.mark.parametrize("private_kind", ["product", "proposal", "source"])
def test_actual_private_objects_stop_before_comparison_or_source_projection(
    work, monkeypatch, private_kind
):
    if private_kind == "product":
        project = create_g0_project(work, visibility="private")
        f = comparison(work, [subject("product", project.product_id)])
    elif private_kind == "proposal":
        identity, _ = create(work)
        f = comparison(
            work, [subject("proposal", identity)], proposal_id=identity, private_context=True
        )
    else:
        source = artifact(work, visibility="private")
        identity = public_proposal(work)
        f = comparison(
            work,
            [subject("proposal", identity)],
            proposal_id=identity,
            private_context=True,
            read_sources=[
                {"artifact_id": str(source), "expected_revision": 1, "product_id": None}
            ],
        )

    def forbidden_body(*_args, **_kwargs):
        pytest.fail("Private content must not reach a domain/body projection")

    original_sources = m3_spec_compare._public_sources

    def no_private_sources(session, ctx, refs):
        refs = list(refs)
        assert not refs, "Private source must be denied before its body resolver"
        return original_sources(session, ctx, refs)

    # These spies do not supply authorization or substitute a read result.
    monkeypatch.setattr(m3_spec_compare.spec_compare, "compare", forbidden_body)
    monkeypatch.setattr(m3_spec_compare.views, "read", forbidden_body)
    monkeypatch.setattr(m3_spec_compare, "_public_sources", no_private_sources)
    with pytest.raises(DomainError) as denied:
        invoke(f)
    assert denied.value.code == "SOURCE_UNAVAILABLE"
    with f.store.transaction(f.scope) as (session, _):
        calls = list(session.scalars(select(AgentToolCall).where(
            AgentToolCall.run_id == f.scope.run_id, AgentToolCall.tool == TOOL,
        )))
        assert calls and all(call.state != "completed" and call.result is None for call in calls)


def test_actual_g0_baseline_ignores_unselected_private_definition_history(work):
    project = create_g0_project(work, visibility="category")
    source = definitions.source(work, visibility="private")
    draft = definitions.post(
        work,
        definitions.command(
            work,
            "product.definition.draft",
            definitions.payload(
                source,
                parent_definition_id=project.definition_id,
                expected_parent_revision=1,
                title="Unselected private next draft",
            ),
            source,
        ),
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["subject_id"] != project.definition_id
    f = comparison(work, [subject("product", project.product_id)])
    result = invoke(f)
    chosen = result["subjects"][0]
    assert chosen["baseline_kind"] == "g0"
    assert chosen["definition_id"] == project.definition_id
    assert chosen["definition_revision"] == 1
    assert "Unselected private next draft" not in str(result)
    assert "Pressure: 150 PSI" not in str(result)


def test_actual_claim_withdrawal_invalidates_completed_comparison_recovery(work):
    parameter = publish(work, standard_condition="one meter")
    source = artifact(work)
    claim = record_claim(work, source)
    ref = {"type": "claim", "id": claim["subject_id"], "version": 1}
    entry = add_knowledge(
        work,
        kind="competitor",
        source_refs=[ref],
        content={
            "brand": "Synthetic",
            "model": "Actual comparison source",
            "metrics": [{
                "parameter_id": parameter["parameter_id"],
                "parameter_version": 1,
                "unit": "dB",
                "condition_note": "one meter",
                "value": "0",
                "nature": "measured",
                "source_ref": ref,
            }],
        },
    )
    f = comparison(work, [subject("competitor", entry["entry_id"])])
    first = invoke(f)
    assert first["groups"][0]["observations"][0]["value"] == "0"
    save(work, withdraw_request(work, claim["subject_id"]))
    with pytest.raises(DomainError) as denied:
        invoke(f)
    assert denied.value.code == "SOURCE_UNAVAILABLE"
    with f.store.transaction(f.scope) as (session, _):
        call = session.get(AgentToolCall, UUID(first["execution_ref"]["call_id"]))
        assert call.state == "completed" and call.result["groups"] == first["groups"]


def test_actual_public_document_change_rejects_old_read_without_overwriting_receipt(work):
    identity = public_proposal(work)
    f = comparison(work, [subject("proposal", identity)], proposal_id=identity)
    first = invoke(f)
    row = read(work, identity).json()
    item = next(item for item in row["items"] if item["kind"] == "section")
    content = deepcopy(item["content"])
    content["text"] = "Named human changed the actual comparison document"
    response = post(work, request(work, "proposal.item.patch", {
        "proposal_id": identity,
        "ops": [{
            "kind": item["kind"], "item_id": item["item_id"],
            "base_version": item["version"], "content": content,
        }],
    }, revision=row["revision"]))
    assert response.status_code == 200, response.text
    with pytest.raises(DomainError) as denied:
        invoke(f)
    assert denied.value.code == "SOURCE_STALE"
    with f.store.transaction(f.scope) as (session, _):
        call = session.get(AgentToolCall, UUID(first["execution_ref"]["call_id"]))
        assert call.state == "completed"
        assert call.result["input_digest"] == first["input_digest"]
