"""Pure direct-set selection and delegation; no synthetic authority verdicts."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from pdos_next.contracts import SourceRead
from pdos_next.domain.quality_execution import evidence
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.source_current import direct_source_basis


def reference(identity, revision=1, position="line:1;quote_sha256:" + "a" * 64):
    return SourceRef(id=identity, revision=revision, position=position)


def read(identity, revision=1):
    return SourceRead(artifact_id=identity, expected_revision=revision)


def test_no_direct_refs_do_not_read_or_expand_the_read_set(monkeypatch):
    class UnreadSet:
        def __iter__(self):
            raise AssertionError("Historical read set must not be traversed without direct refs")

    def unexpected(*args):
        raise AssertionError("No source authority or IO check was requested")

    monkeypatch.setattr(evidence, "check_source", unexpected)
    assert direct_source_basis(object(), object(), uuid4(), [], UnreadSet()) == ([], False)


def test_direct_refs_keep_all_positions_and_exact_existing_basis_without_upstream_reads(
    monkeypatch,
):
    lower, upper, upstream = UUID(int=1), UUID(int=2), UUID(int=3)
    session, ctx, product = object(), object(), SimpleNamespace(id=uuid4())
    original = {
        "id": str(lower),
        "revision": 1,
        "hash": "b" * 64,
        "status": "active",
        "owner_id": str(uuid4()),
        "visibility": "private",
        "source_kind": "uploaded_original",
        "original": {
            "id": str(uuid4()),
            "epoch": 7,
            "source_state": "active",
            "disposition": "active",
        },
    }
    native = {
        "id": str(upper),
        "revision": 2,
        "hash": "c" * 64,
        "status": "active",
        "owner_id": str(uuid4()),
        "visibility": "category",
        "source_kind": "registered_native_text",
        "registration": {
            "receipt_id": str(uuid4()),
            "actor_id": str(uuid4()),
            "requester_id": str(uuid4()),
            "run_id": None,
        },
    }
    refs = [
        reference(upper, 2),
        reference(lower),
        reference(lower, position="line:2;quote_sha256:" + "d" * 64),
    ]
    called = []

    def checked(s, caller, pid, ref):
        assert s is session and caller is ctx and pid == product.id
        assert ref.id != upstream
        called.append(ref)
        entry = original if ref.id == lower else native
        return [read(ref.id, ref.revision).model_dump(mode="json")], [entry], ref.id == lower

    monkeypatch.setattr(evidence, "check_source", checked)
    basis, private = direct_source_basis(
        session, ctx, product, refs, [read(upstream, 9), read(upper, 2), read(lower)]
    )
    assert called == refs
    assert basis == [original, native] and private is True
    assert basis[0]["original"]["epoch"] == 7
    assert basis[1]["registration"] is native["registration"]


@pytest.mark.parametrize(
    ("reads", "reason"),
    [([], "MISSING_REQUIRED_EVIDENCE"), ([2], "SOURCE_STALE"), ([1, 2], "SOURCE_STALE")],
)
def test_direct_revision_contract_fails_before_source_checks(monkeypatch, reads, reason):
    identity = uuid4()

    def unexpected(*args):
        raise AssertionError("Invalid declared revisions must fail before source IO")

    monkeypatch.setattr(evidence, "check_source", unexpected)
    with pytest.raises(DomainError) as raised:
        direct_source_basis(
            object(), object(), uuid4(), [reference(identity)], [read(identity, v) for v in reads]
        )
    assert raised.value.reason == reason


@pytest.mark.parametrize(
    "reason",
    ["SOURCE_UNAVAILABLE", "SOURCE_STALE", "INTEGRITY_MISMATCH", "MISSING_REQUIRED_EVIDENCE"],
)
def test_existing_scope_content_position_and_safety_failures_are_not_masked(monkeypatch, reason):
    identity = uuid4()
    failure = DomainError(reason, "Existing source guard failed")

    def rejected(*args):
        raise failure

    monkeypatch.setattr(evidence, "check_source", rejected)
    with pytest.raises(DomainError) as raised:
        direct_source_basis(object(), object(), uuid4(), [reference(identity)], [read(identity)])
    assert raised.value is failure


def test_unbound_domain_reference_keeps_the_existing_integration_guard(monkeypatch):
    ref = SourceRef(id=uuid4(), revision=1, kind="domain", position="fixed domain fact")
    failure = DomainError("INTEGRATION_REQUIRED", "Unbound domain source", 503)

    def rejected(s, ctx, pid, source):
        assert source is ref
        raise failure

    monkeypatch.setattr(evidence, "check_source", rejected)
    with pytest.raises(DomainError) as raised:
        direct_source_basis(object(), object(), uuid4(), [ref], [])
    assert raised.value is failure
