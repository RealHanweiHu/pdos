"""Host-run PostgreSQL checks; this module is not executed by the resource subagent."""

# ruff: noqa: F811 - imports register transitive pytest fixtures
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_project_first_plan import post
from verification_handoff import fixtures as handoff_fixtures
from verification_launch import fixtures as launch_fixtures
from verification_launch.fixtures import (  # noqa: F401
    accepted_work,
    advance_clock,
    command,
    known_configuration,
    launch_work,
    operational_work,
    promised,
    ready_work,
    started,
)

from pdos_next.database import tenant_session
from pdos_next.domain.build_operational_facts.models import ResourceOccupancy
from pdos_next.domain.test_resources import service
from pdos_next.domain.test_resources.models import (
    SampleRunUsage,
    SampleUsageSentinel,
)
from pdos_next.domain.test_resources.models import (
    TestResourceFact as ResourceFact,
)
from pdos_next.domain.test_resources.models import (
    TestResourceReservation as ResourceReservation,
)
from pdos_next.domain.test_resources.schemas import TestResourceFactInput as FactInput
from pdos_next.errors import DomainError
from pdos_next.models import Receipt
from pdos_next.schemas.verification.contracts import EventTime
from pdos_next.test_resource_import import import_test_resource_fact


@pytest.fixture
def destructive_launch_work(ready_work, monkeypatch):
    """Build the destructive declaration before any immutable dossier/method exists."""
    ordinary_payload = handoff_fixtures.prep_payload

    def destructive_payload(*args, **kwargs):
        payload = ordinary_payload(*args, **kwargs)
        payload["items"][0]["destructive"] = True
        return payload

    monkeypatch.setattr(handoff_fixtures, "prep_payload", destructive_payload)
    acceptance = launch_fixtures.accepted_work.__wrapped__(ready_work, monkeypatch)
    work = next(acceptance)
    prepared = launch_fixtures.launch_work.__wrapped__(work)
    try:
        yield next(prepared)
    finally:
        prepared.close()
        acceptance.close()


def bundle(work, session, *, own_intent=None):
    return service.load_bundle(
        session,
        work.quality.ctx,
        work.setup.product,
        work.binding,
        work.test_fact_id,
        1,
        own_intent=own_intent,
    )


def advance_fact(work, **changes):
    data = work.test_input.model_dump(mode="json")
    data.update(expected_previous_id=str(work.test_fact_id), expected_previous_revision=1)
    data.update(changes)
    with tenant_session(work.setup.engine, work.setup.tenant) as session:
        receipt = import_test_resource_fact(
            session,
            work.quality.ctx,
            work.setup.product,
            work.test_issuer,
            FactInput.model_validate(data),
            request_key=str(uuid4()),
            command_id=uuid4(),
        )
    return UUID(receipt["subject_id"])


def test_assess_has_no_usage_or_reservation_side_effects(launch_work):
    work = launch_work
    with tenant_session(work.setup.engine, work.setup.tenant) as session:
        value = bundle(work, session)
        assert value.report.status == "READY"
        assert value.fact_ref.id == work.test_fact_id and value.nature == "synthetic"
        for model in (SampleRunUsage, SampleUsageSentinel, ResourceReservation):
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.tenant_id == work.setup.tenant)
                )
                == 0
            )
        assert all(v.state == "available" for v in value.sample_usage)


def test_global_build_occupancy_blocks_test_capacity(launch_work):
    work = launch_work
    resource = next(v.resource for v in work.test_input.resources if v.resource.kind == "equipment")
    with tenant_session(work.setup.engine, work.setup.tenant) as session:
        bundle(work, session)  # Acquires the same Product/global asset gates.
        start_id = UUID(work.start_receipt["subject_id"])
        session.add(
            ResourceOccupancy(
                tenant_id=work.setup.tenant,
                product_id=work.setup.product,
                project_id=work.binding.project_id,
                build_id=work.binding.build_id,
                owner_kind="build",
                owner_execution_id=start_id,
                build_start_id=start_id,
                test_run_id=None,
                asset_id=resource.id,
                resource_id=resource.id,
                resource_revision=resource.revision,
                window_start=work.binding.window.start,
                window_finish=work.binding.window.finish,
                units="1",
                intent_digest="a" * 64,
                reservation={"synthetic_capacity_conflict": True},
            )
        )
        session.flush()
        assert bundle(work, session).report.status == "BLOCKED"


def test_named_callback_revocation_never_defaults_to_accepted(launch_work):
    work = launch_work
    with tenant_session(work.setup.engine, work.setup.tenant) as session:
        original = bundle(work, session)
        work.test_decisions_current = False
        changed = bundle(work, session)
        assert changed.report.status == "UNKNOWN"
        assert changed.facts_revision != original.facts_revision
        assert any(
            c.code in {"acceptance_missing", "calibration_missing", "qualification_missing"}
            and c.status == "UNKNOWN"
            for c in changed.report.checks
        )


def test_issuer_disable_restore_does_not_revive_old_fact(launch_work):
    work = launch_work
    service.disable_issuer(work.setup.engine, work.test_issuer.key)
    with tenant_session(work.setup.engine, work.setup.tenant) as session:
        value = bundle(work, session)
        assert value.report.status == "UNKNOWN"
        assert any(c.code == "trusted_issuer_unavailable" for c in value.report.checks)
        with pytest.raises(DomainError) as exc:
            service.trusted_import(
                session, work.quality.ctx, work.setup.product, work.test_issuer, work.test_input
            )
        assert exc.value.code == "TRUSTED_ISSUER_REQUIRED"


def test_unknown_external_scope_preserved_and_old_version_conflicts(launch_work):
    work = launch_work
    inputs = deepcopy(work.test_input.model_dump(mode="json")["resources"])
    for resource in inputs:
        resource["external_occupancies_complete"] = False
    current_id = advance_fact(work, resources=inputs)
    with tenant_session(work.setup.engine, work.setup.tenant) as session:
        with pytest.raises(DomainError) as exc:
            bundle(work, session)
        assert exc.value.code == "RESOURCE_FACT_VERSION_CONFLICT"
        value = service.load_bundle(
            session, work.quality.ctx, work.setup.product, work.binding, current_id, 2
        )
        assert value.report.status == "UNKNOWN"
        assert any(c.code == "occupancy_scope_unknown" for c in value.report.checks)


def test_import_original_intent_does_not_rewind_current(launch_work):
    work = launch_work
    new_id = advance_fact(work, state="withdrawn", reason="Synthetic controlled withdrawal")
    with tenant_session(work.setup.engine, work.setup.tenant) as session:
        prior = service.trusted_import(
            session, work.quality.ctx, work.setup.product, work.test_issuer, work.test_input
        )
        assert prior["id"] == str(work.test_fact_id)
        _, current = service._current(
            session, work.quality.ctx, work.setup.product, work.binding.run_id
        )
        assert current.id == new_id and current.state == "withdrawn"
        assert (
            session.scalar(
                select(func.count())
                .select_from(ResourceFact)
                .where(ResourceFact.tenant_id == work.setup.tenant)
            )
            == 2
        )


def test_start_effects_rollback_with_enclosing_uow(launch_work, monkeypatch):
    work = launch_work
    promised(work)
    advance_clock(work, monkeypatch)
    cmd = command(work, "test.run.start")
    event = EventTime.model_validate(cmd["payload"]["at"])
    before_receipts = None
    with pytest.raises(RuntimeError, match="abort after staged effects"):
        with tenant_session(work.setup.engine, work.setup.tenant) as session:
            before_receipts = session.scalar(
                select(func.count())
                .select_from(Receipt)
                .where(Receipt.tenant_id == work.setup.tenant)
            )
            bound = bundle(work, session)
            result = service.stage_start(
                session,
                work.quality.ctx,
                work.setup.product,
                work.binding,
                work.test_fact_id,
                1,
                expected_facts_revision=bound.facts_revision,
                intent_digest="a" * 64,
                accepted_confirmation=True,
                verified_actual_start=event,
            )
            assert result.disposition == "staged_in_caller_uow"
            assert result.sample_usage_ids and result.occupancy_ids
            raise RuntimeError("abort after staged effects")
    with tenant_session(work.setup.engine, work.setup.tenant) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Receipt)
                .where(Receipt.tenant_id == work.setup.tenant)
            )
            == before_receipts
        )
        for model in (SampleRunUsage, SampleUsageSentinel, ResourceReservation):
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.tenant_id == work.setup.tenant)
                )
                == 0
            )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ResourceOccupancy)
                .where(
                    ResourceOccupancy.tenant_id == work.setup.tenant,
                    ResourceOccupancy.owner_kind == "test_run",
                )
            )
            == 0
        )


def test_own_run_proof_rechecked_without_new_effects(launch_work, monkeypatch):
    work = launch_work
    receipt, _ = started(work, monkeypatch)
    from pdos_next.domain.verification_launch.models import VerificationLaunchFact

    with tenant_session(work.setup.engine, work.setup.tenant) as session:
        fact = session.get(VerificationLaunchFact, UUID(receipt["subject_id"]))
        # Common RunStart receipts refer to Run versions, not the internal resource fact.
        if fact is None:
            fact = session.scalar(
                select(VerificationLaunchFact).where(
                    VerificationLaunchFact.tenant_id == work.setup.tenant,
                    VerificationLaunchFact.run_id == work.binding.run_id,
                    VerificationLaunchFact.operation == "test.run.start",
                )
            )
        intent = fact.intent_digest
        first = service.recheck_running(
            session,
            work.quality.ctx,
            work.setup.product,
            work.binding,
            work.test_fact_id,
            1,
            intent_digest=intent,
        )
        second = service.recheck_running(
            session,
            work.quality.ctx,
            work.setup.product,
            work.binding,
            work.test_fact_id,
            1,
            intent_digest=intent,
        )
        assert first.facts_revision == second.facts_revision
        assert session.scalar(
            select(func.count())
            .select_from(SampleRunUsage)
            .where(SampleRunUsage.tenant_id == work.setup.tenant)
        ) == len({p.sample.id for p in work.binding.pairs})
        with pytest.raises(DomainError) as exc:
            service.recheck_running(
                session,
                work.quality.ctx,
                work.setup.product,
                work.binding,
                work.test_fact_id,
                1,
                intent_digest="f" * 64,
            )
        assert exc.value.code == "RUN_INTENT_CONFLICT"


def test_destructive_actual_start_consumes_once_and_new_use_remains_blocked(
    destructive_launch_work, monkeypatch
):
    work = destructive_launch_work
    original = deepcopy(work.accepted_request["request_snapshot"])
    assert all(pair.destructive for pair in work.binding.pairs)
    assert next(item for item in original["items"] if item["id"] == "dimension")["destructive"]

    receipt, prepared = started(work, monkeypatch)
    with tenant_session(work.setup.engine, work.setup.tenant) as session:
        usages = list(
            session.scalars(
                select(SampleRunUsage).where(
                    SampleRunUsage.tenant_id == work.setup.tenant,
                    SampleRunUsage.run_id == work.binding.run_id,
                )
            )
        )
        assert len(usages) == 1
        usage = usages[0]
        usage_id = usage.id
        assert usage.destructive is True and usage.state == "consumed"
        assert usage.sample_id == work.binding.pairs[0].sample.id
        assert EventTime.model_validate(
            usage.source_basis["actual_start"]
        ) == EventTime.model_validate(work.start_command["payload"]["at"])
        before = {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == work.setup.tenant)
            )
            for model in (SampleRunUsage, ResourceReservation, ResourceOccupancy, Receipt)
        }
        # No own-intent exclusion: the persisted consumption must block a fresh
        # availability probe even though original physical readiness stays ready.
        availability = bundle(work, session)
        assert availability.report.status == "BLOCKED"
        assert any(c.code == "sample_usage_conflict" for c in availability.report.checks)
        assert availability.sample_usage[0].state == "consumed"

    same = post(work.quality, prepared)
    assert same.status_code == 200, same.text
    assert same.json()["receipt_id"] == receipt["receipt_id"]
    alias = deepcopy(prepared)
    alias.update(command_id=str(uuid4()), idempotency_key=str(uuid4()))
    replay = post(work.quality, alias)
    assert replay.status_code == 200, replay.text
    assert replay.json()["receipt_id"] == receipt["receipt_id"]

    from pdos_next.domain.verification_front.models import FormalVerificationRequest

    with tenant_session(work.setup.engine, work.setup.tenant) as session:
        after = {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == work.setup.tenant)
            )
            for model in (SampleRunUsage, ResourceReservation, ResourceOccupancy, Receipt)
        }
        assert after == before
        history = session.get(FormalVerificationRequest, UUID(work.accepted_request["id"]))
        assert history.request_snapshot == original
        still_consumed = session.scalar(
            select(SampleRunUsage).where(
                SampleRunUsage.tenant_id == work.setup.tenant,
                SampleRunUsage.run_id == work.binding.run_id,
            )
        )
        assert still_consumed.id == usage_id and still_consumed.state == "consumed"
        # The same retained ledger also blocks another Run at a disjoint later
        # interval; destructive use is not released by the clock passing.
        future = work.binding.model_copy(
            update={
                "run_id": uuid4(),
                "window": work.binding.window.model_copy(
                    update={
                        "start": work.binding.window.finish,
                        "finish": work.binding.window.finish
                        + (work.binding.window.finish - work.binding.window.start),
                    }
                ),
            }
        )
        views, checks = service.sample_usage_checks(future, [still_consumed])
        assert views[0].state == "consumed" and checks[0].status == "BLOCKED"
