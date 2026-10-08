"""Retained Start proof checks; only root executes these on its guarded PG target.

Every Start below is a real API flow with its real clock and one shared resource/
sample transaction. Later read-clock advancement never writes a backdated event
or renews execution permission. All authority/source material is synthetic.
"""

# ruff: noqa: F811 - imported fixtures register their transitive dependencies

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from build_start.test_transactions import import_authority
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
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
    TestResourceReservation as ResourceReservation,
)
from pdos_next.domain.verification_launch import service as launch
from pdos_next.domain.verification_launch.models import (
    VerificationRunCurrent,
    VerificationRunVersion,
)
from pdos_next.models import Artifact, Audit, Outbox, Receipt, RequestKey
from pdos_next.schemas.verification.contracts import TestRun as RunDTO
from pdos_next.service import digest

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
    preparation = launch_fixtures.launch_work.__wrapped__(work, request=None)
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
        rows = session.scalars(
            select(model).where(model.tenant_id == work.setup.tenant).order_by(model.id)
        ).all()
        result[model.__tablename__] = [
            digest({column.name: getattr(row, column.name) for column in model.__table__.columns})
            for row in rows
        ]
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


def test_retained_saved_start_with_simulated_late_read_clock_and_no_new_permission(
    retained_started_work, monkeypatch
):
    work = retained_started_work
    with tenant_session(work.setup.engine, work.setup.tenant) as session:
        row = _run_row(session, work)
        original = _proof(session, work, row)
        _current(original)
        original_effects = _effects(session, work)
        saved_at = row.created_at
        assert work.binding.window.start <= saved_at < work.binding.window.finish

    # A new independent results-only credential has no applicability to the
    # original Start. Its addition must not erase that already committed event.
    _result_authority(work, suffix=f"later-{uuid4()}")
    with tenant_session(work.setup.engine, work.setup.tenant) as session:
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
            with tenant_session(work.setup.engine, work.setup.tenant) as session:
                row = _run_row(session, work)
                proof = _proof(session, work, row, at=late)
                _current(proof)
                assert proof["execution_window_elapsed"] is True
                assert proof["saved_start_at"] == saved_at.isoformat()
                assert proof["actual_start"] == original["actual_start"]
                assert proof["facts_revision"] == original["facts_revision"]
                assert proof["occupancy"] == original["occupancy"]
                assert proof["sample_usage"] == original["sample_usage"]
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

    with tenant_session(work.setup.engine, work.setup.tenant) as session:
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
    with tenant_session(work.setup.engine, work.setup.tenant) as session:
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
                **{c.name: deepcopy(getattr(row, c.name)) for c in row.__table__.columns}
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


def test_retained_proof_rechecks_source_terminal_withdrawal_and_resource_sample_epochs(
    retained_started_work,
):
    work = retained_started_work
    with tenant_session(work.setup.engine, work.setup.tenant) as session:
        original = _effects(session, work)
        _current(_proof(session, work))
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
                assert proof["current"] is False, model.__tablename__
                assert proof["reason_codes"] == ["RETAINED_EXECUTION_CHANGED"], proof
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


def test_retained_proof_rejects_issuer_disable_restore_aba_without_new_effects(
    retained_started_work,
):
    work = retained_started_work
    with tenant_session(work.setup.engine, work.setup.tenant) as session:
        _current(_proof(session, work))
    issuer = work.test_issuer
    resources.disable_issuer(work.setup.engine, issuer.key)
    with tenant_session(work.setup.engine, work.setup.tenant) as session:
        missing = _proof(session, work)
        assert missing["current"] is False
        assert missing["reason_codes"] == ["RETAINED_EXECUTION_CHANGED"], missing
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
    with tenant_session(work.setup.engine, work.setup.tenant) as session:
        proof = _proof(session, work)
        assert proof["current"] is False
        assert proof["reason_codes"] == ["RETAINED_EXECUTION_CHANGED"], proof


def test_retained_proof_rejects_original_professional_qualification_revoke_restore_aba(
    retained_started_work,
):
    work = retained_started_work
    with tenant_session(work.setup.engine, work.setup.tenant) as session:
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
    with tenant_session(work.setup.engine, work.setup.tenant) as session:
        assert _proof(session, work)["current"] is False
    import_authority(
        work,
        "manufacturing",
        "qualification",
        state="active",
        previous_id=revoked["subject_id"],
        expected_previous_revision=revoked["subject_revision"],
    )
    with tenant_session(work.setup.engine, work.setup.tenant) as session:
        pointer = session.scalar(
            select(ProfessionalCurrent).where(
                ProfessionalCurrent.tenant_id == work.setup.tenant,
                ProfessionalCurrent.subject_id == work.setup.human,
                ProfessionalCurrent.kind == "qualification",
                ProfessionalCurrent.external_id == "synthetic-manufacturing-qualification",
            )
        )
        assert pointer.epoch == original_epoch + 2
        assert _proof(session, work)["current"] is False


def test_retained_proof_rejects_new_real_observation_of_configuration_deviation(
    retained_started_work,
):
    work = retained_started_work
    with tenant_session(work.setup.engine, work.setup.tenant) as session:
        _current(_proof(session, work))
    # The shared launch fixture retains fixed IDs, not its original command
    # payloads. Reconstruct only new draft inputs from the exact saved versions;
    # never rewrite the planned configurations or substitute a current version.
    response = work.setup.client.get(
        f"/v1/products/{work.setup.product}/configurations", headers=work.setup.headers
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
                    "reason": "Synthetic new observed deviation requires retained-proof recheck",
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
    with tenant_session(work.setup.engine, work.setup.tenant) as session:
        proof = _proof(session, work)
        assert proof["current"] is False, proof
        assert proof["reason_codes"] in (["SOURCE_STALE"], ["RETAINED_EXECUTION_CHANGED"])
