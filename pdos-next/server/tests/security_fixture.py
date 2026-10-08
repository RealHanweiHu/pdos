"""Explicit synthetic worker facts for PG tests; no scanner/production qualification."""

from threading import Lock

import pytest

from pdos_next.evidence_processing import parse_original
from pdos_next.evidence_security.types import (
    ScanConfiguration,
    ScannerIdentity,
    ScanPolicy,
    ScanReceipt,
    ScanStatus,
)
from pdos_next.models import now
from pdos_next.original_security import SecurityRuntime, configure, queue_uploaded, scan_requested
from pdos_next.originals import parse_uploaded


class SyntheticScanner:
    """Only an injected test port; it neither inspects bytes nor certifies a scanner."""

    def __init__(self, status=ScanStatus.CLEAN):
        self.status = status
        self.calls = 0
        self.before_reply = None
        self.transform = None
        self._lock = Lock()

    async def scan(self, request):
        with self._lock:
            self.calls += 1
        started = now()
        if self.before_reply:
            self.before_reply(request)
        result = ScanReceipt(
            request.request_id,
            request.binding,
            request.scanner,
            request.policy.digest,
            self.status,
            started,
            now(),
            None if self.status == ScanStatus.CLEAN else f"SYNTHETIC_{self.status.value.upper()}",
        )
        return self.transform(result) if self.transform else result


def synthetic_runtime(scanner=None, parser=parse_original):
    return SecurityRuntime(
        ScanConfiguration(
            ScannerIdentity("synthetic-test-port", "fixture-only@1", "fixture-rules@1"),
            ScanPolicy(),
        ),
        scanner or SyntheticScanner(),
        parser,
    )


@pytest.fixture
def secured_runtime(setup):
    prior = getattr(setup.engine, "_pdos_security_runtime", None)
    runtime = synthetic_runtime()
    configure(setup.engine, runtime)
    try:
        yield runtime
    finally:
        configure(setup.engine, prior)


def ensure_scanned(engine, reference):
    queued = queue_uploaded(engine, reference)
    result = scan_requested(engine, {**reference, "subject_id": queued["request_id"]})
    assert result["status"] == "clean", result
    return result


def secured_parse(engine, reference, store):
    ensure_scanned(engine, reference)
    return parse_uploaded(engine, reference, store)
