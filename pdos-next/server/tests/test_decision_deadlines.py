from datetime import UTC, datetime, timedelta

from pdos_next.clock import proof_deadline_current


def test_only_named_t2_decision_can_have_no_confirmation_deadline():
    at = datetime(2026, 10, 9, tzinfo=UTC)
    assert proof_deadline_current("T2", None, at)
    assert not proof_deadline_current("T1", None, at)
    assert not proof_deadline_current("T0", None, at)
    for tier in ("T1", "T2"):
        assert proof_deadline_current(tier, at + timedelta(seconds=1), at)
        assert not proof_deadline_current(tier, at, at)
        assert not proof_deadline_current(tier, at - timedelta(seconds=1), at)
        assert not proof_deadline_current(tier, at.replace(tzinfo=None), at)
