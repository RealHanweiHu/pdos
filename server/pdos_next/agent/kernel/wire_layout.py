"""Message layout 2 of the main graph, selected by prompt version (D590, D577, D595, D356).

Layout 1, the one every released prompt uses, sends the run envelope first and the
preloaded skill bodies after it. Each run has a new envelope, so nothing after the
tool definitions can be reused by the provider's prompt cache on a run's first call,
and the server-authored user messages carry no common mark of what they are.

Layout 2 changes only what is sent, and only for prompt versions whose text describes it:

- the preloaded skill bodies come first, each under a one-line JSON header;
- one fixed assistant message follows them. The real-model probe of 2026-11-16/17
  found that the provider reuses the prefix reliably only when an assistant message
  precedes the part that changes (evidence: context-cache-layout-20261116);
- the run envelope comes next, typed, with the user's request as its last key and the
  page material the composer appended to it moved into a key of its own;
- the last-turn note, human answers and the adoption receipt are typed JSON too.

Graph state is not rearranged: its first message stays the run envelope, which
admission, reduction, snapshots and metering all rely on. ``arranged`` is applied at
the gateway, to the messages that were admitted, just before they are sent.

The prompt text and this layout must change together. A version listed here whose
text does not describe the layout, or the reverse, fails ``test_wire_layout``.
"""

import json

LAYOUT_PROMPT_VERSIONS = frozenset({"1.2.0-layout-draft"})
# Byte-frozen: it is part of the reusable prefix of every run.
OPENING_REPLY = "Acknowledged."
NO_SKILL = "No skill is preloaded for this run."


def enabled(version, isolation="main"):
    return isolation == "main" and version in LAYOUT_PROMPT_VERSIONS


def _dump(value):
    return json.dumps(value, ensure_ascii=False)


def typed(version, isolation, kind, source, body, *, legacy):
    """A server-authored user message: typed in layout 2, ``legacy`` text otherwise."""
    if not enabled(version, isolation):
        return {"role": "user", "content": legacy}
    return {"role": "user", "content": _dump({"type": kind, "source": source, **body})}


def _is_typed(message):
    try:
        value = json.loads(message.get("content", ""))
    except (TypeError, ValueError):
        return False
    return isinstance(value, dict) and isinstance(value.get("type"), str)


def _envelope(message):
    """The run envelope as sent: typed, reference data first, the request last."""
    from .work_state import PAGE_MATERIAL_BOUNDARY

    try:
        value = json.loads(message["content"])
    except (KeyError, TypeError, ValueError):
        return message
    if not isinstance(value, dict) or not isinstance(value.get("goal"), str):
        return message
    request, boundary, material = value["goal"].partition(PAGE_MATERIAL_BOUNDARY)
    rest = {key: child for key, child in value.items() if key != "goal"}
    return {**message, "content": _dump({
        "type": "run_envelope", "source": "server", **rest,
        **({"page_material": material} if boundary else {}),
        "goal": request,
    })}


def arranged(messages, *, version, isolation, skills=()):
    """The messages as sent and the index of the fixed assistant message, or None.

    ``skills`` are the run's loaded skill bindings in load order; the preloaded ones
    come first and match the leading skill bodies one to one.
    """
    if not enabled(version, isolation) or not messages:
        return messages, None
    end = 1
    while (end < len(messages) and messages[end].get("role") == "user"
           and not _is_typed(messages[end])):
        end += 1
    bodies = []
    for index, message in enumerate(messages[1:end]):
        binding = skills[index] if index < len(skills) else None
        header = {"type": "skill_body", "source": "server",
                  "skill": getattr(binding, "key", None),
                  "version": getattr(binding, "version", None)}
        bodies.append({**message, "content": _dump(header) + "\n" + message["content"]})
    if not bodies:
        bodies = [{"role": "user", "content": _dump({
            "type": "skill_body", "source": "server", "skill": None, "note": NO_SKILL,
        })}]
    return [*bodies, {"role": "assistant", "content": OPENING_REPLY},
            _envelope(messages[0]), *messages[end:]], len(bodies)


def arrange(messages, *, version, isolation, skills=()):
    return arranged(messages, version=version, isolation=isolation, skills=skills)[0]
