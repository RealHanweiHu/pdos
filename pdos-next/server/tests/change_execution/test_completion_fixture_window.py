"""The long native scenario declares its own finite qualifications before signing."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from . import test_native_field_completion_chain as scenario


@pytest.mark.parametrize(
    "hours,deadline_hours,expected", ((None, None, 2), (4, None, 4), (4, 3, 3))
)
def test_completion_fixture_declares_finite_window_for_only_its_named_operations(
    monkeypatch, hours, deadline_hours, expected
):
    at = datetime(2026, 10, 22, tzinfo=UTC)
    requester, reviewer = uuid4(), uuid4()
    work = SimpleNamespace(
        quality=SimpleNamespace(human=requester),
        independent_reviewer=SimpleNamespace(human=reviewer),
        build_id=uuid4(),
        setup=SimpleNamespace(
            test_authorization_window=timedelta(hours=hours) if hours is not None else None,
            test_authorization_until=(
                at + timedelta(hours=deadline_hours) if deadline_hours is not None else None
            ),
        ),
    )
    imports = []
    monkeypatch.setattr(scenario, "now", lambda: at)
    monkeypatch.setattr(
        scenario, "import_authority",
        lambda actual, role, kind, **fields: imports.append((actual, role, kind, fields)),
    )
    scenario.completion_people(work)
    assert len(imports) == 4
    for actual, role, kind, fields in imports:
        assert actual is work and role == "quality" and kind in {"duty", "qualification"}
        assert datetime.fromisoformat(fields["valid_from"]) == at - timedelta(minutes=1)
        assert datetime.fromisoformat(fields["valid_until"]) == at + timedelta(hours=expected)
        expected_operations = {"change.verification.record", "change.close"}
        if fields["subject_id"] == str(requester):
            expected_operations.add("change.effectivity.record")
        else:
            assert fields["subject_id"] == str(reviewer)
        assert set(fields["operations"]) == expected_operations


def test_completion_counts_keep_the_actual_named_callers_private_proof_scope(monkeypatch):
    requester, reviewer = object(), object()
    work = SimpleNamespace(quality=requester)

    def counts(acting):
        assert acting.quality is reviewer
        return {"confirmations": 3}

    @contextmanager
    def session(actual, caller):
        assert actual is work and caller is reviewer
        yield SimpleNamespace(scalar=lambda *_: 2)

    monkeypatch.setattr(scenario.helper, "counts", counts)
    monkeypatch.setattr(scenario.helper, "session", session)
    result = scenario.completion_counts(work, reviewer)
    assert result == {"confirmations": 3, "change_completion_records": 2}
