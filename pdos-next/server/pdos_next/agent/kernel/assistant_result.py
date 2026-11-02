"""Server-attached answer grounding for ordinary replies (RAG design v0.4 §8.2)."""

from copy import deepcopy

NON_LOOKUP_TOOLS = frozenset({"skill.load"})


def attach(output, tool_results):
    result = deepcopy(output)
    body = result.get("result")
    if not isinstance(body, dict):
        return result
    body.pop("assistant", None)  # Only the server authors grounding.
    if all(tool.get("tool") in NON_LOOKUP_TOOLS for tool in tool_results):
        body["assistant"] = {"version": 1, "kind": "general", "lookup": "not_run"}
    return result
