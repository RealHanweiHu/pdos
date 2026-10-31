"""Calendar presets preserve local wall slots and the original tick watermark contract."""

from contextlib import nullcontext
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.automations.trigger_time import Schedule


def dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def schedule(kind="weekdays", first="2026-10-30T09:00:00-04:00", zone="America/New_York"):
    return Schedule(first_at=dt(first), original_timezone=zone, calendar=kind)


def test_weekdays_skip_weekend_preserve_nine_am_across_autumn_dst_and_tick_replay():
    s = schedule()
    friday = dt("2026-10-30T13:00:00Z")
    monday = dt("2026-11-02T14:00:00Z")
    assert s.due(friday) == friday
    for point in (dt("2026-10-31T16:00:00Z"), dt("2026-11-01T18:00:00Z")):
        assert s.due(point, last_due=friday) is None
        assert s.wake_before(point, monday + timedelta(hours=1)) == monday
    assert s.due(monday) == monday
    assert s.due(monday, last_due=friday) == monday
    assert s.due(monday, last_due=monday) is None
    assert (monday - friday).total_seconds() == 73 * 3600


def test_weekly_monday_preserves_local_clock_across_spring_dst():
    s = schedule("weekly_monday", "2026-03-02T09:00:00-05:00")
    first, second = dt("2026-03-02T14:00:00Z"), dt("2026-03-09T13:00:00Z")
    assert s.due(second, last_due=first) == second
    assert s.due(second + timedelta(days=2), last_due=second) is None
    assert s.wake_before(first, second + timedelta(hours=1)) == second
    assert (second - first).total_seconds() == 167 * 3600


def test_skipped_local_date_is_not_shifted_or_invented():
    s = schedule("weekdays", "2011-12-29T09:00:00-10:00", "Pacific/Apia")
    thursday, monday = dt("2011-12-29T19:00:00Z"), dt("2012-01-01T19:00:00Z")
    assert s.due(dt("2011-12-30T20:00:00Z"), last_due=thursday) is None
    assert s.wake_before(thursday, monday + timedelta(hours=1)) == monday
    assert s.due(monday, last_due=thursday) == monday


def test_calendar_latest_slot_no_backlog_expiry_and_supervision_bound():
    s = schedule()
    last = dt("2026-11-06T14:00:00Z")
    assert s.due(dt("2026-11-06T20:00:00Z")) == last
    assert s.wake_before(last, last + timedelta(seconds=30)) == last + timedelta(seconds=30)
    expiring = s.model_copy(update={"expires_at": last})
    assert expiring.due(last) is None
    with pytest.raises(ValueError):
        s.due(last, last_due=last + timedelta(seconds=1))


def test_none_calendar_preserves_old_serialized_shape_and_interval_semantics():
    raw = {"first_at": "2026-10-30T13:00:00Z", "original_timezone": "America/New_York",
           "interval_seconds": 86400, "expires_at": None}
    implicit = Schedule.model_validate(raw)
    explicit = Schedule.model_validate({**raw, "calendar": None})
    assert implicit.model_dump(mode="json") == explicit.model_dump(mode="json") == raw
    assert implicit.due(dt("2026-11-01T13:00:00Z")) == dt("2026-11-01T13:00:00Z")
    assert "calendar" not in implicit.model_dump()


def test_calendar_rejects_ambiguous_modes_and_unselected_first_date():
    with pytest.raises(ValidationError):
        Schedule(first_at=dt("2026-10-30T09:00:00-04:00"), original_timezone="America/New_York",
                 interval_seconds=86400, calendar="weekdays")
    with pytest.raises(ValidationError):
        schedule("weekly_monday")  # Friday is not a selected first Monday.
    with pytest.raises(ValidationError):
        schedule("weekdays", "2026-10-31T09:00:00-04:00")
    assert schedule().first_at.tzinfo is not None


def test_repeated_weekday_wall_time_uses_the_earlier_instant_once():
    s = schedule("weekdays", "2026-10-29T23:30:00+03:00", "Africa/Cairo")
    first, repeated = dt("2026-10-29T20:30:00Z"), dt("2026-10-29T21:30:00Z")
    assert s.due(repeated) == first
    assert s.due(repeated, last_due=first) is None
    with pytest.raises(ValidationError):
        schedule("weekdays", "2026-10-29T23:30:00+02:00", "Africa/Cairo")


def test_missing_weekday_hour_is_skipped_not_silently_shifted():
    s = schedule("weekdays", "2026-04-23T00:30:00+02:00", "Africa/Cairo")
    prior, next_slot = dt("2026-04-22T22:30:00Z"), dt("2026-04-26T21:30:00Z")
    assert s.due(dt("2026-04-24T01:00:00Z"), last_due=prior) is None
    assert s.wake_before(prior, next_slot + timedelta(hours=1)) == next_slot
    assert s.due(next_slot, last_due=prior) == next_slot


def test_actual_service_tick_uses_calendar_and_persisted_watermark_without_requeue(monkeypatch):
    from pdos_next.domain.automations import service_runtime as runtime

    config = schedule()
    grant = SimpleNamespace(id=uuid4(), rule_id=uuid4(), published_version_id=uuid4(),
                            expires_at=None)
    pointer = SimpleNamespace(published_version_id=grant.published_version_id, state="active",
                              admitted_count=0, last_admitted_at=None)
    spec = SimpleNamespace(trigger_kind="schedule", trigger_config=config.model_dump(mode="json"),
                           max_runs=52, cooldown_seconds=0)
    point, previous, queued = [dt("2026-10-30T13:00:00Z")], [None], []

    class SQLTransport:
        # These are saved rows/watermarks only, not a substitute for PG RLS or
        # the real unique-attempt constraint verified by the parent checkpoint.
        def scalar(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            if entity is runtime.Current:
                return pointer
            assert entity is runtime.Attempt
            return previous[0]

        def scalars(self, _statement):
            return []

    s = SQLTransport()
    monkeypatch.setattr(runtime, "context", lambda _ref: object())
    monkeypatch.setattr(runtime, "now", lambda: point[0])
    monkeypatch.setattr(runtime, "session", lambda *_a: nullcontext(s))
    monkeypatch.setattr(runtime, "saved", lambda *_a, **_k: (grant, None, spec))
    monkeypatch.setattr(runtime, "stopped_reason", lambda *_a: None)
    monkeypatch.setattr(runtime, "condition_state", lambda *_a: "ready")

    def enqueue(_s, _grant, _spec, *, key, due_at, origin):
        assert _s is s and _grant is grant and _spec is spec
        queued.append((key, due_at, origin))
        previous[0] = due_at

    monkeypatch.setattr(runtime, "enqueue", enqueue)
    for instant in ("2026-10-30T13:00:00Z", "2026-10-30T13:00:00Z",
                    "2026-10-31T13:00:00Z", "2026-11-02T14:00:00Z",
                    "2026-11-02T14:00:00Z"):
        point[0] = dt(instant)
        assert runtime.tick(object(), {})["state"] == "active"
    assert [key for key, _due, _origin in queued] == [
        "schedule:2026-10-30T13:00:00+00:00", "schedule:2026-11-02T14:00:00+00:00",
    ]
    assert all(origin["original_timezone"] == "America/New_York" for _, _, origin in queued)
