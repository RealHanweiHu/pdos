"""The shared reader preserves fixed launch history and keeps results unconnected."""

from copy import deepcopy

import pytest
from test_handoff_common import documented, row_for
from verification_launch.test_pure import (
    promised,
    started,
    work,  # noqa: F401
)

from pdos_next.domain.verification_front.service import _snapshot
from pdos_next.error_catalog import REASONS
from pdos_next.errors import DomainError
from pdos_next.service import digest


def launch_row(request, operation):
    row = row_for(documented(request))
    row.operation = operation
    return row


def test_common_reader_keeps_scheduled_and_running_history(work):  # noqa: F811
    promised(work)
    scheduled = launch_row(work.request, "verification.schedule.promise")
    fixed_scheduled = deepcopy(scheduled.request_snapshot)
    assert _snapshot(scheduled).status == "scheduled"
    assert _snapshot(scheduled).timeline.actual_start is None
    # Repeated reads leave the fixed promise and its empty actual-start clock intact.
    _snapshot(scheduled)
    assert scheduled.request_snapshot == fixed_scheduled


def test_common_reader_accepts_running_only_with_matching_start_operation(work):  # noqa: F811
    mutation = started(work)
    row = launch_row(mutation.request, "test.run.start")
    loaded = _snapshot(row)
    assert loaded.status == "executing"
    assert loaded.timeline.promised_start is not None and loaded.timeline.actual_start is not None
    row.operation = "verification.handoff.accept"
    with pytest.raises(DomainError) as error:
        _snapshot(row)
    assert error.value.reason == "INTEGRITY_MISMATCH"
    assert error.value.code == REASONS["INTEGRITY_MISMATCH"]


@pytest.mark.parametrize("clock", ["preliminary_result", "final_result", "disposed"])
def test_launch_cannot_smuggle_result_or_disposition_through_shared_reader(work, clock):  # noqa: F811
    request = documented(started(work).request)
    request = request.model_copy(
        update={
            "timeline": request.timeline.model_copy(update={clock: request.timeline.actual_start})
        }
    )
    row = launch_row(request, "test.run.start")
    row.snapshot_sha256 = digest(request.model_dump(mode="json"))
    with pytest.raises(DomainError) as error:
        _snapshot(row)
    assert error.value.reason == "INTEGRITY_MISMATCH"
    assert error.value.code == REASONS["INTEGRITY_MISMATCH"]


@pytest.mark.parametrize("clock", ["promised_start", "actual_start"])
def test_running_history_cannot_lose_its_required_clock(work, clock):  # noqa: F811
    request = documented(started(work).request)
    request = request.model_copy(
        update={"timeline": request.timeline.model_copy(update={clock: None})}
    )
    row = launch_row(request, "test.run.start")
    with pytest.raises(DomainError) as error:
        _snapshot(row)
    assert error.value.reason == "INTEGRITY_MISMATCH"
    assert error.value.code == REASONS["INTEGRITY_MISMATCH"]
