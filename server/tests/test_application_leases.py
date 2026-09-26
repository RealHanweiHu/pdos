"""Actual Owner factory, expired/stolen lease fences and model-free supervision."""

from time import monotonic, sleep
from typing import NoReturn
from uuid import UUID, uuid4

import httpx2
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import DBAPIError

from app.ai import application_context, application_gateway, application_leases
from app.ai.application_leases import ApplicationLeaseKeeper, bind_write
from app.ai.chat import ChatAssessment
from app.ai.chat_runs import ChatRunStore
from app.ai.gateway import GatewayInvocation
from app.ai.lease_heartbeat import LeaseHeartbeat
from app.db.schema import metadata, tables
from app.worker.dispatcher import AgentDispatcher
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
from tests.test_budget_ledger import SERVER_ROOT
from tests.test_budget_ledger import ledger_db as ledger_db


def expire(engine: Engine, run: UUID) -> None:
    with engine.begin() as c:
        c.execute(
            tables.application_run_leases.update()
            .where(
                tables.application_run_leases.c.run_id == run,
            )
            .values(expires_at=func.clock_timestamp())
        )


def test_actual_heartbeat_renews_same_token_and_terminal_run_releases_it(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, tenant, _ = ledger_db
    environment, _, _ = factory_setup
    actor, project = identity(engine)
    monkeypatch.setattr(
        application_leases, "LeaseHeartbeat", lambda renew: LeaseHeartbeat(renew, interval=0.02)
    )
    with application_gateway.configured_application_gateway(engine, environment) as gateway:
        row, request = start(engine, gateway, tenant, actor, project)
        before = records(engine, tables.application_run_leases)[0]
        deadline = monotonic() + 2
        after = before
        while after["renewed_at"] == before["renewed_at"] and monotonic() < deadline:
            sleep(0.01)
            after = records(engine, tables.application_run_leases)[0]
        assert after["renewed_at"] > before["renewed_at"]
        assert before["id"] == after["id"]
        assert (
            after["expires_at"]
            <= records(engine, tables.application_authorizations)[0]["expires_at"]
        )
        assert gateway.invoke_structured(request, ChatAssessment).status == "succeeded"
        ChatRunStore(engine, gateway=gateway).finish(
            tenant_id=tenant,
            run_id=row["id"],
            result={
                "status": "insufficient_evidence",
                "answer": None,
                "citations": [],
                "error_code": None,
            },
        )
        ended = records(engine, tables.application_run_leases)[0]
        assert ended["ended_at"] and ended["stop_reason"] == "completed"
        manifest = records(engine, tables.application_context_manifests)[0]
        assert manifest["owner_lease_id"] == ended["id"]
        spans = records(engine, tables.budget_activity_spans)
        assert len(spans) == 1 and spans[0]["lease_token"] == ended["id"]
        assert spans[0]["stopped_at"] is not None


@pytest.mark.parametrize("fault", ["expired", "other_owner", "wrong_token"])
def test_unowned_or_expired_run_never_reaches_provider(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture, fault: str
) -> None:
    engine, tenant, _ = ledger_db
    environment, calls, _ = factory_setup
    actor, project = identity(engine)
    with application_gateway.configured_application_gateway(engine, environment) as gateway:
        row, request = start(engine, gateway, tenant, actor, project)
        keeper = gateway.application_lease_keeper
        assert isinstance(keeper, ApplicationLeaseKeeper)
        if fault == "expired":
            expire(engine, row["id"])
            old = records(engine, tables.application_run_leases)[0]
            keeper.renew_all()
            assert records(engine, tables.application_run_leases)[0] == old
            result = gateway.invoke_structured(request, ChatAssessment)
        elif fault == "wrong_token":
            keeper._tokens[tenant, row["id"]] = uuid4()
            result = gateway.invoke_structured(request, ChatAssessment)
        else:
            with application_gateway.configured_application_gateway(engine, environment) as other:
                result = other.invoke_structured(request, ChatAssessment)
        assert result.error_code == (
            "APPLICATION_RUN_LEASE_REQUIRED"
            if fault == "other_owner"
            else "APPLICATION_RUN_LEASE_LOST"
        )
    assert calls == [] and records(engine, tables.budget_journal) == []


def test_database_rechecks_lease_after_manifest_before_dispatch(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, tenant, _ = ledger_db
    environment, calls, _ = factory_setup
    actor, project = identity(engine)
    original = application_context.freeze_chat_manifest
    with application_gateway.configured_application_gateway(engine, environment) as gateway:
        row, request = start(engine, gateway, tenant, actor, project)

        def frozen(
            engine: Engine,
            invocation: GatewayInvocation,
            *,
            attempt_id: UUID,
            qualification: dict[str, object],
            removed_paths: tuple[str, ...],
            gateway: object = None,
        ) -> None:
            original(
                engine,
                invocation,
                attempt_id=attempt_id,
                qualification=qualification,
                removed_paths=removed_paths,
                gateway=gateway,
            )
            expire(engine, row["id"])

        monkeypatch.setattr(application_context, "freeze_chat_manifest", frozen)
        result = gateway.invoke_structured(request, ChatAssessment)
        assert result.error_code == "BUDGET_APPLICATION_LEASE_LOST"
    assert calls == []
    assert (
        max(records(engine, tables.budget_journal), key=lambda r: r["revision"])[
            "reservation_status"
        ]
        == "cancelled_before_dispatch"
    )


def test_success_publication_requires_original_token_even_for_database_owner(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture
) -> None:
    engine, tenant, _ = ledger_db
    environment, _, _ = factory_setup
    actor, project = identity(engine)
    with application_gateway.configured_application_gateway(engine, environment) as gateway:
        row, _ = start(engine, gateway, tenant, actor, project)
        with pytest.raises(DBAPIError, match="APPLICATION_RUN_LEASE_LOST"), engine.begin() as c:
            c.execute(
                tables.agent_runs.update()
                .where(tables.agent_runs.c.id == row["id"])
                .values(status="succeeded", completed_at=func.clock_timestamp())
            )
        with engine.begin() as c:
            bind_write(c, gateway, tenant, row["id"])
            c.execute(
                tables.agent_runs.update()
                .where(tables.agent_runs.c.id == row["id"])
                .values(status="succeeded", completed_at=func.clock_timestamp())
            )


def test_expiry_after_provider_keeps_actual_usage_and_hides_output(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, tenant, _ = ledger_db
    environment, calls, _ = factory_setup
    actor, project = identity(engine)
    original = base_factory.response
    with application_gateway.configured_application_gateway(engine, environment) as gateway:
        row, request = start(engine, gateway, tenant, actor, project)

        def response() -> httpx2.Response:
            expire(engine, row["id"])
            return original()

        monkeypatch.setattr(base_factory, "response", response)
        result = gateway.invoke_structured(request, ChatAssessment)
        assert result.output is None and result.error_code == "APPLICATION_RUN_LEASE_LOST"
    assert len(calls) == 1
    last = max(records(engine, tables.budget_journal), key=lambda r: r["revision"])
    assert last["reservation_status"] == "settled" and last["charged_tokens"] == 10
    assert records(engine, tables.model_invocations)[0]["status"] == "succeeded"


@pytest.mark.parametrize("unknown", [False, True])
def test_dispatcher_expires_interrupted_request_without_resetting_budget_or_recalling_model(
    ledger_db: LedgerFixture,
    factory_setup: FactoryFixture,
    monkeypatch: pytest.MonkeyPatch,
    unknown: bool,
) -> None:
    engine, tenant, _ = ledger_db
    environment, calls, _ = factory_setup
    actor, project = identity(engine)
    with application_gateway.configured_application_gateway(engine, environment) as gateway:
        row, request = start(engine, gateway, tenant, actor, project)
        if unknown:

            def timeout() -> NoReturn:
                raise httpx2.ReadTimeout("synthetic response lost")

            monkeypatch.setattr(base_factory, "response", timeout)
            assert gateway.invoke_structured(request, ChatAssessment).output is None
        expire(engine, row["id"])
        frozen = records(engine, tables.budget_lineages)
        budget_before = records(engine, tables.budget_journal)
        assert AgentDispatcher(engine).dispatch_once().stopped_run_count >= 1
        with engine.connect() as c:
            ended = (
                c.execute(select(tables.agent_runs).where(tables.agent_runs.c.id == row["id"]))
                .mappings()
                .one()
            )
            assert ended["status"] == "degraded"
            assert ended["error_code"] == (
                "APPLICATION_CALL_RECEIPT_UNKNOWN" if unknown else "APPLICATION_RUN_LEASE_EXPIRED"
            )
            assert c.execute(text("SELECT cehub_ai.expire_application_runs(100)")).scalar_one() == 0
        assert records(engine, tables.budget_lineages) == frozen
        assert records(engine, tables.budget_journal) == budget_before
        if unknown:
            last = max(budget_before, key=lambda r: r["revision"])
            assert last["reservation_status"] == "unknown" and last["held_tokens"] > 0
        span = next(
            s for s in records(engine, tables.budget_activity_spans) if s["run_id"] == row["id"]
        )
        assert span["stopped_at"] <= span["lease_expires_at"]
    assert len(calls) == int(unknown)


def test_lease_history_prevents_destructive_downgrade(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture
) -> None:
    engine, tenant, _ = ledger_db
    environment, _, _ = factory_setup
    actor, project = identity(engine)
    with application_gateway.configured_application_gateway(engine, environment) as gateway:
        start(engine, gateway, tenant, actor, project)
        for statement in (
            tables.application_run_leases.update().values(owner_id=uuid4()),
            tables.application_run_leases.delete(),
        ):
            with pytest.raises(DBAPIError, match="immutable"), engine.begin() as c:
                c.execute(statement)
        for values in ({"stop_reason": "completed"}, {"ended_at": func.clock_timestamp()}):
            with (
                pytest.raises(DBAPIError, match="ck_application_run_leases_lifecycle"),
                engine.begin() as c,
            ):
                c.execute(tables.application_run_leases.update().values(**values))
        with pytest.raises(DBAPIError, match="persistent application lease history"):
            command.downgrade(
                Config(str(SERVER_ROOT / "alembic.ini")), "0083_domain_context_adapters"
            )


def test_owner_lease_metadata_matches_database(ledger_db: LedgerFixture) -> None:
    engine, _, _ = ledger_db
    with engine.connect() as c:
        context = MigrationContext.configure(
            c,
            opts=dict(
                include_schemas=True,
                include_object=lambda obj, name, kind, reflected, compared: (
                    kind != "table" or name == "application_run_leases"
                ),
            ),
        )
        assert compare_metadata(context, metadata) == []
