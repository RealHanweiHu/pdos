"""Actual saved readers with no-connect SELECT substitutes, never RLS proof.

The private request-key association SELECT is executed by the real helper under
the actual reader context. Its boolean result is an explicit IO substitute;
the saved fact/paired normalization and all surrounding group guards are real.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_fact_write import apply, consume, make_world, prepared
from test_live_paired_owner import frame as paired_frame
from test_participants_owner import RawSession

from pdos_next import service as common
from pdos_next.domain.capa_effectiveness import fact_atom_storage, paired_storage
from pdos_next.errors import DomainError
from pdos_next.models import (
    Audit,
    Confirmation,
    Grant,
    Outbox,
    Principal,
    Product,
    Receipt,
    RequestKey,
)


def _columns(row):
    # Common DB-generated audience columns are not mapped by these domain
    # classes and are not consumed by this saved-group reader.
    # Inspect already supplied values only: a detached writer fixture has
    # unloaded optional columns, which must never trigger a connection here.
    return {column.name: vars(row).get(column.name) for column in row.__table__.c}


def _fact_frame(monkeypatch, kind):
    # Reuse the actual pure writer's immutable body/proof shape, not a new
    # hand-authored FactAtom. SELECT rows below remain explicit substitutes.
    written = make_world(monkeypatch, kind)
    phase = prepared(written)
    consumed = consume(written, phase)
    row = apply(written, phase, consumed)
    proof = consumed[0]
    s = RawSession(written.s.get_bind())
    s.begin()
    ctx = replace(written.ctx, actor_id=uuid4(), requester_id=None)
    ctx = replace(ctx, requester_id=ctx.actor_id)
    pid = written.product.id
    s.info["scope"] = (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id)
    s.seed(type(row), **_columns(row))
    s.seed(Confirmation, **_columns(proof))
    s.seed(Product, **_columns(written.product))
    for actor in (ctx.actor_id, written.ctx.actor_id):
        s.seed(Principal, id=actor, tenant_id=ctx.tenant_id, kind="human", active=True)
        s.seed(
            Grant,
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            category_id=ctx.category_id,
            principal_id=actor,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            can_write=True,
        )
    _, operation, _, subject, event, status = fact_atom_storage.SPECS[kind]
    receipt = s.seed(
        Receipt,
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=pid,
        command_id=row.command_id,
        actor_id=row.actor_id,
        requester_id=row.actor_id,
        operation=operation,
        subject_type=subject,
        subject_id=row.id,
        subject_revision=row.revision,
        visibility=row.visibility,
        request_digest=common.digest("original stored request"),
        intent_digest=row.intent_digest,
        created_at=row.created_at + timedelta(microseconds=1),
        result={
            "id": str(row.id),
            "revision": row.revision,
            "status": status,
            "fact_kind": kind,
            "payload_sha256": row.payload_sha256,
        },
    )
    s.seed(
        RequestKey,
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        actor_id=row.actor_id,
        receipt_id=receipt["id"],
        digest=receipt["request_digest"],
        key="private original request",
    )
    s.seed(
        Audit,
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        receipt_id=receipt["id"],
        actor_id=row.actor_id,
        operation=operation,
    )
    s.seed(
        Outbox,
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        receipt_id=receipt["id"],
        actor_id=row.actor_id,
        type=event,
        subject_id=row.id,
        subject_revision=row.revision,
        schema_version=1,
        correlation_id=row.command_id,
    )
    work = SimpleNamespace(
        s=s,
        ctx=ctx,
        pid=pid,
        receipt=SimpleNamespace(**receipt),
        missing_code="FACT_ORIGINAL_REQUEST_KEY_MISSING",
        hide_key=lambda: s.rows[RequestKey.__tablename__].clear(),
        damage_group=lambda: s.rows[Outbox.__tablename__][0].update(correlation_id=uuid4()),
        group_error="FACT_AUDIT_OUTBOX_BINDING_MISMATCH",
        close=lambda: (s.close(), written.s.close(), s.get_bind().dispose()),
    )
    work.read = lambda: fact_atom_storage.read_fact_atom(
        s, work.ctx, pid, kind=kind, fact_id=row.id, revision=row.revision
    )
    return work


def _pair_frame(monkeypatch):
    # This current fixture understands the exact multi-Run Fact/Current join.
    # Only its SELECT normalization is used, not its substituted live owners.
    frame = paired_frame(monkeypatch, "test.run.start")
    receipt = frame.memory.first(Receipt)
    work = SimpleNamespace(
        s=frame.s,
        ctx=frame.ctx,
        pid=frame.binding.scope.product_id,
        receipt=receipt,
        missing_code="PAIR_REQUEST_PROVENANCE_MISSING",
        hide_key=lambda: frame.memory.drop(RequestKey),
        damage_group=lambda: setattr(frame.memory.first(Audit), "actor_id", uuid4()),
        group_error="PAIR_ATOM_MISMATCH",
        close=frame.s.close,
    )
    work.s.info["scope"] = (
        work.ctx.tenant_id,
        work.ctx.actor_id,
        work.ctx.requester_id,
        work.ctx.category_id,
    )
    work.read = lambda: paired_storage.read_storage_pair(
        work.s,
        work.ctx,
        work.pid,
        frame.binding.output_ref,
        at=frame.clock[0],
    )
    return work


@pytest.fixture(params=("observation", "review", "pair"))
def work(request, monkeypatch):
    value = (
        _pair_frame(monkeypatch)
        if request.param == "pair"
        else _fact_frame(monkeypatch, request.param)
    )
    assert value.ctx.actor_id != value.receipt.actor_id
    yield value
    value.close()


def _binding_io(monkeypatch, work, *, result=True):
    original = work.s.scalar
    original_context = work.ctx
    transaction = work.s.get_transaction()
    state = SimpleNamespace(result=result, calls=0)

    def scalar(statement, *args, **kwargs):
        columns = list(statement.selected_columns)
        function = getattr(columns[0], "element", None)
        if getattr(function, "name", None) != "change_receipt_key_bound":
            return original(statement, *args, **kwargs)
        assert function.packagenames == ("public",)
        assert tuple(value.value for value in function.clauses) == (
            work.ctx.tenant_id,
            work.pid,
            work.receipt.id,
        )
        assert work.ctx is original_context
        assert work.s.info["scope"] == (
            work.ctx.tenant_id,
            work.ctx.actor_id,
            work.ctx.requester_id,
            work.ctx.category_id,
        )
        assert work.s.get_transaction() is transaction
        assert statement.get_execution_options()["autoflush"] is False
        state.calls += 1
        return state.result

    monkeypatch.setattr(work.s, "scalar", scalar)
    return state


def _reject(work, code):
    with pytest.raises(DomainError) as error:
        work.read()
    assert error.value.reason == code


def test_peer_hidden_key_uses_boolean_association_without_changing_reader(work, monkeypatch):
    work.hide_key()
    checked = _binding_io(monkeypatch, work)
    read = work.read()
    assert checked.calls == 1
    receipt_id = read.material.receipt.id if hasattr(read, "material") else read.atom.receipt_id
    assert receipt_id == work.receipt.id


@pytest.mark.parametrize("result", (False, 1))
def test_peer_missing_or_nonboolean_association_cannot_return_material(work, monkeypatch, result):
    work.hide_key()
    checked = _binding_io(monkeypatch, work, result=result)
    _reject(work, work.missing_code)
    assert checked.calls == 1


def test_visible_exact_original_key_does_not_call_boolean_fallback(work, monkeypatch):
    checked = _binding_io(monkeypatch, work, result=False)
    work.read()
    assert checked.calls == 0


def test_own_missing_key_cannot_borrow_peer_fallback(work, monkeypatch):
    work.hide_key()
    work.ctx = replace(work.ctx, actor_id=work.receipt.actor_id, requester_id=work.receipt.actor_id)
    work.s.info["scope"] = (
        work.ctx.tenant_id,
        work.ctx.actor_id,
        work.ctx.requester_id,
        work.ctx.category_id,
    )
    checked = _binding_io(monkeypatch, work)
    _reject(work, work.missing_code)
    assert checked.calls == 0


def test_true_peer_association_does_not_replace_saved_group_guards(work, monkeypatch):
    work.hide_key()
    checked = _binding_io(monkeypatch, work)
    work.damage_group()
    _reject(work, work.group_error)
    assert checked.calls == 1
