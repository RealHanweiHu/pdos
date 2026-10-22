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
from pdos_next.domain.build_operational_facts.models import OperationalAsset, ResourceOccupancy
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
    prepared = launch_fixtures.launch_work.__wrapped__(work, request=None, monkeypatch=monkeypatch)
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
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as session:
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
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as session:
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
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as session:
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
        # The physical owner advances the resource watermark in the same UOW.
        session.get(OperationalAsset, resource.id).occupancy_epoch += 1
        session.flush()
        assert bundle(work, session).report.status == "BLOCKED"


def test_named_callback_revocation_never_defaults_to_accepted(launch_work):
    work = launch_work
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as session:
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
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as session:
        value = bundle(work, session)
        assert value.report.status == "UNKNOWN"
        assert any(c.code == "trusted_issuer_unavailable" for c in value.report.checks)
        with pytest.raises(DomainError) as exc:
            service.trusted_import(
                session, work.quality.ctx, work.setup.product, work.test_issuer, work.test_input
            )
        assert exc.value.reason == "TRUSTED_ISSUER_REQUIRED"


def test_unknown_external_scope_preserved_and_old_version_conflicts(launch_work):
    work = launch_work
    inputs = deepcopy(work.test_input.model_dump(mode="json")["resources"])
    for resource in inputs:
        resource["external_occupancies_complete"] = False
    current_id = advance_fact(work, resources=inputs)
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as session:
        with pytest.raises(DomainError) as exc:
            bundle(work, session)
        assert exc.value.reason == "RESOURCE_FACT_VERSION_CONFLICT"
        value = service.load_bundle(
            session, work.quality.ctx, work.setup.product, work.binding, current_id, 2
        )
        assert value.report.status == "UNKNOWN"
        assert any(c.code == "occupancy_scope_unknown" for c in value.report.checks)


def test_import_original_intent_does_not_rewind_current(launch_work):
    work = launch_work
    new_id = advance_fact(work, state="withdrawn", reason="Synthetic controlled withdrawal")
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as session:
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
        with tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.quality.human,
            category_id=work.setup.category,
        ) as session:
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
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as session:
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
    from pdos_next.domain.test_resources import retained
    from pdos_next.domain.verification_launch.models import VerificationRunVersion

    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as session:
        saved = session.get(VerificationRunVersion, UUID(receipt["subject_id"]))
        assert saved.operation == "test.run.start" and saved.run_id == work.binding.run_id
        assert saved.revision == receipt["subject_revision"]
        intent = saved.intent_digest
        assert saved.input_snapshot["execution_proof_contract"] == "s0-direct-v1"
        first = retained.inspect_retained_execution(
            session, work.quality.ctx, work.setup.product, saved
        )
        second = retained.inspect_retained_execution(
            session, work.quality.ctx, work.setup.product, saved
        )
        assert first["current"] and second["current"]
        assert first["reason_codes"] == second["reason_codes"] == []
        assert first["facts_revision"] == second["facts_revision"]
        assert first["original_start_intent"] == second["original_start_intent"] == intent
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
        assert exc.value.reason == "RUN_RESERVATION_MISSING"
        from sqlalchemy import event

        from pdos_next.contracts import Command
        from pdos_next.domain.test_resources.models import TestResourceCurrent as ResourceCurrent
        from pdos_next.request_proof import request_proof
        from pdos_next.service import command_scope

        # The read owner holds its dependency locks, but only a real command
        # scope acquires the Product gate required by writer raw-row reuse.
        held_product = command_scope(
            session, work.quality.ctx, Command.model_validate(work.start_command), lock=True
        )
        assert held_product.id == work.setup.product
        assert work.setup.product in request_proof(session).scope_locks
        assert not (session.new or session.dirty or session.deleted)
        models = (ResourceReservation, SampleRunUsage, ResourceOccupancy, Receipt)
        before = {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == work.setup.tenant)
            )
            for model in models
        }
        selected = {ResourceCurrent: [], ResourceFact: []}

        def observed(_connection, _cursor, statement, parameters, _context, _executemany):
            if not statement.lstrip().startswith("SELECT") or not isinstance(parameters, dict):
                return
            if (
                "FROM test_resource_current" in statement
                and parameters.get("run_id_1") == work.binding.run_id
                and parameters.get("tenant_id_1") == work.setup.tenant
            ):
                selected[ResourceCurrent].append(statement)
            if "FROM test_resource_facts" in statement and any(
                value == work.test_fact_id
                or (isinstance(value, (list, tuple)) and work.test_fact_id in value)
                for value in parameters.values()
            ):
                selected[ResourceFact].append(statement)

        # A prior unrelated owner may already have loaded this immutable ID.
        # Remove only its raw row so this observation proves the maker path.
        request_proof(session).read_rows.pop((ResourceFact, work.test_fact_id), None)
        event.listen(work.setup.engine, "before_cursor_execute", observed)
        try:
            retained_first = retained.inspect_retained_execution(
                session, work.quality.ctx, work.setup.product, saved
            )
            retained_second = retained.inspect_retained_execution(
                session, work.quality.ctx, work.setup.product, saved
            )
            assert retained_first["current"] is True, retained_first
            assert retained_second["current"] is True, retained_second
            assert retained_first["facts_revision"] == retained_second["facts_revision"]
            assert (ResourceFact, work.test_fact_id) not in request_proof(session).read_rows
            # The fixed direct contract never reopens the upstream Current
            # collection. Non-RR still rereads its exact immutable Fact at the
            # terminal boundary after source IO; only the initial raw row shares.
            assert selected[ResourceCurrent] == [], selected
            assert len(selected[ResourceFact]) == 3, selected
            assert all("LIMIT" in sql for sql in selected[ResourceFact]), selected
        finally:
            event.remove(work.setup.engine, "before_cursor_execute", observed)
        after = {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == work.setup.tenant)
            )
            for model in models
        }
        assert after == before


def test_rr_canonical_owned_sets_share_rows_and_reject_wrong_saved_scope_without_effects(
    launch_work, monkeypatch
):
    from sqlalchemy import event
    from sqlalchemy.orm.attributes import set_committed_value

    from pdos_next.domain.test_resources import retained
    from pdos_next.domain.test_resources.models import TestResourceCurrent as ResourceCurrent
    from pdos_next.domain.verification_launch import service as launch
    from pdos_next.domain.verification_launch.models import VerificationRunVersion as RunVersion
    from pdos_next.request_proof import request_proof

    work = launch_work
    receipt, _ = started(work, monkeypatch)
    models = (SampleRunUsage, ResourceReservation, ResourceOccupancy, Receipt, RunVersion)
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
        read_snapshot=True,
    ) as session:
        assert session.connection().get_isolation_level() == "REPEATABLE READ"
        before = {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == work.setup.tenant)
            )
            for model in models
        }
        selected = {ResourceCurrent: [], ResourceOccupancy: [], SampleRunUsage: []}

        def observed(connection, cursor, statement, parameters, context, executemany):
            if not statement.lstrip().startswith("SELECT") or not isinstance(parameters, dict):
                return
            for model in selected:
                run_key = "owner_execution_id_1" if model is ResourceOccupancy else "run_id_1"
                if (
                    f"FROM {model.__tablename__}" in statement
                    and parameters.get(run_key) == work.binding.run_id
                    and parameters.get("tenant_id_1") == work.setup.tenant
                ):
                    selected[model].append((statement, parameters))

        event.listen(work.setup.engine, "before_cursor_execute", observed)
        try:
            saved = session.get(RunVersion, UUID(receipt["subject_id"]))
            first = retained.inspect_retained_execution(
                session, work.quality.ctx, work.setup.product, saved
            )
            assert first["current"] is True, first
            assert first["reason_codes"] == []
            effects = launch._saved_effects(session, work.quality.ctx, work.setup.product, saved)
            second = retained.inspect_retained_execution(
                session, work.quality.ctx, work.setup.product, saved
            )
            assert second["current"] is True, second
            assert second["facts_revision"] == first["facts_revision"]
            assert second["occupancy"] == first["occupancy"] == effects["occupancy"]
            assert second["sample_usage"] == first["sample_usage"] == effects["sample_usage"]
            assert selected[ResourceCurrent] == [], selected
            assert all(
                len(selected[model]) == 1 for model in (ResourceOccupancy, SampleRunUsage)
            ), selected
            occupancy_sql = selected[ResourceOccupancy][0][0].split("WHERE", 1)[1]
            usage_sql = selected[SampleRunUsage][0][0].split("WHERE", 1)[1]
            # Query the complete owner collection; project/build mismatches
            # must be visible to the owner guards instead of filtered away.
            assert "operational_resource_occupancies.product_id" not in occupancy_sql
            assert "operational_resource_occupancies.project_id" not in occupancy_sql
            assert "operational_resource_occupancies.build_id" not in occupancy_sql
            assert "sample_run_usages.project_id" not in usage_sql
            assert "sample_run_usages.build_id" not in usage_sql
            assert [item["resource_id"] for item in effects["occupancy"]] == sorted(
                item["resource_id"] for item in effects["occupancy"]
            )
            assert [item["sample_id"] for item in effects["sample_usage"]] == sorted(
                item["sample_id"] for item in effects["sample_usage"]
            )
        finally:
            event.remove(work.setup.engine, "before_cursor_execute", observed)

        owned = service._own_occupancies(
            session, work.quality.ctx, work.setup.product, work.binding.run_id
        )
        usages = service._own_usages(
            session, work.quality.ctx, work.setup.product, work.binding.run_id
        )
        assert owned and usages
        epoch = request_proof(session).mutation_epoch
        for row in (owned[0], usages[0]):
            original_project = row.project_id
            # Change only the RLS-loaded Python projection, without bypassing
            # any database scope/FK rule or writing an invalid business row.
            # The actual clean RR owner must still reject its changed full scope.
            set_committed_value(row, "project_id", uuid4())
            try:
                assert not (session.new or session.dirty or session.deleted)
                with pytest.raises(DomainError) as caught:
                    launch._saved_effects(session, work.quality.ctx, work.setup.product, saved)
                assert caught.value.reason == "RUN_RESERVATION_MISSING"
            finally:
                set_committed_value(row, "project_id", original_project)
        assert request_proof(session).mutation_epoch == epoch
        after = {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == work.setup.tenant)
            )
            for model in models
        }
        assert after == before


def test_destructive_actual_start_consumes_once_and_new_use_remains_blocked(
    destructive_launch_work, monkeypatch
):
    work = destructive_launch_work
    original = deepcopy(work.accepted_request["request_snapshot"])
    assert all(pair.destructive for pair in work.binding.pairs)
    assert next(item for item in original["items"] if item["id"] == "dimension")["destructive"]

    receipt, prepared = started(work, monkeypatch)
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as session:
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
    assert same.json()["id"] == receipt["id"]
    alias = deepcopy(prepared)
    alias.update(command_id=str(uuid4()), idempotency_key=str(uuid4()))
    replay = post(work.quality, alias)
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == receipt["id"]

    from pdos_next.domain.verification_front.models import FormalVerificationRequest

    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as session:
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
