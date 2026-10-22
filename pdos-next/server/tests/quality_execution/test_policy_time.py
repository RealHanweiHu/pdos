"""Actual policy intervals remain constraints; material captures have no TTL."""

from datetime import UTC, datetime, timedelta

from pdos_next.domain.quality_execution.policy import policy_time_current

AT = datetime(2026, 10, 8, tzinfo=UTC)


def fact(identity, start, end, *, state="active"):
    return {
        "id": identity,
        "revision": 1,
        "state": state,
        "valid_from": (AT + timedelta(hours=start)).isoformat(),
        "valid_until": (AT + timedelta(hours=end)).isoformat(),
    }


def test_future_policy_activation_is_a_real_conflict_without_a_capture_deadline():
    value = {
        "id": "selected",
        "revision": 1,
        "valid_until": None,
        "source_basis": [fact("selected", -1, 4), fact("future", 1, 2)],
    }
    assert policy_time_current(value, AT)
    assert not policy_time_current(value, AT + timedelta(hours=1))
    assert policy_time_current(value, AT + timedelta(hours=2))


def test_earlier_expired_or_withdrawn_policy_does_not_expire_selected_policy():
    value = {
        "id": "selected",
        "revision": 1,
        "valid_until": None,
        "source_basis": [
            fact("selected", -1, 4),
            fact("old", -3, -2),
            fact("withdrawn", -1, 1, state="withdrawn"),
        ],
    }
    assert policy_time_current(value, AT + timedelta(hours=2))
    assert not policy_time_current(value, AT + timedelta(hours=4))


def test_mismatched_selected_version_and_malformed_interval_cannot_authorize():
    value = {"id": "other", "revision": 1, "source_basis": [fact("selected", -1, 4)]}
    assert not policy_time_current(value, AT)
    value["id"] = "selected"
    value["source_basis"][0]["valid_until"] = "2026-10-09T00:00:00"
    assert not policy_time_current(value, AT)
    assert not policy_time_current(value, AT.replace(tzinfo=None))
