"""Actual handoff/result commands determine named, side-effect-free attention.

The inherited fixtures register explicit synthetic professional qualifications and
real source artifacts. Only the root checkpoint executes this PostgreSQL module.
"""

# ruff: noqa: F811 - imported fixtures intentionally register their dependency tree

from sqlalchemy import event, select
from sqlalchemy.orm import Session
from test_project_first_plan import accepted
from verification_handoff import fixtures as physical
from verification_handoff.fixtures import handoff_work  # noqa: F401
from verification_results import fixtures as results
from verification_results.fixtures import (  # noqa: F401
    accepted_work,
    known_configuration,
    launch_work,
    operational_work,
    ready_work,
    results_work,
)

from pdos_next.domain.verification_front.models import (
    FormalVerificationCurrent,
    FormalVerificationRequest,
)
from pdos_next.domain.verification_handoff.models import (
    ActualMethodApplicability,
    ActualMethodBatch,
    ActualMethodCurrent,
    VerificationHandoffFact,
)
from pdos_next.domain.verification_launch.models import (
    VerificationRunCurrent,
    VerificationRunVersion,
)
from pdos_next.domain.verification_results.models import (
    MeasurementImportCapture,
    MeasurementRecord,
    TestResultActionFact,
    TestResultProjection,
)
from pdos_next.models import Audit, Confirmation, Outbox, Receipt, RequestKey
from pdos_next.service import digest


def _snapshot(work):
    """Inspect this isolated tenant, including rows hidden from another caller."""
    with Session(work.setup.admin) as session:
        result = {}
        for model in (
            FormalVerificationRequest,
            FormalVerificationCurrent,
            ActualMethodBatch,
            ActualMethodApplicability,
            ActualMethodCurrent,
            VerificationHandoffFact,
            VerificationRunVersion,
            VerificationRunCurrent,
            MeasurementImportCapture,
            MeasurementRecord,
            TestResultActionFact,
            TestResultProjection,
            Receipt,
            Confirmation,
            Audit,
            Outbox,
            RequestKey,
        ):
            rows = session.execute(
                select(model.__table__)
                .where(model.tenant_id == work.setup.tenant)
                .order_by(model.id)
            ).mappings()
            values = [dict(row) for row in rows]
            result[model.__tablename__] = (len(values), digest(values))
        return result


def _receive(work, caller, *, kind, source_id):
    before, statements = _snapshot(work), []

    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(work.setup.engine, "before_cursor_execute", capture)
    try:
        response = caller.client.get(
            "/v1/personal/attention",
            # Personal scope deliberately has no category query parameter.
            params={"queue": "receive", "page_size": 100},
            headers=caller.headers,
        )
    finally:
        event.remove(work.setup.engine, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    assert _snapshot(work) == before
    assert not any(
        statement.lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE "))
        for statement in statements
    )
    page = response.json()
    assert page["version"] == "personal-attention/v1"
    assert page["queue"] == "receive" and page["principal_id"] == str(caller.human)
    assert page["total_records"] == len(page["items"]) and page["next_cursor"] is None
    assert all(item["responsible"]["id"] == str(caller.human) for item in page["items"])
    return [
        item
        for item in page["items"]
        if item["kind"] == kind and item["source"]["id"] == str(source_id)
    ]


def _pending(work, caller, *, kind, source_id, version_id, revision, state, count):
    items = _receive(work, caller, kind=kind, source_id=source_id)
    assert len(items) == 1
    item = items[0]
    assert item["id"] == f"{kind}:{source_id}"
    assert item["source"] == {
        "id": str(source_id),
        "version_id": str(version_id),
        "revision": revision,
        "epoch": None,
    }
    assert item["state"] == state and item["responsibility"] == "named_return_owner"
    assert item["target"] == "project" and item["blocked"] is None
    assert item["category"]["id"] == str(work.setup.category)
    assert item["product"]["id"] == str(work.setup.product)
    assert item["project"]["id"] == str(work.config["project"])
    assert item["due_at"] is item["valid_until"] is None
    assert item["details"] == {
        "stage": "handoff_return" if kind == "verification_handoff_return" else "results_return",
        "coverage_count": count,
        "build_id": str(work.build_id),
    }


def test_actual_handoff_latest_return_owner_and_accepted_coverage_leave_receive(handoff_work):
    work = handoff_work
    kind = "verification_handoff_return"
    identity = work.request_id
    assert not _receive(work, work.engineer, kind=kind, source_id=identity)
    accepted(work.quality, physical.actual_method(work))
    accepted(work.engineer, physical.handoff(work))
    offered = physical.current(work)
    coverage = offered["offered_coverage"]
    assert len(coverage) == 2
    assert not _receive(work, work.engineer, kind=kind, source_id=identity)

    accepted(
        work.quality,
        physical.handoff(
            work,
            operation="verification.handoff.accept",
            coverage=coverage[:1],
            returned=coverage[1:],
        ),
    )
    partial = physical.current(work)
    assert partial["accepted_coverage"] == coverage[:1]
    assert partial["returns"][-1]["coverage"] == coverage[1:]

    def pending(caller, row):
        _pending(
            work,
            caller,
            kind=kind,
            source_id=identity,
            version_id=row["id"],
            revision=row["revision"],
            state=row["status"],
            count=len(coverage[1:]),
        )

    pending(work.engineer, partial)
    assert not _receive(work, work.setup, kind=kind, source_id=identity)

    # Return requires an actual next human. None is not a legal payload; use the
    # existing manufacturing/project owner, then return the same pending pair
    # to engineering through another real, sourced quality command.
    for next_owner, previous_owner in (
        (work.setup, work.engineer),
        (work.engineer, work.setup),
    ):
        command = physical.handoff(
            work, operation="verification.handoff.return", coverage=coverage[1:]
        )
        command["payload"]["next_owner_id"] = str(next_owner.human)
        accepted(work.quality, command)
        returned = physical.current(work)
        assert returned["returns"][-1]["next_owner_id"] == str(next_owner.human)
        assert returned["returns"][-1]["coverage"] == coverage[1:]
        assert returned["accepted_coverage"] == coverage[:1]
        assert not _receive(work, previous_owner, kind=kind, source_id=identity)
        pending(next_owner, returned)

    accepted(
        work.quality,
        physical.handoff(work, operation="verification.handoff.accept", coverage=coverage[1:]),
    )
    received = physical.current(work)
    assert len(received["accepted_coverage"]) == len(coverage)
    assert len(received["returns"]) == len(partial["returns"]) + 2
    for caller in (work.engineer, work.setup, work.quality):
        assert not _receive(work, caller, kind=kind, source_id=identity)


def test_actual_partial_result_return_leaves_receive_after_missing_measurement(results_work):
    work = results_work
    kind = "verification_result_return"
    initial = results.current_rows(work)
    identity = initial.row.run_id
    assert not _receive(work, work.quality, kind=kind, source_id=identity)

    captured, _ = results.capture(work, (0,))
    accepted(work.quality, results.command(work, "test.results.import", captured=captured))
    partial = results.current_rows(work)
    assert partial.run.status == "running" and len(partial.run.measurements) == 1
    pending = partial.run.partial_returns[-1]
    assert str(pending.next_owner_id) == str(work.quality.human)
    assert len(pending.pending_coverage) == 1
    _pending(
        work,
        work.quality,
        kind=kind,
        source_id=identity,
        version_id=partial.row.id,
        revision=partial.row.revision,
        state=partial.run.status,
        count=len(pending.pending_coverage),
    )
    assert not _receive(work, work.engineer, kind=kind, source_id=identity)

    captured, _ = results.capture(work, (1,))
    accepted(
        work.quality,
        results.command(work, "test.results.import", captured=captured, final=True),
    )
    completed = results.current_rows(work)
    assert len(completed.run.measurements) == len(completed.run.coverage) == 2
    assert completed.run.status == "results_pending"
    # The saved partial return remains history; only its unmeasured coverage
    # determines current attention. No attention read updates the original fact.
    assert completed.run.partial_returns == partial.run.partial_returns
    assert not _receive(work, work.quality, kind=kind, source_id=identity)
