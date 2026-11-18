"""Which part of a model request the provider could reuse (D592).

The provider reports one number, the cached input tokens. It does not say which part
of the request was read from cache, so a low number cannot be told apart from a
prefix that changed. This module keeps a content-free outline of each request, a
digest and a token estimate per part in request order, and compares it with the
previous call of the same run: the parts that are identical from the start are the
prefix the provider could have reused, and the first part that differs says why the
rest could not.

Nothing here holds text. The digests are truncated SHA-256 of the same values the
gateway already binds (system prompt, tool definitions) and of each admitted message.
The token numbers are the admission meter's estimates, not provider counts.

The order assumed is system prompt, tool definitions, messages. A provider template
that renders tools elsewhere changes what a widened tool list invalidates; that is a
route capability (D596), not something this outline can see.
"""

import json

from pdos_next.core.service import digest

from .context_budget import estimate_tokens

VERSION = 1
ORDER = "system,tools,messages"
SHORT = 16  # Hex characters kept from each digest.
TOOL_REDUCTION = "older_tool_result"


def _text(value):
    return value if isinstance(value, str) else json.dumps(
        value, ensure_ascii=False, sort_keys=True)


def _tokens(message):
    return estimate_tokens(_text(message.get("content", ""))) + sum(
        estimate_tokens(_text(message[key]))
        for key in ("tool_calls", "provider_continuation") if message.get(key)
    )


def outline(*, prompt_digest, tools_digest, segments, messages, loaded_skills=0,
            opening=None):
    """One request as ``[label, digest, estimated tokens]`` rows in request order.

    ``messages`` are the messages as sent. ``opening`` is the index of the fixed
    assistant message under message layout 2 (see ``wire_layout``), where the skill
    bodies precede it and the run envelope follows; None for layout 1.
    """
    first_assistant = next(
        (index for index, message in enumerate(messages)
         if message.get("role") == "assistant"), len(messages),
    )

    def label(index, message):
        if opening is not None:
            return ("skill" if index < opening else "opening" if index == opening
                    else "envelope" if index == opening + 1 else "loop")
        if index == 0:
            return "envelope"
        return "skill" if index < first_assistant and message.get("role") == "user" else "loop"

    rows = [["system", prompt_digest[:SHORT], segments.get("system", 0)],
            ["tools", tools_digest[:SHORT], segments.get("tools", 0)]]
    for index, message in enumerate(messages):
        rows.append([label(index, message), digest(message)[:SHORT], _tokens(message)])
    return {"rows": rows, "loaded_skills": loaded_skills}


def _reason(previous, current, shared, *, cleanup_applied, reductions):
    if shared == len(previous["rows"]):
        return "append_only"
    if shared == len(current["rows"]):
        return "messages_removed"
    label = current["rows"][shared][0]
    if label == "system":
        return "system_changed"
    if label == "tools":
        return ("tools_widened_by_skill_load"
                if current["loaded_skills"] > previous["loaded_skills"] else "tools_changed")
    if label in {"skill", "opening"} and shared < len(previous["rows"]) and (
            previous["rows"][shared][0] in {"skill", "opening"}):
        return "skills_changed"
    if label == "envelope":
        # Cleaning old tool results also rewrites the first message, which lists the
        # reductions; that is the invalidation D591 describes.
        if any(item.get("kind") != TOOL_REDUCTION for item in reductions):
            return "envelope_reduced"
        return "tool_cleanup_rewrote_envelope" if cleanup_applied else "envelope_changed"
    return "tool_cleanup" if cleanup_applied else "messages_changed"


def compare(previous, current, *, cleanup_applied=False, reductions=(), cache_read=None):
    """What the provider could have reused from the previous call of this run.

    ``previous`` is None for the first call of a run in its isolation. Reuse across
    runs is not derived here: the first call records its stable digests, and runs are
    joined by those digests when the records are analysed.
    """
    rows = current["rows"]
    by_label = {}
    for label, value, _ in rows:
        by_label.setdefault(label, []).append(value)
    result = {
        "version": VERSION, "order": ORDER, "chunks": len(rows),
        "stable_prefix_tokens": rows[0][2] + rows[1][2],
        "system_digest": rows[0][1], "tools_digest": rows[1][1],
        "envelope_digest": by_label.get("envelope", [None])[0],
        "skills_digest": digest(by_label["skill"])[:SHORT] if by_label.get("skill") else None,
        "loaded_skills": current["loaded_skills"],
    }
    if previous is None:
        return {**result, "basis": "first_call", "shared_chunks": None,
                "expected_reusable_tokens": None, "first_changed": None,
                "first_changed_message": None, "reason": "first_call_in_run",
                "read_to_expected_ratio": None}
    shared = 0
    for old, new in zip(previous["rows"], rows, strict=False):
        if old[:2] != new[:2]:
            break
        shared += 1
    expected = sum(row[2] for row in rows[:shared])
    changed = shared < len(previous["rows"]) and shared < len(rows)
    return {
        **result, "basis": "previous_call", "shared_chunks": shared,
        "expected_reusable_tokens": expected,
        "first_changed": rows[shared][0] if changed else None,
        # Index into the request's messages; the system prompt and tools precede them.
        "first_changed_message": shared - 2 if changed and shared >= 2 else None,
        "reason": _reason(previous, current, shared, cleanup_applied=cleanup_applied,
                          reductions=reductions),
        "read_to_expected_ratio": round(cache_read / expected, 3)
        if type(cache_read) is int and expected > 0 else None,
    }
