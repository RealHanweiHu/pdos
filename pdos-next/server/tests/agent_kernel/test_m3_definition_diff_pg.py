"""Actual Bootstrap/BoundHost definition reads; root alone runs isolated PG.

Only completed synthetic model ledger calls are supplied. No model, worker or
qualification is invoked. Business drafts and patches use actual human commands;
the explicitly labelled old-publication fixture retains its established meaning.
"""
# ruff: noqa: F811 -- pytest injects the explicitly imported fixture.

from copy import copy, deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from pdos_next.agent_kernel import m3_definition_diff
from pdos_next.agent_kernel.bindings import ModelBinding, execution_key
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.deterministic_proofs import resolve_compute_proof
from pdos_next.agent_kernel.domain_reads import DomainReads
from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.m3_calculators import ENGINES
from pdos_next.agent_kernel.models import AgentToolCall, TenantSkillEnablement
from pdos_next.agent_kernel.read_execution import ReadBinding, ReadSource
from pdos_next.domain.preproject.baseline import publication_digest
from pdos_next.domain.products.definitions import definition_view
from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, ObjectAudience, Product
from pdos_next.service import digest
from tests.agent_kernel.test_transactions import human_session
from tests.agent_kernel.test_transactions import run as create_read_run
from tests.g0_fixture import create_g0_project
from tests.preproject.test_derivation_transactions import (
    definition_reads,
    derivative_payload,
    reviewer_session,
    synthetic_owner,
    synthetic_parent,
    typed_private_parent,
)
from tests.preproject.test_evidence_commands_pg import share_request
from tests.preproject.test_g0 import create, read, save
from tests.preproject.test_g0 import work as work
from tests.products import test_definition_transactions as definitions
from tests.products.test_definition_inherit_pg import inherit
from tests.products.test_definition_item_commands_pg import current_items, patch, upsert

TOOL = "calc.derivation_diff"


def reader(work, arguments, *, proposal_id=None, product_bound=False, tool=TOOL):
    store, scope = create_read_run(
        work,
        proposal_id=UUID(proposal_id) if proposal_id else None,
        **({"product_id": work.product} if product_bound else {}),
    )
    bootstrap = Bootstrap(work.engine)
    route = SimpleNamespace(version="synthetic-diff-read@1", digest=digest("synthetic diff route"))
    bootstrap.route = lambda *_: route
    binding = ModelBinding(
        model_version=route.version,
        model_route_digest=route.digest,
        tool_definitions_digest=digest(bootstrap.registry.definitions()),
        prompt_digest=digest("synthetic diff prefix"),
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
    model_id, _ = store.claim(
        scope,
        "synthetic-diff-model:" + str(uuid4()),
        "model",
        {"fixture": "no provider invocation"},
        execution_binding=binding.model_dump(mode="json"),
    )
    store.settle(scope, model_id, result={"calls": [{"name": tool, "arguments": arguments}]})
    adapters = bootstrap.adapters()
    assert tool in adapters.read_tools and tool in adapters.read_restores
    assert tool not in adapters.compute_engines
    return SimpleNamespace(
        store=store,
        scope=scope,
        bootstrap=bootstrap,
        host=BoundHost(store, adapters),
        spec=bootstrap.registry.get(tool),
        arguments=arguments,
        ctx=bootstrap.commands.context(scope),
        source=ReadSource(model_call_id=model_id, response_index=0),
        key=execution_key(scope.run_id, model_id, 0),
    )


def invoke(f):
    return f.host.read(f.scope, f.spec, f.arguments, f.key, source=f.source)


def fixed(work, identity, revision):
    return {
        "product_id": str(work.product),
        "definition_id": str(identity),
        "definition_revision": revision,
        "variant_id": None,
    }


def accepted(work, command):
    response = definitions.post(work, command)
    assert response.status_code == 200, response.text
    return UUID(response.json()["subject_id"])


def values(work, identity, **changes):
    rows = current_items(work, identity)
    ops = []
    for key, value in changes.items():
        op = upsert(
            rows.get(key),
            key=key,
            value=str(value),
            unit="PSI",
            availability="known",
            item_status="confirmed",
            nature="decided",
            reason="合成人工目标",
            test_conditions=["固定合成条件"],
        )
        op["source_refs"] = [
            {
                "type": "human",
                "id": str(work.human),
                "version": 1,
                "statement": "本人确认的合成目标，非测量结果",
            }
        ]
        ops.append(op)
    accepted(work, patch(work, identity, *ops))


def three_way(work, *, visibility="category"):
    artifact_id = definitions.source(work, visibility="category")
    old = accepted(
        work,
        definitions.command(
            work,
            "product.definition.draft",
            definitions.payload(artifact_id, visibility=visibility),
            artifact_id,
        ),
    )
    values(work, old, child_only=0, conflict=0, parent_only=0)
    child = accepted(work, inherit(work, old))
    values(work, child, child_only=1, conflict=2)
    new = accepted(work, inherit(work, child, revision=2))
    # The third actual version provides the incoming contents. Restore the
    # child-only field to the old value; keep independent and conflicting edits.
    values(work, new, child_only=0, conflict=3, parent_only=1)
    return SimpleNamespace(
        old=old,
        new=new,
        child=child,
        artifact_id=artifact_id,
        arguments={
            "three_way": {
                "old_parent": fixed(work, old, 1),
                "new_parent": fixed(work, new, 3),
                "child": fixed(work, child, 2),
            }
        },
    )


def test_actual_three_way_tool_is_ordinary_read_and_cannot_authorize_computed_claim(work):
    chain = three_way(work)
    f = reader(work, chain.arguments)
    result = invoke(f)
    classes = {row["path"]: row["classification"] for row in result["differences"]}
    assert classes["specs/child_only"] == "child_only"
    assert classes["specs/parent_only"] == "parent_only"
    assert classes["specs/conflict"] == "conflict"
    assert result["old_parent"]["definition_id"] == str(chain.old)
    assert result["new_parent"]["definition_id"] == str(chain.new)
    assert result["child"]["definition_id"] == str(chain.child)
    assert result["unavailable_blocks"] == ["bom", "certification", "tooling"]
    assert result["execution_ref"]["read_kind"] == "ordinary/v1"
    assert invoke(f) == result
    with f.store.transaction(f.scope) as (session, run):
        call = session.get(AgentToolCall, UUID(result["execution_ref"]["call_id"]))
        binding = ReadBinding.model_validate(call.execution_binding)
        assert call.state == "completed" and call.receipt_id is None
        assert binding.read_kind == "ordinary/v1" and binding.tool == TOOL
        assert binding.model_call_id == f.source.model_call_id and binding.response_index == 0
        assert binding.run_id == run.id and binding.session_id == run.session_id
        assert binding.requester_id == work.human and binding.writer_id == work.agent
        assert binding.engine_version is None and binding.result_digest is None
        assert call.input_digest == digest([TOOL, f.arguments])
        assert call.result == {
            key: value for key, value in result.items() if key != "execution_ref"
        }
        with pytest.raises(DomainError) as denied:
            resolve_compute_proof(
                session,
                f.ctx,
                run,
                {"call_id": str(call.id), "result_path": ["differences", 0]},
                result["differences"][0],
                engines=ENGINES,
            )
        assert denied.value.code == "SOURCE_UNAVAILABLE"
        assert denied.value.detail["reason"] == "compute_binding_invalid"


@pytest.mark.parametrize("next_value", [1, 5], ids=["same-content-new-item-version", "new-content"])
def test_completed_diff_restores_reauthorize_full_item_versions_without_freezing_draft(
    work,
    next_value,
):
    chain = three_way(work)
    f = reader(work, chain.arguments)
    first = invoke(f)
    before = current_items(work, chain.new)["parent_only"]
    values(work, chain.new, parent_only=next_value)
    after = current_items(work, chain.new)["parent_only"]
    assert after.item_version == before.item_version + 1
    with pytest.raises(DomainError) as denied:
        invoke(f)
    assert denied.value.code == "SOURCE_STALE"
    fresh = invoke(reader(work, chain.arguments))
    assert fresh["request_digest"] != first["request_digest"]
    if next_value == 1:
        assert {row["path"]: row["classification"] for row in fresh["differences"]} == {
            row["path"]: row["classification"] for row in first["differences"]
        }
    with human_session(work) as session:
        views = [
            definition_view(session, work.ctx, session.get(DefinitionRevision, identity))
            for identity in (chain.old, chain.new, chain.child)
        ]
    watermark = next(item for item in views[1]["item_versions"] if item["key"] == "parent_only")
    assert watermark["item_version"] == after.item_version
    assert watermark["row_id"] == str(after.id)
    assert fresh["request_digest"] == digest(
        {
            "inputs": m3_definition_diff.DefinitionDiffInput.model_validate(
                chain.arguments
            ).model_dump(mode="json"),
            "views": views,
        }
    )
    with f.store.transaction(f.scope) as (session, _):
        call = session.get(AgentToolCall, UUID(first["execution_ref"]["call_id"]))
        assert (
            call.state == "completed" and call.result["request_digest"] == first["request_digest"]
        )


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("definition_revision", 999, "VERSION_CONFLICT"),
        ("variant_id", "00000000-0000-0000-0000-000000000001", "VERSION_CONFLICT"),
        ("product_id", "00000000-0000-0000-0000-000000000001", "FORBIDDEN_SCOPE"),
    ],
)
def test_fixed_definition_identity_mismatch_never_rebinds_to_another_current_row(
    work,
    field,
    value,
    code,
):
    chain = three_way(work)
    arguments = deepcopy(chain.arguments)
    arguments["three_way"]["old_parent"][field] = value
    f = reader(work, arguments, product_bound=True)
    with pytest.raises(DomainError) as denied:
        invoke(f)
    assert denied.value.code == code


@pytest.mark.parametrize("private_kind", ["definition", "nested_source"])
def test_private_header_or_current_nested_source_stops_before_definition_body(
    work,
    monkeypatch,
    private_kind,
):
    if private_kind == "nested_source":
        parent, source_id, _, copied_value = typed_private_parent(work)
        with synthetic_owner(work) as session:
            audience = ObjectAudience(
                id=uuid4(),
                tenant_id=work.tenant,
                category_id=work.category,
                object_type="artifact_versions",
                subject_id=source_id,
                owner_id=work.human,
                principal_id=work.peer,
            )
            audience_id = audience.id
            session.add(audience)
        baseline, listed, fixed_view = definition_reads(work, parent, actor=work.peer)
        assert baseline.status_code == listed.status_code == fixed_view.status_code == 200
        assert copied_value in listed.text and copied_value in fixed_view.text
        # Revoke an actual audience in the owner-only synthetic fixture;
        # the immutable Artifact remains unchanged.
        with synthetic_owner(work) as session:
            session.delete(session.get(ObjectAudience, audience_id))
        with reviewer_session(work) as session:
            assert session.get(Artifact, source_id) is None
            assert session.get(Product, parent.product_id) is not None
        peer = copy(work)
        peer.human = work.peer
        peer.ctx = work.ctx.__class__(work.tenant, work.peer, work.peer, category_id=work.category)
        peer.headers = {"Authorization": f"Bearer {work.tokens[work.peer]}"}
        arguments = {
            "baseline": fixed(work, parent.id, parent.revision),
            "proposed": fixed(work, parent.id, parent.revision),
        }
        f = reader(peer, arguments)
    else:
        chain = three_way(work, visibility="private")
        f = reader(work, chain.arguments)

    def forbidden_body(*_args, **_kwargs):
        pytest.fail("Private definition/source reached the full definition body")

    monkeypatch.setattr(m3_definition_diff.definitions, "definition_view", forbidden_body)
    with pytest.raises(DomainError) as denied:
        invoke(f)
    assert denied.value.code == "SOURCE_UNAVAILABLE", (str(denied.value), denied.value.detail)
    with f.store.transaction(f.scope) as (session, _):
        calls = session.scalars(
            select(AgentToolCall).where(
                AgentToolCall.run_id == f.scope.run_id,
                AgentToolCall.tool == TOOL,
            )
        ).all()
        assert calls and all(call.state != "completed" and call.result is None for call in calls)


@pytest.mark.parametrize("baseline_kind", ["g0", "published"])
def test_g0_and_old_published_baseline_keep_fixed_dto_and_digest(work, baseline_kind):
    if baseline_kind == "g0":
        project = create_g0_project(work, visibility="category")
        parent_id = UUID(project.definition_id)
    else:
        parent_id = synthetic_parent(work).id
    with human_session(work) as session:
        parent = session.get(DefinitionRevision, parent_id)
        before = definition_view(session, work.ctx, parent)
        before_digest = publication_digest(before)
    child_id = accepted(work, inherit(work, parent_id))
    values(work, child_id, added=0)
    arguments = {
        "baseline": fixed(work, parent_id, 1),
        "proposed": fixed(work, child_id, 2),
    }
    f = reader(work, arguments)
    result = invoke(f)
    assert result["old_parent"]["definition_id"] == str(parent_id)
    assert result["new_parent"] == result["old_parent"]
    assert result["child"]["definition_id"] == str(child_id)
    assert any(
        item["path"] == "specs/added" and item["classification"] == "child_only"
        for item in result["differences"]
    )
    assert invoke(f) == result
    with human_session(work) as session:
        after = definition_view(session, work.ctx, session.get(DefinitionRevision, parent_id))
        assert after == before and publication_digest(after) == before_digest


def test_actual_legacy_proposal_mode_keeps_original_derivation_result(work):
    parent = synthetic_parent(work)
    proposal_id, _ = create(work, derivative_payload(work, parent))
    save(work, share_request(work, proposal_id))
    row = read(work, proposal_id).json()
    arguments = {
        "baseline": {
            "product_id": str(work.product),
            "definition_id": str(parent.id),
            "definition_revision": parent.revision,
        },
        "proposed": {"proposal_id": proposal_id, "revision": row["revision"]},
        "areas": ["specification"],
    }
    f = reader(work, arguments, proposal_id=proposal_id)
    result = invoke(f)
    original = DomainReads(f.store, f.bootstrap.commands).call(f.scope, arguments, name=TOOL)
    assert {key: value for key, value in result.items() if key != "execution_ref"} == original
    assert invoke(f) == result
    assert result["execution_ref"]["read_kind"] == "ordinary/v1"
