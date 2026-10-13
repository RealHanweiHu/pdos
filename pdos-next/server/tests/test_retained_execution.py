"""Retained Start proof checks; only root executes these on its guarded PG target.

Every Start below is a real API flow with its real clock and one shared resource/
sample transaction. Later read-clock advancement never writes a backdated event
or renews execution permission. All authority/source material is synthetic.
"""

# ruff: noqa: F811 - imported fixtures register their transitive dependencies

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from build_start.test_transactions import import_authority
from sqlalchemy import event, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, make_transient_to_detached
from test_build_execution import actual_command, actual_comparison, alternate_configurations
from test_project_first_plan import accepted
from verification_handoff import fixtures as handoff_fixtures
from verification_launch import fixtures as launch_fixtures
from verification_launch.fixtures import (  # noqa: F401 - required pytest fixture registrations
    known_configuration,
    operational_work,
    ready_work,
)

from pdos_next.database import tenant_session
from pdos_next.domain.build_operational_facts.models import (
    MaterialHold,
    OperationalAsset,
    ResourceOccupancy,
)
from pdos_next.domain.build_start import service as builds
from pdos_next.domain.build_start.models import BuildStart
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.professional_authority.models import ProfessionalCurrent
from pdos_next.domain.test_resources import retained
from pdos_next.domain.test_resources import service as resources
from pdos_next.domain.test_resources.models import (
    SampleRunUsage,
    SampleUsageSentinel,
)
from pdos_next.domain.test_resources.models import (
    TestResourceCurrent as ResourceCurrent,
)
from pdos_next.domain.test_resources.models import (
    TestResourceFact as ResourceFact,
)
from pdos_next.domain.test_resources.models import (
    TestResourceReservation as ResourceReservation,
)
from pdos_next.domain.verification_launch import service as launch
from pdos_next.domain.verification_launch.models import (
    VerificationRunCurrent,
    VerificationRunVersion,
)
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Audit, Outbox, Product, Receipt, RequestKey, now
from pdos_next.request_proof import request_proof
from pdos_next.schemas.verification.contracts import TestRun as RunDTO
from pdos_next.service import Context, digest

RESULT_OPERATIONS = (
    "test.results.import",
    "test.result.compute",
    "test.run.review",
    "test.disposition.decide",
)
EFFECT_MODELS = (
    MaterialHold,
    ResourceOccupancy,
    ResourceReservation,
    SampleRunUsage,
    SampleUsageSentinel,
    OperationalAsset,
    BuildStart,
    VerificationRunVersion,
    VerificationRunCurrent,
    Receipt,
    Audit,
    Outbox,
    RequestKey,
)


def _result_authority(work, *, suffix):
    """Separate exact result duties fit the closed per-fact operation limit."""
    return {
        kind: import_authority(
            work,
            "quality",
            kind,
            subject_id=str(work.quality.human),
            operations=list(RESULT_OPERATIONS),
            external_id=f"synthetic-retained-results-{suffix}-{kind}",
        )
        for kind in ("duty", "qualification")
    }


@pytest.fixture
def retained_launch_work(ready_work, monkeypatch):
    # Add result authority before *all* fixed professional snapshots. Do not
    # modify the shared launch fixture or append new roles to an old credential.
    ordinary_start = handoff_fixtures.start

    def start_with_results(work):
        work.retained_result_authority = _result_authority(work, suffix="before-start")
        return ordinary_start(work)

    monkeypatch.setattr(handoff_fixtures, "start", start_with_results)
    acceptance = launch_fixtures.accepted_work.__wrapped__(ready_work, monkeypatch)
    work = next(acceptance)
    preparation = launch_fixtures.launch_work.__wrapped__(
        work, request=None, monkeypatch=monkeypatch
    )
    try:
        yield next(preparation)
    finally:
        preparation.close()
        acceptance.close()


@pytest.fixture
def retained_started_work(retained_launch_work, monkeypatch):
    work = retained_launch_work
    work.test_start_receipt, _ = launch_fixtures.started(work, monkeypatch)
    return work


def _scoped(work, ctx=None):
    caller = ctx or work.quality.ctx
    return tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=caller.actor_id,
        requester_id=caller.requester_id,
        category_id=caller.category_id,
    )


def _run_row(session, work):
    row = session.scalar(
        select(VerificationRunVersion).where(
            VerificationRunVersion.tenant_id == work.setup.tenant,
            VerificationRunVersion.product_id == work.setup.product,
            VerificationRunVersion.run_id == work.binding.run_id,
            VerificationRunVersion.revision == 2,
        )
    )
    assert row is not None and row.operation == "test.run.start"
    return row


def _effects(session, work):
    """Compare complete retained rows, including both monotonic effect epochs."""
    result = {}
    for model in EFFECT_MODELS:
        rows = session.execute(
            select(model.__table__)
            .where(model.__table__.c.tenant_id == work.setup.tenant)
            .order_by(model.__table__.c.id)
        ).mappings()
        result[model.__tablename__] = [digest(dict(row)) for row in rows]
    return result


def _proof(session, work, row=None, *, at=None):
    before = _effects(session, work)
    value = retained.inspect_retained_execution(
        session,
        work.quality.ctx,
        work.setup.product,
        row or _run_row(session, work),
        at=at,
    )
    assert _effects(session, work) == before, "A retained read changed effects or their epochs"
    return value


def _current(value):
    assert value["current"] is True, value
    assert value["reason_codes"] == []
    assert value["nature"] == "retained_execution_evidence_not_current_execution_permission"
    assert len(value["occupancy"]) == 2 and len(value["sample_usage"]) == 1
    assert value["sample_usage"][0]["state"] == "reserved"
    assert value["sample_usage"][0]["destructive"] is False


def test_retained_rr_evidence_does_not_survive_source_withdrawal_between_requests(
    retained_started_work,
):
    work = retained_started_work
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.quality.ctx.category_id,
        read_snapshot=True,
    ) as session:
        first = _proof(session, work)
        second = _proof(session, work)
        _current(first)
        _current(second)
        for key in (
            "source_basis",
            "facts_revision",
            "original_start_intent",
            "plan_binding",
            "reservation",
            "occupancy",
            "sample_usage",
        ):
            assert first[key] == second[key]

    source_id = UUID(work.start_command["payload"]["sources"][0]["artifact_id"])
    with _scoped(work) as session:
        session.execute(
            update(Artifact)
            .where(Artifact.tenant_id == work.setup.tenant, Artifact.id == source_id)
            .values(status="withdrawn")
        )
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.quality.ctx.category_id,
        read_snapshot=True,
    ) as session:
        fresh = _proof(session, work)
        assert fresh["current"] is False
        assert fresh["reason_codes"] == ["SOURCE_UNAVAILABLE"], fresh


def test_retained_saved_start_with_simulated_late_read_clock_and_no_new_permission(
    retained_started_work, monkeypatch
):
    work = retained_started_work
    with _scoped(work) as session:
        row = _run_row(session, work)
        original = _proof(session, work, row)
        _current(original)
        original_effects = _effects(session, work)
        saved_at = row.created_at
        assert work.binding.window.start <= saved_at < work.binding.window.finish

    # A new independent results-only credential has no applicability to the
    # original Start. Its addition must not erase that already committed event.
    _result_authority(work, suffix=f"later-{uuid4()}")
    with _scoped(work) as session:
        current = _proof(session, work)
        _current(current)
        assert current["facts_revision"] == original["facts_revision"]
        assert current["original_start_intent"] == original["original_start_intent"]

    for late in (
        work.binding.window.finish + timedelta(seconds=1),
        work.at + timedelta(minutes=41),
    ):
        # Advance only this read evaluator's server clock, after the real Start.
        # No API event, immutable timestamp or qualified fact is synthesized.
        with monkeypatch.context() as clock:
            clock.setattr(resources, "now", lambda late=late: late)
            clock.setattr(retained, "now", lambda late=late: late)
            with _scoped(work) as session:
                row = _run_row(session, work)
                proof = _proof(session, work, row, at=late)
                _current(proof)
                assert proof["execution_window_elapsed"] is True
                assert proof["saved_start_at"] == saved_at.isoformat()
                assert proof["actual_start"] == original["actual_start"]
                assert proof["facts_revision"] == original["facts_revision"]
                assert proof["occupancy"] == original["occupancy"]
                assert proof["sample_usage"] == original["sample_usage"]
                if late == work.at + timedelta(minutes=41):
                    current_authority = professional.assess(
                        session,
                        work.quality.ctx,
                        work.setup.product,
                        work.binding.project_id,
                        "test.run.start",
                        work.binding.purpose,
                        late,
                    )
                    assert current_authority["authorized"] is False
                    assert current_authority["qualified"] is False
                    assert "PROFESSIONAL_FACT_EXPIRED" in current_authority["reason_codes"]

            with _scoped(work, work.setup.ctx) as session:
                permission = builds.execution_projection(
                    session,
                    work.setup.ctx,
                    work.setup.product,
                    UUID(work.build_id),
                    retained_at=saved_at,
                )
                assert permission["evaluation_nature"] == "retained_execution_at_saved_start"
                assert not any(
                    permission[action]
                    for action in (
                        "readiness_compute",
                        "engineering_approve",
                        "engineering_revoke",
                        "manufacturing_approve",
                        "manufacturing_revoke",
                        "start",
                    )
                )

    with _scoped(work) as session:
        final_effects = _effects(session, work)
        # The two deliberate credential imports added their own receipts only.
        for table in original_effects:
            if table not in {
                Receipt.__tablename__,
                Audit.__tablename__,
                Outbox.__tablename__,
                RequestKey.__tablename__,
            }:
                assert final_effects[table] == original_effects[table]


def test_retained_proof_rejects_changed_fixed_run_basis_even_with_valid_snapshot_hash(
    retained_started_work,
):
    work = retained_started_work
    with _scoped(work) as session:
        row = _run_row(session, work)
        _current(_proof(session, work, row))
        for change in (
            "actual_configuration",
            "cavity",
            "planned_engineering",
            "method",
            "criterion",
            "sample_item_coverage",
        ):
            # A detached candidate represents an invalid subsequent result row;
            # never UPDATE the immutable original Run or its existing samples.
            candidate = SimpleNamespace(
                **{
                    c.name: deepcopy(getattr(row, c.name))
                    for c in row.__table__.columns
                    if c.name != "audience_dependencies"
                }
            )
            raw = candidate.run_snapshot
            if change == "actual_configuration":
                raw["samples"][0]["actual_configuration"]["id"] = str(uuid4())
            elif change == "cavity":
                raw["samples"][0]["cavity"] = "Synthetic changed cavity"
            elif change == "planned_engineering":
                raw["build"]["engineering_configuration"]["revision"] += 1
            elif change == "method":
                raw["items"][0]["method"]["revision"] += 1
            elif change == "criterion":
                raw["items"][0]["criterion"]["upper"] = "11.5"
            else:
                raw["coverage"][0]["item_id"] = "Synthetic different item"
            candidate.run_snapshot = RunDTO.model_validate(raw).model_dump(mode="json")
            candidate.snapshot_sha256 = digest(candidate.run_snapshot)
            launch._snapshot(candidate)  # Closed DTO/hash checks alone still accept this shape.
            proof = _proof(session, work, candidate)
            assert proof["current"] is False, change
            assert proof["reason_codes"] == ["RUN_START_PROOF_INVALID"], (change, proof)


def test_retained_proof_rechecks_source_withdrawal_without_reinterpreting_asset_sample_epochs(
    retained_started_work,
):
    work = retained_started_work
    with _scoped(work) as session:
        original = _effects(session, work)
        baseline = _proof(session, work)
        _current(baseline)
        equipment = next(
            r.resource for r in work.test_input.resources if r.resource.kind == "equipment"
        )
        for model, condition, values in (
            (
                OperationalAsset,
                OperationalAsset.id == equipment.id,
                {"occupancy_epoch": OperationalAsset.occupancy_epoch + 1},
            ),
            (
                SampleUsageSentinel,
                SampleUsageSentinel.sample_id == work.binding.pairs[0].sample.id,
                {"epoch": SampleUsageSentinel.epoch + 1},
            ),
        ):
            savepoint = session.begin_nested()
            try:
                session.execute(
                    update(model)
                    .where(
                        model.tenant_id == work.setup.tenant,
                        condition,
                    )
                    .values(**values)
                )
                proof = _proof(session, work)
                # Later capacity/usage watermarks cannot rewrite the exact
                # already committed Start, reservation and usage identities.
                _current(proof)
                for key in (
                    "facts_revision", "original_start_intent", "reservation",
                    "occupancy", "sample_usage"
                ):
                    assert proof[key] == baseline[key], (model.__tablename__, key)
            finally:
                savepoint.rollback()
                session.expire_all()
            assert _effects(session, work) == original
            _current(_proof(session, work))

        # Withdraw an original Start event source in this transaction. The new
        # terminal-source DB guard must reject ABA revival of the same identity.
        source_id = UUID(work.start_command["payload"]["sources"][0]["artifact_id"])
        session.execute(
            update(Artifact)
            .where(
                Artifact.tenant_id == work.setup.tenant,
                Artifact.id == source_id,
            )
            .values(status="withdrawn")
        )
        withdrawn = _proof(session, work)
        assert withdrawn["current"] is False
        assert withdrawn["reason_codes"] == ["SOURCE_UNAVAILABLE"], withdrawn
        with pytest.raises(DBAPIError) as forbidden_restore, session.begin_nested():
            session.execute(
                update(Artifact).where(Artifact.id == source_id).values(status="active")
            )
        assert "Withdrawn source version is terminal" in str(forbidden_restore.value.orig)
        session.expire_all()
        assert session.get(Artifact, source_id).status == "withdrawn"
        assert _proof(session, work)["current"] is False
        assert _effects(session, work) == original


def test_retained_proof_preserves_fixed_issuer_evidence_after_registry_aba(
    retained_started_work,
):
    work = retained_started_work
    with _scoped(work) as session:
        before = _proof(session, work)
        _current(before)
    issuer = work.test_issuer
    resources.disable_issuer(work.setup.engine, issuer.key)
    with _scoped(work) as session:
        missing = _proof(session, work)
        _current(missing)
        for key in (
            "facts_revision", "original_start_intent", "reservation",
                    "occupancy", "sample_usage"
        ):
            assert missing[key] == before[key]
    restored = resources.configure_local_synthetic(
        work.setup.engine,
        tenant_id=issuer.tenant_id,
        product_id=issuer.product_id,
        project_id=issuer.project_id,
        key=issuer.key,
        version=issuer.version,
        enabled=True,
        test_marker_verified=True,
        verify_named_decision=issuer.verify_named_decision,
    )
    assert restored.epoch > issuer.epoch and restored is not issuer
    with _scoped(work) as session:
        proof = _proof(session, work)
        # Signed issuer material remains exact; current registry changes can
        # restrict a new Start, never reinterpret the already saved event.
        _current(proof)
        for key in (
            "facts_revision", "original_start_intent", "reservation",
                    "occupancy", "sample_usage"
        ):
            assert proof[key] == before[key]


def test_retained_proof_keeps_history_without_current_manufacturing_qualification(
    retained_started_work,
):
    work = retained_started_work
    with _scoped(work) as session:
        _current(_proof(session, work))
        pointer = session.scalar(
            select(ProfessionalCurrent).where(
                ProfessionalCurrent.tenant_id == work.setup.tenant,
                ProfessionalCurrent.subject_id == work.setup.human,
                ProfessionalCurrent.kind == "qualification",
                ProfessionalCurrent.external_id == "synthetic-manufacturing-qualification",
            )
        )
        original_epoch = pointer.epoch
    old = work.credentials[("manufacturing", "qualification")]
    revoked = import_authority(
        work,
        "manufacturing",
        "qualification",
        state="revoked",
        previous_id=old["subject_id"],
        expected_previous_revision=old["subject_revision"],
    )
    with _scoped(work) as session:
        _current(_proof(session, work))
    with _scoped(work, ctx=work.setup.ctx) as session:
        current = professional.assess(
            session,
            work.setup.ctx,
            work.setup.product,
            UUID(work.config["project"]),
            "build.start",
            work.scope.purpose,
            now(),
        )
        assert current["qualified"] is False, current
    import_authority(
        work,
        "manufacturing",
        "qualification",
        state="active",
        previous_id=revoked["subject_id"],
        expected_previous_revision=revoked["subject_revision"],
    )
    with _scoped(work) as session:
        pointer = session.scalar(
            select(ProfessionalCurrent).where(
                ProfessionalCurrent.tenant_id == work.setup.tenant,
                ProfessionalCurrent.subject_id == work.setup.human,
                ProfessionalCurrent.kind == "qualification",
                ProfessionalCurrent.external_id == "synthetic-manufacturing-qualification",
            )
        )
        assert pointer.epoch == original_epoch + 2
        _current(_proof(session, work))
    with _scoped(work, ctx=work.setup.ctx) as session:
        current = professional.assess(
            session,
            work.setup.ctx,
            work.setup.product,
            UUID(work.config["project"]),
            "build.start",
            work.scope.purpose,
            now(),
        )
        assert current["qualified"] is True, current


def test_retained_proof_preserves_fixed_start_after_new_configuration_observation(
    retained_started_work,
):
    work = retained_started_work
    with _scoped(work) as session:
        before = _proof(session, work)
        _current(before)
    # The shared launch fixture retains fixed IDs, not its original command
    # payloads. Reconstruct only new draft inputs from the exact saved versions;
    # never rewrite the planned configurations or substitute a current version.
    response = work.setup.client.get(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/configurations",
        headers=work.setup.headers,
    )
    assert response.status_code == 200, response.text
    configurations = response.json()
    planned_engineering = next(
        row
        for row in configurations["engineering"]
        if row["id"] == work.config["engineering"]["subject_id"]
    )
    planned_process = next(
        row
        for row in configurations["processes"]
        if row["id"] == work.config["process"]["subject_id"]
    )
    assert planned_process["engineering_configuration_id"] == planned_engineering["id"]
    fixed = {
        **work.config,
        "build": {"subject_id": work.build_id},
        "engineering_payload": {
            "name": planned_engineering["name"],
            "visibility": planned_engineering["visibility"],
            "definition_id": planned_engineering["definition_id"],
            "expected_definition_revision": planned_engineering["definition_revision"],
            "bom_id": planned_engineering["bom_id"],
            "expected_bom_revision": planned_engineering["bom_revision"],
            **deepcopy(planned_engineering["design_versions"]),
            "sources": deepcopy(planned_engineering["sources"]),
            "reason": "Create a distinct fixed observed engineering configuration",
        },
        "process_payload": {
            "name": planned_process["name"],
            "visibility": planned_process["visibility"],
            "engineering_configuration_id": planned_engineering["id"],
            "expected_engineering_revision": planned_engineering["revision"],
            "site": planned_process["site"],
            "line": planned_process["line"],
            "operations": deepcopy(planned_process["operations"]),
            "sources": deepcopy(planned_process["sources"]),
            "reason": "Create a distinct fixed observed manufacturing configuration",
        },
    }
    engineering, manufacturing = alternate_configurations(work.setup, fixed)
    comparison = actual_comparison(work.setup, fixed, engineering, manufacturing)
    assert comparison["differences"]
    _, _ = accepted(
        work.setup,
        actual_command(
            work.setup,
            fixed,
            actual_engineering_configuration_id=engineering["subject_id"],
            actual_manufacturing_configuration_id=manufacturing["subject_id"],
            differences=[
                {
                    "path": difference["path"],
                    "reason": "Synthetic observation independent of the fixed Start",
                    "sources": [
                        {
                            "artifact_id": fixed["source"],
                            "expected_revision": 1,
                            "line": 1,
                            "quote": "Synthetic requirement is unverified",
                        }
                    ],
                }
                for difference in comparison["differences"]
            ],
        ),
    )
    with _scoped(work) as session:
        proof = _proof(session, work)
        _current(proof)
        for key in (
            "facts_revision", "original_start_intent", "reservation",
                    "occupancy", "sample_usage"
        ):
            assert proof[key] == before[key]


@pytest.fixture
def retained_raw_rows(monkeypatch):
    """Real Session/proof events; only the SQL transport is an explicit pure seam."""
    actor = uuid4()
    ctx = Context(uuid4(), actor, actor, category_id=uuid4())
    product, run, identity = uuid4(), uuid4(), uuid4()
    with Session() as session:
        session.begin()
        session.info["read_snapshot"] = False
        session.info["scope"] = (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id)
        request_proof(session).scope_locks.add(product)
        value = SimpleNamespace(
            session=session,
            ctx=ctx,
            product=product,
            run=run,
            fact=identity,
            calls=[],
            rows={
                ResourceCurrent: [
                    ResourceCurrent(
                        id=uuid4(),
                        tenant_id=ctx.tenant_id,
                        category_id=ctx.category_id,
                        product_id=product,
                        run_id=run,
                        fact_id=identity,
                        fact_revision=1,
                        epoch=1,
                    )
                ],
                ResourceFact: [
                    ResourceFact(
                        id=identity,
                        tenant_id=ctx.tenant_id,
                        category_id=ctx.category_id,
                        product_id=product,
                        run_id=run,
                        revision=1,
                    )
                ],
            },
        )

        def scalars(query):
            value.calls.append(query)
            return list(value.rows[query.column_descriptions[0]["entity"]])

        monkeypatch.setattr(session, "scalars", scalars)
        try:
            yield value
        finally:
            session.rollback()  # Pending ORM boundary tests must never try unbound I/O.


def _retained_raw(value, *, model=ResourceCurrent, run=None, product=None, revision=1, **options):
    product = product or value.product
    where = [model.tenant_id == value.ctx.tenant_id, model.product_id == product]
    where.extend(
        [model.run_id == (run or value.run)]
        if model is ResourceCurrent
        else [model.id == value.fact, model.revision == revision]
    )
    return retained._one(value.session, value.ctx, model, *where, scope_id=product, **options)


def test_retained_raw_held_writer_reuses_exact_pointer_and_fact_rows(retained_raw_rows):
    rows = retained_raw_rows
    for model in (ResourceCurrent, ResourceFact):
        first = _retained_raw(rows, model=model)
        assert _retained_raw(rows, model=model) is first
    assert len(rows.calls) == 2
    for query in rows.calls:
        assert query._for_update_arg is None
        assert query.compile().params["param_1"] == 2
        assert query.get_execution_options() == {"populate_existing": True, "autoflush": False}


def test_retained_raw_key_keeps_full_query_parameters_and_context(retained_raw_rows):
    rows = retained_raw_rows
    _retained_raw(rows)
    _retained_raw(rows, run=uuid4())
    _retained_raw(rows, model=ResourceFact)
    _retained_raw(rows, model=ResourceFact, revision=2)
    rows.ctx = replace(rows.ctx, agent_run_id=uuid4())
    _retained_raw(rows)
    assert len(rows.calls) == 5
    assert rows.calls[0].compile().params != rows.calls[1].compile().params
    assert rows.calls[2].compile().params != rows.calls[3].compile().params


def test_retained_raw_key_keeps_the_actual_transaction_scope(retained_raw_rows):
    rows = retained_raw_rows
    rows.session.info["scope"] = (*rows.session.info["scope"][:3], None)
    _retained_raw(rows)
    rows.session.info["scope"] = (
        rows.ctx.tenant_id,
        rows.ctx.actor_id,
        rows.ctx.requester_id,
        rows.ctx.category_id,
    )
    _retained_raw(rows)
    assert len(rows.calls) == 2


@pytest.mark.parametrize("mode", ["unheld", "different_gate", "no_transaction", "fake"])
def test_retained_raw_without_the_actual_product_gate_stays_fresh(retained_raw_rows, mode):
    rows = retained_raw_rows
    if mode == "unheld":
        request_proof(rows.session).scope_locks.clear()
    elif mode == "different_gate":
        request_proof(rows.session).scope_locks = {uuid4()}
    elif mode == "no_transaction":
        rows.session.rollback()
    else:
        rows.session = SimpleNamespace(
            info={"read_snapshot": True},
            scalars=lambda query: rows.calls.append(query) or rows.rows[ResourceCurrent],
        )
    _retained_raw(rows)
    _retained_raw(rows)
    assert len(rows.calls) == 2


@pytest.mark.parametrize("pending", ["new", "dirty", "deleted"])
def test_retained_raw_pending_writer_state_cannot_reuse_rows(retained_raw_rows, pending):
    rows = retained_raw_rows
    _retained_raw(rows)
    pointer = ResourceCurrent(id=uuid4(), epoch=1)
    if pending != "new":
        make_transient_to_detached(pointer)
    rows.session.add(pointer)
    if pending == "dirty":
        pointer.epoch = 2
    elif pending == "deleted":
        rows.session.delete(pointer)
    _retained_raw(rows)
    _retained_raw(rows)
    assert len(rows.calls) == 3


def test_retained_raw_snapshot_reuses_rows_but_rejects_pending_write(retained_raw_rows):
    rows = retained_raw_rows
    rows.session.info["read_snapshot"] = True
    request_proof(rows.session).scope_locks.clear()
    _retained_raw(rows)
    _retained_raw(rows)
    assert len(rows.calls) == 1
    rows.session.add(ResourceCurrent(id=uuid4(), epoch=1))
    with pytest.raises(DomainError) as caught:
        _retained_raw(rows)
    assert caught.value.reason == "INVALID_READ_CONTEXT" and len(rows.calls) == 1


def test_retained_raw_other_actor_cannot_borrow_held_rows(retained_raw_rows):
    rows = retained_raw_rows
    _retained_raw(rows)
    rows.ctx = replace(rows.ctx, actor_id=uuid4(), requester_id=uuid4())
    with pytest.raises(DomainError) as caught:
        _retained_raw(rows)
    assert caught.value.reason == "FORBIDDEN_SCOPE" and len(rows.calls) == 1


def test_retained_raw_recognized_dml_discards_rows_before_next_read(retained_raw_rows):
    rows = retained_raw_rows
    _retained_raw(rows)
    proof = request_proof(rows.session)
    before = proof.mutation_epoch

    # Actual ORMExecuteState runs the production class-level invalidator; this
    # instance listener only prevents the subsequent transport from reaching a DB.
    def no_database(_state):
        return SimpleNamespace()

    event.listen(rows.session, "do_orm_execute", no_database, retval=True)
    try:
        rows.session.execute(
            update(ResourceCurrent).where(ResourceCurrent.id == uuid4()).values(epoch=2)
        )
    finally:
        event.remove(rows.session, "do_orm_execute", no_database)
    assert proof.mutation_epoch == before + 1 and not proof.scalar_rows
    _retained_raw(rows)
    assert len(rows.calls) == 2


def test_retained_raw_savepoint_rollback_discards_the_held_read_proof(retained_raw_rows):
    rows = retained_raw_rows
    _retained_raw(rows)
    proof = request_proof(rows.session)
    before = proof.mutation_epoch
    savepoint = rows.session.begin_nested()
    savepoint.rollback()
    assert proof.mutation_epoch > before and not proof.scope_locks and not proof.scalar_rows
    _retained_raw(rows)
    request_proof(rows.session).scope_locks.add(rows.product)
    _retained_raw(rows)
    _retained_raw(rows)
    assert len(rows.calls) == 3


def test_retained_raw_new_root_transaction_does_not_borrow_old_rows(retained_raw_rows):
    rows = retained_raw_rows
    first = _retained_raw(rows)
    old_proof = request_proof(rows.session)
    rows.session.rollback()
    rows.session.begin()
    request_proof(rows.session).scope_locks.add(rows.product)
    rows.rows[ResourceCurrent] = [ResourceCurrent(id=uuid4(), epoch=2)]
    second = _retained_raw(rows)
    assert second is not first and request_proof(rows.session) is not old_proof
    assert _retained_raw(rows) is second and len(rows.calls) == 2


def test_retained_raw_fresh_reads_untracked_current_change(retained_raw_rows):
    rows = retained_raw_rows
    first = _retained_raw(rows)
    proof = request_proof(rows.session)
    before = proof.mutation_epoch
    changed = ResourceCurrent(id=first.id, fact_id=uuid4(), fact_revision=2, epoch=2)
    rows.rows[ResourceCurrent] = [changed]  # Pure transport models an untracked raw SQL change.
    assert _retained_raw(rows) is first
    assert _retained_raw(rows, fresh=True) is changed
    assert proof.mutation_epoch == before and len(rows.calls) == 2


@pytest.mark.parametrize("unavailable", [ResourceCurrent, ResourceFact])
def test_retained_final_dependency_forces_both_rows_actual(retained_raw_rows, unavailable):
    rows = retained_raw_rows
    _retained_raw(rows)
    _retained_raw(rows, model=ResourceFact)
    rows.rows[unavailable] = []
    before = len(rows.calls)
    binding = SimpleNamespace(run_id=rows.run)
    bundle = SimpleNamespace(fact_ref=SimpleNamespace(id=rows.fact, revision=1))
    with pytest.raises(DomainError) as caught:
        retained._fixed_dependency(
            rows.session, rows.ctx, rows.product, binding, bundle, fresh=True
        )
    assert caught.value.reason == "FORBIDDEN_SCOPE"
    assert len(rows.calls) - before == (1 if unavailable is ResourceCurrent else 2)


def test_retained_held_writer_keeps_fixed_fact_after_late_current_successor(
    retained_started_work, monkeypatch
):
    """Actual PG lineage/trigger checks; root alone executes this guarded test."""
    work = retained_started_work
    from pdos_next import source_current

    ordinary_effects, ordinary_basis = launch._saved_effects, source_current.direct_source_basis
    with _scoped(work) as session:
        gate = session.scalar(
            select(Product)
            .where(Product.tenant_id == work.setup.tenant, Product.id == work.setup.product)
            .with_for_update()
        )
        assert gate is not None
        request_proof(session).scope_locks.add(gate.id)
        baseline = _proof(session, work)
        _current(baseline)
        savepoint = session.begin_nested()
        try:
            pointer, original = resources._current(
                session, work.quality.ctx, work.setup.product, work.binding.run_id
            )
            # Prepare a real valid successor before the cached inspection. Its
            # insert obeys the actual app-role lineage/source/RLS triggers; the
            # callback only advances Current using its legal next revision.
            values = {
                attribute.key: deepcopy(getattr(original, attribute.key))
                for attribute in ResourceFact.__mapper__.column_attrs
            }
            values.update(
                id=uuid4(),
                created_at=now(),
                revision=original.revision + 1,
                previous_id=original.id,
                previous_revision=original.revision,
            )
            successor = ResourceFact(**values)
            successor.data = {
                **successor.data,
                "expected_previous_id": str(original.id),
                "expected_previous_revision": original.revision,
            }
            successor.fact_sha256 = resources._fact_hash(successor)
            session.add(successor)
            session.flush()
            before = _effects(session, work)
            seen = {"effects": False, "changed": False, "fresh": []}

            def real_effects(s, ctx, product_id, row, *, fresh=False):
                value = ordinary_effects(s, ctx, product_id, row, fresh=fresh)
                seen["effects"] = True
                seen["fresh"].append(fresh)
                return value

            def source_io_changes_current(s, ctx, product_id, refs, reads):
                value = ordinary_basis(s, ctx, product_id, refs, reads)
                if s is session and seen["effects"] and not seen["changed"]:
                    proof = request_proof(session)
                    epoch = proof.mutation_epoch
                    changed = session.execute(
                        text(
                            "UPDATE test_resource_current "
                            "SET fact_id=:fact, fact_revision=:revision, epoch=epoch+1 "
                            "WHERE tenant_id=:tenant AND product_id=:product AND id=:pointer "
                            "AND fact_id=:previous AND fact_revision=:previous_revision "
                            "RETURNING id"
                        ),
                        {
                            "fact": successor.id,
                            "revision": successor.revision,
                            "tenant": work.setup.tenant,
                            "product": work.setup.product,
                            "pointer": pointer.id,
                            "previous": original.id,
                            "previous_revision": original.revision,
                        },
                    ).scalar_one()
                    assert changed == pointer.id
                    assert proof.mutation_epoch == epoch, "Raw text SQL must exercise untracked I/O"
                    seen["changed"] = True
                return value

            monkeypatch.setattr(launch, "_saved_effects", real_effects)
            monkeypatch.setattr(source_current, "direct_source_basis", source_io_changes_current)
            # Permission remains read-only; this is an actual command Session
            # with a held Product gate, so its final owner SQL must be fresh.
            value = retained.inspect_retained_execution(
                session, work.quality.ctx, work.setup.product, _run_row(session, work), write=False
            )
            assert seen["changed"] and seen["fresh"] == [True]
            # Direct source IO and terminal owner SQL are actual, but a new
            # upstream Current version cannot replace the fixed saved Fact.
            _current(value)
            for key in (
                "facts_revision", "original_start_intent", "reservation",
                    "occupancy", "sample_usage"
            ):
                assert value[key] == baseline[key]
            assert _effects(session, work) == before, (
                "Inspection changed retained execution effects"
            )
        finally:
            savepoint.rollback()
