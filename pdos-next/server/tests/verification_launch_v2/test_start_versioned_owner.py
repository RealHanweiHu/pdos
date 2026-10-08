"""Complete DTO and UOW tests with explicit SQL/source/qualification substitutes.

These tests do not claim actual PG atomicity, source bytes or qualification.
"""

# ruff: noqa: F811 -- imported fixture names are the pytest registration.
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from test_fingerprint_compatibility import materials  # noqa: F401

from pdos_next.domain.test_resources import service as codec
from pdos_next.domain.test_resources import service as resources
from pdos_next.domain.test_resources.schemas import TestReservationResult as Result
from pdos_next.domain.verification_launch import service as launch
from pdos_next.errors import DomainError
from pdos_next.service import Context, digest


def uid(n):
    return UUID(int=n)


@pytest.fixture
def work(materials, monkeypatch):
    old, _, fixed = materials
    material = deepcopy(old)
    material["issuer"] = {
        "key": fixed.issuer_key,
        "scope": {
            "tenant_id": fixed.tenant_id,
            "product_id": fixed.product_id,
            "project_id": fixed.project_id,
        },
        "version": fixed.issuer_version,
        "nature": "synthetic",
        "epoch": fixed.issuer_epoch,
    }
    material["issuer_epochs"] = {fixed.issuer_key: fixed.issuer_epoch}
    proof = codec._stored_fingerprint_v2(material)
    binding = old["binding"]
    result = Result(
        owner_run_id=binding.run_id,
        reservation_id=binding.run_id,
        occupancy_ids=(uid(41),),
        sample_usage_ids=(uid(42),),
        facts_revision=proof["facts_revision"],
        replayed=False,
    )
    raw = {
        "plan_binding": binding.model_dump(mode="json"),
        "reservation": result.model_dump(mode="json"),
        "resource_facts_revision": proof["facts_revision"],
        "resource_fingerprint_version": codec._FINGERPRINT_V2,
        "resource_dependency_proof": deepcopy(proof),
    }
    original = SimpleNamespace(
        input_snapshot=raw,
        operation="test.run.start",
        project_id=binding.project_id,
        build_id=binding.build_id,
        run_id=binding.run_id,
        intent_digest="original-intent",
        writer_id=binding.executor_id,
        visibility="product",
    )
    reservation = SimpleNamespace(
        id=binding.run_id,
        tenant_id=fixed.tenant_id,
        product_id=fixed.product_id,
        project_id=binding.project_id,
        build_id=binding.build_id,
        run_id=binding.run_id,
        owner_id=binding.executor_id,
        visibility="product",
        state="formal",
        fact_id=uid(13),
        fact_revision=1,
        intent_digest=original.intent_digest,
        binding=raw["plan_binding"],
        facts_revision=proof["facts_revision"],
        fingerprint_version=codec._FINGERPRINT_V2,
        dependency_proof=deepcopy(proof),
    )
    s = Session(bind=create_engine("sqlite://"))
    s.begin()
    ctx = Context(fixed.tenant_id, binding.executor_id, binding.executor_id)
    clock = [datetime(2026, 10, 3, 12, 1, tzinfo=UTC)]
    bound = SimpleNamespace(
        fingerprint_version=codec._FINGERPRINT_V2,
        dependency_proof=deepcopy(proof),
        reserved_dependency_proof=deepcopy(proof),
        reservation=result,
        binding=binding,
        resources=SimpleNamespace(
            facts_revision=proof["facts_revision"], valid_until=clock[0] + timedelta(hours=1)
        ),
        physical=SimpleNamespace(
            authority={"valid_until": (clock[0] + timedelta(hours=1)).isoformat()},
            visibility="product",
        ),
        plan=SimpleNamespace(resource_fact_id=uid(13), expected_resource_fact_revision=1),
        fingerprint_runtime=None,
        caller_uow=None,
        caller_digest=None,
    )
    payload = SimpleNamespace(run_id=binding.run_id)
    command = SimpleNamespace(operation="test.run.start")
    monkeypatch.setattr(resources, "_reservation", lambda *args: reservation)
    monkeypatch.setattr(launch, "_read_evidence", lambda *args: "current")
    monkeypatch.setattr(launch, "_intent", lambda *args: "original-intent")
    monkeypatch.setattr(launch, "now", lambda: clock[0])
    yield SimpleNamespace(
        s=s,
        ctx=ctx,
        pid=fixed.product_id,
        proof=proof,
        binding=binding,
        original=original,
        row=reservation,
        result=result,
        bound=bound,
        payload=payload,
        command=command,
        clock=clock,
    )
    s.close()


def test_immutable_start_actual_owner_dispatch_and_deepcopy(work):
    w = work
    version, proof = launch._saved_start_fingerprint(w.s, w.ctx, w.pid, w.original)
    assert version == codec._FINGERPRINT_V2 and proof == w.proof
    proof["material"]["issuer"]["key"] = "caller-mutates-copy"
    assert w.original.input_snapshot["resource_dependency_proof"] == w.proof
    assert w.row.dependency_proof == w.proof


def test_new_start_checks_complete_same_uow_row(work):
    w = work
    saved = launch._start_reservation_proof(w.s, w.ctx, w.command, w.pid, w.payload, w.bound)
    assert saved == w.proof
    saved["material"]["issuer"]["key"] = "mutation"
    assert w.row.dependency_proof == w.proof and w.bound.dependency_proof == w.proof
    assert not w.s.new and not w.s.dirty and not w.s.deleted


@pytest.mark.parametrize("key", ["resource_fingerprint_version", "resource_dependency_proof"])
def test_explicit_partial_start_never_uses_v1(work, key):
    w = work
    del w.original.input_snapshot[key]
    with pytest.raises(DomainError) as exc:
        launch._saved_start_fingerprint(w.s, w.ctx, w.pid, w.original)
    assert exc.value.code == "RESOURCE_FINGERPRINT_VERSION_UNSUPPORTED"


@pytest.mark.parametrize("value", [None, "test-resource-dependency-v1", "future-v3", True, 2])
def test_explicit_version_never_guessed_or_downgraded(work, value):
    w = work
    w.original.input_snapshot["resource_fingerprint_version"] = value
    with pytest.raises(DomainError) as exc:
        launch._saved_start_fingerprint(w.s, w.ctx, w.pid, w.original)
    assert exc.value.code == "RESOURCE_FINGERPRINT_VERSION_UNSUPPORTED"


def test_only_two_absent_start_keys_and_two_null_owner_cols_are_legacy(work):
    w = work
    del w.original.input_snapshot["resource_fingerprint_version"]
    del w.original.input_snapshot["resource_dependency_proof"]
    w.row.fingerprint_version, w.row.dependency_proof = None, None
    assert launch._saved_start_fingerprint(w.s, w.ctx, w.pid, w.original) == (
        codec._FINGERPRINT_V1,
        None,
    )


@pytest.mark.parametrize(
    "column,value",
    [("fingerprint_version", "test-resource-dependency-v2"), ("dependency_proof", {})],
)
def test_unversioned_start_cannot_infer_owner_version(work, column, value):
    w = work
    del w.original.input_snapshot["resource_fingerprint_version"]
    del w.original.input_snapshot["resource_dependency_proof"]
    w.row.fingerprint_version, w.row.dependency_proof = None, None
    setattr(w.row, column, value)
    with pytest.raises(DomainError) as exc:
        launch._saved_start_fingerprint(w.s, w.ctx, w.pid, w.original)
    assert exc.value.code == "RESOURCE_FINGERPRINT_MATERIAL_INVALID"


@pytest.mark.parametrize(
    "owner,value",
    [
        ("tenant_id", uid(91)),
        ("product_id", uid(92)),
        ("project_id", uid(93)),
        ("build_id", uid(94)),
        ("run_id", uid(95)),
        ("intent_digest", "another"),
        ("id", uid(96)),
        ("facts_revision", "d" * 64),
        ("binding", {}),
    ],
)
def test_saved_start_wrong_actual_owner_or_triple_fp_rejected(work, owner, value):
    w = work
    setattr(w.row, owner, value)
    with pytest.raises(DomainError) as exc:
        launch._saved_start_fingerprint(w.s, w.ctx, w.pid, w.original)
    assert exc.value.code == "RUN_RESERVATION_MISSING"


@pytest.mark.parametrize("position", ["start", "result", "material", "column"])
def test_independent_start_result_kernel_material_fingerprint_cannot_diverge(work, position):
    w = work
    if position == "start":
        w.original.input_snapshot["resource_facts_revision"] = "d" * 64
    elif position == "result":
        w.original.input_snapshot["reservation"]["facts_revision"] = "d" * 64
    elif position == "material":
        w.original.input_snapshot["resource_dependency_proof"]["facts_revision"] = "d" * 64
    else:
        w.row.dependency_proof["facts_revision"] = "d" * 64
    with pytest.raises(DomainError):
        launch._saved_start_fingerprint(w.s, w.ctx, w.pid, w.original)


@pytest.mark.parametrize("position", ["preview", "stage", "actual"])
def test_resealed_but_different_complete_material_rejected(work, position):
    w = work
    changed = deepcopy(w.proof["material"])
    changed["epoch"] += 1
    other = codec._stored_fingerprint_v2(changed)
    if position == "preview":
        w.bound.dependency_proof = other
    elif position == "stage":
        w.bound.reserved_dependency_proof = other
    else:
        w.row.dependency_proof = other
    with pytest.raises(DomainError) as exc:
        launch._start_reservation_proof(w.s, w.ctx, w.command, w.pid, w.payload, w.bound)
    assert exc.value.code == "INTEGRITY_MISMATCH"


@pytest.mark.parametrize(
    "field,value",
    [
        ("replayed", True),
        ("facts_revision", "b" * 64),
        ("owner_run_id", uid(97)),
        ("reservation_id", uid(98)),
    ],
)
def test_new_start_cannot_replay_partial_or_save_another_result(work, field, value):
    w = work
    w.bound.reservation = w.result.model_copy(update={field: value})
    with pytest.raises(DomainError):
        launch._start_reservation_proof(w.s, w.ctx, w.command, w.pid, w.payload, w.bound)


@pytest.mark.parametrize("sink", [None, (), {}, [], [{}, {}]])
def test_collector_requires_exact_single_fresh_producer_result(sink):
    with pytest.raises(DomainError) as exc:
        launch._collected_resource_proof(resources, sink, "b" * 64)
    assert exc.value.code == "RESOURCE_FINGERPRINT_MATERIAL_INVALID"


def test_collector_full_codec_and_expected_digest_are_both_checked(work):
    w = work
    assert (
        launch._collected_resource_proof(resources, [w.proof], w.proof["facts_revision"]) == w.proof
    )
    with pytest.raises(DomainError) as exc:
        launch._collected_resource_proof(resources, [w.proof], "b" * 64)
    assert exc.value.code == "RESOURCE_FACTS_CHANGED"


def capture(w, monkeypatch):
    from pdos_next.domain.capa_effectiveness.fact_atom_storage import _uow

    w.bound.fingerprint_runtime = object()
    w.bound.caller_uow = _uow(w.s)
    w.bound.caller_digest = digest(vars(w.ctx))
    monkeypatch.setattr(resources, "_same_fingerprint_runtime", lambda *args: None, raising=False)


def test_real_session_root_and_savepoint_same_owner_close_success(work, monkeypatch):
    w = work
    with w.s.begin_nested():
        capture(w, monkeypatch)
        launch._close_start_boundary(w.s, w.ctx, w.bound)
    assert w.s.in_transaction()


@pytest.mark.parametrize("change", ["nested", "root", "bind", "caller"])
def test_root_savepoint_engine_and_actual_caller_changes_fail_closed(work, monkeypatch, change):
    w = work
    capture(w, monkeypatch)
    if change == "nested":
        w.s.begin_nested()
    elif change == "root":
        w.s.rollback()
        w.s.begin()
    elif change == "bind":
        w.s.bind = create_engine("sqlite://")
    else:
        object.__setattr__(w.ctx, "requester_id", uid(99))
    with pytest.raises(DomainError) as exc:
        launch._close_start_boundary(w.s, w.ctx, w.bound)
    assert exc.value.code == "FACT_CALLER_UOW_CHANGED"


@pytest.mark.parametrize("deadline", ["resource", "authority"])
def test_actual_clock_final_expiry_after_all_owner_io_rejects(work, monkeypatch, deadline):
    w = work
    capture(w, monkeypatch)
    if deadline == "resource":
        w.bound.resources.valid_until = w.clock[0]
    else:
        w.bound.physical.authority["valid_until"] = w.clock[0].isoformat()
    with pytest.raises(DomainError) as exc:
        launch._close_start_boundary(w.s, w.ctx, w.bound)
    assert exc.value.code == "SOURCE_STALE"


def test_unrelated_registry_mutation_during_whole_launch_owner_io_rejected(work, monkeypatch):
    w = work
    capture(w, monkeypatch)

    def changed(*args):
        raise DomainError("SOURCE_STALE", "Explicit runtime owner substitution")

    monkeypatch.setattr(resources, "_same_fingerprint_runtime", changed)
    with pytest.raises(DomainError) as exc:
        launch._close_start_boundary(w.s, w.ctx, w.bound)
    assert exc.value.code == "SOURCE_STALE"


def owner_load(w, monkeypatch, *, original=False, verify_event=True):
    from pdos_next.contracts import Command
    from pdos_next.domain.verification_launch.models import VerificationLaunchFact
    from pdos_next.domain.verification_launch.schemas import ExecutionPlan, StartPayload
    from pdos_next.schemas.verification.contracts import Coverage

    binding = w.binding
    plan = ExecutionPlan(
        window=binding.window,
        executor_id=binding.executor_id,
        equipment=binding.equipment,
        calibration=binding.calibration,
        environment=binding.environment,
        conditions=binding.conditions,
        resource_fact_id=uid(13),
        expected_resource_fact_revision=1,
    )
    payload = StartPayload(
        request_id=binding.request_id,
        expected_request_revision=5,
        run_id=binding.run_id,
        expected_run_revision=1,
        expected_plan_sha256=digest(plan.model_dump(mode="json")),
        at={
            "occurred_at": binding.window.start,
            "original_timezone": "UTC",
            "source": {"id": uid(30), "revision": 1, "kind": "artifact", "position": "line:1"},
        },
        reason="Explicit isolated owner substitute",
    )
    command = Command(
        command_id=uid(81),
        idempotency_key="isolated-start-material-owner",
        operation="test.run.start",
        product_id=w.pid,
        expected_revision=1,
        source_read_set=[{"artifact_id": uid(30), "expected_revision": 1}],
        payload=payload.model_dump(mode="json"),
    )
    product = SimpleNamespace(id=w.pid, tenant_id=w.ctx.tenant_id)
    build = SimpleNamespace(id=binding.build_id, project_id=binding.project_id)
    request = SimpleNamespace(
        id=binding.request_id,
        build=build,
        scope=SimpleNamespace(project_id=binding.project_id),
        purpose=binding.purpose,
        samples=[binding.pairs[0].sample],
    )
    prior = SimpleNamespace(
        id=binding.accepted_request_id,
        revision=5,
        sources=[],
        required_source_read_set=[],
        visibility="product",
    )
    run_row = SimpleNamespace(
        input_snapshot={"plan_binding": binding.model_dump(mode="json")},
        sources=[],
        required_source_read_set=[],
        plan_sha256=payload.expected_plan_sha256,
    )
    fixed_run = SimpleNamespace(
        request_id=request.id,
        build=build,
        coverage=[Coverage(sample_id=binding.pairs[0].sample.id, item_id=binding.pairs[0].item_id)],
    )
    fact = SimpleNamespace(
        revision=1,
        binding=binding.model_dump(mode="json"),
        sources=[],
        required_source_read_set=[],
        visibility="product",
    )
    method = SimpleNamespace(
        id=binding.pairs[0].method_id,
        revision=1,
        snapshot_sha256=binding.pairs[0].method_sha256,
        sources=[],
        required_source_read_set=[],
    )
    authority = {
        "valid_until": (w.clock[0] + timedelta(hours=1)).isoformat(),
        "required_source_read_set": [],
    }
    original_fact = (
        SimpleNamespace(intent_digest=w.original.intent_digest, run_version_id=uid(75))
        if original
        else None
    )
    calls = []
    monkeypatch.setattr(launch, "_human", lambda *a, **k: None)
    monkeypatch.setattr(launch.front, "_version", lambda *a: prior)
    monkeypatch.setattr(launch.front, "_snapshot", lambda *a: request)
    monkeypatch.setattr(launch.front, "_current", lambda *a, **k: (None, None))
    monkeypatch.setattr(launch, "_current", lambda *a, **k: (None, None))
    monkeypatch.setattr(launch.front, "_build", lambda *a: build)
    monkeypatch.setattr(launch.front, "_linked", lambda *a: (None, None, None, []))
    monkeypatch.setattr(launch.front, "_assess", lambda *a, **k: authority)
    monkeypatch.setattr(launch, "_version", lambda *a: run_row)
    monkeypatch.setattr(launch, "_snapshot", lambda *a: (fixed_run, plan))
    monkeypatch.setattr(launch, "_full_coverage", lambda *a: None)
    monkeypatch.setattr(
        launch, "_row", lambda *a: w.original if a[3].__name__ == "VerificationRunVersion" else fact
    )
    monkeypatch.setattr(resources, "lock_binding_assets", lambda *a, **k: None)
    monkeypatch.setattr(
        launch.physical,
        "_inspect",
        lambda *a, **k: {
            "source_refs": [],
            "required_source_read_set": [],
            "visibility": "product",
        },
    )
    monkeypatch.setattr(launch.physical, "_method_pointer", lambda *a: (None, method))
    monkeypatch.setattr(launch.front, "_row", lambda *a: prior)
    monkeypatch.setattr(launch, "_binding", lambda *a: binding)
    monkeypatch.setattr(launch, "_event", lambda *a, **k: calls.append(("event", k)))
    monkeypatch.setattr(launch.physical, "_basis", lambda *a: ({}, False))
    monkeypatch.setattr(resources, "_fingerprint_runtime", lambda *a: object(), raising=False)
    monkeypatch.setattr(resources, "_same_fingerprint_runtime", lambda *a: None, raising=False)
    monkeypatch.setattr(
        w.s,
        "scalar",
        lambda query: (
            original_fact
            if query.column_descriptions[0]["entity"] is VerificationLaunchFact
            else None
        ),
    )

    def bundle(*args, **kwargs):
        calls.append(("load", kwargs.copy()))
        if "_fingerprint_collector" in kwargs:
            kwargs["_fingerprint_collector"].append(deepcopy(w.proof))
        return SimpleNamespace(
            binding=binding,
            facts_revision=w.proof["facts_revision"],
            required_source_read_set=(),
            valid_until=w.clock[0] + timedelta(hours=1),
        )

    monkeypatch.setattr(resources, "load_bundle", bundle)
    bound = launch._load(w.s, w.ctx, command, product, payload, verify_event=verify_event)
    return bound, calls


def test_actual_loader_new_start_chooses_v2_before_source_owner_io_without_effects(
    work, monkeypatch
):
    bound, calls = owner_load(work, monkeypatch)
    resource_call = next(value for kind, value in calls if kind == "load")
    assert resource_call["_fingerprint_version"] == codec._FINGERPRINT_V2
    assert resource_call["_fingerprint_collector"] == [work.proof]
    assert resource_call["write"] is False and "own_intent" not in resource_call
    assert resource_call["verified_actual_start"].occurred_at == work.binding.window.start
    assert bound.dependency_proof == work.proof and bound.fingerprint_runtime is not None
    assert not work.s.new and not work.s.dirty and not work.s.deleted


def test_read_only_capability_still_uses_new_start_v2_but_no_actual_event_claim(work, monkeypatch):
    bound, calls = owner_load(work, monkeypatch, verify_event=False)
    resource_call = next(value for kind, value in calls if kind == "load")
    assert resource_call["_fingerprint_version"] == codec._FINGERPRINT_V2
    assert "verified_actual_start" not in resource_call
    assert not any(kind == "event" for kind, value in calls)
    assert bound.dependency_proof == work.proof and not work.s.new


def test_actual_loader_saved_v2_owner_dispatch_preserves_exact_original_and_current_uow(
    work, monkeypatch
):
    bound, calls = owner_load(work, monkeypatch, original=True)
    resource_call = next(value for kind, value in calls if kind == "load")
    assert resource_call["_fingerprint_version"] == codec._FINGERPRINT_V2
    assert resource_call["own_intent"] == work.original.intent_digest
    assert bound.saved_start is work.original and bound.dependency_proof == work.proof
    assert bound.fingerprint_runtime is not None and not work.s.new


def test_actual_loader_unversioned_real_owner_keeps_v1_and_avoids_new_material_claim(
    work, monkeypatch
):
    w = work
    del w.original.input_snapshot["resource_fingerprint_version"]
    del w.original.input_snapshot["resource_dependency_proof"]
    w.row.fingerprint_version, w.row.dependency_proof = None, None
    bound, calls = owner_load(w, monkeypatch, original=True)
    resource_call = next(value for kind, value in calls if kind == "load")
    assert resource_call["_fingerprint_version"] == codec._FINGERPRINT_V1
    assert "_fingerprint_collector" not in resource_call
    assert bound.dependency_proof is None and bound.fingerprint_runtime is None
    assert not work.s.new


def record_work(w, monkeypatch):
    from pdos_next.domain.verification_launch.schemas import ExecutionPlan
    from pdos_next.schemas.verification.contracts import Scope, TimeFact
    from pdos_next.schemas.verification.contracts import TestRun as Run

    binding = w.binding
    scope = Scope(tenant_id=w.ctx.tenant_id, product_id=w.pid, project_id=binding.project_id)
    run = Run(
        id=binding.run_id,
        revision=2,
        scope=scope,
        request_id=binding.request_id,
        request_revision=5,
        build={
            "id": binding.build_id,
            "revision": 1,
            "product_id": w.pid,
            "project_id": binding.project_id,
            "engineering_configuration": {"id": uid(60), "revision": 1},
            "manufacturing_configuration": {"id": uid(61), "revision": 1},
        },
        items=[{"id": binding.pairs[0].item_id, "feature": "fixed", "sample_count": 1}],
        samples=[binding.pairs[0].sample],
        coverage=[{"sample_id": binding.pairs[0].sample.id, "item_id": binding.pairs[0].item_id}],
        status="running",
        actual_start=TimeFact(
            occurred_at=binding.window.start,
            received_at=binding.window.start,
            actor_id=binding.executor_id,
            original_timezone="UTC",
            source={"id": uid(30), "revision": 1, "kind": "artifact", "position": "line:1"},
        ),
    )
    previous = SimpleNamespace(id=uid(74), revision=5)
    w.bound.physical = SimpleNamespace(
        previous=previous,
        base=SimpleNamespace(id=binding.request_id),
        build=SimpleNamespace(id=binding.build_id, revision=1, project_id=binding.project_id),
        authority={"valid_until": (w.clock[0] + timedelta(hours=1)).isoformat()},
        references=[],
        reads=[],
        visibility="product",
    )
    w.bound.plan = ExecutionPlan(
        window=binding.window,
        executor_id=binding.executor_id,
        equipment=binding.equipment,
        calibration=binding.calibration,
        environment=binding.environment,
        conditions=binding.conditions,
        resource_fact_id=uid(13),
        expected_resource_fact_revision=1,
    )
    w.bound.run_row = SimpleNamespace(
        id=uid(73),
        request_version_id=uid(74),
        request_revision=5,
        input_snapshot={"plan_binding": binding.model_dump(mode="json")},
        owner_id=w.ctx.actor_id,
        revision=1,
    )
    w.bound.source_basis = {}
    mutation = SimpleNamespace(
        request=SimpleNamespace(
            revision=5,
            status="executing",
            timeline=SimpleNamespace(preliminary_result=None, final_result=None, disposed=None),
        ),
        run=run,
        events=[SimpleNamespace(model_dump=lambda **kwargs: {"type": "RunStarted"})],
    )
    pointer = SimpleNamespace(run_version_id=uid(73), run_revision=1)
    flushes = []
    monkeypatch.setattr(w.s, "flush", lambda *a, **k: flushes.append(len(w.s.new)))
    monkeypatch.setattr(launch, "semantic", lambda *args: {"explicit": "pure command substitute"})
    w.payload.reason = "Pure owner sequence; no common approval or actual SQL"
    return mutation, pointer, flushes


def test_actual_record_persists_same_proof_after_same_uow_resource_row_before_return(
    work, monkeypatch
):
    w = work
    mutation, pointer, flushes = record_work(w, monkeypatch)
    returned = launch._record(
        w.s,
        w.ctx,
        w.command,
        SimpleNamespace(id=w.pid),
        w.payload,
        w.bound,
        (None, pointer),
        mutation,
    )
    assert returned.input_snapshot["resource_dependency_proof"] == w.row.dependency_proof == w.proof
    assert returned.input_snapshot["resource_fingerprint_version"] == codec._FINGERPRINT_V2
    assert returned.input_snapshot["resource_facts_revision"] == w.result.facts_revision
    assert returned.input_snapshot["reservation"]["facts_revision"] == w.row.facts_revision
    assert len(w.s.new) == 2 and len(flushes) == 2
    assert pointer.run_version_id == returned.id and pointer.run_revision == 2
    assert w.bound.run_row.input_snapshot == {"plan_binding": w.binding.model_dump(mode="json")}
    assert w.row.dependency_proof == w.proof


def test_record_full_group_flush_io_registry_change_is_detected_before_owner_return(
    work, monkeypatch
):
    w = work
    mutation, pointer, flushes = record_work(w, monkeypatch)
    capture(w, monkeypatch)

    def changed(*args):
        assert len(flushes) == 2
        raise DomainError("SOURCE_STALE", "Explicit last-flush registry mutation")

    monkeypatch.setattr(resources, "_same_fingerprint_runtime", changed)
    with pytest.raises(DomainError) as exc:
        launch._record(
            w.s,
            w.ctx,
            w.command,
            SimpleNamespace(id=w.pid),
            w.payload,
            w.bound,
            (None, pointer),
            mutation,
        )
    assert exc.value.code == "SOURCE_STALE"
    # No connection was opened. The real common caller owns rollback of this staged UOW.
    assert len(w.s.new) == 2
    w.s.rollback()
    assert not w.s.new


def effect_rows(w, monkeypatch):
    from pdos_next.domain.build_operational_facts.models import ResourceOccupancy

    w.row.reservation = {"pure_substitute": "actual kernel JSON owner"}
    w.row.reservation_sha256 = digest(w.row.reservation)
    occupied = SimpleNamespace(
        id=uid(41),
        resource_id=uid(21),
        resource_revision=1,
        units=1,
        window_start=w.binding.window.start,
        window_finish=w.binding.window.finish,
    )
    sample = w.binding.pairs[0].sample
    usage = SimpleNamespace(
        id=uid(42),
        sample_id=sample.id,
        sample_revision=sample.revision,
        actual_configuration_id=sample.actual_configuration.id,
        actual_configuration_revision=sample.actual_configuration.revision,
        state="reserved",
        destructive=False,
        coverage=[],
        window_start=w.binding.window.start,
        window_finish=w.binding.window.finish,
    )
    monkeypatch.setattr(w.s, "scalar", lambda *a: w.row)
    monkeypatch.setattr(
        w.s,
        "scalars",
        lambda q: SimpleNamespace(
            all=lambda: (
                [occupied] if q.column_descriptions[0]["entity"] is ResourceOccupancy else [usage]
            )
        ),
    )
    monkeypatch.setattr(launch, "_version", lambda *args: w.original)
    return SimpleNamespace(
        operation="test.result.compute",
        run_id=w.binding.run_id,
        project_id=w.binding.project_id,
        build_id=w.binding.build_id,
        input_snapshot=deepcopy(w.original.input_snapshot),
    )


def test_real_saved_effect_reader_later_version_cannot_change_original_proof_identity(
    work, monkeypatch
):
    row = effect_rows(work, monkeypatch)
    effects = launch._saved_effects(work.s, work.ctx, work.pid, row)
    assert len(effects["occupancy"]) == 1 and len(effects["sample_usage"]) == 1
    assert effects["occupancy_evaluation"].endswith("current_qualification_not_evaluated")
    assert not work.s.new


@pytest.mark.parametrize(
    "field",
    ["resource_facts_revision", "resource_fingerprint_version", "resource_dependency_proof"],
)
def test_later_version_cannot_replace_v2_original_start_identity(work, monkeypatch, field):
    row = effect_rows(work, monkeypatch)
    row.input_snapshot[field] = None
    with pytest.raises(DomainError) as exc:
        launch._saved_effects(work.s, work.ctx, work.pid, row)
    assert exc.value.code == "RUN_START_PROOF_INVALID"


@pytest.mark.parametrize("field", ["resource_fingerprint_version", "resource_dependency_proof"])
def test_later_legacy_result_cannot_introduce_even_null_explicit_version(work, monkeypatch, field):
    w = work
    del w.original.input_snapshot["resource_fingerprint_version"]
    del w.original.input_snapshot["resource_dependency_proof"]
    w.row.fingerprint_version, w.row.dependency_proof = None, None
    row = effect_rows(w, monkeypatch)
    row.input_snapshot[field] = None
    with pytest.raises(DomainError) as exc:
        launch._saved_effects(w.s, w.ctx, w.pid, row)
    assert exc.value.code == "RUN_START_PROOF_INVALID"


@pytest.mark.parametrize(
    "owner,value",
    [
        ("owner_id", uid(95)),
        ("visibility", "private"),
        ("state", "released"),
        ("fact_id", uid(96)),
        ("fact_revision", 2),
    ],
)
def test_new_start_requires_actual_row_writer_visibility_formal_state_and_fixed_fact(
    work, owner, value
):
    w = work
    setattr(w.row, owner, value)
    with pytest.raises(DomainError) as exc:
        launch._start_reservation_proof(w.s, w.ctx, w.command, w.pid, w.payload, w.bound)
    assert exc.value.code == "INTEGRITY_MISMATCH"


def test_new_load_does_not_convert_unknown_qualification_into_clock_parse_error(work, monkeypatch):
    w = work
    from pdos_next.domain.capa_effectiveness.fact_atom_storage import _uow

    w.bound.fingerprint_runtime = object()
    w.bound.caller_uow, w.bound.caller_digest = _uow(w.s), digest(vars(w.ctx))
    w.bound.physical.authority["valid_until"] = None
    monkeypatch.setattr(resources, "_same_fingerprint_runtime", lambda *a: None, raising=False)
    launch._close_start_boundary(w.s, w.ctx, w.bound, check_deadlines=False)
    assert not w.s.new
