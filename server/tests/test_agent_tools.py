from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, create_engine

from app.ai.embeddings import EmbeddingResult
from app.ai.runtime_contract import (
    AgentKey,
    EventReference,
    FrozenRunContext,
    empty_multimodal_context,
    user_context_for_agent,
)
from app.ai.tools import (
    TOOL_DEFINITIONS,
    AgentReadTools,
    ToolScopeViolationError,
    tool_definitions_for_agent,
)
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.domain.memories import MemoryDraft, MemoryService, memory_review_digest
from tests.db_cleanup import clear_test_tenants

SERVER_ROOT = Path(__file__).resolve().parents[1]


class StaticEmbeddingGateway:
    provider = "test"
    model = "memory-v1"
    dimensions = 3

    def embed(self, text_value: str) -> EmbeddingResult:
        assert text_value.strip()
        return EmbeddingResult(provider=self.provider, model=self.model, values=(1.0, 0.0, 0.0))


@pytest.fixture
def agent_tools_database_url() -> Iterator[str]:
    test_url = configured_test_database_url()
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")
    engine = create_engine(psycopg_database_url(test_url))
    try:
        with engine.begin() as connection:
            clear_test_tenants(connection)
        yield test_url
    finally:
        engine.dispose()
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url


def seed_project(connection: Connection, *, slug: str) -> tuple[UUID, UUID]:
    tenant_id = uuid4()
    workflow_id = uuid4()
    project_id = uuid4()
    connection.execute(
        tables.tenants.insert(),
        {"id": tenant_id, "slug": slug, "name": slug.title()},
    )
    connection.execute(
        tables.workflows.insert(),
        {"id": workflow_id, "tenant_id": tenant_id, "code": "npd", "name": "NPD"},
    )
    connection.execute(
        tables.projects.insert(),
        {
            "id": project_id,
            "tenant_id": tenant_id,
            "workflow_id": workflow_id,
            "code": f"PRJ-{slug.upper()}",
            "name": slug.title(),
            "status": "active",
        },
    )
    return tenant_id, project_id


def frozen_context(
    *,
    tenant_id: UUID,
    project_id: UUID,
    agent_key: AgentKey = AgentKey.PROJECT_INTELLIGENCE,
    event_type: str = "ISSUE_CREATED",
) -> FrozenRunContext:
    occurred_at = datetime(2026, 8, 11, 20, 1, tzinfo=UTC)
    return FrozenRunContext(
        tenant_id=tenant_id,
        project_id=project_id,
        run_id=uuid4(),
        agent_key=agent_key,
        built_at=occurred_at + timedelta(minutes=15),
        window_started_at=occurred_at - timedelta(minutes=1),
        window_ended_at=occurred_at + timedelta(minutes=14),
        trigger_events=(
            EventReference(
                id=1,
                event_type=event_type,
                entity="issue",
                entity_id=uuid4(),
                timestamp=occurred_at,
            ),
        ),
        project={"id": str(project_id), "code": "PRJ-1", "status": "active"},
        execution={"open_issue_count": 2},
        multimodal=empty_multimodal_context(),
        user=user_context_for_agent(agent_key),
    )


def append_event(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    number: int,
) -> int:
    return int(
        connection.execute(
            tables.events.insert()
            .values(
                tenant_id=tenant_id,
                project_id=project_id,
                event_id=f"issue:{project_id}:{number}",
                event_type="ISSUE_CREATED",
                schema_version=1,
                source="tool_test",
                entity="issue",
                entity_id=uuid4(),
                payload={"private_description": "must not leave tool"},
                timestamp=datetime(2026, 8, 11, 20, number, tzinfo=UTC),
            )
            .returning(tables.events.c.id)
        ).scalar_one()
    )


def test_tool_definitions_freeze_use_do_not_use_negative_example_and_boundary() -> None:
    assert [definition.name for definition in TOOL_DEFINITIONS] == [
        "get_project_context",
        "search_memory",
        "get_recent_events",
        # V2-8 (D25): reach is available to every seat, not a per-agent extra.
        "web_search",
        "web_fetch",
        "source_snapshot",
    ]
    for definition in TOOL_DEFINITIONS:
        assert "Use when" in definition.description
        assert "Do not use" in definition.description
        assert "Negative example" in definition.description
        assert "Boundary" in definition.description
        assert definition.input_example

    assert [
        definition.name
        for definition in tool_definitions_for_agent(AgentKey.ENGINEERING_INTELLIGENCE)
    ] == [*([definition.name for definition in TOOL_DEFINITIONS]), "get_engineering_evidence"]
    assert [
        definition.name for definition in tool_definitions_for_agent(AgentKey.QUALITY_INTELLIGENCE)
    ] == [*([definition.name for definition in TOOL_DEFINITIONS]), "get_quality_evidence"]
    assert [
        definition.name for definition in tool_definitions_for_agent(AgentKey.SUPPLIER_INTELLIGENCE)
    ] == [*([definition.name for definition in TOOL_DEFINITIONS]), "get_supplier_delay_evidence"]
    assert [
        definition.name
        for definition in tool_definitions_for_agent(AgentKey.EXECUTIVE_INTELLIGENCE)
    ] == [*([definition.name for definition in TOOL_DEFINITIONS]), "get_portfolio_brief"]
    assert [
        definition.name for definition in tool_definitions_for_agent(AgentKey.PROJECT_INTELLIGENCE)
    ] == [*([definition.name for definition in TOOL_DEFINITIONS]), "get_issue_evidence"]


def test_tools_fail_close_on_claimed_scope_and_memory_is_explicitly_not_enabled(
    agent_tools_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(agent_tools_database_url))
    try:
        with engine.begin() as connection:
            tenant_id, project_id = seed_project(connection, slug="bound")
        tools = AgentReadTools(
            engine,
            run_context=frozen_context(tenant_id=tenant_id, project_id=project_id),
        )

        with pytest.raises(ToolScopeViolationError):
            tools.get_project_context(project_id=uuid4())
        with pytest.raises(ToolScopeViolationError):
            tools.get_recent_events(project_id=uuid4())
        with pytest.raises(ToolScopeViolationError):
            tools.search_memory(project_id=uuid4(), query="injected scope")

        project = tools.get_project_context(project_id=project_id)
        assert project.project["id"] == str(project_id)
        memory = tools.search_memory(project_id=project_id, query="gate readiness")
        assert memory.source_status == "not_enabled"
        assert memory.shown_count == memory.total_count == 0
        assert not memory.truncated
        assert "已显示 0 之 0 条" in memory.continuation
    finally:
        engine.dispose()


def test_memory_search_returns_only_verified_project_scoped_memory(
    agent_tools_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(agent_tools_database_url))
    gateway = StaticEmbeddingGateway()
    try:
        with engine.begin() as connection:
            tenant_id, project_id = seed_project(connection, slug="memory")
            other_tenant_id, other_project_id = seed_project(connection, slug="memory-other")
            creator_id = uuid4()
            verifier_id = uuid4()
            for user_id, username in (
                (creator_id, "memory-creator"),
                (verifier_id, "memory-verifier"),
            ):
                connection.execute(
                    tables.users.insert(),
                    {
                        "id": user_id,
                        "tenant_id": tenant_id,
                        "username": username,
                        "display_name": username,
                        "role": "quality",
                    },
                )
            other_creator_id = uuid4()
            other_verifier_id = uuid4()
            for user_id, username in (
                (other_creator_id, "other-creator"),
                (other_verifier_id, "other-verifier"),
            ):
                connection.execute(
                    tables.users.insert(),
                    {
                        "id": user_id,
                        "tenant_id": other_tenant_id,
                        "username": username,
                        "display_name": username,
                        "role": "quality",
                    },
                )
        service = MemoryService(engine)
        verified = service.create(
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=creator_id,
            draft=MemoryDraft(
                title="Gate readiness lesson",
                content="Validate connector pin mapping before DVT.",
                tags=("DVT",),
                knowledge_kind="design_rule",
            ),
        )
        service.verify(
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=verifier_id,
            memory_id=verified.id,
            expected_review_digest=memory_review_digest(verified),
            gateway=gateway,
        )
        service.create(
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=creator_id,
            draft=MemoryDraft(title="Draft secret", content="Must not be retrieved."),
        )
        other = service.create(
            tenant_id=other_tenant_id,
            project_id=other_project_id,
            actor_user_id=other_creator_id,
            draft=MemoryDraft(
                title="Other tenant", content="Must remain isolated.", knowledge_kind="design_rule"
            ),
        )
        service.verify(
            tenant_id=other_tenant_id,
            project_id=other_project_id,
            actor_user_id=other_verifier_id,
            memory_id=other.id,
            expected_review_digest=memory_review_digest(other),
            gateway=gateway,
        )
        tools = AgentReadTools(
            engine,
            run_context=frozen_context(tenant_id=tenant_id, project_id=project_id),
            embedding_gateway=gateway,
        )

        page = tools.search_memory(project_id=project_id, query="connector DVT", limit=10)

        assert page.source_status == "ready"
        assert page.shown_count == page.total_count == 1
        assert page.items[0]["memory_id"] == str(verified.id)
        assert page.items[0]["title"] == "Gate readiness lesson"
        assert "created_by_user_id" not in page.items[0]
        assert "embedding" not in page.items[0]
    finally:
        engine.dispose()


def test_recent_events_are_tenant_bound_payload_free_and_explicitly_paginated(
    agent_tools_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(agent_tools_database_url))
    try:
        with engine.begin() as connection:
            tenant_id, project_id = seed_project(connection, slug="page")
            other_tenant_id, other_project_id = seed_project(connection, slug="other")
            event_ids = [
                append_event(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    number=number,
                )
                for number in range(1, 4)
            ]
            append_event(
                connection,
                tenant_id=other_tenant_id,
                project_id=other_project_id,
                number=4,
            )
        tools = AgentReadTools(
            engine,
            run_context=frozen_context(tenant_id=tenant_id, project_id=project_id),
        )

        first = tools.get_recent_events(project_id=project_id, limit=2)
        assert [item["id"] for item in first.items] == event_ids[:2]
        assert first.shown_count == 2
        assert first.total_count == 3
        assert first.truncated
        assert first.next_after_id == event_ids[1]
        assert f"已显示 2 之 3 条；使用 after_id={event_ids[1]} 续读。" == first.continuation
        assert "payload" not in first.items[0]

        second = tools.get_recent_events(
            project_id=project_id,
            after_id=first.next_after_id or 0,
            limit=2,
        )
        assert [item["id"] for item in second.items] == event_ids[2:]
        assert second.shown_count == second.total_count == 1
        assert not second.truncated
        assert second.next_after_id is None
    finally:
        engine.dispose()


def test_document_fragments_are_tenant_bound_and_never_expose_object_keys(
    agent_tools_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(agent_tools_database_url))
    document_id = uuid4()
    try:
        with engine.begin() as connection:
            tenant_id, project_id = seed_project(connection, slug="document")
            user_id = uuid4()
            connection.execute(
                tables.users.insert(),
                {
                    "id": user_id,
                    "tenant_id": tenant_id,
                    "username": "uploader",
                    "display_name": "Uploader",
                    "role": "engineer",
                },
            )
            connection.execute(
                tables.documents.insert(),
                {
                    "id": document_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "uploaded_by_user_id": user_id,
                    "object_key": "private/source.xlsx",
                    "filename": "source.xlsx",
                    "media_type": (
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    ),
                    "classification": "internal",
                    "size_bytes": 10,
                    "sha256": "a" * 64,
                    "extraction_status": "extracted",
                    "fragment_count": 1,
                },
            )
            connection.execute(
                tables.document_fragments.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "document_id": document_id,
                    "ordinal": 1,
                    "locator": "sheet:Risk,rows:1-2",
                    "text": "Connector delay\tHigh",
                },
            )
        tools = AgentReadTools(
            engine,
            run_context=frozen_context(tenant_id=tenant_id, project_id=project_id),
        )

        page = tools.get_document_fragments(
            project_id=project_id,
            document_id=document_id,
        )

        assert page.shown_count == page.total_count == 1
        assert page.items[0]["locator"] == "sheet:Risk,rows:1-2"
        assert "object_key" not in page.items[0]
        assert "private/source.xlsx" not in str(page.items)
        with pytest.raises(ToolScopeViolationError):
            tools.get_document_fragments(project_id=uuid4(), document_id=document_id)

        with engine.begin() as connection:
            connection.execute(
                tables.documents.update()
                .where(tables.documents.c.id == document_id)
                .values(classification="confidential")
            )
        assert (
            tools.get_document_fragments(
                project_id=project_id,
                document_id=document_id,
            ).shown_count
            == 0
        )
    finally:
        engine.dispose()


def test_engineering_evidence_is_project_bound_allowlisted_and_paginated(
    agent_tools_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(agent_tools_database_url))
    try:
        with engine.begin() as connection:
            tenant_id, project_id = seed_project(connection, slug="engineering")
            other_tenant_id, other_project_id = seed_project(connection, slug="engineering-other")
            actor_id = uuid4()
            other_actor_id = uuid4()
            connection.execute(
                tables.users.insert(),
                [
                    {
                        "id": actor_id,
                        "tenant_id": tenant_id,
                        "username": "engineering-actor",
                        "display_name": "Engineering Actor",
                        "role": "engineer",
                    },
                    {
                        "id": other_actor_id,
                        "tenant_id": other_tenant_id,
                        "username": "other-engineering-actor",
                        "display_name": "Other Engineering Actor",
                        "role": "engineer",
                    },
                ],
            )
            bom_id = uuid4()
            connection.execute(
                tables.development_boms.insert(),
                {
                    "id": bom_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "created_by_user_id": actor_id,
                    "bom_type": "ebom",
                    "code": "EBOM-1",
                    "name": "Drive EBOM",
                    "notes": "Internal connector review",
                },
            )
            connection.execute(
                tables.development_bom_items.insert(),
                [
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "bom_id": bom_id,
                        "line_number": line_number,
                        "part_number": f"PART-{line_number}",
                        "description": "Connector",
                        "quantity": 1,
                        "unit": "ea",
                        "attributes": {"supplier_secret": "must-not-leave"},
                    }
                    for line_number in (10, 20)
                ],
            )
            ecr_id = uuid4()
            connection.execute(
                tables.engineering_change_requests.insert(),
                {
                    "id": ecr_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "requested_by_user_id": actor_id,
                    "code": "ECR-1",
                    "title": "Connector change",
                    "reason": "Improve retention",
                },
            )
            connection.execute(
                tables.ecr_affected_boms.insert(),
                {
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "ecr_id": ecr_id,
                    "bom_id": bom_id,
                },
            )
            connection.execute(
                tables.development_boms.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": other_tenant_id,
                    "project_id": other_project_id,
                    "created_by_user_id": other_actor_id,
                    "bom_type": "ebom",
                    "code": "OTHER-EBOM",
                    "name": "Other tenant BOM",
                },
            )
        tools = AgentReadTools(
            engine,
            run_context=frozen_context(
                tenant_id=tenant_id,
                project_id=project_id,
                agent_key=AgentKey.ENGINEERING_INTELLIGENCE,
                event_type="DEVELOPMENT_BOM_ITEM_ADDED",
            ),
        )

        first = tools.get_engineering_evidence(project_id=project_id, limit=2)
        second = tools.get_engineering_evidence(
            project_id=project_id,
            offset=first.next_after_id or 0,
            limit=2,
        )

        assert first.shown_count == 2 and first.total_count == 4 and first.truncated
        assert second.shown_count == 2 and second.total_count == 4 and not second.truncated
        evidence = (*first.items, *second.items)
        assert {item["entity"] for item in evidence} == {
            "development_bom",
            "development_bom_item",
            "engineering_change_request",
        }
        assert "item_count=2" in str(evidence)
        bom_items = [item for item in evidence if item["entity"] == "development_bom_item"]
        assert sorted(item["label"] for item in bom_items) == [
            "EBOM-1 · #10 · PART-10",
            "EBOM-1 · #20 · PART-20",
        ]
        assert all("description=Connector; quantity=1 ea" in item["excerpt"] for item in bom_items)
        assert "OTHER-EBOM" not in str(evidence)
        assert "supplier_secret" not in str(evidence)
        assert set(evidence[0]) == {
            "reference_id",
            "entity",
            "entity_id",
            "label",
            "excerpt",
        }
        with pytest.raises(ToolScopeViolationError):
            tools.get_engineering_evidence(project_id=uuid4())
    finally:
        engine.dispose()


def test_quality_evidence_excludes_customer_and_document_identifiers(
    agent_tools_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(agent_tools_database_url))
    now = datetime.now(UTC)
    try:
        with engine.begin() as connection:
            tenant_id, project_id = seed_project(connection, slug="quality-evidence")
            workflow_id = connection.execute(
                tables.projects.select()
                .with_only_columns(tables.projects.c.workflow_id)
                .where(tables.projects.c.id == project_id)
            ).scalar_one()
            actor_id = uuid4()
            connection.execute(
                tables.users.insert(),
                {
                    "id": actor_id,
                    "tenant_id": tenant_id,
                    "username": "quality-evidence-actor",
                    "display_name": "Quality Evidence Actor",
                    "role": "quality",
                },
            )
            stage_id = uuid4()
            connection.execute(
                tables.stages.insert(),
                {
                    "id": stage_id,
                    "tenant_id": tenant_id,
                    "workflow_id": workflow_id,
                    "code": "dvt",
                    "name": "DVT",
                    "sequence": 1,
                },
            )
            plan_id = uuid4()
            connection.execute(
                tables.test_plans.insert(),
                {
                    "id": plan_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "workflow_id": workflow_id,
                    "stage_id": stage_id,
                    "created_by_user_id": actor_id,
                    "phase": "dvt",
                    "title": "DVT Validation",
                    "sample_size": 1,
                    "status": "active",
                },
            )
            connection.execute(
                tables.test_cases.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "plan_id": plan_id,
                    "created_by_user_id": actor_id,
                    "title": "Connector retention",
                    "category": "mechanical",
                    "acceptance_criteria": "Retains load",
                    "severity": "critical",
                    "status": "failed",
                    "result_notes": "Latch released early",
                    "executed_by_user_id": actor_id,
                    "executed_at": now,
                },
            )
            complaint_id = uuid4()
            connection.execute(
                tables.complaints.insert(),
                {
                    "id": complaint_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "reported_by_user_id": actor_id,
                    "owner_user_id": actor_id,
                    "code": "CMP-1",
                    "title": "Connector release",
                    "description": "Connector released in field use",
                    "source": "customer",
                    "severity": "high",
                    "occurred_at": now - timedelta(days=1),
                    "reported_at": now,
                    "customer_reference": "CUSTOMER-SECRET-REF",
                    "affected_scope": "DVT connector family",
                    "document_refs": ["private/quality/object-key.pdf"],
                },
            )
            connection.execute(
                tables.nonconformance_reports.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "complaint_id": complaint_id,
                    "owner_user_id": actor_id,
                    "created_by_user_id": actor_id,
                    "code": "NCR-1",
                    "nonconformity": "Retention below requirement",
                    "requirement_reference": "SPEC-CONN-1",
                    "severity": "high",
                    "target_date": now.date() + timedelta(days=14),
                },
            )
        tools = AgentReadTools(
            engine,
            run_context=frozen_context(
                tenant_id=tenant_id,
                project_id=project_id,
                agent_key=AgentKey.QUALITY_INTELLIGENCE,
                event_type="COMPLAINT_CREATED",
            ),
        )

        page = tools.get_quality_evidence(project_id=project_id, limit=10)

        assert page.shown_count == page.total_count == 3
        assert {item["entity"] for item in page.items} == {
            "test_case",
            "complaint",
            "nonconformance_report",
        }
        assert "CUSTOMER-SECRET-REF" not in str(page.items)
        assert "private/quality/object-key.pdf" not in str(page.items)
        assert "customer_id" not in str(page.items)
        with pytest.raises(ToolScopeViolationError):
            tools.get_quality_evidence(project_id=uuid4())
    finally:
        engine.dispose()


def test_phase_three_tools_are_tenant_aggregated_bounded_and_identity_free(
    agent_tools_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ai.capability_contract import CapabilityRollout
    from tests.rollout_support import set_agent_rollout

    # Exercise the projection implementation using synthetic test adoption only.
    set_agent_rollout(monkeypatch, AgentKey.SUPPLIER_INTELLIGENCE, CapabilityRollout.LIVE)
    set_agent_rollout(monkeypatch, AgentKey.EXECUTIVE_INTELLIGENCE, CapabilityRollout.LIVE)
    engine = create_engine(psycopg_database_url(agent_tools_database_url))
    now = datetime.now(UTC)
    try:
        with engine.begin() as connection:
            tenant_id, trigger_project_id = seed_project(connection, slug="phase-three")
            workflow_id = uuid4()
            portfolio_project_id = uuid4()
            connection.execute(
                tables.workflows.insert(),
                {
                    "id": workflow_id,
                    "tenant_id": tenant_id,
                    "code": "phase-three-portfolio",
                    "name": "Portfolio",
                },
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": portfolio_project_id,
                    "tenant_id": tenant_id,
                    "workflow_id": workflow_id,
                    "code": "PRJ-PORTFOLIO",
                    "name": "Same Tenant Portfolio Project",
                    "status": "on_hold",
                },
            )
            connection.execute(
                tables.issues.insert(),
                [
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "project_id": portfolio_project_id,
                        "title": f"Open issue {index}",
                    }
                    for index in range(2)
                ],
            )
            connection.execute(
                tables.risks.insert(),
                [
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "project_id": portfolio_project_id,
                        "title": f"Open risk {index}",
                    }
                    for index in range(3)
                ],
            )
            connection.execute(
                tables.tasks.insert(),
                [
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "project_id": portfolio_project_id,
                        "title": f"Overdue task {index}",
                        "due_date": (now - timedelta(days=1)).date(),
                    }
                    for index in range(4)
                ],
            )
            supplier_id = uuid4()
            connection.execute(
                tables.suppliers.insert(),
                {
                    "id": supplier_id,
                    "tenant_id": tenant_id,
                    "code": "SUP-1",
                    "name": "Approved Supplier Name",
                    "description": "PRIVATE SUPPLIER CONTACT",
                },
            )
            connection.execute(
                tables.events.insert(),
                {
                    "tenant_id": tenant_id,
                    "project_id": portfolio_project_id,
                    "event_id": f"supplier-delay:{uuid4()}",
                    "event_type": "SUPPLIER_DELAY_REPORTED",
                    "schema_version": 1,
                    "source": "supplier_service",
                    "entity": "supplier_delay",
                    "entity_id": uuid4(),
                    "payload": {
                        "supplier_id": str(supplier_id),
                        "expected_date": "2026-08-10",
                        "reported_date": "2026-08-16",
                        "private_contact": "must not cross",
                    },
                    "timestamp": now,
                },
            )
            other_tenant_id, other_project_id = seed_project(connection, slug="phase-three-other")
            other_supplier_id = uuid4()
            connection.execute(
                tables.suppliers.insert(),
                {
                    "id": other_supplier_id,
                    "tenant_id": other_tenant_id,
                    "code": "OTHER-SUP",
                    "name": "Other Tenant Supplier",
                },
            )
            connection.execute(
                tables.events.insert(),
                {
                    "tenant_id": other_tenant_id,
                    "project_id": other_project_id,
                    "event_id": f"supplier-delay:{uuid4()}",
                    "event_type": "SUPPLIER_DELAY_REPORTED",
                    "schema_version": 1,
                    "source": "supplier_service",
                    "entity": "supplier_delay",
                    "entity_id": uuid4(),
                    "payload": {
                        "supplier_id": str(other_supplier_id),
                        "expected_date": "2026-08-10",
                        "reported_date": "2026-09-01",
                    },
                    "timestamp": now,
                },
            )

        supplier_tools = AgentReadTools(
            engine,
            run_context=frozen_context(
                tenant_id=tenant_id,
                project_id=trigger_project_id,
                agent_key=AgentKey.SUPPLIER_INTELLIGENCE,
                event_type="SUPPLIER_DELAY_REPORTED",
            ),
        )
        executive_tools = AgentReadTools(
            engine,
            run_context=frozen_context(
                tenant_id=tenant_id,
                project_id=trigger_project_id,
                agent_key=AgentKey.EXECUTIVE_INTELLIGENCE,
                event_type="PROJECT_STAGE_CHANGED",
            ),
        )

        delays = supplier_tools.get_supplier_delay_evidence(
            project_id=trigger_project_id,
            limit=20,
        )
        portfolio = executive_tools.get_portfolio_brief(
            project_id=trigger_project_id,
            limit=20,
        )

        assert delays.shown_count == delays.total_count == 1
        assert "PRJ-PORTFOLIO" in str(delays.items)
        assert "Approved Supplier Name" in str(delays.items)
        assert "private_contact" not in str(delays.items)
        assert "PRIVATE SUPPLIER CONTACT" not in str(delays.items)
        assert "Other Tenant Supplier" not in str(delays.items)
        assert {item["label"] for item in portfolio.items} >= {
            "PRJ-PHASE-THREE · Phase-Three",
            "PRJ-PORTFOLIO · Same Tenant Portfolio Project",
        }
        portfolio_item = next(
            item for item in portfolio.items if item["label"].startswith("PRJ-PORTFOLIO ·")
        )
        assert "open_issues=2" in portfolio_item["excerpt"]
        assert "open_risks=3" in portfolio_item["excerpt"]
        assert "overdue_tasks=4" in portfolio_item["excerpt"]
        assert "Other Tenant" not in str(portfolio.items)
        with pytest.raises(ToolScopeViolationError):
            supplier_tools.get_supplier_delay_evidence(project_id=portfolio_project_id)
        with pytest.raises(ToolScopeViolationError):
            executive_tools.get_portfolio_brief(project_id=portfolio_project_id)
    finally:
        engine.dispose()


@pytest.mark.parametrize("rollout", ["shadow", "disabled"])
def test_existing_tool_instance_rechecks_rollout_before_read(
    monkeypatch: pytest.MonkeyPatch,
    rollout: str,
) -> None:
    from app.ai.capability_contract import CapabilityRollout
    from app.ai.rollout_guard import CapabilityUnavailableError
    from tests.rollout_support import set_agent_rollout

    context = frozen_context(tenant_id=uuid4(), project_id=uuid4())
    # An unconnected engine makes any accidental database read fail the test.
    engine = create_engine("postgresql+psycopg://invalid:invalid@127.0.0.1:1/pdos_test")
    tools = AgentReadTools(engine, run_context=context)
    set_agent_rollout(monkeypatch, context.agent_key, CapabilityRollout(rollout))
    try:
        with pytest.raises(CapabilityUnavailableError, match=f"CAPABILITY_{rollout.upper()}"):
            tools.get_project_context(project_id=context.project_id)
        with pytest.raises(CapabilityUnavailableError):
            tools.get_recent_events(project_id=context.project_id)
        with pytest.raises(CapabilityUnavailableError):
            tools.search_memory(project_id=context.project_id, query="project")
    finally:
        engine.dispose()


def test_issue_evidence_is_project_bound_and_carries_no_people(
    agent_tools_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(agent_tools_database_url))
    try:
        with engine.begin() as connection:
            tenant_id, project_id = seed_project(connection, slug="issue-evidence")
            other_tenant_id, other_project_id = seed_project(connection, slug="issue-other")
            owner_id = uuid4()
            connection.execute(
                tables.users.insert(),
                {
                    "id": owner_id,
                    "tenant_id": tenant_id,
                    "username": "issue-owner",
                    "display_name": "Issue Owner",
                    "role": "engineer",
                },
            )
            issue_id = uuid4()
            connection.execute(
                tables.issues.insert(),
                [
                    {
                        "id": issue_id,
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "owner_user_id": owner_id,
                        "reported_by_user_id": owner_id,
                        "title": "Charging temperature over limit",
                        "description": "Cell reached 52C against a 45C limit on two units.",
                        "issue_type": "test_failure",
                        "severity": "high",
                        "root_cause": "Charge current too high",
                    },
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "owner_user_id": None,
                        "reported_by_user_id": None,
                        "title": "Blank description issue",
                        "description": "   ",
                        "issue_type": "engineering",
                        "severity": "medium",
                        "root_cause": None,
                    },
                ],
            )
            connection.execute(
                tables.issues.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": other_tenant_id,
                    "project_id": other_project_id,
                    "title": "Other tenant issue",
                },
            )
        tools = AgentReadTools(
            engine,
            run_context=frozen_context(tenant_id=tenant_id, project_id=project_id),
        )

        page = tools.get_issue_evidence(project_id=project_id, limit=10)

        assert page.shown_count == 2 and page.total_count == 2 and not page.truncated
        by_label = {item["label"]: item for item in page.items}
        assert set(by_label) == {"Charging temperature over limit", "Blank description issue"}
        issue = by_label["Charging temperature over limit"]
        assert issue["reference_id"] == f"issue:{issue_id}"
        assert issue["excerpt"] == (
            "type=test_failure; severity=high; status=open; "
            "description=Cell reached 52C against a 45C limit on two units.; "
            "root_cause=Charge current too high"
        )
        assert "description=" not in by_label["Blank description issue"]["excerpt"]
        assert str(owner_id) not in str(page.items)
        assert "Issue Owner" not in str(page.items)
        assert "Other tenant issue" not in str(page.items)
        with pytest.raises(ToolScopeViolationError):
            tools.get_issue_evidence(project_id=other_project_id)
    finally:
        engine.dispose()
