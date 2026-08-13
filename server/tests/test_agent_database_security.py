from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app.ai.embeddings import EmbeddingResult
from app.ai.executor import AgentExecutor, GatewayAgentModelInvoker
from app.ai.finding_writer import RestrictedAgentFindingWriter
from app.ai.gateway import ProviderRateCard, StructuredModelGateway
from app.ai.model_catalog import GoldenQualification, ModelCatalog, ProtocolKind, ProviderName
from app.ai.provider_adapters import ChatMessage, ProviderResponse
from app.ai.run_store import RestrictedAgentRunStore
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.domain.model_governance import ModelGovernanceService
from app.worker.dispatcher import AgentDispatcher

SERVER_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SERVER_ROOT.parent
SECURITY_TEMPLATE = REPOSITORY_ROOT / "infra/postgres/security/agent-runtime.sql"
SECURITY_ROLES = REPOSITORY_ROOT / "infra/postgres/security/agent-runtime-roles.sql"
SECURITY_REVERT = REPOSITORY_ROOT / "infra/postgres/security/agent-runtime-revert.sql"


def execute_sql_file(connection: Connection, path: Path) -> None:
    driver_connection = cast(Any, connection.connection.driver_connection)
    with driver_connection.cursor() as cursor:
        cursor.execute(path.read_text())


def role_engine(database_url: str, role: str) -> Engine:
    role_url = make_url(database_url).set(
        username=role,
        password=f"{role}_test_only",
    )
    return create_engine(psycopg_database_url(role_url.render_as_string(hide_password=False)))


class FakeAgentAdapter:
    def __init__(self, event_id: int, *, candidate_type: str, payload: dict[str, object]) -> None:
        self.event_id = event_id
        self.candidate_type = candidate_type
        self.payload = payload
        self.calls: list[tuple[object, Sequence[ChatMessage]]] = []

    def complete(self, route: object, messages: Sequence[ChatMessage]) -> ProviderResponse:
        self.calls.append((route, messages))
        return ProviderResponse(
            content=json.dumps(
                {
                    "disposition": "human_review_candidate",
                    "candidate_type": self.candidate_type,
                    "summary": "Review the scoped Agent candidate.",
                    "proposed_payload": self.payload,
                    "evidence_event_ids": [self.event_id],
                    "confidence": 0.9,
                }
            ),
            input_tokens=20,
            output_tokens=10,
            request_id="restricted-runtime-test",
            model_version="MiniMax-M2.7-test",
        )


class FakeEmbeddingGateway:
    provider = "test"
    model = "memory-v1"
    dimensions = 3

    def embed(self, text_value: str) -> EmbeddingResult:
        assert text_value.strip()
        return EmbeddingResult(provider=self.provider, model=self.model, values=(1.0, 0.0, 0.0))


@pytest.fixture
def secured_agent_database_url() -> Iterator[str]:
    test_url = configured_test_database_url()
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")
    engine = create_engine(psycopg_database_url(test_url))
    try:
        with engine.begin() as connection:
            execute_sql_file(connection, SECURITY_REVERT)
            connection.execute(text("TRUNCATE TABLE cehub_core.tenants CASCADE"))
            execute_sql_file(connection, SECURITY_ROLES)
            execute_sql_file(connection, SECURITY_ROLES)
            connection.execute(text("ALTER ROLE pdos_worker PASSWORD 'pdos_worker_test_only'"))
            connection.execute(text("ALTER ROLE pdos_agent PASSWORD 'pdos_agent_test_only'"))
            execute_sql_file(connection, SECURITY_TEMPLATE)
            execute_sql_file(connection, SECURITY_TEMPLATE)
        yield test_url
    finally:
        with engine.begin() as connection:
            execute_sql_file(connection, SECURITY_REVERT)
            connection.execute(text("TRUNCATE TABLE cehub_core.tenants CASCADE"))
            connection.execute(text("ALTER ROLE pdos_worker PASSWORD NULL"))
            connection.execute(text("ALTER ROLE pdos_agent PASSWORD NULL"))
        engine.dispose()
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url


def seed_two_tenants(
    connection: Connection,
    *,
    agent_key: str = "project_intelligence",
    event_type: str = "ISSUE_CREATED",
) -> dict[str, UUID | int]:
    tenant_a = uuid4()
    tenant_b = uuid4()
    workflow_a = uuid4()
    workflow_b = uuid4()
    project_a = uuid4()
    project_b = uuid4()
    subscription_a = uuid4()
    run_a = uuid4()
    now = datetime.now(UTC)
    connection.execute(
        tables.tenants.insert(),
        [
            {"id": tenant_a, "slug": f"secure-{tenant_a}", "name": "Secure A"},
            {"id": tenant_b, "slug": f"secure-{tenant_b}", "name": "Secure B"},
        ],
    )
    connection.execute(
        tables.workflows.insert(),
        [
            {"id": workflow_a, "tenant_id": tenant_a, "code": "npd", "name": "NPD"},
            {"id": workflow_b, "tenant_id": tenant_b, "code": "npd", "name": "NPD"},
        ],
    )
    connection.execute(
        tables.projects.insert(),
        [
            {
                "id": project_a,
                "tenant_id": tenant_a,
                "workflow_id": workflow_a,
                "code": "PRJ-A",
                "name": "Project A",
                "status": "active",
            },
            {
                "id": project_b,
                "tenant_id": tenant_b,
                "workflow_id": workflow_b,
                "code": "PRJ-B",
                "name": "Project B",
                "status": "active",
            },
        ],
    )
    event_a = int(
        connection.execute(
            tables.events.insert()
            .values(
                tenant_id=tenant_a,
                project_id=project_a,
                event_id=f"issue:{uuid4()}",
                event_type=event_type,
                schema_version=1,
                source="security_test",
                entity="issue",
                entity_id=uuid4(),
                payload={"description": "must remain private"},
                timestamp=now - timedelta(minutes=16),
            )
            .returning(tables.events.c.id)
        ).scalar_one()
    )
    event_b = int(
        connection.execute(
            tables.events.insert()
            .values(
                tenant_id=tenant_b,
                project_id=project_b,
                event_id=f"issue:{uuid4()}",
                event_type=event_type,
                schema_version=1,
                source="security_test",
                entity="issue",
                entity_id=uuid4(),
                payload={"description": "other tenant private"},
                timestamp=now - timedelta(minutes=16),
            )
            .returning(tables.events.c.id)
        ).scalar_one()
    )
    connection.execute(
        tables.agent_subscriptions.insert(),
        {
            "id": subscription_a,
            "tenant_id": tenant_a,
            "agent_key": agent_key,
        },
    )
    connection.execute(
        tables.agent_runs.insert(),
        {
            "id": run_a,
            "tenant_id": tenant_a,
            "project_id": project_a,
            "subscription_id": subscription_a,
            "agent_key": agent_key,
            "status": "queued",
            "window_started_at": now - timedelta(minutes=30),
            "window_ended_at": now - timedelta(minutes=15),
            "first_event_row_id": event_a,
            "last_event_row_id": event_a,
            "event_count": 1,
            "event_row_ids": [event_a],
        },
    )
    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "project_a": project_a,
        "project_b": project_b,
        "run_a": run_a,
        "event_a": event_a,
        "event_b": event_b,
    }


def denied(connection: Connection, statement: str, parameters: Mapping[str, object]) -> None:
    with pytest.raises(DBAPIError), connection.begin_nested():
        connection.execute(text(statement), parameters)


def seed_verified_memory(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    suffix: str,
) -> UUID:
    creator_id = uuid4()
    verifier_id = uuid4()
    memory_id = uuid4()
    now = datetime.now(UTC)
    connection.execute(
        tables.users.insert(),
        [
            {
                "id": creator_id,
                "tenant_id": tenant_id,
                "username": f"memory-creator-{suffix}",
                "display_name": "Memory Creator",
                "role": "quality",
            },
            {
                "id": verifier_id,
                "tenant_id": tenant_id,
                "username": f"memory-verifier-{suffix}",
                "display_name": "Memory Verifier",
                "role": "quality",
            },
        ],
    )
    connection.execute(
        tables.memories.insert(),
        {
            "id": memory_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "created_by_user_id": creator_id,
            "verified_by_user_id": verifier_id,
            "title": f"Verified memory {suffix}",
            "content": "Scoped verified guidance.",
            "tags": [],
            "source_refs": [],
            "content_sha256": suffix[0].lower() * 64,
            "status": "verified",
            "verified_at": now,
            "created_at": now,
            "updated_at": now,
        },
    )
    connection.execute(
        tables.memory_embeddings.insert(),
        {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "project_id": project_id,
            "memory_id": memory_id,
            "created_by_user_id": verifier_id,
            "provider": "test",
            "model": "memory-v1",
            "dimensions": 3,
            "content_sha256": suffix[0].lower() * 64,
            "embedding": [1.0, 0.0, 0.0],
            "created_at": now,
        },
    )
    return memory_id


def seed_phase_two_evidence(
    connection: Connection,
    *,
    ids: dict[str, UUID | int],
    agent_key: str,
) -> tuple[str, str] | None:
    if agent_key not in {"engineering_intelligence", "quality_intelligence"}:
        return None
    actor_a = uuid4()
    actor_b = uuid4()
    connection.execute(
        tables.users.insert(),
        [
            {
                "id": actor_a,
                "tenant_id": ids["tenant_a"],
                "username": f"phase-two-a-{actor_a}",
                "display_name": "Phase Two A",
                "role": "quality" if agent_key == "quality_intelligence" else "engineer",
            },
            {
                "id": actor_b,
                "tenant_id": ids["tenant_b"],
                "username": f"phase-two-b-{actor_b}",
                "display_name": "Phase Two B",
                "role": "quality" if agent_key == "quality_intelligence" else "engineer",
            },
        ],
    )
    if agent_key == "engineering_intelligence":
        scoped = "Scoped Engineering A"
        excluded = "Other Engineering B"
        for suffix, actor_id, tenant_key, project_key, name in (
            ("A", actor_a, "tenant_a", "project_a", scoped),
            ("B", actor_b, "tenant_b", "project_b", excluded),
        ):
            connection.execute(
                tables.development_boms.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": ids[tenant_key],
                    "project_id": ids[project_key],
                    "created_by_user_id": actor_id,
                    "bom_type": "ebom",
                    "code": f"EBOM-{suffix}",
                    "name": name,
                },
            )
        return scoped, excluded

    scoped = "Scoped Complaint A"
    excluded = "Other Complaint B"
    now = datetime.now(UTC)
    for suffix, actor_id, tenant_key, project_key, title in (
        ("A", actor_a, "tenant_a", "project_a", scoped),
        ("B", actor_b, "tenant_b", "project_b", excluded),
    ):
        connection.execute(
            tables.complaints.insert(),
            {
                "id": uuid4(),
                "tenant_id": ids[tenant_key],
                "project_id": ids[project_key],
                "reported_by_user_id": actor_id,
                "owner_user_id": actor_id,
                "code": f"CMP-{suffix}",
                "title": title,
                "description": "Allowlisted quality summary",
                "source": "internal",
                "severity": "high",
                "occurred_at": now - timedelta(days=1),
                "reported_at": now,
                "customer_reference": f"PRIVATE-{suffix}",
                "document_refs": [f"private/{suffix}/quality.pdf"],
            },
        )
    return scoped, excluded


def seed_context_layers(
    connection: Connection,
    *,
    ids: dict[str, UUID | int],
    agent_key: str,
) -> tuple[str | None, str]:
    role = {
        "project_intelligence": "project_manager",
        "knowledge_lite": "engineer",
        "engineering_intelligence": "engineer",
        "quality_intelligence": "quality",
    }[agent_key]
    member_a = uuid4()
    member_b = uuid4()
    private_identity = f"Private Identity {member_a}"
    connection.execute(
        tables.users.insert(),
        [
            {
                "id": member_a,
                "tenant_id": ids["tenant_a"],
                "username": f"context-a-{member_a}",
                "email": f"private-{member_a}@example.invalid",
                "display_name": private_identity,
                "role": role,
            },
            {
                "id": member_b,
                "tenant_id": ids["tenant_b"],
                "username": f"context-b-{member_b}",
                "email": f"private-{member_b}@example.invalid",
                "display_name": f"Other Identity {member_b}",
                "role": role,
            },
        ],
    )
    connection.execute(
        tables.project_members.insert(),
        [
            {
                "id": uuid4(),
                "tenant_id": ids["tenant_a"],
                "project_id": ids["project_a"],
                "user_id": member_a,
                "added_by_user_id": member_a,
            },
            {
                "id": uuid4(),
                "tenant_id": ids["tenant_b"],
                "project_id": ids["project_b"],
                "user_id": member_b,
                "added_by_user_id": member_b,
            },
        ],
    )
    if agent_key != "knowledge_lite":
        return None, private_identity

    internal_document = uuid4()
    restricted_document = uuid4()
    internal_excerpt = "Scoped internal document A"
    connection.execute(
        tables.documents.insert(),
        [
            {
                "id": internal_document,
                "tenant_id": ids["tenant_a"],
                "project_id": ids["project_a"],
                "uploaded_by_user_id": member_a,
                "object_key": "private/A/internal.pdf",
                "filename": "Scoped A.pdf",
                "media_type": "application/pdf",
                "classification": "internal",
                "size_bytes": 100,
                "sha256": "a" * 64,
                "extraction_status": "extracted",
                "fragment_count": 1,
            },
            {
                "id": restricted_document,
                "tenant_id": ids["tenant_a"],
                "project_id": ids["project_a"],
                "uploaded_by_user_id": member_a,
                "object_key": "private/A/restricted.pdf",
                "filename": "Restricted A.pdf",
                "media_type": "application/pdf",
                "classification": "restricted",
                "size_bytes": 100,
                "sha256": "b" * 64,
                "extraction_status": "extracted",
                "fragment_count": 1,
            },
        ],
    )
    connection.execute(
        tables.document_fragments.insert(),
        [
            {
                "id": uuid4(),
                "tenant_id": ids["tenant_a"],
                "project_id": ids["project_a"],
                "document_id": internal_document,
                "ordinal": 1,
                "locator": "page:1",
                "text": internal_excerpt,
            },
            {
                "id": uuid4(),
                "tenant_id": ids["tenant_a"],
                "project_id": ids["project_a"],
                "document_id": restricted_document,
                "ordinal": 1,
                "locator": "page:1",
                "text": "Restricted document must not cross",
            },
        ],
    )
    connection.execute(
        tables.events.update()
        .where(tables.events.c.id == ids["event_a"])
        .values(entity="document", entity_id=internal_document)
    )
    return internal_excerpt, private_identity


def test_worker_permissions_allow_control_plane_and_deny_business_mutation(
    secured_agent_database_url: str,
) -> None:
    owner_engine = create_engine(psycopg_database_url(secured_agent_database_url))
    engine = role_engine(secured_agent_database_url, "pdos_worker")
    try:
        with owner_engine.begin() as connection:
            ids = seed_two_tenants(connection)
        dispatcher = AgentDispatcher(engine)
        dispatch = dispatcher.dispatch_tenant(tenant_id=UUID(str(ids["tenant_a"])))
        assert dispatch.scanned_event_count == 1
        with engine.begin() as connection:
            assert (
                connection.execute(text("SELECT count(*) FROM cehub_event.events")).scalar_one()
                == 2
            )
            connection.execute(
                text(
                    "INSERT INTO cehub_ai.agent_dispatcher_cursors "
                    "(id, tenant_id, consumer_key) VALUES (:id, :tenant_id, 'security-test')"
                ),
                {"id": uuid4(), "tenant_id": ids["tenant_a"]},
            )
            denied(
                connection,
                "UPDATE cehub_project.projects SET name = 'injected' WHERE id = :project_id",
                {"project_id": ids["project_a"]},
            )
            denied(
                connection,
                "DELETE FROM cehub_event.events WHERE id = :event_id",
                {"event_id": ids["event_a"]},
            )
    finally:
        engine.dispose()
        owner_engine.dispose()


def test_agent_lease_scopes_projections_and_allows_only_controlled_writes(
    secured_agent_database_url: str,
) -> None:
    owner_engine = create_engine(psycopg_database_url(secured_agent_database_url))
    engine = role_engine(secured_agent_database_url, "pdos_agent")
    try:
        with owner_engine.begin() as connection:
            ids = seed_two_tenants(connection)
            memory_a = seed_verified_memory(
                connection,
                tenant_id=UUID(str(ids["tenant_a"])),
                project_id=UUID(str(ids["project_a"])),
                suffix="a",
            )
            seed_verified_memory(
                connection,
                tenant_id=UUID(str(ids["tenant_b"])),
                project_id=UUID(str(ids["project_b"])),
                suffix="b",
            )
            connection.execute(
                tables.finding_quality_controls.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": ids["tenant_a"],
                    "agent_key": "project_intelligence",
                    "finding_type": "blocker_alert",
                    "status": "narrowed",
                    "minimum_review_count": 5,
                    "acceptance_threshold_basis_points": 5000,
                    "reviewed_count": 5,
                    "accepted_count": 1,
                    "applied_count": 0,
                    "last_evaluated_at": datetime.now(UTC),
                    "narrowed_at": datetime.now(UTC),
                    "narrowed_reason": "test quality threshold",
                },
            )
        with engine.begin() as connection:
            assert (
                connection.execute(
                    text("SELECT count(*) FROM cehub_ai.agent_project_projection")
                ).scalar_one()
                == 0
            )
            assert (
                connection.execute(
                    text("SELECT count(*) FROM cehub_ai.agent_memory_projection")
                ).scalar_one()
                == 0
            )
            claim = (
                connection.execute(
                    text("SELECT * FROM cehub_ai.claim_agent_run(:started_at)"),
                    {"started_at": datetime.now(UTC)},
                )
                .mappings()
                .one()
            )
            connection.execute(
                text("SELECT cehub_ai.bind_agent_scope(:run_id, :lease_token)"),
                {"run_id": claim["id"], "lease_token": claim["lease_token"]},
            )
            projects = list(
                connection.execute(
                    text("SELECT id, tenant_id FROM cehub_ai.agent_project_projection")
                ).mappings()
            )
            assert projects == [{"id": ids["project_a"], "tenant_id": ids["tenant_a"]}]
            events = list(
                connection.execute(
                    text("SELECT id, tenant_id FROM cehub_ai.agent_event_projection")
                ).mappings()
            )
            assert events == [{"id": ids["event_a"], "tenant_id": ids["tenant_a"]}]
            memories = list(
                connection.execute(
                    text("SELECT memory_id, tenant_id FROM cehub_ai.agent_memory_projection")
                ).mappings()
            )
            assert memories == [{"memory_id": memory_a, "tenant_id": ids["tenant_a"]}]
            assert (
                connection.execute(
                    text("SELECT count(*) FROM cehub_ai.agent_document_fragment_projection")
                ).scalar_one()
                == 0
            )
            assert (
                connection.execute(
                    text("SELECT count(*) FROM cehub_ai.agent_user_role_projection")
                ).scalar_one()
                == 0
            )

            connection.execute(
                text("SELECT set_config('pdos.tenant_id', CAST(:tenant_b AS text), true)"),
                ids,
            )
            assert (
                connection.execute(
                    text("SELECT count(*) FROM cehub_ai.agent_project_projection")
                ).scalar_one()
                == 0
            )
            connection.execute(
                text("SELECT cehub_ai.bind_agent_scope(:run_id, :lease_token)"),
                {"run_id": claim["id"], "lease_token": claim["lease_token"]},
            )

            denied(
                connection,
                "SELECT * FROM cehub_project.projects",
                {},
            )
            denied(connection, "SELECT * FROM cehub_core.users", {})
            denied(connection, "SELECT * FROM cehub_project.project_members", {})
            denied(connection, "SELECT * FROM cehub_memory.memories", {})
            denied(
                connection,
                "INSERT INTO cehub_memory.memories "
                "(id, tenant_id, project_id, created_by_user_id, title, content, "
                "content_sha256, status) VALUES "
                "(:id, :tenant_id, :project_id, :actor_id, 'Injected', 'Injected', "
                ":content_sha256, 'draft')",
                {
                    "id": uuid4(),
                    "tenant_id": ids["tenant_a"],
                    "project_id": ids["project_a"],
                    "actor_id": uuid4(),
                    "content_sha256": "c" * 64,
                },
            )
            denied(
                connection,
                "INSERT INTO cehub_memory.memory_embeddings "
                "(id, tenant_id, project_id, memory_id, created_by_user_id, provider, "
                "model, dimensions, content_sha256, embedding) VALUES "
                "(:id, :tenant_id, :project_id, :memory_id, :actor_id, 'test', "
                "'memory-v1', 3, :content_sha256, '[1,0,0]'::vector)",
                {
                    "id": uuid4(),
                    "tenant_id": ids["tenant_a"],
                    "project_id": ids["project_a"],
                    "memory_id": memory_a,
                    "actor_id": uuid4(),
                    "content_sha256": "c" * 64,
                },
            )
            denied(
                connection,
                "UPDATE cehub_ai.agent_runs SET status = 'succeeded' WHERE id = :run_id",
                {"run_id": ids["run_a"]},
            )
            denied(
                connection,
                "INSERT INTO cehub_project.risks "
                "(id, tenant_id, project_id, title) "
                "VALUES (:id, :tenant_id, :project_id, 'injected')",
                {"id": uuid4(), "tenant_id": ids["tenant_a"], "project_id": ids["project_a"]},
            )
            denied(
                connection,
                "INSERT INTO cehub_project.gate_signoff_rounds "
                "(id, tenant_id, project_id, gate_id, round_number, policy_version, "
                "requirements, opened_by_user_id) VALUES "
                "(:id, :tenant_id, :project_id, :gate_id, 1, 'injected', "
                "'{}'::jsonb, :actor_id)",
                {
                    "id": uuid4(),
                    "tenant_id": ids["tenant_a"],
                    "project_id": ids["project_a"],
                    "gate_id": uuid4(),
                    "actor_id": uuid4(),
                },
            )
            denied(
                connection,
                "INSERT INTO cehub_project.gate_grandfather_exemptions "
                "(id, tenant_id, project_id, gate_id, requirement_key, policy_version, "
                "reason, approved_by_user_id) VALUES "
                "(:id, :tenant_id, :project_id, :gate_id, 'injected', 'v2', "
                "'injected', :actor_id)",
                {
                    "id": uuid4(),
                    "tenant_id": ids["tenant_a"],
                    "project_id": ids["project_a"],
                    "gate_id": uuid4(),
                    "actor_id": uuid4(),
                },
            )
            denied(
                connection,
                "INSERT INTO cehub_product.build_batches "
                "(id, tenant_id, project_id, workflow_id, stage_id, "
                "created_by_user_id, phase, code, planned_quantity) VALUES "
                "(:id, :tenant_id, :project_id, :workflow_id, :stage_id, "
                ":actor_id, 'evt', 'injected', 1)",
                {
                    "id": uuid4(),
                    "tenant_id": ids["tenant_a"],
                    "project_id": ids["project_a"],
                    "workflow_id": uuid4(),
                    "stage_id": uuid4(),
                    "actor_id": uuid4(),
                },
            )
            denied(
                connection,
                "INSERT INTO cehub_product.engineering_change_requests "
                "(id, tenant_id, project_id, requested_by_user_id, code, title, reason) "
                "VALUES (:id, :tenant_id, :project_id, :actor_id, 'ECR-X', 'injected', 'injected')",
                {
                    "id": uuid4(),
                    "tenant_id": ids["tenant_a"],
                    "project_id": ids["project_a"],
                    "actor_id": uuid4(),
                },
            )
            denied(
                connection,
                "INSERT INTO cehub_project.project_check_items "
                "(id, tenant_id, project_id, workflow_id, stage_id, template_id, "
                "created_by_user_id, binding_key, phase_id, phase_code, phase_name, "
                "task_id, task_name, deliverable_name, requirement, is_gate) VALUES "
                "(:id, :tenant_id, :project_id, :workflow_id, :stage_id, :template_id, "
                ":actor_id, 'injected', 'evt', 'P4', 'EVT', 'x', 'x', 'x', 'x', true)",
                {
                    "id": uuid4(),
                    "tenant_id": ids["tenant_a"],
                    "project_id": ids["project_a"],
                    "workflow_id": uuid4(),
                    "stage_id": uuid4(),
                    "template_id": uuid4(),
                    "actor_id": uuid4(),
                },
            )
            quality_write_parameters = {
                "id": uuid4(),
                "tenant_id": ids["tenant_a"],
                "project_id": ids["project_a"],
                "actor_id": uuid4(),
                "parent_id": uuid4(),
            }
            denied(
                connection,
                "INSERT INTO cehub_quality.complaints "
                "(id, tenant_id, project_id, reported_by_user_id, owner_user_id, "
                "code, title, description, source, severity, occurred_at, reported_at) "
                "VALUES (:id, :tenant_id, :project_id, :actor_id, :actor_id, "
                "'CMP-X', 'injected', 'injected', 'internal', 'low', now(), now())",
                quality_write_parameters,
            )
            denied(
                connection,
                "INSERT INTO cehub_quality.nonconformance_reports "
                "(id, tenant_id, project_id, complaint_id, owner_user_id, "
                "created_by_user_id, code, nonconformity, requirement_reference, "
                "severity, target_date) VALUES (:id, :tenant_id, :project_id, "
                ":parent_id, :actor_id, :actor_id, 'NCR-X', 'injected', "
                "'injected', 'low', current_date)",
                quality_write_parameters,
            )
            denied(
                connection,
                "INSERT INTO cehub_quality.root_cause_analyses "
                "(id, tenant_id, project_id, ncr_id, analyst_user_id, version, "
                "method, analysis, root_cause) VALUES (:id, :tenant_id, "
                ":project_id, :parent_id, :actor_id, 1, '5why', 'injected', 'injected')",
                quality_write_parameters,
            )
            denied(
                connection,
                "INSERT INTO cehub_quality.capa_actions "
                "(id, tenant_id, project_id, ncr_id, owner_user_id, "
                "created_by_user_id, action_type, description, due_date) "
                "VALUES (:id, :tenant_id, :project_id, :parent_id, :actor_id, "
                ":actor_id, 'corrective', 'injected', current_date)",
                quality_write_parameters,
            )
            denied(
                connection,
                "INSERT INTO cehub_quality.effectiveness_reviews "
                "(id, tenant_id, project_id, ncr_id, reviewer_user_id, "
                "review_number, criteria, observation_due_at, actual_result, "
                "result, evidence_refs, reviewed_at) VALUES (:id, :tenant_id, "
                ":project_id, :parent_id, :actor_id, 1, 'injected', now(), "
                "'injected', 'effective', '[1]'::jsonb, now())",
                quality_write_parameters,
            )
            denied(
                connection,
                "INSERT INTO cehub_ai.model_invocations "
                "(id, tenant_id, project_id, run_id, agent_key, prompt_version, provider, "
                "model, protocol, status, structured_attempts) VALUES "
                "(:id, :tenant_b, :project_b, :run_id, 'project_intelligence', 'v1', "
                "'minimax', 'MiniMax-M2.7', 'openai-compatible', 'succeeded', 1)",
                {
                    "id": uuid4(),
                    "tenant_b": ids["tenant_b"],
                    "project_b": ids["project_b"],
                    "run_id": ids["run_a"],
                },
            )
            invocation_id = uuid4()
            connection.execute(
                text(
                    "INSERT INTO cehub_ai.model_invocations "
                    "(id, tenant_id, project_id, run_id, agent_key, prompt_version, provider, "
                    "model, protocol, status, structured_attempts) VALUES "
                    "(:id, :tenant_a, :project_a, :run_id, 'project_intelligence', 'v1', "
                    "'minimax', 'MiniMax-M2.7', 'openai-compatible', 'succeeded', 1)"
                ),
                {
                    "id": invocation_id,
                    "tenant_a": ids["tenant_a"],
                    "project_a": ids["project_a"],
                    "run_id": ids["run_a"],
                },
            )
            denied(
                connection,
                "SELECT * FROM cehub_ai.findings",
                {},
            )
            denied(
                connection,
                "INSERT INTO cehub_ai.findings "
                "(id, tenant_id, project_id, run_id, model_invocation_id, agent_key, "
                "finding_type, origin_key, title, summary, proposed_payload, "
                "evidence_event_ids, confidence_basis_points, preflight_version) VALUES "
                "(:id, :tenant_id, :project_id, :run_id, :invocation_id, "
                "'project_intelligence', 'risk_suggestion', 'direct', 'Direct', 'Direct', "
                "'{}'::jsonb, CAST(:evidence AS jsonb), 8000, 'finding-preflight-v1')",
                {
                    "id": uuid4(),
                    "tenant_id": ids["tenant_a"],
                    "project_id": ids["project_a"],
                    "run_id": ids["run_a"],
                    "invocation_id": invocation_id,
                    "evidence": f"[{ids['event_a']}]",
                },
            )
            finding_parameters = {
                "finding_id": uuid4(),
                "run_id": claim["id"],
                "lease_token": claim["lease_token"],
                "invocation_id": invocation_id,
                "origin_key": "schedule-risk",
                "finding_type": "risk_suggestion",
                "title": "Review schedule risk",
                "summary": "Scoped evidence indicates a schedule risk.",
                "payload": ('{"title":"Schedule risk","likelihood":3,"impact":4}'),
                "confidence": 8500,
                "preflight_version": "finding-preflight-v1",
                "created_at": datetime.now(UTC),
            }
            create_finding_sql = text(
                "SELECT cehub_ai.create_agent_finding("
                ":finding_id, :run_id, :lease_token, :invocation_id, :origin_key, "
                ":finding_type, :title, :summary, CAST(:payload AS jsonb), "
                "CAST(:evidence AS jsonb), :confidence, :preflight_version, :created_at)"
            )
            denied(
                connection,
                str(create_finding_sql),
                {**finding_parameters, "evidence": f"[{ids['event_b']}]"},
            )
            denied(
                connection,
                str(create_finding_sql),
                {
                    **finding_parameters,
                    "finding_id": uuid4(),
                    "origin_key": "cross-agent-type",
                    "finding_type": "knowledge_draft",
                    "payload": '{"title":"Injected","draft_text":"Injected"}',
                    "evidence": f"[{ids['event_a']}]",
                },
            )
            denied(
                connection,
                str(create_finding_sql),
                {
                    **finding_parameters,
                    "finding_id": uuid4(),
                    "origin_key": "narrowed-blocker",
                    "finding_type": "blocker_alert",
                    "evidence": f"[{ids['event_a']}]",
                },
            )
            connection.execute(
                create_finding_sql,
                {**finding_parameters, "evidence": f"[{ids['event_a']}]"},
            )
            connection.execute(
                text(
                    "SELECT cehub_ai.complete_agent_run("
                    ":run_id, :lease_token, 'succeeded', NULL, :completed_at)"
                ),
                {
                    "run_id": claim["id"],
                    "lease_token": claim["lease_token"],
                    "completed_at": datetime.now(UTC),
                },
            )
        with owner_engine.connect() as connection:
            status = connection.execute(
                select(tables.agent_runs.c.status).where(tables.agent_runs.c.id == ids["run_a"])
            ).scalar_one()
            assert status == "succeeded"
            finding = (
                connection.execute(
                    select(tables.findings).where(
                        tables.findings.c.id == finding_parameters["finding_id"]
                    )
                )
                .mappings()
                .one()
            )
            actions = list(
                connection.execute(
                    select(tables.finding_actions.c.action).where(
                        tables.finding_actions.c.finding_id == finding["id"]
                    )
                ).scalars()
            )
            assert finding["status"] == "pending_review"
            assert actions == ["created"]
    finally:
        engine.dispose()
        owner_engine.dispose()


@pytest.mark.parametrize(
    (
        "agent_key",
        "event_type",
        "candidate_type",
        "payload",
        "prompt_version",
        "perspective_role",
    ),
    [
        (
            "project_intelligence",
            "ISSUE_CREATED",
            "risk_suggestion",
            {
                "title": "Review the scoped issue",
                "description": "The scoped issue may affect delivery",
                "likelihood": 3,
                "impact": 4,
            },
            "project-intelligence-v1",
            "project_manager",
        ),
        (
            "knowledge_lite",
            "DOCUMENT_UPLOADED",
            "knowledge_draft",
            {
                "title": "Review the scoped source",
                "draft_text": "Retain this lesson only as an unverified draft.",
                "applicability": "Projects with the same evidence pattern.",
            },
            "knowledge-lite-v1",
            "engineer",
        ),
        (
            "engineering_intelligence",
            "DEVELOPMENT_BOM_CREATED",
            "bom_impact_suggestion",
            {
                "title": "Review BOM impact",
                "description": "The scoped BOM may affect validation.",
                "likelihood": 3,
                "impact": 4,
            },
            "engineering-intelligence-v1",
            "engineer",
        ),
        (
            "quality_intelligence",
            "COMPLAINT_CREATED",
            "capa_suggestion",
            {
                "title": "Review CAPA response",
                "description": "The scoped complaint warrants Quality review.",
                "likelihood": 3,
                "impact": 5,
                "mitigation_plan": "Confirm containment and root cause.",
                "contingency_plan": "Review preventive controls.",
            },
            "quality-intelligence-v1",
            "quality",
        ),
    ],
)
def test_restricted_agent_executes_projection_gateway_and_trace_end_to_end(
    secured_agent_database_url: str,
    agent_key: str,
    event_type: str,
    candidate_type: str,
    payload: dict[str, object],
    prompt_version: str,
    perspective_role: str,
) -> None:
    owner_engine = create_engine(psycopg_database_url(secured_agent_database_url))
    agent_engine = role_engine(secured_agent_database_url, "pdos_agent")
    now = datetime.now(UTC)
    try:
        with owner_engine.begin() as connection:
            ids = seed_two_tenants(
                connection,
                agent_key=agent_key,
                event_type=event_type,
            )
            seed_verified_memory(
                connection,
                tenant_id=UUID(str(ids["tenant_a"])),
                project_id=UUID(str(ids["project_a"])),
                suffix="a",
            )
            seed_verified_memory(
                connection,
                tenant_id=UUID(str(ids["tenant_b"])),
                project_id=UUID(str(ids["project_b"])),
                suffix="b",
            )
            phase_two_evidence = seed_phase_two_evidence(
                connection,
                ids=ids,
                agent_key=agent_key,
            )
            scoped_document, private_identity = seed_context_layers(
                connection,
                ids=ids,
                agent_key=agent_key,
            )
        run_store = RestrictedAgentRunStore(agent_engine)
        catalog = ModelCatalog.from_environment(
            {
                "PDOS_LLM_PROVIDER": "minimax",
                "PDOS_LLM_BASE_URL": "https://model.invalid/v1",
                "PDOS_LLM_API_KEY": "test-only-key",
                "PDOS_LLM_MODEL": "MiniMax-M2.7",
            }
        )
        qualifications = [
            GoldenQualification(
                provider=ProviderName.MINIMAX,
                model="MiniMax-M2.7",
                suite_version="security-test-v1",
                suite_digest="sha256:security-test",
                status="passed",
            )
        ]
        governance = ModelGovernanceService(
            agent_engine,
            catalog=catalog,
            qualifications=qualifications,
            default_daily_token_budget=2_000_000,
            run_store=run_store,
        )
        adapter = FakeAgentAdapter(
            int(ids["event_a"]),
            candidate_type=candidate_type,
            payload=payload,
        )
        gateway = StructuredModelGateway(
            agent_engine,
            catalog=catalog,
            qualifications=qualifications,
            governance=governance,
            adapters={ProtocolKind.OPENAI_COMPATIBLE: adapter},
            rate_cards={ProviderName.MINIMAX: ProviderRateCard(0, 0)},
            run_store=run_store,
        )

        result = AgentExecutor(
            agent_engine,
            model_invoker=GatewayAgentModelInvoker(gateway),
            run_store=run_store,
            finding_writer=RestrictedAgentFindingWriter(
                agent_engine,
                run_store=run_store,
            ),
            embedding_gateway=FakeEmbeddingGateway(),
        ).execute_next(now=now)

        assert result.status == "succeeded"
        assert result.run_id == ids["run_a"]
        assert len(adapter.calls) == 1
        assert result.finding_id is not None
        serialized_messages = " ".join(
            message.content for _, messages in adapter.calls for message in messages
        )
        assert "must remain private" not in serialized_messages
        assert "Verified memory a" in serialized_messages
        assert "Verified memory b" not in serialized_messages
        assert str(ids["tenant_b"]) not in serialized_messages
        if phase_two_evidence is not None:
            scoped_evidence, excluded_evidence = phase_two_evidence
            assert scoped_evidence in serialized_messages
            assert excluded_evidence not in serialized_messages
        assert "PRIVATE-A" not in serialized_messages
        assert "private/A/quality.pdf" not in serialized_messages
        assert private_identity not in serialized_messages
        assert "example.invalid" not in serialized_messages
        if scoped_document is not None:
            assert scoped_document in serialized_messages
            assert "Restricted document must not cross" not in serialized_messages
            assert "private/A/internal.pdf" not in serialized_messages
        with owner_engine.connect() as connection:
            run = (
                connection.execute(
                    select(tables.agent_runs).where(tables.agent_runs.c.id == ids["run_a"])
                )
                .mappings()
                .one()
            )
            invocation = (
                connection.execute(
                    select(tables.model_invocations).where(
                        tables.model_invocations.c.run_id == ids["run_a"]
                    )
                )
                .mappings()
                .one()
            )
            finding = (
                connection.execute(
                    select(tables.findings).where(tables.findings.c.id == result.finding_id)
                )
                .mappings()
                .one()
            )
        assert run["status"] == "succeeded"
        assert run["context_version"] == "run-context-v2"
        assert run["run_context"]["schema_version"] == 2
        assert run["run_context"]["user"]["perspective_role"] == perspective_role
        assert run["run_context"]["user"]["decision_mode"] == "advisory_only"
        assert run["run_context"]["tenant_id"] == str(ids["tenant_a"])
        assert invocation["tenant_id"] == ids["tenant_a"]
        assert invocation["status"] == "succeeded"
        assert invocation["prompt_version"] == prompt_version
        assert finding["status"] == "pending_review"
        assert finding["agent_key"] == agent_key
        assert finding["finding_type"] == candidate_type
        assert finding["model_invocation_id"] == invocation["id"]
    finally:
        agent_engine.dispose()
        owner_engine.dispose()
