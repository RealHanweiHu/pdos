"""Explicit M2 PostgreSQL cases; no public domain adapter/model or auto-collection.

Only the existing marked 51698 M2 fixture is accepted. Synthetic receipt/Audit/Outbox
rows are constructed here as transaction fixtures, not by the public command owner.
"""

import os
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bindings import DomainBinding
from pdos_next.agent_kernel.execution import (
    finish_domain_call,
    prepare_domain_call,
    recover_domain_call,
)
from pdos_next.agent_kernel.models import (
    AgentEvent,
    AgentRun,
    AgentSession,
    AgentToolCall,
    KernelRow,
)
from pdos_next.clock import now
from pdos_next.database import engine_for, tenant_session
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Base, Category, Grant, Outbox, Principal, Product, Receipt
from pdos_next.safety import verify_test_target
from pdos_next.service import digest
from tests.agent_kernel.test_execution_binding import ledger

PORT = 51698
MARKER = "3749a9d8-a9de-4544-87c7-6766338a73a8"


@pytest.fixture(scope="module")
def private_engines():
    if os.environ.get("TEST_DATABASE_MARKER") != MARKER:
        raise RuntimeError("Only the existing marked M2 fixture is authorized")
    engines = []
    for key in ("TEST_DATABASE_URL", "DATABASE_URL"):
        url = make_url(os.environ[key])  # Explicit only; no .env or fallback.
        if url.host != "127.0.0.1" or url.port != PORT or url.database != "pdos_test":
            raise RuntimeError("Expected private M2 endpoint changed")
        engine = engine_for(os.environ[key])
        verify_test_target(engine)
        engines.append(engine)
    yield SimpleNamespace(admin=engines[0], app=engines[1])
    for engine in engines:
        engine.dispose()


@contextmanager
def admin_session(f):
    verify_test_target(f.engines.admin)
    with Session(f.engines.admin) as session, session.begin():
        yield session


@contextmanager
def app_session(f):
    verify_test_target(f.engines.app)
    with tenant_session(
        f.engines.app, f.scope.tenant_id, actor_id=f.scope.writer_id,
        requester_id=f.scope.requester_id, category_id=f.scope.category_id,
    ) as session:
        yield session


@pytest.fixture
def pg(private_engines):
    return seed_fixture(private_engines)


@pytest.fixture
def product_pg(private_engines):
    return seed_fixture(private_engines, with_product=True)


def seed_fixture(private_engines, *, with_product=False):
    f = ledger()
    f.engines = private_engines
    if with_product:
        f.scope = replace(f.scope, product_id=uuid4())
        f.run.product_id = f.scope.product_id
    f.run.trigger, f.run.goal = "page", "Synthetic trusted-call PostgreSQL fixture"
    f.run.intent_key, f.run.intent_digest = str(uuid4()), digest(str(uuid4()))
    f.model.call_key, f.model.input_digest = str(uuid4()), digest("synthetic model request")
    with admin_session(f) as session:
        session.add_all([
            Principal(id=f.scope.requester_id, tenant_id=f.scope.tenant_id,
                      name="M2 synthetic requester", kind="human"),
            Principal(id=f.scope.writer_id, tenant_id=f.scope.tenant_id,
                      name="M2 synthetic writer", kind="agent"),
        ])
        session.flush()
        session.add(Category(
            id=f.scope.category_id, tenant_id=f.scope.tenant_id,
            name="M2 synthetic category", purpose="Private trusted-call validation",
            owner_id=f.scope.requester_id,
        ))
        session.flush()
        if with_product:
            session.add(Product(
                id=f.scope.product_id, tenant_id=f.scope.tenant_id,
                category_id=f.scope.category_id, owner_id=f.scope.requester_id,
                name="M2 synthetic product", purpose="Private transaction fixture",
            ))
            session.flush()
        session.add_all([
            Grant(tenant_id=f.scope.tenant_id, category_id=f.scope.category_id,
                  principal_id=person, can_write=True, expires_at=None)
            for person in (f.scope.requester_id, f.scope.writer_id)
        ])
        session.add(AgentSession(
            id=f.scope.session_id, tenant_id=f.scope.tenant_id,
            category_id=f.scope.category_id, product_id=f.scope.product_id,
            owner_id=f.scope.requester_id,
        ))
        session.flush()
        session.add(f.run)
        session.flush()
        session.add_all([f.model, f.event, f.qualification])
        session.flush()
        # Keep only IDs and fixed value objects after leaving this real Session.
        session.expunge_all()
    return f


def read_receipt(session, scope, receipt):
    """Real RLS/read checks; this is a fixture callback, not root's public owner."""
    visible = session.scalar(select(Receipt.id).where(Receipt.id == receipt.id))
    current = session.scalar(text("SELECT category_access(:tenant,:category,false)"), {
        "tenant": scope.tenant_id, "category": scope.category_id,
    })
    if visible != receipt.id or not current:
        raise DomainError("FORBIDDEN_SCOPE", "原回执当前不可读。")


def prepare(session, f, **changes):
    options = dict(catalog=f.catalog, registry=f.registry, route=lambda *_: f.route,
                   command_digest=digest("synthetic command"), read_receipt=read_receipt)
    options.update(changes)
    return prepare_domain_call(session, f.scope, f.spec, f.arguments, f.source, **options)


def synthetic_receipt_atom(session, f, call):
    """Synthetic ledger atom only; deliberately no Claim/Artifact/domain invocation."""
    receipt = Receipt(
        id=uuid4(), tenant_id=f.scope.tenant_id, category_id=f.scope.category_id,
        product_id=f.scope.product_id,
        command_id=uuid4(), actor_id=f.scope.writer_id, requester_id=f.scope.requester_id,
        operation=f.spec.operation_key, subject_type="synthetic", subject_id=uuid4(),
        subject_revision=1, visibility="category", agent_run_id=f.scope.run_id,
        request_digest=call.execution_binding["command_digest"], intent_digest=digest(str(uuid4())),
        result={"synthetic_fixture": True},
    )
    session.add(receipt)
    session.flush()
    session.add_all([
        Audit(tenant_id=f.scope.tenant_id, category_id=f.scope.category_id,
              receipt_id=receipt.id, actor_id=f.scope.writer_id, operation=receipt.operation),
        Outbox(tenant_id=f.scope.tenant_id, category_id=f.scope.category_id,
               receipt_id=receipt.id, type="synthetic.trusted_call_completed",
               subject_id=receipt.subject_id, subject_revision=1,
               actor_id=f.scope.writer_id, correlation_id=receipt.command_id),
    ])
    session.flush()
    return receipt


def completed(f):
    with app_session(f) as session:
        call, prior = prepare(session, f)
        assert prior is None
        receipt = synthetic_receipt_atom(session, f, call)
        result = finish_domain_call(session, f.scope, call.id, receipt.id)
        identities = call.id, receipt.id
    return *identities, result


def test_installed_binding_schema_guard_and_owned_metadata_match(pg):
    owned = {cls.__tablename__ for cls in KernelRow.__subclasses__()}

    def include(obj, name, kind, reflected, compare_to):
        table = obj if kind == "table" else getattr(obj, "table", None)
        return table is None or table.name in owned

    verify_test_target(pg.engines.admin)
    with pg.engines.admin.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "s0_0716"
        column = connection.execute(text("""SELECT is_nullable,column_default
          FROM information_schema.columns WHERE table_schema='public'
          AND table_name='agent_tool_calls' AND column_name='execution_binding'""")).one()
        assert column == ("NO", None)
        assert connection.scalar(text("""SELECT convalidated FROM pg_constraint
          WHERE conname='kernel_execution_binding_shape'
          AND conrelid='agent_tool_calls'::regclass"""))
        definition = connection.scalar(text(
            "SELECT pg_get_functiondef('kernel_call_guard()'::regprocedure)"
        ))
        assert "new.execution_binding is distinct from old.execution_binding" in definition.lower()
        context = MigrationContext.configure(connection, opts={"include_object": include})
        assert compare_metadata(context, Base.metadata) == []


@pytest.mark.parametrize("binding", [None, {}, {"kind": "domain_t0"}, {"kind": "model"}])
def test_sql_rejects_json_null_missing_kind_and_incomplete_execution_binding(pg, binding):
    with pytest.raises(DBAPIError) as error:
        with app_session(pg) as session:
            session.add(AgentToolCall(
                tenant_id=pg.scope.tenant_id, run_id=pg.scope.run_id, call_key=str(uuid4()),
                tool="model", input_digest=digest("synthetic"), execution_binding=binding,
            ))
            session.flush()
    assert error.value.orig.sqlstate == "23514"


def test_sql_rejects_completed_domain_call_without_actual_receipt(pg):
    binding = DomainBinding(
        **pg.source.model_dump(), operation=pg.spec.operation_key,
        model_version=pg.route.version, model_route_digest=pg.route.digest,
        tool_definitions_digest=digest(pg.registry.definitions()), cancel_epoch=0,
        command_digest=digest("synthetic command"),
    )
    with pytest.raises(DBAPIError) as error:
        with app_session(pg) as session:
            session.add(AgentToolCall(
                tenant_id=pg.scope.tenant_id, run_id=pg.scope.run_id, call_key=str(uuid4()),
                tool=pg.spec.name, input_digest=digest("synthetic"), state="completed",
                result={}, execution_binding=binding.model_dump(mode="json"),
            ))
            session.flush()
    assert error.value.orig.sqlstate == "23514"


def test_sql_not_null_rejects_actual_sql_null_binding(pg):
    names = [column.name for column in AgentToolCall.__table__.columns]
    expressions = [
        "CAST(:new_id AS uuid)" if name == "id" else ":new_key" if name == "call_key"
        else "NULL" if name == "execution_binding" else name
        for name in names
    ]
    with pytest.raises(DBAPIError) as error:
        with app_session(pg) as session:
            session.execute(text(
                f"INSERT INTO agent_tool_calls ({','.join(names)}) "
                f"SELECT {','.join(expressions)} FROM agent_tool_calls WHERE id=:source"
            ), {"new_id": uuid4(), "new_key": str(uuid4()), "source": pg.model.id})
    assert error.value.orig.sqlstate == "23502"


def test_sql_binding_is_immutable_before_call_completion(pg):
    with app_session(pg) as session:
        call = AgentToolCall(
            tenant_id=pg.scope.tenant_id, run_id=pg.scope.run_id, call_key=str(uuid4()),
            tool="model", input_digest=digest("synthetic"),
            execution_binding=deepcopy(pg.model.execution_binding),
        )
        session.add(call)
        session.flush()
        identity = call.id
    with pytest.raises(DBAPIError) as error:
        with app_session(pg) as session:
            session.execute(text("""UPDATE agent_tool_calls SET execution_binding=
              jsonb_set(execution_binding,'{model_route_digest}',to_jsonb(CAST(:digest AS text)))
              WHERE id=:id"""), {"digest": digest("changed"), "id": identity})
    assert error.value.orig.sqlstate == "P0001"
    with app_session(pg) as session:
        saved = session.get(AgentToolCall, identity)
        assert saved.state == "started" and saved.execution_binding == pg.model.execution_binding


@pytest.mark.parametrize("stage", ["after_prepare", "after_receipt", "after_finish"])
def test_same_session_tail_failure_rolls_back_call_receipt_audit_and_outbox(product_pg, stage):
    pg = product_pg
    with admin_session(pg) as session:
        lifecycle_epoch = session.get(Product, pg.scope.product_id).lifecycle_epoch
    with pytest.raises(RuntimeError, match="synthetic UOW tail failure"):
        with app_session(pg) as session:
            call, _ = prepare(session, pg)
            if stage != "after_prepare":
                receipt = synthetic_receipt_atom(session, pg, call)
                if stage == "after_finish":
                    finish_domain_call(session, pg.scope, call.id, receipt.id)
            raise RuntimeError("synthetic UOW tail failure")
    with admin_session(pg) as session:
        assert session.scalar(select(func.count()).select_from(AgentToolCall).where(
            AgentToolCall.run_id == pg.scope.run_id, AgentToolCall.tool == pg.spec.name,
        )) == 0
        for model in (Receipt, Audit, Outbox):
            assert session.scalar(select(func.count()).select_from(model).where(
                model.tenant_id == pg.scope.tenant_id,
            )) == 0
        assert session.get(Product, pg.scope.product_id).lifecycle_epoch == lifecycle_epoch


@pytest.mark.parametrize("state", ["running", "completed", "partial", "failed"])
def test_completed_recovery_is_zero_dml_after_write_and_qualification_revocation(product_pg, state):
    pg = product_pg
    call_id, receipt_id, result = completed(pg)
    with admin_session(pg) as session:
        qualification = session.get(type(pg.qualification), pg.qualification.id)
        qualification.enabled, qualification.qualification_revoked = False, True
        for grant in session.scalars(select(Grant).where(
            Grant.category_id == pg.scope.category_id
        )):
            grant.can_write = False
        session.get(AgentRun, pg.scope.run_id).state = state
    mutations = []

    def record(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            mutations.append(statement)

    event.listen(pg.engines.app, "before_cursor_execute", record)
    try:
        with app_session(pg) as session:
            call, previous = recover_domain_call(
                session, pg.scope, pg.spec, pg.arguments, pg.source,
                command_digest=digest("synthetic command"), read_receipt=read_receipt,
            )
            assert call.id == call_id and previous == result and call.receipt_id == receipt_id
    finally:
        event.remove(pg.engines.app, "before_cursor_execute", record)
    assert mutations == []


@pytest.mark.parametrize("change", ["arguments", "command", "no_read_callback", "epoch"])
def test_actual_completed_recovery_rejects_mismatched_intents_and_epoch(product_pg, change):
    pg = product_pg
    completed(pg)
    arguments, command, reader = pg.arguments, digest("synthetic command"), read_receipt
    if change == "arguments":
        arguments = {"text": "changed"}
    elif change == "command":
        command = digest("different command")
    elif change == "no_read_callback":
        reader = None
    else:
        with admin_session(pg) as session:
            session.get(AgentRun, pg.scope.run_id).cancel_epoch += 1
    with pytest.raises(DomainError) as error:
        with app_session(pg) as session:
            recover_domain_call(session, pg.scope, pg.spec, arguments, pg.source,
                                command_digest=command, read_receipt=reader)
    assert error.value.code == {
        "arguments": "DUPLICATE_INTENT_CONFLICT", "command": "DUPLICATE_INTENT_CONFLICT",
        "no_read_callback": "SOURCE_UNAVAILABLE", "epoch": "CANCELLED_RUN",
    }[change]


def test_current_read_revocation_blocks_recovery_without_mutating_prior_facts(product_pg):
    from datetime import timedelta

    pg = product_pg
    call_id, receipt_id, result = completed(pg)
    with admin_session(pg) as session:
        grant = session.scalar(select(Grant).where(
            Grant.category_id == pg.scope.category_id, Grant.principal_id == pg.scope.writer_id,
        ))
        grant.expires_at = now() - timedelta(seconds=1)
    with pytest.raises(DomainError) as error:
        with app_session(pg) as session:
            recover_domain_call(session, pg.scope, pg.spec, pg.arguments, pg.source,
                                command_digest=digest("synthetic command"),
                                read_receipt=read_receipt)
    assert error.value.code == "FORBIDDEN_SCOPE"
    with admin_session(pg) as session:
        call = session.get(AgentToolCall, call_id)
        assert call.state == "completed" and call.result == result and call.receipt_id == receipt_id
        assert session.get(Receipt, receipt_id) is not None


def test_unadapted_category_receipt_owner_refuses_without_partial_call_commit(pg):
    with pytest.raises(DBAPIError) as error:
        with app_session(pg) as session:
            call, _ = prepare(session, pg)
            synthetic_receipt_atom(session, pg, call)
    assert error.value.orig.sqlstate == "42501"
    with admin_session(pg) as session:
        assert session.scalar(select(func.count()).select_from(AgentToolCall).where(
            AgentToolCall.run_id == pg.scope.run_id, AgentToolCall.tool == pg.spec.name,
        )) == 0
        assert session.scalar(select(func.count()).select_from(Receipt).where(
            Receipt.tenant_id == pg.scope.tenant_id,
        )) == 0


@pytest.mark.parametrize("change", [
    "arguments", "response_index", "model_run", "load_event_run", "route", "qualification",
])
def test_real_model_reply_skill_event_and_qualification_are_checked_before_new_call(pg, change):
    if change == "arguments":
        pg.arguments = {"text": "changed model arguments"}
    elif change == "response_index":
        pg.source = pg.source.model_copy(update={"response_index": 1})
    elif change in {"model_run", "load_event_run"}:
        with admin_session(pg) as session:
            other_run = AgentRun(
                tenant_id=pg.scope.tenant_id, category_id=pg.scope.category_id,
                session_id=pg.scope.session_id, requester_id=pg.scope.requester_id,
                writer_id=pg.scope.writer_id, trigger="page", goal="Synthetic other run",
                intent_key=str(uuid4()), intent_digest=digest(str(uuid4())),
                state="running", data_categories=list(pg.scope.data_categories),
                customer_identities=list(pg.scope.customer_identities), versions=pg.run.versions,
            )
            session.add(other_run)
            session.flush()
            binding = deepcopy(pg.model.execution_binding)
            target_run = other_run.id
            if change == "load_event_run":
                other_event = AgentEvent(
                    id=uuid4(), tenant_id=pg.scope.tenant_id, run_id=other_run.id,
                    sequence=1, body=deepcopy(pg.event.body),
                )
                session.add(other_event)
                pg.source = pg.source.model_copy(update={
                    "skill": pg.source.skill.model_copy(update={"load_event_id": other_event.id}),
                })
                binding["loaded_skills"] = [pg.source.skill.model_dump(mode="json")]
                target_run = pg.scope.run_id
            model = AgentToolCall(
                id=uuid4(), tenant_id=pg.scope.tenant_id, run_id=target_run,
                call_key=str(uuid4()), tool="model", input_digest=digest("synthetic"),
                state="completed", result=deepcopy(pg.model.result), execution_binding=binding,
            )
            session.add(model)
            pg.source = pg.source.model_copy(update={"model_call_id": model.id})
    elif change == "route":
        pg.route = SimpleNamespace(version="rotated@1", digest=pg.route.digest)
    else:
        with admin_session(pg) as session:
            session.get(type(pg.qualification), pg.qualification.id).qualification_revoked = True
    with pytest.raises(DomainError) as error:
        with app_session(pg) as session:
            prepare(session, pg)
    assert error.value.code == {
        "arguments": "DUPLICATE_INTENT_CONFLICT", "response_index": "FORBIDDEN_SCOPE",
        "model_run": "FORBIDDEN_SCOPE", "load_event_run": "FORBIDDEN_SCOPE",
        "route": "VERSION_CONFLICT", "qualification": "QUALIFICATION_REQUIRED",
    }[change]
    with admin_session(pg) as session:
        assert session.scalar(select(func.count()).select_from(AgentToolCall).where(
            AgentToolCall.run_id == pg.scope.run_id, AgentToolCall.tool == pg.spec.name,
        )) == 0


def test_actual_run_lock_refreshes_preloaded_identity_map_epoch(pg):
    with pytest.raises(DomainError) as error:
        with app_session(pg) as session:
            cached = session.get(AgentRun, pg.scope.run_id)
            assert cached.cancel_epoch == 0
            with admin_session(pg) as external:
                external.get(AgentRun, pg.scope.run_id).cancel_epoch = 1
            prepare(session, pg)
    assert error.value.code == "CANCELLED_RUN"


def test_finish_refreshes_epoch_changed_by_sql_in_the_same_uow(product_pg):
    pg = product_pg
    with pytest.raises(DomainError) as error:
        with app_session(pg) as session:
            call, _ = prepare(session, pg)
            receipt = synthetic_receipt_atom(session, pg, call)
            session.execute(text("UPDATE agent_runs SET cancel_epoch=1 WHERE id=:id"),
                            {"id": pg.scope.run_id})
            finish_domain_call(session, pg.scope, call.id, receipt.id)
    assert error.value.code == "CANCELLED_RUN"
    with admin_session(pg) as session:
        assert session.get(AgentRun, pg.scope.run_id).cancel_epoch == 0
        assert session.scalar(select(func.count()).select_from(Receipt).where(
            Receipt.tenant_id == pg.scope.tenant_id,
        )) == 0
