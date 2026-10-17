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
        visibility="category",
    )
    reservation = SimpleNamespace(
        id=binding.run_id,
        tenant_id=fixed.tenant_id,
        product_id=fixed.product_id,
        project_id=binding.project_id,
        build_id=binding.build_id,
        run_id=binding.run_id,
        owner_id=binding.executor_id,
        visibility="category",
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
    ctx = Context(fixed.tenant_id, binding.executor_id, binding.executor_id, category_id=uid(97))
    clock = [datetime(2026, 10, 3, 12, 1, tzinfo=UTC)]
    bound = SimpleNamespace(
        fingerprint_version=codec._FINGERPRINT_V2,
        dependency_proof=deepcopy(proof),
        reserved_dependency_proof=deepcopy(proof),
        reservation=result,
        binding=binding,
        resources=SimpleNamespace(
            facts_revision=proof["facts_revision"],
            valid_until=clock[0] + timedelta(hours=1),
            expiry_boundaries=(),
            authority_basis=None,
        ),
        physical=SimpleNamespace(
            authority=deepcopy(proof["material"]["authority"]),
            visibility="category",
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
    assert exc.value.reason == "RESOURCE_FINGERPRINT_VERSION_UNSUPPORTED"


@pytest.mark.parametrize("value", [None, "test-resource-dependency-v1", "future-v3", True, 2])
def test_explicit_version_never_guessed_or_downgraded(work, value):
    w = work
    w.original.input_snapshot["resource_fingerprint_version"] = value
    with pytest.raises(DomainError) as exc:
        launch._saved_start_fingerprint(w.s, w.ctx, w.pid, w.original)
    assert exc.value.reason == "RESOURCE_FINGERPRINT_VERSION_UNSUPPORTED"


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
    assert exc.value.reason == "RESOURCE_FINGERPRINT_MATERIAL_INVALID"


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
    assert exc.value.reason == "RUN_RESERVATION_MISSING"


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
    assert exc.value.reason == "INTEGRITY_MISMATCH"


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
    assert exc.value.reason == "RESOURCE_FINGERPRINT_MATERIAL_INVALID"


def test_collector_full_codec_and_expected_digest_are_both_checked(work):
    w = work
    assert (
        launch._collected_resource_proof(resources, [w.proof], w.proof["facts_revision"]) == w.proof
    )
    with pytest.raises(DomainError) as exc:
        launch._collected_resource_proof(resources, [w.proof], "b" * 64)
    assert exc.value.reason == "RESOURCE_FACTS_CHANGED"


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
    assert exc.value.reason == "FACT_CALLER_UOW_CHANGED"


@pytest.mark.parametrize("deadline", ["resource", "authority"])
def test_actual_clock_final_expiry_after_all_owner_io_rejects(work, monkeypatch, deadline):
    w = work
    capture(w, monkeypatch)
    if deadline == "resource":
        w.bound.resources.valid_until = w.clock[0]
    else:
        w.bound.physical.authority["fact_refs"][0]["valid_until"] = w.clock[0].isoformat()
    with pytest.raises(DomainError) as exc:
        launch._close_start_boundary(w.s, w.ctx, w.bound)
    assert exc.value.reason == "SOURCE_STALE"


def test_unrelated_registry_mutation_during_whole_launch_owner_io_rejected(work, monkeypatch):
    w = work
    capture(w, monkeypatch)

    def changed(*args):
        raise DomainError("SOURCE_STALE", "Explicit runtime owner substitution")

    monkeypatch.setattr(resources, "_same_fingerprint_runtime", changed)
    with pytest.raises(DomainError) as exc:
        launch._close_start_boundary(w.s, w.ctx, w.bound)
    assert exc.value.reason == "SOURCE_STALE"


def owner_load(w, monkeypatch, *, original=False, verify_event=True):
    """Real direct loader/UOW with explicit SQL, source and qualification transports."""
    from pdos_next import source_current
    from pdos_next.contracts import Command
    from pdos_next.domain.professional_authority import service as professional
    from pdos_next.domain.quality_execution import evidence
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
        reason="Explicit isolated direct-owner transports",
    )
    command = Command(
        command_id=uid(81),
        idempotency_key="isolated-start-material-owner",
        operation="test.run.start",
        category_id=w.ctx.category_id,
        product_id=w.pid,
        expected_revision=1,
        source_read_set=[{"artifact_id": uid(30), "expected_revision": 1}],
        payload=payload.model_dump(mode="json"),
    )
    product = SimpleNamespace(
        id=w.pid, tenant_id=w.ctx.tenant_id, category_id=w.ctx.category_id, revision=1
    )
    build = SimpleNamespace(id=binding.build_id, project_id=binding.project_id)
    request = SimpleNamespace(
        id=binding.request_id,
        build=build,
        purpose=binding.purpose,
        scope=SimpleNamespace(product_id=w.pid, project_id=binding.project_id),
        samples=[binding.pairs[0].sample],
        documents=[],
        items=[],
    )
    prior = SimpleNamespace(
        id=binding.accepted_request_id, revision=5, snapshot_sha256="a" * 64, visibility="category"
    )
    run_row = SimpleNamespace(
        id=uid(73),
        revision=1,
        snapshot_sha256="b" * 64,
        input_snapshot={"plan_binding": binding.model_dump(mode="json")},
        plan_sha256=payload.expected_plan_sha256,
    )
    fixed_run = SimpleNamespace(
        id=binding.run_id,
        revision=1,
        request_id=request.id,
        build=build,
        coverage=[Coverage(sample_id=binding.pairs[0].sample.id, item_id=binding.pairs[0].item_id)],
    )
    authority = deepcopy(w.proof["material"]["authority"])
    calls = []
    if not verify_event:
        w.s.info["read_snapshot"] = True
    monkeypatch.setattr(launch, "_human", lambda *a, **k: None)
    monkeypatch.setattr(launch, "require_access", lambda *a, **k: product)
    monkeypatch.setattr(launch.front, "_version", lambda *a: prior)
    monkeypatch.setattr(launch.front, "_snapshot", lambda *a: request)
    monkeypatch.setattr(launch.front, "_build", lambda *a: build)
    monkeypatch.setattr(launch.front, "_assess", lambda *a, **k: authority)
    monkeypatch.setattr(launch, "_version", lambda *a: run_row)
    monkeypatch.setattr(launch, "_snapshot", lambda *a: (fixed_run, plan))
    monkeypatch.setattr(launch, "_full_coverage", lambda *a: None)
    monkeypatch.setattr(
        launch,
        "_direct_start_references",
        lambda *a: ([binding.equipment.model_dump(mode="json")], [payload.at.source]),
    )
    monkeypatch.setattr(evidence, "refs_from_exact", lambda *a: (payload.at.source,))

    def direct_sources(*args):
        calls.append(("source", args[-1]))
        return [], False

    monkeypatch.setattr(source_current, "direct_source_basis", direct_sources)
    monkeypatch.setattr(
        launch,
        "_direct_start_summaries",
        lambda *a, **k: (
            {binding.pairs[0].sample.id: {"visibility": "category"}},
            {},
            {"samples": [], "methods": []},
        ),
    )
    monkeypatch.setattr(launch, "_direct_authority_stamp", lambda *a: ("selected-executor",))
    monkeypatch.setattr(
        professional,
        "_subject_access",
        lambda *a: (
            SimpleNamespace(active=True, kind="human"),
            SimpleNamespace(can_write=True, expires_at=None),
        ),
    )
    monkeypatch.setattr(
        launch, "_new_write", lambda *a: (SimpleNamespace(id=uid(71)), SimpleNamespace(id=uid(72)))
    )
    monkeypatch.setattr(launch, "_event", lambda *a, **k: calls.append(("event", k)))

    def forbidden_full_owner(*args, **kwargs):
        pytest.fail("A direct Start must not reload the historical upstream closure")

    for owner, name in (
        (resources, "load_bundle"),
        (resources, "_fingerprint_runtime"),
        (launch.front, "_linked"),
        (launch.physical, "_inspect"),
    ):
        monkeypatch.setattr(owner, name, forbidden_full_owner)

    def prepare(*args, **kwargs):
        calls.append(("prepare_direct", kwargs.copy()))
        bundle = resources.BoundTestResources(
            binding=binding,
            facts_revision=w.proof["facts_revision"],
            nature="synthetic",
            report={
                "status": "READY",
                "capacity_status": "checked",
                "checks": [],
                "fixed_resources": [],
                "input_digest": "c" * 64,
                "checked_at": w.clock[0],
            },
            required_source_read_set=kwargs["reads"],
        )
        return {
            "bundle": bundle.model_dump(mode="json"),
            "dependency_proof": deepcopy(w.proof),
            "watermark": {"resource": [str(uid(13)), 1, 1]},
            "visibility": "category",
        }

    monkeypatch.setattr(resources, "prepare_start_direct", prepare)
    if original:
        # A completed legacy owner remains a fixed codec reader, rather than
        # becoming a new Start's upstream qualification or resource Current.
        version, proof = launch._saved_start_fingerprint(w.s, w.ctx, w.pid, w.original)
        assert version == codec._FINGERPRINT_V2 and proof == w.proof
    bound = launch._load(w.s, w.ctx, command, product, payload, verify_event=verify_event)
    return bound, calls


def test_actual_loader_new_start_chooses_v2_before_source_owner_io_without_effects(
    work, monkeypatch
):
    bound, calls = owner_load(work, monkeypatch)
    resource_call = next(value for kind, value in calls if kind == "prepare_direct")
    assert resource_call["verified_actual_start"].occurred_at == work.binding.window.start
    assert resource_call["reads"] == [{"artifact_id": str(uid(30)), "expected_revision": 1}]
    assert bound.direct_contract and bound.fingerprint_version == codec._FINGERPRINT_V2
    assert bound.dependency_proof == work.proof and bound.direct_authority_stamp
    assert bound.caller_uow[0][-1] is work.s.get_transaction()
    assert not work.s.new and not work.s.dirty and not work.s.deleted


def test_read_only_capability_still_uses_new_start_v2_but_no_actual_event_claim(work, monkeypatch):
    bound, calls = owner_load(work, monkeypatch, verify_event=False)
    resource_call = next(value for kind, value in calls if kind == "prepare_direct")
    assert resource_call["verified_actual_start"] is None
    assert not any(kind == "event" for kind, value in calls)
    assert work.s.info["read_snapshot"] is True
    assert bound.direct_contract and bound.dependency_proof == work.proof
    assert not work.s.new and not work.s.dirty and not work.s.deleted


def test_actual_loader_saved_v2_owner_dispatch_preserves_exact_original_and_current_uow(
    work, monkeypatch
):
    saved_input, saved_owner = (
        deepcopy(work.original.input_snapshot),
        deepcopy(work.row.dependency_proof),
    )
    bound, calls = owner_load(work, monkeypatch, original=True)
    assert len([kind for kind, value in calls if kind == "prepare_direct"]) == 1
    assert bound.dependency_proof == work.proof and bound.saved_start is None
    assert work.original.input_snapshot == saved_input and work.row.dependency_proof == saved_owner
    assert bound.caller_uow[0][-1] is work.s.get_transaction()
    assert not work.s.new and not work.s.dirty and not work.s.deleted


def test_saved_unversioned_owner_keeps_v1_and_avoids_new_material_claim(work):
    del work.original.input_snapshot["resource_fingerprint_version"]
    del work.original.input_snapshot["resource_dependency_proof"]
    work.row.fingerprint_version, work.row.dependency_proof = None, None
    saved = deepcopy(work.original.input_snapshot)
    version, proof = launch._saved_start_fingerprint(work.s, work.ctx, work.pid, work.original)
    assert version == codec._FINGERPRINT_V1 and proof is None
    assert work.original.input_snapshot == saved
    assert not work.s.new and not work.s.dirty and not work.s.deleted


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
    from pdos_next.schemas.verification.contracts import Timeline

    before_timeline = Timeline(request_created=run.actual_start)
    previous = SimpleNamespace(id=uid(74), revision=5)
    w.bound.physical = SimpleNamespace(
        previous=previous,
        base=SimpleNamespace(id=binding.request_id, timeline=before_timeline),
        build=SimpleNamespace(id=binding.build_id, revision=1, project_id=binding.project_id),
        authority={"valid_until": (w.clock[0] + timedelta(hours=1)).isoformat()},
        references=[],
        reads=[],
        visibility="category",
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
            timeline=before_timeline.model_copy(update={"actual_start": run.actual_start}),
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
    assert exc.value.reason == "SOURCE_STALE"
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
        lambda q: (
            [occupied] if q.column_descriptions[0]["entity"] is ResourceOccupancy else [usage]
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
    assert exc.value.reason == "RUN_START_PROOF_INVALID"


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
    assert exc.value.reason == "RUN_START_PROOF_INVALID"


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
    assert exc.value.reason == "INTEGRITY_MISMATCH"


def test_new_load_does_not_convert_unknown_qualification_into_clock_parse_error(work, monkeypatch):
    w = work
    from pdos_next.domain.capa_effectiveness.fact_atom_storage import _uow

    w.bound.fingerprint_runtime = object()
    w.bound.caller_uow, w.bound.caller_digest = _uow(w.s), digest(vars(w.ctx))
    w.bound.physical.authority["valid_until"] = None
    monkeypatch.setattr(resources, "_same_fingerprint_runtime", lambda *a: None, raising=False)
    launch._close_start_boundary(w.s, w.ctx, w.bound, check_deadlines=False)
    assert not w.s.new
