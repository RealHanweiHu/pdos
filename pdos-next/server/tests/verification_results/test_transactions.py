"""Scoped real-PG result transaction proofs. Root alone runs these tests."""

# ruff: noqa: F811 - pytest imports intentionally register fixtures
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select
from test_project_first_plan import accepted, post
from verification_results.fixtures import (  # noqa: F401
    accepted_work,
    capture,
    command,
    current_rows,
    known_configuration,
    launch_work,
    listing,
    operational_work,
    ready_work,
    results_work,
    upload_report,
)

from pdos_next.database import tenant_session
from pdos_next.domain.build_operational_facts.models import ResourceOccupancy
from pdos_next.domain.test_resources.models import SampleRunUsage, TestResourceReservation
from pdos_next.domain.verification_front.models import FormalVerificationRequest
from pdos_next.domain.verification_launch.models import (
    VerificationRunCurrent,
    VerificationRunVersion,
)
from pdos_next.domain.verification_results.models import (
    MeasurementRecord,
    TestResultActionFact,
    TestResultProjection,
)
from pdos_next.models import Audit, Confirmation, Outbox, Receipt
from pdos_next.service import digest


def counts(work, *, result_only=False):
    with tenant_session(work.setup.engine, work.setup.tenant, actor_id=work.quality.human, category_id=work.setup.category) as session:

        def count(model):
            statement = select(func.count()).select_from(model)
            if result_only:
                operations = (
                    "test.results.import",
                    "test.result.compute",
                    "test.run.review",
                    "test.disposition.decide",
                )
                if model in (Receipt, Audit):
                    statement = statement.where(model.operation.in_(operations))
                elif model is Outbox:
                    statement = statement.join(
                        Receipt,
                        (Receipt.tenant_id == Outbox.tenant_id) & (Receipt.id == Outbox.receipt_id),
                    ).where(Receipt.operation.in_(operations))
            return session.scalar(statement)

        return {
            m.__tablename__: count(m)
            for m in (
                FormalVerificationRequest,
                VerificationRunVersion,
                TestResultActionFact,
                MeasurementRecord,
                TestResultProjection,
                TestResourceReservation,
                ResourceOccupancy,
                SampleRunUsage,
                Receipt,
                Audit,
                Outbox,
            )
        }


def test_partial_final_compute_review_disposition_same_chain_retains_prior_execution(results_work):
    work = results_work
    first, _ = capture(work, (0,))
    baseline = counts(work, result_only=True)
    original = current_rows(work)
    value = command(work, "test.results.import", captured=first)
    receipt, prepared = accepted(work.quality, value)
    assert receipt["subject_type"] == "test_run"
    partial = current_rows(work)
    assert partial.run.status == "running" and partial.run.result == "indeterminate"
    assert (
        len(partial.run.measurements) == 1
        and len(partial.run.partial_returns[0].pending_coverage) == 1
    )
    assert partial.request.request_snapshot["timeline"]["final_result"] is None
    replay = post(work.quality, prepared)
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == receipt["id"]
    alias = deepcopy(prepared)
    alias.update(command_id=str(uuid4()), idempotency_key=str(uuid4()))
    replay = post(work.quality, alias)
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == receipt["id"]
    second, _ = capture(work, (1,))
    final_receipt, _ = accepted(
        work.quality, command(work, "test.results.import", captured=second, final=True)
    )
    final = current_rows(work)
    assert final.run.status == "results_pending" and final.run.result == "pass"
    assert len(final.run.measurements) == 2 and final.run.measurements[0].raw_value == "10.0000"
    assert final.request.status == "reported"
    assert (
        final.run.actual_start == original.run.actual_start
        and final.run.execution == original.run.execution
    )
    fixed_id = final.row.id
    computed_response = post(work.quality, command(work, "test.result.compute"))
    assert computed_response.status_code == 200, computed_response.text
    computed = computed_response.json()
    assert (
        computed["subject_type"] == "test_result_projection"
        and current_rows(work).row.id == fixed_id
    )
    review, _ = accepted(work.quality, command(work, "test.run.review"))
    assert review["subject_type"] == "test_run" and current_rows(work).run.status == "reviewed"
    assert current_rows(work).request.id == final.request.id
    disposition, _ = accepted(work.quality, command(work, "test.disposition.decide"))
    assert disposition["subject_type"] == "test_run"
    disposed = current_rows(work)
    assert disposed.run.status == "disposed" and disposed.request.status == "disposed"
    assert disposed.run.result == "pass" and disposed.run.measurements == final.run.measurements
    after = counts(work, result_only=True)
    for model in (TestResourceReservation, ResourceOccupancy, SampleRunUsage):
        assert after[model.__tablename__] == baseline[model.__tablename__]
    assert (
        after[TestResultActionFact.__tablename__]
        == baseline[TestResultActionFact.__tablename__] + 4
    )
    assert after[MeasurementRecord.__tablename__] == baseline[MeasurementRecord.__tablename__] + 2
    assert after[Receipt.__tablename__] == baseline[Receipt.__tablename__] + 5
    assert after[Audit.__tablename__] == baseline[Audit.__tablename__] + 5
    assert after[Outbox.__tablename__] == baseline[Outbox.__tablename__] + 5
    with tenant_session(work.setup.engine, work.setup.tenant, actor_id=work.quality.human, category_id=work.setup.category) as session:
        original_row = session.get(VerificationRunVersion, work.original_start_id)
        assert original_row.run_snapshot == work.original_start
        action = session.scalar(
            select(TestResultActionFact).where(
                TestResultActionFact.next_run_version_id == UUID(final_receipt["subject_id"])
            )
        )
        projection = session.get(TestResultProjection, action.projection_id)
        assert projection.run_version_id == UUID(final_receipt["subject_id"])
        assert projection.basis_sha256 == digest(projection.input_snapshot)
        projection_basis = projection.basis_sha256
        assert (
            session.scalar(
                select(VerificationRunCurrent.run_version_id).where(
                    VerificationRunCurrent.tenant_id == work.setup.tenant,
                    VerificationRunCurrent.run_id == work.binding.run_id,
                )
            )
            == disposed.row.id
        )
    view = listing(work)
    current = next(r for r in view["runs"] if r["id"] == str(disposed.row.id))
    assert current["zero_occupancy"] is False and current["occupancy"] and current["sample_usage"]
    assert current["current_projection"]["basis_sha256"] == projection_basis
    assert view["report_sources"][0]["lines"][0]["original_line"] == 1


def test_import_last_outbox_failure_rolls_back_measurements_projection_chain_and_token(
    results_work,
):
    work = results_work
    captured, _ = capture(work, (0,))
    value = command(work, "test.results.import", captured=captured)
    reviewed = post(work.quality, value, True)
    assert reviewed.status_code == 200, reviewed.text
    prepared = reviewed.json()["command"]
    token = prepared["payload"]["confirmation_token"]
    before = counts(work)
    fixed = current_rows(work)

    def fail(_mapper, _connection, _target):
        raise RuntimeError("Synthetic terminal outbox failure")

    event.listen(Outbox, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="Synthetic terminal outbox failure"):
            post(work.quality, prepared)
    finally:
        event.remove(Outbox, "before_insert", fail)
    assert counts(work) == before
    after = current_rows(work)
    assert after.row.id == fixed.row.id and after.request.id == fixed.request.id
    with tenant_session(work.setup.engine, work.setup.tenant, actor_id=work.quality.human, category_id=work.setup.category) as session:
        assert (
            session.scalar(
                select(Confirmation.consumed).where(Confirmation.token_hash == digest(token))
            )
            is False
        )
    receipt, _ = accepted(work.quality, value)
    assert receipt["subject_type"] == "test_run"
