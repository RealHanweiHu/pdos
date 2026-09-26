"""Readable weekly-report sections; original records stay in the frozen source."""

from datetime import UTC, datetime
from typing import Any

STATUS = {
    "todo": "待开始",
    "waiting": "等待前置条件",
    "in_progress": "进行中",
    "blocked": "受阻",
    "done": "已完成",
    "skipped": "已跳过",
    "cancelled": "已取消",
    "pending_approval": "待批准",
    "open": "待处理",
    "triage": "待分派",
    "analysis": "分析中",
    "action": "整改中",
    "verification": "待验证",
    "closed": "已关闭",
}
SEVERITY = {"low": "低", "medium": "中", "high": "高", "critical": "严重"}
ACTIONS = {
    "task.create": "创建任务",
    "task.update": "更新任务资料",
    "task.transition": "办理任务状态",
    "issue.create": "登记问题",
    "issue.update": "更新问题资料",
    "issue.transition": "办理问题状态",
}


def moment(value: Any) -> str:
    if value is None:
        return "未记录"
    text = str(value)
    if "T" in text:
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return text
        if parsed.tzinfo is not None:
            return parsed.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    return text


def weekly_sections(
    work: dict[str, list[dict[str, Any]]],
    events: list[dict[str, Any]],
    people: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    names = {person["id"]: person["display_name"] for person in people}

    def person(identity: Any) -> str:
        if identity is None:
            return "未指定"
        return names.get(str(identity)) or "原人员资料不可用（见来源索引）"

    tasks, issues = [], []
    for number, task in enumerate(work["tasks"], 1):
        tasks.append(
            f"{number}. {task['title']}\n"
            f"状态：{STATUS.get(task['status'], task['status'])}；"
            f"负责人：{person(task['assignee_user_id'])}\n"
            f"计划到期：{moment(task['due_date'])}；完成时间：{moment(task['completed_at'])}\n"
            f"阻塞说明：{task['blocked_reason'] or '未记录'}\n"
            f"资料最后更新：{moment(task['updated_at'])}"
        )
    for number, issue in enumerate(work["issues"], 1):
        issues.append(
            f"{number}. {issue['title']}\n"
            f"状态：{STATUS.get(issue['status'], issue['status'])}；"
            f"严重度：{SEVERITY.get(issue['severity'], issue['severity'])}\n"
            f"负责人：{person(issue['owner_user_id'])}；"
            f"验证人：{person(issue['verifier_user_id'])}\n"
            f"目标日期：{moment(issue['target_date'])}；关闭时间：{moment(issue['closed_at'])}\n"
            f"重开次数：{issue['reopen_count']}；资料最后更新：{moment(issue['updated_at'])}"
        )
    titles = {row["id"]: row["title"] for rows in work.values() for row in rows}
    activity = [
        f"{i}. {moment(event['timestamp'])} · {person(event['actor_user_id'])}\n"
        f"{ACTIONS.get(event['action'], '办理记录（' + event['action'] + '）')}："
        f"{titles.get(event['entity_id'], '原事项资料不可用（见来源索引）')}"
        for i, event in enumerate(events, 1)
    ]
    references = [
        f"{'任务' if key == 'tasks' else '问题'} {i}：{row['id']}"
        for key, rows in work.items()
        for i, row in enumerate(rows, 1)
    ]
    references.extend(
        f"办理记录 {i}：审计编号 {event['id']}；原事项 {event['entity_id']}"
        for i, event in enumerate(events, 1)
    )
    user_ids = sorted(
        {
            identity
            for rows in [*work.values(), events]
            for row in rows
            for key, identity in row.items()
            if key.endswith("_user_id") and identity is not None
        }
    )
    references.extend(f"人员 {person(identity)}：{identity}" for identity in user_ids)
    return [
        (
            "窗口内真实任务/问题办理",
            "\n\n".join(activity) or "所选窗口内没有已登记的任务或问题办理。",
        ),
        ("窗口涉及任务及当前未结束任务", "\n\n".join(tasks) or "当前范围内没有任务记录。"),
        ("窗口涉及问题及当前未关闭问题", "\n\n".join(issues) or "当前范围内没有问题记录。"),
        ("来源索引（供回查）", "\n".join(references) or "当前范围内没有来源记录。"),
    ]
