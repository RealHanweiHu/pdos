"""Authenticated request replay, fresh disclosure and event-free Chat runs."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from threading import Event
from typing import NoReturn
from uuid import UUID, uuid4

import httpx2
import pytest
from fastapi.testclient import TestClient
from psycopg import Error as PsycopgError
from pydantic import BaseModel
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.ai import application_gateway
from app.ai.budget_adoption import METER_DIGEST_KEY, METER_PATH_KEY, MODE_KEY, PROFILE_KEY
from app.ai.chat import ChatAssessment, ChatClaim
from app.ai.gateway import GatewayInvocation, GatewayResult, StructuredModelGateway
from app.api.ai import get_application_gateway
from app.db.engine import get_engine
from app.db.schema import tables
from app.main import app
from tests.db_cleanup import clear_test_tenants
from tests.migration_fixtures import rollback_migration_operations
from tests.test_ai_api import (
    FakeGateway,
    FakeObjectStore,
    login,
    seed_project_and_users,
    setup_owner,
)
from tests.test_ai_api import (
    api_context as api_context,
)
from tests.test_ai_api import (
    isolated_ai_api_database as isolated_ai_api_database,
)
from tests.test_input_metering import publication
from tests.test_model_budget_controller import response as model_response
from tests.test_model_gateway import qualification

ApiContext = tuple[TestClient, FakeObjectStore, FakeGateway]
ChatSetup = tuple[TestClient, FakeGateway, UUID, UUID, UUID, dict[str, str], dict[str, str]]


@pytest.fixture
def chat_setup(api_context: ApiContext, isolated_ai_api_database: str) -> Iterator[ChatSetup]:
    client, _, gateway = api_context
    tenant, owner, headers = setup_owner(client)
    project, _ = seed_project_and_users(isolated_ai_api_database, tenant_id=tenant)
    gateway.chat_output = ChatAssessment(
        disposition="answered",
        claims=(ChatClaim(text="The project is active.", citation_ids=(f"project:{project}",)),),
    )
    body = dict(project_id=str(project), question="What is the status?", request_id="same-request")
    try:
        yield client, gateway, tenant, owner, project, headers, body
    finally:
        with get_engine().begin() as connection:
            clear_test_tenants(connection)


@pytest.mark.parametrize("variant", ["same", "content", "actor", "source_changed"])
def test_chat_replay_binding_and_fresh_sources(chat_setup: ChatSetup, variant: str) -> None:
    client, gateway, tenant, owner, project, headers, body = chat_setup
    engine = get_engine()
    with engine.connect() as c:
        event_count = c.execute(select(func.count()).select_from(tables.events)).scalar_one()
    first = client.post("/api/ai/chat", headers=headers, json=body)
    assert first.status_code == 200 and first.json()["status"] == "answered", first.text
    with engine.begin() as c:
        run = c.execute(select(tables.agent_runs)).mappings().one()
        assert run["subscription_id"] is None and run["first_event_row_id"] is None
        assert run["event_count"] == 0 and run["event_row_ids"] == []
        assert run["requested_by_user_id"] == owner and run["status"] == "succeeded"
        assert (
            c.execute(select(func.count()).select_from(tables.events)).scalar_one() == event_count
        )
        if variant == "source_changed":
            c.execute(
                update(tables.projects)
                .where(tables.projects.c.id == project)
                .values(name="Changed")
            )
        if variant == "actor":
            manager = c.execute(
                select(tables.users.c.id).where(
                    tables.users.c.tenant_id == tenant, tables.users.c.username == "manager"
                )
            ).scalar_one()
            c.execute(
                tables.project_members.insert().values(
                    id=uuid4(),
                    tenant_id=tenant,
                    project_id=project,
                    user_id=manager,
                    added_by_user_id=owner,
                )
            )
    if variant == "actor":
        headers = login(client, "manager")
        listed = client.get(f"/api/ai/projects/{project}/runs", headers=headers)
        assert listed.status_code == 200 and listed.json()["items"] == []
    if variant == "content":
        body = {**body, "question": "Different content"}
    repeated = client.post("/api/ai/chat", headers=headers, json=body)
    if variant in {"actor", "content"}:
        assert repeated.status_code == 409
    elif variant == "source_changed":
        assert repeated.json()["error_code"] == "CHAT_EVIDENCE_CHANGED"
        assert repeated.json()["answer"] is None and repeated.json()["citations"] == []
    else:
        assert repeated.json() == first.json()
    assert len(gateway.invocations) == 1
    assert "request_id" not in gateway.invocations[0].context
    assert str(owner) not in str(gateway.invocations[0].context)


def test_chat_in_flight_overlap_cannot_create_second_run(
    chat_setup: ChatSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, gateway, _, _, _, headers, body = chat_setup
    entered, release = Event(), Event()
    original = gateway.invoke_structured

    def held[OutputT: BaseModel](
        invocation: GatewayInvocation, output_type: type[OutputT]
    ) -> GatewayResult[OutputT]:
        entered.set()
        assert release.wait(10)
        return original(invocation, output_type)

    monkeypatch.setattr(gateway, "invoke_structured", held)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.post, "/api/ai/chat", headers=headers, json=body)
        try:
            assert entered.wait(10)
            second = client.post("/api/ai/chat", headers=headers, json=body)
            assert second.status_code == 409
        finally:
            release.set()
        assert first.result(timeout=10).status_code == 200
    assert len(gateway.invocations) == 1
    with get_engine().connect() as c:
        assert c.execute(select(func.count()).select_from(tables.agent_runs)).scalar_one() == 1


def test_chat_revocation_during_model_call_blocks_disclosure(
    chat_setup: ChatSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, gateway, _, owner, _, headers, body = chat_setup
    original = gateway.invoke_structured

    def revoke[OutputT: BaseModel](
        invocation: GatewayInvocation, output_type: type[OutputT]
    ) -> GatewayResult[OutputT]:
        result = original(invocation, output_type)
        with get_engine().begin() as c:
            c.execute(
                update(tables.users).where(tables.users.c.id == owner).values(is_active=False)
            )
        return result

    monkeypatch.setattr(gateway, "invoke_structured", revoke)
    denied = client.post("/api/ai/chat", headers=headers, json=body)
    assert denied.status_code == 403 and "The project is active." not in denied.text
    with get_engine().connect() as c:
        row = c.execute(select(tables.agent_runs)).mappings().one()
    assert row["status"] == "degraded"
    assert row["run_context"]["chat_result"]["answer"] is None


def test_chat_unexpected_failure_is_persisted_and_never_reissued(
    chat_setup: ChatSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, gateway, _, _, _, headers, body = chat_setup
    calls: list[tuple[GatewayInvocation, type[BaseModel]]] = []

    def fail(invocation: GatewayInvocation, output_type: type[BaseModel]) -> NoReturn:
        calls.append((invocation, output_type))
        raise RuntimeError("synthetic interrupted response")

    monkeypatch.setattr(gateway, "invoke_structured", fail)
    with pytest.raises(RuntimeError, match="synthetic interrupted"):
        client.post("/api/ai/chat", headers=headers, json=body)
    repeated = client.post("/api/ai/chat", headers=headers, json=body)
    assert repeated.status_code == 200 and repeated.json()["error_code"] == "CHAT_REQUEST_FAILED"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"request_id": None},
        {"request_id": " "},
        {"requested_by_user_id": None},
        {"event_count": 1},
        {"first_event_row_id": 1},
        {"agent_key": "project_intelligence"},
    ],
)
def test_chat_database_origin_shape_is_not_nullable_bypass(
    chat_setup: ChatSetup, changes: dict[str, object]
) -> None:
    client, _, _, _, _, headers, body = chat_setup
    assert client.post("/api/ai/chat", headers=headers, json=body).status_code == 200
    with get_engine().connect() as c:
        row = dict(c.execute(select(tables.agent_runs)).mappings().one())
    row.update(id=uuid4(), request_id=str(uuid4()))
    now = datetime.now(UTC)
    row.update(window_started_at=now, window_ended_at=now)
    row.update(changes)
    with pytest.raises(IntegrityError) as denied, get_engine().begin() as c:
        c.execute(tables.agent_runs.insert().values(**row))
    assert isinstance(denied.value.orig, PsycopgError)
    assert denied.value.orig.sqlstate == "23514"
    assert denied.value.orig.diag.constraint_name == "ck_agent_runs_event_bounds_consistent"


def test_chat_migration_preserves_history_and_worker_cannot_impersonate_user(
    chat_setup: ChatSetup,
) -> None:
    client, _, _, _, _, headers, body = chat_setup
    with get_engine().connect() as c:
        original_head = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert client.post("/api/ai/chat", headers=headers, json=body).status_code == 200
    with (
        rollback_migration_operations(get_engine()),
        pytest.raises(DBAPIError, match="persistent Chat request history"),
    ):
        import_module("migrations.versions.0068_chat_request_runs").downgrade()
    with get_engine().connect() as c:
        assert (
            c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == original_head
        )
        if c.execute(text("SELECT 1 FROM pg_roles WHERE rolname='pdos_worker'")).first() is None:
            pytest.skip("worker role not installed in this isolated database")
        assert not c.execute(
            text(
                "SELECT has_column_privilege('pdos_worker', 'cehub_ai.agent_runs', "
                "'request_id', 'INSERT')"
            )
        ).scalar_one()
        assert not c.execute(
            text(
                "SELECT has_column_privilege('pdos_worker', 'cehub_ai.agent_runs', "
                "'requested_by_user_id', 'INSERT')"
            )
        ).scalar_one()
    with pytest.raises(DBAPIError) as denied, get_engine().begin() as c:
        c.execute(text("SET LOCAL ROLE pdos_worker"))
        c.execute(text("INSERT INTO cehub_ai.agent_runs (request_id) VALUES ('forged')"))
    assert isinstance(denied.value.orig, PsycopgError)
    assert denied.value.orig.sqlstate == "42501"


def test_chat_actual_api_reaches_explicit_budget_factory_once(
    chat_setup: ChatSetup, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _, _, project, headers, body = chat_setup
    path, _, digest = publication(tmp_path, qualified_input_limit=2000)
    output = ChatAssessment(
        disposition="answered",
        claims=(ChatClaim(text="The project is active.", citation_ids=(f"project:{project}",)),),
    )
    requests: list[httpx2.Request] = []

    def provider(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return model_response(output.model_dump_json())

    original_client = httpx2.Client
    monkeypatch.setattr(
        httpx2,
        "Client",
        lambda **kwargs: original_client(transport=httpx2.MockTransport(provider), **kwargs),
    )
    monkeypatch.setattr(
        application_gateway, "load_golden_qualifications", lambda *a, **kw: [qualification()]
    )
    environment = {
        "PDOS_LLM_PROVIDER": "minimax",
        "PDOS_LLM_MODEL": "MiniMax-M2.7",
        "PDOS_LLM_BASE_URL": "https://fake-openai.local/v1",
        "PDOS_LLM_API_KEY": "test-only",
        MODE_KEY: "budgeted",
        PROFILE_KEY: "short",
        METER_PATH_KEY: str(path),
        METER_DIGEST_KEY: digest,
    }

    def configured() -> Iterator[StructuredModelGateway]:
        with application_gateway.configured_application_gateway(
            get_engine(), environment
        ) as gateway:
            yield gateway

    app.dependency_overrides[get_application_gateway] = configured
    first = client.post("/api/ai/chat", headers=headers, json=body)
    assert first.status_code == 200 and first.json()["status"] == "answered", first.text
    assert client.post("/api/ai/chat", headers=headers, json=body).json() == first.json()
    assert len(requests) == 1
    with get_engine().connect() as c:
        run = c.execute(select(tables.agent_runs)).mappings().one()
        lineage = c.execute(select(tables.budget_run_links)).mappings().one()
        authorization = c.execute(select(tables.application_authorizations)).mappings().one()
        assert authorization["run_id"] == run["id"]
        assert authorization["principal_id"] == run["requested_by_user_id"]
        assert authorization["body"]["purpose"] == "chat_answer"
        trace = c.execute(select(tables.model_invocations)).mappings().one()
        entries = list(
            c.execute(
                select(tables.budget_journal).order_by(tables.budget_journal.c.revision)
            ).mappings()
        )
    assert lineage["run_id"] == run["id"] == trace["run_id"]
    assert trace["budget_call_id"] is not None and entries[-1]["charged_tokens"] == 10
    assert len(entries) == 3 and entries[-1]["held_tokens"] == 0
