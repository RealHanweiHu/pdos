"""Private bound baseline/diff/platform analysis; real domain commands, synthetic models."""
# ruff: noqa: F811 -- explicitly imported marked PG fixture

import json
from copy import deepcopy
from dataclasses import replace
from time import perf_counter
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

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
from tests.agent_kernel.test_m3_definition_diff_pg import three_way
from tests.agent_kernel.test_m3_original_binding_pg import actual_run
from tests.agent_kernel.test_proposal_context_pg import agree
from tests.agent_kernel.test_transactions import human_session
from tests.preproject.test_baseline_blocks_pg import owner_fixture_chain
from tests.preproject.test_derivation_transactions import (
    derivative_payload,
    synthetic_parent,
    typed_private_parent,
)
from tests.preproject.test_g0 import create, decide_request, payload, read, save, submit
from tests.preproject.test_g0 import work as work
from tests.preproject.test_standard_match_pg import counts
from tests.products import test_definition_transactions as definition_commands
from tests.products.test_definition_item_commands_pg import confirmed, current_items, patch, upsert
from tests.products.test_platform_links_pg import request as platform_request


def bound(work, data):
    identity, _ = create(work, data)
    owner = Bootstrap(work.engine)
    scope, _ = actual_run(work, owner, UUID(identity))
    return SimpleNamespace(owner=owner, scope=scope, work=work)


def call(f, tool, arguments):
    route = SimpleNamespace(
        version="synthetic-private-analysis@1", digest=digest("synthetic analysis")
    )
    f.owner.route = lambda *_: route
    binding = ModelBinding(
        model_version=route.version,
        model_route_digest=route.digest,
        tool_definitions_digest=digest(f.owner.registry.definitions()),
        prompt_digest=digest("synthetic private analysis prefix"),
        isolation="main",
        cancel_epoch=f.scope.cancel_epoch,
        loaded_skills=(),
    )
    with f.owner.store.transaction(f.scope) as (_, run):
        run.state = "running"
        run.versions = {
            **run.versions,
            "model_version": route.version,
            "model_route_digest": route.digest,
            "tool_definitions": {"main": binding.tool_definitions_digest},
            "prompt_prefixes": {"main": binding.prompt_digest},
        }
    identity, _ = f.owner.store.claim(
        f.scope,
        "synthetic-private-analysis:" + str(uuid4()),
        "model",
        {},
        execution_binding=binding.model_dump(mode="json"),
    )
    f.owner.store.settle(
        f.scope, identity, result={"calls": [{"name": tool, "arguments": arguments}]}
    )
    host = BoundHost(f.owner.store, f.owner.adapters())
    source = ReadSource(model_call_id=identity, response_index=0)
    key = execution_key(f.scope.run_id, identity, 0)

    def perform():
        return host.read(f.scope, f.owner.registry.get(tool), arguments, key, source=source)

    statements = 0

    def count_sql(*_):
        nonlocal statements
        statements += 1

    event.listen(f.work.engine, "before_cursor_execute", count_sql)
    started = perf_counter()
    try:
        result = perform()
    finally:
        event.remove(f.work.engine, "before_cursor_execute", count_sql)
    f.last_read = {
        "tool": tool,
        "elapsed_ms": round((perf_counter() - started) * 1000, 2),
        "sql_count": statements,
        "real_provider_calls": 0,
    }
    return result, perform


def definition_ref(identity, version=1):
    return {"type": "definition", "id": str(identity), "version": version}


@pytest.mark.parametrize("private_kind", ["product", "nested_source"])
def test_private_baseline_proposal_diff_spec_and_platform_are_readable_without_business_writes(
    work, private_kind, monkeypatch
):
    parent = (
        synthetic_parent(work, private=True)
        if private_kind == "product"
        else typed_private_parent(work)[0]
    )
    f = bound(work, derivative_payload(work, parent))
    link, _ = confirmed(work, platform_request(work, compatibility="Synthetic bound compatibility"))
    before = counts(work)
    baseline, replay = call(
        f,
        "product.baseline.read",
        {
            "product_id": str(work.product),
            "definition_revision": 1,
            "areas": ["specification", "platform"],
        },
    )
    assert baseline["definition"]["id"] == str(parent.id) and baseline["derivation_eligible"]
    if private_kind == "product":
        print(json.dumps({"scope": "one bound private published baseline read", **f.last_read}))
    assert baseline["blocks"]["platform"]["items"][0]["id"] == link["result"]["platform_id"]
    assert replay() == baseline
    revision = read(work, str(f.scope.proposal_id)).json()["revision"]
    from pdos_next.domain.preproject import views

    actual_read, document_reads = views.read, []

    def document(*args, **kwargs):
        document_reads.append(args[2])
        return actual_read(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(views, "read", document)
        difference, _ = call(
            f,
            "calc.derivation_diff",
            {
                "baseline": {
                    "product_id": str(work.product),
                    "definition_id": str(parent.id),
                    "definition_revision": 1,
                },
                "proposed": {"proposal_id": str(f.scope.proposal_id), "revision": revision},
                "areas": ["specification"],
            },
        )
    assert document_reads == [f.scope.proposal_id]
    assert difference["old_parent"]["definition_id"] == str(parent.id)
    assert difference["execution_ref"]["read_kind"] == "ordinary/v1"
    platforms, _ = call(f, "platform.read", {"product_id": str(work.product)})
    assert platforms["items"][0]["links"][0]["compatibility"] == "Synthetic bound compatibility"
    assert platforms["link_scope"] == (
        "current_audience" if private_kind == "product" else "category_shared"
    )
    compared, _ = call(
        f,
        "calc.spec_compare",
        {
            "subjects": [
                {"type": "proposal", "id": str(f.scope.proposal_id)},
                {"type": "product", "id": str(work.product)},
            ]
        },
    )
    assert len(compared["subjects"]) == 2 and counts(work) == before
    with f.owner.store.transaction(f.scope) as (_, run):
        assert run.private_context and run.versions[KEY]["proposal_id"] == str(f.scope.proposal_id)


def test_private_three_way_recovery_keeps_actual_item_versions_and_old_result(work):
    chain = three_way(work, visibility="private")
    data = payload(work)
    data["source_refs"] = [
        definition_ref(chain.old),
        definition_ref(chain.child, 2),
        definition_ref(chain.new, 3),
    ]
    f = bound(work, data)
    with f.owner.store.transaction(f.scope) as (_, run):
        assert run.product_id is None and run.read_sources
        assert {ref["product_id"] for ref in run.read_sources} == {str(work.product)}
    with pytest.raises(DBAPIError) as invalid_scope:
        with human_session(work) as session:
            original = session.get(AgentRun, f.scope.run_id)
            candidate = {
                column.key: deepcopy(getattr(original, column.key))
                for column in AgentRun.__table__.columns
            }
            candidate.update(id=uuid4(), intent_key=str(uuid4()))
            candidate["read_sources"][0]["product_id"] = str(uuid4())
            session.add(AgentRun(**candidate))
            session.flush()
    assert invalid_scope.value.orig.sqlstate == "23514"
    from migrations.schema_s0_0761 import DOWNGRADE_SQL, GATE

    with pytest.raises(DBAPIError, match="model-source history requires s0_0761"):
        with work.admin.begin() as connection:
            connection.exec_driver_sql("SET LOCAL ROLE pdos_next_owner")
            for statement in DOWNGRADE_SQL:
                connection.exec_driver_sql(statement)
    with work.admin.connect() as connection:
        assert connection.scalar(
            text("SELECT relforcerowsecurity FROM pg_class WHERE oid='agent_runs'::regclass")
        )
        assert (
            connection.scalar(
                text("SELECT pg_get_functiondef('kernel_source_reference_gate()'::regprocedure)")
            )
            == GATE
        )
    print(
        json.dumps(
            {
                "category_run_actual_model_scope_preserved": True,
                "wrong_source_model_rejected": True,
                "unsafe_downgrade_rejected": True,
                "forced_rls_restored": True,
            }
        )
    )
    before = counts(work)
    result, replay = call(f, "calc.derivation_diff", chain.arguments)
    classifications = {row["path"]: row["classification"] for row in result["differences"]}
    assert classifications["specs/child_only"] == "child_only"
    assert classifications["specs/parent_only"] == "parent_only"
    assert classifications["specs/conflict"] == "conflict"
    assert replay() == result and counts(work) == before
    current = current_items(work, chain.new)["parent_only"]
    change = upsert(
        current,
        key="parent_only",
        value="5",
        unit="PSI",
        availability="known",
        item_status="confirmed",
        nature="decided",
        reason="Synthetic fixed-definition check",
    )
    change["source_refs"] = deepcopy(current.source_refs)
    denied = definition_commands.post(work, patch(work, chain.new, change))
    assert denied.status_code == 409 and denied.json()["detail"]["reason"] == "definition_consumed"
    assert replay() == result
    with Session(work.admin) as session, session.begin():
        session.get(Artifact, chain.artifact_id).status = "withdrawn"
    with pytest.raises(DomainError):
        replay()
    with Session(work.admin) as session:
        call_row = session.get(AgentToolCall, UUID(result["execution_ref"]["call_id"]))
        assert (
            call_row.state == "completed"
            and call_row.result["request_digest"] == result["request_digest"]
        )


def test_baseline_and_platform_restore_recheck_source_and_link_watermarks(work):
    parent, artifact_id, *_ = typed_private_parent(work)
    f = bound(work, derivative_payload(work, parent))
    link, _ = confirmed(work, platform_request(work))
    baseline, baseline_replay = call(
        f,
        "product.baseline.read",
        {"product_id": str(work.product), "definition_revision": 1, "areas": ["specification"]},
    )
    first, platform_replay = call(f, "platform.read", {"product_id": str(work.product)})
    confirmed(
        work,
        platform_request(
            work,
            new_platform=None,
            platform_id=link["result"]["platform_id"],
            expected_link_version=1,
            compatibility="Synthetic revised compatibility",
        ),
    )
    with pytest.raises(DomainError) as error:
        platform_replay()
    assert error.value.code == "SOURCE_STALE"
    with Session(work.admin) as session, session.begin():
        session.get(Artifact, artifact_id).status = "withdrawn"
    for replay in (baseline_replay, platform_replay):
        with pytest.raises(DomainError):
            replay()
    with Session(work.admin) as session:
        for result in (baseline, first):
            assert (
                session.get(AgentToolCall, UUID(result["execution_ref"]["call_id"])).state
                == "completed"
            )


@pytest.mark.parametrize("tool", ["product.baseline.read", "platform.read"])
def test_private_product_outside_bound_definitions_is_unavailable(work, monkeypatch, tool):
    f = bound(work, payload(work))
    synthetic_parent(work, private=True)
    if tool == "product.baseline.read":
        from pdos_next.domain.preproject import baseline

        monkeypatch.setattr(
            baseline, "read_baseline", lambda *_a, **_kw: pytest.fail("Unbound private body")
        )
    with pytest.raises(DomainError):
        call(f, tool, {"product_id": str(work.product)})


def test_proposal_product_source_uses_actual_scope_and_private_parent(work):
    synthetic_parent(work, private=True)
    identity = definition_commands.source(work, visibility="category")
    with human_session(work) as session:
        source = session.get(Artifact, identity)
        quote = source.content.splitlines()[0]
    data = payload(work)
    data["source_refs"] = [
        {"type": "artifact", "id": str(identity), "version": 1, "line": 1, "quote": quote}
    ]
    f = bound(work, data)
    detail = read(work, str(f.scope.proposal_id)).json()
    assert detail["private_source_count"] > 0 and detail["visibility"] == "private"
    with f.owner.store.transaction(f.scope) as (_, run):
        assert run.private_context and run.read_sources == [
            {
                "artifact_id": str(identity),
                "expected_revision": 1,
                "product_id": str(work.product),
            }
        ]


def test_bound_variant_platform_reads_only_actual_target_and_not_other_private_links(work):
    parent = synthetic_parent(work)
    proposal, _ = create(work, derivative_payload(work, parent, "new_variant"))
    submit(work, proposal)
    decision, _ = save(work, decide_request(work, proposal), actor=work.peer)
    result = decision["result"]
    data = payload(work)
    data["source_refs"] = [definition_ref(result["definition_id"])]
    f = bound(work, data)
    saved, _ = confirmed(
        work,
        platform_request(
            work,
            variant_id=result["variant_id"],
            compatibility="Synthetic variant-only compatibility",
        ),
    )
    selected, _ = call(
        f, "platform.read", {"product_id": str(work.product), "variant_id": result["variant_id"]}
    )
    assert selected["link_scope"] == "current_audience"
    assert selected["items"][0]["links"][0]["variant_id"] == result["variant_id"]
    assert selected["items"][0]["id"] == saved["result"]["platform_id"]
    general, _ = call(f, "platform.read", {})
    assert general["link_scope"] == "category_shared"
    assert all(not item["links"] for item in general["items"])
    baseline, _ = call(
        f,
        "product.baseline.read",
        {
            "product_id": str(work.product),
            "variant_id": result["variant_id"],
            "definition_revision": 1,
            "areas": ["specification", "platform"],
        },
    )
    assert (
        baseline["definition"]["id"] == result["definition_id"]
        and baseline["baseline_kind"] == "g0"
    )


def test_private_bom_sources_require_existing_binding_and_unselected_blocks_stay_unread(work):
    chain = owner_fixture_chain(work, "source")
    data = payload(work)
    data["source_refs"] = [definition_ref(chain.parent.id)]
    f = bound(work, data)
    result, _ = call(
        f,
        "product.baseline.read",
        {"product_id": str(work.product), "definition_revision": 1, "areas": ["specification"]},
    )
    assert result["definition"]["id"] == str(chain.parent.id) and not result["blocks"]
    with pytest.raises(DomainError):
        call(
            f,
            "product.baseline.read",
            {"product_id": str(work.product), "definition_revision": 1, "areas": ["bom"]},
        )
    from pdos_next.domain.configurations.models import PartIdentity

    with human_session(work) as session:
        source = session.get(PartIdentity, chain.part_id).sources[0]
    data["source_refs"].append(
        {
            "type": "artifact",
            "id": source["artifact_id"],
            "version": source["expected_revision"],
            "line": source["line"],
            "quote": source["quote"],
        }
    )
    explicit = bound(work, data)
    available, _ = call(
        explicit,
        "product.baseline.read",
        {
            "product_id": str(work.product),
            "definition_revision": 1,
            "areas": ["bom"],
        },
    )
    assert available["blocks"]["bom"]["status"] == "available"
    assert available["blocks"]["bom"]["items"][0]["bom_id"] == str(chain.bom_id)


def test_registered_graph_reads_private_baseline_diff_platform_then_completes(work):
    parent = synthetic_parent(work, private=True)
    f = bound(work, derivative_payload(work, parent))
    confirmed(work, platform_request(work, compatibility="Synthetic private graph compatibility"))
    agree(work, f.scope, f.scope.data_categories)
    with Session(work.admin) as session, session.begin():
        session.get(AgentRun, f.scope.run_id).token_limit = 1_000_000
        session.add(
            TenantSkillEnablement(tenant_id=work.tenant, skill_key="derivative_diff", enabled=True)
        )
    f.owner.route = lambda *_: configured_route()
    revision = read(work, str(f.scope.proposal_id)).json()["revision"]
    tools = [
        ("product.baseline.read", {"product_id": str(work.product), "definition_revision": 1}),
        (
            "calc.derivation_diff",
            {
                "baseline": {"product_id": str(work.product), "definition_revision": 1},
                "proposed": {"proposal_id": str(f.scope.proposal_id), "revision": revision},
            },
        ),
        ("platform.read", {"product_id": str(work.product)}),
    ]
    turns = []

    def answer(kwargs):
        if turns:
            previous = json.loads(kwargs["messages"][-1]["content"])
            assert "error" not in previous, previous
        turns.append(kwargs["messages"])
        if len(turns) <= len(tools):
            name, args = tools[len(turns) - 1]
            return ModelTurn(
                calls=(ToolCall(id="analysis-" + str(len(turns)), name=name, arguments=args),),
                usage=ProviderUsage(2, 1),
            )
        return ModelTurn(
            structured={
                "status": "completed",
                "summary": "Synthetic private analysis",
                "result": {},
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
        f.scope, goal="Synthetic private derivation analysis", preload=("derivative_diff",)
    )
    assert result["output"]["status"] == "completed" and client.calls == 4, result["output"]
    with f.owner.store.transaction(f.scope) as (session, run):
        assert run.state == "completed"
        actual = list(
            session.scalars(
                select(AgentToolCall).where(
                    AgentToolCall.run_id == run.id,
                    AgentToolCall.tool.in_([name for name, _ in tools]),
                )
            )
        )
        assert len(actual) == 3 and all(row.state == "completed" for row in actual)
    print(
        json.dumps(
            {
                "run_id": str(f.scope.run_id),
                "registered_graph": "xiaopai",
                "synthetic_model_turns": client.calls,
                "outcome": result["output"]["status"],
                "real_provider_calls": 0,
            }
        )
    )
