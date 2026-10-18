"""Native text needs actual server registration; uploaded files keep their gate."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from pdos_next.domain.change_execution import service
from pdos_next.errors import DomainError
from pdos_next.models import Principal, Run

from .test_evidence import evidence


def native(monkeypatch, *, agent=False):
    from pdos_next import service as common

    s, ctx, pid, reads, exact, store = evidence(monkeypatch, no_original=True)
    source = common.source_for(s, ctx, pid, exact.id, exact.revision)
    actor_id = uuid4() if agent else source.owner_id
    run_id = uuid4() if agent else None
    receipt = SimpleNamespace(
        category_id=ctx.category_id,
        id=uuid4(),
        command_id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=pid,
        operation="evidence.artifact.register",
        subject_type="artifact",
        subject_id=source.id,
        subject_revision=source.revision,
        requester_id=source.owner_id,
        actor_id=actor_id,
        visibility=source.visibility,
        run_id=run_id,
        result={"id": str(source.id), "revision": source.revision, "status": "active"},
        request_digest="a" * 64,
        intent_digest="b" * 64,
    )
    requester = SimpleNamespace(id=source.owner_id, tenant_id=ctx.tenant_id, kind="human")
    actor = (
        SimpleNamespace(id=actor_id, tenant_id=ctx.tenant_id, kind="agent") if agent else requester
    )
    run = (
        SimpleNamespace(
            id=run_id,
            tenant_id=ctx.tenant_id,
            product_id=pid,
            requester_id=source.owner_id,
            writer_id=actor_id,
        )
        if agent
        else None
    )
    principals = {actor.id: actor, requester.id: requester}
    s.get = lambda model, identity: (
        principals.get(identity) if model is Principal else run if model is Run else None
    )
    s.scalars = lambda _query: (receipt,)
    return s, ctx, pid, reads, exact, store, receipt, run


@pytest.mark.parametrize("agent", [False, True])
def test_registered_native_text_keeps_exact_real_registration_provenance(monkeypatch, agent):
    s, ctx, pid, reads, exact, store, receipt, _ = native(monkeypatch, agent=agent)
    basis, private, verified = service._evidence(s, ctx, pid, reads, (exact,))
    saved = basis[str(exact.id)]
    assert saved["source_origin"] == "registered_native_text"
    assert saved["registration_receipt_id"] == str(receipt.id)
    assert saved["registration_actor_id"] == str(receipt.actor_id)
    assert saved["registration_run_id"] == (str(receipt.run_id) if agent else None)
    assert "original_id" not in saved and "security_epoch" not in saved
    assert store.calls == 0 and not private and service.digest(exact) in verified


@pytest.mark.parametrize(
    "field",
    [
        "tenant_id",
        "category_id",
        "product_id",
        "subject_id",
        "subject_revision",
        "requester_id",
        "visibility",
    ],
)
def test_native_receipt_cannot_be_a_different_scope_subject_or_audience(monkeypatch, field):
    s, ctx, pid, reads, exact, _, receipt, _ = native(monkeypatch)
    setattr(
        receipt,
        field,
        2 if field == "subject_revision" else "private" if field == "visibility" else uuid4(),
    )
    with pytest.raises(DomainError) as error:
        service._evidence(s, ctx, pid, reads, (exact,))
    assert error.value.reason == "INTEGRATION_REQUIRED" and error.value.status == 503


def test_native_receipt_result_must_be_the_exact_registration_version(monkeypatch):
    s, ctx, pid, reads, exact, _, receipt, _ = native(monkeypatch)
    receipt.result = {"id": str(exact.id), "revision": True, "status": "active"}
    with pytest.raises(DomainError, match="登记身份"):
        service._evidence(s, ctx, pid, reads, (exact,))


def test_agent_native_text_requires_actual_exact_bound_run(monkeypatch):
    s, ctx, pid, reads, exact, _, _, run = native(monkeypatch, agent=True)
    run.writer_id = uuid4()
    with pytest.raises(DomainError) as error:
        service._evidence(s, ctx, pid, reads, (exact,))
    assert error.value.reason == "INTEGRATION_REQUIRED" and error.value.status == 503


def test_duplicate_or_missing_native_registration_is_unknown(monkeypatch):
    s, ctx, pid, reads, exact, _, receipt, _ = native(monkeypatch)
    for registered in ((), (receipt, receipt)):
        s.scalars = lambda _query, rows=registered: rows
        with pytest.raises(DomainError) as error:
            service._evidence(s, ctx, pid, reads, (exact,))
        assert error.value.reason == "INTEGRATION_REQUIRED" and error.value.status == 503


def test_uploaded_original_keeps_bytes_integrity_and_security_epoch(monkeypatch):
    s, ctx, pid, reads, exact, store = evidence(monkeypatch)
    basis, _, _ = service._evidence(s, ctx, pid, reads, (exact,))
    assert basis[str(exact.id)]["source_origin"] == "uploaded_original"
    assert basis[str(exact.id)]["original_revision"] == 1
    assert basis[str(exact.id)]["security_epoch"] == 7 and store.calls == 1


@pytest.mark.parametrize("io", [True, False])
def test_registered_native_text_needs_no_uploaded_object_store(monkeypatch, io):
    s, ctx, pid, reads, exact, store, receipt, _ = native(monkeypatch)
    s.get_bind = SimpleNamespace  # No object-store dependency is installed.
    basis, _, verified = service._evidence(s, ctx, pid, reads, (exact,), io=io)
    assert basis[str(exact.id)]["registration_receipt_id"] == str(receipt.id)
    assert service.digest(exact) in verified and store.calls == 0
    s.scalars = lambda query: ()
    with pytest.raises(DomainError) as failure:
        service._evidence(s, ctx, pid, reads, (exact,), io=io)
    assert failure.value.reason == "INTEGRATION_REQUIRED"
    assert "登记回执" in failure.value.message  # Absence of a store never waives provenance.


def test_uploaded_byte_io_still_requires_actual_object_store(monkeypatch):
    s, ctx, pid, reads, exact, store = evidence(monkeypatch)
    s.get_bind = SimpleNamespace
    with pytest.raises(DomainError) as failure:
        service._evidence(s, ctx, pid, reads, (exact,), io=True)
    assert failure.value.reason == "INTEGRATION_REQUIRED" and failure.value.status == 503
    assert store.calls == 0


def test_uploaded_metadata_refresh_keeps_safety_check_without_store_or_byte_io(monkeypatch):
    from pdos_next import original_security

    s, ctx, pid, reads, exact, store = evidence(monkeypatch)
    s.get_bind = SimpleNamespace
    checked, require_safe = [], original_security.require_safe

    def safety(*args, **kwargs):
        checked.append(args[2].id)
        return require_safe(*args, **kwargs)

    monkeypatch.setattr(original_security, "require_safe", safety)
    basis, _, verified = service._evidence(s, ctx, pid, reads, (exact,), io=False)
    assert checked == [UUID(basis[str(exact.id)]["original_id"])]
    assert basis[str(exact.id)]["security_epoch"] == 7
    assert service.digest(exact) in verified and store.calls == 0
