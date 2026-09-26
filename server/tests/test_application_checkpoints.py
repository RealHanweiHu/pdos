"""Completed inference survives caller interruption without new budget or dispatch."""

from collections.abc import Callable
from dataclasses import replace
from time import sleep
from typing import NoReturn
from uuid import UUID, uuid4

import httpx2
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from pydantic import BaseModel
from sqlalchemy import Connection, Engine, RowMapping, text
from sqlalchemy.exc import DBAPIError

from app.ai import application_checkpoints, application_gateway
from app.ai.application_leases import ApplicationLeaseKeeper, bind_write
from app.ai.chat import ChatAssessment
from app.ai.gateway import GatewayInvocation, GatewayResult
from app.db.schema import metadata, tables
from tests import test_application_budget_factory as base_factory
from tests.test_application_authorization import (
    FactoryFixture,
    LedgerFixture,
    identity,
    records,
    start,
)
from tests.test_application_authorization import chat_provider as chat_provider
from tests.test_application_budget_factory import factory_setup as factory_setup
from tests.test_application_leases import expire
from tests.test_budget_ledger import SERVER_ROOT
from tests.test_budget_ledger import ledger_db as ledger_db


def snapshot(engine: Engine) -> list[list[RowMapping]]:
    return [
        records(engine, t)
        for t in (
            tables.budget_journal,
            tables.model_invocations,
            tables.model_call_sessions,
            tables.model_call_events,
            tables.application_context_manifests,
            tables.application_result_checkpoints,
        )
    ]


def test_completed_result_replays_without_new_model_meter_or_receipt(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, tenant, _ = ledger_db
    environment, calls, _ = factory_setup
    actor, project = identity(engine)
    with application_gateway.configured_application_gateway(engine, environment) as gateway:
        _, request = start(engine, gateway, tenant, actor, project)
        first = gateway.invoke_structured(request, ChatAssessment)
        assert first.output is not None
        checkpoint = records(engine, tables.application_result_checkpoints)[0]
        assert checkpoint["body"]["output"] == first.output.model_dump(mode="json")
        assert checkpoint["invocation_id"] == first.invocation_id
        before = snapshot(engine)

        def forbidden(*args: object, **kwargs: object) -> NoReturn:
            pytest.fail("durable result should not enter metering/admission again")

        monkeypatch.setattr(gateway._budget_controller, "complete", forbidden)
        assert gateway.invoke_structured(request, ChatAssessment) == first
        assert snapshot(engine) == before
    assert len(calls) == 1


def test_interruption_after_atomic_commit_recovers_the_original_result(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, tenant, _ = ledger_db
    environment, calls, _ = factory_setup
    actor, project = identity(engine)
    with application_gateway.configured_application_gateway(engine, environment) as gateway:
        _, request = start(engine, gateway, tenant, actor, project)
        original = gateway._call_fence.finish

        def interrupted(
            *,
            tenant_id: UUID,
            session_id: UUID,
            invocation_id: UUID,
            before_commit: Callable[[Connection], None] | None = None,
        ) -> NoReturn:
            original(
                tenant_id=tenant_id,
                session_id=session_id,
                invocation_id=invocation_id,
                before_commit=before_commit,
            )
            raise RuntimeError("synthetic caller interruption after commit")

        monkeypatch.setattr(gateway._call_fence, "finish", interrupted)
        with pytest.raises(RuntimeError, match="after commit"):
            gateway.invoke_structured(request, ChatAssessment)
        before = snapshot(engine)
        result = gateway.invoke_structured(request, ChatAssessment)
        assert result.status == "succeeded" and result.output is not None
        assert snapshot(engine) == before
        assert records(engine, tables.model_call_events)[-1]["state"] == "closed"
    assert len(calls) == 1


def test_interruption_before_commit_rolls_back_result_and_keeps_unknown_fence(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, tenant, _ = ledger_db
    environment, calls, _ = factory_setup
    actor, project = identity(engine)
    original = application_checkpoints.save
    with application_gateway.configured_application_gateway(engine, environment) as gateway:
        _, request = start(engine, gateway, tenant, actor, project)

        def interrupted(
            c: Connection,
            gateway: object,
            invocation: GatewayInvocation,
            result: GatewayResult[BaseModel],
        ) -> NoReturn:
            original(c, gateway, invocation, result)
            raise RuntimeError("synthetic persistence interruption")

        monkeypatch.setattr(application_checkpoints, "save", interrupted)
        with pytest.raises(RuntimeError, match="persistence interruption"):
            gateway.invoke_structured(request, ChatAssessment)
        assert records(engine, tables.application_result_checkpoints) == []
        assert (
            max(records(engine, tables.model_call_events), key=lambda r: r["revision"])["state"]
            == "unknown"
        )
        assert (
            max(records(engine, tables.budget_journal), key=lambda r: r["revision"])[
                "reservation_status"
            ]
            == "settled"
        )
        monkeypatch.setattr(application_checkpoints, "save", original)
        assert gateway.invoke_structured(request, ChatAssessment).output is None
    assert len(calls) == 1


@pytest.mark.parametrize(
    "fault", ["authorization", "source", "bundle", "context", "lease", "owner"]
)
def test_checkpoint_is_not_a_bypass_of_current_scope_and_source(
    ledger_db: LedgerFixture,
    factory_setup: FactoryFixture,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    from app.ai import application_context

    engine, tenant, _ = ledger_db
    environment, calls, _ = factory_setup
    actor, project = identity(engine)
    with application_gateway.configured_application_gateway(engine, environment) as gateway:
        row, request = start(engine, gateway, tenant, actor, project)
        assert gateway.invoke_structured(request, ChatAssessment).output is not None
        before = snapshot(engine)
        if fault == "authorization":
            with engine.begin() as c:
                c.execute(tables.project_members.delete())
        elif fault == "source":
            with engine.begin() as c:
                c.execute(
                    tables.projects.update()
                    .where(tables.projects.c.id == project)
                    .values(name="Changed")
                )
        elif fault == "bundle":
            original = application_context.chat_bundle
            monkeypatch.setattr(
                application_context,
                "chat_bundle",
                lambda *, work_focus=False: {
                    **original(work_focus=work_focus),
                    "version": "different",
                },
            )
        elif fault == "context":
            request = request.model_copy(
                update={"context": {**request.context, "question": "Other"}}
            )
        elif fault == "lease":
            expire(engine, row["id"])
        elif fault == "owner":
            assert isinstance(gateway.application_lease_keeper, ApplicationLeaseKeeper)
            gateway.application_lease_keeper._tokens.clear()
        result = gateway.invoke_structured(request, ChatAssessment)
        assert result.error_code is not None
        assert result.output is None and result.error_code.startswith("APPLICATION_")
        assert snapshot(engine) == before
    assert len(calls) == 1


def test_unknown_provider_receipt_never_becomes_reusable_result(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, tenant, _ = ledger_db
    environment, calls, _ = factory_setup
    actor, project = identity(engine)

    def timeout() -> NoReturn:
        raise httpx2.ReadTimeout("synthetic response lost")

    monkeypatch.setattr(base_factory, "response", timeout)
    with application_gateway.configured_application_gateway(engine, environment) as gateway:
        _, request = start(engine, gateway, tenant, actor, project)
        assert gateway.invoke_structured(request, ChatAssessment).output is None
        assert gateway.invoke_structured(request, ChatAssessment).output is None
    assert records(engine, tables.application_result_checkpoints) == [] and len(calls) == 1
    assert any(r["reservation_status"] == "unknown" for r in records(engine, tables.budget_journal))


def test_database_rejects_wrong_call_receipt_and_preserves_immutable_result(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture
) -> None:
    engine, tenant, _ = ledger_db
    environment, _, _ = factory_setup
    actor, project = identity(engine)
    with application_gateway.configured_application_gateway(engine, environment) as gateway:
        row, request = start(engine, gateway, tenant, actor, project)
        assert gateway.invoke_structured(request, ChatAssessment).status == "succeeded"
        checkpoint = dict(records(engine, tables.application_result_checkpoints)[0])
        with (
            pytest.raises(DBAPIError, match="APPLICATION_RESULT_RECEIPT_INVALID"),
            engine.begin() as c,
        ):
            bind_write(c, gateway, tenant, row["id"])
            c.execute(
                tables.application_result_checkpoints.insert().values(
                    **{**checkpoint, "id": uuid4(), "model_call_id": uuid4()}
                )
            )
        for statement in (
            tables.application_result_checkpoints.update().values(body={}),
            tables.application_result_checkpoints.delete(),
        ):
            with pytest.raises(DBAPIError, match="append-only"), engine.begin() as c:
                c.execute(statement)
        with pytest.raises(DBAPIError, match="persistent application result history"):
            command.downgrade(
                Config(str(SERVER_ROOT / "alembic.ini")), "0084_application_run_leases"
            )


def test_lease_expiry_at_persistence_closes_known_call_without_exposing_output(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, tenant, _ = ledger_db
    environment, calls, _ = factory_setup
    actor, project = identity(engine)
    original = application_checkpoints.save
    with application_gateway.configured_application_gateway(engine, environment) as gateway:
        row, request = start(engine, gateway, tenant, actor, project)

        def expired(
            c: Connection,
            gateway: object,
            invocation: GatewayInvocation,
            result: GatewayResult[BaseModel],
        ) -> None:
            expire(engine, row["id"])
            original(c, gateway, invocation, result)

        monkeypatch.setattr(application_checkpoints, "save", expired)
        result = gateway.invoke_structured(request, ChatAssessment)
        assert result.output is None and result.error_code == "APPLICATION_RUN_LEASE_LOST"
    assert len(calls) == 1 and records(engine, tables.application_result_checkpoints) == []
    assert (
        max(records(engine, tables.model_call_events), key=lambda r: r["revision"])["state"]
        == "closed"
    )
    assert (
        max(records(engine, tables.budget_journal), key=lambda r: r["revision"])["charged_tokens"]
        == 10
    )


def test_result_schema_matches_postgresql_and_empty_migration_roundtrips(
    ledger_db: LedgerFixture,
) -> None:
    engine, _, _ = ledger_db
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    with engine.connect() as c:
        original_head = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    command.downgrade(config, "0084_application_run_leases")
    command.upgrade(config, "head")
    with engine.connect() as c:
        context = MigrationContext.configure(
            c,
            opts=dict(
                include_schemas=True,
                include_object=lambda obj, name, kind, reflected, compared: (
                    kind != "table" or name == "application_result_checkpoints"
                ),
            ),
        )
        assert compare_metadata(context, metadata) == []
        assert (
            c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == original_head
        )


@pytest.mark.parametrize("fault", ["unavailable", "model", "active_budget"])
def test_cached_result_honors_current_model_policy_and_active_execution_budget(
    ledger_db: LedgerFixture,
    factory_setup: FactoryFixture,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    engine, tenant, _ = ledger_db
    environment, calls, _ = factory_setup
    actor, project = identity(engine)
    with application_gateway.configured_application_gateway(engine, environment) as gateway:
        if fault == "active_budget":
            assert gateway._budget_controller is not None
            assert gateway.creation_budget_profile is not None
            gateway._budget_controller._profile = gateway.creation_budget_profile.model_copy(
                update={"active_seconds": 10}
            )
        row, request = start(engine, gateway, tenant, actor, project)
        assert gateway.invoke_structured(request, ChatAssessment).status == "succeeded"
        before = snapshot(engine)
        if fault == "unavailable":
            old = gateway._governance.get(tenant_id=tenant)
            selection = old.selection
            assert selection is not None
            monkeypatch.setattr(
                gateway._governance,
                "get",
                lambda **kw: replace(old, selection=replace(selection, available=False)),
            )
        elif fault == "model":
            original = type(gateway._catalog).resolve_route
            monkeypatch.setattr(
                type(gateway._catalog),
                "resolve_route",
                lambda self, **kw: replace(original(self, **kw), model="different-qualified-model"),
            )
        else:
            with engine.connect() as c:
                elapsed = c.execute(
                    text("""SELECT extract(epoch FROM clock_timestamp()-started_at)
                    FROM cehub_ai.budget_activity_spans WHERE run_id=:r"""),
                    dict(r=row["id"]),
                ).scalar_one()
            sleep(max(0, 10.1 - float(elapsed)))
        result = gateway.invoke_structured(request, ChatAssessment)
        assert (
            result.output is None
            and result.error_code
            == {
                "unavailable": "MODEL_NOT_AVAILABLE",
                "model": "APPLICATION_RESULT_MODEL_CHANGED",
                "active_budget": "BUDGET_ACTIVE_TIME_EXHAUSTED",
            }[fault]
        )
        assert snapshot(engine) == before
    assert len(calls) == 1
