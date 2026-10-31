"""CTX-09/11 native mechanics/admission observations; no model-quality scores.

Root alone executes the four explicitly guarded PostgreSQL cases. The offline
provider only drives registered control flow. No Temporal, embedding or provider
network is used. CTX-09 deliberately reports partial scenario binding: native
JSON fragments do not establish the question's three-items-per-page assumption.
"""

import json
import os
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from g0_fixture import create_g0_project
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.activities import KernelActivities
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.context_budget import TOOL_RESULT_RESERVE, budget_for
from pdos_next.agent_kernel.disclosure import disclosure, skill_operations
from pdos_next.agent_kernel.graph import AgentKernel
from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.models import AgentEvent, AgentToolCall, TenantSkillEnablement
from pdos_next.agent_kernel.read_execution import ReadBinding
from pdos_next.agent_kernel.result_continuation import parse_handle
from pdos_next.agent_kernel.types import ModelTurn, ToolCall, WireAgentOutput
from pdos_next.api import create_app
from pdos_next.domain.preproject import category_service
from pdos_next.domain.preproject.schemas import Reference
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Receipt
from pdos_next.providers.types import ProviderUsage
from pdos_next.service import digest
from tests.agent_kernel.eval_v0_ctx09_directory_support import (
    DIRECTORY_REGION,
    MECHANICS_REGION,
    DirectoryControl,
    code_reference,
    complete_prefix_items,
    native_directory,
)
from tests.agent_kernel.test_model_configuration_transactions import configured, submit
from tests.enterprise_search.test_eval_v0_contracts_pg import explicit_target
from tests.enterprise_search.test_work_followup_temporal_pg import register, totals
from tests.preproject.test_g0 import post, request

ROOT = Path(__file__).resolve().parents[4]
QUESTIONS = ROOT / "docs/evaluations/xiaopai-v0/context-questions.json"
NOT_SCORED = ["answer_correctness", "citation_semantics", "real_usage_latency_cost"]
OLD_TITLE = "补齐湿热复验原件"
NEW_TITLE = "收集湿热复验报告和测量附件"

PG_ONLY = pytest.mark.skipif(
    not explicit_target(), reason="Root must explicitly bind all roles to guarded 53502/pdos_test",
)


def case(identity):
    collection = json.loads(QUESTIONS.read_text())
    assert collection["synthetic"] and not collection["trusted_root"]
    return next(value for value in collection["cases"] if value["id"] == identity)


def observation_path(identity, focus):
    folder = os.environ.get("PDOS_CONTEXT_NATIVE_OUTPUT_DIR")
    if folder is None:
        return None
    folder = Path(folder)
    assert folder.is_absolute() and folder.is_dir(), "Root must pre-create the evidence directory"
    destination = folder / f"{identity}-F{focus}.json"
    assert not destination.exists(), "Native observations must never overwrite prior evidence"
    return destination


def write_observation(destination, value, record_property):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n"
    if destination is not None:
        with destination.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
    record_property("context_native_observation", encoded)


def model_call(name, arguments):
    return ModelTurn(calls=(ToolCall(id="offline-" + str(uuid4()), name=name,
                                     arguments=arguments),), usage=ProviderUsage(0, 0))


def stop(*, partial=False, citations=()):
    return ModelTurn(structured={
        "status": "partial" if partial else "completed",
        "summary": "离线原生控制流回放结束；回答质量未评测。",
        "result": {"assistant": {"citation_ids": list(citations)}} if citations else {},
        "questions": [], "unfinished": ["原生续读仍有缺页"] if partial else [],
    }, usage=ProviderUsage(0, 0))


def tool_values(messages):
    return [json.loads(row["content"]) for row in messages if row["role"] == "tool"]


class ScriptedProvider:
    def __init__(self, identity):
        self.case_id, self.requests = identity, []
        self.source, self.title = None, None
        self.fragments, self.failure, self.candidates = [], None, []
        self.directory_control = None

    def close(self):
        pass

    def turn(self, route, **kwargs):
        from pdos_agent_runtime.graph import in_registered_agent_graph

        assert in_registered_agent_graph()
        self.requests.append({"route_digest": route.digest, **{
            key: deepcopy(kwargs[key]) for key in ("system", "messages", "tools", "output_schema")
        }})
        messages, tools = kwargs["messages"], kwargs["tools"]
        values = tool_values(messages)
        names = {tool["name"] for tool in tools}
        if self.case_id == "CTX-09":
            assert kwargs["output_schema"] == WireAgentOutput.model_json_schema()
            if self.directory_control is not None:
                return self.directory_control.turn(messages)
            if not values:
                return model_call("category.knowledge.list", {
                    "kind": "boundary", "region": MECHANICS_REGION})
            last = values[-1]
            if "error" in last:
                self.failure = deepcopy(last)
                return stop(partial=True)
            assert last["format"] == "json_fragment" and last["total_pages"] == 3
            if not self.fragments or self.fragments[-1]["page"] != last["page"]:
                self.fragments.append(deepcopy(last))
            assert last["page"] in {1, 2}
            return model_call("result.read", last["read_more"]["arguments"])
        if names == {"assistant.passage.read", "result.read"}:
            cid = json.loads(messages[0]["content"])["context"]["citation_id"]
            if not values:
                return model_call("assistant.passage.read", {
                    "citation_id": cid, "cursor": 0, "page_chars": 2000,
                })
            assert values[-1]["next_cursor"] is None
            # Mechanical quote extraction, never a semantic or answer score.
            quote = values[-1]["text"].splitlines()[7]
            return ModelTurn(structured={
                "status": "completed", "summary": "离线逐字提取控制流。",
                "questions": [], "unfinished": [],
                "result": {"rows": [{"citation_id": cid, "quote": quote, "statement": quote}]},
            }, usage=ProviderUsage(0, 0))
        assert kwargs["output_schema"] == WireAgentOutput.model_json_schema()
        if not values:
            return model_call("assistant.materials.read", {
                "artifact_ids": [self.source["artifact_id"]],
            })
        if "items" in values[-1]:
            return model_call("assistant.extract", {
                "citation_ids": [row["citation_id"] for row in values[-1]["items"]],
            })
        if "rows" in values[-1]:
            rows = values[-1]["rows"]
            assert rows and rows[0]["quote"] == self.source["quote"]
            if self.title is None:
                return stop(citations=[row["citation_id"] for row in rows])
            assert "work.task.create" in names
            context = json.loads(messages[0]["content"])["context"]["work_followup_action"]
            return model_call("work.task.create", {
                "project_id": context["project_id"], "title": self.title,
                "goal": "收集缺失的湿热复验资料，保持原件未归档状态待本人核对。",
                "outcomes": [{"key": "materials", "text": "报告和测量附件及其原件定位",
                              "required": True}],
                "sources": [{"kind": "artifact", "id": self.source["artifact_id"],
                             "revision": self.source["expected_revision"],
                             "position": "line:8;quote_sha256:"
                             + sha256(self.source["quote"].encode()).hexdigest()}],
                "reason": "本人只要求预览；负责人和日期未选择。",
                "plan_task": None, "g0_open_item": None,
            })
        prepared = values[-1]
        assert prepared["requires_human"] and prepared["state"] == "candidate"
        self.candidates.append(deepcopy(prepared))
        extracted = next(value["rows"] for value in reversed(values) if "rows" in value)
        return stop(citations=[row["citation_id"] for row in extracted])


@contextmanager
def native_runtime(setup, provider, focus):
    management, runtime, configuration = configured(setup)
    api = None
    try:
        metadata = configuration["payload"]["metadata"]
        metadata["max_output_tokens"] = 2048
        metadata["context_window_tokens"] = focus + 2048 + TOOL_RESULT_RESERVE
        saved, _ = submit(setup, management, configuration)
        assert saved.status_code == 200, saved.text
        runtime = replace(runtime, provider_client=provider)
        owner = Bootstrap(setup.engine, ports=runtime)
        adapters = replace(owner.adapters(), cost_required=False,
                           provider_for=lambda *_: "offline-native-context-no-egress")
        host = BoundHost(owner.store, adapters)
        # Keep original registered child tools/graphs, replacing only accounting's
        # cost requirement and injecting this same offline provider into the host.
        from pdos_next.enterprise_search.assistant_graph import AssistantExtractGraph

        owner._assistant_adapter.graph = AssistantExtractGraph(host, owner._assistant_adapter)
        workflow_starts = []

        async def record_start(reference):
            workflow_starts.append(deepcopy(reference))

        async def prohibited_signal(*_args):
            pytest.fail("This native mechanics harness must not drive Temporal or adoption")

        ports = owner.api_ports(SimpleNamespace(
            start=record_start, signal=prohibited_signal, cancel=prohibited_signal,
        ))

        def binding(*args):
            value = owner.binding_for(*args)
            value.token_limit = 2_000_000
            return value

        api = TestClient(create_app(setup.engine, setup.auth, workflow_enabled=False,
                                   agent_runtime_ports=runtime,
                                   agent_api_ports=replace(ports, binding_for=binding)))
        yield SimpleNamespace(owner=owner, host=host, api=api, person=setup,
                              activities=KernelActivities(setup.engine), starts=workflow_starts,
                              path=f"/v1/categories/{setup.category}/agent-runs")
    finally:
        if api is not None:
            api.close()
        management.close()


def advance(runtime, payload):
    person = runtime.person
    accepted = runtime.api.post(runtime.path, headers=person.headers, json={
        "idempotency_key": str(uuid4()), **payload,
    })
    assert accepted.status_code == 202, accepted.text
    identity = UUID(accepted.json()["run_id"])
    scope = runtime.owner.store.scope(
        tenant_id=person.tenant, requester_id=person.human, writer_id=person.agent,
        category_id=person.category, run_id=identity,
    )
    route = runtime.owner.route_for(scope)
    assert budget_for(route)["window"] - budget_for(route)["reserve"] in {48_000, 64_000}
    preload = runtime.activities.preload(scope, runtime.host.adapters)
    state = AgentKernel(runtime.host, runtime.owner.registry).execute(
        scope, goal=payload["goal"], preload=preload,
    )
    assert state["output"]["status"] in {"completed", "partial"}, state["output"]
    return scope, state


def ledgers(runtime, scopes):
    calls, budgets, runs, candidates = [], [], [], []
    for scope in scopes:
        with runtime.owner.store.transaction(scope) as (session, run):
            runs.append({"run_id": str(run.id), "continued_from_id": str(run.continued_from_id)
                         if run.continued_from_id else None, "read_sources": run.read_sources})
            for row in session.scalars(select(AgentToolCall).where(
                AgentToolCall.run_id == run.id,
            ).order_by(AgentToolCall.created_at, AgentToolCall.id)):
                calls.append({"id": str(row.id), "run_id": str(run.id), "tool": row.tool,
                              "state": row.state, "error_code": row.error_code,
                              "input_digest": row.input_digest,
                              "receipt_id": str(row.receipt_id) if row.receipt_id else None,
                              "binding": deepcopy(row.execution_binding),
                              "result": deepcopy(row.result)})
            for row in session.scalars(select(AgentEvent).where(
                AgentEvent.run_id == run.id,
            ).order_by(AgentEvent.sequence)):
                if row.body.get("type") in {"context_observed", "context_admission_observed"}:
                    budgets.append({"run_id": str(run.id), **deepcopy(row.body)})
                elif row.body.get("type") == "domain_candidate":
                    candidates.append({"event_id": str(row.id), "run_id": str(run.id),
                                       "body": deepcopy(row.body)})
    return {"calls": calls, "runs": runs, "candidates": candidates}, budgets


def model_observations(actual, requests, events, focus):
    """Every dispatch retains its actual model ledger budget, including children.

    AssistantExtractGraph dispatches through the gateway but wraps child events;
    it does not emit the main host's full context_observed event shape.
    """
    models = [row for row in actual["calls"] if row["tool"] == "model"]
    assert len(models) == len(requests)
    remaining = list(models)
    dispatches = []
    for index, request_row in enumerate(requests):
        def matches(row, request_row=request_row):
            native_request = {key: request_row[key] for key in (
                "system", "messages", "tools", "output_schema",
            )}
            native_request.update(route=request_row["route_digest"],
                                  provider_key="offline-native-context-no-egress",
                                  execution_binding=row["binding"])
            return row["input_digest"] == digest(["model", native_request])

        matched = [row for row in remaining if matches(row)]
        assert len(matched) == 1, {"dispatch_index": index, "matches": len(matched)}
        row = matched[0]
        remaining.remove(row)
        dispatches.append({"dispatch_index": index, "model_call_id": row["id"],
                           "run_id": row["run_id"], "isolation": row["binding"]["isolation"],
                           "input_digest": row["input_digest"]})
    assert not remaining
    budgets = []
    for row in models:
        assert row["state"] == "completed" and row["error_code"] is None
        budget, usage = row["result"]["context_budget"], row["result"]["usage"]
        assert budget["focus"] == focus and budget["admission_tokens"] <= focus
        assert budget["window"] == focus + 2048 + TOOL_RESULT_RESERVE
        assert usage["input_tokens"] == usage["output_tokens"] == 0
        budgets.append({"record_source": "agent_tool_calls.result.context_budget",
                        "model_call_id": row["id"], "run_id": row["run_id"],
                        "isolation": row["binding"]["isolation"], **deepcopy(budget),
                        "usage": deepcopy(usage)})
    observed_ids = [row["model_call_id"] for row in events if row["type"] == "context_observed"]
    assert len(observed_ids) == len(set(observed_ids))
    model_ids = {row["id"] for row in models}
    assert set(observed_ids) <= model_ids
    main_ids = {row["id"] for row in models if row["binding"]["isolation"] == "main"}
    assert main_ids <= set(observed_ids)
    return budgets, dispatches, {
        "full_context_observed_model_call_ids": observed_ids,
        "ledger_budget_only_model_call_ids": sorted(model_ids - set(observed_ids)),
    }


def observed(runtime, provider, scopes, focus, *, native_binding_status, status, bindings):
    actual, events = ledgers(runtime, scopes)
    assert events and all(row["focus"] == focus for row in events)
    rejected = [row for row in events if row["type"] == "context_admission_observed"]
    budgets, dispatches, coverage = model_observations(actual, provider.requests, events, focus)
    assert all(row["window"] == focus + 2048 + TOOL_RESULT_RESERVE for row in rejected)
    assert bool(rejected) == (status == "context_admission_blocked")
    return {
        "version": "context-native-observation/v1", "case_id": provider.case_id,
        "f_budget_tokens": focus, "native_binding_status": native_binding_status,
        "status": status, "scripted_provider": True, "real_model_calls": 0,
        "real_embedding_calls": 0, "temporal_executed": False,
        "provider_dispatches": len(provider.requests), "context_budget": [*budgets, *rejected],
        "bindings": {**bindings, **actual, "provider_dispatch_bindings": dispatches,
                     "context_observation_events": events,
                     "context_observation_coverage": coverage},
        "model_quality_score": None, "not_scored": NOT_SCORED,
        "preflight_status": "context_admission_blocked" if rejected
        else "admitted_with_full_production_disclosure",
        "provider_inputs": provider.requests,
        "question_set_sha256": sha256(QUESTIONS.read_bytes()).hexdigest(),
    }


def test_model_observations_keeps_three_main_two_extract_dispatches_and_budgets():
    requests, models, events = [], [], []
    for index, isolation in enumerate(["main", "main", "assistant_extract",
                                       "assistant_extract", "main"]):
        request_row = {"route_digest": "synthetic-route", "system": "synthetic frozen system",
                       "tools": [], "output_schema": {},
                       "messages": [{"role": "user", "content": str(index)}]}
        native = {key: request_row[key] for key in ("system", "messages", "tools", "output_schema")}
        binding = {"kind": "model", "isolation": isolation}
        native.update(route=request_row["route_digest"],
                      provider_key="offline-native-context-no-egress", execution_binding=binding)
        row = {"id": str(uuid4()), "run_id": "synthetic-seed-run", "tool": "model",
               "state": "completed", "error_code": None, "binding": binding,
               "input_digest": digest(["model", native]), "result": {
                   "context_budget": {"focus": 48_000, "window": 54_048, "admission_tokens": 100},
                   "usage": {"input_tokens": 0, "output_tokens": 0},
               }}
        requests.append(request_row)
        models.append(row)
        if isolation == "main":
            events.append({"type": "context_observed", "model_call_id": row["id"]})
    actual = {"calls": models}
    budgets, dispatches, coverage = model_observations(actual, requests, events, 48_000)
    assert len(budgets) == len(dispatches) == 5
    assert len(coverage["full_context_observed_model_call_ids"]) == 3
    assert len(coverage["ledger_budget_only_model_call_ids"]) == 2
    assert [row["dispatch_index"] for row in dispatches] == list(range(5))
    for corrupt in ("drop_child", "input_digest", "nonzero_usage",
                    "missing_main_event", "duplicate_event"):
        altered, observed_events = deepcopy(actual), deepcopy(events)
        if corrupt == "drop_child":
            altered["calls"].pop(2)
        elif corrupt == "input_digest":
            altered["calls"][2]["input_digest"] = "mismatched-input"
        elif corrupt == "nonzero_usage":
            altered["calls"][2]["result"]["usage"]["input_tokens"] = 1
        elif corrupt == "missing_main_event":
            observed_events.pop()
        else:
            observed_events.append(deepcopy(events[0]))
        with pytest.raises(AssertionError):
            model_observations(altered, requests, observed_events, 48_000)


def assert_disclosure(runtime, provider):
    registry, catalog = runtime.owner.registry, runtime.owner.catalog
    for request_row in provider.requests:
        tools = request_row["tools"]
        names = {row["name"] for row in tools}
        if names == {"assistant.passage.read", "result.read"}:
            continue
        # Check the exact production disclosure, rather than a hand-picked count.
        skills = [catalog.configuration("work_management")] if "work.task.create" in names else []
        assert tools == disclosure(registry, operations=skill_operations(skills))
        assert request_row["output_schema"] == WireAgentOutput.model_json_schema()


@PG_ONLY
@pytest.mark.parametrize("focus", [48_000, 64_000], ids=["F48000", "F64000"])
def test_ctx09_native_handle_page2_then_same_handle_page3_failure(
    setup, monkeypatch, focus, record_property,
):
    destination = observation_path("CTX-09", focus)
    question = case("CTX-09")
    project = create_g0_project(setup, visibility="category").project_id
    # Only the six disclosed scenario entries exist in this source. Repeated
    # known text creates three JSON fragments, not invented entries 7..9.
    known = "条目1 Q-301 已登记；条目2 Q-302 待确认；条目3 Q-303 已登记；" + (
        "条目4 Q-304 已登记；条目5 Q-305 已登记；条目6 Q-306 待确认。"
    )
    registered = post(setup, request(setup, "category.knowledge.add", {
        "kind": "boundary", "regions": [MECHANICS_REGION],
        "content": {"definition": known + "；已披露条目过程说明" * 1000},
    }))
    assert registered.status_code == 200, registered.text
    directory = native_directory(setup, question)
    provider = ScriptedProvider("CTX-09")
    with native_runtime(setup, provider, focus) as runtime:
        original = runtime.host.continue_result
        rechecks = []

        def fail_page3(bound, data, *, original_reader=None):
            if data.page != 3:
                return original(bound, data, original_reader=original_reader)

            def unavailable(*args, **kwargs):
                # First do the real original registered READ/source check. The
                # injected availability failure happens before page 3 is built.
                value = runtime.host.read(*args, **kwargs)
                rechecks.append({"handle": data.handle, "page": data.page,
                                 "original_call_id": value["execution_ref"]["call_id"]})
                raise DomainError("SOURCE_UNAVAILABLE", "离线夹具受控续读不可用。")

            return original(bound, data, original_reader=unavailable)

        monkeypatch.setattr(runtime.host, "continue_result", fail_page3)
        scope, state = advance(runtime, {
            "goal": question["turns"][0]["content"] + "\n" + question["final_prompt"],
            "product_id": str(setup.product), "project_id": str(project),
        })
        assert provider.failure is not None
        assert provider.failure["error"]["code"] == "SOURCE_UNAVAILABLE", provider.failure
        assert state["output"]["status"] == "partial"
        assert [row["page"] for row in provider.fragments] == [1, 2]
        first, second = provider.fragments
        assert first["result_handle"] == second["result_handle"] == rechecks[0]["handle"]
        assert first["total_pages"] == second["total_pages"] == 3
        assert provider.failure and len(rechecks) == 1
        bindings, _budgets = ledgers(runtime, [scope])
        call_id, fingerprint = parse_handle(first["result_handle"])
        origin = next(row for row in bindings["calls"] if row["id"] == str(call_id))
        assert origin["tool"] == "category.knowledge.list"
        assert digest(origin["result"]) == fingerprint
        ReadBinding.model_validate(origin["binding"])
        pages = [row for row in bindings["calls"] if row["tool"] == "result.read"]
        assert len(pages) == 2 and {row["state"] for row in pages} == {"completed", "failed"}
        failed = next(row for row in pages if row["state"] == "failed")
        assert failed["error_code"] == "SOURCE_UNAVAILABLE" and failed["result"] is None
        final_values = tool_values(provider.requests[-1]["messages"])
        assert [row.get("page") for row in final_values if row.get("format")] == [1, 2]
        assert final_values[-1]["error"]["code"] == "SOURCE_UNAVAILABLE"
        assert all(not row.get("preview") for row in final_values if row.get("page") == 3)
        # A separate ordinary nine-object directory tests business coverage.
        # Natural JSON fragments keep their actual boundaries; no padding or
        # tool-cap adjustment makes these equal three business items per page.
        natural = provider.directory_control = DirectoryControl("natural_fragments")
        natural_scope, natural_state = advance(runtime, {
            "goal": question["turns"][0]["content"] + "\n" + question["final_prompt"],
            "product_id": str(setup.product), "project_id": str(project),
        })
        assert natural_state["output"]["status"] == "partial"
        assert natural.pages, natural.failure
        natural_calls, _ = ledgers(runtime, [natural_scope])
        natural_read = next(row for row in natural_calls["calls"]
                            if row["tool"] == "category.knowledge.list")
        ReadBinding.model_validate(natural_read["binding"])
        assert [row["id"] for row in natural_read["result"]["items"]] == [
            row["id"] for row in directory["entries"]]
        for row, expected in zip(natural_read["result"]["items"][:6],
                                 directory["entries"][:6], strict=True):
            faq = expected["faq"]
            assert faq["code"] in row["content"]["definition"]
            assert row["source_refs"] == [code_reference(faq)]
        if natural.pages[0].get("format") == "json_fragment":
            natural_handle = natural.pages[0]["result_handle"]
            natural_origin, natural_digest = parse_handle(natural_handle)
            assert str(natural_origin) == natural_read["id"]
            assert natural_digest == digest(natural_read["result"])
            assert all(page["result_handle"] == natural_handle for page in natural.pages)
            assert [page["page"] for page in natural.pages] == list(
                range(1, len(natural.pages) + 1))
            if natural.failure:
                failed_pages = [row for row in natural_calls["calls"]
                                if row["tool"] == "result.read" and row["state"] == "failed"]
                assert len(failed_pages) == 1 and failed_pages[0]["result"] is None
                failed_binding = ReadBinding.model_validate(failed_pages[0]["binding"])
                parent_model = next(row for row in natural_calls["calls"]
                                    if row["id"] == str(failed_binding.model_call_id))
                assert parent_model["result"]["calls"][failed_binding.response_index][
                    "arguments"] == {"handle": natural_handle, "page": 3}
        prefixes = natural.object_coverage()
        natural_ids = [[row["id"] for row in items] for items in prefixes]
        if natural.failure:
            assert natural.failure["error"]["code"] == "SOURCE_UNAVAILABLE"
        natural_aligned = (
            len(natural.pages) == 2
            and natural.pages[0].get("total_pages") == 3
            and natural_ids == [[row["id"] for row in directory["entries"][:3]],
                                [row["id"] for row in directory["entries"][:6]]]
            and natural.failure is not None
        )
        natural_control = {
            "run_id": str(natural_scope.run_id), "original_read_call_id": natural_read["id"],
            "native_result_total_items": len(natural_read["result"]["items"]),
            "format": natural.pages[0].get("format", "complete_json"),
            "total_pages": natural.pages[0].get("total_pages", 1),
            "complete_directory_item_ids_after_each_delivery": natural_ids,
            "same_binding_three_then_six_of_nine": natural_aligned,
            "failure": natural.failure,
        }
        # Cursor pages are an independent binding, not result.read pages. Their
        # successful 6/9 coverage cannot repair a different fragment alignment.
        cursor = provider.directory_control = DirectoryControl("native_cursor")
        native_list = runtime.host.adapters.read_tools["category.knowledge.list"]
        cursor_rechecks = []

        def missing_directory_page(bound, arguments):
            value = native_list(bound, arguments)
            if (arguments.get("region") == DIRECTORY_REGION and cursor.third_cursor
                    and arguments.get("cursor") == cursor.third_cursor):
                assert [row["id"] for row in value["items"]] == [
                    row["id"] for row in directory["entries"][6:]]
                assert all(row["content"]["material"]["body_state"] == "not_provided"
                           for row in value["items"])
                cursor_rechecks.append({"run_id": str(bound.run_id),
                                        "cursor": arguments["cursor"],
                                        "ordinary_source_rechecked": True})
                raise DomainError("SOURCE_UNAVAILABLE", "离线目录第三业务页受控不可用。")
            return value

        monkeypatch.setitem(runtime.host.adapters.read_tools, "category.knowledge.list",
                            missing_directory_page)
        cursor_scope, cursor_state = advance(runtime, {
            "goal": question["turns"][0]["content"] + "\n" + question["final_prompt"],
            "product_id": str(setup.product), "project_id": str(project),
        })
        assert cursor_state["output"]["status"] == "partial"
        assert cursor.failure and cursor.failure["error"]["code"] == "SOURCE_UNAVAILABLE"
        assert len(cursor.pages) == 2 and len(cursor_rechecks) == 1
        visible = [row for page in cursor.pages for row in page["items"]]
        assert [row["id"] for row in visible] == [row["id"] for row in directory["entries"][:6]]
        for row, expected in zip(visible, directory["entries"][:6], strict=True):
            faq = expected["faq"]
            assert faq["code"] in row["content"]["definition"]
            assert faq["record_status"] in row["content"]["definition"]
            assert row["source_refs"] == [code_reference(faq)]
        cursor_calls, _ = ledgers(runtime, [cursor_scope])
        directory_reads = [row for row in cursor_calls["calls"]
                           if row["tool"] == "category.knowledge.list"]
        assert len(directory_reads) == 3
        assert [row["state"] for row in directory_reads] == ["completed", "completed", "failed"]
        for row in directory_reads:
            assert ReadBinding.model_validate(row["binding"]).run_id == cursor_scope.run_id
        assert directory_reads[-1]["error_code"] == "SOURCE_UNAVAILABLE"
        assert directory_reads[-1]["result"] is None
        assert_disclosure(runtime, provider)
        write_observation(destination, observed(
            runtime, provider, [scope, natural_scope, cursor_scope], focus,
            native_binding_status="bound" if natural_aligned else "partial",
            status=("native_single_binding_directory_checks_passed_model_quality_not_scored"
                    if natural_aligned else
                    "native_mechanics_and_cursor_coverage_passed_single_binding_unbound"),
            bindings={"source_receipt_id": registered.json()["id"],
                      "source_lineage_id": registered.json()["subject_id"],
                      "result_handle": first["result_handle"], "source_rechecks": rechecks,
                      "coverage": {"format": "json_fragment", "read_pages": [1, 2],
                                   "missing_pages": [3], "total_pages": 3,
                                   "read_characters": sum(len(row["preview"])
                                                          for row in provider.fragments),
                                   "total_characters": first["total_characters"],
                                   "scenario_items_read": None, "scenario_total_items": 9},
                      "native_directory": directory,
                      "natural_single_binding_control": natural_control,
                      "independent_cursor_control": {
                          "run_id": str(cursor_scope.run_id), "read_directory_objects": 6,
                          "total_directory_objects": 9, "missing_directory_ordinals": [7, 8, 9],
                          "source_rechecks": cursor_rechecks,
                          "read_directory_entry_ids": [row["id"] for row in visible],
                          "failed_read_call_id": directory_reads[-1]["id"],
                          "business_coverage_control_passed": True,
                          "same_binding_as_mechanical_handle": False},
                      "scenario_gap": None if natural_aligned else
                          "Natural fragment boundaries do not prove exactly 3 then 6/9 complete "
                          "objects. Independent cursor coverage and the long-result mechanical "
                          "handle use different READ bindings and are not a full scenario pass."},
        ), record_property)


def test_ctx09_code_sources_follow_real_shared_material_reference_contract(monkeypatch):
    """Real source-type and literal-line guards, with DB authority ports isolated."""
    identity = uuid4()
    ctx = SimpleNamespace(tenant_id=uuid4(), category_id=uuid4())
    quote = "Q-301；合成登记状态：已登记。"
    source = {"type": "artifact", "id": str(identity), "version": 1,
              "line": 1, "quote": quote}
    artifact = SimpleNamespace(tenant_id=ctx.tenant_id, category_id=ctx.category_id,
                               product_id=None, original_id=None, visibility="category",
                               content=quote)
    session = SimpleNamespace(get=lambda model, key: (
        artifact if model is Artifact and key == identity else None))
    checked = []

    def actual_source(_session, _ctx, product, key, revision):
        assert _session is session and _ctx is ctx and product is None
        assert key == identity and revision == 1
        checked.append((key, revision))
        return artifact

    monkeypatch.setattr(category_service, "source_for", actual_source)
    wire_reference = code_reference(source)
    reference = Reference.model_validate(wire_reference)
    assert wire_reference == reference.model_dump(mode="json")
    category_service.check_shared_sources(session, ctx, [reference])
    assert checked == [(identity, 1)]
    with pytest.raises(DomainError) as mismatch:
        category_service.check_shared_sources(
            session, ctx, [reference.model_copy(update={"quote": "Q-302"})])
    assert mismatch.value.detail["reason"] == "quote_not_in_source"
    with pytest.raises(DomainError) as private_type:
        category_service.check_shared_sources(
            session, ctx, [reference.model_copy(update={"type": "knowledge"})])
    assert private_type.value.detail["reason"] == "private_source_in_shared"


def test_ctx09_complete_objects_are_decoded_from_actual_prefix_not_fragment_count():
    """Unsigned JSON parsing only; native bindings are separately asserted by PG."""
    first = [{"id": str(uuid4()), "content": {"definition": f"Q-{index}"}}
             for index in range(301, 310)]
    encoded = json.dumps({"as_of": "clock", "items": first, "next_cursor": None},
                         ensure_ascii=False, sort_keys=True)
    sixth = encoded.index(json.dumps(first[6], ensure_ascii=False, sort_keys=True))
    partial = encoded[:sixth + 20]
    assert complete_prefix_items(partial) == first[:6]
    assert complete_prefix_items(encoded) == first
    assert complete_prefix_items(encoded[:sixth]) == first[:6]


def test_ctx09_cursor_controller_follows_real_cursor_fields_and_preserves_failure():
    """Unsigned sequencing only; this supplies no native source or READ proof."""
    controller = DirectoryControl("native_cursor")
    messages = [{"role": "user", "content": "current goal"}]
    assert controller.turn(messages).calls[0].arguments == {
        "kind": "boundary", "region": DIRECTORY_REGION, "page_size": 3}
    for page in (1, 2):
        messages.append({"role": "tool", "content": json.dumps({
            "items": [{"id": str(uuid4())} for _ in range(3)],
            "next_cursor": f"actual-supplied-cursor-{page}",
        })})
        assert controller.turn(messages).calls[0].arguments["cursor"] == (
            f"actual-supplied-cursor-{page}")
    assert controller.third_cursor == "actual-supplied-cursor-2"
    messages.append({"role": "tool", "content": json.dumps({
        "error": {"code": "SOURCE_UNAVAILABLE"}})})
    final = controller.turn(messages)
    assert final.structured["status"] == "partial"
    assert controller.failure["error"]["code"] == "SOURCE_UNAVAILABLE"
    assert final.usage.input_tokens == final.usage.output_tokens == 0


def candidate(runtime, scope):
    response = runtime.api.get(runtime.path + f"/{scope.run_id}/candidates",
                               headers=runtime.person.headers)
    assert response.status_code == 200, response.text
    rows = [row for row in response.json()["items"] if row.get("kind") == "work_followup"]
    assert len(rows) == 1, response.text
    return rows[0]


def work_receipts(setup):
    with Session(setup.admin) as session:
        return session.scalar(select(func.count()).select_from(Receipt).where(
            Receipt.tenant_id == setup.tenant,
            Receipt.operation.in_(["work.task.create", "work.task.assign"]),
        ))


def admission_budget(state, focus):
    """Recognize only the production graph's actual required-context stop."""
    output = state["output"]
    body = output.get("result", {})
    if body.get("context_incomplete") is not True:
        return None
    budget = body["context_budget"]
    assert output["status"] == "partial" and body["actions"] == [] and body["missing"]
    assert budget["focus"] == focus and budget["over_focus"] is True
    assert budget["window"] == focus + 2048 + TOOL_RESULT_RESERVE
    assert budget["admission_tokens"] > focus
    return budget


def admission_stop(runtime, provider, parent, old, state, focus, seed_dispatches, before):
    budget = admission_budget(state, focus)
    if budget is None:
        return None
    # F64 must continue to exercise both actual candidates; no broad error or
    # ordinary partial result may be relabelled as a successful admission stop.
    assert focus == 48_000
    actual, observations = ledgers(runtime, [parent, old])
    old_calls = [row for row in actual["calls"] if row["run_id"] == str(old.run_id)]
    assert old_calls == [] and actual["candidates"] == [] and provider.candidates == []
    assert len(provider.requests) == seed_dispatches
    response = runtime.api.get(runtime.path + f"/{old.run_id}/candidates",
                               headers=runtime.person.headers)
    assert response.status_code == 200 and response.json()["items"] == [], response.text
    failed = [row for row in observations if row["run_id"] == str(old.run_id)
              and row["type"] == "context_admission_observed"]
    assert len(failed) == 1 and failed[0]["context_incomplete"] is True
    assert failed[0]["admission_tokens"] == budget["admission_tokens"]
    assert failed[0]["missing"] == state["output"]["result"]["missing"]
    with runtime.owner.store.transaction(old) as (_session, run):
        assert run.state == "partial" and run.result == state["output"]
    assert (totals(runtime.person), work_receipts(runtime.person)) == before
    return {
        "admission_stop": {"output": state["output"], "budget": budget,
                           "missing": failed[0]["missing"]},
        "phases": {
            "seed": {"run_id": str(parent.run_id), "provider_dispatches": seed_dispatches,
                     "purpose": "native source READ/citation seed; no business task write"},
            "old_candidate": {"run_id": str(old.run_id), "provider_dispatches": 0,
                              "tool_call_count": 0, "candidate_count": 0,
                              "create_assign_receipt_delta": 0},
            "corrected_candidate": {"status": "not_executed_after_admission_stop"},
        },
        "business_counts_before_after": before,
        "create_assign_receipt_delta": 0,
    }


@PG_ONLY
@pytest.mark.parametrize("focus", [48_000, 64_000], ids=["F48000", "F64000"])
def test_ctx11_native_corrected_candidate_preserves_old_pending_without_business_receipt(
    setup, focus, record_property,
):
    destination = observation_path("CTX-11", focus)
    question = case("CTX-11")
    project = create_g0_project(setup, visibility="category").project_id
    source = register(setup, "S11-A 合成复验记录", "\n".join(
        [f"合成复验记录目录行{number}" for number in range(1, 8)] + ["湿热复验原件尚未归档"]
    ))
    source["line"], source["quote"] = 8, "湿热复验原件尚未归档"
    provider = ScriptedProvider("CTX-11")
    provider.source = source
    with native_runtime(setup, provider, focus) as runtime:
        skill = runtime.owner.catalog.configuration("work_management")
        enabled, _ = submit(setup, runtime.api, {
            "command_id": str(uuid4()), "idempotency_key": str(uuid4()),
            "category_id": str(setup.category), "product_id": None,
            "operation": "ai.skill.enable", "expected_revision": 1, "source_read_set": [],
            "payload": {"skill_key": skill.key, "expected_revision": 0,
                        "skill_version": skill.version, "skill_digest": skill.digest,
                        "enabled": True},
        })
        assert enabled.status_code == 200, enabled.text
        parent, parent_state = advance(runtime, {
            "goal": "只读取明确选择的S11-A复验记录，不保存或指派任务。",
            "product_id": str(setup.product), "project_id": str(project),
            "sources": [{"artifact_id": source["artifact_id"], "expected_revision": 1}],
        })
        answer = parent_state["output"]["result"]["assistant"]
        assert answer["lookup"] == "cited" and answer["citation_ids"]
        before = totals(setup), work_receipts(setup)
        provider.title = OLD_TITLE
        seed_dispatches = len(provider.requests)
        old, old_state = advance(runtime, {
            "goal": question["turns"][0]["content"], "continue_from_run_id": str(parent.run_id),
            "sources": [{"artifact_id": source["artifact_id"], "expected_revision": 1}],
            "work_followup_action": {"project_id": str(project),
                                     "citation_ids": answer["citation_ids"], "assignment": None},
        })
        stopped = admission_stop(
            runtime, provider, parent, old, old_state, focus, seed_dispatches, before,
        )
        if stopped is not None:
            assert_disclosure(runtime, provider)
            write_observation(destination, observed(
                runtime, provider, [parent, old], focus, native_binding_status="not_executable",
                status="context_admission_blocked",
                bindings={"source": source, "project_id": str(project), **stopped},
            ), record_property)
            return
        assert old_state["output"]["status"] == "completed", old_state["output"]
        old_candidate = candidate(runtime, old)
        assert old_candidate["state"] == "pending" and old_candidate["receipt"] is None
        assert old_candidate["command"]["payload"]["title"] == OLD_TITLE
        with runtime.owner.store.transaction(old) as (session, run):
            state = session.get(AgentEvent, UUID(old_candidate["event_id"]))
            old_digest = digest(state.body)
            selected_sources = deepcopy(run.read_sources)
            current = run.result["result"]["assistant"]["citation_ids"]
            assert current
            qualification = session.scalar(select(TenantSkillEnablement).where(
                TenantSkillEnablement.tenant_id == setup.tenant,
                TenantSkillEnablement.skill_key == "work_management",
            ))
            assert not qualification.pilot and not qualification.review_case_refs
        provider.title = NEW_TITLE
        new, new_state = advance(runtime, {
            "goal": question["turns"][4]["content"] + "\n" + question["final_prompt"],
            "continue_from_run_id": str(old.run_id),
            "sources": [{"artifact_id": source["artifact_id"], "expected_revision": 1}],
            "work_followup_action": {"project_id": str(project),
                                     "citation_ids": current, "assignment": None},
        })
        assert new_state["output"]["status"] == "completed", new_state["output"]
        new_candidate = candidate(runtime, new)
        assert new_candidate["event_id"] != old_candidate["event_id"]
        assert new_candidate["state"] == "pending" and new_candidate["receipt"] is None
        assert new_candidate["command"]["payload"]["title"] == NEW_TITLE
        assert new_candidate["assignment"] is None and new_candidate["task"] is None
        assert candidate(runtime, old) == old_candidate
        assert (totals(setup), work_receipts(setup)) == before
        with runtime.owner.store.transaction(new) as (session, run):
            assert run.read_sources == selected_sources
            old_event = session.get(AgentEvent, UUID(old_candidate["event_id"]))
            assert digest(old_event.body) == old_digest
        assert len(provider.candidates) == 2
        assert provider.candidates[-1]["event_id"] == new_candidate["event_id"]
        assert all(row["requires_human"] is True for row in provider.candidates)
        final = tool_values(provider.requests[-1]["messages"])[-1]
        assert final["event_id"] == new_candidate["event_id"] and final["requires_human"]
        assert final["command"]["payload"]["title"] == NEW_TITLE
        assert not {"assignee_id", "recipient_id", "due_at", "deadline"}.intersection(
            final["command"]["payload"]
        )
        assert_disclosure(runtime, provider)
        write_observation(destination, observed(
            runtime, provider, [parent, old, new], focus, native_binding_status="bound",
            status="native_mechanics_passed_model_quality_not_scored",
            bindings={"source": source, "project_id": str(project),
                      "old_candidate": old_candidate, "current_candidate": new_candidate,
                      "old_event_body_digest_before_after": old_digest,
                      "read_sources_unchanged": selected_sources,
                      "business_counts_before_after": before,
                      "create_assign_receipt_delta": 0,
                      "human_inputs_unselected": ["assignee", "date"],
                      "input_contract": "Assignee belongs to separate native assign and date to "
                                        "later commitment; neither is a task-create field."},
        ), record_property)
