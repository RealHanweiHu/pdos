"""Which aged-out originals are renewed, and the reason people see (D215); no database."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.core.models import now
from pdos_next.evidence_security.types import SecurityDecision, SecurityState
from pdos_next.originals import rescan


def gate(*reasons, state=SecurityState.STALE):
    return SecurityDecision(state, False, True, tuple(reasons))


CLEAN, FAILED = SimpleNamespace(status="clean"), SimpleNamespace(status="unavailable")


@pytest.mark.parametrize(
    ("decision", "stored", "expected"),
    [
        (gate("SCAN_EXPIRED"), CLEAN, True),
        (gate("SCAN_EXPIRED", "SCAN_BUDGET_EXPIRED"), CLEAN, True),
        (gate("SCANNER_CONFIGURATION_CHANGED"), CLEAN, True),
        (gate("SCAN_EXPIRED"), FAILED, False),  # Failed or infected: a person decides.
        (gate("SOURCE_OR_ACCESS_CHANGED"), CLEAN, False),
        (gate("SCAN_REQUIRED", state=SecurityState.NOT_SCANNED), None, False),
        (SecurityDecision(SecurityState.CLEAN, True, False, ()), CLEAN, False),
        (None, None, False),
    ],
)
def test_only_once_clean_receipts_that_aged_out_or_lost_their_scanner_are_renewed(
    decision, stored, expected
):
    assert rescan.renewable(decision, stored) is expected


RUNTIME = object()


class FakeSession:
    def __init__(self, principal, grant, runtime=RUNTIME):
        self.principal, self.grant, self.runtime = principal, grant, runtime

    def get_bind(self):
        return SimpleNamespace(_pdos_security_runtime=self.runtime)

    def get(self, _model, _identity):
        return self.principal

    def scalar(self, _query):
        return self.grant


def reason(*, status="parsed", active=True, kind="human", grant=True, can_write=True,
           expires=timedelta(days=1), runtime=RUNTIME):
    original = SimpleNamespace(status=status, tenant_id=uuid4(), category_id=uuid4())
    principal = SimpleNamespace(active=active, kind=kind)
    expires_at = None if expires is None else now() + expires
    row = SimpleNamespace(can_write=can_write, expires_at=expires_at)
    session = FakeSession(principal, row if grant else None, runtime)
    return rescan.rescan_reason(session, original, SimpleNamespace(requester_id=uuid4()))


def test_reason_says_scheduled_or_names_why_it_cannot_be_automatic():
    assert reason() == "RESCAN_SCHEDULED"
    assert reason(expires=None) == "RESCAN_SCHEDULED"
    assert reason(runtime=None) == "SCANNER_UNAVAILABLE"
    assert reason(status="needs_ocr") == "RESCAN_NOT_AUTOMATIC"
    for change in (
        {"active": False}, {"kind": "agent"}, {"grant": False}, {"can_write": False},
        {"expires": -timedelta(seconds=1)},
    ):
        assert reason(**change) == "RESCAN_REQUESTER_UNAVAILABLE", change
