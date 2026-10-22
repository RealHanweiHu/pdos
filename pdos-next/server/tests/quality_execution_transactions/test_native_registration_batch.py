"""No connection: exact RR raw-source/receipt batching keeps real source guards."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import inspect, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import UnboundExecutionError
from sqlalchemy.orm import Session, make_transient_to_detached

from pdos_next.domain.products.models import DefinitionSource
from pdos_next.domain.quality_execution import evidence
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Category, Grant, Principal, Product, Receipt, Run
from pdos_next.request_proof import request_proof
from pdos_next.service import Context, command_scope, digest, prove_sources, source_for


def _scope():
    return SimpleNamespace(
        tenant_id=UUID(int=100),
        category_id=UUID(int=101),
        actor_id=UUID(int=102),
        requester_id=UUID(int=102),
    ), UUID(int=103)


def _source(ctx, product, identity, revision=1, *, original_id=None):
    content = f"Exact source {identity} at revision {revision}"
    return SimpleNamespace(
        id=UUID(int=identity),
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        product_id=product,
        revision=revision,
        content=content,
        content_hash=digest(content),
        original_id=original_id,
        owner_id=ctx.requester_id,
        visibility="private",
        status="active",
    )


def _receipt(ctx, row):
    return Receipt(
        id=UUID(int=1000 + row.id.int + row.revision),
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        product_id=row.product_id,
        subject_type="artifact",
        operation="evidence.artifact.register",
        subject_id=row.id,
        subject_revision=row.revision,
        requester_id=row.owner_id,
        actor_id=row.owner_id,
        visibility=row.visibility,
        result={"id": str(row.id), "revision": row.revision},
        run_id=None,
    )


def _reads(rows):
    return [{"artifact_id": str(row.id), "expected_revision": row.revision} for row in rows]


def _rr(session, ctx):
    session.info["read_snapshot"] = True
    session.info["scope"] = (
        ctx.tenant_id,
        ctx.actor_id,
        ctx.requester_id,
        ctx.category_id,
    )


def _source_reader(monkeypatch, rows, events):
    by_identity = {(row.id, row.revision): row for row in rows}

    def checked(_session, _ctx, _pid, identity, revision):
        events.append(("source", identity, revision))
        return by_identity[(identity, revision)]

    monkeypatch.setattr(evidence, "source_for", checked)


def _no_scalar(_query):
    raise AssertionError("The batch must fill every native source's exact raw scalar key")


def _raw_artifacts_then_receipts(rows, selected):
    """SQL transport only; receipt-focused tests retain their separate guard seam."""

    def scalars(query):
        if query.column_descriptions[0]["entity"] is Artifact:
            identities = query.compile().params["id_1"]
            return [row for row in rows if row.id in identities]
        return selected(query)

    return scalars


def test_rr_native_receipts_batch_complete_nullable_scope_and_exact_versions(monkeypatch):
    ctx, pid = _scope()
    rows = [_source(ctx, pid, 1, 2), _source(ctx, None, 2, 4), _source(ctx, pid, 3, 7)]
    receipts = [_receipt(ctx, row) for row in rows]
    events, queries = [], []
    _source_reader(monkeypatch, rows, events)

    def selected(query):
        events.append(("receipts",))
        queries.append(query)
        return receipts

    with Session() as session:
        _rr(session, ctx)
        monkeypatch.setattr(session, "scalars", _raw_artifacts_then_receipts(rows, selected))
        monkeypatch.setattr(session, "scalar", _no_scalar)
        with session.begin():
            basis, private = evidence.source_basis(session, ctx, pid, _reads(rows))
            assert private and [value["revision"] for value in basis] == [2, 4, 7]
            assert events == [("source", row.id, row.revision) for row in rows] + [("receipts",)]
            compiled = queries[0].compile(dialect=postgresql.dialect())
            sql, params = str(compiled), compiled.params
            assert "action_receipts.tenant_id =" in sql
            assert "action_receipts.operation =" in sql
            assert "action_receipts.subject_type =" in sql
            assert "action_receipts.product_id IS NOT DISTINCT FROM NULL" in sql
            assert sql.count("(action_receipts.subject_id, action_receipts.subject_revision)") == 2
            assert "LIMIT" not in sql and queries[0]._for_update_arg is None
            assert ctx.tenant_id in params.values() and pid in params.values()
            assert "evidence.artifact.register" in params.values()
            assert "artifact" in params.values()
            pairs = [value for value in params.values() if isinstance(value, list)]
            assert {tuple(value) for value in pairs} == {
                ((rows[0].id, 2), (rows[2].id, 7)),
                ((rows[1].id, 4),),
            }
            proof = request_proof(session)
            for row, receipt in zip(rows, receipts, strict=True):
                key = (
                    "scope-scalar",
                    pid,
                    (Receipt, "artifact-registration", row.id, row.revision),
                )
                assert proof.scalar_rows[key] == (False, receipt)
            assert evidence.source_basis(session, ctx, pid, _reads(rows)) == (basis, private)
            assert len(queries) == 1
        with session.begin():
            assert evidence.source_basis(session, ctx, pid, _reads(rows)) == (basis, private)
            assert len(queries) == 2


def test_rr_missing_native_registration_is_cached_as_absence_and_rejected(monkeypatch):
    ctx, pid = _scope()
    rows = [_source(ctx, pid, 1), _source(ctx, None, 2, 3)]
    queries, events = [], []
    _source_reader(monkeypatch, rows, events)

    def selected(query):
        queries.append(query)
        return [_receipt(ctx, rows[0])]

    with Session() as session, session.begin():
        _rr(session, ctx)
        monkeypatch.setattr(session, "scalars", _raw_artifacts_then_receipts(rows, selected))
        monkeypatch.setattr(session, "scalar", _no_scalar)
        for _ in range(2):
            with pytest.raises(DomainError) as failure:
                evidence.source_basis(session, ctx, pid, _reads(rows))
            assert failure.value.reason == "SOURCE_UNAVAILABLE"
        assert len(queries) == 1
        key = ("scope-scalar", pid, (Receipt, "artifact-registration", rows[1].id, 3))
        assert request_proof(session).scalar_rows[key] == (False, None)


@pytest.mark.parametrize(
    "changed", ["owner", "visibility", "result_id", "result_revision", "actor"]
)
def test_rr_cached_raw_registration_still_runs_each_business_guard(monkeypatch, changed):
    ctx, pid = _scope()
    row = _source(ctx, pid, 1)
    receipt = _receipt(ctx, row)
    queries, events = [], []
    _source_reader(monkeypatch, [row], events)

    def selected(query):
        queries.append(query)
        return [receipt]

    with Session() as session, session.begin():
        _rr(session, ctx)
        monkeypatch.setattr(session, "scalars", _raw_artifacts_then_receipts([row], selected))
        monkeypatch.setattr(session, "scalar", _no_scalar)
        assert evidence.source_basis(session, ctx, pid, _reads([row]))[0]
        if changed == "owner":
            receipt.requester_id = UUID(int=999)
        elif changed == "visibility":
            receipt.visibility = "product"
        elif changed == "result_id":
            receipt.result["id"] = str(UUID(int=999))
        elif changed == "result_revision":
            receipt.result["revision"] = 99
        else:
            receipt.actor_id = UUID(int=999)
        with pytest.raises(DomainError) as failure:
            evidence.source_basis(session, ctx, pid, _reads([row]))
        assert failure.value.reason == "SOURCE_UNAVAILABLE" and len(queries) == 1
        assert events == [("source", row.id, 1), ("source", row.id, 1)]


@pytest.mark.parametrize("changed", ["missing", "tenant", "product", "requester", "writer"])
def test_rr_cached_native_ai_registration_rechecks_actual_origin_run(monkeypatch, changed):
    ctx, pid = _scope()
    row = _source(ctx, pid, 1)
    receipt = _receipt(ctx, row)
    receipt.run_id, receipt.actor_id = UUID(int=201), UUID(int=202)
    origin = SimpleNamespace(
        tenant_id=ctx.tenant_id,
        product_id=pid,
        requester_id=receipt.requester_id,
        writer_id=receipt.actor_id,
    )
    events, lookups = [], []
    _source_reader(monkeypatch, [row], events)

    def get_run(model, identity):
        assert model is evidence.Run and identity == receipt.run_id
        lookups.append(identity)
        return origin

    with Session() as session, session.begin():
        _rr(session, ctx)
        monkeypatch.setattr(
            session, "scalars", _raw_artifacts_then_receipts([row], lambda _query: [receipt])
        )
        monkeypatch.setattr(session, "scalar", _no_scalar)
        monkeypatch.setattr(session, "get", get_run)
        assert evidence.source_basis(session, ctx, pid, _reads([row]))[0]
        if changed == "missing":
            origin = None
        else:
            field = {
                "tenant": "tenant_id",
                "product": "product_id",
                "requester": "requester_id",
                "writer": "writer_id",
            }[changed]
            setattr(origin, field, UUID(int=999))
        with pytest.raises(DomainError) as failure:
            evidence.source_basis(session, ctx, pid, _reads([row]))
        assert failure.value.reason == "SOURCE_UNAVAILABLE"
        assert lookups == [receipt.run_id, receipt.run_id]


def test_rr_all_source_permissions_precede_native_receipt_query(monkeypatch):
    ctx, pid = _scope()
    rows = [_source(ctx, pid, 1), _source(ctx, pid, 2)]
    events = []

    def checked(_session, _ctx, _pid, identity, revision):
        events.append((identity, revision))
        if identity == rows[1].id:
            raise DomainError("SOURCE_UNAVAILABLE", "Actual second source access rejected", 403)
        return rows[0]

    monkeypatch.setattr(evidence, "source_for", checked)
    with Session() as session, session.begin():
        _rr(session, ctx)
        monkeypatch.setattr(session, "scalars", _raw_artifacts_then_receipts(rows, _no_scalar))
        monkeypatch.setattr(session, "scalar", _no_scalar)
        with pytest.raises(DomainError) as failure:
            evidence.source_basis(session, ctx, pid, _reads(rows))
        assert failure.value.status == 403
        assert events == [(row.id, row.revision) for row in rows]
        assert not request_proof(session).scalar_rows


@pytest.mark.parametrize("real_session", [True, False])
def test_non_rr_native_sources_keep_per_source_query_and_guard_order(monkeypatch, real_session):
    ctx, pid = _scope()
    rows = [_source(ctx, pid, 1), _source(ctx, None, 2, 3)]
    events = []
    _source_reader(monkeypatch, rows, events)
    receipts = {row.id: _receipt(ctx, row) for row in rows}

    def selected(query):
        params = query.compile().params
        identity = params["subject_id_1"]
        events.append(("receipt", identity))
        assert params["subject_revision_1"] == receipts[identity].subject_revision
        return receipts[identity]

    session = Session() if real_session else SimpleNamespace(scalar=selected)
    try:
        if real_session:
            monkeypatch.setattr(session, "scalar", selected)
            monkeypatch.setattr(session, "scalars", _no_scalar)
            session.begin()
        for _ in range(2):
            assert evidence.source_basis(session, ctx, pid, _reads(rows))[0]
        assert events == [
            value
            for _ in range(2)
            for row in rows
            for value in (("source", row.id, row.revision), ("receipt", row.id))
        ]
    finally:
        if real_session:
            session.close()


def test_rr_uploaded_original_security_query_is_not_replaced_by_native_batch(monkeypatch):
    ctx, pid = _scope()
    original = _source(ctx, None, 1, original_id=UUID(int=301))
    native = _source(ctx, pid, 2, 5)
    queries, events = [], []
    _source_reader(monkeypatch, [original, native], events)

    def selected(query):
        queries.append(query)
        params = query.compile().params
        assert params["original_id_1"] == original.original_id
        return None

    with Session() as session, session.begin():
        _rr(session, ctx)
        monkeypatch.setattr(
            session,
            "scalars",
            _raw_artifacts_then_receipts(
                [original, native], lambda _query: [_receipt(ctx, native)]
            ),
        )
        monkeypatch.setattr(session, "scalar", selected)
        with pytest.raises(DomainError) as failure:
            evidence.source_basis(session, ctx, pid, _reads([original, native]))
        assert failure.value.reason == "SOURCE_UNAVAILABLE" and len(queries) == 1


def test_rr_pending_write_rejects_before_native_receipt_batch(monkeypatch):
    ctx, pid = _scope()
    row = _source(ctx, pid, 1)
    events = []
    _source_reader(monkeypatch, [row], events)
    with Session() as session, session.begin():
        _rr(session, ctx)
        session.add(_receipt(ctx, row))
        monkeypatch.setattr(session, "scalars", _no_scalar)
        monkeypatch.setattr(session, "scalar", _no_scalar)
        with pytest.raises(DomainError) as failure:
            evidence.source_basis(session, ctx, pid, _reads([row]))
        assert failure.value.reason == "INVALID_READ_CONTEXT" and not events
        session.expunge_all()


def _actual_scope():
    ctx, pid = _scope()
    return Context(**vars(ctx)), pid


def _artifact(ctx, pid, identity, revision=1):
    return Artifact(
        **vars(_source(ctx, pid, identity, revision)),
        title=f"Native source {identity}",
        source_label="Pure SQL transport; real source_for guards",
    )


def _real_source_transport(session, monkeypatch, rows, queries):
    """Supply raw ORM rows only; never replace source_for or its business guards."""
    receipts = [_receipt(session.info["pure_ctx"], row) for row in rows]

    def scalars(query):
        model = query.column_descriptions[0]["entity"]
        queries.append((model, query))
        if model is Artifact:
            proof = request_proof(session)
            assert not proof.authority and not proof.scalar_rows
            identities = query.compile().params["id_1"]
            return [row for row in rows if row.id in identities]
        assert model is Receipt
        return receipts

    def scalar(query):
        # The real source guard may look for a sealed G0 citation after a
        # missing/mismatched native source. This fixture has no signed bridge.
        if query.column_descriptions[0]["entity"] is DefinitionSource:
            return None
        return _no_scalar(query)

    monkeypatch.setattr(session, "scalars", scalars)
    monkeypatch.setattr(session, "scalar", scalar)
    return receipts


def test_rr_artifact_batch_real_source_for_complete_raw_rows_nullable_scope_and_new_transaction(
    monkeypatch,
):
    ctx, pid = _actual_scope()
    rows = [_artifact(ctx, pid if index % 2 else None, index) for index in range(1, 25)]
    queries = []
    assert evidence.source_for is source_for
    with Session() as session:
        _rr(session, ctx)
        session.info["pure_ctx"] = ctx
        _real_source_transport(session, monkeypatch, rows, queries)
        with session.begin():
            basis, private = evidence.source_basis(session, ctx, pid, _reads(rows))
            assert private and [value["id"] for value in basis] == [str(row.id) for row in rows]
            artifact_queries = [query for model, query in queries if model is Artifact]
            assert len(artifact_queries) == 1
            query = artifact_queries[0]
            compiled = query.compile(dialect=postgresql.dialect())
            sql, params = str(compiled), compiled.params
            assert "artifact_versions.tenant_id =" in sql
            assert "artifact_versions.category_id =" in sql
            assert "artifact_versions.product_id IS NULL OR artifact_versions.product_id =" in sql
            assert "ORDER BY artifact_versions.id" in sql
            assert set(params["id_1"]) == {row.id for row in rows}
            assert {ctx.tenant_id, ctx.category_id, pid} <= set(
                value for value in params.values() if isinstance(value, UUID)
            )
            assert "LIMIT" not in sql and query._for_update_arg is None
            assert query.get_execution_options()["autoflush"] is False
            proof = request_proof(session)
            assert not proof.authority
            for row in rows:
                assert proof.read_rows[(Artifact, row.id)] is row
            assert evidence.source_basis(session, ctx, pid, _reads(rows)) == (basis, private)
            assert len(queries) == 2  # One complete Artifact and one complete Receipt read.
        with session.begin():
            assert evidence.source_basis(session, ctx, pid, _reads(rows)) == (basis, private)
            assert len(queries) == 4


def test_rr_artifact_batch_only_queries_missing_canonical_raw_rows(monkeypatch):
    ctx, pid = _actual_scope()
    rows = [_artifact(ctx, pid, 1), _artifact(ctx, None, 2), _artifact(ctx, pid, 3)]
    queries = []
    with Session() as session, session.begin():
        _rr(session, ctx)
        session.info["pure_ctx"] = ctx
        proof = request_proof(session)
        # An earlier exact RR reader held this raw ORM row, without an authority verdict.
        proof.read_rows[(Artifact, rows[0].id)] = rows[0]
        _real_source_transport(session, monkeypatch, rows, queries)
        basis, _private = evidence.source_basis(session, ctx, pid, _reads(rows))
        artifact_queries = [query for model, query in queries if model is Artifact]
        assert len(artifact_queries) == 1
        assert set(artifact_queries[0].compile().params["id_1"]) == {rows[1].id, rows[2].id}
        assert [value["id"] for value in basis] == [str(row.id) for row in rows]
        assert not proof.authority


@pytest.mark.parametrize("changed", ["tenant", "category", "product", "status", "revision", "hash"])
def test_rr_artifact_batch_real_source_for_rechecks_every_raw_scope_version_and_content(
    monkeypatch,
    changed,
):
    ctx, pid = _actual_scope()
    row, queries = _artifact(ctx, pid, 1), []
    reads = _reads([row])
    assert evidence.source_for is source_for
    with Session() as session, session.begin():
        _rr(session, ctx)
        session.info["pure_ctx"] = ctx
        _real_source_transport(session, monkeypatch, [row], queries)
        assert evidence.source_basis(session, ctx, pid, reads)[0]
        if changed in ("tenant", "category", "product"):
            setattr(row, f"{changed}_id", UUID(int=999))
        elif changed == "status":
            row.status = "withdrawn"
        elif changed == "revision":
            row.revision += 1
        else:
            row.content = "Changed bytes without changing immutable content hash"
        with pytest.raises(DomainError) as failure:
            evidence.source_basis(session, ctx, pid, reads)
        assert failure.value.reason == {
            "revision": "SOURCE_STALE",
            "hash": "INTEGRITY_MISMATCH",
        }.get(changed, "SOURCE_UNAVAILABLE")
        if changed in ("tenant", "category", "product"):
            assert failure.value.status == 403
        assert len(queries) == 2


def test_rr_artifact_batch_real_source_for_missing_row_keeps_first_source_rejection_order(
    monkeypatch,
):
    ctx, pid = _actual_scope()
    first, missing = _artifact(ctx, pid, 1), _artifact(ctx, None, 2)
    reads = _reads([first, missing])
    queries, scalar_queries, signed_queries = [], [], []
    with Session() as session, session.begin():
        _rr(session, ctx)
        session.info["pure_ctx"] = ctx
        _real_source_transport(session, monkeypatch, [first], queries)

        def unavailable(query):
            if query.column_descriptions[0]["entity"] is DefinitionSource:
                signed_queries.append(query)
                return None  # No actual sealed G0 citation in this native fixture.
            scalar_queries.append(query)
            assert query.column_descriptions[0]["entity"] is Artifact
            assert query.compile().params["id_1"] == missing.id
            return None  # Explicit denied/missing SQL row, never an ACL-positive substitute.

        monkeypatch.setattr(session, "scalar", unavailable)
        first.revision += 1
        with pytest.raises(DomainError) as failure:
            evidence.source_basis(session, ctx, pid, reads)
        assert failure.value.reason == "SOURCE_STALE" and not scalar_queries and not signed_queries
        first.revision -= 1
        with pytest.raises(DomainError) as failure:
            evidence.source_basis(session, ctx, pid, reads)
        assert failure.value.reason == "SOURCE_UNAVAILABLE" and failure.value.status == 403
        assert len(scalar_queries) == len(signed_queries) == 1
        assert all(model is Artifact for model, _query in queries)
        assert not request_proof(session).scalar_rows


def test_rr_artifact_batch_conflicting_complete_read_set_fails_before_any_sql(monkeypatch):
    ctx, pid = _actual_scope()
    with Session() as session, session.begin():
        _rr(session, ctx)
        monkeypatch.setattr(session, "scalar", _no_scalar)
        monkeypatch.setattr(session, "scalars", _no_scalar)
        with pytest.raises(DomainError) as failure:
            evidence.source_basis(
                session,
                ctx,
                pid,
                [
                    {"artifact_id": str(UUID(int=1)), "expected_revision": 1},
                    {"artifact_id": str(UUID(int=1)), "expected_revision": 2},
                ],
            )
        assert failure.value.reason == "SOURCE_STALE"
        assert "request_proof" not in session.info


@pytest.mark.parametrize("changed", ["identity", "cancel_epoch"])
def test_rr_artifact_raw_rows_cannot_borrow_another_full_context(monkeypatch, changed):
    ctx, pid = _actual_scope()
    row, queries = _artifact(ctx, pid, 1), []
    with Session() as session, session.begin():
        _rr(session, ctx)
        session.info["pure_ctx"] = ctx
        _real_source_transport(session, monkeypatch, [row], queries)
        assert evidence.source_basis(session, ctx, pid, _reads([row]))[0]
        changed_ctx = (
            replace(ctx, actor_id=UUID(int=999), requester_id=UUID(int=999))
            if changed == "identity"
            else replace(ctx, cancel_epoch=1)
        )
        _rr(session, changed_ctx)
        with pytest.raises(DomainError) as failure:
            evidence.source_basis(session, changed_ctx, pid, _reads([row]))
        assert failure.value.reason == "INVALID_READ_CONTEXT"
        assert len(queries) == 2


@pytest.mark.parametrize("changed", ["direct_dml", "rollback", "scope", "pending"])
def test_rr_artifact_raw_rows_are_not_published_after_query_boundary_change(monkeypatch, changed):
    ctx, pid = _actual_scope()
    row = _artifact(ctx, pid, 1)
    with Session() as session, session.begin():
        _rr(session, ctx)
        proof = request_proof(session)

        def selected(query):
            assert query.column_descriptions[0]["entity"] is Artifact
            if changed == "direct_dml":
                with pytest.raises(UnboundExecutionError):
                    session.execute(update(Artifact).values(status="withdrawn"))
            elif changed == "rollback":
                session.rollback()
            elif changed == "scope":
                _rr(session, replace(ctx, actor_id=UUID(int=999)))
            else:
                session.add(_receipt(ctx, row))
            return [row]

        monkeypatch.setattr(session, "scalars", selected)
        monkeypatch.setattr(session, "scalar", _no_scalar)
        try:
            with pytest.raises(DomainError) as failure:
                evidence.source_basis(session, ctx, pid, _reads([row]))
            assert failure.value.reason == (
                "FORBIDDEN_SCOPE" if changed == "scope" else "INVALID_READ_CONTEXT"
            )
            assert (Artifact, row.id) not in proof.read_rows
            assert ("quality-artifact-raw-scope",) not in proof.read_rows
            assert not proof.sources and not proof.scalar_rows
        finally:
            session.expunge_all()


def test_non_rr_real_source_for_keeps_each_artifact_then_receipt_query(monkeypatch):
    ctx, pid = _actual_scope()
    rows = [_artifact(ctx, pid, 1), _artifact(ctx, None, 2)]
    receipts = {row.id: _receipt(ctx, row) for row in rows}
    by_id, events = {row.id: row for row in rows}, []
    assert evidence.source_for is source_for
    with Session() as session, session.begin():
        session.info["scope"] = (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id)

        def selected(query):
            model = query.column_descriptions[0]["entity"]
            params = query.compile().params
            identity = params["id_1"] if model is Artifact else params["subject_id_1"]
            events.append((model, identity))
            return by_id[identity] if model is Artifact else receipts[identity]

        monkeypatch.setattr(session, "scalar", selected)
        monkeypatch.setattr(session, "scalars", _no_scalar)
        for _ in range(2):
            assert evidence.source_basis(session, ctx, pid, _reads(rows))[0]
        assert events == [
            event
            for _ in range(2)
            for row in rows
            for event in ((Artifact, row.id), (Receipt, row.id))
        ]


def _writer_transport(session, monkeypatch, ctx, pid, rows):
    """Real gate/prove_sources code; transport witnesses SQL, not a PG lock claim."""
    product = Product(
        id=pid,
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        revision=1,
    )
    category = Category(
        id=ctx.category_id,
        tenant_id=ctx.tenant_id,
        revision=1,
        lifecycle_epoch=1,
    )
    person = Principal(
        id=ctx.actor_id,
        tenant_id=ctx.tenant_id,
        active=True,
        kind="human",
        access_epoch=1,
    )
    grant = Grant(
        id=UUID(int=401),
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        principal_id=ctx.actor_id,
        can_write=True,
        expires_at=None,
        access_epoch=1,
    )
    state = {"rows": rows, "receipts": [_receipt(ctx, row) for row in rows], "queries": []}
    original_execute = session.execute
    session.info["scope"] = (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id)
    session.info["read_snapshot"] = False

    def get(model, identity):
        assert model is Product and identity == pid
        return product

    def execute(query):
        assert [value["entity"] for value in query.column_descriptions] == [Principal, Grant]
        assert query._for_update_arg is not None and query._for_update_arg.read is True
        return SimpleNamespace(all=lambda: [(person, grant)])

    def scalar(query):
        model = query.column_descriptions[0]["entity"]
        if model is Product:
            assert query._for_update_arg is not None
            return product
        if model is Artifact:
            if query.column_descriptions[0]["expr"] is Artifact:
                assert query._for_update_arg is not None and query._for_update_arg.read is True
                identity = query.compile().params["id_1"]
                return next(row for row in rows if row.id == identity)
            return next((row.id for row in rows if row.product_id is None), None)
        assert model is Receipt
        state["queries"].append(("scalar", query, request_proof(session).mutation_epoch))
        identity = query.compile().params["subject_id_1"]
        return next((row for row in state["receipts"] if row.subject_id == identity), None)

    def scalars(query):
        model = query.column_descriptions[0]["entity"]
        if model is Category:
            assert query._for_update_arg is not None
            return [category]
        if model is Artifact:
            assert query._for_update_arg is not None and query._for_update_arg.read is True
            return rows
        assert model is Receipt
        state["queries"].append(("batch", query, request_proof(session).mutation_epoch))
        return state["receipts"]

    monkeypatch.setattr(session, "get", get)
    monkeypatch.setattr(session, "execute", execute)
    monkeypatch.setattr(session, "scalar", scalar)
    monkeypatch.setattr(session, "scalars", scalars)
    reads = [SimpleNamespace(artifact_id=row.id, expected_revision=row.revision) for row in rows]
    command = SimpleNamespace(
        operation="quality.issue.triage",
        product_id=pid,
        source_read_set=reads,
    )
    assert command_scope(session, ctx, command, lock=True) is product
    prove_sources(session, ctx, pid, reads)
    # Boundary tests exercise the actual ORM mutation event instead of the transport seam.
    monkeypatch.setattr(session, "execute", original_execute)
    return state


def test_writer_lazy_native_receipt_batch_uses_real_gate_locked_raws_and_complete_nullable_set(
    monkeypatch,
):
    ctx, pid = _actual_scope()
    rows = [_artifact(ctx, pid if index % 2 else None, index) for index in range(1, 25)]
    assert evidence.source_for is source_for
    with Session() as session, session.begin():
        state = _writer_transport(session, monkeypatch, ctx, pid, rows)
        proof = request_proof(session)
        assert pid in proof.scope_locks and (Category, ctx.category_id) in proof.scope_locks
        assert all(proof.read_rows[(Artifact, ("locked", row.id))] is True for row in rows)
        basis, private = evidence.source_basis(session, ctx, pid, _reads(rows))
        assert private and [value["id"] for value in basis] == [str(row.id) for row in rows]
        assert len(state["queries"]) == 1 and state["queries"][0][0] == "batch"
        query = state["queries"][0][1]
        compiled = query.compile(dialect=postgresql.dialect())
        sql, params = str(compiled), compiled.params
        assert "action_receipts.tenant_id =" in sql and "action_receipts.category_id =" in sql
        assert "action_receipts.product_id IS NOT DISTINCT FROM NULL" in sql
        assert "LIMIT" not in sql and query._for_update_arg is None
        pairs = [value for value in params.values() if isinstance(value, list)]
        assert {pair for group in pairs for pair in group} == {
            (row.id, row.revision) for row in rows
        }
        assert evidence.source_basis(session, ctx, pid, _reads(rows)) == (basis, private)
        assert len(state["queries"]) == 1


@pytest.mark.parametrize("first_receipt_invalid", [True, False])
def test_writer_lazy_native_receipt_batch_keeps_first_error_before_later_source_guard(
    monkeypatch,
    first_receipt_invalid,
):
    ctx, pid = _actual_scope()
    rows = [_artifact(ctx, pid, 1), _artifact(ctx, pid, 2)]
    with Session() as session, session.begin():
        state = _writer_transport(session, monkeypatch, ctx, pid, rows)
        rows[1].status = "withdrawn"
        if first_receipt_invalid:
            state["receipts"][0].requester_id = UUID(int=999)
        with pytest.raises(DomainError) as failure:
            evidence.source_basis(session, ctx, pid, _reads(rows))
        assert failure.value.reason == "SOURCE_UNAVAILABLE"
        assert failure.value.message == (
            "原生文本缺少精确登记来源证明。"
            if first_receipt_invalid
            else "来源已撤回，不能继续使用。"
        )
        assert len(state["queries"]) == 1 and state["queries"][0][0] == "batch"


@pytest.mark.parametrize("changed", ["missing", "owner", "result", "origin_run"])
def test_writer_lazy_native_raw_receipt_cache_never_replaces_business_guards(monkeypatch, changed):
    ctx, pid = _actual_scope()
    rows = [_artifact(ctx, pid, 1), _artifact(ctx, pid, 2)]
    with Session() as session, session.begin():
        state = _writer_transport(session, monkeypatch, ctx, pid, rows)
        receipt = state["receipts"][1]
        if changed == "missing":
            state["receipts"].remove(receipt)
        elif changed == "owner":
            receipt.requester_id = UUID(int=999)
        elif changed == "result":
            receipt.result = {"id": str(receipt.subject_id), "revision": 99}
        else:
            receipt.run_id, receipt.actor_id = UUID(int=901), UUID(int=902)

            def missing_run(model, identity):
                assert model is Run and identity == receipt.run_id
                return None

            monkeypatch.setattr(session, "get", missing_run)
        with pytest.raises(DomainError) as failure:
            evidence.source_basis(session, ctx, pid, _reads(rows))
        assert failure.value.reason == "SOURCE_UNAVAILABLE"
        assert len(state["queries"]) == 1 and state["queries"][0][0] == "batch"


def test_writer_lazy_native_receipts_unloaded_later_raw_keeps_first_receipt_error(monkeypatch):
    ctx, pid = _actual_scope()
    rows = [_artifact(ctx, pid, 1), _artifact(ctx, pid, 2)]
    assert evidence.source_for is source_for
    with Session() as session, session.begin():
        state = _writer_transport(session, monkeypatch, ctx, pid, rows)
        # Deleting a transient field leaves its old value in committed_state,
        # which unloaded excludes. Attach a clean ORM identity and expire it
        # through the real Session API instead, without fetching a later source.
        make_transient_to_detached(rows[1])
        session.add(rows[1])
        session.expire(rows[1], ["content"])
        assert inspect(rows[1]).persistent and not session.new and not session.dirty
        assert "content" in inspect(rows[1]).unloaded
        state["receipts"][0].requester_id = UUID(int=999)
        try:
            with pytest.raises(DomainError) as failure:
                evidence.source_basis(session, ctx, pid, _reads(rows))
            assert failure.value.reason == "SOURCE_UNAVAILABLE"
            assert failure.value.message == "原生文本缺少精确登记来源证明。"
            assert len(state["queries"]) == 1 and state["queries"][0][0] == "scalar"
        finally:
            session.expunge(rows[1])


@pytest.mark.parametrize(
    "changed",
    [
        "unheld",
        "wrong_pid",
        "category_only",
        "unlocked_source",
        "missing_raw",
        "missing_category_gate",
        "pending",
    ],
)
def test_writer_lazy_native_receipts_ineligible_material_keeps_original_scalar_queries(
    monkeypatch,
    changed,
):
    ctx, pid = _actual_scope()
    rows = [
        _artifact(ctx, pid, 1),
        _artifact(ctx, None if changed == "missing_category_gate" else pid, 2),
    ]
    with Session() as session, session.begin():
        state = _writer_transport(session, monkeypatch, ctx, pid, rows)
        proof = request_proof(session)
        if changed in ("unheld", "wrong_pid", "category_only"):
            proof.scope_locks.discard(pid)
            if changed == "wrong_pid":
                proof.scope_locks.add(UUID(int=999))
            elif changed == "category_only":
                proof.scope_locks.add((Category, ctx.category_id))
        elif changed == "unlocked_source":
            proof.read_rows.pop((Artifact, ("locked", rows[1].id)))
        elif changed == "missing_raw":
            key = (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id, pid, rows[1].id)
            proof.sources.pop(key)
            proof.source_rows.pop(key)
            proof.read_rows.pop((Artifact, rows[1].id), None)
        elif changed == "missing_category_gate":
            proof.scope_locks.remove((Category, ctx.category_id))
        else:
            session.add(Receipt(id=UUID(int=999)))
        try:
            assert len(evidence.source_basis(session, ctx, pid, _reads(rows))[0]) == 2
            assert [kind for kind, _query, _epoch in state["queries"]] == ["scalar", "scalar"]
        finally:
            session.expunge_all()


def test_writer_lazy_native_receipts_full_context_change_cannot_borrow_cached_rows(monkeypatch):
    ctx, pid = _actual_scope()
    row = _artifact(ctx, pid, 1)
    with Session() as session, session.begin():
        state = _writer_transport(session, monkeypatch, ctx, pid, [row])
        assert evidence.source_basis(session, ctx, pid, _reads([row]))[0]
        with pytest.raises(DomainError) as failure:
            evidence.source_basis(session, replace(ctx, cancel_epoch=1), pid, _reads([row]))
        assert failure.value.reason == "INVALID_READ_CONTEXT"
        assert len(state["queries"]) == 1


@pytest.mark.parametrize("changed", ["direct_dml", "rollback", "pending", "raw", "scope"])
def test_writer_lazy_native_receipts_query_boundary_change_rejects_without_raw_publication(
    monkeypatch,
    changed,
):
    ctx, pid = _actual_scope()
    rows = [_artifact(ctx, pid, 1), _artifact(ctx, pid, 2)]
    with Session() as session, session.begin():
        _writer_transport(session, monkeypatch, ctx, pid, rows)
        proof = request_proof(session)

        def changed_query(query):
            assert query.column_descriptions[0]["entity"] is Receipt
            if changed == "direct_dml":
                with pytest.raises(UnboundExecutionError):
                    session.execute(update(Artifact).values(status="withdrawn"))
            elif changed == "rollback":
                session.rollback()
            elif changed == "pending":
                session.add(Receipt(id=UUID(int=999)))
            elif changed == "raw":
                rows[1].content = "Raw source changed during receipt IO"
            else:
                session.info["scope"] = (
                    ctx.tenant_id,
                    UUID(int=999),
                    ctx.requester_id,
                    ctx.category_id,
                )
            return [_receipt(ctx, row) for row in rows]

        monkeypatch.setattr(session, "scalars", changed_query)
        try:
            with pytest.raises(DomainError) as failure:
                evidence.source_basis(session, ctx, pid, _reads(rows))
            assert failure.value.reason == (
                "FORBIDDEN_SCOPE" if changed == "scope" else "INVALID_READ_CONTEXT"
            )
            assert not proof.scalar_rows
            assert ("quality-native-writer-scope", pid) not in proof.read_rows
        finally:
            session.expunge_all()


@pytest.mark.parametrize("boundary", ["direct_dml", "savepoint_rollback"])
def test_writer_lazy_native_receipts_new_epoch_reads_again_after_real_orm_boundary(
    monkeypatch,
    boundary,
):
    ctx, pid = _actual_scope()
    rows = [_artifact(ctx, pid, 1), _artifact(ctx, pid, 2)]
    with Session() as session, session.begin():
        state = _writer_transport(session, monkeypatch, ctx, pid, rows)
        basis = evidence.source_basis(session, ctx, pid, _reads(rows))
        proof = request_proof(session)
        old_epoch = proof.mutation_epoch
        assert len(state["queries"]) == 1
        if boundary == "direct_dml":
            with pytest.raises(UnboundExecutionError):
                session.execute(update(Artifact).values(status="withdrawn"))
        else:
            savepoint = session.begin_nested()
            savepoint.rollback()
        assert proof.mutation_epoch > old_epoch and not proof.scalar_rows
        # The real owner reacquires any discarded gate/source proof, not a copied positive result.
        refreshed = _writer_transport(session, monkeypatch, ctx, pid, rows)
        assert evidence.source_basis(session, ctx, pid, _reads(rows)) == basis
        assert len(refreshed["queries"]) == 1 and refreshed["queries"][0][0] == "batch"
        assert refreshed["queries"][0][2] > state["queries"][0][2]
