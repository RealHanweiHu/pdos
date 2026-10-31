import json
from copy import deepcopy
from dataclasses import replace

import pytest

from pdos_next.agent_kernel.context_budget import fit_messages, measure
from pdos_next.agent_kernel.gateway import AgentGateway
from pdos_next.agent_kernel.graph import AgentKernel
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.agent_kernel.types import WireAgentOutput
from pdos_next.errors import DomainError
from tests.agent_kernel.test_bound_read_host import make_host
from tests.agent_kernel.test_gateway import configured_route
from tests.agent_kernel.test_graph import Host, scope


def route():
    return replace(configured_route(), context_window_tokens=8_192, max_output_tokens=1_024)


def message(context):
    return [{"role": "user", "content": json.dumps(
        {"goal": "当前原话", "context_ref": "synthetic", "context": context}, ensure_ascii=False,
    )}]


def test_required_constraints_question_focus_and_citations_are_never_cut():
    original = message({"work_state": {
        "constraints": [{"text": "必需约束" * 1_000}],
        "focus_objects": [{"kind": "artifact", "id": "fixed"}],
        "citations": [{"citation_id": "must-check"}],
    }})
    saved = deepcopy(original)
    with pytest.raises(DomainError) as error:
        fit_messages(route(), "fixed", [], original, allow_envelope=True)
    assert error.value.reason == "CONTEXT_INCOMPLETE" and original == saved
    fields = {item["field"] for item in error.value.detail["missing"]}
    assert {"current_question", "work_state.constraints", "work_state.focus_objects",
            "work_state.citations"} <= fields


def test_history_answer_shrinks_before_other_content_but_user_original_survives():
    original = message({"work_state": {"constraints": [{"text": "只看D16"}]},
                        "conversation": {"turns": [
                            {"run_id": "previous", "goal": "前轮用户原话" * 50,
                             "historical_outcome": {"summary": "历史回答" * 1_000}}
                        ]}})
    result, budget = fit_messages(route(), "fixed", [], original, allow_envelope=True)
    envelope = json.loads(result[0]["content"])
    turn = envelope["context"]["conversation"]["turns"][0]
    assert turn["goal"] == "前轮用户原话" * 50
    assert turn["historical_outcome"]["truncated"]
    assert len(turn["historical_outcome"]["summary"]) == 120
    assert budget["reductions"][0]["kind"] == "history_answer_preview"
    assert not budget["over_focus"]
    assert envelope["context_reductions"][0]["read_more"]["tool"] == "conversation.history"


def test_old_ordinary_results_get_handles_latest_and_evidence_remain_exact():
    messages = [*message({}), {"role": "assistant", "content": "", "tool_calls": [
        {"id": "old", "name": "category.read", "arguments": {}},
    ]}, {"role": "tool", "tool_call_id": "old", "content": json.dumps({"data": "正文" * 2_000})},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "latest", "name": "assistant.extract", "arguments": {}},
        ]}, {"role": "tool", "tool_call_id": "latest", "content": '{"evidence":"exact"}'}]
    def compact(name, value):
        return {"omitted": True, "result_handle": "controlled", "read_more": {
            "tool": "result.read", "arguments": {"handle": "controlled", "page": 1},
        }}
    result, budget = fit_messages(route(), "fixed", [], messages, compact_tool=compact,
                                  allow_envelope=True)
    assert json.loads(result[2]["content"])["omitted"]
    assert result[-1] == messages[-1] and budget["reductions"][0]["kind"] == "older_tool_result"
    protected = deepcopy(messages)
    protected[1]["tool_calls"][0]["name"] = "assistant.extract"
    with pytest.raises(DomainError):
        fit_messages(route(), "fixed", [], protected, compact_tool=compact, allow_envelope=True)


def test_current_object_details_become_authorized_item_directory():
    original = message({"proposal": {"id": "proposal", "items": [
        {"item_id": "item", "version": 7, "content": {"body": "详细" * 3_000}}
    ]}})
    result, budget = fit_messages(route(), "fixed", [], original, allow_envelope=True)
    item = json.loads(result[0]["content"])["context"]["proposal"]["items"][0]
    assert item["item_id"] == "item" and item["version"] == 7
    assert item["content"]["read_more"] == {"tool": "proposal.items.read", "arguments": {
        "proposal_id": "proposal", "item_ids": ["item"],
    }}
    assert budget["reductions"][0]["kind"] == "object_detail_directory"


def test_estimate_includes_tool_arguments_provider_continuation_output_schema_and_margin():
    messages = [*message({}), {"role": "assistant", "content": "", "tool_calls": [
        {"name": "tool", "arguments": {"body": "参数" * 100}},
    ], "provider_continuation": {"reasoning": "续接" * 100}}]
    value = measure(route(), "fixed", [], messages, {"description": "输出" * 200})
    assert value["segments"]["loop"] > 400
    assert value["segments"]["tools"] > 400
    assert value["admission_tokens"] > value["estimated_total"]


def test_gateway_stops_before_ledger_reservation_and_provider_call():
    from pdos_agent_runtime.graph import registered_graph_context

    f = make_host()
    events = []
    f.store.emit = lambda scope, event: events.append(event)
    gateway = AgentGateway(f.store, route_for=lambda _: route(), cost_required=False,
                           client=object())
    with registered_graph_context("xiaopai"), pytest.raises(DomainError) as error:
        gateway.turn(f.scope, system="fixed", messages=message({"work_state": {
            "constraints": [{"text": "约束" * 3_000}]
        }}), tools=[], output_schema={})
    assert error.value.reason == "CONTEXT_INCOMPLETE"
    assert not f.store.claimed_bindings
    assert events[-1]["type"] == "context_incomplete"


def test_graph_preserves_context_incomplete_details_as_partial_without_retry():
    host = Host([])
    calls = []
    def blocked(*args, **kwargs):
        calls.append(1)
        raise DomainError("CONTEXT_INCOMPLETE", "必需内容超限", detail={
            "missing": [{"field": "work_state.constraints", "estimated_tokens": 5_000}],
        })
    host.model = blocked
    result = AgentKernel(host, default_registry()).execute(scope(), goal="当前原话")["output"]
    assert result["status"] == "partial" and result["result"]["context_incomplete"]
    assert result["unfinished"] == ["work_state.constraints"] and len(calls) == 1


def test_unknown_32k_route_reports_fixed_surface_and_effective_recovery():
    from pdos_next.agent_kernel.disclosure import disclosure

    registry = default_registry()
    kernel = AgentKernel(None, registry)
    with pytest.raises(DomainError) as error:
        fit_messages(replace(configured_route(), context_window_tokens=None),
                     kernel.system, disclosure(registry), message({}),
                     WireAgentOutput.model_json_schema())
    assert error.value.detail["reason_key"] == "fixed_context_exceeds_window"
    assert error.value.recovery == {
        "action": "configure_model_context_window", "new_run_required": True,
    }
    assert "工具定义" in error.value.message and "模型" in error.value.message


def test_actual_input_calibration_is_frozen_for_replay_and_used_by_next_request():
    f = make_host()
    gateway = AgentGateway(f.store, route_for=lambda _: route(), cost_required=False,
                           client=object())
    assert gateway.context_baseline(f.scope, route(), "first-request") is None
    baseline = {"route_digest": route().digest, "estimated_total": 100,
                "actual_input_tokens": 200}
    f.run.versions = {**f.run.versions, "context_observations": {"main": baseline}}
    assert gateway.context_baseline(f.scope, route(), "first-request") is None
    assert gateway.context_baseline(f.scope, route(), "next-request") == baseline
    messages = message({})
    value = measure(route(), "fixed", [], messages, calibration=baseline)
    assert value["calibration_factor"] == 2 and value["estimation_basis"] == "previous_actual_input"
    assert value["admission_tokens"] == value["estimated_total"] * 2
    # The saved estimate does not decrease below the conservative first-call floor.
    small = {**baseline, "actual_input_tokens": 10}
    assert measure(route(), "fixed", [], messages, calibration=small)["calibration_factor"] == 1.15
