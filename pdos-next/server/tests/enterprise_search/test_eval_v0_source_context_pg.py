"""Model-free native source/admission observations for four V0 context scenarios.

Only root runs PG. Scripted turns select real registered reads, never supply a
scenario tool result, answer score, real usage or approval. Archive document
versions and the native registration snapshot revision remain separate.
"""

import json
import os
import re
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest
from pdos_agent_runtime.graph import in_registered_agent_graph
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bootstrap import Bootstrap, RuntimePorts
from pdos_next.agent_kernel.context_budget import TOOL_RESULT_RESERVE, budget_for, measure
from pdos_next.agent_kernel.disclosure import disclosure
from pdos_next.agent_kernel.graph import AgentKernel
from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall
from pdos_next.agent_kernel.types import ModelTurn, ToolCall, WireAgentOutput
from pdos_next.enterprise_search.assistant_graph import AssistantExtractGraph
from pdos_next.models import Artifact, ObjectAudience
from pdos_next.providers.types import ProviderUsage
from tests.agent_kernel.test_gateway import configured_route
from tests.agent_kernel.test_run_continuation import start
from tests.enterprise_search.test_eval_v0_contracts_pg import explicit_target
from tests.enterprise_search.test_retrieval_pg import index
from tests.preproject.test_g0 import post, request

ROOT = Path(__file__).resolve().parents[4]
QUESTIONS = ROOT / "docs/evaluations/xiaopai-v0/context-questions.json"
CASE_IDS = ("CTX-02", "CTX-03", "CTX-08", "CTX-12")
NOT_SCORED = ["answer_correctness", "citation_semantics", "real_usage_latency_cost"]
SECRET = "SYNT-LANTERN-47"
WIRE_FIELDS = ("system", "tools", "messages", "output_schema")
CTX12_CATEGORY = "category_scoped_read_without_fixed_pins"
CTX12_PINNED = "fixed_pins_eight_sources"
PINNED_DIAGNOSTIC = (
    ROOT / "docs/reports/evidence/pdos-next-context-native-v0-20261029/ctx12-state-diagnostic.json"
)


def cases():
    value = json.loads(QUESTIONS.read_text())
    assert value["synthetic"] is True and value["trusted_root"] is False
    return {row["id"]: row for row in value["cases"] if row["id"] in CASE_IDS}


def documents(case):
    """Explicit untrusted fixture documents, not injected trusted tool messages."""
    if case["id"] == "CTX-02":
        return [
            ("S2-A", 3, "D16接头漏气复盘 v3", "23摄氏度干燥环境、B01，胶粘剂固化不足。"),
            ("S2-B", 2, "D16装配降本 v2", "23摄氏度干燥环境，重点是材料单价。"),
            (
                "S2-C",
                1,
                "低温湿态接头记录 v1",
                "\n\n\n5摄氏度、潮湿、B04，已观察到界面渗水\n未记录根因，等待重复测量。",
            ),
        ]
    if case["id"] == "CTX-03":
        return [
            ("S3-A", 4, "V-071 v4 B03泄漏记录", "请求V-071，版本4，轮次B03；保压60秒，压降7 kPa。"),
            (
                "S3-B",
                2,
                "V-017 v2 B03泄漏记录",
                "\n" * 6 + "请求V-017，版本2，轮次B03\n保压45秒，压降11 kPa\n判据未附。",
            ),
            ("S3-C", 1, "V-017 v1 B02泄漏记录", "请求V-017，版本1，轮次B02；保压30秒，压降9 kPa。"),
        ]
    if case["id"] == "CTX-08":
        return [
            ("S8-A", 1, "银汀 R4 公开复验记录", "已登记一次接口复验；没有完成回执。"),
            ("S8-B", 1, "银汀 R4 内部讨论记录", f"内部代号{SECRET}，返工备料17套。"),
        ]
    replay = case["replay_input"]
    assert replay["repeat_each_record"] == 1
    rule = replay["expansion_rule"]
    assert rule["operation"] == "append_to_existing_turn_content"
    records = {row["record_id"]: row for row in replay["records"]}
    assert len(records) == len(replay["record_order"]) == 8
    result = []
    for identity in replay["record_order"]:
        row = records[identity]
        source = case["turns"][row[rule["target_index_field"]]]
        assert source["role"] == "tool" and len(row["lines"]) == 32
        body = (
            source["content"]
            + rule["prefix"]
            + rule["line_joiner"].join(row["lines"])
            + rule["suffix"]
        )
        result.append(
            (row["source_label"], row["source_revision"], f"泊岸 K8 {row['source_label']} v1", body)
        )
    return result


def ctx12_queries(case):
    # Exact codes locate the beginning/end chunks. Each registered citation
    # still authorizes only its own bounded region, never the entire document.
    records = {row["record_id"]: row for row in case["replay_input"]["records"]}
    ordered = [records[key] for key in case["replay_input"]["record_order"]]
    return tuple(
        " ".join(re.search(r"追溯号([A-Z0-9-]+)", row["lines"][index]).group(1) for row in ordered)
        for index in (0, -1)
    )


def pinned_control():
    from pdos_next.agent_kernel.work_state import STATE_TOKENS

    if not PINNED_DIAGNOSTIC.is_file():
        return {"diagnostic": str(PINNED_DIAGNOSTIC.relative_to(ROOT)), "available": False}
    rows = json.loads(PINNED_DIAGNOSTIC.read_text())["runs"]
    return {
        "diagnostic": str(PINNED_DIAGNOSTIC.relative_to(ROOT)),
        "available": True,
        "binding_variant": CTX12_PINNED,
        "status": "CONTEXT_INCOMPLETE",
        "state_cap_tokens": STATE_TOKENS,
        "state_tokens": [row["work_state"]["estimated_tokens"] for row in rows],
        "fixed_selection_tokens": [
            measure_body(json.dumps(row["work_state"]["context_selection"], ensure_ascii=False))
            for row in rows
        ],
        "cause": "eight explicit UI source selections plus inherited state exceed STATE_TOKENS",
    }


def merged_span(intervals, expected_chars):
    reached = 0
    for first, last in sorted(intervals):
        assert first <= reached, (reached, first, last)
        reached = max(reached, last)
    assert reached == expected_chars
    return reached


def observed_spans(intervals, expected_chars):
    """Union actual native ranges; a stop must retain its exact missing ranges."""
    reached, count, missing = 0, 0, []
    for first, last in sorted(intervals):
        assert 0 <= first <= last <= expected_chars
        if first > reached:
            missing.append({"char_start": reached, "char_end": first})
        count += max(0, last - max(reached, first))
        reached = max(reached, last)
    if reached < expected_chars:
        missing.append({"char_start": reached, "char_end": expected_chars})
    return {"complete": not missing, "read_union_chars": count,
            "missing_intervals": missing}


def actual_source_coverage(owner, scope, issued, sources, case, *, require_complete=True):
    """Prove full bodies from actual native passage locators, not predicted windows."""
    by_cid = {item["citation_id"]: item for item in issued}
    bodies = {sources[label]["artifact_id"]: body for label, _, _, body in documents(case)}
    by_source = {row["artifact_id"]: row for row in sources.values()}
    spans, calls = {identity: [] for identity in bodies}, {identity: [] for identity in bodies}
    with owner.store.transaction(scope) as (session, run):
        assert run.read_sources == []
        assert run.versions["requested_context_selection"] is None
        for call in session.scalars(
            select(AgentToolCall).where(
                AgentToolCall.run_id == run.id,
                AgentToolCall.tool == "assistant.passage.read",
                AgentToolCall.state == "completed",
            )
        ):
            assert call.execution_binding["kind"] == "read"
            assert call.execution_binding["isolation"] == "assistant_extract"
            page = call.result
            item = by_cid[page["citation_id"]]
            identity = item["source_id"]
            assert page["content_hash"] == by_source[identity]["content_sha256"]
            assert page["source_revision"] == by_source[identity]["artifact_snapshot_revision"]
            first, last = page["locator"]["char_start"], page["locator"]["char_end"]
            assert page["text"] == bodies[identity][first:last]
            spans[identity].append((first, last))
            calls[identity].append({"call_id": str(call.id), "char_start": first, "char_end": last})
    result = {}
    for identity, intervals in spans.items():
        length = len(bodies[identity])
        coverage = observed_spans(intervals, length)
        if require_complete:
            assert coverage["read_union_chars"] == merged_span(intervals, length)
            assert coverage["complete"]
        result[identity] = {"complete": coverage["complete"], "body_chars": length,
                            "read_union_chars": coverage["read_union_chars"],
                            "passage_reads": calls[identity],
                            **({"missing_intervals": coverage["missing_intervals"]}
                               if not require_complete else {})}
    return result


def route_for(focus):
    return replace(
        configured_route(),
        max_output_tokens=2048,
        context_window_tokens=focus + 2048 + TOOL_RESULT_RESERVE,
    )


def write_observation(value, directory=None):
    target = (
        directory if directory is not None else os.environ.get("PDOS_CONTEXT_NATIVE_OUTPUT_DIR")
    )
    if target is None:
        return
    root = Path(target)
    assert root.is_absolute() and root.is_dir(), "Root must precreate the absolute output directory"
    destination = root / f"{value['case_id']}-F{value['f_budget_tokens']}.json"
    # Never overwrite a prior observation or silently create a new evidence root.
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def decoded_results(messages):
    """Rebuild only actual JSON result pages; previews never prove full coverage."""
    values = [json.loads(row["content"]) for row in messages if row["role"] == "tool"]
    if not values:
        return [], None
    fragments = {}
    for value in values:
        if value.get("format") == "json_fragment":
            fragments.setdefault(value["result_handle"], {})[value["page"]] = value
    latest = values[-1]
    if latest.get("format") == "json_fragment":
        pages = fragments[latest["result_handle"]]
        missing = [
            i
            for i in range(1, latest["total_pages"] + 1)
            if i not in pages or "preview" not in pages[i]
        ]
        if missing:
            return [], {"handle": latest["result_handle"], "page": missing[0]}
    decoded, seen = [], set()
    for value in values:
        if value.get("format") != "json_fragment":
            decoded.append(value)
            continue
        handle = value["result_handle"]
        if handle in seen:
            continue
        pages = fragments[handle]
        if all(i in pages and "preview" in pages[i] for i in range(1, value["total_pages"] + 1)):
            decoded.append(
                json.loads("".join(pages[i]["preview"] for i in range(1, value["total_pages"] + 1)))
            )
            seen.add(handle)
    return decoded, None


class ScriptedSourceProvider:
    """Only routes real selectors/pages and copies bounded actually read quotes."""

    def __init__(
        self, sources, *, search=None, selected=None, cite=None, extract=True, private_summary=False
    ):
        self.sources, self.search, self.selected, self.cite = sources, search, selected, cite
        self.searches = list(search) if isinstance(search, tuple) else [search]
        self.extracted_batches = 0
        self.extract, self.private_summary = extract, private_summary
        self.requests, self.issued, self.evidence, self.coverage = [], [], [], []

    def close(self):
        pass

    @staticmethod
    def call(name, arguments):
        return ModelTurn(
            calls=(ToolCall(id="scripted-" + name, name=name, arguments=arguments),),
            usage=ProviderUsage(0, 0),
        )

    def turn(self, route, **request):
        assert in_registered_agent_graph()
        # emit and other host callbacks are framework plumbing, never model input.
        request = {key: deepcopy(request[key]) for key in WIRE_FIELDS}
        names = {item["name"] for item in request["tools"]}
        child = names == {"assistant.passage.read", "result.read"}
        self.requests.append(
            {"isolation": "assistant_extract" if child else "main", "route": route, **request}
        )
        messages = request["messages"]
        values, pending = decoded_results(messages)
        if pending is not None:
            return self.call("result.read", pending)
        if child:
            cid = json.loads(messages[0]["content"])["context"]["citation_id"]
            pages = [
                value for value in values if value.get("citation_id") == cid and "text" in value
            ]
            if not pages or pages[-1]["next_cursor"] is not None:
                return self.call(
                    "assistant.passage.read",
                    {
                        "citation_id": cid,
                        "cursor": pages[-1]["next_cursor"] if pages else 0,
                        "page_chars": 2000,
                    },
                )
            quotes = [line for line in pages[0]["text"].splitlines() if line.strip()][:2]
            result = {
                "rows": [
                    {"citation_id": cid, "statement": "脚本复制的已读原句。", "quote": quote[:1000]}
                    for quote in quotes
                ]
            }
            summary = "脚本读取完毕，不评价模型答案。"
        else:
            assert "assistant.passage.read" not in names
            if not values:
                if self.search is not None:
                    return self.call("assistant.search", {"query": self.searches[0], "limit": 8})
                return self.call(
                    "assistant.materials.read",
                    {
                        "artifact_ids": [row["artifact_id"] for row in self.sources.values()],
                    },
                )
            latest = values[-1]
            assert not latest.get("error"), latest
            if "items" in latest:
                self.issued.extend(deepcopy(latest["items"]))
                if self.extract:
                    ids = [
                        item["citation_id"]
                        for item in latest["items"]
                        if self.selected is None or item["source_id"] in self.selected
                    ]
                    assert ids
                    return self.call("assistant.extract", {"citation_ids": ids})
                self.evidence = []
            else:
                assert "rows" in latest and not latest.get("failures"), latest
                self.evidence.extend(deepcopy(latest["rows"]))
                self.coverage.extend(deepcopy(latest.get("coverage", [])))
                self.extracted_batches += 1
                if self.extracted_batches < len(self.searches):
                    return self.call(
                        "assistant.search",
                        {
                            "query": self.searches[self.extracted_batches],
                            "limit": 8,
                        },
                    )
            by_id = {item["citation_id"]: item["source_id"] for item in self.issued}
            ids = list(
                dict.fromkeys(
                    row["citation_id"]
                    for row in self.evidence
                    if self.cite is None or by_id[row["citation_id"]] in self.cite
                )
            )
            result = {"assistant": {"citation_ids": ids}} if self.extract else {}
            summary = "脚本完成真实读取控制流；不输出任务答案。"
            if self.private_summary:
                private = self.sources["S8-B"]["artifact_id"]
                summary = next(
                    row["quote"] for row in self.evidence if by_id[row["citation_id"]] == private
                )
        return ModelTurn(
            structured={
                "status": "completed",
                "summary": summary,
                "result": result,
                "questions": [],
                "unfinished": [],
            },
            usage=ProviderUsage(0, 0),
        )


def register_sources(setup, case):
    result, audience_id = {}, None
    for label, version, title, body in documents(case):
        private = label == "S8-B"
        response = post(
            setup,
            request(
                setup,
                "evidence.artifact.register",
                {
                    "title": title,
                    "content": body,
                    "source_label": label,
                    "visibility": "audience" if private else "category",
                },
            ),
            actor=setup.peer if private else setup.human,
        )
        assert response.status_code == 200, response.text
        identity = UUID(response.json()["subject_id"])
        if private:
            with Session(setup.admin) as session, session.begin():
                audience = ObjectAudience(
                    tenant_id=setup.tenant,
                    category_id=setup.category,
                    object_type="artifact_versions",
                    subject_id=identity,
                    owner_id=setup.peer,
                    principal_id=setup.human,
                )
                session.add(audience)
                session.flush()
                audience_id = audience.id
        index(setup, identity)
        with Session(setup.admin) as session:
            row = session.get(Artifact, identity)
            assert row.revision == 1 and row.content == body
            result[label] = {
                "artifact_id": str(identity),
                "artifact_snapshot_revision": row.revision,
                "archive_declared_version": version,
                "content_sha256": row.content_hash,
                "body_chars": len(body),
                "body_utf8_bytes": len(body.encode()),
                "body_estimated_tokens": measure_body(body),
            }
    return result, audience_id


def measure_body(body):
    from pdos_next.agent_kernel.context_budget import estimate_tokens

    return estimate_tokens(body)


def run_native(
    setup, provider, focus, goal, *, sources=(), parent=None, personal=False, deep=False
):
    options = (
        {"continue_from_run_id": str(parent)}
        if parent
        else {
            "sources": [
                {
                    "artifact_id": row["artifact_id"],
                    "expected_revision": row["artifact_snapshot_revision"],
                }
                for row in sources
            ]
        }
    )
    if deep:
        options["lookup_depth"] = "deep"
    identity, response = start(setup, personal=personal, goal=goal, **options)
    # A fixture-only total accounting allowance is independent of the unchanged
    # production per-request context window, depth limits and full disclosure.
    with Session(setup.admin) as session, session.begin():
        run = session.get(AgentRun, identity)
        assert run.state == "queued"
        run.token_limit = 2_000_000
    owner = Bootstrap(
        setup.engine, ports=RuntimePorts(provider_client=provider, preload=lambda _: ())
    )
    owner.route_for = lambda _: route_for(focus)
    owner.provider_for = lambda *_: "synthetic-context-no-egress"
    scope = owner.store.scope(
        tenant_id=setup.tenant,
        requester_id=setup.human,
        writer_id=setup.agent,
        category_id=None if personal else setup.category,
        run_id=identity,
    )
    host = BoundHost(owner.store, replace(owner.adapters(), cost_required=False))
    owner._assistant_adapter.graph = AssistantExtractGraph(host, owner._assistant_adapter)
    kernel = AgentKernel(host, owner.registry)
    output = kernel.execute(scope, goal=goal, execution_key={"native_context": str(identity)})[
        "output"
    ]
    main = [item for item in provider.requests if item["isolation"] == "main"]
    if main:
        assert main[0]["system"] == kernel.system
        assert main[0]["tools"] == disclosure(owner.registry)
        assert main[0]["output_schema"] == WireAgentOutput.model_json_schema()
    return owner, scope, output, response


def observation(owner, scope, provider, *, phase):
    budgets, reads = [], []
    with owner.store.transaction(scope) as (session, run):
        for call in session.scalars(
            select(AgentToolCall)
            .where(AgentToolCall.run_id == scope.run_id)
            .order_by(AgentToolCall.created_at, AgentToolCall.id)
        ):
            if call.tool == "model" and call.state == "completed":
                budgets.append(
                    {
                        "phase": phase,
                        "call_id": str(call.id),
                        "isolation": call.execution_binding["isolation"],
                        **deepcopy(call.result["context_budget"]),
                        "actual_usage_source": "scripted_zero_placeholder_not_real_usage",
                    }
                )
            elif call.execution_binding.get("kind") == "read" and call.state == "completed":
                reads.append(
                    {
                        "call_id": str(call.id),
                        "tool": call.tool,
                        "binding": deepcopy(call.execution_binding),
                        "source_revision": (call.result or {}).get("source_revision"),
                        "content_hash": (call.result or {}).get("content_hash"),
                    }
                )
        versions = deepcopy(run.versions)
        assert run.held_tokens == run.used_tokens == 0
    main = [item for item in provider.requests if item["isolation"] == "main"]
    envelope = json.loads(main[0]["messages"][0]["content"]) if main else {}
    context = envelope.get("context", {})
    history = context.get("conversation", versions.get("conversation_memory", {}))
    work = context.get("work_state", versions.get("work_state", {}))
    return {
        "budgets": budgets,
        "reads": reads,
        "run_id": str(scope.run_id),
        "dispatches": len(provider.requests),
        "main_dispatches": len(main),
        "main_request_bytes": [
            len(
                json.dumps(
                    {
                        key: value
                        for key, value in item.items()
                        if key not in {"route", "isolation"}
                    },
                    ensure_ascii=False,
                ).encode()
            )
            for item in main
        ],
        "history": [
            {
                "run_id": turn["run_id"],
                "outcome_state": turn["outcome_state"],
                "has_outcome": turn["historical_outcome"] is not None,
                "has_sources": bool(turn["sources"]),
            }
            for turn in history.get("turns", [])
        ],
        "work_state": {
            key: work.get(key)
            for key in ("revision", "estimated_tokens", "context_incomplete", "notes", "missing")
        },
        "context_snapshots_recorded": bool(versions.get("context_snapshots")),
    }


def record_admission_stop(case_id, focus, sources, output, observations, *, variant=None,
                          controls=None, issued_citations=None):
    """A production budget refusal is an observed stop, never a scenario pass."""
    assert output.get("result", {}).get("context_incomplete") is True, output
    budgets = [item for value in observations for item in value["budgets"]]
    failed = output["result"].get("context_budget")
    if failed:
        budgets.append({"phase": "admission_stop", "isolation": "main", **failed})
    write_observation(
        {
            "version": "context-native-observation/v1",
            "case_id": case_id,
            "f_budget_tokens": focus,
            "native_binding_status": "partial",
            "status": "CONTEXT_INCOMPLETE",
            "binding_variant": variant,
            "scripted_provider": True,
            "real_model_calls": 0,
            "provider_dispatches": sum(value["dispatches"] for value in observations),
            "context_budget": budgets,
            "bindings": {
                "sources": sources,
                "read_calls": [row for value in observations for row in value["reads"]],
                **({"issued_citations": issued_citations} if issued_citations is not None else {}),
            },
            "model_quality_score": None,
            "not_scored": NOT_SCORED,
            "scenario_completion_observed": False,
            **({"controls": controls} if controls is not None else {}),
            "missing": output["result"].get("missing", []),
            "work_state": [value["work_state"] for value in observations],
            **({"pinned_eight_source_control": pinned_control()} if case_id == "CTX-12" else {}),
        }
    )


@pytest.mark.parametrize("case_id", CASE_IDS)
@pytest.mark.parametrize("focus", [48000, 64000])
@pytest.mark.skipif(not explicit_target(), reason="Root must bind guarded isolated 53502/pdos_test")
def test_eval_v0_native_source_context_admission(setup, case_id, focus):
    case = cases()[case_id]
    variant = (
        os.environ.get("PDOS_CTX12_BINDING_VARIANT", CTX12_CATEGORY)
        if case_id == "CTX-12"
        else "native_source_context"
    )
    assert case_id != "CTX-12" or variant in {CTX12_CATEGORY, CTX12_PINNED}
    category_read = case_id == "CTX-12" and variant == CTX12_CATEGORY
    sources, audience = register_sources(setup, case)
    personal = case_id in {"CTX-03", "CTX-08"}
    search = {"CTX-03": "V-017 V-071", "CTX-08": "银汀 R4"}.get(case_id)
    if category_read:
        search = ctx12_queries(case)[0]
    cited = {sources["S8-A"]["artifact_id"]} if case_id == "CTX-08" else None
    seed = ScriptedSourceProvider(
        sources,
        search=search,
        cite=cited,
        extract=case_id != "CTX-12",
        private_summary=case_id == "CTX-08",
    )
    user_goals = [turn["content"] for turn in case["turns"] if turn["role"] == "user"]
    goal = "\n".join(user_goals[:-1] or user_goals)
    owner, scope, prior, _response = run_native(
        setup,
        seed,
        focus,
        goal,
        sources=() if personal or category_read else sources.values(),
        personal=personal,
    )
    first = observation(owner, scope, seed, phase="native_history")
    if prior["status"] != "completed":
        record_admission_stop(case_id, focus, sources, prior, [first], variant=variant)
        return
    controls = {
        "scenario_tool_text_injected_as_trusted_result": False,
        "scenario_assistant_transcript_injected": False,
    }
    if case_id == "CTX-08":
        answer = prior["result"]["assistant"]
        assert {row["source_id"] for row in answer["sources"]} == cited
        assert SECRET in prior["summary"]
        with owner.store.transaction(scope) as (session, run):
            assert run.read_sources == []
            passages = [
                call.result["text"]
                for call in session.scalars(
                    select(AgentToolCall).where(
                        AgentToolCall.run_id == run.id,
                        AgentToolCall.tool == "assistant.passage.read",
                    )
                )
            ]
            assert any(SECRET in body for body in passages)
        with Session(setup.admin) as session, session.begin():
            session.delete(session.get(ObjectAudience, audience))
        controls.update(
            private_body_actually_read=True, private_final_citation=False, audience_withdrawn=True
        )
    target = {sources["S3-B"]["artifact_id"]} if case_id == "CTX-03" else cited
    # CTX08 re-searches only the still-readable public source after withdrawal.
    current_search = "V-017" if case_id == "CTX-03" else search
    if category_read:
        current_search = ctx12_queries(case)
    provider = ScriptedSourceProvider(sources, search=current_search, selected=target, cite=target)
    next_goal = "\n".join([user_goals[-1], case["final_prompt"]])
    current, bound, output, response = run_native(
        setup,
        provider,
        focus,
        next_goal,
        parent=scope.run_id,
        personal=personal,
        deep=case_id == "CTX-12",
    )
    second = observation(current, bound, provider, phase="final_prompt")
    if output["status"] != "completed":
        if case_id == "CTX-12" and category_read:
            coverage = actual_source_coverage(
                current, bound, provider.issued, sources, case, require_complete=False,
            )
            main_text = str([item["messages"] for item in provider.requests
                             if item["isolation"] == "main"])
            assert all(record["lines"][0] not in main_text
                       for record in case["replay_input"]["records"])
            controls.update(
                actual_source_read_coverage=coverage,
                eight_expanded_documents_read_in_isolated_graph=all(
                    row["complete"] for row in coverage.values()),
                completed_extraction_ranges=deepcopy(provider.coverage),
                final_answer_completed=False,
                full_completion=False,
            )
            record_admission_stop(case_id, focus, sources, output, [first, second], variant=variant,
                                  controls=controls,
                                  issued_citations={"history": seed.issued,
                                                    "final": provider.issued})
        else:
            record_admission_stop(case_id, focus, sources, output, [first, second], variant=variant)
        return
    assert response["session_id"] == str(scope.session_id)
    assert first["context_snapshots_recorded"] and second["context_snapshots_recorded"]
    if case_id == "CTX-03":
        candidates = {item["source_id"]: item for item in provider.issued}
        assert candidates[sources["S3-B"]["artifact_id"]]["channel"] == "exact_code"
        assert sources["S3-C"]["artifact_id"] in candidates
        assert {item["source_id"] for item in output["result"]["assistant"]["sources"]} == target
        controls["exact_archive_identifier_selected"] = True
    if case_id == "CTX-08":
        assert second["history"][0]["outcome_state"] == "hidden"
        assert not second["history"][0]["has_outcome"] and not second["history"][0]["has_sources"]
        assert SECRET not in str(provider.requests) and SECRET not in str(output)
        assert {item["source_id"] for item in provider.issued} == cited
        controls["secret_occurrences_in_new_provider_history"] = 0
    if case_id == "CTX-12":
        main_text = str(
            [item["messages"] for item in provider.requests if item["isolation"] == "main"]
        )
        for record in case["replay_input"]["records"]:
            assert record["lines"][0] not in main_text
        citations = 16 if category_read else 8
        assert len(provider.issued) == citations
        assert len({row["citation_id"] for row in provider.evidence}) == citations
        assert len(provider.coverage) == citations
        assert all(
            row["complete"] and row["read_chars"] == row["range_chars"] for row in provider.coverage
        )
        controls["eight_expanded_documents_read_in_isolated_graph"] = True
        if category_read:
            assert all(item["channel"] == "exact_code" for item in provider.issued)
            controls["actual_source_read_coverage"] = actual_source_coverage(
                current, bound, provider.issued, sources, case
            )
            controls["native_lookup_profile"] = {
                "history": "quick: one directory search, no extraction",
                "final": "deep: two searches, eight distinct fixed sources",
            }
    for phase_provider in (seed, provider):
        for item in phase_provider.requests:
            measured = measure(
                item["route"],
                item["system"],
                item["tools"],
                item["messages"],
                item["output_schema"],
            )
            assert measured["focus"] == focus and not measured["over_focus"]
    budgets = first["budgets"] + second["budgets"]
    main_budgets = [row for row in budgets if row["isolation"] == "main"]
    pressure = any(row.get("reductions") for row in main_budgets)
    value = {
        "version": "context-native-observation/v1",
        "case_id": case_id,
        "f_budget_tokens": focus,
        "native_binding_status": "bound",
        "status": "native_control_checks_passed",
        "binding_variant": variant,
        "scripted_provider": True,
        "real_model_calls": 0,
        "provider_dispatches": first["dispatches"] + second["dispatches"],
        "context_budget": budgets,
        "bindings": {
            "sources": sources,
            "read_calls": first["reads"] + second["reads"],
            "issued_citations": {"history": seed.issued, "final": provider.issued},
        },
        "model_quality_score": None,
        "not_scored": NOT_SCORED,
        "pressure_comparison": "triggered" if pressure else "not_triggered",
        "native_history": first["history"],
        "final_history": second["history"],
        "work_state": {"history": first["work_state"], "final": second["work_state"]},
        "main_request_bytes": first["main_request_bytes"] + second["main_request_bytes"],
        "controls": controls,
        **({"pinned_eight_source_control": pinned_control()} if case_id == "CTX-12" else {}),
        "limits": [
            "Archive versions are document claims; native artifact registrations are revision 1.",
            "Real linked history replaces scenario prose; not literal transcript replay.",
            "Scripted zero usage is a placeholder, never real usage or calibration evidence.",
            "No answer/citation/pressure-benefit/latency/cost/live-provider score.",
        ],
    }
    write_observation(value)


@pytest.mark.parametrize("focus", [48000, 64000])
def test_native_focus_profiles_keep_actual_output_and_tool_reserves(focus):
    route = route_for(focus)
    assert budget_for(route)["focus"] == focus
    assert route.max_output_tokens == 2048
    assert route.context_window_tokens == focus + 6048


def test_expansion_registers_eight_distinct_documents_once_without_injecting_transcript():
    case = cases()["CTX-12"]
    docs = documents(case)
    assert len(docs) == len({row[0] for row in docs}) == 8
    assert sum(len(row[3]) for row in docs) > 30_000
    for _label, revision, _title, body in docs:
        assert revision == 1 and body.count("附录32") == 1
    assert all(SECRET not in row[3] for row in documents(cases()["CTX-03"]))


def test_output_is_exclusive_and_does_not_create_unapproved_directory(tmp_path):
    value = {"case_id": "CTX-02", "f_budget_tokens": 48000}
    write_observation(value, str(tmp_path))
    with pytest.raises(FileExistsError):
        write_observation(value, str(tmp_path))
    with pytest.raises(AssertionError):
        write_observation(value, str(tmp_path / "not-created"))
    assert not (tmp_path / "not-created").exists()


def test_result_pages_require_every_original_fragment_before_decoding():
    from pdos_next.agent_kernel.result_continuation import page_view

    original = {"rows": [{"quote": "隔离原句" * 800}], "coverage": {"complete": True}}
    handle = "result:00000000-0000-0000-0000-000000000001:" + "a" * 64
    first = page_view(original, handle, 1, cap=1000)
    messages = [{"role": "tool", "content": json.dumps(first, ensure_ascii=False)}]
    decoded, pending = decoded_results(messages)
    assert decoded == [] and pending == {"handle": handle, "page": 2}
    for page in range(2, first["total_pages"] + 1):
        messages.append(
            {
                "role": "tool",
                "content": json.dumps(
                    page_view(original, handle, page, cap=1000), ensure_ascii=False
                ),
            }
        )
    decoded, pending = decoded_results(messages)
    assert decoded == [original] and pending is None


def test_provider_capture_excludes_emit_and_preserves_only_actual_wire_fields():
    from pdos_agent_runtime.graph import registered_graph_context

    provider = ScriptedSourceProvider({}, search="V-017")
    wire = {
        "system": "fixed",
        "tools": [{"name": "assistant.search"}],
        "messages": [{"role": "user", "content": "native goal"}],
        "output_schema": {"type": "object"},
    }
    with registered_graph_context("xiaopai"):
        provider.turn(route_for(48000), **wire, emit=lambda _: None)
    captured = {
        key: value
        for key, value in provider.requests[0].items()
        if key not in {"route", "isolation"}
    }
    assert captured == wire and set(captured) == set(WIRE_FIELDS)
    assert json.loads(json.dumps(captured)) == wire


def test_ctx12_window_plan_uses_exact_trace_codes_and_keeps_complete_native_spans():
    """Plan check only; the PG case separately proves actual ledger interval union."""
    from pdos_next.enterprise_search.indexing import chunks

    case = cases()["CTX-12"]
    queries = ctx12_queries(case)
    assert len(queries) == 2 and all(len(query.split()) == 8 for query in queries)
    for ordinal, (_label, _version, _title, body) in enumerate(documents(case)):
        intervals = []
        for query in queries:
            code = query.split()[ordinal]
            locations = [locator for text, locator in chunks(body) if code in text]
            assert len(locations) == 1
            location = locations[0]
            intervals.append(
                (max(0, location["char_start"] - 1000), min(len(body), location["char_end"] + 1000))
            )
        assert merged_span(intervals, len(body)) == len(body)


def test_actual_coverage_union_rejects_a_gap_without_counting_duplicate_chars():
    assert merged_span([(0, 2000), (1900, 3000), (100, 200)], 3000) == 3000
    with pytest.raises(AssertionError):
        merged_span([(0, 2000), (2001, 3000)], 3000)
    with pytest.raises(AssertionError):
        merged_span([(0, 2000)], 3000)


def test_admission_stop_coverage_preserves_actual_union_and_missing_ranges():
    assert observed_spans([(0, 2000), (1900, 3000), (100, 200)], 3000) == {
        "complete": True, "read_union_chars": 3000, "missing_intervals": []}
    assert observed_spans([(0, 2000), (2001, 2999)], 3000) == {
        "complete": False, "read_union_chars": 2998,
        "missing_intervals": [{"char_start": 2000, "char_end": 2001},
                              {"char_start": 2999, "char_end": 3000}]}
    assert observed_spans([], 3000) == {
        "complete": False, "read_union_chars": 0,
        "missing_intervals": [{"char_start": 0, "char_end": 3000}]}


def test_admission_stop_records_read_coverage_without_promoting_completion(monkeypatch):
    saved = []
    monkeypatch.setattr(__import__(__name__, fromlist=["write_observation"]),
                        "write_observation", saved.append)
    controls = {"actual_source_read_coverage": {"actual-native-id": {
        "complete": True, "body_chars": 4695, "read_union_chars": 4695}},
        "full_completion": False, "final_answer_completed": False}
    issued = {"history": [], "final": [{"citation_id": "actual-issued-id"}]}
    record_admission_stop("CTX-12", 48000, {}, {"result": {
        "context_incomplete": True, "context_budget": {"focus": 48000, "admission_tokens": 48298},
        "missing": [{"field": "messages[8]"}]}},
        [{"budgets": [], "dispatches": 54, "reads": [], "work_state": {}}],
        variant=CTX12_CATEGORY, controls=controls, issued_citations=issued)
    assert len(saved) == 1
    value = saved[0]
    assert value["native_binding_status"] == "partial" and value["status"] == "CONTEXT_INCOMPLETE"
    assert value["scenario_completion_observed"] is False and value["model_quality_score"] is None
    assert value["controls"] == controls and value["bindings"]["issued_citations"] == issued
    assert value["context_budget"][-1]["admission_tokens"] == 48298


def test_multiple_search_controller_retains_only_rows_from_each_supplied_result():
    """Pure sequencing test; these unsigned messages make no native READ claim."""
    from pdos_agent_runtime.graph import registered_graph_context

    provider = ScriptedSourceProvider({}, search=("first trace", "last trace"))
    messages = [{"role": "user", "content": "{}"}]
    wire = {
        "system": "fixed",
        "tools": [{"name": "assistant.search"}],
        "output_schema": {"type": "object"},
        "messages": messages,
    }
    with registered_graph_context("xiaopai"):
        assert provider.turn(route_for(48000), **wire).calls[0].arguments["query"] == "first trace"
        for index in (1, 2):
            cid = f"00000000-0000-0000-0000-{index:012d}"
            messages.append(
                {
                    "role": "tool",
                    "content": json.dumps(
                        {"items": [{"citation_id": cid, "source_id": "unit-source"}]}
                    ),
                }
            )
            assert provider.turn(route_for(48000), **wire).calls[0].name == "assistant.extract"
            messages.append(
                {
                    "role": "tool",
                    "content": json.dumps(
                        {
                            "rows": [{"citation_id": cid, "quote": f"supplied page {index}"}],
                            "coverage": [{"complete": True}],
                        }
                    ),
                }
            )
            turn = provider.turn(route_for(48000), **wire)
            if index == 1:
                assert turn.calls[0].arguments["query"] == "last trace"
            else:
                assert len(turn.structured["result"]["assistant"]["citation_ids"]) == 2
    assert len(provider.issued) == len(provider.evidence) == len(provider.coverage) == 2
