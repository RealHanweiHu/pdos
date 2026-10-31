"""Deterministic per-call admission and reversible reduction (context §4/§6)."""

import json
import math
from copy import deepcopy

from pdos_next.errors import DomainError

DEFAULT_WINDOW = 32_000
TOOL_RESULT_RESERVE = 4_000
FOCUS_CAP = 64_000


def _is_wide(char):
    code = ord(char)
    return (
        0x3400 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0x3000 <= code <= 0x303F
        or 0xFF00 <= code <= 0xFFEF
    )


def estimate_tokens(text):
    if not text:
        return 0
    wide = sum(1 for char in text if _is_wide(char))
    return wide + math.ceil((len(text) - wide) / 4)


def budget_for(route):
    window = route.context_window_tokens or DEFAULT_WINDOW
    reserve = route.max_output_tokens + TOOL_RESULT_RESERVE
    return {
        "window": window,
        "window_configured": route.context_window_tokens is not None,
        "reserve": reserve,
        "focus": max(0, min(window - reserve, FOCUS_CAP)),
    }


def _text(value):
    return (
        value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    )


def segments(system, tools, messages, output_schema=None):
    first_assistant = next(
        (i for i, m in enumerate(messages) if m.get("role") == "assistant"), len(messages)
    )
    envelope_text = _text(messages[0].get("content", "")) if messages else ""
    history = 0
    try:
        conversation = json.loads(envelope_text).get("context", {}).get("conversation")
        if conversation is not None:
            history = estimate_tokens(_text(conversation))
    except (ValueError, AttributeError):
        history = 0
    envelope = estimate_tokens(envelope_text)
    skills = sum(
        estimate_tokens(_text(m.get("content", "")))
        for m in messages[1:first_assistant]
        if m.get("role") == "user"
    )
    loop = sum(
        estimate_tokens(_text(m.get("content", "")))
        + sum(estimate_tokens(_text(m[key])) for key in ("tool_calls", "provider_continuation")
              if m.get(key))
        for m in messages[first_assistant:]
    )
    values = {
        "system": estimate_tokens(system),
        "tools": estimate_tokens(_text(tools))
        + (estimate_tokens(_text(output_schema)) if output_schema else 0),
        "skills": skills,
        "envelope": envelope - history,
        "history": history,
        "loop": loop,
    }
    return {"segments": values, "estimated_total": sum(values.values())}


def measure(route, system, tools, messages, output_schema=None, *, calibration=None):
    value = {**budget_for(route), **segments(system, tools, messages, output_schema)}
    # Actual input on this same route calibrates the character estimate. Keep
    # the conservative 15% floor for previously unseen mixes of text/schema.
    factor = 1.15
    if calibration and calibration.get("estimated_total", 0) > 0:
        factor = max(factor, calibration["actual_input_tokens"] / calibration["estimated_total"])
    value["admission_tokens"] = math.ceil(value["estimated_total"] * factor)
    value["estimation_margin"] = 0.15
    value["calibration_factor"] = factor
    value["estimation_basis"] = "previous_actual_input" if calibration else "first_call_estimate"
    if calibration:
        value["previous_actual_input_tokens"] = calibration["actual_input_tokens"]
        value["previous_estimated_tokens"] = calibration["estimated_total"]
    value["over_focus"] = value["admission_tokens"] > value["focus"]
    value["fixed_over_half"] = (
        value["segments"]["system"] + value["segments"]["tools"]
        + value["segments"]["skills"]
    ) > value["focus"] / 2
    value["fixed_admission_tokens"] = math.ceil((
        value["segments"]["system"] + value["segments"]["tools"]
        + value["segments"]["skills"]
    ) * factor)
    return value


def _envelope(messages):
    try:
        value = json.loads(messages[0]["content"])
        return value if isinstance(value, dict) and isinstance(value.get("context"), dict) else {}
    except (IndexError, KeyError, TypeError, ValueError):
        return {}


def required_items(system, tools, messages, output_schema=None):
    """Names/estimates only: never echo private content in a failure event."""
    envelope = _envelope(messages)
    context = envelope.get("context", {})
    work = context.get("work_state", {})
    rows = []

    def add(field, value):
        if value not in (None, "", [], {}):
            rows.append({"field": field, "estimated_tokens": estimate_tokens(_text(value))})

    add("system", system)
    add("tool_definitions", tools)
    add("output_schema", output_schema)
    add("current_question", envelope.get("goal", context.get("goal")))
    for key in ("root_goal", "current_goal", "constraints", "exclusions", "focus_objects",
                "citations"):
        add("work_state." + key, work.get(key))
    add("sources", context.get("sources"))
    for key, value in context.items():
        if key not in {"work_state", "conversation", "goal", "sources"}:
            add("context." + key, value)
    for key, value in work.items():
        if key not in {"root_goal", "current_goal", "constraints", "exclusions", "focus_objects",
                       "citations"}:
            add("work_state." + key, value)
    first_assistant = next((i for i, item in enumerate(messages)
                            if item.get("role") == "assistant"), len(messages))
    for index, message in enumerate(messages):
        if index == 0 and not envelope:
            add("current_question", message.get("content"))
        elif message.get("role") == "user" and index < first_assistant:
            add(f"skill_body[{index}]", message.get("content"))
        elif message.get("role") == "user":
            add(f"human_or_verification_message[{index}]", message.get("content"))
    # User originals in history must survive every reduction, even when they
    # alone exhaust the window. Refer to the exact turn instead of a generic gap.
    conversation = context.get("conversation", {})
    add("conversation.root_goal", conversation.get("root_goal"))
    for index, turn in enumerate(conversation.get("turns", [])):
        add(f"conversation.turns[{index}].goal", turn.get("goal"))
        add(f"conversation.turns[{index}].historical_outcome", turn.get("historical_outcome"))
    return rows


def fit_messages(route, system, tools, messages, output_schema=None, *, compact_tool=None,
                 allow_envelope=False, calibration=None):
    """Shrink only recoverable data, in the design's fixed order.

    The input/checkpoint remains intact. A trusted host signs any derived server
    envelope before egress. Full results used by domain verification never pass
    through this function.
    """
    result = deepcopy(messages)
    reductions = []
    envelope = _envelope(result) if allow_envelope else {}

    def measured():
        return measure(route, system, tools, result, output_schema, calibration=calibration)

    def commit_envelope():
        envelope["context_reductions"] = reductions
        result[0]["content"] = json.dumps(envelope, ensure_ascii=False)

    def over():
        return measured()["over_focus"]

    if not over():
        return result, {**measured(), "reductions": reductions}
    conversation = envelope.get("context", {}).get("conversation", {})
    for phase, indices, limit in (
        ("history_directory", range(3, len(conversation.get("turns", []))), 60),
        ("history_answer_preview", range(min(3, len(conversation.get("turns", [])))), 120),
    ):
        for index in indices:
            if not over():
                break
            turn = conversation["turns"][index]
            outcome = turn.get("historical_outcome")
            if not isinstance(outcome, dict) or len(outcome.get("summary", "")) <= limit:
                continue
            outcome["summary"] = outcome["summary"][:limit]
            outcome["truncated"] = True
            reduction = {"kind": phase, "field": f"conversation.turns[{index}].historical_outcome",
                         "run_id": turn["run_id"], "read_more": {
                             "tool": "conversation.history", "arguments": {"page_size": 25},
                             "locate_run_id": turn["run_id"],
                         }}
            reductions.append(reduction)
            commit_envelope()
    # Keep the latest result, receipts, evidence rows, skill loads and errors.
    # Older ordinary reads may become metadata + their actual durable handle.
    names = {}
    tool_indices = []
    for index, message in enumerate(result):
        if message.get("role") == "assistant":
            names.update({call["id"]: call["name"] for call in message.get("tool_calls", [])})
        elif message.get("role") == "tool":
            tool_indices.append(index)
    if over() and compact_tool:
        before = measured()["admission_tokens"]
        for index in tool_indices[:-1]:
            # X3's cleanup threshold: clear at least 20% of F per pass (or all
            # eligible reads). Required/evidence content is never sacrificed.
            if not over() and before - measured()["admission_tokens"] >= measured()["focus"] * .2:
                break
            message = result[index]
            name = names.get(message.get("tool_call_id"))
            if not name or name == "skill.load" or name.startswith(
                ("assistant.", "evidence.", "research.")
            ):
                continue
            try:
                value = json.loads(message["content"])
            except (TypeError, ValueError):
                continue
            if not isinstance(value, dict) or value.get("error") or value.get("omitted"):
                continue
            compacted = compact_tool(name, value)
            if (compacted is None
                    or estimate_tokens(_text(compacted)) >= estimate_tokens(_text(value))):
                continue
            message["content"] = json.dumps(compacted, ensure_ascii=False)
            reductions.append({"kind": "older_tool_result", "field": f"messages[{index}]",
                               "handle": compacted["result_handle"],
                               "read_more": compacted["read_more"]})
            if envelope:
                commit_envelope()
    if over():
        proposal = envelope.get("context", {}).get("proposal", {})
        for index, item in enumerate(proposal.get("items", [])):
            if not over():
                break
            if not isinstance(item, dict) or estimate_tokens(_text(item.get("content", {}))) <= 256:
                continue
            read_more = {"tool": "proposal.items.read", "arguments": {
                "proposal_id": proposal["id"], "item_ids": [item["item_id"]],
            }}
            item["content"] = {"omitted": True, "read_more": read_more}
            reductions.append({"kind": "object_detail_directory",
                               "field": f"proposal.items[{index}].content",
                               "read_more": read_more})
            commit_envelope()
    value = {**measured(), "reductions": reductions}
    if value["over_focus"]:
        missing = required_items(system, tools, result, output_schema)
        # Include every still-carried segment that could not be removed safely.
        # These are jointly unfit, not individually declared absent/truncated.
        for index, message in enumerate(result):
            if message.get("role") in {"tool", "assistant"}:
                missing.append({"field": f"messages[{index}]",
                                "estimated_tokens": estimate_tokens(_text(message))})
        fixed_overflow = value["fixed_admission_tokens"] > value["focus"]
        raise DomainError(
            "CONTEXT_INCOMPLETE",
            "固定系统提示、工具定义与必需技能已超过当前模型窗口预算。"
            "请核对模型的上下文窗口配置，或选择窗口足够的模型后重新发起。"
            if fixed_overflow else
            "必需上下文超过当前模型预算，请缩小范围、清理本次携带或开新会话。",
            detail={"missing": missing, "context_budget": value,
                    "reason_key": "fixed_context_exceeds_window" if fixed_overflow
                    else "required_context_exceeds_window"},
            recovery={"action": "configure_model_context_window" if fixed_overflow
                      else "reduce_required_context", "new_run_required": fixed_overflow},
        )
    return result, value
