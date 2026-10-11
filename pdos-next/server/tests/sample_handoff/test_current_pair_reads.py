"""Real ordinary-role Current/Fact guard cases; synthetic material only.

Root alone applies/runs this proposal in its verified isolated target.
Diagnostic fault policies always roll back, with intact Current RLS/SELECT ACL.
These cases establish neither real qualification nor accepted performance.
"""

# ruff: noqa: F811 - imported fixtures register their actual dependency chain

from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, attributes
from test_project_first_plan import accepted
from verification_handoff.fixtures import (  # noqa: F401
    actual_method,
    handoff_work,
    known_configuration,
    operational_work,
    ready_work,
)

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.professional_authority import service as authority
from pdos_next.domain.professional_authority.models import ProfessionalCurrent, ProfessionalFact
from pdos_next.domain.sample_handoff import service as readiness
from pdos_next.domain.sample_handoff.models import SampleReadinessCurrent, SampleReadinessFact
from pdos_next.domain.verification_handoff import service as methods
from pdos_next.domain.verification_handoff.models import (
    ActualMethodApplicability,
    ActualMethodCurrent,
)
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Confirmation, Outbox, Receipt, now
from pdos_next.request_proof import request_proof, scope_is_held
from pdos_next.schemas.verification.contracts import SampleRef
from pdos_next.service import Context, command_scope
from tests.professional_authority.test_transactions import (  # noqa: F401
    OP,
    PURPOSE,
    authority_work,
    imported,
    pair,
    successor,
)


def _gate(session, setup, ctx):
    scope = command_scope(
        session,
        ctx,
        Command(
            command_id=uuid4(),
            idempotency_key=str(uuid4()),
            operation="build.readiness.compute",
            category_id=setup.category,
            product_id=setup.product,
            expected_revision=1,
            payload={},
        ),
        lock=True,
    )
    assert scope.id == setup.product and scope_is_held(session, setup.product)
    assert setup.product in request_proof(session).scope_locks
    assert session.is_active and session.get_nested_transaction() is None
    assert not (session.new or session.dirty or session.deleted)
    assert session.scalar(text("SELECT current_user")) == "pdos_next_app"
    assert (
        session.scalar(text("SELECT pg_has_role(current_user,'pdos_next_owner','MEMBER')")) is False
    )


def _session(setup, ctx, *, bind=None, read_snapshot=False):
    return tenant_session(
        bind if bind is not None else setup.engine,
        setup.tenant,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        category_id=setup.category,
        read_snapshot=read_snapshot,
    )


@contextmanager
def _statements(session, current_model, fact_model):
    """Passive client counts; policies' internal SQL is not client SQL."""
    observed = {"phase": None, "calls": {}}
    target = session.get_bind()

    def before(connection, cursor, statement, parameters, context, executemany):
        phase = observed["phase"]
        if phase is None or not statement.lstrip().startswith("SELECT"):
            return
        if (
            current_model.__tablename__ not in statement
            and fact_model.__tablename__ not in statement
        ):
            return
        assert not executemany
        observed["calls"].setdefault(phase, []).append(
            (
                current_model.__tablename__ in statement,
                fact_model.__tablename__ in statement,
                "FOR UPDATE" in statement,
            )
        )

    event.listen(target, "before_cursor_execute", before)
    try:
        yield observed
    finally:
        observed["phase"] = None
        event.remove(target, "before_cursor_execute", before)


@contextmanager
def _runtime_fault(setup, current_model, fact_model):
    name = f"pdos_pair_runtime_{uuid4().hex}"
    tables = current_model.__tablename__, fact_model.__tablename__
    assert all(value.replace("_", "").isalnum() for value in tables)
    query = text(
        "SELECT schemaname,tablename,policyname,permissive,roles,cmd,qual,with_check "
        "FROM pg_policies WHERE schemaname='public' AND tablename IN (:current,:fact) "
        "ORDER BY tablename,policyname"
    )
    parameters = {"current": tables[0], "fact": tables[1]}
    with setup.admin.connect() as connection:
        outer = connection.begin()
        before = list(connection.execute(query, parameters).mappings())
        try:
            # Runtime policy error, never a parse-time SELECT privilege failure.
            connection.execute(
                text(
                    f"CREATE FUNCTION public.{name}() RETURNS boolean "
                    "LANGUAGE plpgsql VOLATILE SECURITY INVOKER AS $$ "
                    "BEGIN RAISE EXCEPTION 'pair runtime RLS fault' USING ERRCODE='P0001'; END; $$"
                )
            )
            connection.execute(text(f"GRANT EXECUTE ON FUNCTION public.{name}() TO pdos_next_app"))
            connection.execute(
                text(
                    f"CREATE POLICY {name} ON public.{tables[1]} AS RESTRICTIVE "
                    f"FOR SELECT TO pdos_next_app USING (public.{name}())"
                )
            )
            connection.execute(text("SET LOCAL ROLE pdos_next_app"))
            assert (
                connection.scalar(
                    text("SELECT has_table_privilege(current_user,:table,'SELECT')"),
                    {"table": f"public.{tables[1]}"},
                )
                is True
            )
            yield connection
        finally:
            outer.rollback()
            assert list(connection.execute(query, parameters).mappings()) == before
            assert (
                connection.scalar(
                    text("SELECT to_regprocedure(:name)"), {"name": f"public.{name}()"}
                )
                is None
            )
            connection.rollback()


def _families(work):
    sample_id = UUID(work.samples[0]["id"])
    return (
        (
            SampleReadinessCurrent,
            SampleReadinessFact,
            lambda session, **options: readiness._current(
                session, work.quality.ctx, work.setup.product, sample_id, **options
            ),
        ),
        (
            ActualMethodCurrent,
            ActualMethodApplicability,
            lambda session, **options: methods._method_pointer(
                session,
                work.quality.ctx,
                work.setup.product,
                UUID(work.request_id),
                sample_id,
                "dimension",
                **options,
            ),
        ),
    )


def _effects(setup):
    with Session(setup.admin) as session:
        return {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == setup.tenant)
            )
            for model in (Receipt, Audit, Outbox, Confirmation)
        }


def test_missing_physical_current_skips_runtime_fact_rls_fault(handoff_work):
    work = handoff_work
    accepted(work.quality, actual_method(work))
    for current_model, fact_model, _load in _families(work):
        with _runtime_fault(work.setup, current_model, fact_model) as connection:
            with _session(work.setup, work.quality.ctx, bind=connection) as session:
                _gate(session, work.setup, work.quality.ctx)

                def missing(current=current_model):
                    if current is SampleReadinessCurrent:
                        # Absent exact scope; no stored FK or facts are broken.
                        return readiness._current(
                            session, work.quality.ctx, work.setup.product, uuid4()
                        )
                    return methods._method_pointer(
                        session,
                        work.quality.ctx,
                        work.setup.product,
                        UUID(work.request_id),
                        UUID(work.samples[0]["id"]),
                        f"missing-item-{uuid4().hex}",
                    )

                with _statements(session, current_model, fact_model) as observed:
                    observed["phase"] = "missing"
                    assert missing() == (None, None)
                    observed["phase"] = None
                assert observed["calls"] == {"missing": [(True, True, False)]}
                # A real existing Fact must actually evaluate the fault policy.
                with pytest.raises(DBAPIError) as raised:
                    with session.begin_nested():
                        session.scalar(
                            select(fact_model.id)
                            .where(
                                fact_model.tenant_id == work.setup.tenant,
                                fact_model.product_id == work.setup.product,
                            )
                            .limit(1)
                        )
                assert raised.value.orig.sqlstate == "P0001"


def test_missing_professional_current_skips_runtime_fact_rls_fault(setup, authority_work):
    pair(setup, authority_work)
    caller = Context(setup.tenant, setup.peer, setup.peer, category_id=setup.category)
    with _runtime_fault(setup, ProfessionalCurrent, ProfessionalFact) as connection:
        with _session(setup, caller, bind=connection) as session:
            _gate(session, setup, caller)
            with _statements(session, ProfessionalCurrent, ProfessionalFact) as observed:
                observed["phase"] = "missing"
                value = authority.assess(
                    session,
                    caller,
                    setup.product,
                    UUID(authority_work["project"]),
                    OP,
                    PURPOSE,
                    now(),
                    write=True,
                )
                observed["phase"] = None
            assert value["authorized"] is False and value["fact_refs"] == []
            # Connection has no Engine issuer registry; this negative raw-loader
            # ordering result cannot establish any professional qualification.
            assert observed["calls"] == {"missing": [(True, True, True)]}
            with pytest.raises(DBAPIError) as raised:
                with session.begin_nested():
                    session.scalar(
                        select(ProfessionalFact.id).where(
                            ProfessionalFact.tenant_id == setup.tenant,
                            ProfessionalFact.product_id == setup.product,
                        )
                    )
            assert raised.value.orig.sqlstate == "P0001"


def test_physical_current_pair_cache_lock_and_loaded_integrity_remain_exact(handoff_work):
    work = handoff_work
    accepted(work.quality, actual_method(work))
    before = _effects(work.setup)
    for current_model, fact_model, load in _families(work):
        with _session(work.setup, work.quality.ctx, read_snapshot=True) as session:
            assert session.scalar(text("SHOW transaction_isolation")) == "repeatable read"
            assert session.scalar(text("SHOW transaction_read_only")) == "on"
            with _statements(session, current_model, fact_model) as observed:
                observed["phase"] = "first"
                pointer, fact = load(session)
                observed["phase"] = "repeat"
                assert load(session) == (pointer, fact)
                observed["phase"] = None
            assert pointer is not None and fact is not None and inspect(fact).persistent
            assert not inspect(fact).unloaded
            assert observed["calls"] == {"first": [(True, True, False)]}
            expected = (
                "SAMPLE_READINESS_INTEGRITY_UNKNOWN"
                if fact_model is SampleReadinessFact
                else "INTEGRITY_MISMATCH"
            )
            revision = fact.revision
            try:
                # Corrupt only actual app-loaded Python material, not DB/FK/RLS.
                attributes.set_committed_value(fact, "revision", revision + 1)
                with pytest.raises(DomainError) as mismatch:
                    load(session)
                assert mismatch.value.reason == expected
            finally:
                attributes.set_committed_value(fact, "revision", revision)
            material = (
                fact.fixed_snapshot
                if fact_model is SampleReadinessFact
                else fact.assessment_snapshot
            )
            marker = f"untracked-{uuid4().hex}"
            try:
                material[marker] = True
                assert fact not in session.dirty
                with pytest.raises(DomainError) as invalid:
                    if fact_model is SampleReadinessFact:
                        load(session)
                    else:
                        parent = methods.front._row(
                            session, work.quality.ctx, work.setup.product, fact.request_version_id
                        )
                        methods._actual_binding(
                            session,
                            work.quality.ctx,
                            work.setup.product,
                            methods.front._snapshot(parent),
                            SampleRef.model_validate(fact.assessment_snapshot["sample"]),
                            {
                                "actual_configuration": fact.assessment_snapshot[
                                    "actual_configuration"
                                ]
                            },
                            fact,
                            parent=parent,
                        )
                assert invalid.value.reason == expected and material[marker] is True
            finally:
                del material[marker]
        with _session(work.setup, work.quality.ctx) as session:
            _gate(session, work.setup, work.quality.ctx)
            with _statements(session, current_model, fact_model) as observed:
                observed["phase"] = "first"
                pointer, fact = load(session)
                observed["phase"] = "repeat"
                assert load(session) == (pointer, fact)
                observed["phase"] = "upgrade"
                assert load(session, lock=True) == (pointer, fact)
                observed["phase"] = "locked_repeat"
                assert load(session, lock=True) == (pointer, fact)
                observed["phase"] = None
            assert observed["calls"] == {
                "first": [(True, True, False)],
                "upgrade": [(True, False, True)],
            }
    assert _effects(work.setup) == before


def test_professional_write_pair_upgrade_and_plain_json_mutation_keep_old_guard(
    setup, authority_work
):
    records = pair(setup, authority_work)
    project_id, at = UUID(authority_work["project"]), now()
    before = _effects(setup)
    with _session(setup, setup.ctx) as session:
        _gate(session, setup, setup.ctx)
        with _statements(session, ProfessionalCurrent, ProfessionalFact) as observed:
            observed["phase"] = "summary"
            summarized = authority.assess(
                session, setup.ctx, setup.product, project_id, OP, PURPOSE, at
            )
            assert not any(
                isinstance(row, ProfessionalFact) for row in session.identity_map.values()
            )
            observed["phase"] = "upgrade"
            first = authority.assess(
                session, setup.ctx, setup.product, project_id, OP, PURPOSE, at, write=True
            )
            observed["phase"] = "repeat"
            repeated = authority.assess(
                session, setup.ctx, setup.product, project_id, OP, PURPOSE, at, write=True
            )
            observed["phase"] = None
            assert first == repeated == summarized
            assert first["authorized"] is True and first["qualified"] is True
            assert first["synthetic"] is True and len(first["fact_refs"]) == 2
            assert observed["calls"] == {
                "summary": [(True, False, False)],
                "upgrade": [(True, True, True)],
            }
            qualification = next(
                row
                for row in session.identity_map.values()
                if isinstance(row, ProfessionalFact) and row.kind == "qualification"
            )
            marker = f"untracked-{uuid4().hex}"
            try:
                qualification.operations.append(marker)
                assert qualification not in session.dirty and inspect(qualification).persistent
                with session.no_autoflush:
                    observed["phase"] = "pending_json"
                    rejected = authority.assess(
                        session, setup.ctx, setup.product, project_id, OP, PURPOSE, at, write=True
                    )
                    observed["phase"] = None
                assert rejected["authorized"] is False
                assert "AUTHORITY_INTEGRITY_UNKNOWN" in rejected["reason_codes"]
                assert (
                    marker in qualification.operations and "pending_json" not in observed["calls"]
                )
            finally:
                observed["phase"] = None
                qualification.operations.remove(marker)
    assert _effects(setup) == before
    newer = imported(
        setup,
        authority_work,
        successor(
            setup,
            authority_work,
            records[1],
            reason="Synthetic successor for raw-loader guard",
        ),
    )
    before = _effects(setup)
    with _session(setup, setup.ctx) as session:
        _gate(session, setup, setup.ctx)
        historical = session.get(ProfessionalFact, UUID(records[1]["subject_id"]))
        assert historical is not None and inspect(historical).persistent
        marker = f"historical-untracked-{uuid4().hex}"
        try:
            historical.operations.append(marker)
            assert historical not in session.dirty
            with _statements(session, ProfessionalCurrent, ProfessionalFact) as observed:
                observed["phase"] = "fresh_current_loaded_json"
                with session.no_autoflush:
                    value = authority.assess(
                        session,
                        setup.ctx,
                        setup.product,
                        project_id,
                        OP,
                        PURPOSE,
                        now(),
                        write=True,
                    )
                observed["phase"] = None
            # A different fresh Fact ID must not erase an unrelated historical
            # JSON mutation. Original complete Current/Fact fallback is retained.
            assert value["authorized"] is True and value["qualified"] is True
            assert newer["subject_id"] in {row["id"] for row in value["fact_refs"]}
            assert marker in historical.operations
            assert observed["calls"] == {
                "fresh_current_loaded_json": [(True, False, True), (False, True, False)]
            }
        finally:
            historical.operations.remove(marker)
    assert _effects(setup) == before
