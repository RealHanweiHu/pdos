"""Status-update cadence: drafting slots, publication deadlines and "状态更新缺失".

P34-6 and P65: the project owner sets a cadence; on each slot 小Pai drafts a status
update as a one-confirmation (T1) candidate for the owner, who publishes it under
their own name (P18). The cadence is the owner's active `status_update_draft`
automation rule; its schedule slots are the drafting times. The owner then has one
working day to publish (the deadline). After a deadline passes with no named status
update published since the previous deadline (or since the cadence was switched on),
the project shows "状态更新缺失" until the next update is published.

Deadlines use the weekday estimate (P41-10, D17) and say so. Nothing here writes,
drafts or publishes; it only reads the cadence timing and the latest update.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text

from pdos_next.core.clock import now
from pdos_next.domain.automations.trigger_time import Schedule

from . import business_days
from .models import ProjectStatusUpdate

GRACE_WORKDAYS = 1
_LOOKAHEAD = timedelta(days=400)
_TICK = timedelta(microseconds=1)


def _aware(value):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("An aware instant is required")
    return value.astimezone(UTC)


def _previous(schedule, slot):
    """The latest slot strictly before `slot`, or None."""
    return schedule.due(slot - _TICK) if slot - _TICK >= _aware(schedule.first_at) else None


def _upcoming(schedule, at):
    bound = at + _LOOKAHEAD
    candidate = schedule.wake_before(at, bound)
    return None if candidate >= bound or candidate <= at else candidate


def _iso(value):
    return value.isoformat() if value is not None else None


def state(schedule, *, activated_at, latest_update_at, at):
    """Pure cadence state at `at`.

    A cycle counts once the cadence was on before its deadline (the timer drafts for the
    latest slot even when it fell just before activation). A cycle is published when a
    named update exists after the previous cycle's deadline, or for the first cycle
    after the cadence was switched on.
    """
    schedule = Schedule.model_validate(schedule)
    at, activated_at = _aware(at), _aware(activated_at)
    latest = _aware(latest_update_at) if latest_update_at is not None else None
    zone = schedule.original_timezone

    def deadline(slot):
        return business_days.add_weekdays(slot, GRACE_WORKDAYS, zone)

    def published(slot):
        # The first cycle starts when the cadence was switched on.
        prior = _previous(schedule, slot)
        return latest is not None and latest > (
            deadline(prior) if prior is not None else activated_at
        )

    current = schedule.due(at)
    passed = window = None
    if current is not None:
        if at >= deadline(current):
            passed = current
        else:
            window = current
            passed = _previous(schedule, current)
    if passed is not None and deadline(passed) <= activated_at:
        passed = None
    missing = passed is not None and not published(passed)
    if missing:
        status = "missing"
    elif window is not None and not published(window):
        status = "awaiting_publication"
    else:
        status = "on_track"
    upcoming = _upcoming(schedule, at)
    return {
        "status": status,
        "missing": missing,
        "missing_since": _iso(deadline(passed)) if missing else None,
        "current_slot_at": _iso(window),
        "current_deadline_at": _iso(deadline(window)) if window is not None else None,
        "next_slot_at": _iso(upcoming),
        "next_deadline_at": _iso(deadline(upcoming)) if upcoming is not None else None,
        "latest_update_at": _iso(latest),
        "grace_workdays": GRACE_WORKDAYS,
        **business_days.basis(zone),
    }


def cadence_view(s, ctx, product_id, project_id):
    """Readable to anyone who can see the project now; rule details stay with its owner."""
    from .owner import project

    row = project(s, ctx, product_id, project_id)
    cadence = s.execute(
        text("SELECT * FROM public.project_status_cadence(:t, :p)"),
        {"t": ctx.tenant_id, "p": row.id},
    ).one_or_none()
    latest = s.scalar(
        select(func.max(ProjectStatusUpdate.created_at)).where(
            ProjectStatusUpdate.tenant_id == ctx.tenant_id,
            ProjectStatusUpdate.product_id == product_id,
            ProjectStatusUpdate.project_id == row.id,
        )
    )
    result = {
        "project_id": str(row.id),
        "latest_update_at": _iso(latest),
        "cadence": None,
        "as_of": now().isoformat(),
    }
    if cadence is None:
        return result
    schedule = Schedule.model_validate(cadence.schedule)
    result["cadence"] = {
        "rule_id": str(cadence.rule_id),
        "owner_id": str(cadence.owner_id),
        "first_at": _aware(schedule.first_at).isoformat(),
        "interval_seconds": schedule.interval_seconds,
        "calendar": schedule.calendar,
        "original_timezone": schedule.original_timezone,
        "activated_at": _aware(cadence.activated_at).isoformat(),
        **state(
            schedule,
            activated_at=cadence.activated_at,
            latest_update_at=latest,
            at=now(),
        ),
    }
    return result
