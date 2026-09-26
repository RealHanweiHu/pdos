"""Fictional reminder scenarios using the production planner, without delivery."""

from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.domain.process_template_reminders import ReminderPolicy, policy
from app.domain.reminders import object_specs

Recipient = Literal["owner", "verifier", "project_owner"]
PEOPLE: dict[Recipient, UUID] = {
    "owner": UUID(int=1),
    "verifier": UUID(int=2),
    "project_owner": UUID(int=3),
}


class ExpectedReminder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy_key: str = Field(min_length=1, max_length=64)
    recipient: Recipient
    fire_at: AwareDatetime


class ReminderRehearsal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    entity: Literal["task", "issue"]
    status: Literal[
        "todo",
        "in_progress",
        "blocked",
        "done",
        "skipped",
        "pending_approval",
        "open",
        "analysis",
        "action",
        "verification",
        "closed",
    ]
    as_of: AwareDatetime
    due_date: date | None = None
    updated_at: AwareDatetime | None = None
    owner_present: bool = True
    verifier_present: bool = True
    project_owner_present: bool = True
    project_owner_same_as_owner: bool = False
    expected: list[ExpectedReminder] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def valid_object(self) -> "ReminderRehearsal":
        allowed = (
            {"todo", "in_progress", "blocked", "done", "skipped", "pending_approval"}
            if self.entity == "task"
            else {"open", "analysis", "action", "verification", "closed"}
        )
        if self.status not in allowed:
            raise ValueError("模拟状态与任务/问题类型不符")
        if self.updated_at is not None and self.updated_at > self.as_of:
            raise ValueError("最后更新时间不能晚于模拟扫描时间")
        if self.project_owner_same_as_owner and not (
            self.owner_present and self.project_owner_present
        ):
            raise ValueError("同一人场景必须同时提供负责人和项目负责人")
        return self


def planned(case: ReminderRehearsal, configured: ReminderPolicy) -> list[ExpectedReminder]:
    project_owner = PEOPLE["owner"] if case.project_owner_same_as_owner else PEOPLE["project_owner"]
    labels = {identity: label for label, identity in PEOPLE.items()}
    specs = object_specs(
        entity=case.entity,
        entity_id=UUID(int=4),
        title=case.name,
        status=case.status,
        owner=PEOPLE["owner"] if case.owner_present else None,
        verifier=PEOPLE["verifier"] if case.verifier_present else None,
        project_owner=project_owner if case.project_owner_present else None,
        due_day=case.due_date,
        updated_at=case.updated_at,
        as_of=case.as_of,
        configured=configured,
    )
    return sorted(
        [
            ExpectedReminder(
                policy_key=item.policy_key,
                recipient=labels[item.recipient_user_id],
                fire_at=item.fire_at,
            )
            for item in specs
        ],
        key=lambda item: (item.policy_key, item.recipient, item.fire_at),
    )


def rehearse_reminders(snapshot: dict[str, Any], cases: list[ReminderRehearsal]) -> dict[str, Any]:
    configured = policy(snapshot)
    defaults = ReminderPolicy().model_dump()
    required = {key for key, value in configured.model_dump().items() if value != defaults[key]}
    positives: set[str] = set()
    terminals: set[str] = set()
    results = []
    for case in cases:
        actual = planned(case, configured)
        expected = sorted(
            case.expected, key=lambda item: (item.policy_key, item.recipient, item.fire_at)
        )
        passed = actual == expected
        if passed:
            if case.entity == "task" and case.status in {"done", "skipped"}:
                terminals.update({"task_due", "task_accept"})
            elif case.entity == "issue" and case.status == "closed":
                terminals.update({"issue_due", "issue_verification", "issue_stalled_days"})
            else:
                if (
                    case.owner_present
                    and case.project_owner_present
                    and not case.project_owner_same_as_owner
                    and case.due_date
                ):
                    positives.add(case.entity + "_due")
                if case.entity == "task" and case.status == "todo" and case.owner_present:
                    positives.add("task_accept")
                if (
                    case.entity == "issue"
                    and case.status == "verification"
                    and case.verifier_present
                ):
                    positives.add("issue_verification")
                if (
                    case.entity == "issue"
                    and case.status in {"analysis", "action"}
                    and case.owner_present
                    and case.updated_at
                    and case.updated_at
                    <= case.as_of - timedelta(days=configured.issue_stalled_days or 7)
                ):
                    positives.add("issue_stalled_days")
        results.append(
            {
                "name": case.name,
                "inputs": case.model_dump(mode="json"),
                "passed": passed,
                "actual": [
                    item.model_dump(mode="json") | {"due": item.fire_at <= case.as_of}
                    for item in actual
                ],
                "expected": [item.model_dump(mode="json") for item in expected],
            }
        )
    return {
        "cases": results,
        "coverage": [
            {"key": key, "active": key in positives, "terminal": key in terminals}
            for key in sorted(required)
        ],
        "passed": required <= positives
        and required <= terminals
        and all(item["passed"] for item in results),
        "scope": (
            "使用虚构日期与联系人，复用实际提醒计算，核对完整时间和接收人；"
            "不会扫描项目或发送通知。非默认规则需覆盖办理中及完成/关闭后不再提醒的场景。"
            "示例预期可修改，不代表阶段验收。"
        ),
    }


def reminder_examples(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    configured = policy(snapshot)
    as_of = datetime(2026, 1, 10, 12, tzinfo=UTC)
    examples = []
    for entity, status, name in [
        ("task", "todo", "任务待接单与到期"),
        ("task", "done", "任务已完成"),
        ("issue", "action", "问题行动与停滞"),
        ("issue", "verification", "问题待验证"),
        ("issue", "closed", "问题已关闭"),
    ]:
        case = ReminderRehearsal.model_validate(
            {
                "name": name,
                "entity": entity,
                "status": status,
                "as_of": as_of,
                "due_date": as_of.date(),
                "updated_at": as_of - timedelta(days=91),
            }
        )
        case.expected = planned(case, configured)
        examples.append(case.model_dump(mode="json"))
    return examples
