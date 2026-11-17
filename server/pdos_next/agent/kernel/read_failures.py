"""A read whose source never answered cannot stand behind a completed result (D479).

Research, enterprise search and the project's current basis have their own checks.
This is the general rule for every other read: when the last call of a read tool in
the run ended with the source unavailable or stale, a result the model marked as
completed becomes partial and names the tool. A later successful call of the same
tool clears it; errors the model caused itself (wrong arguments, out of scope) do
not count, because the model was told and could answer accordingly.
"""

from copy import deepcopy

SOURCE_FAILURES = frozenset({"SOURCE_UNAVAILABLE", "SOURCE_STALE"})
NOTE = "以下读取未成功，相关内容未经核对：{tools}。"


def unresolved(tool_results):
    """Read tools whose last call in this run ended with a source failure, in call order."""
    last = {}
    for item in tool_results:
        if item.get("tier") != "READ":
            continue
        value = item.get("value")
        error = value.get("error") if isinstance(value, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        last.pop(item.get("tool"), None)
        last[item.get("tool")] = code in SOURCE_FAILURES
    return [tool for tool, failed in last.items() if failed]


def attach(output, tool_results):
    if output.get("status") != "completed":
        return output
    tools = unresolved(tool_results)
    if not tools:
        return output
    result = deepcopy(output)
    result["status"] = "partial"
    result["unfinished"] = [*result.get("unfinished", []), NOTE.format(tools="、".join(tools))]
    return result
