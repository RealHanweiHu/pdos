"""Pure exact security-row reuse; source and SQL IO use explicit unbound seams."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, make_transient_to_detached

from pdos_next.domain.verification_handoff import service
from pdos_next.engines.supply_cost.common import SnapshotRef
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, OriginalSecurity
from pdos_next.request_proof import request_proof
from pdos_next.service import Context


@pytest.fixture
def work(monkeypatch):
    actor, product, original = uuid4(), uuid4(), uuid4()
    ctx = Context(uuid4(), actor, actor, category_id=uuid4())
    captured = datetime(2026, 10, 8, 12, tzinfo=UTC)
    artifacts = {uuid4(): SimpleNamespace(original_id=original) for _ in range(2)}
    state = SimpleNamespace(epoch=7, source_state="active", disposition="active")
    with Session() as session:
        session.begin()
        session.info["read_snapshot"] = True
        session.info["scope"] = (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id)
        value = SimpleNamespace(
            session=session,
            ctx=ctx,
            product=product,
            original=original,
            artifacts=artifacts,
            states={(ctx.tenant_id, product, original): state},
            reads=[{"artifact_id": str(key), "expected_revision": 1} for key in artifacts],
            references=[],
            refs={
                f"artifact:{key}": SnapshotRef(
                    source_id=f"artifact:{key}",
                    version="1",
                    sha256="a" * 64,
                    captured_at=captured,
                    valid_until=captured + timedelta(hours=1),
                    state="current",
                )
                for key in artifacts
            },
            private=False,
            queries=[],
            source_checks=[],
        )

        def get(model, identity):
            assert model is Artifact
            return value.artifacts[identity]

        def scalar(statement):
            assert statement.column_descriptions[0]["entity"] is OriginalSecurity
            assert statement._for_update_arg is None
            params = statement.compile().params
            key = (params["tenant_id_1"], params["product_id_1"], params["original_id_1"])
            value.queries.append(key)
            return value.states.get(key)

        def sources(_session, context, scope, reads, references):
            value.source_checks.append((context, scope, list(reads), list(references)))
            return value.refs, value.private

        monkeypatch.setattr(session, "get", get)
        monkeypatch.setattr(session, "scalar", scalar)
        monkeypatch.setattr(service, "_sources", sources)
        try:
            yield value
        finally:
            # Dirty/deleted cases must not flush the unbound Session on teardown.
            session.rollback()


def basis(value):
    return service._basis(
        value.session, value.ctx, value.product, value.reads, value.references
    )


def test_same_original_exact_rr_row_is_shared_without_deduplicating_read_proof(work):
    first, private = basis(work)
    assert basis(work) == (first, private)
    assert len(work.queries) == 1
    assert work.queries[0] == (work.ctx.tenant_id, work.product, work.original)
    assert len(first["security"]) == len(work.reads) == 2
    assert all(row["epoch"] == 7 for row in first["security"])
    assert all("valid_until" not in row for row in first["refs"])
    assert len(work.source_checks) == 2


def test_different_originals_are_not_shared_by_sql_shape(work):
    original = uuid4()
    list(work.artifacts.values())[1].original_id = original
    work.states[(work.ctx.tenant_id, work.product, original)] = SimpleNamespace(
        epoch=11, source_state="active", disposition="active"
    )
    first, _ = basis(work)
    assert basis(work)[0] == first
    assert {row["epoch"] for row in first["security"]} == {7, 11}
    assert len(work.queries) == 2


def test_same_original_different_product_does_not_borrow_its_epoch(work):
    original_product = work.product
    assert all(row["epoch"] == 7 for row in basis(work)[0]["security"])
    work.product = uuid4()
    assert all(row["epoch"] is None for row in basis(work)[0]["security"])
    work.product = original_product
    assert all(row["epoch"] == 7 for row in basis(work)[0]["security"])
    assert len(work.queries) == 2


def test_category_original_keeps_the_original_product_equality_query(work):
    state = work.states.pop((work.ctx.tenant_id, work.product, work.original))
    work.states[(work.ctx.tenant_id, None, work.original)] = state
    first, _ = basis(work)
    assert basis(work)[0] == first
    assert first["security"] == [
        {
            "original_id": str(work.original),
            "epoch": None,
            "source_state": None,
            "disposition": None,
        }
    ] * 2
    assert work.queries == [(work.ctx.tenant_id, work.product, work.original)]


def test_basis_refs_and_private_remain_fresh_even_when_security_rows_are_shared(work):
    first, private = basis(work)
    key = sorted(work.refs)[0]
    work.refs[key] = work.refs[key].model_copy(update={"version": "2", "sha256": "b" * 64})
    work.private = True
    second, private_after = basis(work)
    assert not private and private_after and first["refs"] != second["refs"]
    assert first["security"] == second["security"] and len(work.queries) == 1
    assert len(work.source_checks) == 2


def test_current_source_guard_still_runs_before_using_shared_security_rows(work, monkeypatch):
    basis(work)

    def revoked(*_):
        raise DomainError("SOURCE_UNAVAILABLE", "Current original source withdrawn")

    monkeypatch.setattr(service, "_sources", revoked)
    with pytest.raises(DomainError) as caught:
        basis(work)
    assert caught.value.reason == "SOURCE_UNAVAILABLE" and len(work.queries) == 1


@pytest.mark.parametrize("mode", ["scope_gate_writer", "no_transaction", "fake"])
def test_non_rr_writer_and_fake_use_every_original_scalar_query(work, mode):
    if mode == "scope_gate_writer":
        work.session.info["read_snapshot"] = False
        request_proof(work.session).scope_locks.add(work.product)
    elif mode == "no_transaction":
        work.session.rollback()
    else:
        work.session = SimpleNamespace(
            info={"read_snapshot": True}, get=work.session.get, scalar=work.session.scalar
        )
    assert basis(work) == basis(work)
    assert len(work.queries) == len(work.reads) * 2


@pytest.mark.parametrize("pending", ["new", "dirty", "deleted"])
def test_pending_orm_state_does_not_reuse_an_earlier_rr_epoch(work, pending):
    basis(work)
    row = OriginalSecurity(id=uuid4(), epoch=1)
    if pending != "new":
        make_transient_to_detached(row)
    work.session.add(row)
    if pending == "dirty":
        row.epoch = 2
    elif pending == "deleted":
        work.session.delete(row)
    basis(work)
    assert len(work.queries) == 1 + len(work.reads)


def test_security_row_proof_never_survives_the_root_transaction(work):
    basis(work)
    work.session.rollback()
    with work.session.begin():
        key = (work.ctx.tenant_id, work.product, work.original)
        work.states[key] = SimpleNamespace(
            epoch=12, source_state="withdrawn", disposition="quarantined"
        )
        rows = basis(work)[0]["security"]
        assert all(row["epoch"] == 12 and row["source_state"] == "withdrawn" for row in rows)
        assert all(row["disposition"] == "quarantined" for row in rows)
    assert len(work.queries) == 2


def test_other_actor_cannot_borrow_security_rows_from_the_rr_transaction(work):
    basis(work)
    work.ctx = Context(work.ctx.tenant_id, uuid4(), uuid4(), category_id=work.ctx.category_id)
    with pytest.raises(DomainError) as caught:
        basis(work)
    assert caught.value.reason == "FORBIDDEN_SCOPE" and len(work.queries) == 1


def test_sources_without_uploaded_originals_add_no_security_query(work):
    for artifact in work.artifacts.values():
        artifact.original_id = None
    first, private = basis(work)
    assert basis(work) == (first, private)
    assert len(first["refs"]) == len(work.reads) and first["security"] == []
    assert not work.queries and len(work.source_checks) == 2
