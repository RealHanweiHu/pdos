"""Filters over the already-authorized personal queue projections."""

from datetime import date
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Date, Select, cast, false, func

WorkFocus = Literal["all", "overdue", "today", "blocked", "high", "confirm"]


def filter_queue(
    statement: Select[Any],
    name: str,
    *,
    project_id: UUID | None,
    search: str,
    focus: WorkFocus,
    as_of: date,
) -> Select[Any]:
    fields = statement.selected_columns
    if project_id is not None:
        statement = statement.where(fields.project_id == project_id)
    if search:
        title = (
            fields.description
            if name == "capa_actions"
            else fields.gate_name
            if name == "gate_signoffs"
            else fields.title
        )
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(
            func.concat(title, " ", fields.project_code, " ", fields.project_name).ilike(
                f"%{escaped}%", escape="\\"
            )
        )
    if focus in ("overdue", "today"):
        due = (
            fields.due_date
            if name in ("tasks", "capa_actions", "task_takeover_actions")
            else fields.target_date
            if name in ("issues", "risks")
            else cast(func.timezone("Asia/Shanghai", fields.review_due_at), Date)
            if name == "gate_signoffs"
            else None
        )
        if due is None:
            return statement.where(false())
        statement = statement.where(due < as_of if focus == "overdue" else due == as_of)
    elif focus == "blocked":
        statement = statement.where(
            fields.status == "blocked" if name in ("tasks", "task_takeover_actions") else false()
        )
    elif focus == "high":
        priority = (
            fields.priority
            if name in ("tasks", "task_takeover_actions")
            else fields.severity
            if name == "issues"
            else None
        )
        statement = statement.where(
            priority.in_(("high", "critical")) if priority is not None else false()
        )
    elif focus == "confirm":
        if name in ("tasks", "issues"):
            statement = statement.where(
                fields.status == ("pending_approval" if name == "tasks" else "verification")
            )
        elif name in ("risk_followup_actions", "task_takeover_actions"):
            statement = statement.where(fields.mode == "review")
        elif name not in (
            "gate_signoffs",
            "findings",
            "cross_schedule_approvals",
            "id_design_actions",
            "change_execution_confirmations",
            "cost_freeze_approvals",
        ):
            statement = statement.where(false())
    return statement
