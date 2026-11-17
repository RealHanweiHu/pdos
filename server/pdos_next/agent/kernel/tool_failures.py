"""A failed tool call tells the model what to do next (D246).

The public error codes stay the ~15 categories of v1.1 §08.7, and the reason stays in
``detail``. A category alone does not say how to recover: a refused citation and a run
bound to the wrong project are both ``FORBIDDEN_SCOPE``, while the first needs other
arguments and the second must not be worked around. So the server adds one
``next_step`` to each error it returns to the model: an action and a short hint,
derived from the category and, where the category misleads, the concrete reason.

The server also limits retries. When the same tool fails again for the same kind of
reason, the hint says to stop calling it: a transient failure gets one retry, a
fixable one two attempts, and anything else none.

Nothing here changes what the tool did, the public payload of an API error, the
ledger, or the frozen prompt prefix: the hint is part of the tool result, which is
appended at the end of the context.
"""

HINTS = {
    "fix_arguments": (
        "按工具定义和本条说明修正参数后再调用；缺对象或版本时先用读取工具查到实际编号，"
        "查不到就请用户选择，不要猜。"
    ),
    "change_approach": (
        "当前范围里没有找到：换一种允许的查找方式（换关键词、先列出或搜索、改用已下发的工具）；"
        "仍没有就在结果里说明已查过的范围。"
    ),
    "deliver_partial": (
        "本轮预算已用完：不要再调用同类工具，交付已核对的部分，把没做完的写进 unfinished。"
    ),
    "retry_once": "暂时性读取失败：可以原样再试一次；再失败就不要继续重试。",
    "reread": "资料已变化或与已有结果冲突：先重新读取最新版本，基于新结果继续，不要沿用旧值。",
    "respect_boundary": (
        "当前权限或运行范围不允许：不要换参数或换工具绕过。说明这一步做不了，"
        "以及可行的办理路径（在对应页面办理，或由有权限的人办理）。"
    ),
    "needs_person": "须本人确认、具名决定或资格：不要重复调用，说明需要谁在哪里办理。",
    "stop": "不要重复同一调用，说明这一步没有完成。",
}

BY_CATEGORY = {
    "VALIDATION_FAILED": "fix_arguments",
    "MISSING_REQUIRED_EVIDENCE": "fix_arguments",
    "NOT_FOUND": "change_approach",
    "SOURCE_UNAVAILABLE": "retry_once",
    "RATE_LIMITED": "retry_once",
    "SOURCE_STALE": "reread",
    "VERSION_CONFLICT": "reread",
    "DUPLICATE_INTENT_CONFLICT": "reread",
    "FORBIDDEN_SCOPE": "respect_boundary",
    "CONFIRMATION_REQUIRED": "needs_person",
    "NAMED_DECISION_REQUIRED": "needs_person",
    "QUALIFICATION_REQUIRED": "needs_person",
}

# Reasons whose category points the model the wrong way, keyed by ``detail.reason_key``
# or ``detail.reason``. Each comes from failures seen in the real-model runs.
BY_REASON = {
    # The search depth budget of this turn; a provider rate limit stays ``retry_once``.
    "MODEL_BUDGET_EXCEEDED": ("deliver_partial", None),
    "tool_not_registered": (
        "change_approach", "工具名不在当前下发的工具里：改用已下发的工具，不要自造名称。",
    ),
    "isolated_subtask_only": (
        "change_approach", "原文只能在隔离子任务里读取：改用对应的抽取或研究工具。",
    ),
    "write_skill_required": (
        "fix_arguments", "先用 skill.load 加载列出这个工具的技能包，再调用。",
    ),
    "EXTERNAL_OUTCOME_UNKNOWN": (
        "stop", "结果未知，服务器会核对：不要重发同一动作，说明这一步待核对。",
    ),
}
# The enterprise-search ledger refuses citations that this run never read.
CITATION_PREFIX = "assistant_"
CITATION_HINT = "引用编号只能取自本次运行实际读取返回的结果，按原样使用，不要改写或自造。"

# How many earlier consecutive failures of the same kind a tool may have before the
# hint says to stop calling it.
ATTEMPTS = {"retry_once": 1, "fix_arguments": 2, "change_approach": 2}
STOP_HINT = (
    "「{tool}」已连续 {count} 次因同类原因失败，不要再调用它：改用其他已下发的工具，"
    "或交付已核对的部分，并在 unfinished 写明缺口。"
)


def classify(error):
    """The action and hint for one public error payload."""
    code = error.get("code")
    detail = error.get("detail") if isinstance(error.get("detail"), dict) else {}
    keys = [detail.get("reason_key"), detail.get("reason")]
    for key in keys:
        if isinstance(key, str) and key in BY_REASON:
            action, hint = BY_REASON[key]
            return action, hint or HINTS[action]
    reason_key = keys[0]
    if (code == "FORBIDDEN_SCOPE" and isinstance(reason_key, str)
            and reason_key.startswith(CITATION_PREFIX)):
        return "fix_arguments", CITATION_HINT
    action = BY_CATEGORY.get(code, "stop")
    return action, HINTS[action]


def _error(value):
    error = value.get("error") if isinstance(value, dict) else None
    return error if isinstance(error, dict) else None


def annotate(value, tool, history):
    """Add ``next_step`` to a failed tool result.

    ``history`` holds the run's earlier tool results in call order (``tool`` and
    ``value``). Only failures of the same tool immediately before this one, with the
    same action, count as repeats; a success or another kind of failure resets it.
    """
    error = _error(value)
    if error is None:
        return value
    action, hint = classify(error)
    repeats = 0
    for item in reversed(history):
        if item.get("tool") != tool:
            continue
        earlier = _error(item.get("value"))
        if earlier is None or classify(earlier)[0] != action:
            break
        repeats += 1
    step = {"action": action, "hint": hint}
    if repeats >= ATTEMPTS.get(action, 1):
        step = {"action": "stop", "hint": STOP_HINT.format(tool=tool, count=repeats + 1)}
    if repeats:
        step["failures"] = repeats + 1
    return {**value, "error": {**error, "next_step": step}}
