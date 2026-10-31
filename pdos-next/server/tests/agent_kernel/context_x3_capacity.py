"""Test-only capacity fixture; existing registered READs and unchanged prefix."""

import json
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

from pdos_next.agent_kernel.context_budget import estimate_tokens, fit_messages, measure
from pdos_next.agent_kernel.graph import AgentKernel
from pdos_next.agent_kernel.registry import ToolRegistry
from pdos_next.agent_kernel.result_continuation import handle_for, page_view
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.agent_kernel.types import WireAgentOutput

TOOLS = ("category.read", "category.parameters.list", "assistant.search", "assistant.extract",
         "assistant.passage.read", "result.read")
CAPACITY_TOKENS = 3_300
ROUTE = SimpleNamespace(context_window_tokens=32_000, max_output_tokens=1_024)
SCHEMA = WireAgentOutput.model_json_schema()


def registry():
    original = default_registry()
    return ToolRegistry(original.get(name) for name in TOOLS)


def capacity_result(number, actual):
    """Call this only AFTER the real READ; omit only its volatile transport time.

    Empty parameter_ids gives an actual empty RLS-scoped result. Capacity is
    deliberately synthetic transport data, never a business fact or evidence.
    """
    value = {key: child for key, child in actual.items() if key != "as_of"}
    assert value == {"items": [], "next_cursor": None}, value
    value["synthetic_capacity"] = {"purpose": "context-cleanup-test-only",
                                   "number": number, "body": "容" * CAPACITY_TOKENS}
    assert estimate_tokens(json.dumps(value, ensure_ascii=False)) < 3_936
    return value


def first_messages():
    return [{"role": "user", "content": json.dumps({
        "goal": "核对密封圈措施，保留原证据并在确认后继续。",
        "context": {"sources": [], "work_state": {"revision": 1}},
    }, ensure_ascii=False)}]


def batch(messages, names_and_values, *, number):
    calls = [{"id": f"plan-{number}-{index}", "name": name, "arguments": {}}
             for index, (name, _) in enumerate(names_and_values)]
    return [*messages, {"role": "assistant", "content": "", "tool_calls": calls}, *[
        {"role": "tool", "tool_call_id": call["id"],
         "content": json.dumps(value, ensure_ascii=False)}
        for call, (_name, value) in zip(calls, names_and_values, strict=True)
    ]]


def protected_controls():
    return [
        ("category.read", {"id": "actual-category-placeholder", "prior_human_receipt": {
            "id": "actual-receipt-placeholder", "operation": "evidence.artifact.register",
            "subject_id": "actual-artifact-placeholder", "result": {"revision": 1}}}),
        ("category.parameters.list", {"error": "VALIDATION_FAILED", "detail": "cursor_invalid"}),
        ("assistant.extract", {"rows": [{"citation_id": "actual-citation-placeholder",
                                         "statement": "更换密封圈", "quote": "更换密封圈"}]}),
    ]


def compact_for_sizing(_name, value):
    """Use the real bounded envelope grammar; this pure function grants no proof."""
    number = value["synthetic_capacity"]["number"]
    handle = handle_for(uuid5(NAMESPACE_URL, f"pure-capacity-sizing-{number}"), value)
    page = page_view(value, handle, 1, 3_936)
    page.pop('preview')
    page.update(omitted=True, read_more={'tool': 'result.read',
                                       'arguments': {'handle': handle, 'page': 1}})
    return page


def sizing_plan():
    """Pure arithmetic only; it is not a PG/runtime acceptance substitute."""
    selected = registry()
    system = AgentKernel(None, selected).system
    messages = batch(first_messages(), protected_controls(), number=0)
    after_first = batch(messages, [("category.parameters.list", capacity_result(i, {
        "items": [], "next_cursor": None,
    })) for i in range(1, 4)], number=1)
    after_second = batch(after_first, [("category.parameters.list", capacity_result(i, {
        "items": [], "next_cursor": None,
    })) for i in range(4, 7)], number=2)

    reduced, fitted = fit_messages(ROUTE, system, selected.definitions(), after_second, SCHEMA,
                                   compact_tool=compact_for_sizing, allow_envelope=True)
    return {
        "fixed": measure(ROUTE, system, selected.definitions(), first_messages(), SCHEMA),
        "after_first": measure(ROUTE, system, selected.definitions(), after_first, SCHEMA),
        "after_second": measure(ROUTE, system, selected.definitions(), after_second, SCHEMA),
        "fitted": fitted, "original": after_second, "reduced": reduced,
    }
