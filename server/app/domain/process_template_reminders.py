"""Versioned task/issue reminder cadence, pinned only at project creation."""

from typing import Annotated, Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, select

from app.db.schema import tables

DayOffset = Annotated[int, Field(ge=-90, le=90)]


class DueReminderPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offsets: list[DayOffset] = Field(default_factory=lambda: [-3, -1, 0, 1, 3], max_length=12)
    escalate_after_days: int | None = Field(default=3, ge=1, le=90)

    @model_validator(mode="after")
    def unique_offsets(self) -> Self:
        if len(set(self.offsets)) != len(self.offsets):
            raise ValueError("同一到期提醒时间不能重复")
        self.offsets = sorted(self.offsets)
        return self


class ReminderPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_due: DueReminderPolicy = Field(default_factory=DueReminderPolicy)
    issue_due: DueReminderPolicy = Field(default_factory=DueReminderPolicy)
    task_accept: bool = True
    issue_verification: bool = True
    issue_stalled_days: int | None = Field(default=7, ge=1, le=90)


def policy(snapshot: dict[str, Any]) -> ReminderPolicy:
    return ReminderPolicy.model_validate(snapshot.get("reminder_policy") or {})


def project_policy(
    connection: Connection,
    tenant_id: UUID,
    project_id: UUID,
) -> tuple[ReminderPolicy, dict[str, Any] | None]:
    t = tables.project_template_versions
    version = (
        connection.execute(
            select(t.c.id, t.c.template_id, t.c.template_version, t.c.snapshot, t.c.digest).where(
                t.c.tenant_id == tenant_id,
                t.c.project_id == project_id,
                t.c.revision == 1,
                t.c.status.in_(("active", "superseded")),
                t.c.difference["adoption_scope"].as_string() == "project_creation",
            )
        )
        .mappings()
        .one_or_none()
    )
    if version is None:
        return ReminderPolicy(), None
    selected = policy(version["snapshot"])
    return selected, {
        "project_template_version_id": str(version["id"]),
        "template_id": version["template_id"],
        "template_version": version["template_version"],
        "template_digest": version["digest"],
        "policy": selected.model_dump(mode="json"),
    }


def due_tag(offset: int) -> str:
    return {-3: "t3", -1: "t1", 0: "due", 1: "overdue1", 3: "overdue3"}.get(
        offset, f"before{abs(offset)}" if offset < 0 else f"after{offset}"
    )


def due_label(offset: int) -> str:
    if offset == -1:
        return "明天到期"
    if offset == 0:
        return "今天到期"
    return f"{abs(offset)} 天后到期" if offset < 0 else f"已逾期 {offset} 天"
