"""Actual adapter/Session/UOW/ORM-consumption checks without database owners.

Owner preparation/serialization below is an explicit narrow test substitute.
No original bytes, professional qualification or database atom is attested.
The production adapter and ConsumptionHost run against real SQLAlchemy state.
"""

from copy import copy, deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.orm import Session, make_transient_to_detached

from pdos_next.contracts import Command, SourceRead
from pdos_next.domain.capa_effectiveness import candidate_commands as commands
from pdos_next.domain.capa_effectiveness import candidate_prepare as prepare
from pdos_next.domain.capa_effectiveness import candidate_write as writer
from pdos_next.domain.capa_effectiveness import service
from pdos_next.domain.capa_effectiveness.fact_consumption import ConsumptionHost
from pdos_next.domain.quality_execution.models import QualityIssueCurrent, QualityIssueVersion
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation, Product
from pdos_next.service import Context, digest, material_digest

ACTUAL_ORIGIN = service._origin


def attach(s, row):
    for column in inspect(type(row)).columns:
        if column.key not in vars(row):
            setattr(row, column.key, None)
    make_transient_to_detached(row)
    s.add(row)
    return row


@pytest.fixture
def world(monkeypatch):
    engine = SimpleNamespace(epoch=1)
    s = Session(bind=engine)
    s.begin()
    ctx = Context(uuid4(), uuid4(), uuid4())
    ctx = Context(ctx.tenant_id, ctx.actor_id, ctx.actor_id, category_id=uuid4())
    product = attach(
        s, Product(id=uuid4(), tenant_id=ctx.tenant_id, category_id=ctx.category_id, revision=7)
    )
    read = SourceRead(artifact_id=uuid4(), expected_revision=1)
    selected_reads = [read]
    payload = commands.CandidateRecordPayload(
        issue_id=uuid4(),
        expected_issue_revision=6,
        capa_id=uuid4(),
        sources=[],
        reason="synthetic adapter boundary only",
        confirmation_token="synthetic-token-not-an-owner-proof",
    )
    command = Command(
        command_id=uuid4(),
        idempotency_key="candidate-service-original-key",
        operation=service.OPERATION,
        category_id=ctx.category_id,
        product_id=product.id,
        expected_revision=7,
        source_read_set=[read],
        payload=payload.model_dump(mode="json"),
    )
    trace = []
    registered = set()
    phase_data = {}
    clock = SimpleNamespace(at=datetime.now(UTC))

    def create(*args, **kwargs):
        trace.append("owner_prepare")
        phase = SimpleNamespace(required_source_read_set=tuple(selected_reads), identity=uuid4())
        registered.add(id(phase))
        phase_data[id(phase)] = {
            "operation": service.OPERATION,
            "payload_semantic": service.semantic(payload),
            "stable_anchor": {"test_substitute": "not actual bytes/authority"},
            "binding": {"test_substitute": True},
            "inspection": {"result": "indeterminate"},
            "raw_source_basis": [{"id": str(read.artifact_id), "revision": 1}],
            "required_source_read_set": [value.model_dump(mode="json") for value in selected_reads],
            "sources": [],
            "authority_snapshot": {"test_substitute": True},
            "policy_snapshot": {"test_substitute": True},
            "owner_id": str(ctx.requester_id),
            "visibility": "private",
            "current_issue_revision": 6,
        }
        return phase

    def review(phase):
        if id(phase) not in registered:
            raise DomainError("CANDIDATE_PREPARED_OWNER_REQUIRED", "test phase invalid", 503)
        return deepcopy(phase_data[id(phase)])

    def discard(phase):
        registered.discard(id(phase))

    def owner_clock(_s, _ctx, _pid, _payload, phase, at):
        assert id(phase) in registered
        trace.append("owner_clock")
        if at >= clock.at + timedelta(minutes=10):
            raise DomainError("SOURCE_STALE", "test owner expiry", 409)
        return phase

    def write_prepare(_s, _ctx, _cmd, _payload, proof, restore_host):
        assert restore_host is runtime.restore_host
        assert proof.consumed is False
        trace.append("write_owner_restore")
        return create()

    monkeypatch.setattr(service, "_origin", lambda *args: "explicit owner selector substitute")
    monkeypatch.setattr(prepare, "prepare_candidate", create)
    monkeypatch.setattr(prepare, "prepare_candidate_write", write_prepare, raising=False)
    monkeypatch.setattr(prepare, "invalidate_prepared_candidate", discard)
    monkeypatch.setattr(prepare, "require_prepared_candidate_clock", owner_clock)
    monkeypatch.setattr(prepare, "_runtime", lambda session: digest(session.get_bind().epoch))
    monkeypatch.setattr(service, "_review", review)
    runtime = service.configure(engine)
    proof = attach(
        s,
        Confirmation(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            category_id=ctx.category_id,
            subject_type="product",
            product_id=product.id,
            actor_id=ctx.actor_id,
            subject_id=product.id,
            operation=service.OPERATION,
            revision=product.revision,
            token_hash=digest(payload.confirmation_token),
            payload_digest=material_digest(ctx, command, payload, service),
            snapshot=review(create()),
            consumed=False,
            created_at=clock.at - timedelta(seconds=2),
            expires_at=clock.at + timedelta(minutes=5),
        ),
    )
    trace.clear()
    monkeypatch.setattr(service, "confirmation_for", lambda *args: proof)

    def no_database(*args, **kwargs):
        pytest.fail("Thin adapter must not flush/commit/open database")

    original_flush = s.flush
    monkeypatch.setattr(s, "flush", no_database)
    monkeypatch.setattr(s, "commit", no_database)
    monkeypatch.setattr(s, "connection", no_database)
    w = SimpleNamespace(
        s=s,
        ctx=ctx,
        product=product,
        payload=payload,
        command=command,
        proof=proof,
        read=read,
        selected_reads=selected_reads,
        runtime=runtime,
        engine=engine,
        trace=trace,
        registered=registered,
        phase_data=phase_data,
        clock=clock,
        original_flush=original_flush,
    )
    yield w
    s.close()


def preview(w):
    phase = service.prepare_preview(w.s, w.ctx, w.command, w.product, w.payload)
    return phase


def write(w):
    return service.prepare_write_review(w.s, w.ctx, w.command, w.product, w.payload)


def consume(w, phase):
    binding = service.bind_consumption(w.s, w.ctx, w.command, w.product, w.payload, phase, w.proof)
    w.proof.consumed = True  # Explicit pure ORM substitute for the common action.
    marker = service.record_consumption(
        w.s, w.ctx, w.command, w.product, w.payload, phase, w.proof, binding
    )
    return binding, marker


def test_actual_alias_and_startup_module_identity(world):
    assert service.semantic is commands.semantic
    assert service.CandidateRecordPayload is commands.CandidateRecordPayload
    assert world.runtime.module is service
    assert world.runtime.restore_host.module is service
    assert world.runtime.consumption_host.modules[service.OPERATION] is service


def test_preview_prepares_once_and_render_is_single_use(world):
    phase = preview(world)
    result = service.preview_prepared(
        world.s, world.ctx, world.command, world.product, world.payload, phase
    )
    assert world.trace == ["owner_prepare", "owner_clock"]
    assert result["operation"] == service.OPERATION
    assert result["inspection"]["result"] == "indeterminate"
    assert world.proof.consumed is False
    with pytest.raises(DomainError):
        service.preview_prepared(
            world.s, world.ctx, world.command, world.product, world.payload, phase
        )


@pytest.mark.parametrize("mutation", ["key", "reads", "token", "payload", "actor", "product"])
def test_complete_preview_binding_rejects_mutation(world, mutation):
    phase = preview(world)
    command, payload, ctx, product = world.command, world.payload, world.ctx, world.product
    if mutation == "key":
        command = command.model_copy(update={"idempotency_key": "other-candidate-key"})
    elif mutation == "reads":
        command = command.model_copy(update={"source_read_set": []})
    elif mutation == "token":
        payload = payload.model_copy(update={"confirmation_token": "different-actual-token"})
        command = command.model_copy(update={"payload": payload.model_dump(mode="json")})
    elif mutation == "payload":
        payload = payload.model_copy(update={"reason": "different reason"})
        command = command.model_copy(update={"payload": payload.model_dump(mode="json")})
    elif mutation == "actor":
        ctx = Context(ctx.tenant_id, uuid4(), uuid4())
    elif mutation == "product":
        product.revision += 1
    with pytest.raises(DomainError):
        service.preview_prepared(world.s, ctx, command, product, payload, phase)


@pytest.mark.parametrize("mutation", ["copy", "nested", "new_transaction", "runtime"])
def test_preview_phase_exact_identity_uow_and_runtime(world, mutation):
    phase = preview(world)
    if mutation == "copy":
        phase = copy(phase)
    elif mutation == "nested":
        world.s.flush = world.original_flush
        world.s.begin_nested()
    elif mutation == "new_transaction":
        world.s.rollback()
        world.s.begin()
    else:
        world.engine.epoch += 1
    with pytest.raises(DomainError):
        service.preview_prepared(
            world.s, world.ctx, world.command, world.product, world.payload, phase
        )


def test_preview_nested_material_change_and_expiry(world, monkeypatch):
    phase = preview(world)
    world.phase_data[id(phase.prepared)]["inspection"]["result"] = "pass"
    with pytest.raises(DomainError):
        service.preview_prepared(
            world.s, world.ctx, world.command, world.product, world.payload, phase
        )
    phase = preview(world)
    monkeypatch.setattr(
        prepare,
        "require_prepared_candidate_clock",
        lambda *args: (_ for _ in ()).throw(DomainError("SOURCE_STALE", "expired", 409)),
    )
    with pytest.raises(DomainError, match="expired"):
        service.preview_prepared(
            world.s, world.ctx, world.command, world.product, world.payload, phase
        )


def test_validate_checks_current_gates_without_product_cas_before_replay(world):
    world.product.revision += 1
    service.validate(world.s, world.ctx, world.command, world.product, world.payload)
    assert world.trace == ["owner_prepare", "owner_clock"]
    with pytest.raises(DomainError) as error:
        preview(world)
    assert error.value.reason == "VERSION_CONFLICT"


def test_missing_complete_source_read_set_is_rejected(world):
    command = world.command.model_copy(update={"source_read_set": []})
    with pytest.raises(DomainError) as error:
        service.validate(world.s, world.ctx, command, world.product, world.payload)
    assert error.value.reason == "MISSING_REQUIRED_EVIDENCE"


def test_same_reads_reordered_still_change_exact_command_phase(world):
    world.selected_reads.append(SourceRead(artifact_id=uuid4(), expected_revision=2))
    world.command = world.command.model_copy(update={"source_read_set": world.selected_reads[:]})
    phase = preview(world)
    reordered = world.command.model_copy(
        update={"source_read_set": list(reversed(world.command.source_read_set))}
    )
    with pytest.raises(DomainError):
        service.preview_prepared(world.s, world.ctx, reordered, world.product, world.payload, phase)


def test_write_restore_uses_original_proof_and_real_false_true_marker(world, monkeypatch):
    phase, snapshot = write(world)
    assert phase.proof is world.proof and snapshot == world.proof.snapshot
    markers = consume(world, phase)

    def actual_delegation(s, ctx, command, product, payload, prepared, **kwargs):
        assert prepared is phase.prepared
        assert kwargs["module"] is service
        host = kwargs["consumption_host"]
        assert type(host) is ConsumptionHost
        assert (
            host.require_live(
                s,
                ctx,
                command,
                payload,
                service,
                world.proof,
                binding=kwargs["consumption_binding"],
                marker=kwargs["consumption_marker"],
            )
            is markers[1]
        )
        return "explicit writer substitute", service.SUBJECT, "private"

    monkeypatch.setattr(writer, "apply_prepared_candidate", actual_delegation)
    result = service.apply_prepared_write(
        world.s, world.ctx, world.command, world.product, world.payload, phase, consumption=markers
    )
    assert result[1] == "capa_verification_candidate"
    with pytest.raises(DomainError):
        service.apply_prepared_write(
            world.s,
            world.ctx,
            world.command,
            world.product,
            world.payload,
            phase,
            consumption=markers,
        )


def test_record_requires_actual_false_true_before_any_owner_io(world):
    phase, _ = write(world)
    binding = service.bind_consumption(
        world.s, world.ctx, world.command, world.product, world.payload, phase, world.proof
    )
    before = list(world.trace)
    with pytest.raises(DomainError) as error:
        service.record_consumption(
            world.s,
            world.ctx,
            world.command,
            world.product,
            world.payload,
            phase,
            world.proof,
            binding,
        )
    assert error.value.reason == "FACT_ACTUAL_FALSE_TRUE_REQUIRED"
    assert world.trace == before


def test_write_rejects_forged_marker_and_never_enters_fallback(world):
    phase, _ = write(world)
    with pytest.raises(DomainError):
        service.apply_prepared_write(
            world.s,
            world.ctx,
            world.command,
            world.product,
            world.payload,
            phase,
            consumption=(object(), True),
        )
    with pytest.raises(DomainError) as error:
        service.apply(world.s, world.ctx, world.command, world.product, world.payload)
    assert error.value.reason == "INTEGRATION_REQUIRED"


def test_failed_writer_cannot_reuse_its_phase(world, monkeypatch):
    phase, _ = write(world)
    markers = consume(world, phase)

    def failure(*args, **kwargs):
        raise DomainError("SOURCE_STALE", "explicit last-owner drift substitute", 409)

    monkeypatch.setattr(writer, "apply_prepared_candidate", failure)
    with pytest.raises(DomainError) as error:
        service.apply_prepared_write(
            world.s,
            world.ctx,
            world.command,
            world.product,
            world.payload,
            phase,
            consumption=markers,
        )
    assert error.value.reason == "SOURCE_STALE"
    with pytest.raises(DomainError) as error:
        service.apply_prepared_write(
            world.s,
            world.ctx,
            world.command,
            world.product,
            world.payload,
            phase,
            consumption=markers,
        )
    assert error.value.reason == "CANDIDATE_COMMON_PHASE_REQUIRED"


def test_runtime_replacement_during_owner_write_is_rejected(world, monkeypatch):
    phase, _ = write(world)
    markers = consume(world, phase)

    def changed(*args, **kwargs):
        service.configure(world.engine)
        return "explicit pending append substitute", service.SUBJECT, "private"

    monkeypatch.setattr(writer, "apply_prepared_candidate", changed)
    with pytest.raises(DomainError):
        service.apply_prepared_write(
            world.s,
            world.ctx,
            world.command,
            world.product,
            world.payload,
            phase,
            consumption=markers,
        )


@pytest.mark.parametrize("mutation", ["missing", "replaced", "wrong_snapshot", "missing_restore"])
def test_write_fails_closed_for_missing_runtime_original_snapshot_and_restore(
    world, monkeypatch, mutation
):
    if mutation == "missing":
        del world.engine._pdos_capa_candidate_runtime
    elif mutation == "replaced":
        world.engine._pdos_capa_candidate_runtime = SimpleNamespace()
    elif mutation == "wrong_snapshot":
        world.proof.snapshot = {"client_anchor": True}
    else:
        monkeypatch.setattr(prepare, "prepare_candidate_write", None)
    with pytest.raises(DomainError):
        write(world)
    assert world.proof.consumed is False


def test_origin_selector_is_exact_current_and_private_caller(world, monkeypatch):
    actual = ACTUAL_ORIGIN
    calls = []
    pointer = SimpleNamespace(project_id=uuid4(), issue_version_id=uuid4(), issue_revision=6)
    row = SimpleNamespace(
        id=pointer.issue_version_id,
        revision=6,
        snapshot_sha256="a" * 64,
        visibility="private",
        owner_id=world.ctx.requester_id,
    )

    def one(s, model, *where):
        calls.append((model, where))
        return pointer if model is QualityIssueCurrent else row

    monkeypatch.setattr(service.fact_atom_storage, "_one", one)
    ref = actual(world.s, world.ctx, world.product.id, world.payload)
    assert ref.id == pointer.issue_version_id and ref.revision == 6
    assert calls[0][0] is QualityIssueCurrent and calls[1][0] is QualityIssueVersion
    row.owner_id = uuid4()
    with pytest.raises(DomainError) as error:
        actual(world.s, world.ctx, world.product.id, world.payload)
    assert error.value.reason == "FORBIDDEN_SCOPE"
