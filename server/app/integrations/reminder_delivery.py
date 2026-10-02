"""Reminder-to-DingTalk dispatch adapter (vNext V1-A8, A10 fatigue guards).

Fired reminders stay in-app by default. Dispatch copies them into the
DingTalk outbox as personal robot messages; the outbox keeps the S5-1 gate —
with delivery disabled rows land in `manual` state and never leave the system.
Idempotency: one outbox row per reminder via the reminder-scoped key.

V1-A10 anti-fatigue guards: dispatch defers entirely inside the configured
quiet window (rows stay fired and are picked up by the next dispatch), and a
per-recipient daily cap bounds how many DMs any one person receives per day.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine, func, select, text

from app.db.schema import tables
from app.domain.reminder_preferences import LOCAL_TZ, current, effective
from app.domain.reminder_preferences import in_quiet_hours as in_quiet_hours
from app.integrations.dingtalk_outbox import DingTalkIntentError, DingTalkIntentService
from app.settings import Settings


@dataclass(frozen=True)
class DispatchOutcome:
    enqueued: int
    already_enqueued: int
    skipped_unbound: int
    deferred_quiet_hours: int
    capped_recipients: int
    delivery_enabled: bool


class ReminderDeliveryDispatcher:
    def __init__(self, engine: Engine, settings: Settings) -> None:
        self._engine = engine
        self._settings = settings
        self._intents = DingTalkIntentService(engine, settings)

    def dispatch(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID | None,
        project_id: UUID,
        now: datetime | None = None,
        automatic: bool = False,
    ) -> DispatchOutcome:
        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        # Serialize periodic and manual dispatch across every project in the tenant.
        # Read quota and insert intents on this same connection and transaction;
        # another dispatcher sees both only after commit, and the lock holder
        # never needs a second connection from a potentially saturated pool.
        with self._engine.begin() as connection:
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                {"scope": f"reminder-dispatch:{tenant_id}"},
            )
            if automatic:
                active_project = connection.execute(
                    select(tables.projects.c.id)
                    .join(tables.tenants, tables.tenants.c.id == tables.projects.c.tenant_id)
                    .where(
                        tables.projects.c.tenant_id == tenant_id,
                        tables.projects.c.id == project_id,
                        tables.projects.c.status != "archived",
                        tables.tenants.c.status == "active",
                    )
                ).scalar_one_or_none()
                if active_project is None:
                    return DispatchOutcome(
                        enqueued=0,
                        already_enqueued=0,
                        skipped_unbound=0,
                        deferred_quiet_hours=0,
                        capped_recipients=0,
                        delivery_enabled=self._settings.dingtalk_delivery_enabled,
                    )
            fired = connection.execute(
                select(
                    tables.reminders.c.id,
                    tables.reminders.c.recipient_user_id,
                    tables.reminders.c.title,
                )
                .where(
                    tables.reminders.c.tenant_id == tenant_id,
                    tables.reminders.c.project_id == project_id,
                    tables.reminders.c.status.in_(("fired", "acknowledged")),
                    tables.reminders.c.target_entity.not_in(("change_discussion", "meeting")),
                    tables.reminders.c.policy_key.not_like("xiaopai_%"),
                )
                .order_by(tables.reminders.c.fired_at, tables.reminders.c.id)
            ).all()
            existing_keys = set(
                connection.execute(
                    select(tables.integration_outbox.c.idempotency_key).where(
                        tables.integration_outbox.c.tenant_id == tenant_id,
                        tables.integration_outbox.c.provider == "dingtalk",
                        tables.integration_outbox.c.operation == "reminder_dm",
                    )
                ).scalars()
            )
            local_day_start = (
                occurred_at.astimezone(LOCAL_TZ)
                .replace(hour=0, minute=0, second=0, microsecond=0)
                .astimezone(UTC)
            )
            recipient_key = tables.integration_outbox.c.payload["recipient_user_id"].as_string()
            sent_today_raw = connection.execute(
                select(recipient_key.label("recipient"), func.count().label("sent"))
                .where(
                    tables.integration_outbox.c.tenant_id == tenant_id,
                    tables.integration_outbox.c.provider == "dingtalk",
                    tables.integration_outbox.c.operation == "reminder_dm",
                    tables.integration_outbox.c.created_at >= local_day_start,
                    recipient_key.is_not(None),
                )
                .group_by(recipient_key)
            ).all()
            sent_today = {UUID(row.recipient): int(row.sent) for row in sent_today_raw}
            if fired and in_quiet_hours(
                occurred_at, quiet_hours=self._settings.reminder_quiet_hours
            ):
                pending = sum(1 for row in fired if f"reminder:{row.id}" not in existing_keys)
                return DispatchOutcome(
                    enqueued=0,
                    already_enqueued=len(fired) - pending,
                    skipped_unbound=0,
                    deferred_quiet_hours=pending,
                    capped_recipients=0,
                    delivery_enabled=self._settings.dingtalk_delivery_enabled,
                )
            enqueued = already = unbound = capped = deferred = 0
            preferences: dict[UUID, dict[str, object]] = {}
            for row in fired:
                key = f"reminder:{row.id}"
                if key in existing_keys:
                    already += 1
                    continue
                if row.recipient_user_id not in preferences:
                    preferences[row.recipient_user_id] = effective(
                        current(connection, tenant_id, row.recipient_user_id),
                        self._settings,
                        occurred_at,
                    )
                policy = preferences[row.recipient_user_id]
                if policy["quiet_now"]:
                    deferred += 1
                    continue
                cap = int(str(policy["daily_cap"]))
                if sent_today.get(row.recipient_user_id, 0) >= cap:
                    capped += 1
                    continue
                try:
                    self._intents.enqueue_reminder_dm(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        actor_user_id=actor_user_id,
                        recipient_user_id=row.recipient_user_id,
                        reminder_id=row.id,
                        title=row.title,
                        connection=connection,
                    )
                    enqueued += 1
                    sent_today[row.recipient_user_id] = sent_today.get(row.recipient_user_id, 0) + 1
                except DingTalkIntentError as error:
                    if error.code == "DINGTALK_USER_NOT_BOUND":
                        unbound += 1
                        continue
                    raise
            return DispatchOutcome(
                enqueued=enqueued,
                already_enqueued=already,
                skipped_unbound=unbound,
                deferred_quiet_hours=deferred,
                capped_recipients=capped,
                delivery_enabled=self._settings.dingtalk_delivery_enabled,
            )
