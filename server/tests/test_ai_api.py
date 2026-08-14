from __future__ import annotations

import os
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from openpyxl import Workbook
from pydantic import BaseModel
from pypdf import PdfWriter
from sqlalchemy import create_engine, select, text

from app.ai.chat import ChatAssessment, ChatClaim
from app.ai.embeddings import EmbeddingResult
from app.ai.executor import AgentAssessment
from app.ai.gateway import GatewayInvocation, GatewayResult
from app.api.ai import get_application_gateway, get_optional_embedding_gateway
from app.auth.passwords import PasswordService
from app.auth.roles import Role
from app.db.engine import get_engine
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.domain.findings import RiskSuggestionPayload
from app.domain.memories import MemoryDraft, MemoryService
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft
from app.main import app
from app.settings import get_settings
from app.storage.documents import DocumentObjectStore, get_document_object_store

SERVER_ROOT = Path(__file__).resolve().parents[1]
TEST_JWT_SECRET = "test-only-jwt-secret-that-is-at-least-32-bytes"
PASSWORD = "correct horse battery staple"


class FakeObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, *, object_key: str, content: bytes, media_type: str, sha256: str) -> None:
        del media_type, sha256
        self.objects[object_key] = content

    def delete(self, *, object_key: str) -> None:
        self.objects.pop(object_key, None)


class FakeGateway:
    def __init__(self) -> None:
        self.invocations: list[GatewayInvocation] = []
        self.chat_output = ChatAssessment(
            disposition="answered",
            claims=(
                ChatClaim(
                    text="The project is active.",
                    citation_ids=("project:placeholder",),
                ),
            ),
        )
        self.risk_output = AgentAssessment(
            disposition="no_action",
            candidate_type=None,
            summary="No risk is supported.",
            proposed_payload=None,
            evidence_event_ids=(),
            confidence=0.8,
        )

    def invoke_structured[OutputT: BaseModel](
        self,
        invocation: GatewayInvocation,
        output_type: type[OutputT],
    ) -> GatewayResult[OutputT]:
        self.invocations.append(invocation)
        output: BaseModel = self.chat_output if output_type is ChatAssessment else self.risk_output
        invocation_id = uuid4()
        with get_engine().begin() as connection:
            connection.execute(
                tables.model_invocations.insert(),
                {
                    "id": invocation_id,
                    "tenant_id": invocation.tenant_id,
                    "project_id": invocation.project_id,
                    "run_id": invocation.run_id,
                    "agent_key": invocation.agent_key,
                    "agent_tier": invocation.agent_tier.value,
                    "prompt_version": invocation.prompt_version,
                    "provider": "minimax",
                    "model": "fake-model",
                    "protocol": "openai-compatible",
                    "status": "succeeded",
                    "structured_attempts": 1,
                },
            )
        return GatewayResult(
            status="succeeded",
            output=output_type.model_validate(output.model_dump()),
            error_code=None,
            structured_attempts=1,
            removed_context_paths=(),
            invocation_id=invocation_id,
        )


class FakeEmbeddingGateway:
    provider = "test"
    model = "memory-v1"
    dimensions = 3

    def embed(self, text_value: str) -> EmbeddingResult:
        assert text_value.strip()
        return EmbeddingResult(provider=self.provider, model=self.model, values=(1.0, 0.0, 0.0))


@pytest.fixture(autouse=True)
def isolated_ai_api_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    test_url = configured_test_database_url()
    monkeypatch.setenv("DATABASE_URL", test_url)
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("JWT_ISSUER", "pdos-test")
    monkeypatch.setenv("JWT_AUDIENCE", "pdos-test-client")
    get_settings.cache_clear()
    get_engine.cache_clear()
    os.environ["DATABASE_URL"] = test_url
    command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")
    engine = create_engine(psycopg_database_url(test_url))
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE cehub_core.tenants CASCADE"))
        yield test_url
    finally:
        engine.dispose()
        get_engine().dispose()
        get_engine.cache_clear()
        get_settings.cache_clear()
        app.dependency_overrides.clear()


@pytest.fixture
def api_context() -> Iterator[tuple[TestClient, FakeObjectStore, FakeGateway]]:
    object_store = FakeObjectStore()
    gateway = FakeGateway()

    def object_store_dependency() -> DocumentObjectStore:
        return object_store

    def gateway_dependency() -> Iterator[FakeGateway]:
        yield gateway

    app.dependency_overrides[get_document_object_store] = object_store_dependency
    app.dependency_overrides[get_application_gateway] = gateway_dependency
    with TestClient(app) as client:
        yield client, object_store, gateway


def setup_owner(client: TestClient) -> tuple[UUID, UUID, dict[str, str]]:
    response = client.post(
        "/api/setup",
        json={
            "tenant_slug": "beepump",
            "tenant_name": "Beehive Technology",
            "username": "owner",
            "password": PASSWORD,
            "display_name": "Initial Owner",
        },
    )
    assert response.status_code == 201
    body = response.json()
    login = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": "owner", "password": PASSWORD},
    )
    return (
        UUID(body["tenant"]["id"]),
        UUID(body["user"]["id"]),
        {"Authorization": f"Bearer {login.json()['access_token']}"},
    )


def seed_project_and_users(database_url: str, *, tenant_id: UUID) -> tuple[UUID, int]:
    workflow_id = uuid4()
    project_id = uuid4()
    issue_id = uuid4()
    engine = create_engine(psycopg_database_url(database_url))
    password_hash = PasswordService().hash(PASSWORD)
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.users.insert(),
                [
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "username": "manager",
                        "display_name": "Manager",
                        "role": Role.PROJECT_MANAGER,
                        "password_hash": password_hash,
                    },
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "username": "supplier",
                        "display_name": "Supplier",
                        "role": Role.SUPPLIER,
                        "password_hash": password_hash,
                    },
                ],
            )
            connection.execute(
                tables.workflows.insert(),
                {
                    "id": workflow_id,
                    "tenant_id": tenant_id,
                    "code": "ai-api",
                    "name": "AI API",
                },
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": project_id,
                    "tenant_id": tenant_id,
                    "workflow_id": workflow_id,
                    "code": "PRJ-AI",
                    "name": "AI Project",
                    "status": "active",
                },
            )
            connection.execute(
                tables.issues.insert(),
                {
                    "id": issue_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "title": "Connector slips",
                    "status": "open",
                    "severity": "high",
                },
            )
            written = EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=None,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"issue:{issue_id}:created",
                    event_type="ISSUE_CREATED",
                    source="issue_service",
                    entity_id=issue_id,
                    payload={"issue_id": str(issue_id), "severity": "high"},
                ),
                AuditDraft(
                    action="issue.create",
                    after_snapshot={"title": "Connector slips", "status": "open"},
                ),
            )
    finally:
        engine.dispose()
    return project_id, written.event_row_id


def login(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def xlsx_bytes() -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    assert worksheet is not None
    worksheet.title = "Risks"
    worksheet.append(["Risk", "Severity"])
    worksheet.append(["Connector slip", "High"])
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def textless_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=10, height=10)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_document_analysis_persists_object_fragments_and_event(
    api_context: tuple[TestClient, FakeObjectStore, FakeGateway],
    isolated_ai_api_database: str,
) -> None:
    client, object_store, _ = api_context
    tenant_id, _, headers = setup_owner(client)
    project_id, _ = seed_project_and_users(isolated_ai_api_database, tenant_id=tenant_id)

    response = client.post(
        "/api/ai/analyze-document",
        headers=headers,
        data={"project_id": str(project_id), "classification": "internal"},
        files={"file": ("risks.xlsx", xlsx_bytes())},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["extraction_status"] == "extracted"
    assert body["fragments"][0]["locator"] == "sheet:Risks,rows:1-2"
    assert body["fragments"][0]["href"].startswith(f"/projects?project={project_id}")
    assert len(object_store.objects) == 1
    assert body["sha256"] not in str(body["fragments"])
    listed = client.get(f"/api/ai/projects/{project_id}/documents", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["items"][0] == {
        "document_id": body["document_id"],
        "project_id": str(project_id),
        "filename": "risks.xlsx",
        "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "classification": "internal",
        "size_bytes": body["size_bytes"],
        "sha256": body["sha256"],
        "extraction_status": "extracted",
        "created_at": listed.json()["items"][0]["created_at"],
    }
    assert "object_key" not in listed.text
    engine = create_engine(psycopg_database_url(isolated_ai_api_database))
    try:
        with engine.connect() as connection:
            document = connection.execute(select(tables.documents)).mappings().one()
            event = (
                connection.execute(
                    select(tables.events).where(tables.events.c.event_type == "DOCUMENT_UPLOADED")
                )
                .mappings()
                .one()
            )
            fragment = connection.execute(select(tables.document_fragments)).mappings().one()
        assert document["object_key"] not in response.text
        assert fragment["text"] == "Risk\tSeverity\nConnector slip\tHigh"
        assert event["entity_id"] == UUID(body["document_id"])
    finally:
        engine.dispose()


def test_document_analysis_marks_textless_pdf_for_ocr_without_a_fragment(
    api_context: tuple[TestClient, FakeObjectStore, FakeGateway],
    isolated_ai_api_database: str,
) -> None:
    client, _, _ = api_context
    tenant_id, _, headers = setup_owner(client)
    project_id, _ = seed_project_and_users(isolated_ai_api_database, tenant_id=tenant_id)
    response = client.post(
        "/api/ai/analyze-document",
        headers=headers,
        data={"project_id": str(project_id)},
        files={"file": ("scan.pdf", textless_pdf_bytes())},
    )

    assert response.status_code == 201
    assert response.json()["extraction_status"] == "ocr_required"
    assert response.json()["fragments"] == []


def test_chat_only_returns_server_mapped_citations_and_fail_closes_unknown_ids(
    api_context: tuple[TestClient, FakeObjectStore, FakeGateway],
    isolated_ai_api_database: str,
) -> None:
    client, _, gateway = api_context
    tenant_id, _, headers = setup_owner(client)
    project_id, _ = seed_project_and_users(isolated_ai_api_database, tenant_id=tenant_id)
    gateway.chat_output = ChatAssessment(
        disposition="answered",
        claims=(
            ChatClaim(
                text="The project is active.",
                citation_ids=(f"project:{project_id}",),
            ),
        ),
    )

    answered = client.post(
        "/api/ai/chat",
        headers=headers,
        json={"project_id": str(project_id), "question": "What is the status?"},
    )

    assert answered.status_code == 200
    assert answered.json()["status"] == "answered"
    assert answered.json()["citations"][0]["href"] == f"/projects?project={project_id}&tab=overview"
    invocation_context = gateway.invocations[-1].context
    assert "href" not in str(invocation_context)
    assert "object_key" not in str(invocation_context)

    gateway.chat_output = ChatAssessment(
        disposition="answered",
        claims=(ChatClaim(text="Invented.", citation_ids=("risk:cross-tenant",)),),
    )
    rejected = client.post(
        "/api/ai/chat",
        headers=headers,
        json={"project_id": str(project_id), "question": "Invent something"},
    )
    assert rejected.json() == {
        "status": "insufficient_evidence",
        "answer": None,
        "citations": [],
        "error_code": "CITATION_SCOPE_INVALID",
    }


def test_chat_can_cite_only_verified_memory_without_exposing_vectors(
    api_context: tuple[TestClient, FakeObjectStore, FakeGateway],
    isolated_ai_api_database: str,
) -> None:
    client, _, gateway = api_context
    tenant_id, owner_id, headers = setup_owner(client)
    project_id, _ = seed_project_and_users(isolated_ai_api_database, tenant_id=tenant_id)
    engine = create_engine(psycopg_database_url(isolated_ai_api_database))
    embedding_gateway = FakeEmbeddingGateway()
    try:
        with engine.connect() as connection:
            verifier_id = UUID(
                str(
                    connection.execute(
                        select(tables.users.c.id).where(
                            tables.users.c.tenant_id == tenant_id,
                            tables.users.c.username == "manager",
                        )
                    ).scalar_one()
                )
            )
        memory = MemoryService(engine).create(
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=owner_id,
            draft=MemoryDraft(
                title="Connector DVT lesson",
                content="Validate connector pin mapping before the DVT build.",
                tags=("DVT", "connector"),
            ),
        )
        MemoryService(engine).verify(
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=verifier_id,
            memory_id=memory.id,
            gateway=embedding_gateway,
        )
    finally:
        engine.dispose()

    def embedding_dependency() -> Iterator[FakeEmbeddingGateway]:
        yield embedding_gateway

    app.dependency_overrides[get_optional_embedding_gateway] = embedding_dependency
    gateway.chat_output = ChatAssessment(
        disposition="answered",
        claims=(
            ChatClaim(
                text="Validate the connector before DVT.",
                citation_ids=(f"memory:{memory.id}",),
            ),
        ),
    )

    response = client.post(
        "/api/ai/chat",
        headers=headers,
        json={"project_id": str(project_id), "question": "What was the connector lesson?"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "answered"
    assert response.json()["citations"] == [
        {
            "reference_id": f"memory:{memory.id}",
            "entity": "memory",
            "entity_id": str(memory.id),
            "label": "Connector DVT lesson",
            "href": f"/knowledge?project={project_id}&memory={memory.id}",
            "excerpt": (
                "Validate connector pin mapping before the DVT build. · tags=DVT, connector"
            ),
        }
    ]
    invocation_context = gateway.invocations[-1].context
    assert "Connector DVT lesson" in str(invocation_context)
    assert "embedding" not in str(invocation_context).lower()


def test_risk_suggestion_creates_only_pending_finding_and_is_idempotent(
    api_context: tuple[TestClient, FakeObjectStore, FakeGateway],
    isolated_ai_api_database: str,
) -> None:
    client, _, gateway = api_context
    tenant_id, _, headers = setup_owner(client)
    project_id, event_row_id = seed_project_and_users(
        isolated_ai_api_database,
        tenant_id=tenant_id,
    )
    gateway.risk_output = AgentAssessment(
        disposition="human_review_candidate",
        candidate_type="risk_suggestion",
        summary="Connector timing evidence warrants review.",
        proposed_payload=RiskSuggestionPayload(
            title="Connector delivery risk",
            description="The connector timing is uncertain.",
            likelihood=3,
            impact=4,
        ),
        evidence_event_ids=(event_row_id,),
        confidence=0.82,
    )
    request = {
        "project_id": str(project_id),
        "request_id": "risk-request-1",
        "concern": "Assess connector timing.",
        "evidence_event_ids": [event_row_id],
    }

    created = client.post("/api/ai/create-risk-suggestion", headers=headers, json=request)
    replay = client.post("/api/ai/create-risk-suggestion", headers=headers, json=request)

    assert created.status_code == replay.status_code == 200
    assert created.json() == replay.json()
    assert created.json()["status"] == "created"
    brief = client.get("/api/ai/brief", headers=headers)
    assert brief.status_code == 200
    assert brief.headers["cache-control"] == "no-store"
    assert brief.json()["status"] == "unavailable"
    assert brief.json()["error_code"] == "MODEL_UNAVAILABLE"
    assert brief.json()["pending_review_count"] == 1
    assert brief.json()["reviewed_count"] == 0
    assert brief.json()["accepted_count"] == 0
    assert brief.json()["applied_count"] == 0
    assert brief.json()["acceptance_rate_basis_points"] is None
    assert brief.json()["narrowed_output_count"] == 0
    assert brief.json()["items"][0]["finding_id"] == created.json()["finding_id"]
    assert brief.json()["items"][0]["evidence"][0]["href"] == (
        f"/projects?project={project_id}&tab=timeline&event_id={event_row_id}"
    )
    engine = create_engine(psycopg_database_url(isolated_ai_api_database))
    try:
        with engine.connect() as connection:
            finding = connection.execute(select(tables.findings)).mappings().one()
            assert connection.execute(select(tables.risks)).all() == []
            run = connection.execute(select(tables.agent_runs)).mappings().one()
            assert run["status"] == "succeeded"
        assert finding["status"] == "pending_review"
        assert finding["finding_type"] == "risk_suggestion"
    finally:
        engine.dispose()


def test_ai_and_document_actions_are_denied_to_external_roles(
    api_context: tuple[TestClient, FakeObjectStore, FakeGateway],
    isolated_ai_api_database: str,
) -> None:
    client, _, _ = api_context
    tenant_id, _, _ = setup_owner(client)
    project_id, _ = seed_project_and_users(isolated_ai_api_database, tenant_id=tenant_id)
    supplier_headers = login(client, "supplier")

    chat = client.post(
        "/api/ai/chat",
        headers=supplier_headers,
        json={"project_id": str(project_id), "question": "status"},
    )
    upload = client.post(
        "/api/ai/analyze-document",
        headers=supplier_headers,
        data={"project_id": str(project_id)},
        files={"file": ("risks.xlsx", xlsx_bytes())},
    )
    assert chat.status_code == upload.status_code == 403
