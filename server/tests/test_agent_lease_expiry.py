"""Independent pdos_test only: actual Agent credentials and PostgreSQL expiry clocks."""

from __future__ import annotations

import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from typing import NoReturn
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from psycopg import Error as PsycopgError
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.exc import DBAPIError

from app.ai.executor import AgentExecutor
from app.ai.gateway import GatewayInvocation
from app.ai.lease_heartbeat import AgentLeaseLostError, LeaseHeartbeat
from app.ai.run_store import ClaimedAgentRun, RestrictedAgentRunStore
from app.ai.runtime_contract import FrozenRunContext
from app.db.schema import tables
from app.db.url import psycopg_database_url
from tests.test_agent_database_security import role_engine, seed_two_tenants
from tests.test_agent_database_security import (
    secured_agent_database_url as secured_agent_database_url,
)

SERVER = Path(__file__).resolve().parents[1]


Leased = tuple[Engine, Engine, RestrictedAgentRunStore, ClaimedAgentRun, dict[str, UUID | int]]


@pytest.fixture
def leased(secured_agent_database_url: str) -> Iterator[Leased]:
    owner = create_engine(psycopg_database_url(secured_agent_database_url))
    agent = role_engine(secured_agent_database_url, "pdos_agent")
    try:
        with owner.begin() as c:
            ids = seed_two_tenants(c)
        store = RestrictedAgentRunStore(agent)
        # A caller cannot mint a future lease by supplying a future claim time.
        claim = store.claim(started_at=datetime(2100, 1, 1, tzinfo=UTC))
        assert claim is not None
        with store.scope(claim):
            yield owner, agent, store, claim, ids
    finally:
        agent.dispose()
        owner.dispose()


def context(owner: Engine, run: UUID) -> dict[str, object]:
    with owner.connect() as c:
        value = c.execute(
            select(tables.agent_runs.c.run_context).where(tables.agent_runs.c.id == run)
        ).scalar_one()
    assert isinstance(value, dict)
    assert all(isinstance(key, str) for key in value)
    return dict(value)


def expires(owner: Engine, run: UUID, seconds: float) -> None:
    with owner.begin() as c:
        c.execute(
            text("""UPDATE cehub_ai.agent_runs SET run_context=run_context || jsonb_build_object(
            '_lease_expires_at', clock_timestamp() + make_interval(secs => :s)) WHERE id=:r"""),
            {"s": seconds, "r": run},
        )


def test_database_clock_bounds_claim_and_authenticated_renewal(leased: Leased) -> None:
    owner, agent, store, claim, _ = leased
    original = context(owner, claim.id)
    renewed_at, expires_at = original["_lease_renewed_at"], original["_lease_expires_at"]
    assert isinstance(renewed_at, str) and isinstance(expires_at, str)
    start = datetime.fromisoformat(renewed_at)
    deadline = datetime.fromisoformat(expires_at)
    assert abs((start - datetime.now(UTC)).total_seconds()) < 5
    assert deadline - start == timedelta(seconds=60)
    renewed = store.renew(claim)
    assert renewed >= deadline
    with agent.begin() as c:
        for run, token in [(uuid4(), claim.lease_token), (claim.id, uuid4())]:
            with pytest.raises(DBAPIError) as denied, c.begin_nested():
                c.execute(
                    text("SELECT cehub_ai.renew_agent_run_lease(:r,:t)"), {"r": run, "t": token}
                )
            assert isinstance(denied.value.orig, PsycopgError)
            assert denied.value.orig.sqlstate == "42501"
        assert not c.execute(
            text(
                "SELECT has_function_privilege(current_user, "
                "'cehub_ai.agent_lease_is_current(uuid,uuid)', 'EXECUTE')"
            )
        ).scalar_one()


def test_expiry_removes_already_bound_projection_and_controlled_write_access(
    leased: Leased,
) -> None:
    owner, agent, store, claim, _ = leased
    with agent.begin() as c:
        store.bind(c)
        assert (
            c.execute(text("SELECT count(*) FROM cehub_ai.agent_project_projection")).scalar_one()
            == 1
        )
        expires(owner, claim.id, -1)
        assert (
            c.execute(text("SELECT count(*) FROM cehub_ai.agent_project_projection")).scalar_one()
            == 0
        )
        with pytest.raises(DBAPIError) as denied, c.begin_nested():
            c.execute(
                text("SELECT cehub_ai.complete_agent_run(:r,:t,'succeeded',NULL,now())"),
                {"r": claim.id, "t": claim.lease_token},
            )
        assert isinstance(denied.value.orig, PsycopgError)
        assert denied.value.orig.sqlstate == "42501"
        with pytest.raises(DBAPIError) as finding_denied, c.begin_nested():
            c.execute(
                text("""SELECT cehub_ai.create_agent_finding(
                    :f,:r,:t,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,now())"""),
                {"f": uuid4(), "r": claim.id, "t": claim.lease_token},
            )
        assert isinstance(finding_denied.value.orig, PsycopgError)
        assert finding_denied.value.orig.sqlstate == "42501"
        message = finding_denied.value.orig.diag.message_primary
        assert message is not None
        assert "lease" in message.lower()
    with pytest.raises(AgentLeaseLostError):
        store.renew(claim)
    with pytest.raises(AgentLeaseLostError), agent.begin() as c:
        store.bind(c)
    with pytest.raises(AgentLeaseLostError):
        store.fail(claim=claim, error_code="synthetic", completed_at=datetime.now(UTC))
    with owner.connect() as c:
        assert c.execute(select(tables.agent_runs.c.status)).scalar_one() == "running"
        assert c.execute(select(tables.findings)).first() is None


def test_context_cannot_replace_server_lease_expiry_or_token(leased: Leased) -> None:
    owner, agent, store, claim, ids = leased
    original = context(owner, claim.id)
    payload = dict(
        run_id=str(claim.id),
        tenant_id=str(ids["tenant_a"]),
        project_id=str(ids["project_a"]),
        agent_key="project_intelligence",
        schema_version=2,
        _lease_token=str(uuid4()),
        _lease_expires_at="2100-01-01T00:00:00Z",
        _lease_renewed_at="2100-01-01T00:00:00Z",
    )
    with agent.begin() as c:
        store.bind(c)
        c.execute(
            text("SELECT cehub_ai.persist_agent_run_context(:r,:t,CAST(:body AS jsonb),now())"),
            {"r": claim.id, "t": claim.lease_token, "body": json.dumps(payload)},
        )
    after = context(owner, claim.id)
    for key in ("_lease_token", "_lease_expires_at", "_lease_renewed_at"):
        assert after[key] == original[key]


def test_expiry_is_rechecked_after_waiting_for_renewal_row_lock(leased: Leased) -> None:
    owner, agent, _, claim, _ = leased
    entered = Event()

    def renew() -> None:
        with agent.begin() as c:
            entered.set()
            c.execute(
                text("SELECT cehub_ai.renew_agent_run_lease(:r,:t)"),
                {"r": claim.id, "t": claim.lease_token},
            )

    with ThreadPoolExecutor(max_workers=1) as pool:
        with owner.begin() as c:
            c.execute(
                text("""UPDATE cehub_ai.agent_runs
                SET run_context=run_context || jsonb_build_object(
                '_lease_expires_at', clock_timestamp() + interval '0.2 seconds') WHERE id=:r"""),
                {"r": claim.id},
            )
            future = pool.submit(renew)
            assert entered.wait(2)
            c.execute(text("SELECT pg_sleep(0.3)"))
        with pytest.raises(DBAPIError) as denied:
            future.result(timeout=5)
        assert isinstance(denied.value.orig, PsycopgError)
        assert denied.value.orig.sqlstate == "42501"


def test_actual_heartbeat_renews_with_independent_agent_connection(leased: Leased) -> None:
    owner, agent, store, claim, _ = leased
    expires(owner, claim.id, 0.5)
    heartbeat = LeaseHeartbeat(lambda: store.renew(claim), interval=0.05)
    heartbeat.start()
    try:
        with owner.connect() as c:
            c.execute(text("SELECT pg_sleep(0.65)"))
        heartbeat.require_current()
        with agent.begin() as c:
            store.bind(c)
            assert (
                c.execute(
                    text("SELECT count(*) FROM cehub_ai.agent_project_projection")
                ).scalar_one()
                == 1
            )
    finally:
        heartbeat.close()


def test_running_lease_prevents_downgrade_and_old_metadata_is_not_grandfathered(
    leased: Leased,
) -> None:
    owner, agent, _, claim, _ = leased
    with owner.connect() as c:
        original_head = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    with pytest.raises(DBAPIError, match="running lease history"):
        command.downgrade(Config(str(SERVER / "alembic.ini")), "0070_event_budget_binding")
    with owner.begin() as c:
        assert (
            c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == original_head
        )
        c.execute(
            text(
                "UPDATE cehub_ai.agent_runs SET run_context=run_context "
                "- '_lease_expires_at' WHERE id=:r"
            ),
            {"r": claim.id},
        )
    with pytest.raises(DBAPIError) as denied, agent.begin() as c:
        c.execute(
            text("SELECT cehub_ai.bind_agent_scope(:r,:t)"), {"r": claim.id, "t": claim.lease_token}
        )
    assert isinstance(denied.value.orig, PsycopgError)
    assert denied.value.orig.sqlstate == "42501"


def test_empty_history_migration_roundtrip(secured_agent_database_url: str) -> None:
    config = Config(str(SERVER / "alembic.ini"))
    command.downgrade(config, "0070_event_budget_binding")
    command.upgrade(config, "head")
    agent = role_engine(secured_agent_database_url, "pdos_agent")
    try:
        with agent.connect() as c:
            assert c.execute(
                text(
                    "SELECT has_function_privilege(current_user, "
                    "'cehub_ai.renew_agent_run_lease(uuid,uuid)', 'EXECUTE')"
                )
            ).scalar_one()
    finally:
        agent.dispose()


def test_executor_reports_lost_lease_without_finalizing_or_calling_model(
    secured_agent_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = create_engine(psycopg_database_url(secured_agent_database_url))
    agent = role_engine(secured_agent_database_url, "pdos_agent")

    class NeverInvoke:
        def invoke(self, _: GatewayInvocation) -> NoReturn:
            pytest.fail("expired worker must not call model")

    try:
        with owner.begin() as c:
            seed_two_tenants(c)
        executor = AgentExecutor(
            agent, model_invoker=NeverInvoke(), run_store=RestrictedAgentRunStore(agent)
        )
        original = executor._load_context

        def expired(*, claim: ClaimedAgentRun, built_at: datetime) -> FrozenRunContext:
            expires(owner, claim.id, -1)
            return original(claim=claim, built_at=built_at)

        monkeypatch.setattr(executor, "_load_context", expired)
        result = executor.execute_next()
        assert result.error_code == "AGENT_RUN_LEASE_LOST"
        with owner.connect() as c:
            assert c.execute(select(tables.agent_runs.c.status)).scalar_one() == "running"
            assert c.execute(select(tables.model_invocations)).first() is None
    finally:
        agent.dispose()
        owner.dispose()
