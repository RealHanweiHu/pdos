import hashlib
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.domain.change_execution import service
from pdos_next.errors import DomainError
from pdos_next.object_storage import ObjectRef
from pdos_next.schemas.verification.contracts import SourceRef

from .test_pure import AT, fixture


def evidence(monkeypatch, *, tamper=False, no_original=False, too_large=False):
    from pdos_next import original_security, originals
    from pdos_next import service as common

    content = "  exact original line  \n第二行\n"
    raw = content.encode()
    pid, tenant, actor, identity, original_id = (uuid4() for _ in range(5))
    category = uuid4()
    source = SimpleNamespace(
        category_id=category,
        product_id=pid,
        id=identity,
        revision=1,
        content=content,
        content_hash=common.digest(content),
        original_id=None if no_original else original_id,
        visibility="category",
        owner_id=actor,
    )
    original = SimpleNamespace(
        category_id=category,
        product_id=pid,
        id=original_id,
        revision=1,
        status="parsed",
        content_hash=hashlib.sha256(raw).hexdigest(),
        visibility="category",
        owner_id=actor,
    )
    ref = ObjectRef(
        original_id,
        1,
        original.content_hash,
        service.MAX_ORIGINAL_BYTES + 1 if too_large else len(raw),
        "text/plain",
        f"originals/{original_id.hex}/v1/{original.content_hash}",
    )

    class Store:
        calls = 0

        def read_original(self, ref):
            self.calls += 1
            return raw + b"tamper" if tamper else raw

    store = Store()
    session = SimpleNamespace(
        info={},
        get_bind=lambda: SimpleNamespace(_pdos_change_store=store),
        scalars=lambda _query: (),
    )
    ctx = SimpleNamespace(
        tenant_id=tenant, actor_id=actor, requester_id=actor, category_id=category
    )
    monkeypatch.setattr(common, "source_for", lambda *args: source)
    monkeypatch.setattr(originals, "require_original", lambda *args, **kwargs: original)
    monkeypatch.setattr(originals, "object_reference", lambda value: ref)
    monkeypatch.setattr(original_security, "require_safe", lambda *args, **kwargs: (7, None))
    read = [{"artifact_id": str(identity), "expected_revision": 1}]
    exact = SourceRef(
        id=identity,
        revision=1,
        kind="artifact",
        position="line:1;quote_sha256:"
        + hashlib.sha256(content.splitlines()[0].encode()).hexdigest(),
    )
    return session, ctx, pid, read, exact, store


def test_exact_full_line_and_real_port_bytes_required(monkeypatch):
    session, ctx, pid, reads, source, store = evidence(monkeypatch)
    basis, private, verified = service._evidence(session, ctx, pid, reads, (source,))
    assert store.calls == 1 and not private and service.digest(source) in verified
    assert basis[str(source.id)]["security_epoch"] == 7


@pytest.mark.parametrize(
    "position",
    [
        "free-form source",
        "line:0;quote_sha256:" + "a" * 64,
        "line:3;quote_sha256:" + "a" * 64,
        "line:1;quote_sha256:" + "a" * 64,
    ],
)
def test_client_position_or_substring_hash_cannot_prove_full_line(monkeypatch, position):
    session, ctx, pid, reads, source, _ = evidence(monkeypatch)
    selected = source.model_copy(update={"position": position})
    with pytest.raises(DomainError) as error:
        service._evidence(session, ctx, pid, reads, (selected,))
    assert error.value.reason == "MISSING_REQUIRED_EVIDENCE"


def test_tampered_original_rejected_before_staging(monkeypatch):
    session, ctx, pid, reads, source, _ = evidence(monkeypatch, tamper=True)
    with pytest.raises(DomainError) as error:
        service._evidence(session, ctx, pid, reads, (source,))
    assert error.value.reason == "INTEGRITY_MISMATCH"


def test_unproven_native_text_is_integration_required_not_a_positive_stub(monkeypatch):
    session, ctx, pid, reads, source, store = evidence(monkeypatch, no_original=True)
    with pytest.raises(DomainError) as error:
        service._evidence(session, ctx, pid, reads, (source,))
    assert error.value.status == 503 and error.value.reason == "INTEGRATION_REQUIRED"
    assert store.calls == 0


def test_bounded_original_size_is_checked_before_io(monkeypatch):
    session, ctx, pid, reads, source, store = evidence(monkeypatch, too_large=True)
    with pytest.raises(DomainError) as error:
        service._evidence(session, ctx, pid, reads, (source,))
    assert error.value.reason == "SOURCE_UNAVAILABLE" and store.calls == 0


def test_metadata_refresh_does_not_repeat_storage_effect(monkeypatch):
    session, ctx, pid, reads, source, store = evidence(monkeypatch)
    basis, _, _ = service._evidence(session, ctx, pid, reads, (source,), io=False)
    assert basis[str(source.id)]["security_epoch"] == 7 and store.calls == 0


def capture_bound():
    work = fixture()
    authority = {"operation": "change.impact.compute", "qualified": True}
    basis = {"runtime_stamp": "same", "evidence": {"old": {"security_epoch": 7}}, "owners": {}}
    capture = SimpleNamespace(
        expires_at=work.snapshot.expires_at, authority_snapshot=authority, source_basis=basis
    )
    bound = SimpleNamespace(
        coverage=None,
        capture=capture,
        graph=work.snapshot,
        scope=work.scope,
        target=work.reader.target,
        authority=authority,
        source_basis=basis,
    )
    return work, bound


def test_capture_can_add_sourced_hypothesis_without_ignoring_old_security_epoch(monkeypatch):
    work, bound = capture_bound()
    monkeypatch.setattr(service, "now", lambda: AT + timedelta(seconds=1))
    monkeypatch.setattr(service, "OwnerReader", lambda *args: work.reader)
    monkeypatch.setattr(service, "_issue_loader", lambda *args: object())
    bound.source_basis = {
        **bound.source_basis,
        "evidence": {
            **bound.source_basis["evidence"],
            "new-hypothesis-source": {"security_epoch": 1},
        },
    }
    service._capture_valid(object(), object(), work.scope.product_id, bound)
    bound.source_basis["evidence"]["old"] = {"security_epoch": 8}
    with pytest.raises(DomainError) as error:
        service._capture_valid(object(), object(), work.scope.product_id, bound)
    assert error.value.reason == "SOURCE_STALE"


def test_capture_end_exclusive_expiry_never_extended(monkeypatch):
    work, bound = capture_bound()
    monkeypatch.setattr(service, "now", lambda: work.snapshot.expires_at)
    with pytest.raises(DomainError) as error:
        service._capture_valid(object(), object(), work.scope.product_id, bound)
    assert error.value.reason == "GRAPH_CAPTURE_EXPIRED"


def test_capture_authority_operation_and_epoch_must_match(monkeypatch):
    work, bound = capture_bound()
    monkeypatch.setattr(service, "now", lambda: AT + timedelta(seconds=1))
    bound.authority = {"operation": "change.request.create", "qualified": True}
    with pytest.raises(DomainError) as error:
        service._capture_valid(object(), object(), work.scope.product_id, bound)
    assert error.value.reason == "SOURCE_STALE"


def test_positive_qualification_cannot_survive_expiry_at_final_staging_boundary():
    operation, purpose = "change.impact.compute", "synthetic change scope"
    bound = SimpleNamespace(
        authority={
            "operation": operation,
            "purpose": purpose,
            "roles": ["engineering"],
            "synthetic": True,
            "fact_refs": [
                dict(
                    kind=kind,
                    role="engineering",
                    nature="synthetic",
                    state="active",
                    operations=[operation],
                    purposes=[purpose],
                    valid_from=(AT - timedelta(hours=1)).isoformat(),
                    valid_until=AT.isoformat(),
                )
                for kind in ("duty", "qualification")
            ],
        },
        graph=None,
        coverage=None,
    )
    with pytest.raises(DomainError) as error:
        service._valid_at(bound, AT)
    assert error.value.reason == "SOURCE_STALE"
    for fact in bound.authority["fact_refs"]:
        fact["valid_until"] = (AT + timedelta(seconds=1)).isoformat()
    service._valid_at(bound, AT)
