"""Persist precise pending work from the partial-result form without fabricating it."""

import pytest
from pydantic import ValidationError

from pdos_next.schemas.verification.contracts import ResultsSubmit

from .helpers import event, measurement, uid
from .test_handlers import perform, running


def test_partial_return_preserves_reason_owner_source_and_exact_pending_pairs(host):
    current = running(host)
    payload = ResultsSubmit(
        measurements=(measurement(pair=current.coverage[0]),), at=event("partial", offset=30),
        incomplete_reason="第二模穴测量等待设备", next_owner_id=uid("quality-next-owner"),
    )
    perform(host, "test.results.import", current.id, current.revision, payload, command="partial")
    saved = host.commands.run_records[current.id]
    returned = saved.partial_returns[0]
    assert returned.returned_coverage == current.coverage[:1]
    assert returned.pending_coverage == current.coverage[1:]
    assert returned.reason == payload.incomplete_reason
    assert returned.next_owner_id == payload.next_owner_id
    assert returned.at.source == payload.at.source
    assert saved.status == "running" and saved.final_result is None


@pytest.mark.parametrize("changes", [
    {"incomplete_reason": "只给原因"}, {"next_owner_id": uid("owner")},
    {"final": True, "incomplete_reason": "最终不能暗建责任", "next_owner_id": uid("owner")},
])
def test_partial_responsibility_is_paired_and_not_hidden_in_final(changes):
    with pytest.raises(ValidationError):
        ResultsSubmit(measurements=(measurement(),), at=event("partial", offset=30), **changes)
