"""Deterministic reminder planning, firing, and in-app notifications (vNext V1-A7).

Reminder instances derive from source-object state through frozen policies.
Idempotency: a per-tenant unique key binds each reminder to its source version
and recipient; firing only moves scheduled rows whose fire_at has passed.
When a source recovers (task done, issue closed), outstanding scheduled
reminders are cancelled; fired history stays for the notification center.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, Row, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.schema import tables
from app.domain.change_discussion_notifications import notification_visible
from app.domain.change_discussion_notifications import specs as discussion_specs
from app.domain.process_template_reminders import (
    DueReminderPolicy,
    ReminderPolicy,
    due_label,
    due_tag,
    project_policy,
)
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

OPEN_TASK_STATUSES = ("todo", "in_progress", "blocked", "pending_approval")
STALLED_AFTER_DAYS = 7
DUE_OFFSETS: tuple[tuple[str, int], ...] = (
    ("t3", -3),
    ("t1", -1),
    ("due", 0),
    ("overdue1", 1),
    ("overdue3", 3),
)


class ReminderNotFoundError(LookupError):
    """Raised when a reminder is absent or not addressed to the actor."""


class ReminderNotFiredError(ValueError):
    """Raised when acknowledging a reminder that has not fired."""


@dataclass(frozen=True)
class ReminderSpec:
    dedupe_key: str
    policy_key: str
    target_entity: str
    target_entity_id: UUID
    recipient_user_id: UUID
    title: str
    fire_at: datetime
    escalation_level: int = 0
    policy_source: dict[str, Any] | None = None


@dataclass(frozen=True)
class ReminderRecord:
    id: UUID
    project_id: UUID
    policy_key: str
    target_entity: str
    target_entity_id: UUID
    title: str
    status: str
    escalation_level: int
    fire_at: datetime
    fired_at: datetime | None
    acknowledged_at: datetime | None


@dataclass(frozen=True)
class ScanOutcome:
    scheduled: int
    cancelled: int
    fired: int


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time(0, 0), tzinfo=UTC)


def _due_specs(
    *,
    entity: str,
    entity_id: UUID,
    title: str,
    due_day: date,
    recipient: UUID,
    project_owner: UUID | None,
    policy: DueReminderPolicy | None = None,
) -> list[ReminderSpec]:
    specs: list[ReminderSpec] = []
    label = "任务" if entity == "task" else "问题"
    effective = policy or DueReminderPolicy()
    for offset in effective.offsets:
        tag = due_tag(offset)
        fire_at = _midnight(due_day) + timedelta(days=offset)
        phase = due_label(offset)
        specs.append(
            ReminderSpec(
                dedupe_key=f"{entity}_due:{entity_id}:{tag}",
                policy_key=f"{entity}_due_{tag}",
                target_entity=entity,
                target_entity_id=entity_id,
                recipient_user_id=recipient,
                title=f"{label}{phase}：{title}"[:512],
                fire_at=fire_at,
            )
        )
    if (
        project_owner is not None
        and project_owner != recipient
        and effective.escalate_after_days is not None
    ):
        specs.append(
            ReminderSpec(
                dedupe_key=f"{entity}_due:{entity_id}:escalation",
                policy_key=f"{entity}_due_escalation",
                target_entity=entity,
                target_entity_id=entity_id,
                recipient_user_id=project_owner,
                title=f"{label}已逾期 {effective.escalate_after_days} 天仍未完成：{title}"[:512],
                fire_at=_midnight(due_day) + timedelta(days=effective.escalate_after_days),
                escalation_level=1,
            )
        )
    return specs


def object_specs(
    *,
    entity: str,
    entity_id: UUID,
    title: str,
    status: str,
    owner: UUID | None,
    verifier: UUID | None,
    due_day: date | None,
    updated_at: datetime | None,
    project_owner: UUID | None,
    as_of: datetime,
    configured: ReminderPolicy,
) -> list[ReminderSpec]:
    """Pure task/issue planner used by both real scans and simulated previews."""
    if (entity == "task" and status not in OPEN_TASK_STATUSES) or (
        entity == "issue" and status == "closed"
    ):
        return []
    specs: list[ReminderSpec] = []
    if entity == "task" and status == "todo" and owner is not None and configured.task_accept:
        specs.append(
            ReminderSpec(
                dedupe_key=f"task_accept:{entity_id}",
                policy_key="task_accept",
                target_entity="task",
                target_entity_id=entity_id,
                recipient_user_id=owner,
                title=f"新任务待接单：{title}"[:512],
                fire_at=as_of,
            )
        )
    if owner is not None and due_day is not None:
        specs.extend(
            _due_specs(
                entity=entity,
                entity_id=entity_id,
                title=title,
                due_day=due_day,
                recipient=owner,
                project_owner=project_owner,
                policy=configured.task_due if entity == "task" else configured.issue_due,
            )
        )
    if (
        entity == "issue"
        and status == "verification"
        and verifier is not None
        and configured.issue_verification
    ):
        specs.append(
            ReminderSpec(
                dedupe_key=f"issue_verify:{entity_id}",
                policy_key="issue_verify",
                target_entity="issue",
                target_entity_id=entity_id,
                recipient_user_id=verifier,
                title=f"问题等待你验证：{title}"[:512],
                fire_at=as_of,
            )
        )
    if (
        entity == "issue"
        and configured.issue_stalled_days is not None
        and status in {"analysis", "action"}
        and owner is not None
        and updated_at is not None
        and updated_at <= as_of - timedelta(days=configured.issue_stalled_days)
    ):
        specs.append(
            ReminderSpec(
                dedupe_key=f"issue_stalled:{entity_id}",
                policy_key="issue_stalled",
                target_entity="issue",
                target_entity_id=entity_id,
                recipient_user_id=owner,
                title=f"问题已停滞超过 {configured.issue_stalled_days} 天：{title}"[:512],
                fire_at=updated_at + timedelta(days=configured.issue_stalled_days),
            )
        )
    return specs


def _active_specs(
    connection: Connection, *, tenant_id: UUID, project_id: UUID, as_of: datetime
) -> list[ReminderSpec]:
    project_owner = connection.execute(
        select(tables.projects.c.owner_user_id).where(
            tables.projects.c.tenant_id == tenant_id,
            tables.projects.c.id == project_id,
        )
    ).scalar_one_or_none()
    specs: list[ReminderSpec] = []
    configured, policy_source = project_policy(connection, tenant_id, project_id)

    tasks = connection.execute(
        select(
            tables.tasks.c.id,
            tables.tasks.c.title,
            tables.tasks.c.status,
            tables.tasks.c.assignee_user_id,
            tables.tasks.c.due_date,
        ).where(
            tables.tasks.c.tenant_id == tenant_id,
            tables.tasks.c.project_id == project_id,
            tables.tasks.c.status.in_(OPEN_TASK_STATUSES),
            tables.tasks.c.assignee_user_id.is_not(None),
        )
    ).all()
    for row in tasks:
        specs.extend(
            object_specs(
                entity="task",
                entity_id=row.id,
                title=row.title,
                status=row.status,
                owner=row.assignee_user_id,
                verifier=None,
                due_day=row.due_date,
                updated_at=None,
                project_owner=project_owner,
                as_of=as_of,
                configured=configured,
            )
        )

    issues = connection.execute(
        select(
            tables.issues.c.id,
            tables.issues.c.title,
            tables.issues.c.status,
            tables.issues.c.owner_user_id,
            tables.issues.c.verifier_user_id,
            tables.issues.c.target_date,
            tables.issues.c.updated_at,
        ).where(
            tables.issues.c.tenant_id == tenant_id,
            tables.issues.c.project_id == project_id,
            tables.issues.c.status != "closed",
        )
    ).all()
    for row in issues:
        specs.extend(
            object_specs(
                entity="issue",
                entity_id=row.id,
                title=row.title,
                status=row.status,
                owner=row.owner_user_id,
                verifier=row.verifier_user_id,
                due_day=row.target_date,
                updated_at=row.updated_at,
                project_owner=project_owner,
                as_of=as_of,
                configured=configured,
            )
        )
    if policy_source is not None:
        specs = [replace(spec, policy_source=policy_source) for spec in specs]
    specs.extend(discussion_specs(connection, tenant_id, project_id, as_of))
    return specs


def _versioned_key(spec: ReminderSpec) -> str:
    key = f"{spec.dedupe_key}:{spec.recipient_user_id}"
    if "_due_" in spec.policy_key or spec.policy_key == "issue_stalled":
        key += f":{spec.fire_at.isoformat()}"
    return key


def _matches_legacy_spec(row: Row[Any], spec: ReminderSpec) -> bool:
    """Reuse pre-versioning instances without replaying their fired history."""
    if row.recipient_user_id != spec.recipient_user_id:
        return False
    if "_due_" in spec.policy_key:
        return bool(row.fire_at == spec.fire_at)
    if spec.policy_key == "issue_stalled":
        # Legacy stalled instances stored the scan time, not the inactivity threshold.
        return bool(row.fire_at >= spec.fire_at)
    return True


def _record_from_row(row: Row[Any]) -> ReminderRecord:
    return ReminderRecord(
        id=row.id,
        project_id=row.project_id,
        policy_key=row.policy_key,
        target_entity=row.target_entity,
        target_entity_id=row.target_entity_id,
        title=row.title,
        status=row.status,
        escalation_level=row.escalation_level,
        fire_at=row.fire_at,
        fired_at=row.fired_at,
        acknowledged_at=row.acknowledged_at,
    )


class ReminderService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def scan(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID | None,
        project_id: UUID,
        as_of: datetime | None = None,
        automatic: bool = False,
    ) -> ScanOutcome:
        occurred_at = datetime.now(UTC)
        effective = as_of or occurred_at
        scheduled = cancelled = fired = 0
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise ReminderNotFoundError
            if (
                automatic
                and connection.execute(
                    select(tables.projects.c.id)
                    .join(tables.tenants, tables.tenants.c.id == tables.projects.c.tenant_id)
                    .where(
                        tables.projects.c.tenant_id == tenant_id,
                        tables.projects.c.id == project_id,
                        tables.projects.c.status != "archived",
                        tables.tenants.c.status == "active",
                    )
                ).scalar_one_or_none()
                is None
            ):
                return ScanOutcome(scheduled=0, cancelled=0, fired=0)
            writer = EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            )
            specs = _active_specs(
                connection, tenant_id=tenant_id, project_id=project_id, as_of=effective
            )
            existing = {
                row.dedupe_key: row
                for row in connection.execute(
                    select(tables.reminders).where(
                        tables.reminders.c.tenant_id == tenant_id,
                        tables.reminders.c.project_id == project_id,
                    )
                )
            }
            active_keys: set[str] = set()
            for spec in specs:
                dedupe_key = _versioned_key(spec)
                previous = existing.get(dedupe_key)
                legacy = existing.get(spec.dedupe_key)
                if previous is None and legacy is not None and _matches_legacy_spec(legacy, spec):
                    previous = legacy
                    dedupe_key = legacy.dedupe_key
                active_keys.add(dedupe_key)
                if previous is not None:
                    if previous.status == "cancelled" or (
                        previous.status == "scheduled" and previous.title != spec.title
                    ):
                        rescheduling = previous.status == "cancelled"
                        values: dict[str, Any] = {
                            "title": spec.title,
                            "status": "scheduled",
                            "updated_at": occurred_at,
                        }
                        if rescheduling:
                            values["fire_at"] = spec.fire_at
                            scheduled += 1
                        connection.execute(
                            tables.reminders.update()
                            .where(
                                tables.reminders.c.tenant_id == tenant_id,
                                tables.reminders.c.id == previous.id,
                            )
                            .values(**values)
                        )
                        writer.record(
                            EventDraft(
                                event_id=f"reminder:{previous.id}:replanned:{uuid4()}",
                                event_type="REMINDER_STATE_CHANGED",
                                source="reminder_service",
                                entity_id=previous.id,
                                payload={
                                    "reminder_id": str(previous.id),
                                    "policy_key": spec.policy_key,
                                    "status": "scheduled",
                                },
                                occurred_at=occurred_at,
                            ),
                            AuditDraft(
                                action="reminder.reschedule" if rescheduling else "reminder.replan",
                                context={"template_policy": spec.policy_source}
                                if spec.policy_source
                                else {},
                                before_snapshot={
                                    "status": previous.status,
                                    "title": previous.title,
                                    "fire_at": previous.fire_at.isoformat(),
                                },
                                after_snapshot={
                                    "status": "scheduled",
                                    "title": spec.title,
                                    "fire_at": (
                                        spec.fire_at if rescheduling else previous.fire_at
                                    ).isoformat(),
                                },
                            ),
                        )
                    continue
                reminder_id = uuid4()
                inserted = connection.execute(
                    pg_insert(tables.reminders)
                    .values(
                        id=reminder_id,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        recipient_user_id=spec.recipient_user_id,
                        policy_key=spec.policy_key,
                        target_entity=spec.target_entity,
                        target_entity_id=spec.target_entity_id,
                        title=spec.title,
                        dedupe_key=dedupe_key,
                        fire_at=spec.fire_at,
                        escalation_level=spec.escalation_level,
                        created_at=occurred_at,
                        updated_at=occurred_at,
                    )
                    .on_conflict_do_nothing(index_elements=["tenant_id", "dedupe_key"])
                    .returning(tables.reminders.c.id)
                ).scalar_one_or_none()
                if inserted is not None:
                    scheduled += 1
                    writer.record(
                        EventDraft(
                            event_id=f"reminder:{reminder_id}:scheduled",
                            event_type="REMINDER_STATE_CHANGED",
                            source="reminder_service",
                            entity_id=reminder_id,
                            payload={
                                "reminder_id": str(reminder_id),
                                "policy_key": spec.policy_key,
                                "status": "scheduled",
                            },
                            occurred_at=occurred_at,
                        ),
                        AuditDraft(
                            action="reminder.schedule",
                            context={"template_policy": spec.policy_source}
                            if spec.policy_source
                            else {},
                            after_snapshot={
                                "dedupe_key": dedupe_key,
                                "policy_key": spec.policy_key,
                                "fire_at": spec.fire_at.isoformat(),
                            },
                        ),
                    )

            stale_rows = connection.execute(
                select(
                    tables.reminders.c.id,
                    tables.reminders.c.dedupe_key,
                    tables.reminders.c.policy_key,
                ).where(
                    tables.reminders.c.tenant_id == tenant_id,
                    tables.reminders.c.project_id == project_id,
                    tables.reminders.c.status == "scheduled",
                    tables.reminders.c.dedupe_key.not_in(active_keys)
                    if active_keys
                    else tables.reminders.c.dedupe_key.is_not(None),
                )
            ).all()
            for row in stale_rows:
                connection.execute(
                    tables.reminders.update()
                    .where(
                        tables.reminders.c.tenant_id == tenant_id, tables.reminders.c.id == row.id
                    )
                    .values(status="cancelled", updated_at=occurred_at)
                )
                cancelled += 1
                writer.record(
                    EventDraft(
                        event_id=f"reminder:{row.id}:cancelled:{uuid4()}",
                        event_type="REMINDER_STATE_CHANGED",
                        source="reminder_service",
                        entity_id=row.id,
                        payload={
                            "reminder_id": str(row.id),
                            "policy_key": row.policy_key,
                            "status": "cancelled",
                        },
                        occurred_at=occurred_at,
                    ),
                    AuditDraft(
                        action="reminder.cancel",
                        before_snapshot={"dedupe_key": row.dedupe_key, "status": "scheduled"},
                        after_snapshot={"status": "cancelled"},
                    ),
                )

            due_rows = connection.execute(
                select(tables.reminders.c.id, tables.reminders.c.policy_key).where(
                    tables.reminders.c.tenant_id == tenant_id,
                    tables.reminders.c.project_id == project_id,
                    tables.reminders.c.status == "scheduled",
                    tables.reminders.c.fire_at <= effective,
                )
            ).all()
            for row in due_rows:
                connection.execute(
                    tables.reminders.update()
                    .where(
                        tables.reminders.c.tenant_id == tenant_id, tables.reminders.c.id == row.id
                    )
                    .values(status="fired", fired_at=occurred_at, updated_at=occurred_at)
                )
                fired += 1
                writer.record(
                    EventDraft(
                        event_id=f"reminder:{row.id}:fired",
                        event_type="REMINDER_STATE_CHANGED",
                        source="reminder_service",
                        entity_id=row.id,
                        payload={
                            "reminder_id": str(row.id),
                            "policy_key": row.policy_key,
                            "status": "fired",
                        },
                        occurred_at=occurred_at,
                    ),
                    AuditDraft(
                        action="reminder.fire",
                        before_snapshot={"status": "scheduled"},
                        after_snapshot={"status": "fired"},
                    ),
                )
        return ScanOutcome(scheduled=scheduled, cancelled=cancelled, fired=fired)

    def list_notifications(
        self, *, tenant_id: UUID, recipient_user_id: UUID, limit: int
    ) -> tuple[list[tuple[ReminderRecord, str, str]], int, dict[str, int]]:
        with self._engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            rows = connection.execute(
                select(
                    tables.reminders,
                    tables.projects.c.code.label("project_code"),
                    tables.projects.c.name.label("project_name"),
                )
                .join(
                    tables.projects,
                    (tables.projects.c.tenant_id == tables.reminders.c.tenant_id)
                    & (tables.projects.c.id == tables.reminders.c.project_id),
                )
                .where(
                    tables.reminders.c.tenant_id == tenant_id,
                    tables.reminders.c.recipient_user_id == recipient_user_id,
                    notification_visible(),
                    tables.reminders.c.status.in_(("fired", "acknowledged")),
                )
                .order_by(tables.reminders.c.fired_at.desc(), tables.reminders.c.id.desc())
                .limit(limit)
            ).all()
            digest_rows = connection.execute(
                select(tables.reminders.c.policy_key, func.count().label("unread_count"))
                .where(
                    tables.reminders.c.tenant_id == tenant_id,
                    tables.reminders.c.recipient_user_id == recipient_user_id,
                    notification_visible(),
                    tables.reminders.c.status == "fired",
                )
                .group_by(tables.reminders.c.policy_key)
            ).all()
        digest = {row.policy_key: int(row.unread_count) for row in digest_rows}
        return (
            [(_record_from_row(row), row.project_code, row.project_name) for row in rows],
            sum(digest.values()),
            digest,
        )

    def acknowledge(
        self, *, tenant_id: UUID, recipient_user_id: UUID, reminder_id: UUID
    ) -> ReminderRecord:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(tables.reminders).where(
                        tables.reminders.c.tenant_id == tenant_id,
                        tables.reminders.c.id == reminder_id,
                        tables.reminders.c.recipient_user_id == recipient_user_id,
                        notification_visible(),
                    )
                )
            ).one_or_none()
            if row is None:
                raise ReminderNotFoundError
            if row.status == "acknowledged":
                return _record_from_row(row)
            if row.status != "fired":
                raise ReminderNotFiredError
            connection.execute(
                tables.reminders.update()
                .where(
                    tables.reminders.c.tenant_id == tenant_id, tables.reminders.c.id == reminder_id
                )
                .values(status="acknowledged", acknowledged_at=occurred_at, updated_at=occurred_at)
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=recipient_user_id,
                project_id=row.project_id,
            ).record(
                EventDraft(
                    event_id=f"reminder:{reminder_id}:acknowledged",
                    event_type="REMINDER_STATE_CHANGED",
                    source="reminder_service",
                    entity_id=reminder_id,
                    payload={
                        "reminder_id": str(reminder_id),
                        "policy_key": row.policy_key,
                        "status": "acknowledged",
                    },
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="reminder.acknowledge",
                    before_snapshot={"status": "fired"},
                    after_snapshot={"status": "acknowledged"},
                ),
            )
            updated = connection.execute(
                select(tables.reminders).where(
                    tables.reminders.c.tenant_id == tenant_id,
                    tables.reminders.c.id == reminder_id,
                )
            ).one()
            return _record_from_row(updated)
