"""No-I/O protocol/count regressions with real DTOs, ORM UOW and Plan kernel.

Owner SQL loaders/access checks are explicit substitutes in renderer tests.  They
prove sequencing and failure propagation, not actual source/qualification truth.
Successful method-cache tests exercise the unchanged real _bound_proof function.
"""

import ast
import copy
import inspect
import json
import socket
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, make_transient_to_detached
from verification_launch import test_pure as delivered

from pdos_next import launch_plan_preview as seam
from pdos_next.contracts import Command, SourceRead
from pdos_next.domain.configurations.schemas import DefinitionReference
from pdos_next.domain.verification_handoff import service as physical
from pdos_next.errors import DomainError
from pdos_next.models import Product
from pdos_next.schemas.verification.contracts import EventTime
from pdos_next.service import Context, digest


@pytest.fixture(autouse=True)
def no_io(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("This candidate's pure checks cannot open a DB or network connection")

    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(Engine, "raw_connection", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture
def work(monkeypatch):
    value = delivered.work.__wrapped__()
    _, clock, report = delivered.preview_setup(value, monkeypatch)
    payload = delivered.public_plan(value)
    references = [
        {
            "artifact_id": uuid4(),
            "expected_revision": 1,
            "line": 1,
            "quote": f"Synthetic original full line {n}; no qualification granted",
        }
        for n in range(10)
    ]
    payload = payload.model_copy(
        update={"sources": tuple(DefinitionReference.model_validate(r) for r in references)}
    )
    category = uuid4()
    ctx = Context(value.request.scope.tenant_id, value.actor, value.actor, category_id=category)
    engine = SimpleNamespace()
    s = Session(bind=engine)
    product = Product(
        id=value.request.scope.product_id,
        tenant_id=ctx.tenant_id,
        category_id=category,
        visibility="private",
        created_at=delivered.AT,
        owner_id=value.actor,
        name="Isolated synthetic counting fixture",
        purpose=value.request.purpose,
        revision=3,
        lifecycle_epoch=1,
        status="draft",
    )
    make_transient_to_detached(product)
    s.add(product)
    command = Command(
        command_id=uuid4(),
        idempotency_key=str(uuid4()),
        operation=seam.OPERATION,
        category_id=category,
        product_id=product.id,
        expected_revision=3,
        source_read_set=[
            SourceRead(artifact_id=r["artifact_id"], expected_revision=1) for r in references
        ],
        payload=payload.model_dump(mode="json"),
    )
    load, guards, cas = seam.launch._load, seam.launch._guards, seam.launch._new_write
    bound = load(s, ctx, command, product, payload)
    bound.physical.authority.update(
        operation=command.operation,
        purpose=value.request.purpose,
        synthetic=True,
        valid_until=None,
        fact_refs=[
            {
                "kind": kind,
                "role": "quality",
                "nature": "synthetic",
                "state": "active",
                "operations": [command.operation],
                "purposes": [value.request.purpose],
                "valid_from": (clock[0] - timedelta(hours=1)).isoformat(),
                "valid_until": (clock[0] + timedelta(minutes=5)).isoformat(),
            }
            for kind in ("duty", "qualification")
        ],
    )
    bound.physical.reads = [r.model_dump(mode="json") for r in command.source_read_set]
    counts = {"load": 0, "guards": 0, "cas": 0}
    failure = [None]

    def counted_load(*args, **kwargs):
        counts["load"] += 1
        if failure[0]:
            raise DomainError(failure[0], "Explicit owner failure substitute")
        return load(*args, **kwargs)

    def counted_guards(*args, **kwargs):
        counts["guards"] += 1
        return guards(*args, **kwargs)

    def counted_cas(*args, **kwargs):
        counts["cas"] += 1
        return cas(*args, **kwargs)

    monkeypatch.setattr(seam.launch, "_load", counted_load)
    monkeypatch.setattr(seam.launch, "_guards", counted_guards)
    monkeypatch.setattr(seam.launch, "_new_write", counted_cas)
    monkeypatch.setattr(seam, "_now", lambda: clock[0])
    result = SimpleNamespace(
        s=s,
        ctx=ctx,
        command=command,
        product=product,
        payload=payload,
        clock=clock,
        counts=counts,
        report=report,
        failure=failure,
        work=value,
        bound=bound,
        engine=engine,
    )
    yield result
    s.close()


def preview(w):
    return seam.preview_once(w.s, w.ctx, w.command, w.product, w.payload)


def test_real_dto_ten_sources_preview_removes_only_duplicate_complete_load(work):
    """Baseline common branch = validate + preview; candidate = owner preview."""
    w = work
    seam.launch.validate(w.s, w.ctx, w.command, w.product, w.payload)
    baseline = seam.launch.preview_view(w.s, w.ctx, w.command, w.product, w.payload)
    assert w.counts == {"load": 2, "guards": 2, "cas": 1}
    w.counts.update(load=0, guards=0, cas=0)
    optimized = preview(w)
    assert w.counts == {"load": 1, "guards": 1, "cas": 1}
    assert optimized == baseline
    assert len(optimized["required_source_read_set"]) == 10
    assert len(w.payload.coverage) == 2
    assert optimized["after"]["occupancy_effect"] == "none"
    assert optimized["after"]["run"]["run_snapshot"]["actual_start"] is None
    assert optimized["resource_report"]["checked_at"] is None
    assert optimized["resource_report"]["input_digest"] == "a" * 64
    assert w.work.reserved == [] and not w.s.new


def test_original_command_readset_and_microsecond_window_are_not_rewritten(work):
    before = copy.deepcopy(work.command.model_dump(mode="json"))
    preview(work)
    assert work.command.model_dump(mode="json") == before
    assert work.payload.execution_plan.window == work.work.plan.window


def test_success_does_not_survive_another_call(work):
    preview(work)
    preview(work)
    assert work.counts["load"] == 2


@pytest.mark.parametrize(
    "code",
    [
        "FORBIDDEN_SCOPE",
        "SOURCE_STALE",
        "SOURCE_CHANGED",
        "ACTUAL_METHOD_UNKNOWN",
        "RESOURCE_NOT_READY",
    ],
)
def test_real_owner_failure_propagates_and_is_never_cached(work, code):
    work.failure[0] = code
    with pytest.raises(DomainError) as error:
        preview(work)
    assert error.value.reason == code
    work.failure[0] = None
    preview(work)
    assert work.counts["load"] == 2


@pytest.mark.parametrize("operation", ["verification.schedule.promise", "test.run.start"])
def test_seam_cannot_dispatch_promise_or_start(work, operation):
    command = work.command.model_copy(update={"operation": operation})
    with pytest.raises(DomainError) as error:
        seam.preview_once(work.s, work.ctx, command, work.product, work.payload)
    assert error.value.reason == "FORBIDDEN_OPERATION" and work.counts["load"] == 0


def test_pending_agent_context_is_not_human_authority(work):
    ctx = replace(work.ctx, actor_id=uuid4(), run_id=uuid4())
    with pytest.raises(DomainError) as error:
        seam.preview_once(work.s, ctx, work.command, work.product, work.payload)
    assert error.value.status == 403 and work.counts["load"] == 0


def test_other_product_scope_cannot_enter_owner(work):
    command = work.command.model_copy(update={"product_id": uuid4()})
    with pytest.raises(DomainError) as error:
        seam.preview_once(work.s, work.ctx, command, work.product, work.payload)
    assert error.value.reason == "FORBIDDEN_SCOPE" and work.counts["load"] == 0


def test_clock_after_all_owner_work_rejects_window_that_elapsed(work, monkeypatch):
    render = seam.launch.preview_view

    def slow(*args):
        value = render(*args)
        work.clock[0] = work.payload.execution_plan.window.start + timedelta(microseconds=1)
        return value

    monkeypatch.setattr(seam.launch, "preview_view", slow)
    with pytest.raises(DomainError) as error:
        preview(work)
    assert error.value.reason == "INVALID_EVENT_TIME"
    assert not work.s.new and work.work.reserved == []


def test_own_professional_expiry_after_owner_io_blocks_return(work, monkeypatch):
    render = seam.launch.preview_view
    work.bound.physical.authority["fact_refs"][0]["valid_until"] = (
        work.clock[0] + timedelta(seconds=10)
    ).isoformat()

    def slow(*args):
        value = render(*args)
        work.clock[0] += timedelta(seconds=11)
        return value

    monkeypatch.setattr(seam.launch, "preview_view", slow)
    with pytest.raises(DomainError) as error:
        preview(work)
    assert error.value.reason == "SOURCE_STALE"


@pytest.mark.parametrize("until", [None, "not-a-time", "2026-10-03T12:00:00"])
def test_missing_or_unaware_actual_authority_deadline_is_unknown(work, until):
    work.bound.physical.authority["fact_refs"][0]["valid_until"] = until
    with pytest.raises(DomainError) as error:
        preview(work)
    assert error.value.reason == "SOURCE_STALE"


@pytest.mark.parametrize("field", ["idempotency_key", "source_read_set", "payload"])
def test_original_envelope_changes_during_io_are_rejected(work, monkeypatch, field):
    render = seam.launch.preview_view

    def drift(*args):
        value = render(*args)
        if field == "idempotency_key":
            work.command.idempotency_key = str(uuid4())
        elif field == "source_read_set":
            work.command.source_read_set.reverse()
        else:
            work.command.payload["reason"] = "Different semantic reason"
        return value

    monkeypatch.setattr(seam.launch, "preview_view", drift)
    with pytest.raises(DomainError) as error:
        preview(work)
    assert error.value.reason in {"SOURCE_CHANGED", "FORBIDDEN_OPERATION"}


def test_current_issuer_epoch_aba_during_io_is_rejected(work, monkeypatch):
    render = seam.launch.preview_view
    work.engine._pdos_test_resource_issuer_epochs = {"fixture": 1}

    def drift(*args):
        value = render(*args)
        work.engine._pdos_test_resource_issuer_epochs["fixture"] = 3
        return value

    monkeypatch.setattr(seam.launch, "preview_view", drift)
    with pytest.raises(DomainError) as error:
        preview(work)
    assert error.value.reason == "SOURCE_STALE"


def test_owner_callback_replacement_during_io_is_rejected(work, monkeypatch):
    render = seam.launch.preview_view

    def drift(*args):
        value = render(*args)
        monkeypatch.setattr(seam.launch, "_load", lambda *_: work.bound)
        return value

    monkeypatch.setattr(seam.launch, "preview_view", drift)
    with pytest.raises(DomainError) as error:
        preview(work)
    assert error.value.reason == "SOURCE_STALE"


def test_nested_transaction_change_during_owner_work_is_rejected(work, monkeypatch):
    render = seam.launch.preview_view

    def drift(*args):
        value = render(*args)
        work.s.begin_nested()
        return value

    monkeypatch.setattr(seam.launch, "preview_view", drift)
    with pytest.raises(DomainError) as error:
        preview(work)
    assert error.value.reason == "SOURCE_STALE"


def test_same_actual_nested_uow_is_accepted_without_connection(work):
    work.s.begin_nested()
    work.s.begin_nested()
    preview(work)
    assert work.counts["load"] == 1


def test_product_material_change_is_rejected(work, monkeypatch):
    render = seam.launch.preview_view

    def drift(*args):
        value = render(*args)
        work.product.lifecycle_epoch += 1
        return value

    monkeypatch.setattr(seam.launch, "preview_view", drift)
    with pytest.raises(DomainError) as error:
        preview(work)
    assert error.value.reason == "INTEGRATION_REQUIRED"


def test_successful_bound_proof_reuses_owner_only_with_fresh_sources_each_hit(monkeypatch):
    at = delivered.AT
    stamp = ("caller", "epoch", at + timedelta(minutes=5))
    counts = {"check": 0, "source": 0, "stamp": 0}

    def fresh(*args):
        counts["stamp"] += 1
        return stamp

    monkeypatch.setattr(physical, "_proof_stamp", fresh)
    monkeypatch.setattr(physical, "now", lambda: at)
    row = SimpleNamespace(
        authority_snapshot={"valid_until": (at + timedelta(minutes=3)).isoformat()}
    )
    bound = SimpleNamespace(proofs={})

    def check():
        counts["check"] += 1

    def sources():
        counts["source"] += 1

    physical._bound_proof(None, None, None, bound, row, "fixed-material", check, sources)
    physical._bound_proof(None, None, None, bound, row, "fixed-material", check, sources)
    assert counts == {"check": 1, "source": 1, "stamp": 4}


def test_successful_cached_proof_does_not_bypass_source_withdrawal(monkeypatch):
    at = delivered.AT
    monkeypatch.setattr(physical, "_proof_stamp", lambda *_: ("epoch", at + timedelta(minutes=5)))
    monkeypatch.setattr(physical, "now", lambda: at)
    row = SimpleNamespace(
        authority_snapshot={"valid_until": (at + timedelta(minutes=3)).isoformat()}
    )
    bound = SimpleNamespace(proofs={})
    physical._bound_proof(None, None, None, bound, row, "same", lambda: None, lambda: None)

    def withdrawn():
        raise DomainError("SOURCE_STALE", "Explicit source withdrawal substitute")

    with pytest.raises(DomainError) as error:
        physical._bound_proof(None, None, None, bound, row, "same", lambda: None, withdrawn)
    assert error.value.reason == "SOURCE_STALE"


def proof_work(monkeypatch):
    clock = [delivered.AT]
    stamp = [1]
    counts = {"check": 0, "sources": 0}
    monkeypatch.setattr(physical, "now", lambda: clock[0])
    monkeypatch.setattr(
        physical, "_proof_stamp", lambda *_: (stamp[0], delivered.AT + timedelta(minutes=3))
    )
    row = SimpleNamespace(
        authority_snapshot={"valid_until": (delivered.AT + timedelta(minutes=3)).isoformat()}
    )
    bound = SimpleNamespace(proofs={})

    def check():
        counts["check"] += 1

    def sources():
        counts["sources"] += 1

    return SimpleNamespace(
        clock=clock, stamp=stamp, counts=counts, row=row, bound=bound, check=check, sources=sources
    )


def check_proof(w, check=None):
    physical._bound_proof(
        None, None, None, w.bound, w.row, "same-full-material", check or w.check, w.sources
    )


def test_failed_original_review_is_never_memoized(monkeypatch):
    w = proof_work(monkeypatch)

    def unavailable():
        raise DomainError("QUALIFICATION_REQUIRED", "Explicit professional failure substitute")

    with pytest.raises(DomainError):
        check_proof(w, unavailable)
    assert w.bound.proofs == {}
    check_proof(w)
    assert w.counts["check"] == 1


def test_fresh_scalar_acl_rejection_precedes_cache_hit(monkeypatch):
    w = proof_work(monkeypatch)
    check_proof(w)

    def revoked(*args):
        raise DomainError("FORBIDDEN_SCOPE", "Explicit revoked caller scalar substitute", 403)

    monkeypatch.setattr(physical, "_proof_stamp", revoked)
    with pytest.raises(DomainError) as error:
        check_proof(w)
    assert error.value.status == 403 and w.counts["check"] == 1


def test_issuer_material_stamp_change_reruns_original_owner(monkeypatch):
    w = proof_work(monkeypatch)
    check_proof(w)
    w.stamp[0] += 1
    check_proof(w)
    assert w.counts["check"] == 2 and w.counts["sources"] == 0


def test_clock_expiry_during_original_owner_io_cannot_cache_success(monkeypatch):
    w = proof_work(monkeypatch)

    def slow():
        w.check()
        w.clock[0] += timedelta(minutes=4)

    with pytest.raises(DomainError) as error:
        check_proof(w, slow)
    assert error.value.reason == "SOURCE_STALE" and w.bound.proofs == {}


def test_cache_deadline_is_not_renewed_by_repeated_success(monkeypatch):
    w = proof_work(monkeypatch)
    check_proof(w)
    first = w.bound.proofs["same-full-material"]
    w.clock[0] += timedelta(minutes=2)
    check_proof(w)
    assert w.bound.proofs["same-full-material"] == first
    w.clock[0] += timedelta(minutes=2)
    with pytest.raises(DomainError) as error:
        check_proof(w)
    assert error.value.reason == "SOURCE_STALE"


def test_ending_original_uow_during_io_never_reads_expired_product(work, monkeypatch):
    render = seam.launch.preview_view

    def ended(*args):
        value = render(*args)
        work.s.rollback()
        return value

    monkeypatch.setattr(seam.launch, "preview_view", ended)
    with pytest.raises(DomainError) as error:
        preview(work)
    assert error.value.reason == "INTEGRATION_REQUIRED"


def test_delivered_validate_guards_are_present_in_unchanged_preview():
    def calls(fn):
        tree = ast.parse(inspect.getsource(fn))
        return [
            n.value.func.id
            for n in tree.body[0].body
            if isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Call)
            and isinstance(n.value.func, ast.Name)
        ]

    assert calls(seam.launch.validate) == ["_guards"]
    assert calls(seam.launch.preview_view)[:2] == ["_guards", "_new_write"]
    tree = ast.parse(inspect.getsource(seam.launch.preview_view))
    first = tree.body[0].body[0]
    assert isinstance(first, ast.Assign) and first.value.func.id == "_load"


def test_applied_exact_seam_cannot_affect_execute_or_phased_consume():
    from pdos_next import service as common

    text = inspect.getsource(common.preview_command)
    assert 'elif command.operation == "test.run.plan":' in text
    assert "snapshot = preview_once(s, ctx, command, product, payload)" in text
    assert "prepare_write" not in text and "apply_prepared" not in text
    assert "test.run.plan" not in common.PHASED_MATERIAL_OPERATIONS
    assert not hasattr(seam, "apply") and not hasattr(seam, "replay_subject")


def test_kernel_future_promise_and_actual_start_are_still_separate():
    w = delivered.work.__wrapped__()
    delivered.promised(w)
    assert w.request.timeline.promised_start.occurred_at == w.plan.window.start
    assert w.plan.window.start > delivered.AT
    assert w.run.actual_start is None and w.reserved == []
    later = delivered.work.__wrapped__()
    started = delivered.started(later)
    assert started.run.actual_start.occurred_at == later.plan.window.start
    assert len(later.reserved) == 1


@pytest.mark.parametrize("actual", [False, True])
def test_real_host_event_requires_past_only_for_actual_start(work, monkeypatch, actual):
    operation = "test.run.start" if actual else "verification.schedule.promise"
    plan, request = work.payload.execution_plan, work.work.request
    line = json.dumps(
        {
            "request_id": str(request.id),
            "run_id": str(work.payload.run_id),
            "purpose": request.purpose,
            "operation": operation,
            "occurred_at": plan.window.start.isoformat(),
            "executor_id": str(plan.executor_id),
        }
    )
    reference = DefinitionReference(artifact_id=uuid4(), expected_revision=1, line=1, quote=line)
    source = physical.event_source(reference)
    cls = seam.launch.StartPayload if actual else seam.launch.PromisePayload
    payload = cls(
        request_id=request.id,
        expected_request_revision=request.revision,
        run_id=work.payload.run_id,
        expected_run_revision=1,
        expected_plan_sha256=digest(plan.model_dump(mode="json")),
        at=EventTime(occurred_at=plan.window.start, original_timezone="UTC", source=source),
        reason="Synthetic event semantics only",
    )
    monkeypatch.setattr(seam.launch, "source_for", lambda *_: SimpleNamespace(content=line))
    refs = [reference.model_dump(mode="json")]
    if actual:
        with pytest.raises(DomainError) as error:
            seam.launch._event(
                None, work.ctx, work.product.id, request, plan, payload, refs, actual=True
            )
        assert error.value.reason == "INVALID_EVENT_TIME"
    else:
        seam.launch._event(
            None, work.ctx, work.product.id, request, plan, payload, refs, actual=False
        )
