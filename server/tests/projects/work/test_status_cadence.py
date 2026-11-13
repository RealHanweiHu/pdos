"""Status-update cadence: drafting slots, one working day to publish, "状态更新缺失"."""

from datetime import UTC, datetime, timedelta

from pdos_next.domain.automations.trigger_time import Schedule
from pdos_next.domain.projects.work.status_cadence import state

# Thursdays 17:00 Shanghai: 小Pai drafts, the owner publishes by Friday 17:00.
FIRST = datetime(2026, 11, 12, 9, tzinfo=UTC)  # Thursday 17:00 +08:00
WEEK = 7 * 86400
SCHEDULE = Schedule(
    first_at=FIRST, original_timezone="Asia/Shanghai", interval_seconds=WEEK
).model_dump(mode="json")
ACTIVATED = FIRST - timedelta(days=2)


def view(at, latest=None, activated=ACTIVATED):
    return state(SCHEDULE, activated_at=activated, latest_update_at=latest, at=at)


def test_before_the_first_slot_only_the_next_slot_and_deadline_show():
    value = view(FIRST - timedelta(hours=1))
    assert value["status"] == "on_track" and not value["missing"]
    assert value["next_slot_at"] == FIRST.isoformat()
    assert value["next_deadline_at"] == (FIRST + timedelta(days=1)).isoformat()
    assert value["basis_label"] == "按周一至周五估算，未扣节假日与停线"


def test_in_the_drafting_window_it_waits_for_publication():
    value = view(FIRST + timedelta(hours=2))
    assert value["status"] == "awaiting_publication" and not value["missing"]
    assert value["current_slot_at"] == FIRST.isoformat()
    assert value["current_deadline_at"] == (FIRST + timedelta(days=1)).isoformat()
    published = view(FIRST + timedelta(hours=3), latest=FIRST + timedelta(hours=2))
    assert published["status"] == "on_track"


def test_after_the_deadline_without_a_named_update_it_is_missing():
    value = view(FIRST + timedelta(days=1, minutes=1))
    assert value["status"] == "missing" and value["missing"]
    assert value["missing_since"] == (FIRST + timedelta(days=1)).isoformat()
    # An update published before the cadence was switched on does not count.
    assert view(FIRST + timedelta(days=2), latest=ACTIVATED - timedelta(hours=1))["missing"]
    # A late update clears it; published after the first deadline, it also covers the
    # second cycle, so only the third deadline without a newer update is missing again.
    late = FIRST + timedelta(days=3)
    assert view(FIRST + timedelta(days=4), latest=late)["status"] == "on_track"
    assert not view(FIRST + timedelta(days=8, hours=1), latest=late)["missing"]
    assert view(FIRST + timedelta(days=15, hours=1), latest=late)["missing"]


def test_the_deadline_skips_the_weekend():
    friday = Schedule(
        first_at=FIRST + timedelta(days=1), original_timezone="Asia/Shanghai", interval_seconds=WEEK
    ).model_dump(mode="json")
    saturday = FIRST + timedelta(days=2, hours=1)
    value = state(friday, activated_at=ACTIVATED, latest_update_at=None, at=saturday)
    assert value["status"] == "awaiting_publication"
    assert value["current_deadline_at"] == (FIRST + timedelta(days=4)).isoformat()  # Monday


def test_the_previous_cycle_stays_missing_during_the_next_drafting_window():
    second = FIRST + timedelta(days=7, hours=1)
    assert view(second)["status"] == "missing"
    # One update after the first deadline covers the next window too.
    assert view(second, latest=FIRST + timedelta(days=6))["status"] == "on_track"


def test_cycles_that_ended_before_activation_are_not_counted():
    activated = FIRST + timedelta(days=3)
    value = view(FIRST + timedelta(days=4), activated=activated)
    assert value["status"] == "on_track" and not value["missing"]
