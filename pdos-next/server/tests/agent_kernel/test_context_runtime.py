"""Synthetic mechanisms, not maintained evaluation questions or golden cases."""

import json
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from pdos_next.agent_kernel.context_budget import estimate_tokens, fit_messages
from pdos_next.agent_kernel.context_runtime import (
    cleanup_tools,
    encoded,
    progress_message,
    protected_result,
)
from pdos_next.agent_kernel.graph import AgentKernel, Budget
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.errors import DomainError
from tests.agent_kernel.test_gateway import configured_route
from tests.agent_kernel.test_graph import Host, final, scope


def messages(values):
    result = [{"role": "user", "content": json.dumps({
        "goal": "目标原话", "context_ref": str(uuid4()), "context": {},
    }, ensure_ascii=False)}]
    for index, (name, value) in enumerate(values):
        result.extend([
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": str(index), "name": name, "arguments": {}},
            ]},
            {"role": "tool", "tool_call_id": str(index), "content": encoded(value)},
        ])
    return result


def compact(name, value):
    handle = "synthetic-controlled:" + value.get("label", "same")
    return {"omitted": True, "result_handle": handle, "read_more": {
        "tool": "result.read", "arguments": {"handle": handle, "page": 1},
    }}


def route():
    return replace(configured_route(), context_window_tokens=12_000, max_output_tokens=1_000)


def test_no_cleanup_or_compactor_call_within_focus():
    original = messages([("category.read", {"body": "small"}),
                         ("category.read", {"body": "latest"})])
    called = []
    result, budget = fit_messages(
        route(), "fixed", [], original,
        compact_tool=lambda *args: called.append(args), allow_envelope=True,
    )
    assert result == original and called == []
    assert budget["cleanup"] == {"triggered": False, "applied": False, "reason": "within_focus"}


@pytest.mark.parametrize("value", [
    {"error": {}}, {"errors": []}, {"receipt_id": str(uuid4())},
    {"id": str(uuid4()), "operation": "record", "subject_id": str(uuid4()), "result": {}},
    {"items": [{"evidence_rows": [{"quote": "recorded"}]}]},
    {"rows": [{"citation_id": str(uuid4()), "quote": "recorded"}]},
    {"event_id": str(uuid4()), "requires_human": True},
    {"format": "json_fragment", "truncated": True, "preview": "unparsed evidence"},
    {"skill": "fixed", "content": "full body"},
])
def test_receipts_evidence_errors_candidates_and_skill_rows_are_protected_by_shape(value):
    assert protected_result("category.read", value)
    original = messages([("category.read", value), ("category.read", {"body": "latest"})])
    called = []
    result, reductions, status = cleanup_tools(
        original, measure=lambda _: {"focus": 1_000, "admission_tokens": 1_100,
                                     "over_focus": True},
        compact_tool=lambda *args: called.append(args),
    )
    assert result == original and reductions == [] and called == []
    assert status["protected_results"] == 1 and not status["applied"]


def test_whole_pass_saves_at_least_twenty_percent_including_placeholder_explanation():
    original = messages([
        ("category.read", {"label": "first", "body": "原文" * 1_400}),
        ("category.read", {"label": "second", "body": "原文" * 1_400}),
        ("category.read", {"label": "third", "body": "原文" * 1_400}),
        ("assistant.extract", {"evidence": "latest exact"}),
    ])
    saved = deepcopy(original)
    reduced, budget = fit_messages(route(), "fixed", [], original, compact_tool=compact,
                                   allow_envelope=True)
    cleanup = budget["cleanup"]
    assert cleanup["applied"] and cleanup["saved_tokens"] >= cleanup["minimum_tokens"]
    assert cleanup["minimum_tokens"] == 1_400
    assert not budget["over_focus"] and reduced[-1] == original[-1]
    assert original == saved
    assert json.loads(reduced[0]["content"])["context_reductions"] == budget["reductions"]
    # A committed graph checkpoint no longer compacts the same original rows.
    repeated, next_budget = fit_messages(route(), "fixed", [], reduced, compact_tool=compact,
                                        allow_envelope=True)
    assert repeated == reduced and not next_budget["cleanup"]["applied"]


def test_insufficient_eligible_content_does_not_commit_partial_cleanup_or_touch_receipt():
    original = messages([
        ("category.read", {"body": "可清" * 200}),
        ("category.read", {"receipt_id": str(uuid4()), "body": "必需" * 4_000}),
        ("category.read", {"body": "latest"}),
    ])
    saved = deepcopy(original)
    with pytest.raises(DomainError) as caught:
        fit_messages(route(), "fixed", [], original, compact_tool=compact, allow_envelope=True)
    status = caught.value.detail["context_budget"]["cleanup"]
    assert not status["applied"] and status["reason"] == "insufficient_eligible_tokens"
    assert 0 < status["candidate_saved_tokens"] < status["minimum_tokens"]
    assert status["saved_tokens"] == 0 and caught.value.detail["context_budget"]["reductions"] == []
    assert original == saved and caught.value.reason == "CONTEXT_INCOMPLETE"


def test_latest_parallel_batch_all_rows_remain_exact():
    original = messages([("category.read", {"body": "原文" * 500})])
    original[-2]["tool_calls"].append({"id": "other", "name": "category.read", "arguments": {}})
    original.append({"role": "tool", "tool_call_id": "other", "content": encoded({"body": "原文"})})
    calls = []
    result, reductions, status = cleanup_tools(
        original, measure=lambda _: {"focus": 1_000, "admission_tokens": 1_100,
                                     "over_focus": True},
        compact_tool=lambda *args: calls.append(args),
    )
    assert result == original and calls == [] and reductions == []
    assert status["retained_latest_results"] == 2


def test_history_reduction_satisfying_focus_never_triggers_tool_cleanup():
    original = messages([("category.read", {"body": "small"})])
    envelope = json.loads(original[0]["content"])
    envelope["context"]["conversation"] = {"turns": [{
        "run_id": "historical", "goal": "原问题", "historical_outcome": {"summary": "历史" * 4_000},
    }]}
    original[0]["content"] = encoded(envelope)
    called = []
    _, budget = fit_messages(route(), "fixed", [], original,
                             compact_tool=lambda *args: called.append(args), allow_envelope=True)
    assert budget["reductions"][0]["kind"] == "history_answer_preview"
    assert not budget["cleanup"]["triggered"] and called == []


def test_previous_reduction_notices_survive_later_object_directory_reduction():
    original = messages([])
    envelope = json.loads(original[0]["content"])
    old = {"kind": "older_tool_result", "field": "messages[2]", "handle": "controlled-old"}
    envelope["context_reductions"] = [old]
    envelope["context"]["proposal"] = {"id": "proposal", "items": [
        {"item_id": "item", "content": {"body": "正文" * 4_000}},
    ]}
    original[0]["content"] = encoded(envelope)
    reduced, budget = fit_messages(route(), "fixed", [], original, allow_envelope=True)
    assert json.loads(reduced[0]["content"])["context_reductions"] == [old, *budget["reductions"]]


def test_progress_is_verbatim_deterministic_bounded_and_absent_before_four_rounds():
    original = messages([])
    envelope = json.loads(original[0]["content"])
    envelope["context"]["work_state"] = {"current_goal": "只看固定版本，不推断日期。" * 1_000,
                                        "unfinished": ["原样未完成项" * 1_000] * 100}
    original[0]["content"] = encoded(envelope)
    kwargs = dict(messages=original, goal="fallback", turn=4, tools_used=6,
                  model_limit=12, tool_limit=40, token_remaining=1234)
    result = progress_message(**kwargs)
    body = json.loads(result["content"])
    assert estimate_tokens(result["content"]) <= 300
    assert envelope["context"]["work_state"]["current_goal"].startswith(
        body["remaining_goal_quote"],
    )
    assert body["remaining_budget"] == {"model_turns": 8, "tool_calls": 34, "tokens": 1234}
    assert body["context_ref"] == envelope["context_ref"] and body["data_only"]
    assert body["carried_unfinished_count"] == 100 and body["goal_quote_truncated"]
    assert progress_message(**kwargs) == result
    assert progress_message(**{**kwargs, "turn": 3}) is None


def test_real_graph_appends_progress_after_round_four_tools_and_preserves_tool_results():
    turns = [ModelTurn(calls=(ToolCall(id=str(i), name="category.read", arguments={}),))
             for i in range(5)] + [final()]
    host = Host(turns)
    host.runtime_budget = lambda _: 321
    kernel = AgentKernel(host, default_registry(), budget=Budget(model_turns=8, tool_calls=10))
    checkpointer = InMemorySaver()
    state = kernel.execute(scope(), goal="原样目标", checkpointer=checkpointer)
    progress = [json.loads(message["content"]) for message in state["messages"]
                if message["role"] == "user" and '"server_progress"' in message["content"]]
    assert [body["turn"] for body in progress] == [4, 5]
    assert all(body["remaining_goal_quote"] == "原样目标" for body in progress)
    assert len(state["tool_results"]) == 5 and state["output"]["status"] == "completed"
    assert not any('"server_progress"' in message["content"]
                   for message in host.captured_model_messages[3])
    assert '"server_progress"' in host.captured_model_messages[4][-1]["content"]


def test_graph_checkpoints_actual_admitted_messages_and_keeps_complete_verification_results():
    class AdmittingHost(Host):
        def model_step(self, bound, **kwargs):
            turn = self.model(bound, **kwargs)
            admitted = deepcopy(kwargs["messages"])
            if len(admitted) > 2:
                admitted[2]["content"] = encoded({"omitted": True, "result_handle": "controlled"})
            return turn, admitted

    host = AdmittingHost([
        ModelTurn(calls=(ToolCall(id="one", name="category.read", arguments={}),)), final(),
    ])
    state = AgentKernel(host, default_registry()).execute(scope(), goal="keep original")
    assert json.loads(state["messages"][2]["content"])["omitted"]
    assert state["tool_results"][0]["value"]["actual"] == "category.read"
    assert state["output"]["result"]["tool_count"] == 1


def test_controlled_fragment_cleanup_uses_real_host_read_ledger_and_restores_exact_page():
    from pdos_next.agent_kernel.context_runtime import compact_fragment_view
    from tests.agent_kernel.test_bound_read_host import make_host, read

    f = make_host()
    f.result = {"body": "ordinary registered result " * 3000}
    current = read(f)
    original = deepcopy(f.store.session.call.result)
    view = f.host.tool_message(f.scope, f.spec, current)
    assert view["truncated"] and view["total_pages"] > 1
    replacement = compact_fragment_view(f.store, f.scope, f.host.adapters.tool_registry, view)
    assert replacement["omitted"] and "preview" not in replacement
    assert replacement["read_more"] == {"tool": "result.read", "arguments": {
        "handle": view["result_handle"], "page": 1,
    }}
    assert f.store.session.call.result == original and f.callbacks == 1
    # Only metadata was omitted. No raw original text bypasses the registered
    # result.read -> original read adapter when the model asks for this page.
    assert "ordinary registered result" not in encoded(replacement)


def test_unparsed_fragment_of_receipt_or_evidence_is_protected_using_full_ledger_shape():
    from pdos_next.agent_kernel.context_runtime import compact_fragment_view
    from tests.agent_kernel.test_bound_read_host import make_host, read

    f = make_host()
    f.result = {"rows": [{"citation_id": str(uuid4()), "quote": "recorded evidence " * 3000}]}
    current = read(f)
    view = f.host.tool_message(f.scope, f.spec, current)
    assert view["truncated"] and "citation_id" not in view
    assert compact_fragment_view(f.store, f.scope, f.host.adapters.tool_registry, view) is None
    assert f.callbacks == 1


def test_altered_or_cross_isolation_fragment_cannot_become_trusted_cleanup_placeholder():
    from pdos_next.agent_kernel.context_runtime import compact_fragment_view
    from tests.agent_kernel.test_bound_read_host import make_host, read

    f = make_host()
    f.result = {"body": "ordinary registered result " * 3000}
    view = f.host.tool_message(f.scope, f.spec, read(f))
    assert compact_fragment_view(f.store, f.scope, f.host.adapters.tool_registry,
                                 {**view, "preview": "forged"}) is None
    with pytest.raises(DomainError):
        compact_fragment_view(f.store, replace(f.scope, isolation="extract"),
                              f.host.adapters.tool_registry, view)


def test_progress_and_completed_tools_are_not_duplicated_after_actual_graph_checkpoint_resume():
    class WorkerLost(BaseException):
        pass

    class RecoveringHost(Host):
        def __init__(self, turns):
            super().__init__(turns)
            self.attempts, self.reads = 0, 0

        def model(self, bound, **kwargs):
            self.attempts += 1
            if self.attempts == 5:
                raise WorkerLost
            return super().model(bound, **kwargs)

        def read(self, *args):
            self.reads += 1
            return super().read(*args)

    host = RecoveringHost([
        *[ModelTurn(calls=(ToolCall(id=str(i), name="category.read", arguments={}),))
          for i in range(4)], final(),
    ])
    kernel = AgentKernel(host, default_registry())
    bound, saver = scope(), InMemorySaver()
    with pytest.raises(WorkerLost):
        kernel.execute(bound, goal="精确保留目标", checkpointer=saver)
    assert host.reads == 4
    result = kernel.execute(bound, checkpointer=saver)
    progress = [message for message in result["messages"]
                if message["role"] == "user" and '"server_progress"' in message["content"]]
    assert len(progress) == 1 and json.loads(progress[0]["content"])["turn"] == 4
    assert host.reads == 4 and len(result["tool_results"]) == 4
    assert result["turns"] == 5 and result["output"]["status"] == "completed"
