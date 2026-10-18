"""Host/UOW boundaries with real ORM objects; SQLite is not an RLS qualification.

Owner-result and PostgreSQL GUC transport are named seams, as is permission IO.
The Product gate, Session transactions, mapper reconstruction and fixed hash guards
are the production code. PostgreSQL locking/RLS remain the actual contract's job.
"""

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next import service as host
from pdos_next.contracts import Command
from pdos_next.domain.build_start import service as starts
from pdos_next.domain.builds import service as builds
from pdos_next.domain.builds.models import Build
from pdos_next.errors import DomainError
from pdos_next.models import Category, Product
from pdos_next.request_proof import request_proof

AT = datetime(2026, 10, 9, 12, tzinfo=UTC)


def sqlite_table(engine, model):
    """Create one real mapped table in SQLite, minus PostgreSQL-only CHECK syntax.

    The category root lock is production behaviour (`category_lifecycle_fence`),
    so the host boundary needs the actual table. Only the `key ~ '...'` regex
    check is dropped; SQLite cannot parse it and this file never asserts on it.
    """
    from sqlalchemy import CheckConstraint, MetaData
    from sqlalchemy.schema import CreateTable

    table = model.__table__.to_metadata(MetaData())
    for constraint in list(table.constraints):
        if isinstance(constraint, CheckConstraint) and "~" in str(constraint.sqltext):
            table.constraints.discard(constraint)
    with engine.begin() as connection:
        # Foreign keys are left out of the DDL: their target tables are not part
        # of this one-table copy, and SQLite would not enforce them anyway.
        connection.execute(CreateTable(table, include_foreign_key_constraints=[]))
    return table


def mapped(model, **values):
    """Use real attribute names; do not invent a mapped audience column."""
    keys = {attribute.key for attribute in model.__mapper__.column_attrs}
    assert set(values) <= keys
    return model(**{**dict.fromkeys(keys), **values})


@pytest.fixture
def owners():
    tenant, category, product, project, actor, build_id, engineering, manufacturing = (
        uuid4() for _ in range(8)
    )
    ctx = host.Context(tenant, actor, actor, category_id=category)
    scope = {
        "tenant_id": tenant,
        "category_id": category,
        "product_id": product,
        "project_id": project,
        "build_id": build_id,
        "created_at": AT,
    }
    build = mapped(
        Build,
        id=build_id,
        tenant_id=tenant,
        category_id=category,
        product_id=product,
        project_id=project,
        owner_id=actor,
        engineering_configuration_id=engineering,
        manufacturing_configuration_id=manufacturing,
        revision=1,
    )
    material = {
        **scope,
        "engineering_configuration_id": engineering,
        "manufacturing_configuration_id": manufacturing,
        "owner_id": actor,
        "visibility": "category",
        "revision": 1,
        "required_source_read_set": [],
        "intent_digest": "a" * 64,
        "reason": "Explicit host unit material",
    }
    assessment = mapped(
        starts.BuildExecutionAssessment,
        **material,
        id=uuid4(),
        build_revision=1,
        engineering_configuration_revision=1,
        manufacturing_configuration_revision=1,
        status="READY",
        execution_scope={},
        result={},
    )
    assessment.snapshot_sha256 = host.digest(starts._material(assessment))
    rows = {
        "ac": mapped(
            starts.BuildAssessmentCurrent,
            **scope,
            id=uuid4(),
            assessment_id=assessment.id,
            assessment_revision=assessment.revision,
        ),
        "af": assessment,
    }
    for prefix, role in (("e", "engineering"), ("m", "manufacturing")):
        decision = mapped(
            starts.BuildAuthorizationDecision,
            **material,
            id=uuid4(),
            role=role,
            action="approve",
            status="approved",
            assessment_id=assessment.id,
            assessment_revision=assessment.revision,
            assessment_sha256=assessment.snapshot_sha256,
            authority_snapshot={},
            fact_binding={},
            sources=[],
        )
        decision.snapshot_sha256 = host.digest(starts._material(decision))
        rows[prefix + "f"] = decision
        rows[prefix + "c"] = mapped(
            starts.BuildAuthorizationCurrent,
            **scope,
            id=uuid4(),
            role=role,
            decision_id=decision.id,
            decision_revision=decision.revision,
        )
    engine = create_engine("sqlite://")
    Product.__table__.create(engine)
    categories = sqlite_table(engine, Category)
    with engine.begin() as connection:
        connection.execute(
            categories.insert().values(
                id=category,
                tenant_id=tenant,
                created_at=AT,
                key="host-boundary",
                name="Host boundary only",
                purpose="No actual professional or RLS qualification",
                owner_id=actor,
                revision=1,
                status="active",
                lifecycle_epoch=1,
                created_by_run_id=None,
            )
        )
        connection.execute(
            Product.__table__.insert().values(
                id=product,
                tenant_id=tenant,
                category_id=category,
                created_at=AT,
                owner_id=actor,
                name="Host boundary only",
                purpose="No actual professional or RLS qualification",
                revision=1,
                lifecycle_epoch=1,
                status="draft",
                visibility="category",
            )
        )
    yield SimpleNamespace(ctx=ctx, product=product, build=build, rows=rows, engine=engine)
    engine.dispose()


def packed_fields(work):
    _, owners = starts._writer_projection_query(work.build)
    selected = {}
    for prefix, table, model in owners:
        attributes = {
            attribute.columns[0].key: attribute.key for attribute in model.__mapper__.column_attrs
        }
        for column in table.c:
            selected[f"{prefix}_{column.key}"] = (
                deepcopy(getattr(work.rows[prefix], attributes[column.key]))
                if column.key in attributes
                else [{"source": "database-owned RLS projection, not Python material"}]
            )
    return selected


@contextmanager
def held_host_session(work, monkeypatch):
    """Actual command_scope creates the marker; permission IO is a named seam."""
    with Session(work.engine) as session, monkeypatch.context() as io:
        session.begin()
        session.info["scope"] = (
            work.ctx.tenant_id,
            work.ctx.actor_id,
            work.ctx.requester_id,
            work.ctx.category_id,
        )
        session.info["read_snapshot"] = False

        def permission_io(s, ctx, pid, **_options):
            assert s is session and ctx is work.ctx and pid == work.product
            return s.get(Product, pid)

        io.setattr(host, "require_access", permission_io)
        command = Command(
            command_id=uuid4(),
            idempotency_key=str(uuid4()),
            operation="build.readiness.compute",
            category_id=work.ctx.category_id,
            product_id=work.product,
            expected_revision=1,
            payload={},
        )
        held = host.command_scope(session, work.ctx, command, lock=True)
        assert isinstance(held, Product) and held.id == work.product
        proof = request_proof(session)
        assert work.product in proof.scope_locks
        calls, stamps, nested = [], [], []
        transport = SimpleNamespace(
            rows=[packed_fields(work)],
            db_scope={
                name: str(value)
                for name, value in zip(
                    ("tenant_id", "actor_id", "requester_id", "category_id"),
                    session.info["scope"],
                    strict=True,
                )
            },
            clock_override="actual-sqlite-clock",
            stamp_rows=None,
            stamp_callback=None,
        )
        token = starts._writer_projection_scope(session, work.ctx, work.product)
        assert token is not None
        connection = token[-2]
        original_execute = session.execute
        original_connection_execute = connection.execute
        packed_keys = set(transport.rows[0])
        stamp_keys = {*transport.db_scope, "lifecycle_epoch"}

        def execute(query, *args, **options):
            columns = getattr(query, "selected_columns", None)
            if columns is None or set(columns.keys()) != packed_keys:
                return original_execute(query, *args, **options)
            assert session.get_nested_transaction() is not None
            calls.append(query)
            return SimpleNamespace(mappings=lambda: deepcopy(transport.rows))

        def stamp_transport(query, *args, **options):
            columns = getattr(query, "selected_columns", None)
            if columns is None or set(columns.keys()) != stamp_keys:
                return original_connection_execute(query, *args, **options)
            stamps.append(query)
            # SQLite cannot qualify PostgreSQL GUC/RLS behavior. Only those
            # four returned strings are a seam; the clock/UOW read is actual.
            epoch = original_connection_execute(
                select(Product.lifecycle_epoch).where(Product.id == work.product)
            ).scalar_one()
            if transport.clock_override != "actual-sqlite-clock":
                epoch = transport.clock_override
            selected = (
                [{**transport.db_scope, "lifecycle_epoch": epoch}]
                if transport.stamp_rows is None
                else transport.stamp_rows
            )
            if transport.stamp_callback is not None:
                transport.stamp_callback()
            return SimpleNamespace(mappings=lambda: deepcopy(selected))

        def remember_nested(_session, transaction):
            if transaction.nested:
                nested.append(transaction)

        event.listen(session, "after_transaction_create", remember_nested)
        io.setattr(connection, "execute", stamp_transport)

        def build_io(s, model, identity, *, scope_id):
            assert s is session and model is Build
            assert identity == work.build.id and scope_id == work.product
            return work.build

        def fact_io(s, model, identity, *, scope_id):
            assert s is session and scope_id == work.product
            assert model is starts.BuildExecutionAssessment and identity == work.rows["af"].id
            return work.rows["af"]

        def ordered_pointer_io(s, key, query, **_options):
            assert s is session
            if key[0] is starts.BuildAssessmentCurrent:
                return work.rows["ac"]
            raise DBAPIError("later authorization read", {}, RuntimeError("later Auth IO"))

        io.setattr(session, "execute", execute)
        io.setattr(builds, "snapshot_get", build_io)
        io.setattr(starts, "snapshot_get", fact_io)
        io.setattr(starts, "snapshot_scalar", ordered_pointer_io)
        io.setattr(starts, "_start", lambda *_args: None)
        try:
            yield SimpleNamespace(
                session=session,
                proof=proof,
                held=held,
                calls=calls,
                stamps=stamps,
                nested=nested,
                connection=connection,
                command=command,
                transport=transport,
                io=io,
            )
        finally:
            # Pending/dirty negatives must never flush fake owner material.
            session.rollback()


def test_packed_writer_reconstructs_complete_real_mapper_fields_without_db_only_attribute(
    owners, monkeypatch
):
    work = owners
    with held_host_session(work, monkeypatch) as host_work:
        result = starts._projection_writer(host_work.session, work.ctx, work.product, work.build)
        assessment, decisions, saved = result
        assert saved is None and set(decisions) == {"engineering", "manufacturing"}
        for actual, original in (
            (assessment, work.rows["af"]),
            (decisions["engineering"], work.rows["ef"]),
            (decisions["manufacturing"], work.rows["mf"]),
        ):
            mapped_keys = {attribute.key for attribute in type(actual).__mapper__.column_attrs}
            table_keys = {column.key for column in type(actual).__table__.c}
            assert table_keys - mapped_keys == {"audience_dependencies"}
            assert not hasattr(actual, "audience_dependencies")
            assert {key: getattr(actual, key) for key in mapped_keys} == {
                key: getattr(original, key) for key in mapped_keys
            }
            assert actual is not original and actual not in host_work.session
            assert actual.snapshot_sha256 == host.digest(starts._material(actual))
        query = host_work.calls[0]
        assert set(query.selected_columns.keys()) == set(host_work.transport.rows[0])
        assert not (host_work.session.new or host_work.session.dirty or host_work.session.deleted)


def test_writer_token_rejects_unheld_dirty_context_and_different_or_routed_real_bind(
    owners, monkeypatch
):
    work = owners
    other_engine = create_engine("sqlite://")
    try:
        for change in (
            "unheld",
            "wrong-product",
            "category-only",
            "read-snapshot",
            "missing-scope",
            "pending",
            "dirty",
            "deleted",
            "unbound",
            "prior-bind-change",
            "routed-build",
            "routed-owner",
            "different-context",
        ):
            with held_host_session(work, monkeypatch) as host_work:
                s, proof = host_work.session, host_work.proof
                pid, ctx = work.product, work.ctx
                assert starts._writer_projection_scope(s, ctx, pid) is not None, change
                if change in {"unheld", "category-only"}:
                    proof.scope_locks.clear()
                    if change == "category-only":
                        proof.scope_locks.add((Category, ctx.category_id))
                elif change == "wrong-product":
                    pid = uuid4()
                elif change == "read-snapshot":
                    s.info["read_snapshot"] = True
                elif change == "missing-scope":
                    s.info.pop("scope")
                elif change == "pending":
                    s.add(Product(id=uuid4()))
                elif change == "dirty":
                    host_work.held.name = "Actual ORM dirty state"
                elif change == "deleted":
                    s.delete(host_work.held)
                elif change in {"unbound", "prior-bind-change"}:
                    s.bind = None if change == "unbound" else other_engine
                elif change in {"routed-build", "routed-owner"}:
                    s.bind_mapper(
                        Build if change == "routed-build" else starts.BuildExecutionAssessment,
                        other_engine,
                    )
                else:
                    ctx = host.Context(
                        work.ctx.tenant_id, uuid4(), uuid4(), category_id=work.ctx.category_id
                    )
                if change == "different-context":
                    with pytest.raises(DomainError, match="请求身份与事务范围不符"):
                        starts._writer_projection_scope(s, ctx, pid)
                else:
                    assert starts._writer_projection_scope(s, ctx, pid) is None, change
                assert host_work.calls == []
    finally:
        other_engine.dispose()


def test_same_db_clock_reuses_only_raw_rows_without_new_savepoint_or_model_aliasing(
    owners, monkeypatch
):
    work = owners
    with held_host_session(work, monkeypatch) as host_work:
        s, proof = host_work.session, host_work.proof
        with s.begin_nested():
            before = starts._writer_projection_scope(s, work.ctx, work.product)
            first = starts._projection_writer(s, work.ctx, work.product, work.build)
            original_reason = first[0].reason
            first[0].reason = "Caller-local model changes must not touch retained raw fields"
            first[1]["engineering"].sources.append({"caller-local": True})
            second = starts._projection_writer(s, work.ctx, work.product, work.build)
            assert starts._writer_projection_scope(s, work.ctx, work.product) == before
        assert len(host_work.calls) == 1 and len(host_work.stamps) == 2
        # One caller SAVEPOINT and only the first speculative packed read.
        assert len(host_work.nested) == 2
        assert second[0].reason == original_reason and first[0] is not second[0]
        assert second[1]["engineering"].sources == []
        assert first[1]["engineering"] is not second[1]["engineering"]
        assert proof.mutation_epoch == 0 and work.product in proof.scope_locks
        assert s.get_transaction() is proof.transaction and s.is_active
        assert not (s.new or s.dirty or s.deleted)


def test_actual_connection_clock_change_refreshes_raw_rows_without_orm_epoch_change(
    owners, monkeypatch
):
    work = owners
    with held_host_session(work, monkeypatch) as host_work:
        s, proof = host_work.session, host_work.proof
        first = starts._projection_writer(s, work.ctx, work.product, work.build)
        before = proof.mutation_epoch
        # This host seam explicitly increments the actual SQLite clock. The
        # ordinary-app PostgreSQL test proves lawful successor triggers.
        host_work.connection.execute(
            Product.__table__.update()
            .where(Product.id == work.product)
            .values(lifecycle_epoch=Product.lifecycle_epoch + 1)
        )
        work.rows["af"].id = uuid4()
        work.rows["af"].revision += 1
        work.rows["af"].reason = "New raw assessment successor transport"
        work.rows["af"].snapshot_sha256 = host.digest(starts._material(work.rows["af"]))
        work.rows["ac"].assessment_id = work.rows["af"].id
        work.rows["ac"].assessment_revision = work.rows["af"].revision
        for prefix in ("e", "m"):
            decision = work.rows[prefix + "f"]
            decision.assessment_id = work.rows["af"].id
            decision.assessment_revision = work.rows["af"].revision
            decision.assessment_sha256 = work.rows["af"].snapshot_sha256
            decision.snapshot_sha256 = host.digest(starts._material(decision))
        host_work.transport.rows = [packed_fields(work)]
        second = starts._projection_writer(s, work.ctx, work.product, work.build)
        assert len(host_work.calls) == 2 and len(host_work.stamps) == 2
        assert len(host_work.nested) == 2
        assert second[0].id != first[0].id and second[0].revision == first[0].revision + 1
        assert second[0].snapshot_sha256 == host.digest(starts._material(second[0]))
        assert proof.mutation_epoch == before == 0
        assert work.product in proof.scope_locks and not s.dirty


def test_fresh_db_scope_or_hidden_product_never_inherits_cached_positive(owners, monkeypatch):
    work = owners
    for field in ("tenant_id", "actor_id", "requester_id", "category_id"):
        for invalid in (str(uuid4()), None, "", "not-a-uuid"):
            with held_host_session(work, monkeypatch) as host_work:
                starts._projection_writer(host_work.session, work.ctx, work.product, work.build)
                host_work.transport.db_scope[field] = invalid
                # A new RLS scope can hide Product: the returned GUC row must
                # still reject identity drift rather than return cached owners.
                host_work.transport.clock_override = None
                with pytest.raises(DomainError) as error:
                    starts._projection_writer(host_work.session, work.ctx, work.product, work.build)
                assert error.value.reason == "FORBIDDEN_SCOPE", (field, invalid)
                assert len(host_work.calls) == 1 and len(host_work.stamps) == 2
    for invalid in (None, True, "1", 1.5):
        with held_host_session(work, monkeypatch) as host_work:
            starts._projection_writer(host_work.session, work.ctx, work.product, work.build)
            host_work.transport.clock_override = invalid
            with pytest.raises(DomainError) as error:
                starts._projection_writer(host_work.session, work.ctx, work.product, work.build)
            assert error.value.reason == "FORBIDDEN_SCOPE", invalid
            assert len(host_work.calls) == 1
    for rows in ([], [{}, {}]):
        with held_host_session(work, monkeypatch) as host_work:
            starts._projection_writer(host_work.session, work.ctx, work.product, work.build)
            host_work.transport.stamp_rows = rows
            with pytest.raises(DomainError) as error:
                starts._projection_writer(host_work.session, work.ctx, work.product, work.build)
            assert error.value.reason == "FORBIDDEN_SCOPE"
            assert len(host_work.calls) == 1


def test_integer_clock_and_incomplete_legacy_context_keep_existing_contract(owners, monkeypatch):
    work = owners
    for epoch in (0, -1):
        with held_host_session(work, monkeypatch) as host_work:
            host_work.transport.clock_override = epoch
            assert (
                starts._projection_writer(host_work.session, work.ctx, work.product, work.build)
                is not None
            )
            assert len(host_work.calls) == 1 and len(host_work.stamps) == 1
    with held_host_session(work, monkeypatch) as host_work:
        ctx = host.Context(work.ctx.tenant_id, work.ctx.actor_id, work.ctx.requester_id)
        host_work.session.info["scope"] = (
            ctx.tenant_id,
            ctx.actor_id,
            ctx.requester_id,
            ctx.category_id,
        )
        assert starts._projection_writer(host_work.session, ctx, work.product, work.build) is None
        assert host_work.calls == host_work.stamps == []


def test_dirty_flush_and_real_orm_mutation_discard_same_clock_raw_window(owners, monkeypatch):
    work = owners
    with held_host_session(work, monkeypatch) as host_work:
        s, proof = host_work.session, host_work.proof
        starts._projection_writer(s, work.ctx, work.product, work.build)
        assert proof.scalar_rows
        host_work.held.name = "Actual dirty Product"
        assert starts._projection_writer(s, work.ctx, work.product, work.build) is None
        assert len(host_work.calls) == 1 and len(host_work.stamps) == 1
        s.flush()
        assert proof.mutation_epoch == 1 and not proof.scalar_rows
        assert work.product in proof.scope_locks
        starts._projection_writer(s, work.ctx, work.product, work.build)
        assert len(host_work.calls) == 2
        s.execute(update(Product).where(Product.id == work.product).values(name="ORM mutation"))
        assert proof.mutation_epoch == 2 and not proof.scalar_rows
        starts._projection_writer(s, work.ctx, work.product, work.build)
        assert len(host_work.calls) == 3 and len(host_work.stamps) == 3
        assert work.product in proof.scope_locks and not s.dirty


def test_nested_and_root_rollback_cannot_borrow_a_previous_raw_window(owners, monkeypatch):
    work = owners
    with held_host_session(work, monkeypatch) as host_work:
        s, proof = host_work.session, host_work.proof
        starts._projection_writer(s, work.ctx, work.product, work.build)
        with pytest.raises(RuntimeError, match="Rollback boundary"):
            with s.begin_nested():
                starts._projection_writer(s, work.ctx, work.product, work.build)
                starts._projection_writer(s, work.ctx, work.product, work.build)
                assert len(host_work.calls) == 2
                raise RuntimeError("Rollback boundary")
        assert proof.mutation_epoch == 1 and not proof.scalar_rows and not proof.scope_locks
        assert starts._projection_writer(s, work.ctx, work.product, work.build) is None
        assert len(host_work.calls) == 2
        # Reacquire the real domain gate after rollback; never repair markers.
        host.command_scope(s, work.ctx, host_work.command, lock=True)
        starts._projection_writer(s, work.ctx, work.product, work.build)
        assert len(host_work.calls) == 3
        s.rollback()
        assert not proof.scalar_rows and not proof.scope_locks
        s.begin()
        assert starts._projection_writer(s, work.ctx, work.product, work.build) is None
        assert len(host_work.calls) == 3
    with held_host_session(work, monkeypatch) as host_work:
        assert host_work.proof is not proof
        starts._projection_writer(host_work.session, work.ctx, work.product, work.build)
        assert len(host_work.calls) == 1


def test_stamp_boundary_drift_declines_before_packed_query(owners, monkeypatch):
    work = owners
    with held_host_session(work, monkeypatch) as host_work:
        host_work.transport.stamp_callback = lambda: setattr(
            host_work.held, "name", "Dirty at stamp"
        )
        assert (
            starts._projection_writer(host_work.session, work.ctx, work.product, work.build) is None
        )
        assert host_work.calls == [] and len(host_work.stamps) == 1


def test_saved_start_uses_actual_full_row_and_still_rechecks_fixed_hash(owners, monkeypatch):
    work = owners
    keys = {attribute.key for attribute in starts.BuildStart.__mapper__.column_attrs}
    common = {
        attribute.key: deepcopy(getattr(work.rows["af"], attribute.key))
        for attribute in type(work.rows["af"]).__mapper__.column_attrs
        if attribute.key in keys
    }
    saved = mapped(starts.BuildStart, **{**common, "id": uuid4()})
    saved.snapshot_sha256 = host.digest(starts._material(saved))
    original_start = starts._start
    with held_host_session(work, monkeypatch) as host_work:
        seen = []

        def actual_start(*_args):
            seen.append(saved)
            return saved

        host_work.io.setattr(starts, "_start", actual_start)
        first = starts._projection_writer(host_work.session, work.ctx, work.product, work.build)
        second = starts._projection_writer(host_work.session, work.ctx, work.product, work.build)
        assert first[2] is second[2] is saved and seen == [saved, saved]
        assert len(host_work.calls) == 1
        saved.reason = "An invalid changed Start must still fail its actual fixed hash"
        with pytest.raises(DomainError, match="执行事实固定摘要无法核对") as error:
            starts._projection_writer(host_work.session, work.ctx, work.product, work.build)
        assert error.value.reason == "INTEGRITY_MISMATCH"
        assert len(host_work.calls) == 1 and seen == [saved, saved, saved]
    assert starts._start is original_start


def test_hidden_ambiguous_or_mismatched_owner_keeps_original_first_assessment_error(
    owners, monkeypatch
):
    work = owners
    work.rows["af"].snapshot_sha256 = "0" * 64
    for change in ("hidden-fact", "ambiguous", "wrong-scope", "wrong-revision", "wrong-role"):
        with held_host_session(work, monkeypatch) as host_work:
            raw = host_work.transport.rows[0]
            if change == "hidden-fact":
                raw["ef_id"] = None
            elif change == "ambiguous":
                host_work.transport.rows.append(deepcopy(raw))
            elif change == "wrong-scope":
                raw["mf_project_id"] = uuid4()
            elif change == "wrong-revision":
                raw["ac_assessment_revision"] += 1
            else:
                raw["mf_role"] = "engineering"
            with pytest.raises(DomainError, match="执行事实固定摘要无法核对") as error:
                starts.execution_projection(
                    host_work.session, work.ctx, work.product, work.build.id
                )
            assert error.value.reason == "INTEGRITY_MISMATCH", change
            assert len(host_work.calls) == 1
            assert work.product in host_work.proof.scope_locks


def test_packed_sql_failure_uses_real_nested_rollback_and_original_guard_order(owners, monkeypatch):
    work = owners
    work.rows["af"].snapshot_sha256 = "0" * 64
    with held_host_session(work, monkeypatch) as host_work:
        s, proof = host_work.session, host_work.proof
        original_transaction = s.get_transaction()
        proof.sources["explicit-host-read"] = object()

        def failed_transport(_query):
            assert s.get_nested_transaction() is not None
            host_work.calls.append("packed SQLSTATE before ordered readers")
            raise DBAPIError("packed owner SELECT", {}, RuntimeError("later Auth SQLSTATE"))

        monkeypatch.setattr(s, "execute", failed_transport)
        with pytest.raises(DomainError, match="执行事实固定摘要无法核对") as error:
            starts.execution_projection(s, work.ctx, work.product, work.build.id)
        assert error.value.reason == "INTEGRITY_MISMATCH"
        assert host_work.calls == ["packed SQLSTATE before ordered readers"]
        assert s.is_active and s.get_transaction() is original_transaction
        assert s.get_nested_transaction() is None
        assert request_proof(s) is proof and proof.mutation_epoch == 1
        assert not proof.scope_locks and not proof.sources
