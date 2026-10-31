"""Deterministic reversible cleanup and bounded server progress (context §6.4/§7)."""

import json
import math
from copy import deepcopy

from .context_budget import estimate_tokens

# Tool names are a conservative first fence. Structural checks below also cover
# evidence/receipts returned by ordinary READs or inside a result.read page.
PROTECTED_PREFIXES = ("assistant.", "evidence.", "research.")
PROTECTED_FIELDS = frozenset({
    "error", "errors", "receipt", "receipt_id", "receipts", "business_receipts",
    "evidence", "evidence_rows", "citation_id", "citation_ids", "requires_human",
    "prepared_event_id", "event_id", "skill", "content_hash", "field_path",
})


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def protected_result(name, value):
    """Unknown/fragmented/proof-bearing rows fail closed; never classify by prose."""
    if name == "skill.load" or name.startswith(PROTECTED_PREFIXES):
        return True
    if not isinstance(value, dict) or value.get("omitted") or value.get("truncated"):
        return True

    def protected(node):
        if isinstance(node, dict):
            if PROTECTED_FIELDS.intersection(node):
                return True
            # Native receipt_view is {id,operation,subject_id,result}; it has no
            # receipt_id field, so its actual shape needs an explicit fence.
            if {"id", "operation", "subject_id", "result"} <= node.keys():
                return True
            return any(protected(child) for child in node.values())
        return isinstance(node, list) and any(protected(child) for child in node)

    return protected(value)


def cleanup_tools(messages, *, measure, compact_tool, decorate=None, compact_fragment=None):
    """Plan a whole >=20%F pass, then commit together or leave input untouched.

    measure(messages) is the admission meter, including placeholder metadata.
    decorate(candidate,reductions) adds the model-visible reduction explanation
    before measuring. The full ledger and verification tool_results are not inputs.
    """
    original = deepcopy(messages)
    before = measure(original)
    threshold = math.ceil(before["focus"] * .2)
    status = {
        "triggered": before["over_focus"], "applied": False,
        "minimum_tokens": threshold, "before_tokens": before["admission_tokens"],
        "after_tokens": before["admission_tokens"], "saved_tokens": 0,
        "candidate_saved_tokens": 0, "eligible_results": 0, "protected_results": 0,
        "retained_latest_results": 0, "replaced_results": 0,
        "cache_invalidation_from_message": None, "reason": "within_focus",
    }
    if not before["over_focus"]:
        return original, [], status
    status["reason"] = "no_eligible_results"
    if compact_tool is None and compact_fragment is None:
        status["reason"] = "no_controlled_compactor"
        return original, [], status
    names, indices = {}, []
    for index, message in enumerate(original):
        if message.get("role") == "assistant":
            names.update({call["id"]: call["name"] for call in message.get("tool_calls", [])})
        elif message.get("role") == "tool":
            indices.append(index)
    # Keep the entire most recent tool batch, rather than just its last row.
    last_assistant = max((index for index, message in enumerate(original)
                          if message.get("role") == "assistant" and message.get("tool_calls")),
                         default=-1)
    # The plan may finish before visiting this batch. Count the full retained
    # batch first, so an early successful break cannot report a misleading zero.
    status["retained_latest_results"] = sum(index > last_assistant for index in indices)
    candidate, reductions = deepcopy(original), []
    for index in indices:
        if index > last_assistant:
            continue
        message = candidate[index]
        name = names.get(message.get("tool_call_id"))
        try:
            value = json.loads(message["content"])
        except (KeyError, TypeError, ValueError):
            status["protected_results"] += 1
            continue
        fragment = (isinstance(value, dict) and value.get("format") == "json_fragment"
                    and value.get("truncated") and not value.get("omitted"))
        if (fragment and compact_fragment is not None and name
                and name != "skill.load" and not name.startswith(PROTECTED_PREFIXES)):
            # A fragment's preview is not parseable evidence. Only the dedicated
            # ledger-backed port may decide whether its full source is ordinary.
            replacement = compact_fragment(value)
            if replacement is None:
                status["protected_results"] += 1
                continue
        elif not name or protected_result(name, value):
            status["protected_results"] += 1
            continue
        else:
            replacement = compact_tool(name, value) if compact_tool else None
        # Only a controlled, reversible placeholder is admissible. A compactor
        # cannot turn a proof-bearing row into a guessed summary.
        if (not isinstance(replacement, dict) or not replacement.get("result_handle")
                or not isinstance(replacement.get("read_more"), dict)
                or replacement["read_more"].get("tool") != "result.read"
                or estimate_tokens(encoded(replacement)) >= estimate_tokens(encoded(value))):
            continue
        status["eligible_results"] += 1
        message["content"] = json.dumps(replacement, ensure_ascii=False)
        reductions.append({"kind": "older_tool_result", "field": f"messages[{index}]",
                           "handle": replacement["result_handle"],
                           "read_more": deepcopy(replacement["read_more"])})
        if decorate:
            decorate(candidate, reductions)
        current = measure(candidate)
        saved = before["admission_tokens"] - current["admission_tokens"]
        status["candidate_saved_tokens"] = saved
        if saved >= threshold and not current["over_focus"]:
            break
    current = measure(candidate)
    saved = before["admission_tokens"] - current["admission_tokens"]
    if reductions and saved >= threshold:
        status.update(applied=True, reason="minimum_reached", saved_tokens=saved,
                      replaced_results=len(reductions),
                      cache_invalidation_from_message=min(
                          index for index in indices if candidate[index] != original[index]
                      ), after_tokens=current["admission_tokens"])
        return candidate, reductions, status
    if reductions:
        status["reason"] = "insufficient_eligible_tokens"
    return original, [], status


def compact_fragment_view(store, scope, registry, value):
    """Omit only an exact issued fragment of a proven ordinary durable READ.

    Inspecting the ledger here removes content; it never returns original text.
    result.read still re-enters its original adapter/permissions when restoring.
    """
    from pdos_next.service import digest

    from .models import AgentToolCall
    from .result_continuation import durable_read, page_view, parse_handle

    handle = value.get("result_handle")
    spec, _, _, _, _ = durable_read(store, scope, handle, registry)
    identity, _ = parse_handle(handle)
    with store.transaction(scope) as (session, _):
        row = session.get(AgentToolCall, identity)
        if protected_result(spec.name, row.result):
            return None
        source = {**row.result, "execution_ref": {
            "call_id": str(row.id), "read_kind": row.execution_binding["read_kind"],
        }}
    expected = page_view(source, handle, value.get("page"), min(spec.max_result_tokens, 4000) - 64)
    if digest(expected) != digest(value):
        return None  # An unissued/altered preview is never rewritten as trusted.
    replacement = {key: child for key, child in value.items() if key != "preview"}
    replacement.update(omitted=True, read_more={
        "tool": "result.read", "arguments": {"handle": handle, "page": value["page"]},
    })
    return replacement


def _prefix(text, limit):
    """An exact prefix, never a paraphrase. The original remains at context_ref."""
    if not isinstance(text, str):
        return ""
    while estimate_tokens(encoded(text)) > limit:
        text = text[:max(0, len(text) - max(1, len(text) // 8))]
    return text


def progress_message(*, messages, goal, turn, tools_used, model_limit, tool_limit,
                     token_remaining=None):
    """At round 4+, restate only frozen quotes and deterministic runtime facts."""
    if turn < 4:
        return None
    try:
        envelope = json.loads(messages[0]["content"])
    except (IndexError, KeyError, TypeError, ValueError):
        envelope = {}
    work = envelope.get("context", {}).get("work_state", {})
    question = work.get("current_goal") or envelope.get("goal") or goal
    if not isinstance(question, str):
        question = goal
    unfinished = work.get("unfinished", [])
    unfinished = unfinished if isinstance(unfinished, list) else []
    # The runtime does not declare a subgoal complete based on model prose.
    # Copied carry-over items are explicitly historical, not fresh domain facts.
    quotes = [_prefix(item, 20) for item in unfinished[:2] if isinstance(item, str)]
    body = {
        "type": "server_progress", "source": "runtime_state", "data_only": True,
        "context_ref": envelope.get("context_ref"), "turn": turn,
        "remaining_goal_quote": _prefix(question, 45),
        "goal_quote_truncated": _prefix(question, 45) != question,
        "carried_unfinished_quotes": quotes,
        "carried_unfinished_count": len(unfinished),
        "unfinished": "本轮结果尚待最终结构与依据核对",
        "remaining_budget": {"model_turns": max(0, model_limit - turn),
                             "tool_calls": max(0, tool_limit - tools_used),
                             "tokens": token_remaining},
    }
    # Framing is counted too. This bound is independent of user goal length.
    while estimate_tokens(encoded(body)) > 300 and body["carried_unfinished_quotes"]:
        body["carried_unfinished_quotes"].pop()
    if estimate_tokens(encoded(body)) > 300:
        body["remaining_goal_quote"] = _prefix(question, 10)
        body["goal_quote_truncated"] = body["remaining_goal_quote"] != question
    return {"role": "user", "content": encoded(body)}
