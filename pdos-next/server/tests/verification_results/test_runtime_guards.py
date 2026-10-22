"""Opaque host epoch changes during bounded original I/O; root runs real PG."""

# ruff: noqa: F811 - imported fixtures register the shared real dependency tree
import pytest
from sqlalchemy import select
from test_project_first_plan import accepted, post

from pdos_next.database import tenant_session
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.test_resources import service as resources
from pdos_next.models import Confirmation
from pdos_next.service import digest
from verification_results.fixtures import (  # noqa: F401
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
from verification_results.test_transactions import counts


@pytest.mark.parametrize("issuer", ["professional", "resources"])
def test_store_io_rechecks_import_issuer_and_preserves_fixed_start_issuer(
    results_work, monkeypatch, issuer
):
    from pdos_next.domain.build_operational_facts.models import ResourceOccupancy
    from pdos_next.domain.test_resources.models import SampleRunUsage, TestResourceReservation
    from pdos_next.domain.verification_launch.models import VerificationRunVersion
    from pdos_next.domain.verification_results.models import MeasurementRecord, TestResultActionFact
    from pdos_next.models import Receipt

    work = results_work
    captured, _ = capture(work, (0,))
    value = command(work, "test.results.import", captured=captured)
    preview = post(work.quality, value, True)
    assert preview.status_code == 200, preview.text
    prepared = preview.json()["command"]
    token = prepared["payload"]["confirmation_token"]
    before = counts(work)
    fixed = current_rows(work)
    original = work.report_store.read_original
    fired = []

    def revoked_after_bytes(reference):
        content = original(reference)
        if not fired:
            fired.append(reference.id)
            if issuer == "professional":
                professional.disable_issuer(work.setup.engine, work.professional_issuer.key)
            else:
                resources.disable_issuer(work.setup.engine, work.test_issuer.key)
        return content

    monkeypatch.setattr(work.report_store, "read_original", revoked_after_bytes)
    response = post(work.quality, prepared)
    assert fired
    after = current_rows(work)
    if issuer == "professional":
        # This importer consumes the currently signed result authority.
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["reason"] == "SOURCE_STALE"
        assert counts(work) == before
        assert after.row.id == fixed.row.id and after.request.id == fixed.request.id
    else:
        # The original Start's resource issuer is already fixed. Registry
        # changes during report IO cannot reopen its historical qualification.
        assert response.status_code == 200, response.text
        current_counts = counts(work)
        for model in (MeasurementRecord, TestResultActionFact, VerificationRunVersion, Receipt):
            table = model.__tablename__
            assert current_counts[table] == before[table] + 1, table
        for model in (TestResourceReservation, ResourceOccupancy, SampleRunUsage):
            table = model.__tablename__
            assert current_counts[table] == before[table], table
        assert after.row.id != fixed.row.id and after.request.id != fixed.request.id
        assert after.run.actual_start == fixed.run.actual_start
        assert after.run.samples == fixed.run.samples
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as session:
        assert (
            session.scalar(
                select(Confirmation.consumed).where(Confirmation.token_hash == digest(token))
            )
            is (issuer == "resources")
        )


def test_compute_semantic_replay_returns_prior_receipt_without_measurement_io(
    results_work, monkeypatch
):
    work = results_work
    captured, _ = capture(work, (0,))
    accepted(work.quality, command(work, "test.results.import", captured=captured))
    value = command(work, "test.result.compute")
    response = post(work.quality, value)
    assert response.status_code == 200, response.text
    before = counts(work)
    original = work.report_store.read_original
    fired = []

    def revoke(reference):
        content = original(reference)
        if not fired:
            fired.append(reference.id)
            resources.disable_issuer(work.setup.engine, work.test_issuer.key)
        return content

    monkeypatch.setattr(work.report_store, "read_original", revoke)
    replay = post(work.quality, value)
    assert not fired and replay.status_code == 200, replay.text
    assert replay.json()["id"] == response.json()["id"] and counts(work) == before
    resources.disable_issuer(work.setup.engine, work.test_issuer.key)
    recovered = post(work.quality, value)
    assert not fired and recovered.status_code == 200, recovered.text
    assert recovered.json()["id"] == response.json()["id"] and counts(work) == before
