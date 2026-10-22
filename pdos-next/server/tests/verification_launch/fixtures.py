"""Explicit synthetic full host flow; root alone executes these PostgreSQL fixtures."""

# ruff: noqa: F811 - pytest fixture imports deliberately register dependencies
import json
from contextvars import ContextVar
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from build_start import test_transactions as start_fixtures
from sqlalchemy import update
from sqlalchemy.orm import Session
from test_project_first_plan import accepted, cmd
from verification_handoff import fixtures as upstream
from verification_handoff.fixtures import (  # noqa: F401
    known_configuration,
    operational_work,
)

from pdos_next.database import tenant_session
from pdos_next.domain.build_operational_facts.schemas import DecisionProof
from pdos_next.domain.test_resources import service as resources
from pdos_next.domain.test_resources.schemas import TestPlanBinding, TestResourceFactInput
from pdos_next.domain.verification_handoff.models import ActualMethodApplicability
from pdos_next.domain.verification_handoff.service import event_source
from pdos_next.domain.verification_launch.schemas import ExecutionPlan
from pdos_next.engines.planning.calendar import frozen_timezone
from pdos_next.models import Grant, LoginSession, now
from pdos_next.service import digest
from pdos_next.test_resource_import import import_test_resource_fact

OPERATIONS = ("test.run.plan", "verification.schedule.promise", "test.run.start")


@pytest.fixture
def ready_work(operational_work, request, monkeypatch):
    # Only the explicitly indirect-parametrized long storage test changes its
    # synthetic pre-signing horizon. All ordinary callers use the original data.
    callspec = getattr(request.node, "callspec", None)
    params = getattr(callspec, "params", {})
    long_storage = "launch_work" in params
    if long_storage:
        _launch_timing(SimpleNamespace(param=params["launch_work"]))
        work = operational_work
        until = now() + timedelta(minutes=120)
        with Session(work.setup.admin) as session, session.begin():
            session.execute(
                update(Grant)
                .where(
                    Grant.tenant_id == work.setup.tenant,
                    Grant.category_id == work.setup.category,
                    Grant.principal_id.in_((work.setup.human, work.setup.peer)),
                )
                .values(expires_at=until)
            )
            session.execute(
                update(LoginSession)
                .where(
                    LoginSession.tenant_id == work.setup.tenant,
                    LoginSession.principal_id.in_((work.setup.human, work.setup.peer)),
                )
                .values(expires_at=until)
            )
        original_fact = start_fixtures.authority_fact
        original_authorization = start_fixtures.authorization_command

        def storage_fact(work, role, kind, **changes):
            value = original_fact(work, role, kind, **changes)
            value["valid_until"] = (work.at + timedelta(minutes=120)).isoformat()
            return value

        def storage_authorization(work, role, **changes):
            command = original_authorization(work, role, **changes)
            limit = (work.at + timedelta(minutes=120)).isoformat()
            command["payload"]["valid_until"] = limit
            for decision in command["payload"]["professional_assessments"]:
                decision["valid_until"] = limit
            return command

        monkeypatch.setattr(start_fixtures, "authority_fact", storage_fact)
        monkeypatch.setattr(start_fixtures, "authorization_command", storage_authorization)
        work.launch_storage_profile = True
    fixture = start_fixtures.ready_work.__wrapped__(operational_work)
    try:
        yield next(fixture)
    finally:
        fixture.close()


@pytest.fixture
def accepted_work(ready_work, monkeypatch):
    original = upstream.import_authority

    def with_launch(work, role, kind, **changes):
        if role == "quality":
            changes["operations"] = sorted(set(changes.get("operations", ())) | set(OPERATIONS))
        return original(work, role, kind, **changes)

    # Imported before BuildStart and all old signer snapshots: never weaken recheck.
    monkeypatch.setattr(upstream, "import_authority", with_launch)
    if getattr(ready_work, "launch_storage_profile", False):
        original_grant = upstream.Grant
        original_login = upstream.LoginSession

        def storage_grant(**values):
            return original_grant(**{**values, "expires_at": now() + timedelta(minutes=120)})

        def storage_login(**values):
            return original_login(**{**values, "expires_at": now() + timedelta(minutes=120)})

        monkeypatch.setattr(upstream, "Grant", storage_grant)
        monkeypatch.setattr(upstream, "LoginSession", storage_login)
    fixture = upstream.handoff_work.__wrapped__(ready_work)
    work = next(fixture)
    try:
        accepted(work.quality, upstream.actual_method(work))
        accepted(work.engineer, upstream.handoff(work))
        view = upstream.listing(work)
        samples = [r for r in view["reference_samples"] if r["request_id"] == work.request_id]
        one = [{"sample_id": samples[0]["id"], "item_id": "dimension"}]
        returned = [{"sample_id": samples[1]["id"], "item_id": "dimension"}]
        accepted(
            work.quality,
            upstream.handoff(
                work, operation="verification.handoff.accept", coverage=one, returned=returned
            ),
        )
        work.accepted_request = upstream.current(work)
        yield work
    finally:
        fixture.close()


def _launch_timing(request):
    if request is None or not hasattr(request, "param"):
        return 12, 20
    parameter = request.param
    if (
        type(parameter) is not dict
        or set(parameter) != {"window_minutes", "fact_minutes"}
        or any(type(value) is not int for value in parameter.values())
        or parameter != {"window_minutes": 45, "fact_minutes": 60}
    ):
        raise ValueError(
            "Only the explicit storage window_minutes=45/fact_minutes=60 profile is allowed"
        )
    return parameter["window_minutes"], parameter["fact_minutes"]


@pytest.fixture
def launch_work(accepted_work, request, monkeypatch):
    window_minutes, fact_minutes = _launch_timing(request)
    work = accepted_work
    view = upstream.listing(work)
    row = work.accepted_request
    raw = row["request_snapshot"]
    run_id = uuid4()
    at = now()
    from pdos_next import clock

    # The plan/promise use a frozen server clock at an already real instant.
    # Start restores real UTC; the database's future-event guard stays active.
    monkeypatch.setattr(clock, "_clock", ContextVar("synthetic_plan_clock", default=lambda: at))
    window = {
        "start": at + timedelta(seconds=1),
        "finish": at + timedelta(minutes=window_minutes),
        "original_timezone": "UTC",
    }
    by_pair = {(r["sample"]["id"], r["item_id"]): r for r in view["actual_methods"] if r["current"]}
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as session:
        method_hashes = {
            key: session.get(ActualMethodApplicability, UUID(value["id"])).snapshot_sha256
            for key, value in by_pair.items()
        }
    by_sample = {r["id"]: r for r in view["reference_samples"]}
    reference = deepcopy(work.actual_source)
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
            "window": window,
            "environment": "Synthetic finite lab",
            "conditions": "Synthetic 20C",
            "equipment": reference,
            "calibration": reference,
            "pairs": [
                {
                    "sample": by_sample[c["sample_id"]]["reference"],
                    "item_id": c["item_id"],
                    "method_id": by_pair[c["sample_id"], c["item_id"]]["id"],
                    "method_revision": by_pair[c["sample_id"], c["item_id"]]["revision"],
                    "method_sha256": method_hashes[c["sample_id"], c["item_id"]],
                    "destructive": next(
                        i["destructive"] for i in raw["items"] if i["id"] == c["item_id"]
                    ),
                }
                for c in row["accepted_coverage"]
            ],
        }
    )
    decisions = {}
    resource_inputs = []
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
                    "valid_until": at + timedelta(minutes=fact_minutes),
                    "actor_id": work.quality.human,
                    "named_decision_id": decision_id,
                    "sources": [reference],
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
                "capacity": "1",
                "calendar": {
                    "calendar_id": "SYN-UTC-TEST",
                    "version": "1",
                    "timezone": "UTC",
                    "timezone_rules_sha256": frozen_timezone("UTC")[1],
                    "weekly": [
                        {"weekday": i, "intervals": [{"start_minute": 0, "end_minute": 1440}]}
                        for i in range(7)
                    ],
                },
                "calendar_sources": [reference],
                "external_occupancies_complete": True,
                "sources": [reference],
            }
        )
    work.test_decisions_current = True

    def named_decision(s, ctx, declared_binding, resource, decision, checked_at):
        current = (
            work.test_decisions_current
            and declared_binding == binding.model_dump(mode="json")
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

    work.test_issuer = resources.configure_local_synthetic(
        work.setup.engine,
        tenant_id=work.setup.tenant,
        product_id=work.setup.product,
        project_id=UUID(work.config["project"]),
        enabled=True,
        test_marker_verified=True,
        key=f"synthetic-test-{work.setup.product}",
        verify_named_decision=named_decision,
    )
    work.binding = binding
    work.test_input = TestResourceFactInput.model_validate(
        {
            "binding": binding,
            "external_id": f"SYN-TEST-{run_id}",
            "valid_from": at - timedelta(minutes=1),
            "valid_until": at + timedelta(minutes=fact_minutes),
            "resources": resource_inputs,
            "required_uses": [{"resource": v["resource"], "units": "1"} for v in resource_inputs],
            "requirements_sources": [reference],
            "sources": [reference],
            "reason": "Explicit synthetic named TestRun resources, no real qualification",
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
            work.test_issuer,
            work.test_input,
            request_key=str(uuid4()),
            command_id=uuid4(),
        )
    work.test_fact_id = UUID(receipt["subject_id"])
    work.plan = ExecutionPlan(
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
        resource_fact_id=work.test_fact_id,
        expected_resource_fact_revision=1,
    )
    yield work
    resources.disable_issuer(work.setup.engine, work.test_issuer.key)


def listing(work, setup=None):
    setup = setup or work.quality
    response = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/verification-launch",
        headers=setup.headers,
        params={"build_id": work.build_id},
    )
    assert response.status_code == 200, response.text
    return response.json()


def current(work, view=None):
    view = view if view is not None else listing(work)
    pointer = view["current_by_request"][work.request_id]
    return next(r for r in view["requests"] if r["id"] == pointer["request_version_id"])


def fixed_run(work, view=None):
    view = view if view is not None else listing(work)
    pointer = view["current_by_run"][str(work.binding.run_id)]
    return next(r for r in view["runs"] if r["id"] == pointer["run_version_id"])


def command(work, operation, **changes):
    from pdos_next.domain.verification_front import service as front
    from pdos_next.domain.verification_launch import service as launch

    # Test input construction reads the same persisted pointers directly. The
    # actual inputs/preview/execute remain real API calls with all host guards.
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as session:
        _, row = front._current(
            session, work.quality.ctx, work.setup.product, UUID(work.request_id)
        )
        _, run_row = launch._current(
            session, work.quality.ctx, work.setup.product, work.binding.run_id
        )
        request_revision = row.revision
        coverage = [
            c.model_dump(mode="json") for c in launch.accepted_coverage(front._snapshot(row))
        ]
        run_revision = run_row.revision if run_row else None
        plan_sha256 = run_row.plan_sha256 if run_row else None
    payload = {
        "request_id": work.request_id,
        "expected_request_revision": request_revision,
        "run_id": str(work.binding.run_id),
        "sources": [],
        "reason": "Explicit synthetic fixed TestRun intent",
        **changes,
    }
    if operation == "test.run.plan":
        payload.setdefault("coverage", coverage)
        payload.setdefault("execution_plan", work.plan.model_dump(mode="json"))
    else:
        payload.setdefault("expected_run_revision", run_revision)
        payload.setdefault("expected_plan_sha256", plan_sha256)
        at = work.binding.window.start if operation.endswith("promise") else now()
        reference = upstream.artifact(
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
        payload["sources"] = [reference]
        payload.setdefault(
            "at",
            {
                "occurred_at": at.isoformat(),
                "original_timezone": "UTC",
                "source": event_source(SimpleRef(reference)).model_dump(mode="json"),
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


def SimpleRef(value):
    from pdos_next.domain.configurations.schemas import DefinitionReference

    return DefinitionReference.model_validate(value)


def planned(work):
    value = command(work, "test.run.plan")
    receipt, prepared = accepted(work.quality, value)
    work.plan_command = value
    return receipt, prepared


def promised(work):
    planned(work)
    value = command(work, "verification.schedule.promise")
    receipt, prepared = accepted(work.quality, value)
    work.promise_command = value
    return receipt, prepared


def advance_clock(work, monkeypatch):
    from pdos_next import clock

    # The stored plan/promise precede this real instant. Never move Python
    # ahead of PostgreSQL or bypass its actual-start storage guard.
    assert datetime.now(UTC) >= work.binding.window.start
    monkeypatch.setattr(
        clock, "_clock", ContextVar("real_start_clock", default=lambda: datetime.now(UTC))
    )
    return now()


def started(work, monkeypatch):
    promised(work)
    advance_clock(work, monkeypatch)
    value = command(work, "test.run.start")
    receipt, prepared = accepted(work.quality, value)
    work.start_command = value
    return receipt, prepared
