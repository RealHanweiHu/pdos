"""D305 disposition accept/reject on the isolated PG (P95 补充确认，用户 2026-11-09 选 A).

The result chain here is the ordinary synthetic one. The tool-trial lookup is
patched to say this request came from a trial, so the test exercises exactly the
"required when the test holds tool-trial samples" rule and the stored outcome.
"""

# ruff: noqa: F811 - pytest imports intentionally register fixtures

from projects.test_project_first_plan import accepted, post
from sqlalchemy import select

from pdos_next.core.database import tenant_session
from pdos_next.domain.manufacturing.tool_trials import service as trials
from pdos_next.domain.verification.results.models import TestResultActionFact
from verification.results.fixtures import (  # noqa: F401
    accepted_work,
    capture,
    command,
    current_rows,
    known_configuration,
    launch_work,
    operational_work,
    ready_work,
    results_work,
)


def test_trial_disposition_requires_and_stores_accept_or_reject(results_work, monkeypatch):
    work = results_work
    first, _ = capture(work, (0,))
    accepted(work.quality, command(work, "test.results.import", captured=first))
    second, _ = capture(work, (1,))
    accepted(work.quality, command(work, "test.results.import", captured=second, final=True))
    computed = post(work.quality, command(work, "test.result.compute"))
    assert computed.status_code == 200, computed.text
    accepted(work.quality, command(work, "test.run.review"))
    request_id = current_rows(work).request.request_id
    monkeypatch.setattr(
        trials, "trial_for_request", lambda s, ctx, product_id, rid: rid == request_id or None
    )
    refused = post(work.quality, command(work, "test.disposition.decide"), True)
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["reason"] == "INVALID_PAYLOAD"
    receipt, _ = accepted(work.quality, command(work, "test.disposition.decide", outcome="accept"))
    assert receipt["subject_type"] == "test_run"
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as s:
        action = s.scalar(
            select(TestResultActionFact).where(
                TestResultActionFact.request_id == request_id,
                TestResultActionFact.operation == "test.disposition.decide",
            )
        )
        assert action.input_snapshot["outcome"] == "accept"
        assert trials.tooling_status(action.input_snapshot["outcome"]) == "accepted"
