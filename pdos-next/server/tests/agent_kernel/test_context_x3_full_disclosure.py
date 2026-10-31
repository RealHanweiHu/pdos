"""Offline registered-graph capacity proof, with the unchanged full initial face.

The provider, reads, receipts and citations below are explicitly synthetic. This
tests disclosure/admission/cleanup/checkpoint mechanics, not model correctness,
real provider window support, durable PG provenance or execution of all 61 tools.
"""

import json
import math
from copy import deepcopy
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pdos_next.agent_kernel.context_budget import estimate_tokens, fit_messages
from pdos_next.agent_kernel.context_runtime import protected_result
from pdos_next.agent_kernel.disclosure import disclosure, record_disclosure
from pdos_next.agent_kernel.graph import AgentKernel
from pdos_next.agent_kernel.result_continuation import handle_for, page_view
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.agent_kernel.types import ModelTurn, RunScope, ToolCall, WireAgentOutput
from pdos_next.errors import DomainError
from pdos_next.providers.types import ProviderRoute
from pdos_next.service import digest
from pydantic import SecretStr

GOAL = "只核对合成密封圈措施；保留回执、依据和错误，等本人继续。"
CONSTRAINT = "只核对合成密封圈措施"
CAPACITY_TOKENS = 3_300
SYNTHETIC_CITATION = str(uuid5(NAMESPACE_URL, "x3-full-face-synthetic-citation"))
SYNTHETIC_RECEIPT = {
    "id": str(uuid5(NAMESPACE_URL, "x3-full-face-synthetic-receipt")),
    "operation": "evidence.artifact.register",
    "subject_id": str(uuid5(NAMESPACE_URL, "x3-full-face-synthetic-artifact")),
    "result": {"revision": 1, "test_only": True},
}


def route(window):
    return ProviderRoute(
        "openai-compatible", "https://synthetic-provider.test/v1", "synthetic-model",
        SecretStr("synthetic-not-a-real-secret"), "synthetic-x3-full-face@1",
        max_output_tokens=1_024, context_window_tokens=window,
    )


def values(messages):
    for message in messages:
        try:
            value = json.loads(message.get("content") or "{}")
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            yield message, value


def tool_values(messages):
    return {row["tool_call_id"]: value for row, value in values(messages)
            if row["role"] == "tool"}


class ScriptedProvider:
    """No transport/tokenizer; scripted outputs test mechanics, never quality."""

    def __init__(self, *, recovery=False):
        self.recovery, self.calls, self.messages = recovery, 0, []
        self.handle = None

    def turn(self, configured, *, system, tools, messages, output_schema):
        from pdos_agent_runtime.graph import in_registered_agent_graph

        assert in_registered_agent_graph()
        assert configured.base_url == "https://synthetic-provider.test/v1"
        assert tools == disclosure(default_registry(), "main", ())
        assert len(tools) == 61
        assert output_schema == WireAgentOutput.model_json_schema()
        self.messages.append(deepcopy(messages))
        phase, self.calls = self.calls, self.calls + 1
        rows = list(tool_values(messages).values())

        def calls(items):
            return ModelTurn(calls=tuple(ToolCall(
                id=f"synthetic-{phase}-{index}", name=name, arguments=arguments,
            ) for index, (name, arguments) in enumerate(items)))

        def answer(status="completed", questions=()):
            # Derive only from the protected synthetic evidence still visible.
            extracted = [row for value in rows for row in value.get("rows", [])]
            assert extracted == [{"citation_id": SYNTHETIC_CITATION,
                                  "statement": "更换密封圈", "quote": "更换密封圈"}]
            assert any(value.get("prior_human_receipt") == SYNTHETIC_RECEIPT for value in rows)
            assert any(value.get("error", {}).get("code") == "VALIDATION_FAILED"
                       for value in rows)
            return ModelTurn(structured={
                "status": status, "summary": extracted[0]["statement"],
                "result": {"synthetic_citation_ids": [extracted[0]["citation_id"]]},
                "questions": list(questions), "unfinished": [],
            })

        if self.recovery:
            assert any(value.get("answers") == {"continue": "继续"}
                       for _row, value in values(messages))
            assert any(value.get("omitted") for value in rows)
            return answer()
        if phase == 0:
            return calls([
                ("category.read", {}),
                ("category.parameters.list", {"parameter_ids": [], "cursor": "bad-cursor"}),
                ("assistant.extract", {"citation_ids": [SYNTHETIC_CITATION]}),
            ])
        if phase in {1, 2, 3}:
            offset = (phase - 1) * 3 + 1
            return calls([("category.parameters.list", {
                "parameter_ids": [], "page_size": number,
            }) for number in range(offset, offset + 3)])
        if phase == 4:
            omitted = next(value for value in rows if value.get("omitted"))
            self.handle = omitted["result_handle"]
            return calls([("result.read", {"handle": self.handle, "page": 1})])
        assert phase == 5
        return answer("needs_input", [{
            "id": "continue", "question": "继续合成检查？", "why": "只测试内存恢复。",
            "options": [], "recommended": None, "allow_free_text": True, "depends_on": [],
        }])


class OfflineHost:
    """Pure ports around the production graph; no DB, KMS, network or receipts."""

    def __init__(self, window, provider):
        self.route, self.provider = route(window), provider
        self.registry = default_registry()
        self.budgets, self.originals, self.reads, self.events = [], {}, [], []
        self.prefixes, self.disclosures, self.versions = [], [], {}
        self.requests = []

    def current(self, _scope):
        pass

    def context(self, _scope, _goal):
        return {"work_state": {
            "revision": 1, "current_goal": GOAL, "constraints": [{"text": CONSTRAINT}],
            "citations": [{"citation_id": SYNTHETIC_CITATION}],
        }}

    def enabled(self, *_args):
        return True

    def model_step(self, _scope, *, loaded_skills=(), **kwargs):
        assert loaded_skills == ()
        self.prefixes.append(kwargs["system"])
        self.disclosures.append(deepcopy(kwargs["tools"]))
        self.requests.append(deepcopy(kwargs["messages"]))
        self.versions["tool_disclosures"] = record_disclosure(
            self.versions, "main", [item["name"] for item in kwargs["tools"]],
            digest(kwargs["tools"]),
        )
        admitted, budget = fit_messages(
            self.route, kwargs["system"], kwargs["tools"], kwargs["messages"],
            kwargs["output_schema"], allow_envelope=True, compact_tool=self.compact,
        )
        self.budgets.append(deepcopy(budget))
        return self.provider.turn(self.route, **{**kwargs, "messages": admitted}), admitted

    def read(self, _scope, spec, arguments, _intent):
        assert spec == self.registry.get(spec.name)
        self.reads.append((spec.name, deepcopy(arguments)))
        if spec.name == "category.read":
            return {"test_only": True, "prior_human_receipt": deepcopy(SYNTHETIC_RECEIPT)}
        if spec.name == "assistant.extract":
            assert arguments == {"citation_ids": [SYNTHETIC_CITATION]}
            return {"test_only": True, "rows": [{"citation_id": SYNTHETIC_CITATION,
                    "statement": "更换密封圈", "quote": "更换密封圈"}]}
        if spec.name == "result.read":
            assert arguments["page"] == 1
            return page_view(self.originals[arguments["handle"]], arguments["handle"], 1, 3_936)
        assert spec.name == "category.parameters.list" and arguments["parameter_ids"] == []
        if arguments.get("cursor") == "bad-cursor":
            raise DomainError("VALIDATION_FAILED", "Synthetic invalid cursor")
        number = arguments["page_size"]
        value = {"items": [], "next_cursor": None, "synthetic_capacity": {
            "purpose": "context-cleanup-test-only", "number": number,
            "irrelevant_text": "无关运输容量；不得据此更改措施或执行写入。",
            "body": "容" * CAPACITY_TOKENS,
        }}
        assert estimate_tokens(json.dumps(value, ensure_ascii=False)) < spec.max_result_tokens - 64
        handle = handle_for(uuid5(NAMESPACE_URL, f"x3-full-face-{number}"), value)
        self.originals[handle] = deepcopy(value)
        return value

    def compact(self, name, value):
        assert name == "category.parameters.list" and not protected_result(name, value)
        identity = uuid5(NAMESPACE_URL, f"x3-full-face-{value['synthetic_capacity']['number']}")
        handle = handle_for(identity, value)
        assert self.originals[handle] == value
        result = page_view(value, handle, 1, 3_936)
        result.pop("preview")
        result.update(omitted=True, read_more={"tool": "result.read", "arguments": {
            "handle": handle, "page": 1,
        }})
        return result

    def verify(self, _scope, result, tool_results):
        assert result["result"]["synthetic_citation_ids"] == [SYNTHETIC_CITATION]
        assert any(item["value"].get("rows") for item in tool_results)
        return result

    def emit(self, _scope, event):
        self.events.append(deepcopy(event))
        return uuid4()

    def finish(self, _scope, _result):
        pass

    def prepare(self, *_args, **_kwargs):
        pytest.fail("Capacity transport must never prepare a business action")

    def write(self, *_args, **_kwargs):
        pytest.fail("Capacity transport must never execute a business action")


@pytest.mark.parametrize("window, focus", [(64_000, 58_976), (200_000, 64_000)])
def test_full_initial_disclosure_long_run_cleans_and_resumes_at_declared_window(window, focus):
    provider = ScriptedProvider()
    host, saver = OfflineHost(window, provider), InMemorySaver()
    kernel = AgentKernel(host, host.registry)
    bound = RunScope(*(uuid4() for _ in range(6)))
    baseline = deepcopy(disclosure(host.registry, "main", ()))
    assert len(baseline) == 61
    paused = kernel.execute(bound, goal=GOAL, checkpointer=saver)
    assert paused["__interrupt__"] and provider.calls == 6
    assert paused["tools_used"] == 13
    assert host.disclosures == [baseline] * 6
    assert host.prefixes == [kernel.system] * 6
    assert len(host.versions["tool_disclosures"]["main"]["chain"]) == 1
    assert all(budget["window"] == window and budget["window_configured"]
               and budget["focus"] == focus and not budget["over_focus"]
               for budget in host.budgets)
    # A fitting 64k route still reports the fixed >50%F limitation. Merely
    # declaring a bigger window never suppresses that design warning.
    assert host.budgets[0]["fixed_over_half"] == (window == 64_000)
    cleanups = [budget["cleanup"] for budget in host.budgets if budget["cleanup"]["applied"]]
    assert cleanups
    assert all(item["before_tokens"] > focus and item["saved_tokens"] >= math.ceil(.2 * focus)
               for item in cleanups)
    assert cleanups[0]["retained_latest_results"] == 3
    for requested, admitted, budget in zip(
        host.requests, provider.messages, host.budgets, strict=True,
    ):
        if not budget["cleanup"]["applied"]:
            continue
        last_batch = next(row["tool_calls"] for row in reversed(requested)
                          if row.get("tool_calls"))
        assert budget["cleanup"]["retained_latest_results"] == len(last_batch)
        original, reduced = tool_values(requested), tool_values(admitted)
        assert all(reduced[call["id"]] == original[call["id"]] for call in last_batch)
    before = {}
    names = {}
    for messages in provider.messages:
        for row in messages:
            names.update({call["id"]: call["name"] for call in row.get("tool_calls", [])})
        for identity, value in tool_values(messages).items():
            before.setdefault(identity, value)
    after = tool_values(paused["messages"])
    protected = {identity: value for identity, value in before.items()
                 if protected_result(names[identity], value) and names[identity] != "result.read"}
    assert len(protected) == 3
    assert all(after[identity] == value for identity, value in protected.items())
    ordinary = [item["value"] for item in paused["tool_results"]
                if item["value"].get("synthetic_capacity")]
    assert len(ordinary) == 9
    assert {value["synthetic_capacity"]["number"] for value in ordinary} == set(range(1, 10))
    assert all(value["synthetic_capacity"]["body"] == "容" * CAPACITY_TOKENS for value in ordinary)
    restored = [item["value"] for item in paused["tool_results"] if item["tool"] == "result.read"]
    assert len(restored) == 1
    assert json.loads(restored[0]["preview"]) == host.originals[provider.handle]
    progress = [value for _row, value in values(paused["messages"])
                if value.get("type") == "server_progress"]
    assert {value["turn"] for value in progress} == {4, 5}
    assert all(value["remaining_goal_quote"] in GOAL for value in progress)
    envelope = json.loads(paused["messages"][0]["content"])
    assert envelope["goal"] == GOAL
    assert envelope["context"]["work_state"] == host.context(bound, GOAL)["work_state"]
    omissions = {identity: value for identity, value in after.items() if value.get("omitted")}
    assert omissions
    # Replace the entire pure Host/provider. The in-memory checkpoint preserves
    # model views, full tool_results and human wait; no old tool is called again.
    next_provider = ScriptedProvider(recovery=True)
    next_host = OfflineHost(window, next_provider)
    finished = AgentKernel(next_host, next_host.registry).execute(
        bound, answer={"continue": "继续"}, checkpointer=saver,
    )
    assert finished["output"]["status"] == "completed" and next_provider.calls == 1
    assert not next_host.reads
    assert finished["tool_results"] == paused["tool_results"]
    resumed = tool_values(next_provider.messages[0])
    assert all(resumed[identity] == value for identity, value in omissions.items())
    assert next_host.disclosures == [baseline] and next_host.prefixes == [kernel.system]


@pytest.mark.parametrize("window", [None, 32_000])
def test_full_initial_disclosure_32k_stops_registered_graph_before_fake_provider(window):
    provider = ScriptedProvider()
    host = OfflineHost(window, provider)
    state = AgentKernel(host, host.registry).execute(
        RunScope(*(uuid4() for _ in range(6))), goal=GOAL,
    )
    output = state["output"]
    assert output["status"] == "partial" and output["result"]["context_incomplete"]
    budget = output["result"]["context_budget"]
    assert budget["window"] == 32_000 and budget["focus"] == 26_976
    assert budget["window_configured"] == (window is not None)
    assert budget["fixed_admission_tokens"] > budget["focus"]
    assert output["result"]["recovery"] == {
        "action": "configure_model_context_window", "new_run_required": True,
    }
    assert len(host.disclosures[0]) == 61
    assert provider.calls == 0 and not host.reads and state["tool_results"] == []
