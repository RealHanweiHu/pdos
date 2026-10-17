"""One real API chain for batched acceptance and two independently promised Runs.

Only the root executes PostgreSQL. Synthetic authority/resource facts enter their
existing trusted import ports; all business transitions use controlled commands.
"""

# ruff: noqa: F811 - imported pytest fixtures intentionally register dependencies
import json
from contextvars import ContextVar
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from security_fixture import synthetic_runtime
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_project_first_plan import accepted, cmd, post
from verification_handoff import fixtures as handoff
from verification_results import fixtures as results

from pdos_next.api import create_app
from pdos_next.database import tenant_session
from pdos_next.domain.build_execution.models import SampleUnit
from pdos_next.domain.build_operational_facts.models import ResourceOccupancy
from pdos_next.domain.build_operational_facts.schemas import DecisionProof
from pdos_next.domain.test_resources import service as resources
from pdos_next.domain.test_resources.models import (
    SampleRunUsage,
    TestResourceFact,
    TestResourceReservation,
)
from pdos_next.domain.test_resources.schemas import TestPlanBinding, TestResourceFactInput
from pdos_next.domain.verification_front import service as front
from pdos_next.domain.verification_front.models import FormalVerificationRequest
from pdos_next.domain.verification_handoff.models import ActualMethodApplicability
from pdos_next.domain.verification_launch import service as launches
from pdos_next.domain.verification_launch.models import (
    VerificationLaunchFact,
    VerificationRunCurrent,
    VerificationRunIdentity,
    VerificationRunVersion,
)
from pdos_next.domain.verification_launch.schemas import ExecutionPlan
from pdos_next.domain.verification_results import service as result_service
from pdos_next.domain.verification_results.models import (
    MeasurementRecord,
    TestResultActionFact,
    TestResultProjection,
)
from pdos_next.engines.planning.calendar import frozen_timezone
from pdos_next.models import Audit, Outbox, Receipt, now
from pdos_next.object_storage import LocalPrivateObjectStore
from pdos_next.service import digest
from pdos_next.test_resource_import import import_test_resource_fact
from verification_launch import fixtures as launch
from verification_launch.fixtures import (  # noqa: F401
    known_configuration,
    operational_work,
    ready_work,
)


@pytest.fixture
def multi_work(ready_work, monkeypatch, tmp_path):
    original_authority = handoff.import_authority

    def all_quality_actions(work, role, kind, **changes):
        if role == "quality":
            changes["operations"] = sorted(
                set(changes.get("operations", ())) | set(result_service.PAYLOADS)
            )
        return original_authority(work, role, kind, **changes)

    # Declare the combined synthetic authority before the retained BuildStart.
    monkeypatch.setattr(handoff, "import_authority", all_quality_actions)
    ready_work.s2_batched_lots = True
    fixture = launch.accepted_work.__wrapped__(ready_work, monkeypatch)
    work = next(fixture)
    work.test_issuers = []
    work.report_store = LocalPrivateObjectStore(tmp_path / "multi-run-originals")
    prior_store = getattr(work.setup.engine, "_pdos_results_store", None)
    prior_security = getattr(work.setup.engine, "_pdos_security_runtime", None)
    original_clients = {
        name: getattr(work, name).client for name in ("quality", "engineer", "setup")
    }
    client = TestClient(
        create_app(
            work.setup.engine,
            work.setup.auth,
            object_store=work.report_store,
            security_runtime=synthetic_runtime(),
        )
    )
    for name in original_clients:
        getattr(work, name).client = client
    try:
        yield work
    finally:
        for issuer in work.test_issuers:
            resources.disable_issuer(work.setup.engine, issuer.key)
        client.close()
        for name, previous in original_clients.items():
            getattr(work, name).client = previous
        result_service.configure_store(work.setup.engine, prior_store)
        from pdos_next.original_security import configure

        configure(work.setup.engine, prior_security)
        fixture.close()


def prepare_run(work, coverage, monkeypatch):
    """Import a distinct exact subset binding, without replacing a production DTO."""
    from pdos_next import clock

    run_work = SimpleNamespace(**vars(work))
    view, row = handoff.listing(work), handoff.current(work)
    raw = row["request_snapshot"]
    at, run_id = now(), uuid4()
    monkeypatch.setattr(clock, "_clock", ContextVar("multi_run_plan_clock", default=lambda: at))
    methods = {
        (value["sample"]["id"], value["item_id"]): value
        for value in view["actual_methods"]
        if value["current"]
    }
    samples = {value["id"]: value for value in view["reference_samples"]}
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as session:
        method_hashes = {
            key: session.get(ActualMethodApplicability, UUID(value["id"])).snapshot_sha256
            for key, value in methods.items()
        }
    conditions = {item["conditions"] for item in raw["items"]}
    assert conditions == {"23 C, dry"}
    source = deepcopy(work.actual_source)
    binding = TestPlanBinding.model_validate(
        {
            "run_id": run_id,
            "request_id": work.request_id,
            "accepted_request_id": row["id"],
            "accepted_request_revision": row["revision"],
            "build_id": work.build_id,
            "project_id": work.config["project"],
            "purpose": raw["purpose"],
            "executor_id": work.quality.human,
            "window": {
                "start": at + timedelta(seconds=1),
                "finish": at + timedelta(minutes=12),
                "original_timezone": "UTC",
            },
            "environment": "Synthetic finite lab",
            "conditions": next(iter(conditions)),
            "equipment": source,
            "calibration": source,
            "pairs": [
                {
                    "sample": samples[c["sample_id"]]["reference"],
                    "item_id": c["item_id"],
                    "method_id": methods[c["sample_id"], c["item_id"]]["id"],
                    "method_revision": methods[c["sample_id"], c["item_id"]]["revision"],
                    "method_sha256": method_hashes[c["sample_id"], c["item_id"]],
                    "destructive": next(
                        item["destructive"] for item in raw["items"] if item["id"] == c["item_id"]
                    ),
                }
                for c in coverage
            ],
        }
    )
    decisions, resource_inputs = {}, []
    for resource_id, kind, fact_kinds in [
        (uuid4(), "equipment", ("acceptance", "calibration")),
        (work.quality.human, "person", ("qualification",)),
    ]:
        facts = []
        for fact_kind in fact_kinds:
            decision_id = uuid4()
            decisions[decision_id] = (resource_id, fact_kind)
            facts.append(
                {
                    "kind": fact_kind,
                    "purpose": binding.purpose,
                    "operation_id": "test.run.start",
                    "status": "accepted",
                    "valid_from": at - timedelta(minutes=1),
                    "valid_until": at + timedelta(minutes=20),
                    "actor_id": work.quality.human,
                    "named_decision_id": decision_id,
                    "sources": [source],
                }
            )
        resource_inputs.append(
            {
                "resource": {"id": resource_id, "revision": 1, "kind": kind},
                "purposes": [binding.purpose],
                "operation_ids": ["test.run.start"],
                "lifecycle": "active",
                "facts": facts,
                "maintenance": [],
                # Both retained windows overlap. Declare two synthetic units from
                # the first import, rather than releasing/changing old occupancy.
                "capacity": "2" if kind == "person" else "1",
                "calendar": {
                    "calendar_id": "SYN-UTC-TEST",
                    "version": "1",
                    "timezone": "UTC",
                    "timezone_rules_sha256": frozen_timezone("UTC")[1],
                    "weekly": [
                        {"weekday": day, "intervals": [{"start_minute": 0, "end_minute": 1440}]}
                        for day in range(7)
                    ],
                },
                "calendar_sources": [source],
                "external_occupancies_complete": True,
                "sources": [source],
            }
        )

    def named_decision(session, ctx, declared_binding, resource, decision, checked_at):
        current = (
            declared_binding == binding.model_dump(mode="json")
            and decisions.get(decision.named_decision_id) == (resource.id, decision.kind)
            and decision.actor_id == work.quality.human
        )
        return DecisionProof(
            current=current,
            facts_revision=digest(
                {"decision": decision.model_dump(mode="json"), "current": current}
            ),
            valid_until=decision.valid_until,
        )

    issuer = resources.configure_local_synthetic(
        work.setup.engine,
        tenant_id=work.setup.tenant,
        product_id=work.setup.product,
        project_id=UUID(work.config["project"]),
        enabled=True,
        test_marker_verified=True,
        key=f"synthetic-multi-{run_id}",
        verify_named_decision=named_decision,
    )
    work.test_issuers.append(issuer)
    fact = TestResourceFactInput.model_validate(
        {
            "binding": binding,
            "external_id": f"SYN-MULTI-{run_id}",
            "valid_from": at - timedelta(minutes=1),
            "valid_until": at + timedelta(minutes=20),
            "resources": resource_inputs,
            "required_uses": [
                {"resource": value["resource"], "units": "1"} for value in resource_inputs
            ],
            "requirements_sources": [source],
            "sources": [source],
            "reason": "Explicit synthetic per-Run scope; no real qualification",
        }
    )
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
            issuer,
            fact,
            request_key=str(uuid4()),
            command_id=uuid4(),
        )
    run_work.binding, run_work.test_fact_id = binding, UUID(receipt["subject_id"])
    run_work.plan = ExecutionPlan(
        **{
            name: getattr(binding, name)
            for name in (
                "window",
                "executor_id",
                "equipment",
                "calibration",
                "environment",
                "conditions",
            )
        },
        resource_fact_id=run_work.test_fact_id,
        expected_resource_fact_revision=1,
    )
    return run_work


def launch_command(work, operation):
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as session:
        _, request = front._current(
            session, work.quality.ctx, work.setup.product, UUID(work.request_id)
        )
        _, run = launches._current(
            session, work.quality.ctx, work.setup.product, run_id=work.binding.run_id
        )
        payload = {
            "request_id": work.request_id,
            "expected_request_revision": request.revision,
            "run_id": str(work.binding.run_id),
            "sources": [],
            "reason": "Synthetic per-Run launch intent",
        }
        if operation == "test.run.plan":
            payload.update(
                coverage=[
                    {"sample_id": str(pair.sample.id), "item_id": pair.item_id}
                    for pair in work.binding.pairs
                ],
                execution_plan=work.plan.model_dump(mode="json"),
            )
        else:
            payload.update(expected_run_revision=run.revision, expected_plan_sha256=run.plan_sha256)
    if operation != "test.run.plan":
        at = work.binding.window.start if operation.endswith("promise") else now()
        source = handoff.artifact(
            work.quality,
            json.dumps(
                {
                    "request_id": work.request_id,
                    "run_id": str(work.binding.run_id),
                    "purpose": work.binding.purpose,
                    "operation": operation,
                    "occurred_at": at.isoformat(),
                    "executor_id": str(work.binding.executor_id),
                }
            ),
        )
        payload.update(
            sources=[source],
            at={
                "occurred_at": at.isoformat(),
                "original_timezone": "UTC",
                "source": handoff.event_source(launch.SimpleRef(source)).model_dump(mode="json"),
            },
        )
    value = cmd(work.quality, operation, payload)
    response = work.quality.client.post(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/verification-launch/inputs",
        headers=work.quality.headers,
        json=value,
    )
    assert response.status_code == 200, response.text
    value["source_read_set"] = response.json()["required_source_read_set"]
    return value


def counts(work):
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as session:
        operations = tuple(launches.PAYLOADS) + tuple(result_service.PAYLOADS)

        def count(model):
            query = select(func.count()).select_from(model)
            # Event-source registration is a separate controlled action. Count
            # only launch/result receipts when proving a refused Start has no
            # effect on this chain; retain all business/resource row counts.
            if model in (Receipt, Audit):
                query = query.where(model.operation.in_(operations))
            elif model is Outbox:
                query = query.join(
                    Receipt,
                    (Receipt.tenant_id == Outbox.tenant_id) & (Receipt.id == Outbox.receipt_id),
                ).where(Receipt.operation.in_(operations))
            return session.scalar(query)

        return {
            model.__tablename__: count(model)
            for model in (
                FormalVerificationRequest,
                VerificationRunIdentity,
                VerificationRunVersion,
                VerificationRunCurrent,
                VerificationLaunchFact,
                TestResourceReservation,
                ResourceOccupancy,
                SampleRunUsage,
                MeasurementRecord,
                TestResultActionFact,
                TestResultProjection,
                Receipt,
                Audit,
                Outbox,
            )
        }


def report(work):
    fixed = results.current_rows(work)
    work.report_rows = []
    for pair in fixed.run.coverage:
        sample = next(sample for sample in fixed.run.samples if sample.id == pair.sample_id)
        item = next(item for item in fixed.run.items if item.id == pair.item_id)
        work.report_rows.append(
            {
                "format": "pdos-measurement-jsonl-v1",
                "run_id": str(fixed.run.id),
                "sample_id": str(sample.id),
                "sample_revision": sample.revision,
                "actual_configuration": sample.actual_configuration.model_dump(mode="json"),
                "cavity": sample.cavity,
                "item_id": item.id,
                "raw_value": "10.0000",
                "unit": item.unit,
                "conditions": fixed.run.execution.conditions,
                "environment": fixed.run.execution.environment,
                "equipment": fixed.run.execution.equipment.model_dump(mode="json"),
                "calibration": fixed.run.execution.calibration.model_dump(mode="json"),
                "method": item.method.model_dump(mode="json"),
                "executor_id": str(work.quality.human),
                "observed_at": now().isoformat(),
                "observed_timezone": "UTC",
            }
        )
    work.report_artifact = results.upload_report(work, work.report_rows)
    return results.capture(work, (0,))[0]


def test_batched_acceptance_two_runs_keep_independent_promises_and_aggregate_only_at_end(
    multi_work,
    monkeypatch,
):
    work = multi_work
    sample_lots = {sample["id"]: sample["lot_id"] for sample in work.samples}
    assert len(sample_lots) == len(set(sample_lots.values())) == 2
    assert set(sample_lots.values()) == set(work.s2_batched_lot_ids)
    assert len({sample["actual_configuration_id"] for sample in work.samples}) == 1
    first = deepcopy(work.accepted_request["accepted_coverage"])
    offered = work.accepted_request["offered_coverage"]
    second = [value for value in offered if value not in first]
    assert len(first) == len(second) == 1
    run_a = prepare_run(work, first, monkeypatch)
    accepted(work.quality, launch_command(run_a, "test.run.plan"))
    accepted(work.quality, launch_command(run_a, "verification.schedule.promise"))
    launch.advance_clock(run_a, monkeypatch)
    start_receipt, start_prepared = accepted(work.quality, launch_command(run_a, "test.run.start"))
    original_a = results.current_rows(run_a)
    first_times = {
        key: deepcopy(original_a.request.request_snapshot["timeline"][key])
        for key in ("promised_start", "actual_start")
    }
    assert all(first_times.values())

    captured_a = report(run_a)
    accepted(work.quality, results.command(run_a, "test.results.import", captured=captured_a))
    partial_a = results.current_rows(run_a)
    first_times["preliminary_result"] = deepcopy(
        partial_a.request.request_snapshot["timeline"]["preliminary_result"]
    )
    assert first_times["preliminary_result"] is not None
    assert partial_a.run.status == "running" and partial_a.run.result == "indeterminate"
    assert partial_a.request.status == "executing"
    accepted(work.quality, results.command(run_a, "test.results.import", final=True))
    final_a = results.current_rows(run_a)
    assert final_a.run.status == "results_pending" and final_a.run.result == "pass"
    assert final_a.request.status == "executing"
    assert final_a.request.request_snapshot["timeline"]["final_result"] is None
    assert handoff.current(work)["coverage_gaps"]

    # Old intent replays after a result successor neither resurrect nor duplicate A.
    before_replay = counts(work)
    for value in (
        start_prepared,
        {**deepcopy(start_prepared), "command_id": str(uuid4()), "idempotency_key": str(uuid4())},
    ):
        replay = post(work.quality, value)
        assert replay.status_code == 200, replay.text
        assert replay.json()["id"] == start_receipt["id"]
    assert counts(work) == before_replay
    assert results.current_rows(run_a).row.id == final_a.row.id

    # A non-result successor may continue this executing request, but its exact
    # previous scope cannot be used to erase the retained preliminary clock.
    forged_id = uuid4()
    forged = deepcopy(vars(final_a.request))
    forged_snapshot = deepcopy(final_a.request.request_snapshot)
    forged_snapshot["revision"] = final_a.request.revision + 1
    forged_snapshot["timeline"]["preliminary_result"] = None
    forged.update(
        id=forged_id,
        created_at=now(),
        revision=final_a.request.revision + 1,
        previous_request_id=final_a.request.id,
        previous_revision=final_a.request.revision,
        operation="verification.handoff.return",
        request_snapshot=forged_snapshot,
        snapshot_sha256=digest(forged_snapshot),
        intent_digest=digest({"negative_clock_probe": str(forged_id)}),
        reason="Synthetic rejected clock erasure; no business fact is accepted",
    )
    before_clock_erasure = counts(work)
    with pytest.raises(
        DBAPIError, match="Non-result operation must preserve prior request result clocks"
    ) as refused_clock:
        with tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.quality.human,
            category_id=work.setup.category,
        ) as session:
            role = session.execute(
                text(
                    "SELECT current_user,rolsuper,rolbypassrls "
                    "FROM pg_roles WHERE rolname=current_user"
                )
            ).one()
            assert tuple(role) == ("pdos_next_app", False, False)
            session.add(FormalVerificationRequest(**forged))
            session.flush()
    assert refused_clock.value.orig.sqlstate == "23514"
    assert counts(work) == before_clock_erasure
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as session:
        assert session.get(FormalVerificationRequest, forged_id) is None
    preserved = results.current_rows(run_a)
    assert preserved.request.id == final_a.request.id
    assert preserved.request.request_snapshot == final_a.request.request_snapshot

    accepted(
        work.quality,
        handoff.handoff(work, operation="verification.handoff.accept", coverage=second),
    )
    continued = handoff.current(work)
    assert continued["status"] == "executing" and len(continued["accepted_coverage"]) == 2
    for key, value in first_times.items():
        assert continued["timeline"][key] == value
    run_b = prepare_run(work, second, monkeypatch)
    accepted(work.quality, launch_command(run_b, "test.run.plan"))

    # B is still before its future window: the existing request-level promise
    # does not grant this new Run an own promise or an actual-start capability.
    before_unpromised_read = counts(work)
    unpromised_view = launch.listing(run_b)
    b_pointer = unpromised_view["current_by_run"][str(run_b.binding.run_id)]
    unpromised_b = next(
        row for row in unpromised_view["runs"] if row["id"] == b_pointer["run_version_id"]
    )
    assert unpromised_b["promise"] is None
    assert unpromised_b["capabilities"]["run_start"] is False
    assert counts(work) == before_unpromised_read
    assert results.current_rows(run_b).run.status == "planned"
    assert results.current_rows(run_a).row.run_snapshot == final_a.row.run_snapshot

    accepted(work.quality, launch_command(run_b, "verification.schedule.promise"))
    launch.advance_clock(run_b, monkeypatch)
    accepted(work.quality, launch_command(run_b, "test.run.start"))
    running_b = results.current_rows(run_b)
    assert running_b.run.status == "running"
    assert running_b.run.actual_start is not None
    assert running_b.run.actual_start != original_a.run.actual_start
    for key, value in first_times.items():
        assert running_b.request.request_snapshot["timeline"][key] == value
    assert results.current_rows(run_a).row.run_snapshot == final_a.row.run_snapshot
    captured_b = report(run_b)
    accepted(
        work.quality, results.command(run_b, "test.results.import", captured=captured_b, final=True)
    )
    final_b = results.current_rows(run_b)
    assert final_b.run.result == "pass" and final_b.request.status == "reported"
    assert final_b.request.request_snapshot["timeline"]["final_result"] is not None
    view = launch.listing(work)
    run_ids = {str(run_a.binding.run_id), str(run_b.binding.run_id)}
    assert set(view["runs_by_request"][work.request_id]) == run_ids
    assert len(view["runs_by_request"][work.request_id]) == 2
    assert set(view["current_by_run"]) == run_ids
    for sample in view["reference_samples"]:
        if sample["id"] in sample_lots:
            assert sample["lot_id"] == sample_lots[sample["id"]]

    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as session:
        promises = session.scalars(
            select(VerificationLaunchFact).where(
                VerificationLaunchFact.request_id == UUID(work.request_id),
                VerificationLaunchFact.operation == "verification.schedule.promise",
            )
        ).all()
        assert {str(promise.run_id) for promise in promises} == run_ids
        assert len(promises) == 2
        for run_work in (run_a, run_b):
            fact = session.get(TestResourceFact, run_work.test_fact_id)
            assert fact.binding == run_work.binding.model_dump(mode="json")
            assert len(fact.binding["pairs"]) == 1
            uses = session.scalars(
                select(SampleRunUsage).where(SampleRunUsage.run_id == run_work.binding.run_id)
            ).all()
            assert {use.sample_id for use in uses} == {run_work.binding.pairs[0].sample.id}
            physical_sample = session.get(SampleUnit, run_work.binding.pairs[0].sample.id)
            assert str(physical_sample.lot_id) == sample_lots[str(physical_sample.id)]
            assert (
                physical_sample.actual_configuration_id
                == run_work.binding.pairs[0].sample.actual_configuration.id
            )
        assert (
            session.get(VerificationRunVersion, original_a.row.id).run_snapshot
            == original_a.row.run_snapshot
        )

    # Each named review/disposition belongs to its own Run; A alone cannot close B.
    for run_work in (run_a, run_b):
        computed = post(work.quality, results.command(run_work, "test.result.compute"))
        assert computed.status_code == 200, computed.text
        accepted(work.quality, results.command(run_work, "test.run.review"))
        reviewed = results.current_rows(run_work).run
        assert reviewed.status == "reviewed"
        assert reviewed.professional_conclusion.actor_id == work.quality.human
        accepted(work.quality, results.command(run_work, "test.disposition.decide"))
        disposed = results.current_rows(run_work).run
        assert disposed.status == "disposed" and disposed.disposition.actor_id == work.quality.human
        expected = "reported" if run_work is run_a else "disposed"
        assert results.current_rows(run_work).request.status == expected
    disposed_b = results.current_rows(run_b)
    assert disposed_b.request.request_snapshot["timeline"]["disposed"] is not None
    assert results.current_rows(run_a).run.measurements == final_a.run.measurements
    assert disposed_b.run.measurements == final_b.run.measurements
