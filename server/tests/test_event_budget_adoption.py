"""Real worker/Agent accounts on an independent pdos_test; synthetic provider only."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NoReturn
from uuid import UUID, uuid4

import httpx2
import pytest
from sqlalchemy import Connection, Engine, RowMapping, create_engine, select, text
from sqlalchemy.exc import DBAPIError

from app.ai import runtime_factory
from app.ai.budget_adoption import (
    AGENT_METER_DIGEST_KEY,
    AGENT_METER_PATH_KEY,
    AGENT_MODE_KEY,
    AGENT_PROFILE_KEY,
    approved_budget_profile,
)
from app.ai.budget_ledger import _profile_digest
from app.ai.input_metering import MeteringError
from app.ai.runtime_contract import AgentKey
from app.db.schema import tables
from app.db.url import psycopg_database_url
from app.worker.dispatcher import AgentDispatcher
from tests.test_agent_database_security import role_engine, seed_two_tenants
from tests.test_agent_database_security import (
    secured_agent_database_url as secured_agent_database_url,
)
from tests.test_input_metering import publication
from tests.test_model_budget_controller import response
from tests.test_model_gateway import qualification

EventScope = tuple[Engine, Engine, Engine, dict[str, UUID | int]]


def scope_id(ids: dict[str, UUID | int], name: str) -> UUID:
    value = ids[name]
    assert isinstance(value, UUID)
    return value


@pytest.fixture
def event_scope(secured_agent_database_url: str) -> Iterator[EventScope]:
    owner = create_engine(psycopg_database_url(secured_agent_database_url))
    worker = role_engine(secured_agent_database_url, "pdos_worker")
    agent = role_engine(secured_agent_database_url, "pdos_agent")
    try:
        with owner.begin() as c:
            ids = seed_two_tenants(c)
            c.execute(tables.agent_runs.delete())
            c.execute(
                tables.tenant_model_settings.insert().values(
                    id=uuid4(),
                    tenant_id=scope_id(ids, "tenant_a"),
                    provider="minimax",
                    model="MiniMax-M2.7",
                    daily_token_budget=100000,
                )
            )
        yield owner, worker, agent, ids
    finally:
        agent.dispose()
        worker.dispose()
        owner.dispose()


@pytest.mark.parametrize("key", ["short", "work_package", "research_discussion"])
def test_worker_freezes_approved_budget_atomically_before_queue_and_does_not_rebind(
    event_scope: EventScope, key: str
) -> None:
    owner, worker, agent, ids = event_scope
    service = AgentDispatcher(worker, budget_profile_key=key)
    assert service.dispatch_tenant(tenant_id=scope_id(ids, "tenant_a")).created_run_count == 1
    with owner.connect() as c:
        run = c.execute(select(tables.agent_runs)).mappings().one()
        frozen = c.execute(select(tables.budget_lineages)).mappings().one()
        assert run["status"] == "debouncing"
        assert frozen["profile"] == approved_budget_profile(key).model_dump(mode="json")
        assert frozen["profile_digest"] == _profile_digest(approved_budget_profile(key))
        assert frozen["absolute_deadline"] - frozen["created_at"] == timedelta(
            seconds=approved_budget_profile(key).lifetime_seconds
        )
        assert run["created_at"] <= frozen["created_at"] <= datetime.now(UTC)
        assert c.execute(select(tables.budget_journal)).first() is None
    # New process policy and repeated dispatch/sealing cannot reset existing run budgets.
    changed = AgentDispatcher(worker, budget_profile_key="research_discussion")
    changed.dispatch_tenant(tenant_id=scope_id(ids, "tenant_a"))
    changed.seal_due_runs()
    with owner.connect() as c:
        assert dict(c.execute(select(tables.budget_lineages)).mappings().one()) == dict(frozen)
        assert c.execute(select(tables.agent_runs.c.status)).scalar_one() == "queued"
    for engine in (worker, agent):
        with engine.connect() as c:
            for table in ("budget_lineages", "budget_run_links", "budget_journal"):
                assert not c.execute(
                    text("SELECT has_table_privilege(current_user, :t, 'INSERT')"),
                    {"t": "cehub_ai." + table},
                ).scalar_one()
            assert not c.execute(
                text(
                    "SELECT has_function_privilege(current_user, "
                    "'cehub_ai.freeze_event_run_budget()', 'EXECUTE')"
                )
            ).scalar_one()


def test_default_dispatcher_resets_stale_pooled_profile_and_does_not_backfill(
    event_scope: EventScope,
) -> None:
    owner, worker, _, ids = event_scope
    with worker.begin() as c:
        c.execute(text("SELECT set_config('pdos.event_budget_profile', 'short', false)"))
    AgentDispatcher(worker).dispatch_tenant(tenant_id=scope_id(ids, "tenant_a"))
    AgentDispatcher(worker, budget_profile_key="short").dispatch_tenant(
        tenant_id=scope_id(ids, "tenant_a")
    )
    with owner.connect() as c:
        assert c.execute(select(tables.agent_runs)).first() is not None
        assert c.execute(select(tables.budget_lineages)).first() is None


def test_bad_database_profile_rolls_back_run_and_cursor_and_trigger_cannot_be_used_late(
    event_scope: EventScope, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, worker, _, ids = event_scope
    service = AgentDispatcher(worker, budget_profile_key="short")
    # Bypass Python validation only to exercise the database's independent trusted-policy check.
    monkeypatch.setattr(service, "_budget_profile_key", "model-invented-limit")
    with pytest.raises(DBAPIError, match="BUDGET_APPROVED_PROFILE_REQUIRED"):
        service.dispatch_tenant(tenant_id=scope_id(ids, "tenant_a"))
    with owner.connect() as c:
        for table in (tables.agent_runs, tables.budget_lineages, tables.agent_dispatcher_cursors):
            assert c.execute(select(table)).first() is None
    service = AgentDispatcher(worker, budget_profile_key="short")
    original = service._route_event

    def fail_after_creation(
        connection: Connection, *, event: RowMapping, subscription: RowMapping, agent_key: AgentKey
    ) -> NoReturn:
        original(connection, event=event, subscription=subscription, agent_key=agent_key)
        raise RuntimeError("synthetic transaction rollback")

    monkeypatch.setattr(service, "_route_event", fail_after_creation)
    with pytest.raises(RuntimeError, match="transaction rollback"):
        service.dispatch_tenant(tenant_id=scope_id(ids, "tenant_a"))
    with owner.connect() as c:
        for table in (tables.agent_runs, tables.budget_lineages, tables.budget_run_links):
            assert c.execute(select(table)).first() is None


@pytest.mark.parametrize(
    "mode", ["budgeted", "wrong_profile", "unbound", "legacy", "bad_meter", "expired_response"]
)
def test_actual_dispatcher_and_restricted_runtime_factory(
    event_scope: EventScope, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    owner, worker, agent, ids = event_scope
    AgentDispatcher(
        worker,
        budget_profile_key=(
            None if mode == "unbound" else "work_package" if mode == "wrong_profile" else "short"
        ),
    ).dispatch_tenant(tenant_id=scope_id(ids, "tenant_a"))
    AgentDispatcher(worker).seal_due_runs()
    path, _, digest = publication(tmp_path, qualified_input_limit=6000)
    calls: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        if mode == "expired_response":
            with owner.begin() as c:
                c.execute(
                    text("""UPDATE cehub_ai.agent_runs
                    SET run_context=run_context || jsonb_build_object(
                        '_lease_expires_at', clock_timestamp() - interval '1 second')
                    WHERE status='running'""")
                )
        return response(
            json.dumps(
                dict(
                    disposition="no_action",
                    candidate_type=None,
                    summary="No supported action.",
                    proposed_payload=None,
                    evidence_event_ids=[],
                    confidence=0.8,
                )
            )
        )

    client_class = httpx2.Client
    monkeypatch.setattr(
        httpx2,
        "Client",
        lambda **kwargs: client_class(transport=httpx2.MockTransport(respond), **kwargs),
    )
    monkeypatch.setattr(
        runtime_factory, "load_golden_qualifications", lambda *a, **kw: [qualification()]
    )
    env = {
        "PDOS_AGENT_DATABASE_URL": agent.url.render_as_string(hide_password=False),
        "PDOS_LLM_PROVIDER": "minimax",
        "PDOS_LLM_BASE_URL": "https://fake-openai.local/v1",
        "PDOS_LLM_API_KEY": "test-secret",
        "PDOS_LLM_MODEL": "MiniMax-M2.7",
        AGENT_MODE_KEY: "budgeted",
        AGENT_PROFILE_KEY: "short",
        AGENT_METER_PATH_KEY: str(path),
        AGENT_METER_DIGEST_KEY: digest,
    }
    if mode == "legacy":
        for key in (
            AGENT_MODE_KEY,
            AGENT_PROFILE_KEY,
            AGENT_METER_PATH_KEY,
            AGENT_METER_DIGEST_KEY,
        ):
            env.pop(key)
    if mode == "bad_meter":
        path.write_text("{}")
        with pytest.raises(MeteringError), runtime_factory.configured_agent_runtime(env):
            pytest.fail("tampered meter must prevent runtime startup")
        assert calls == []
        with owner.connect() as c:
            assert c.execute(select(tables.agent_runs.c.status)).scalar_one() == "queued"
        return
    with runtime_factory.configured_agent_runtime(env) as runtime:
        outcome = runtime.executor.execute_next()
        assert runtime.executor.execute_next().status == "idle"
    if mode == "expired_response":
        assert outcome.error_code == "AGENT_RUN_LEASE_LOST"
        assert outcome.status == "failed" and len(calls) == 1
        with owner.connect() as c:
            assert c.execute(select(tables.agent_runs.c.status)).scalar_one() == "running"
            assert c.execute(select(tables.findings)).first() is None
            assert c.execute(select(tables.model_invocations)).first() is None
            entries = list(
                c.execute(
                    select(tables.budget_journal).order_by(tables.budget_journal.c.revision)
                ).mappings()
            )
            assert len(entries) == 2 and entries[-1]["held_tokens"] > 0
            events = list(c.execute(select(tables.model_call_events.c.state)).scalars())
            assert events == ["open"]
        return
    expected = {
        "wrong_profile": "BUDGET_PROFILE_CONFLICT",
        "unbound": "BUDGET_RUN_UNBOUND",
        "legacy": "MODEL_CALL_BUDGET_REQUIRED",
    }.get(mode)
    assert outcome.error_code == expected, outcome
    assert outcome.status == ("succeeded" if mode == "budgeted" else "degraded"), outcome
    assert len(calls) == (1 if mode == "budgeted" else 0)
    with owner.connect() as c:
        assert c.execute(select(tables.findings)).first() is None
        if mode == "budgeted":
            run = c.execute(select(tables.agent_runs)).mappings().one()
            trace = c.execute(select(tables.model_invocations)).mappings().one()
            assert trace["run_id"] == run["id"] == outcome.run_id
            entries = list(
                c.execute(
                    select(tables.budget_journal).order_by(tables.budget_journal.c.revision)
                ).mappings()
            )
            assert len(entries) == 3
            assert entries[-1]["charged_tokens"] == 10 and entries[-1]["held_tokens"] == 0
            assert entries[0]["request_binding"]["model_call_id"] == str(trace["budget_call_id"])
            assert json.loads(calls[0].content)["max_completion_tokens"] == 64
        else:
            assert c.execute(select(tables.budget_journal)).first() is None


def test_event_budget_migration_refuses_to_remove_binding_with_history(
    event_scope: EventScope,
) -> None:
    from alembic import command
    from alembic.config import Config

    from tests.test_agent_database_security import SERVER_ROOT

    owner, worker, _, ids = event_scope
    AgentDispatcher(worker, budget_profile_key="short").dispatch_tenant(
        tenant_id=scope_id(ids, "tenant_a")
    )
    with owner.connect() as c:
        original_head = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    with pytest.raises(DBAPIError, match="persistent budget history"):
        command.downgrade(Config(str(SERVER_ROOT / "alembic.ini")), "0069_import_mapping_runs")
    with owner.connect() as c:
        assert (
            c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == original_head
        )
        assert c.execute(select(tables.budget_run_links)).first() is not None
        assert c.execute(
            text("SELECT 1 FROM pg_trigger WHERE tgname = 'freeze_event_run_budget'")
        ).first()
