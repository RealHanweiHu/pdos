"""Working-day arithmetic for follow-up rules, estimated Monday to Friday (P41 item 10).

Until the tenant working calendar (D221) is connected, a working day is any
Monday to Friday in the given IANA zone; holidays and line stops are not
deducted, and every result says so. Time is counted only on weekdays: one
working day after Friday 15:00 is Monday 15:00, and one working day after a
Saturday is Tuesday 00:00 (the clock starts on Monday 00:00).

`work_weekday_add(at, days, zone)` in PostgreSQL (migration s0_0905) is the same
rule for read projections; tests hold the two to the same results. When D221
lands, both switch to the tenant calendar together.
"""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BASIS = "weekdays_estimate"
BASIS_LABEL = "按周一至周五估算，未扣节假日与停线"
# The weekday estimate needs a zone; tasks carry none of their own yet.
DEFAULT_TIMEZONE = "Asia/Shanghai"
MAX_DAYS = 366


def _zone(timezone):
    try:
        return ZoneInfo(timezone)
    except (ValueError, ZoneInfoNotFoundError, TypeError) as exc:
        raise ValueError("An actual IANA timezone is required") from exc


def add_weekdays(at: datetime, days: int, timezone: str = DEFAULT_TIMEZONE) -> datetime:
    """Return the UTC instant `days` working days after `at` in `timezone`."""
    if not isinstance(at, datetime) or at.utcoffset() is None:
        raise ValueError("An aware instant is required")
    if type(days) is not int or not 0 <= days <= MAX_DAYS:
        raise ValueError("Working days must be an integer from 0 to 366")
    zone = _zone(timezone)
    local = at.astimezone(zone).replace(tzinfo=None)
    if local.isoweekday() >= 6:
        local = datetime.combine(local.date() + timedelta(days=8 - local.isoweekday()), time())
    for _ in range(days):
        local += timedelta(days=1)
        if local.isoweekday() == 6:
            local += timedelta(days=2)
    return local.replace(tzinfo=zone).astimezone(UTC)


def is_past(anchor: datetime, days: int, at: datetime, timezone: str = DEFAULT_TIMEZONE) -> bool:
    """Whether `at` is at or after `days` working days from `anchor`."""
    return at >= add_weekdays(anchor, days, timezone)


def basis(timezone: str = DEFAULT_TIMEZONE) -> dict:
    """What every result built on this estimate carries (D17 / P41 item 10)."""
    _zone(timezone)
    return {"basis": BASIS, "basis_label": BASIS_LABEL, "timezone": timezone}
