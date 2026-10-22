"""Actual bound proposals vs shared model/competitor; synthetic model ledger only."""
# ruff: noqa: F811 -- explicitly imported marked PG fixtures

import json
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel import m3_spec_compare
from pdos_next.agent_kernel.bindings import ModelBinding, execution_key
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.graph import AgentKernel
from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall, TenantSkillEnablement
from pdos_next.agent_kernel.proposal_context import KEY
from pdos_next.agent_kernel.read_execution import ReadSource
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.errors import DomainError
from pdos_next.models import Artifact
from pdos_next.providers.types import ProviderUsage
from pdos_next.service import digest
from tests.agent_kernel.test_gateway import Client, configured_route
from tests.agent_kernel.test_m3_original_binding_pg import QUOTE, actual_run, uploaded
from tests.agent_kernel.test_proposal_context_pg import agree
from tests.g0_fixture import create_g0_project
from tests.preproject.test_category_context_pg import add_knowledge, publish
from tests.preproject.test_derivation_transactions import derivative_payload, synthetic_parent
from tests.preproject.test_g0 import create, payload, post, read, request
from tests.preproject.test_g0 import work as work
from tests.preproject.test_standard_match_pg import counts
from tests.test_original_security import security_work as security_work

TOOL = "calc.spec_compare"


def fixture(work, security_work, entry="customer_request", *, missing_unit=False):
    parameter = publish(work, unit="dB(A)", standard_condition="one meter")
    parameter_ref = {"parameter_id": parameter["parameter_id"], "parameter_version": 1}
    parent = synthetic_parent(
        work,
        spec_values=[
            {
                **parameter_ref,
                "key": "noise",
                "parameter": "噪声",
                "value_type": "number",
                "value": 70,
                "unit": "dB(A)",
                "condition_note": "one meter",
                "test_conditions": [],
                "exceptions": [],
            }
        ],
    )
    human = {
        "type": "human",
        "id": str(work.human),
        "version": 1,
        "statement": "Synthetic named product requirement",
    }
    data = derivative_payload(work, parent) if entry == "derivative" else payload(work)
    source = None
    if entry == "customer_request":
        _, source = uploaded(work, security_work, label="Synthetic private comparison")
        ref = {"type": "original", "id": str(source), "version": 1, "line": 1, "quote": QUOTE}
        data.update(entry_kind=entry, customer_identities=["Synthetic customer"], source_refs=[ref])
    else:
        ref = human
    spec = next(item for item in data["groups"]["items"] if item["kind"] == "spec")
    spec.update(
        content={
            **({} if missing_unit else parameter_ref),
            "key": "noise",
            "parameter": "噪声",
            "value_type": "number",
            "upper": "75",
            "unit": None if missing_unit else "dB(A)",
            "condition_note": "one meter",
            "availability": "known",
            "item_status": "confirmed",
            "nature": "extracted" if source else "decided",
        },
        source_refs=[ref],
    )
    competitor = add_knowledge(
        work,
        kind="competitor",
        source_refs=[human],
        content={
            "brand": "Synthetic",
            "model": "Shared comparison",
            "metrics": [
                {
                    **parameter_ref,
                    "unit": "dB(A)",
                    "condition_note": "one meter",
                    "value": "65",
                    "nature": "claimed",
                    "source_ref": human,
                }
            ],
        },
    )
    proposal, _ = create(work, data)
    owner = Bootstrap(work.engine)
    scope, _ = actual_run(work, owner, UUID(proposal))
    arguments = {
        "subjects": [
            {"type": "proposal", "id": proposal},
            {"type": "product", "id": str(work.product)},
            {"type": "competitor", "id": competitor["entry_id"]},
        ]
    }
    return SimpleNamespace(
        owner=owner, scope=scope, arguments=arguments, source_id=source, work=work
    )


def ledger(f):
    owner, scope = f.owner, f.scope
    route = SimpleNamespace(version="synthetic-private-spec@1", digest=digest("synthetic route"))
    owner.route = lambda *_: route
    binding = ModelBinding(
        model_version=route.version,
        model_route_digest=route.digest,
        tool_definitions_digest=digest(owner.registry.definitions()),
        prompt_digest=digest("synthetic private comparison prefix"),
        isolation="main",
        cancel_epoch=scope.cancel_epoch,
        loaded_skills=(),
    )
    with owner.store.transaction(scope) as (_, run):
        run.state = "running"
        run.versions = {
            **run.versions,
            "model_version": route.version,
            "model_route_digest": route.digest,
            "tool_definitions": {"main": binding.tool_definitions_digest},
            "prompt_prefixes": {"main": binding.prompt_digest},
        }
    identity, _ = owner.store.claim(
        scope,
        "synthetic-private-spec:" + str(uuid4()),
        "model",
        {"fixture": "no provider invocation"},
        execution_binding=binding.model_dump(mode="json"),
    )
    owner.store.settle(
        scope, identity, result={"calls": [{"name": TOOL, "arguments": f.arguments}]}
    )
    f.source = ReadSource(model_call_id=identity, response_index=0)
    f.key = execution_key(scope.run_id, identity, 0)
    f.host = BoundHost(owner.store, owner.adapters())
    return f


def invoke(f):
    return f.host.read(f.scope, f.owner.registry.get(TOOL), f.arguments, f.key, source=f.source)


@pytest.mark.parametrize("entry", ["customer_request", "new_product", "derivative"])
def test_three_bound_private_entries_compare_shared_models_and_competitors_without_writes(
    work, security_work, entry
):
    f = ledger(fixture(work, security_work, entry))
    before = counts(work)
    with f.owner.store.transaction(f.scope) as (_, run):
        original = digest([run.read_sources, run.data_categories, run.versions[KEY]])
    result = invoke(f)
    assert counts(work) == before
    assert len(result["subjects"]) == 3 and result["groups"]
    observations = [row for group in result["groups"] for row in group["observations"]]
    assert any(row["upper"] == "75" for row in observations), result
    assert any(Decimal(row["value"]) == 70 for row in observations if row["value"]), result
    assert any(Decimal(row["value"]) == 65 for row in observations if row["value"]), result
    assert result["execution_ref"]["read_kind"] == "ordinary/v1"
    assert f.owner.registry.get(TOOL).version == "5"
    assert invoke(f) == result
    with f.owner.store.transaction(f.scope) as (session, run):
        assert run.private_context
        assert digest([run.read_sources, run.data_categories, run.versions[KEY]]) == original
        call = session.get(AgentToolCall, UUID(result["execution_ref"]["call_id"]))
        assert (
            call.execution_binding["tool_definitions_digest"]
            == run.versions["tool_definitions"]["main"]
        )
        assert call.receipt_id is None


def test_bound_private_comparison_keeps_missing_unit_unknown(work, security_work):
    f = ledger(fixture(work, security_work, missing_unit=True))
    result = invoke(f)
    observations = [row for group in result["groups"] for row in group["observations"]]
    selected = [
        row for row in [*observations, *result["unmapped"]] if row["subject"]["type"] == "proposal"
    ]
    assert selected and all(not row["comparable"] for row in selected), result
    assert any("unit" in str(row["reasons"]) for row in selected), result


@pytest.mark.parametrize("change", ["withdraw", "new_original", "missing_binding"])
def test_changed_private_source_binding_stops_before_comparison_body(
    work, security_work, monkeypatch, change
):
    f = ledger(fixture(work, security_work))
    if change == "new_original":
        _, identity = uploaded(work, security_work, label="Synthetic newly mounted comparison")
        response = post(
            work,
            request(
                work,
                "proposal.item.patch",
                {
                    "proposal_id": str(f.scope.proposal_id),
                    "ops": [
                        {
                            "kind": "section",
                            "content": {"key": "summary", "text": "Synthetic new material"},
                            "source_refs": [
                                {
                                    "type": "original",
                                    "id": str(identity),
                                    "version": 1,
                                    "line": 1,
                                    "quote": QUOTE,
                                }
                            ],
                        }
                    ],
                },
            ),
        )
        assert response.status_code == 200, response.text
    else:
        with Session(work.admin) as session, session.begin():
            if change == "withdraw":
                session.get(Artifact, f.source_id).status = "withdrawn"
            else:
                run = session.get(AgentRun, f.scope.run_id)
                run.versions = {key: value for key, value in run.versions.items() if key != KEY}
    monkeypatch.setattr(
        m3_spec_compare.spec_compare,
        "compare",
        lambda *_a, **_kw: pytest.fail("Changed source must stop before comparison"),
    )
    with pytest.raises(DomainError):
        invoke(f)


@pytest.mark.parametrize("other", ["proposal", "private_product"])
def test_private_binding_does_not_authorize_another_private_object(
    work, security_work, monkeypatch, other
):
    f = fixture(work, security_work)
    identity = (
        create(work)[0]
        if other == "proposal"
        else create_g0_project(work, visibility="private").product_id
    )
    f.arguments["subjects"] = [
        {"type": "proposal" if other == "proposal" else "product", "id": str(identity)}
    ]
    ledger(f)
    monkeypatch.setattr(
        m3_spec_compare.spec_compare,
        "compare",
        lambda *_a, **_kw: pytest.fail("Unbound object must stop before comparison"),
    )
    with pytest.raises(DomainError):
        invoke(f)


def test_completed_private_comparison_recovery_rechecks_actual_source_and_result(
    work, security_work
):
    f = ledger(fixture(work, security_work))
    result = invoke(f)
    row = read(work, str(f.scope.proposal_id)).json()
    item = next(item for item in row["items"] if item["kind"] == "spec")
    content = deepcopy(item["content"])
    content["upper"] = "74"
    changed = post(
        work,
        request(
            work,
            "proposal.item.patch",
            {
                "proposal_id": str(f.scope.proposal_id),
                "ops": [
                    {
                        "kind": "spec",
                        "item_id": item["item_id"],
                        "base_version": item["version"],
                        "content": content,
                        "source_refs": item["source_refs"],
                    }
                ],
            },
            revision=row["revision"],
        ),
    )
    assert changed.status_code == 200, changed.text
    with pytest.raises(DomainError) as error:
        invoke(f)
    assert error.value.code == "SOURCE_STALE"
    with Session(work.admin) as session:
        call = session.get(AgentToolCall, UUID(result["execution_ref"]["call_id"]))
        assert call.state == "completed" and call.result["input_digest"] == result["input_digest"]
    with Session(work.admin) as session, session.begin():
        session.get(Artifact, f.source_id).status = "withdrawn"
    with pytest.raises(DomainError):
        invoke(f)


def test_registered_graph_uses_private_comparison_and_finishes_in_same_run(work, security_work):
    f = fixture(work, security_work)
    agree(work, f.scope, f.scope.data_categories)
    f.owner.route = lambda *_: configured_route()
    with Session(work.admin) as session, session.begin():
        session.get(AgentRun, f.scope.run_id).token_limit = 1_000_000
        session.add(
            TenantSkillEnablement(
                tenant_id=work.tenant, skill_key="competitor_comparison", enabled=True
            )
        )
    calls = []

    def answer(kwargs):
        calls.append(kwargs["messages"])
        if len(calls) == 1:
            return ModelTurn(
                calls=(ToolCall(id="compare", name=TOOL, arguments=f.arguments),),
                usage=ProviderUsage(2, 1),
            )
        result = json.loads(kwargs["messages"][-1]["content"])
        assert "error" not in result and len(result["subjects"]) == 3, result
        return ModelTurn(
            structured={
                "status": "completed",
                "summary": "Synthetic private comparison",
                "result": {"input_digest": result["input_digest"]},
                "questions": [],
                "unfinished": [],
            },
            usage=ProviderUsage(2, 1),
        )

    client = Client(answer)
    adapters = replace(
        f.owner.adapters(),
        route_for=lambda _: configured_route(),
        provider_for=lambda *_: "synthetic-provider",
        provider_client=client,
        cost_required=False,
    )
    result = AgentKernel(BoundHost(f.owner.store, adapters), f.owner.registry).execute(
        f.scope, goal="Synthetic proposal comparison", preload=("competitor_comparison",)
    )
    assert result["output"]["status"] == "completed" and client.calls == 2, result["output"]
    with f.owner.store.transaction(f.scope) as (session, run):
        assert run.state == "completed" and run.id == f.scope.run_id
        call = session.scalar(
            select(AgentToolCall).where(
                AgentToolCall.run_id == run.id,
                AgentToolCall.tool == TOOL,
            )
        )
        assert call.state == "completed"
        assert (
            call.execution_binding["tool_definitions_digest"]
            == run.versions["tool_definitions"]["main"]
        )
    print(
        json.dumps(
            {
                "run_id": str(f.scope.run_id),
                "registered_graph": "xiaopai",
                "tool_version": "5",
                "synthetic_model_turns": client.calls,
                "outcome": result["output"]["status"],
                "real_provider_calls": 0,
            }
        )
    )
