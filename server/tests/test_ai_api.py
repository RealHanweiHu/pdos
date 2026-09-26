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
from sqlalchemy import create_engine, select

from app.ai.call_identity import ModelCallSlot, model_call_id
from app.ai.capability_contract import CapabilityKey
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
from app.domain.memories import MemoryDraft, MemoryService, memory_review_digest
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft
from app.main import app
from app.settings import get_settings
from app.storage.documents import DocumentObjectStore, get_document_object_store
from tests.db_cleanup import clear_test_tenants
from tests.provider_environment import clear_provider_environment

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
        if invocation.run_id is not None:
            assert invocation.model_call_id == model_call_id(
                invocation.run_id,
                ModelCallSlot.CHAT_ANSWER
                if invocation.agent_key == "ai_chat"
                else ModelCallSlot.RISK_SUGGESTION,
            )
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
    clear_provider_environment(monkeypatch)
    get_settings.cache_clear()
    get_engine.cache_clear()
    os.environ["DATABASE_URL"] = test_url
    command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")
    engine = create_engine(psycopg_database_url(test_url))
    try:
        with engine.begin() as connection:
            clear_test_tenants(connection)
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
                knowledge_kind="design_rule",
            ),
        )
        MemoryService(engine).verify(
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=verifier_id,
            memory_id=memory.id,
            expected_review_digest=memory_review_digest(memory),
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
        f"/projects?project={project_id}&tab=overview&event_id={event_row_id}"
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


def test_capabilities_endpoint_reports_contract_and_quality_controls(
    api_context: tuple[TestClient, FakeObjectStore, FakeGateway],
    isolated_ai_api_database: str,
) -> None:
    client, _, _ = api_context
    _, _, headers = setup_owner(client)

    response = client.get("/api/ai/capabilities", headers=headers)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    items = response.json()["items"]
    keys = [item["capability_key"] for item in items]
    assert len(keys) == len(set(keys))
    assert set(keys) == {key.value for key in CapabilityKey}
    # Keep the original capabilities and their relative presentation order while
    # requiring all registered additions to be visible in the governance API.
    legacy_keys = [
        "project_intelligence.risk_suggestion",
        "project_intelligence.blocker_alert",
        "project_intelligence.gate_readiness_anomaly",
        "project_intelligence.risk_suggestion_api",
        "knowledge_lite.knowledge_draft",
        "engineering_intelligence.bom_impact_suggestion",
        "engineering_intelligence.change_impact_suggestion",
        "quality_intelligence.quality_cluster_alert",
        "quality_intelligence.capa_suggestion",
        "quality_intelligence.test_plan_change",
        "quality_intelligence.test_report_import",
        "supplier_intelligence.supplier_delay_risk",
        "executive_intelligence.executive_portfolio_brief",
    ]
    assert [key for key in keys if key in legacy_keys] == legacy_keys
    by_key = {item["capability_key"]: item for item in items}
    hard_gate = by_key["project_intelligence.risk_suggestion"]
    assert hard_gate["zone"] == "hard_gate"
    assert hard_gate["rollout"] == "live"
    assert hard_gate["prompt_version"] == "project-intelligence-v2"
    assert hard_gate["finding_types"] == ["risk_suggestion"]
    assert hard_gate["quality_control"] == "finding_quality_control"
    test_plan = by_key["quality_intelligence.test_plan_change"]
    assert test_plan["zone"] == "hard_gate"
    assert test_plan["finding_types"] == ["test_plan_change"]
    assert test_plan["prompt_version"] == "test-plan-change-v5"
    assert test_plan["tools"] == []  # Explicit API request, no event-worker tool access.
    confirm = by_key["quality_intelligence.test_report_import"]
    assert confirm["zone"] == "confirm"
    assert confirm["finding_types"] == []
    shadow = by_key["supplier_intelligence.supplier_delay_risk"]
    assert shadow["rollout"] == "shadow"

    assert client.get("/api/ai/capabilities").status_code == 401


def test_touchpoints_report_explicit_disabled_states_with_manual_paths(
    api_context: tuple[TestClient, FakeObjectStore, FakeGateway],
    isolated_ai_api_database: str,
) -> None:
    client, _, _ = api_context
    _, _, headers = setup_owner(client)

    response = client.get("/api/ai/touchpoints", headers=headers)
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["key"] for item in items] == [
        "ai_brief",
        "ai_chat",
        "document_analyze",
        "risk_suggestion_api",
        "test_report_import",
        "agent_runs",
    ]
    for item in items:
        assert item["manual_alternative"].strip()
        if item["reason_code"] is None:
            assert item["state"] == "enabled"
        elif item["key"] == "test_report_import":
            assert item["state"] == "degraded"
        else:
            assert item["state"] == "disabled"

    assert client.get("/api/ai/touchpoints").status_code == 401


def test_usage_endpoint_reports_budget_and_capability_rows(
    api_context: tuple[TestClient, FakeObjectStore, FakeGateway],
    isolated_ai_api_database: str,
) -> None:
    client, _, _ = api_context
    _, _, headers = setup_owner(client)

    response = client.get("/api/ai/usage", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["rows"] == []
    assert body["budget_exhausted"] in {True, False}
    assert set(body) == {
        "daily_token_budget",
        "used_tokens_today",
        "remaining_tokens_today",
        "budget_exhausted",
        "rows",
    }


@pytest.mark.parametrize("stop_during_model", [False, True])
def test_risk_request_rechecks_rollout_and_records_midcall_stop(
    api_context: tuple[TestClient, FakeObjectStore, FakeGateway],
    isolated_ai_api_database: str,
    monkeypatch: pytest.MonkeyPatch,
    stop_during_model: bool,
) -> None:
    from app.ai.capability_contract import CapabilityRollout
    from app.ai.runtime_contract import AgentKey
    from tests.rollout_support import set_agent_rollout

    client, _, gateway = api_context
    tenant_id, _, headers = setup_owner(client)
    project_id, event_id = seed_project_and_users(isolated_ai_api_database, tenant_id=tenant_id)
    original = gateway.invoke_structured

    def invoke_then_disable[OutputT: BaseModel](
        invocation: GatewayInvocation, output_type: type[OutputT]
    ) -> GatewayResult[OutputT]:
        result = original(invocation, output_type)
        set_agent_rollout(monkeypatch, AgentKey.PROJECT_INTELLIGENCE, CapabilityRollout.DISABLED)
        return result

    if stop_during_model:
        monkeypatch.setattr(gateway, "invoke_structured", invoke_then_disable)
    else:
        set_agent_rollout(monkeypatch, AgentKey.PROJECT_INTELLIGENCE, CapabilityRollout.DISABLED)
    response = client.post(
        "/api/ai/create-risk-suggestion",
        headers=headers,
        json={
            "project_id": str(project_id),
            "request_id": "rollout-stop",
            "concern": "Check the issue",
            "evidence_event_ids": [event_id],
        },
    )
    if stop_during_model:
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "unavailable"
        assert response.json()["error_code"] == "CAPABILITY_DISABLED"
        with get_engine().connect() as connection:
            run = connection.execute(select(tables.agent_runs)).mappings().one()
            assert run["status"] == "degraded"
            assert connection.execute(select(tables.findings.c.id)).first() is None
    else:
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "CAPABILITY_DISABLED"
    assert len(gateway.invocations) == int(stop_during_model)


@pytest.mark.parametrize(
    "variant", ["same_request", "other_actor", "changed_content", "legacy_unbound"]
)
def test_risk_request_replay_preserves_origin_and_does_not_call_again(
    api_context: tuple[TestClient, FakeObjectStore, FakeGateway],
    isolated_ai_api_database: str,
    variant: str,
) -> None:
    client, _, gateway = api_context
    tenant, owner, headers = setup_owner(client)
    project, event = seed_project_and_users(isolated_ai_api_database, tenant_id=tenant)
    body = dict(
        project_id=str(project),
        request_id="bound-risk-request",
        concern="Assess evidence.",
        evidence_event_ids=[event],
    )
    first = client.post("/api/ai/create-risk-suggestion", headers=headers, json=body)
    assert first.status_code == 200, first.text
    engine = create_engine(psycopg_database_url(isolated_ai_api_database))
    try:
        with engine.begin() as connection:
            run = connection.execute(select(tables.agent_runs)).mappings().one()
            assert run["run_context"]["api_actor_user_id"] == str(owner)
            if variant == "other_actor":
                manager = connection.execute(
                    select(tables.users.c.id).where(
                        tables.users.c.tenant_id == tenant, tables.users.c.username == "manager"
                    )
                ).scalar_one()
                connection.execute(
                    tables.project_members.insert(),
                    dict(
                        id=uuid4(),
                        tenant_id=tenant,
                        project_id=project,
                        user_id=manager,
                        added_by_user_id=owner,
                    ),
                )
            if variant == "legacy_unbound":
                old = dict(run["run_context"])
                old.pop("api_actor_user_id")
                connection.execute(
                    tables.agent_runs.update()
                    .where(tables.agent_runs.c.id == run["id"])
                    .values(run_context=old)
                )
        if variant == "other_actor":
            headers = login(client, "manager")
        if variant == "changed_content":
            body["concern"] = "Another request."
        replay = client.post("/api/ai/create-risk-suggestion", headers=headers, json=body)
        if variant == "same_request":
            assert replay.status_code == 200 and replay.json() == first.json()
        else:
            assert replay.status_code == 409, replay.text
            assert replay.json()["detail"]["code"] == "RISK_REQUEST_CONFLICT"
        assert len(gateway.invocations) == 1
        with engine.connect() as connection:
            assert len(connection.execute(select(tables.agent_runs)).all()) == 1
    finally:
        engine.dispose()


def test_concurrent_risk_request_creates_one_run_and_one_model_call(
    api_context: tuple[TestClient, FakeObjectStore, FakeGateway],
    isolated_ai_api_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    client, _, gateway = api_context
    tenant, _, headers = setup_owner(client)
    project, event = seed_project_and_users(isolated_ai_api_database, tenant_id=tenant)
    body = dict(
        project_id=str(project),
        request_id="in-flight-risk",
        concern="Assess evidence.",
        evidence_event_ids=[event],
    )
    entered, release = Event(), Event()
    original = gateway.invoke_structured

    def held[OutputT: BaseModel](
        invocation: GatewayInvocation, output_type: type[OutputT]
    ) -> GatewayResult[OutputT]:
        entered.set()
        assert release.wait(10), "test did not release provider"
        return original(invocation, output_type)

    monkeypatch.setattr(gateway, "invoke_structured", held)
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(
            client.post, "/api/ai/create-risk-suggestion", headers=headers, json=body
        )
        try:
            assert entered.wait(5), "first request did not reach model"
            second = client.post("/api/ai/create-risk-suggestion", headers=headers, json=body)
            assert second.status_code == 409, second.text
        finally:
            release.set()
        result = first.result(timeout=5)
    assert result.status_code == 200, result.text
    replay = client.post("/api/ai/create-risk-suggestion", headers=headers, json=body)
    assert replay.json() == result.json()
    assert len(gateway.invocations) == 1
