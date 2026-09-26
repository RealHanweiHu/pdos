"""Personal additive quiet windows and delivery-side daily reservations."""

from datetime import UTC, datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, exists, func, select, text, true

from app.db.schema import tables
from app.settings import Settings

LOCAL_TZ = timezone(timedelta(hours=8))


class PreferenceConflict(Exception):
    pass


class PreferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    daily_cap: int | None = Field(default=None, ge=0, le=1000)
    quiet_hours: str | None = Field(
        default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$"
    )


def in_quiet_hours(now: datetime, *, quiet_hours: str) -> bool:
    start, end = (time.fromisoformat(value) for value in quiet_hours.split("-"))
    local = now.astimezone(LOCAL_TZ).time()
    return start <= local < end if start <= end else local >= start or local < end


def lock(c: Connection, tenant: UUID, user: UUID) -> None:
    c.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"reminder-personal:{tenant}:{user}"},
    )


def current(c: Connection, tenant: UUID, user: UUID) -> dict[str, Any]:
    t = tables.reminder_preferences
    row = (
        c.execute(
            select(t)
            .where(t.c.tenant_id == tenant, t.c.user_id == user)
            .order_by(t.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    return (
        dict(row)
        if row
        else {"version": 0, "daily_cap": None, "quiet_hours": None, "created_at": None}
    )


def effective(preference: dict[str, Any], settings: Settings, now: datetime) -> dict[str, Any]:
    personal = preference["daily_cap"]
    windows = list(
        dict.fromkeys(
            value for value in [settings.reminder_quiet_hours, preference["quiet_hours"]] if value
        )
    )
    return {
        "version": preference["version"],
        "timezone": "Asia/Shanghai",
        "daily_cap": min(settings.reminder_daily_dm_cap, personal)
        if personal is not None
        else settings.reminder_daily_dm_cap,
        "quiet_hours": windows,
        "quiet_now": any(in_quiet_hours(now, quiet_hours=value) for value in windows),
    }


def usage(
    c: Connection, tenant: UUID, user: UUID, now: datetime, exclude_legacy: UUID | None = None
) -> int:
    r, o = tables.reminder_delivery_reservations, tables.integration_outbox
    day = now.astimezone(LOCAL_TZ).date()
    used = int(
        c.execute(
            select(func.count())
            .select_from(r)
            .where(r.c.tenant_id == tenant, r.c.user_id == user, r.c.local_day == day)
        ).scalar_one()
    )
    # Existing in-flight or completed deliveries before this policy retain a
    # conservative allowance based on their recorded delivery timestamp.
    day_start = datetime.combine(day, time(), LOCAL_TZ).astimezone(UTC)
    legacy = int(
        c.execute(
            select(func.count())
            .select_from(o)
            .where(
                o.c.tenant_id == tenant,
                o.c.provider == "dingtalk",
                o.c.operation.in_(("reminder_dm", "meeting_invite_dm")),
                o.c.payload["recipient_user_id"].as_string() == str(user),
                o.c.status.in_(("sending", "succeeded", "uncertain", "failed", "retry_wait")),
                o.c.id != exclude_legacy if exclude_legacy is not None else true(),
                o.c.attempt_count > 0,
                func.coalesce(o.c.completed_at, o.c.updated_at) >= day_start,
                ~exists(
                    select(r.c.outbox_id).where(r.c.tenant_id == tenant, r.c.outbox_id == o.c.id)
                ),
            )
        ).scalar_one()
    )
    return used + legacy


def reserve_delivery(
    c: Connection, tenant: UUID, user: UUID, outbox_id: UUID, settings: Settings, now: datetime
) -> str | None:
    acquired = c.execute(
        text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"reminder-personal:{tenant}:{user}"},
    ).scalar_one()
    if not acquired:
        return "REMINDER_RECIPIENT_BUSY"
    policy = effective(current(c, tenant, user), settings, now)
    if policy["quiet_now"]:
        return "REMINDER_QUIET_HOURS"
    if policy["daily_cap"] == 0:
        return "REMINDER_DAILY_CAP"
    r = tables.reminder_delivery_reservations
    day = now.astimezone(LOCAL_TZ).date()
    prior = c.execute(
        select(r.c.outbox_id).where(
            r.c.tenant_id == tenant, r.c.outbox_id == outbox_id, r.c.local_day == day
        )
    ).scalar_one_or_none()
    if prior is not None:
        return None
    if usage(c, tenant, user, now, exclude_legacy=outbox_id) >= policy["daily_cap"]:
        return "REMINDER_DAILY_CAP"
    c.execute(
        r.insert().values(
            tenant_id=tenant,
            user_id=user,
            outbox_id=outbox_id,
            local_day=day,
            policy={**policy, "policy": "personal-reminder-v1"},
            created_at=now,
        )
    )
    return None


def read(
    engine: Engine, tenant: UUID, user: UUID, settings: Settings, before_version: int | None = None
) -> dict[str, Any]:
    now = datetime.now(UTC)
    with engine.connect() as c:
        preference = current(c, tenant, user)
        policy = effective(preference, settings, now)
        t = tables.reminder_preferences
        q = select(t).where(t.c.tenant_id == tenant, t.c.user_id == user)
        if before_version is not None:
            q = q.where(t.c.version < before_version)
        rows = c.execute(q.order_by(t.c.version.desc()).limit(21)).mappings().all()
        count = usage(c, tenant, user, now)
        o = tables.integration_outbox
        day_start = (
            now.astimezone(LOCAL_TZ)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .astimezone(UTC)
        )
        enqueued = int(
            c.execute(
                select(func.count())
                .select_from(o)
                .where(
                    o.c.tenant_id == tenant,
                    o.c.provider == "dingtalk",
                    o.c.operation.in_(("reminder_dm", "meeting_invite_dm")),
                    o.c.payload["recipient_user_id"].as_string() == str(user),
                    o.c.created_at >= day_start,
                )
            ).scalar_one()
        )
        return {
            "preference": preference,
            "effective": policy,
            "system": {
                "daily_cap": settings.reminder_daily_dm_cap,
                "quiet_hours": settings.reminder_quiet_hours,
            },
            "delivery_enabled": settings.dingtalk_delivery_enabled,
            "local_day": now.astimezone(LOCAL_TZ).date().isoformat(),
            "enqueued_today": enqueued,
            "enqueue_remaining_today": max(0, policy["daily_cap"] - enqueued),
            "reserved_today": count,
            "remaining_today": max(0, policy["daily_cap"] - count),
            "history": [dict(row) for row in rows[:20]],
            "next_before_version": rows[19]["version"] if len(rows) > 20 else None,
        }


def save(engine: Engine, tenant: UUID, user: UUID, body: PreferenceInput) -> None:
    with engine.begin() as c:
        lock(c, tenant, user)
        before = current(c, tenant, user)
        if before["daily_cap"] == body.daily_cap and before["quiet_hours"] == body.quiet_hours:
            return
        if before["version"] != body.expected_version:
            raise PreferenceConflict
        c.execute(
            tables.reminder_preferences.insert().values(
                tenant_id=tenant,
                user_id=user,
                version=before["version"] + 1,
                daily_cap=body.daily_cap,
                quiet_hours=body.quiet_hours,
            )
        )
