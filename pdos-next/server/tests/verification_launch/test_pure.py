"""Pure delivered-kernel launch checks. No database, provider or real qualification."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from verification_handoff.test_pure import AT, handler, offer
from verification_handoff.test_pure import work as initial_work

from pdos_next.domain.verification.handlers import semantic_digest
from pdos_next.domain.verification.ports import Invocation
from pdos_next.domain.verification_front.adapters import authority_dto
from pdos_next.domain.verification_launch import service
from pdos_next.domain.verification_launch.adapters import LaunchCommands, LaunchSamples, kernel
from pdos_next.domain.verification_launch.schemas import ExecutionPlan, PlanPayload, StartPayload
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import (
    EventTime,
    HandoffAccept,
    RunPlan,
    RunStart,
    SchedulePromise,
)
from pdos_next.service import Context, digest


@pytest.fixture
def work():
    value = initial_work.__wrapped__()
    offered = offer(value)
    h = handler(value)
    h.execute(invocation(value.request, offered, "verification.handoff.offer"), offered)
    value.request = value.recorded[-1]
    accepted = HandoffAccept(
        coverage=offered.coverage,
        returned_coverage=(),
        next_owner_id=value.actor,
        reason="Synthetic full acceptance",
        at=EventTime(occurred_at=AT, original_timezone="UTC", source=value.source),
    )
    h = handler(value, roles=("quality",))
    h.execute(invocation(value.request, accepted, "verification.handoff.accept"), accepted)
    value.request = value.recorded[-1]
    value.recorded = []
    value.reserved = []
    reference = {
        "artifact_id": value.source.id,
        "expected_revision": 1,
        "line": 1,
        "quote": "Explicit synthetic fixture, no real qualification",
    }
    value.plan = ExecutionPlan(
        window={
            "start": AT + timedelta(minutes=2),
            "finish": AT + timedelta(minutes=20),
            "original_timezone": "UTC",
        },
        executor_id=value.actor,
        equipment=reference,
        calibration=reference,
        environment="Synthetic lab",
        conditions="Synthetic 20C",
        resource_fact_id=uuid4(),
        expected_resource_fact_revision=1,
    )
    value.run_id = uuid4()
    return value


def invocation(subject, payload, operation):
    return Invocation(
        command_id=uuid4(),
        operation=operation,
        subject_id=subject.id,
        expected_revision=subject.revision,
        semantic_digest=semantic_digest(payload),
    )


def launch(work, *, at=AT, confirmed=True, availability="ready", applicable=True, actor=None):
    actor = actor or work.actor
    authority = authority_dto(
        {
            "scope": work.request.scope.model_dump(mode="json"),
            "authorized": True,
            "qualified": True,
            "roles": ["quality"],
        },
        actor,
        at,
    )

    def save(mutation):
        work.recorded.append(mutation)
        return mutation.run or mutation.request

    commands = LaunchCommands(
        authority,
        work.request,
        save,
        accepted_confirmation=confirmed,
        fixed_run=getattr(work, "run", None),
    )
    samples = LaunchSamples(
        lambda _: {
            "availability": availability,
            "current_readiness": {
                "source_ref": work.source.model_dump(mode="json"),
                "clocks": {
                    "occurred_at": (AT - timedelta(minutes=10)).isoformat(),
                    "original_timezone": "UTC",
                },
            },
        },
        lambda _: applicable,
        lambda *args: work.reserved.append(args),
        lambda *_: None,
    )
    return kernel(commands, work.request.build, lambda *_: None, samples)


def planned(work):
    value = RunPlan(run_id=work.run_id, coverage=work.request.acceptances[0].coverage)
    launch(work).execute(invocation(work.request, value, "test.run.plan"), value)
    mutation = work.recorded[-1]
    work.request, work.run = mutation.request, mutation.run
    return mutation


def promised(work):
    planned(work)
    value = SchedulePromise(
        run_id=work.run.id,
        expected_run_revision=work.run.revision,
        at=EventTime(
            occurred_at=work.plan.window.start, original_timezone="UTC", source=work.source
        ),
    )
    launch(work).execute(invocation(work.request, value, "verification.schedule.promise"), value)
    work.request = work.recorded[-1].request
    return work.recorded[-1]


def started(work, **changes):
    promised(work)
    value = RunStart(
        at=EventTime(
            occurred_at=work.plan.window.start, original_timezone="UTC", source=work.source
        ),
        execution=service._execution(work.plan),
    )
    launch(work, at=work.plan.window.start + timedelta(seconds=1), **changes).execute(
        invocation(work.run, value, "test.run.start"), value
    )
    return work.recorded[-1]


def test_plan_and_full_promise_are_zero_occupancy_and_preserve_unaccepted_gaps(work):
    original = work.request
    promised(work)
    assert work.run.status == "planned" and work.run.actual_start is None
    assert work.run.execution is None and work.run.result == "pending"
    assert work.reserved == [] and work.request.status == "scheduled"
    assert work.request.timeline.promised_start.occurred_at == work.plan.window.start
    assert work.request.timeline.actual_start is None
    assert work.request.acceptances == original.acceptances


def test_actual_start_uses_kernel_and_reserves_once_before_recording(work):
    result = started(work)
    assert result.run.status == "running" and result.run.revision == 2
    assert result.request.status == "executing"
    assert result.run.actual_start.occurred_at == work.plan.window.start
    assert result.run.execution == service._execution(work.plan)
    assert len(work.reserved) == 1
    assert result.run.result == "pending" and not result.run.measurements
    assert result.request.timeline.final_result is None and result.request.timeline.disposed is None


@pytest.mark.parametrize(
    "availability,applicable", [("unknown", True), ("hold", True), ("ready", False)]
)
def test_kernel_blocks_unknown_or_hold_or_inapplicable_before_plan(work, availability, applicable):
    payload = RunPlan(run_id=work.run_id, coverage=work.request.acceptances[0].coverage)
    with pytest.raises(DomainError) as error:
        launch(work, availability=availability, applicable=applicable).execute(
            invocation(work.request, payload, "test.run.plan"), payload
        )
    assert error.value.reason == "SAMPLE_UNAVAILABLE"
    assert not work.reserved and not work.recorded


def test_common_confirmation_required_before_any_effect(work):
    promised(work)
    work.recorded.clear()
    value = RunStart(
        at=EventTime(
            occurred_at=work.plan.window.start, original_timezone="UTC", source=work.source
        ),
        execution=service._execution(work.plan),
    )
    with pytest.raises(DomainError, match="共同开测实质确认"):
        launch(work, at=work.plan.window.start, confirmed=False).execute(
            invocation(work.run, value, "test.run.start"), value
        )
    assert not work.reserved and not work.recorded


def test_current_actor_must_be_fixed_executor(work):
    with pytest.raises(DomainError) as error:
        started(work, actor=uuid4())
    assert error.value.reason == "NAMED_DECISION_REQUIRED"
    assert not work.reserved


def public_plan(work):
    return PlanPayload(
        request_id=work.request.id,
        expected_request_revision=work.request.revision,
        run_id=work.run_id,
        coverage=work.request.acceptances[0].coverage,
        execution_plan=work.plan,
        reason="Explicit synthetic plan",
    )


@pytest.mark.parametrize("field", ["tenant_id", "qualified", "nature", "resource_units"])
def test_public_plan_rejects_trusted_field_injection(work, field):
    raw = public_plan(work).model_dump(mode="json")
    raw[field] = "client claim"
    with pytest.raises(ValidationError):
        PlanPayload.model_validate(raw)


def test_run_selects_nonempty_accepted_subset_without_hiding_request_scope(work):
    original = work.request.model_dump(mode="json")
    service._full_coverage(work.request, work.request.acceptances[0].coverage[:1])
    service._full_coverage(work.request, work.request.acceptances[0].coverage)
    assert work.request.model_dump(mode="json") == original
    with pytest.raises(DomainError) as error:
        service._full_coverage(work.request, ())
    assert error.value.reason == "INVALID_COVERAGE"


def test_closed_start_cannot_replace_execution_plan(work):
    raw = dict(
        request_id=work.request.id,
        expected_request_revision=1,
        run_id=work.run_id,
        expected_run_revision=1,
        expected_plan_sha256="a" * 64,
        at=EventTime(occurred_at=AT, original_timezone="UTC", source=work.source),
        reason="Synthetic start",
        execution_plan=work.plan,
    )
    with pytest.raises(ValidationError):
        StartPayload.model_validate(raw)


def test_alias_semantic_ignores_token_and_coverage_order_only(work):
    payload = public_plan(work)
    alternate = payload.model_copy(
        update={"confirmation_token": "x" * 30, "coverage": tuple(reversed(payload.coverage))}
    )
    assert service.semantic(payload) == service.semantic(alternate)
    changed = payload.model_copy(
        update={
            "execution_plan": work.plan.model_copy(update={"environment": "another environment"})
        }
    )
    assert digest(service.semantic(payload)) != digest(service.semantic(changed))


def binding(work):
    methods = {
        (c.sample_id, c.item_id): SimpleNamespace(id=uuid4(), revision=1, snapshot_sha256="b" * 64)
        for c in work.request.acceptances[0].coverage
    }
    row = SimpleNamespace(id=uuid4(), revision=work.request.revision)
    return service._binding(
        row, work.request, work.run_id, work.plan, methods, work.request.acceptances[0].coverage
    )


def test_http_json_plan_matches_complete_strict_resource_binding_values(work):
    declared = binding(work)
    # The strict professional reference subtype and configuration base type have
    # different nominal identities despite identical fully validated values.
    http_plan = ExecutionPlan.model_validate_json(work.plan.model_dump_json())
    assert type(declared.equipment) is not type(http_plan.equipment)
    assert declared.equipment != http_plan.equipment
    assert service._fixed_plan(declared) == service._fixed_plan(http_plan)
    assert service._fixed_plan(declared)["equipment"] == http_plan.equipment.model_dump(mode="json")


def preview_setup(work, monkeypatch, operation="test.run.plan"):
    if operation == "verification.schedule.promise":
        planned(work)
    elif operation == "test.run.start":
        promised(work)
    if operation == "test.run.plan":
        payload = public_plan(work)
    else:
        cls = StartPayload if operation == "test.run.start" else service.PromisePayload
        payload = cls(
            request_id=work.request.id,
            expected_request_revision=work.request.revision,
            run_id=work.run_id,
            expected_run_revision=work.run.revision,
            expected_plan_sha256=digest(work.plan.model_dump(mode="json")),
            at=EventTime(
                occurred_at=work.plan.window.start,
                original_timezone="UTC",
                source=work.source,
            ),
            reason="Explicit newly reviewed version",
        )
    ctx = Context(work.request.scope.tenant_id, work.actor, work.actor)
    product = SimpleNamespace(id=work.request.scope.product_id)
    clock = [
        work.plan.window.start + timedelta(seconds=1) if isinstance(payload, StartPayload) else AT
    ]
    report = {
        "status": "READY",
        "capacity_status": "checked",
        "input_digest": "a" * 64,
        "checks": [{"code": "complete_current_facts", "status": "READY"}],
        "conditions": [],
        "fixed_resources": [{"id": "fixed-resource", "epoch": 4}],
    }
    authority = {
        "scope": work.request.scope.model_dump(mode="json"),
        "roles": ["quality"],
        "authorized": True,
        "qualified": True,
    }
    p = SimpleNamespace(
        previous=SimpleNamespace(), base=work.request, references=[], reads=[], authority=authority
    )
    run_row = None
    if hasattr(work, "run"):
        run_row = SimpleNamespace(
            id=uuid4(),
            execution_plan=work.plan.model_dump(mode="json"),
            plan_sha256=digest(work.plan.model_dump(mode="json")),
            sources=[],
            required_source_read_set=[],
            authority_snapshot=authority,
            created_at=AT,
        )
    bound = SimpleNamespace(
        physical=p,
        run_row=run_row,
        run=getattr(work, "run", None),
        plan=work.plan,
        resources=SimpleNamespace(
            report=SimpleNamespace(
                model_dump=lambda **_: {**deepcopy(report), "checked_at": clock[0].isoformat()}
            ),
            sample_usage=[],
        ),
    )
    monkeypatch.setattr(service, "now", lambda: clock[0])
    monkeypatch.setattr(service, "_load", lambda *_: bound)
    monkeypatch.setattr(service, "_guards", lambda *_: None)
    monkeypatch.setattr(service, "_new_write", lambda *_: None)
    monkeypatch.setattr(service, "_promise", lambda *_: None)
    monkeypatch.setattr(
        service.physical,
        "_request_view",
        lambda *_: {
            "id": "fixed-request-version",
            "previous_request_id": "older-fixed-request-version",
            "previous_revision": work.request.revision - 1,
            "reason": "Saved earlier reason",
            "created_at": (AT - timedelta(minutes=1)).isoformat(),
            "sha256": "c" * 64,
            "zero_occupancy": True,
            "request_snapshot": work.request.model_dump(mode="json"),
        },
    )
    monkeypatch.setattr(service, "_kernel", lambda *args, **kwargs: launch(work, at=clock[0]))
    command = SimpleNamespace(operation=operation, command_id=uuid4())
    return lambda: service.preview_view(None, ctx, command, product, payload), clock, report


@pytest.mark.parametrize(
    "operation,new_version,zero_occupancy",
    [
        ("test.run.plan", False, True),
        ("verification.schedule.promise", True, True),
        ("test.run.start", True, False),
    ],
)
def test_reviewed_request_metadata_and_occupancy_match_the_proposed_version(
    work, monkeypatch, operation, new_version, zero_occupancy
):
    preview, _, _ = preview_setup(work, monkeypatch, operation)
    result = preview()
    before, after = result["before"]["request"], result["after"]["request"]
    assert after["zero_occupancy"] is zero_occupancy
    if new_version:
        assert after["id"] is None and after["sha256"] is None
        assert after["created_at"] is None
        assert after["reason"] == "Explicit newly reviewed version"
        assert after["previous_request_id"] == before["id"]
        assert after["previous_revision"] == work.request.revision
    else:
        for field in (
            "id",
            "sha256",
            "created_at",
            "reason",
            "previous_request_id",
            "previous_revision",
        ):
            assert after[field] == before[field]
    if operation == "test.run.start":
        assert after["status"] == "executing"
        assert result["after"]["run"]["zero_occupancy"] is False
        assert result["after"]["occupancy_effect"] == "stage_formal_and_sample_use_in_caller_uow"
    else:
        assert result["after"]["occupancy_effect"] == "none"


def test_material_preview_stable_across_current_server_report_clocks(work, monkeypatch):
    preview, clock, _ = preview_setup(work, monkeypatch)
    first = preview()
    clock[0] += timedelta(seconds=30)
    second = preview()
    assert digest(first) == digest(second)
    report = first["resource_report"]
    assert report["checked_at"] is None
    assert report["checked_at_basis"] == "server_revalidates_on_execute"
    assert report["input_digest"] == "a" * 64 and report["fixed_resources"][0]["epoch"] == 4


@pytest.mark.parametrize("field", ["input_digest", "conditions", "status", "fixed_resources"])
def test_material_preview_still_binds_complete_facts_checks_and_occupancy_epochs(
    work, monkeypatch, field
):
    preview, clock, report = preview_setup(work, monkeypatch)
    first = preview()
    report[field] = {
        "input_digest": "b" * 64,
        "conditions": ["A new condition"],
        "status": "UNKNOWN",
        "fixed_resources": [{"id": "fixed-resource", "epoch": 5}],
    }[field]
    clock[0] += timedelta(seconds=30)
    assert digest(first) != digest(preview())


@pytest.mark.parametrize(
    "field", ["window", "executor_id", "equipment", "calibration", "environment", "conditions"]
)
def test_every_fixed_plan_field_still_participates_in_binding_comparison(work, field):
    declared = binding(work)
    raw = work.plan.model_dump(mode="json")
    if field == "window":
        raw[field]["finish"] = (work.plan.window.finish + timedelta(minutes=1)).isoformat()
    elif field == "executor_id":
        raw[field] = str(uuid4())
    elif field in {"equipment", "calibration"}:
        raw[field]["line"] = 2
    else:
        raw[field] = "A different fixed value"
    assert service._fixed_plan(declared) != service._fixed_plan(ExecutionPlan.model_validate(raw))


@pytest.mark.parametrize(
    "operation,expected",
    [("plan", "test_run"), ("promise", "verification_request"), ("start", "test_run")],
)
def test_replay_subject_family_is_version_row_not_generic_lifecycle(work, operation, expected):
    value = public_plan(work)
    if operation != "plan":
        cls = service.PromisePayload if operation == "promise" else StartPayload
        value = cls(
            request_id=work.request.id,
            expected_request_revision=1,
            run_id=work.run_id,
            expected_run_revision=1,
            expected_plan_sha256="a" * 64,
            at=EventTime(occurred_at=AT, original_timezone="UTC", source=work.source),
            reason="Synthetic fixed promise",
        )
    assert service.replay_subject_type(value) == expected


def test_snapshot_hash_and_execution_conditions_are_exact(work):
    planned(work)
    row = SimpleNamespace(
        run_snapshot=work.run.model_dump(mode="json"),
        execution_plan=work.plan.model_dump(mode="json"),
        snapshot_sha256=digest(work.run.model_dump(mode="json")),
        plan_sha256=digest(work.plan.model_dump(mode="json")),
        run_id=work.run.id,
        revision=1,
        request_id=work.request.id,
        request_revision=work.run.request_revision,
        tenant_id=work.request.scope.tenant_id,
        product_id=work.request.scope.product_id,
        project_id=work.request.scope.project_id,
        build_id=work.request.build.id,
        build_revision=1,
        status="planned",
    )
    assert service._snapshot(row)[0] == work.run
    row.execution_plan = {**row.execution_plan, "conditions": "tampered"}
    with pytest.raises(DomainError) as error:
        service._snapshot(row)
    assert error.value.reason == "INTEGRITY_MISMATCH"


@pytest.mark.parametrize("source_time", ["iso", "z", "offset"])
def test_event_checks_current_exact_artifact_and_whole_fixed_json(work, monkeypatch, source_time):
    import json

    at = work.plan.window.start
    reference = work.plan.equipment.model_dump(mode="json")
    expected = {
        "request_id": str(work.request.id),
        "run_id": str(work.run_id),
        "purpose": work.request.purpose,
        "operation": "test.run.start",
        "occurred_at": at.isoformat(),
        "executor_id": str(work.actor),
    }
    if source_time == "z":
        expected["occurred_at"] = at.isoformat().replace("+00:00", "Z")
    elif source_time == "offset":
        from datetime import timezone

        expected["occurred_at"] = at.astimezone(timezone(timedelta(hours=-7))).isoformat()
    source = SimpleNamespace(content=json.dumps(expected))
    calls = []
    monkeypatch.setattr(service, "source_for", lambda *args: calls.append(args) or source)
    monkeypatch.setattr(service, "now", lambda: at)
    payload = StartPayload(
        request_id=work.request.id,
        expected_request_revision=1,
        run_id=work.run_id,
        expected_run_revision=1,
        expected_plan_sha256="a" * 64,
        at=EventTime(
            occurred_at=at,
            original_timezone="UTC",
            source=service.physical.event_source(work.plan.equipment),
        ),
        reason="Synthetic exact actual event",
    )
    ctx = Context(work.request.scope.tenant_id, work.actor, work.actor)
    service._event(
        None,
        ctx,
        work.request.scope.product_id,
        work.request,
        work.plan,
        payload,
        [reference],
        actual=True,
    )
    assert len(calls) == 1
    source.content = json.dumps({**expected, "qualified": True})
    with pytest.raises(DomainError) as error:
        service._event(
            None,
            ctx,
            work.request.scope.product_id,
            work.request,
            work.plan,
            payload,
            [reference],
            actual=True,
        )
    assert error.value.reason == "INVALID_EVENT_EVIDENCE"


@pytest.mark.parametrize("invalid", ["naive", "duplicate", "missing", "extra"])
def test_event_rejects_ambiguous_or_unaware_source_clock(work, monkeypatch, invalid):
    import json

    at = work.plan.window.start
    event = {
        "request_id": str(work.request.id),
        "run_id": str(work.run_id),
        "purpose": work.request.purpose,
        "operation": "test.run.start",
        "occurred_at": at.isoformat(),
        "executor_id": str(work.actor),
    }
    if invalid == "naive":
        event["occurred_at"] = at.replace(tzinfo=None).isoformat()
    elif invalid == "missing":
        event.pop("executor_id")
    elif invalid == "extra":
        event["qualified"] = True
    encoded = json.dumps(event)
    if invalid == "duplicate":
        encoded = encoded[:-1] + ', "request_id": ' + json.dumps(str(work.request.id)) + "}"
    monkeypatch.setattr(service, "source_for", lambda *_: SimpleNamespace(content=encoded))
    monkeypatch.setattr(service, "now", lambda: at)
    payload = StartPayload(
        request_id=work.request.id,
        expected_request_revision=1,
        run_id=work.run_id,
        expected_run_revision=1,
        expected_plan_sha256="a" * 64,
        at=EventTime(
            occurred_at=at,
            original_timezone="UTC",
            source=service.physical.event_source(work.plan.equipment),
        ),
        reason="Synthetic exact actual event",
    )
    ctx = Context(work.request.scope.tenant_id, work.actor, work.actor)
    with pytest.raises(DomainError) as error:
        service._event(
            None,
            ctx,
            work.request.scope.product_id,
            work.request,
            work.plan,
            payload,
            [work.plan.equipment.model_dump(mode="json")],
            actual=True,
        )
    assert error.value.reason == "INVALID_EVENT_EVIDENCE"


def test_inputs_return_complete_sources_and_never_call_apply_or_effect(work, monkeypatch):
    from pdos_next.contracts import Command

    payload = public_plan(work)
    ctx = Context(work.request.scope.tenant_id, work.actor, work.actor)
    product = SimpleNamespace(id=work.request.scope.product_id, revision=1)
    reads = [{"artifact_id": str(work.source.id), "expected_revision": 1}]
    bound = SimpleNamespace(
        physical=SimpleNamespace(authority={"authorized": False}, reads=reads),
        binding=SimpleNamespace(model_dump=lambda **_: {"run_id": str(work.run_id)}),
        resources=SimpleNamespace(
            report=SimpleNamespace(model_dump=lambda **_: {"status": "UNKNOWN"})
        ),
    )
    monkeypatch.setattr(service, "_load", lambda *args, **kw: bound)
    monkeypatch.setattr(
        service,
        "_guards",
        lambda *_: (_ for _ in ()).throw(
            DomainError("QUALIFICATION_REQUIRED", "Explicit unknown qualification", 403)
        ),
    )
    monkeypatch.setattr(service, "apply", lambda *_: pytest.fail("read-only inputs invoked apply"))
    s = SimpleNamespace(scalar=lambda _: product)
    command = Command(
        command_id=uuid4(),
        idempotency_key="read-only-input-test",
        operation="test.run.plan",
        category_id=uuid4(),
        product_id=product.id,
        expected_revision=1,
        payload=payload.model_dump(mode="json"),
    )
    result = service.inputs(s, ctx, product.id, command)
    assert not result["allowed"] and result["required_source_read_set"] == reads
    assert result["blockers"][0]["code"] == "QUALIFICATION_REQUIRED"


def test_scoped_get_checks_authoritative_linked_reads_before_queries(work, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "_human", lambda *_: None)
    monkeypatch.setattr(
        service.front, "_build", lambda *_: SimpleNamespace(id=work.request.build.id)
    )
    monkeypatch.setattr(
        service.front, "_linked", lambda *_: (None, None, None, ["fixed-linked-reads"])
    )

    def guard(*args):
        calls.append(args[-1])
        raise DomainError("SOURCE_UNAVAILABLE", "Authoritative linked source withdrawn")

    monkeypatch.setattr(service, "_sources", guard)
    s = SimpleNamespace(
        scalar=lambda _: SimpleNamespace(
            id=work.request.scope.product_id, tenant_id=work.request.scope.tenant_id
        )
    )
    ctx = Context(work.request.scope.tenant_id, work.actor, work.actor)
    with pytest.raises(DomainError) as error:
        service.list_launch(s, ctx, work.request.scope.product_id, build_id=work.request.build.id)
    assert error.value.reason == "SOURCE_UNAVAILABLE" and calls == [["fixed-linked-reads"]]


@pytest.mark.parametrize("mutate", ["expired", "unqualified", "wrong_subject"])
def test_host_current_qualification_guard_precedes_physical_and_effect(work, monkeypatch, mutate):
    authority = {
        "authorized": True,
        "qualified": True,
        "subject_id": str(work.actor),
        "roles": ["quality"],
        "valid_until": (AT + timedelta(minutes=1)).isoformat(),
    }
    if mutate == "expired":
        authority["valid_until"] = AT.isoformat()
    elif mutate == "unqualified":
        authority["qualified"] = None
    else:
        authority["subject_id"] = str(uuid4())
    monkeypatch.setattr(service, "now", lambda: AT)
    monkeypatch.setattr(service.physical, "_execution", lambda *_: pytest.fail("guard skipped"))
    bound = SimpleNamespace(physical=SimpleNamespace(authority=authority))
    ctx = Context(work.request.scope.tenant_id, work.actor, work.actor)
    with pytest.raises(DomainError) as error:
        service._guards(None, ctx, None, None, public_plan(work), bound)
    assert error.value.reason == "QUALIFICATION_REQUIRED"


@pytest.mark.parametrize("borrowed", [False, True])
def test_first_request_promise_cannot_authorize_a_different_run(work, monkeypatch, borrowed):
    promised(work)
    first_run_id = work.run.id
    second_run_id = uuid4()
    request_row = SimpleNamespace(id=uuid4(), revision=work.request.revision, status="executing")
    run_row = SimpleNamespace(id=uuid4(), revision=1, status="planned")
    bound = SimpleNamespace(
        physical=SimpleNamespace(previous=request_row, base=work.request),
        run_row=run_row,
        plan=work.plan,
    )
    payload = StartPayload(
        request_id=work.request.id,
        expected_request_revision=request_row.revision,
        run_id=second_run_id,
        expected_run_revision=1,
        expected_plan_sha256=digest(work.plan.model_dump(mode="json")),
        at=EventTime(
            occurred_at=work.plan.window.start, original_timezone="UTC", source=work.source
        ),
        reason="Synthetic second Run cannot borrow the first promise",
    )
    checked = []

    def promise_lookup(session, context, product_id, run_id):
        checked.append(run_id)
        return (
            SimpleNamespace(
                request_id=work.request.id,
                run_version_id=uuid4(),
                input_snapshot={"expected_plan_sha256": payload.expected_plan_sha256},
            )
            if borrowed
            else None
        )

    monkeypatch.setattr(service.front, "_current", lambda *args, **kw: (object(), request_row))
    monkeypatch.setattr(service, "_current", lambda *args, **kw: (object(), run_row))
    monkeypatch.setattr(service, "_promise", promise_lookup)
    monkeypatch.setattr(service, "now", lambda: work.plan.window.start + timedelta(seconds=1))
    assert work.request.timeline.promised_start is not None and second_run_id != first_run_id
    with pytest.raises(DomainError) as error:
        service._new_write(
            SimpleNamespace(info={}),
            SimpleNamespace(),
            SimpleNamespace(expected_revision=1),
            SimpleNamespace(id=work.request.scope.product_id, revision=1),
            payload,
            bound,
        )
    assert error.value.reason == "INVALID_STATE"
    assert checked == [second_run_id]
