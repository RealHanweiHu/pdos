"""Deterministic cockpit rules (D37 ⑦, D76): no ratios, no invented dates or grades."""

from datetime import UTC, datetime, timedelta

from pdos_next.domain.projects.cockpit import rules
from pdos_next.domain.projects.governance.rules import HEALTH_RULES

AT = datetime(2026, 11, 9, 8, 0, tzinfo=UTC)


def timeline(forecast=None, baseline=None, promised=(), actual=None):
    return {
        "task_key": "gate",
        "forecast": {"latest_finish": forecast} if forecast else None,
        "baseline": {"latest_finish": baseline} if baseline else None,
        "commitments": [{"promised_at": value, "fulfilled": done} for value, done in promised],
        "actual": actual,
    }


def test_every_rule_is_versioned_and_health_tiers_follow_p61():
    ids = [rule["id"] for rule in rules.RULES]
    assert len(ids) == len(set(ids))
    assert all(rule["version"] >= 1 and rule["text"] for rule in rules.RULES)
    assert [rule["label"] for rule in HEALTH_RULES] == [
        "有阻塞",
        "待核对",
        "有风险",
        "待批准",
        "正常",
    ]
    assert {rule["id"] for rule in HEALTH_RULES} <= set(ids)


def test_slip_compares_forecast_with_baseline_and_open_commitments_only():
    assert rules.slip(None)["state"] == "unknown"
    assert rules.slip(timeline())["state"] == "unknown"
    late = rules.slip(timeline("2026-12-10", "2026-12-01"))
    assert (late["state"], late["against"]) == ("late", ["基线"])
    promised = rules.slip(timeline("2026-12-10", None, [("2026-12-05T00:00:00Z", False)]))
    assert promised["against"] == ["承诺"]
    # A fulfilled promise no longer counts against the forecast.
    kept = rules.slip(timeline("2026-12-10", "2026-12-20", [("2026-12-05T00:00:00Z", True)]))
    assert kept["state"] == "on_track"
    assert rules.slip(timeline("2026-12-10", None))["state"] == "unknown"
    assert rules.slip(timeline("2026-12-10", "2026-12-01", actual="2026-12-09"))["state"] == "done"


def test_due_window_and_overdue_are_plain_date_comparisons():
    assert rules.due_soon(AT, (AT + timedelta(days=6)).isoformat())
    assert rules.due_soon(AT, "2026-11-16")  # a bare date is the start of that UTC day
    assert not rules.due_soon(AT, (AT + timedelta(days=8)).isoformat())
    assert not rules.due_soon(AT, (AT - timedelta(hours=1)).isoformat())
    assert not rules.due_soon(AT, None)
    assert rules.overdue(AT, "2026-11-08T23:00:00Z")
    assert not rules.overdue(AT, None)


def test_overdue_waits_only_on_recorded_escalation():
    assert rules.wait_overdue({"escalation": "check_due"})
    assert rules.wait_overdue({"escalation": "claimed_commitment_due"})
    for escalation in ("none", "unknown", "closed"):
        assert not rules.wait_overdue({"escalation": escalation})
    assert not rules.wait_overdue(None)


def test_exit_conditions_stay_one_state_per_condition():
    checks = [
        {"key": "g0", "label": "G0", "state": "READY", "detail": "x"},
        {"key": "baseline", "label": "基线", "state": "UNKNOWN", "detail": "y"},
    ]
    result = rules.exit_conditions(checks)
    assert [(c["key"], c["state_label"]) for c in result] == [("g0", "满足"), ("baseline", "未知")]
    assert all(set(c) == {"key", "label", "state", "state_label"} for c in result)


def test_issue_order_uses_recorded_risk_and_never_invents_p0():
    issues = [
        {"risk": "low", "recorded_at": "1"},
        {"risk": None, "recorded_at": "2"},
        {"risk": "critical", "recorded_at": "3"},
        {"risk": "high", "recorded_at": "4"},
    ]
    assert [i["risk"] for i in sorted(issues, key=rules.issue_key)] == [
        "critical",
        "high",
        None,
        "low",
    ]
    assert rules.ISSUE_RISK_NAMES[None] == "未分级"
    assert not any("P0" in name or "P1" in name for name in rules.ISSUE_RISK_NAMES.values())


def test_first_sentence_of_a_named_update():
    assert (
        rules.first_sentence("样机 B-03 已完成装配。下周开始噪声复测。") == "样机 B-03 已完成装配。"
    )
    assert rules.first_sentence("Ready for EVT. Next week we test.") == "Ready for EVT."
    assert rules.first_sentence("没有句号的一句话") == "没有句号的一句话"
    assert rules.first_sentence("") is None


def row(state, *, owner="me", pending=False, slipped=False, status="active"):
    return {
        "project": {"status": status, "owner": {"id": owner}},
        "health": {"state": state},
        "next_node": {"slip": {"state": "late" if slipped else "on_track"}},
        "review_pending": pending,
    }


def test_summary_counts_whole_projects_and_my_decisions():
    rows = [
        row("blocked", slipped=True),
        row("pending_approval", pending=True),
        row("pending_approval", owner="other", pending=True),
        row("normal", status="closed"),
    ]
    result = rules.summary(rows, principal_id="me")
    assert result["active"] == 3
    assert {h["label"]: h["count"] for h in result["health"]} == {
        "有阻塞": 1,
        "待核对": 0,
        "有风险": 0,
        "待批准": 2,
        "正常": 1,
    }
    assert result["slipped_nodes"] == 1
    assert result["my_stage_decisions"] == 1


def test_actions_sort_blocked_then_decide_then_receive():
    actions = [
        {"kind": "receive", "title": "b", "due_at": None},
        {"kind": "decide", "title": "c", "due_at": "2026-11-20"},
        {"kind": "blocked", "title": "a", "due_at": None},
        {"kind": "decide", "title": "d", "due_at": "2026-11-10"},
    ]
    assert [a["title"] for a in rules.sort_actions(actions)] == ["a", "d", "c", "b"]
