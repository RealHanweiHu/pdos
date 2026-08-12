"""Evidence-scoped, citation-enforced project chat."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, RowMapping, desc, select

from app.ai.application_gateway import ApplicationModelGateway
from app.ai.gateway import GatewayInvocation
from app.ai.model_catalog import AgentTier
from app.db.schema import tables

PROMPT_PATH = Path(__file__).with_name("prompts") / "ai_chat_v1.json"


class ChatPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1, max_length=128)
    agent_key: Literal["ai_chat"]
    system_prompt: str = Field(min_length=1, max_length=100_000)
    instruction: str = Field(min_length=1, max_length=100_000)


CHAT_PROMPT = ChatPrompt.model_validate_json(PROMPT_PATH.read_text())


class ChatClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1, max_length=2_000)
    citation_ids: tuple[str, ...] = Field(min_length=1, max_length=10)


class ChatAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    disposition: Literal["answered", "insufficient_evidence"]
    claims: tuple[ChatClaim, ...] = Field(max_length=10)

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.disposition == "answered" and not self.claims:
            raise ValueError("answered chat requires at least one cited claim")
        if self.disposition == "insufficient_evidence" and self.claims:
            raise ValueError("insufficient evidence cannot carry claims")
        return self


class ChatEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reference_id: str
    entity: str
    entity_id: str
    label: str
    href: str
    excerpt: str


@dataclass(frozen=True)
class ChatResult:
    status: Literal["answered", "insufficient_evidence", "unavailable"]
    answer: str | None
    citations: tuple[ChatEvidence, ...]
    error_code: str | None = None


def _excerpt(*parts: object, limit: int = 1_000) -> str:
    value = " · ".join(
        str(part).strip() for part in parts if part is not None and str(part).strip()
    )
    return value[:limit]


def _base_href(project_id: UUID, tab: str, **params: object) -> str:
    query = "&".join(f"{name}={value}" for name, value in params.items())
    return f"/projects?project={project_id}&tab={tab}" + (f"&{query}" if query else "")


class ChatEvidenceRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def collect(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        question: str,
    ) -> tuple[ChatEvidence, ...]:
        with self._engine.connect() as connection:
            project = (
                connection.execute(
                    select(
                        tables.projects.c.id,
                        tables.projects.c.code,
                        tables.projects.c.name,
                        tables.projects.c.status,
                        tables.stages.c.name.label("stage_name"),
                    )
                    .select_from(
                        tables.projects.outerjoin(
                            tables.stages,
                            (tables.stages.c.tenant_id == tables.projects.c.tenant_id)
                            & (tables.stages.c.id == tables.projects.c.current_stage_id),
                        )
                    )
                    .where(
                        tables.projects.c.tenant_id == tenant_id,
                        tables.projects.c.id == project_id,
                    )
                )
                .mappings()
                .one()
            )
            evidence = [self._project_evidence(project, project_id=project_id)]
            evidence.extend(
                self._work_item_evidence(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                )
            )
            evidence.extend(
                self._event_evidence(connection, tenant_id=tenant_id, project_id=project_id)
            )
            evidence.extend(
                self._document_evidence(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    question=question,
                )
            )
        return tuple(evidence)

    @staticmethod
    def _project_evidence(project: RowMapping, *, project_id: UUID) -> ChatEvidence:
        stage = project["stage_name"] or "Unassigned"
        return ChatEvidence(
            reference_id=f"project:{project_id}",
            entity="project",
            entity_id=str(project_id),
            label=f"{project['code']} · {project['name']}",
            href=_base_href(project_id, "overview"),
            excerpt=_excerpt(f"status={project['status']}", f"stage={stage}"),
        )

    @staticmethod
    def _work_item_evidence(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
    ) -> list[ChatEvidence]:
        specifications = (
            (
                "issue",
                tables.issues,
                (tables.issues.c.title, tables.issues.c.status, tables.issues.c.severity),
                "issues",
            ),
            (
                "risk",
                tables.risks,
                (
                    tables.risks.c.title,
                    tables.risks.c.status,
                    tables.risks.c.likelihood,
                    tables.risks.c.impact,
                ),
                "risks",
            ),
            (
                "task",
                tables.tasks,
                (tables.tasks.c.title, tables.tasks.c.status, tables.tasks.c.due_date),
                "tasks",
            ),
            (
                "gate",
                tables.gates,
                (tables.gates.c.name, tables.gates.c.status, tables.gates.c.review_due_at),
                "timeline",
            ),
        )
        evidence: list[ChatEvidence] = []
        for entity, table, columns, tab in specifications:
            timestamp_column = table.c.updated_at if "updated_at" in table.c else table.c.created_at
            rows = connection.execute(
                select(table.c.id, *columns)
                .where(table.c.tenant_id == tenant_id, table.c.project_id == project_id)
                .order_by(desc(timestamp_column))
                .limit(10)
            ).mappings()
            for row in rows:
                item_id = UUID(str(row["id"]))
                values = [row[column.name] for column in columns]
                evidence.append(
                    ChatEvidence(
                        reference_id=f"{entity}:{item_id}",
                        entity=entity,
                        entity_id=str(item_id),
                        label=str(values[0]),
                        href=_base_href(project_id, tab, **{f"{entity}_id": item_id}),
                        excerpt=_excerpt(*values),
                    )
                )
        return evidence

    @staticmethod
    def _event_evidence(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
    ) -> list[ChatEvidence]:
        rows = connection.execute(
            select(
                tables.events.c.id,
                tables.events.c.event_type,
                tables.events.c.entity,
                tables.events.c.timestamp,
            )
            .where(
                tables.events.c.tenant_id == tenant_id,
                tables.events.c.project_id == project_id,
            )
            .order_by(tables.events.c.id.desc())
            .limit(10)
        ).mappings()
        return [
            ChatEvidence(
                reference_id=f"event:{row['id']}",
                entity="event",
                entity_id=str(row["id"]),
                label=str(row["event_type"]),
                href=_base_href(project_id, "timeline", event_id=row["id"]),
                excerpt=_excerpt(row["event_type"], row["entity"], row["timestamp"].isoformat()),
            )
            for row in rows
        ]

    @staticmethod
    def _document_evidence(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        question: str,
    ) -> list[ChatEvidence]:
        rows = list(
            connection.execute(
                select(
                    tables.documents.c.id.label("document_id"),
                    tables.documents.c.filename,
                    tables.document_fragments.c.ordinal,
                    tables.document_fragments.c.locator,
                    tables.document_fragments.c.text,
                )
                .select_from(
                    tables.document_fragments.join(
                        tables.documents,
                        (tables.documents.c.tenant_id == tables.document_fragments.c.tenant_id)
                        & (tables.documents.c.id == tables.document_fragments.c.document_id),
                    )
                )
                .where(
                    tables.document_fragments.c.tenant_id == tenant_id,
                    tables.document_fragments.c.project_id == project_id,
                    tables.documents.c.classification == "internal",
                )
                .order_by(
                    tables.documents.c.created_at.desc(),
                    tables.document_fragments.c.ordinal,
                )
                .limit(200)
            ).mappings()
        )
        terms = {term.lower() for term in re.findall(r"[\w\u4e00-\u9fff]{2,}", question)}

        def score(row: RowMapping) -> tuple[int, int]:
            text_value = str(row["text"]).lower()
            return (sum(1 for term in terms if term in text_value), -int(row["ordinal"]))

        selected = sorted(rows, key=score, reverse=True)[:5]
        output: list[ChatEvidence] = []
        for row in selected:
            document_id = UUID(str(row["document_id"]))
            ordinal = int(row["ordinal"])
            output.append(
                ChatEvidence(
                    reference_id=f"document:{document_id}:fragment:{ordinal}",
                    entity="document_fragment",
                    entity_id=str(document_id),
                    label=f"{row['filename']} · {row['locator']}",
                    href=_base_href(
                        project_id,
                        "timeline",
                        document_id=document_id,
                        entity_id=document_id,
                        fragment=ordinal,
                    ),
                    excerpt=_excerpt(row["text"]),
                )
            )
        return output


class ChatService:
    def __init__(self, engine: Engine, *, gateway: ApplicationModelGateway) -> None:
        self._engine = engine
        self._gateway = gateway

    def answer(self, *, tenant_id: UUID, project_id: UUID, question: str) -> ChatResult:
        evidence = ChatEvidenceRepository(self._engine).collect(
            tenant_id=tenant_id,
            project_id=project_id,
            question=question,
        )
        result = self._gateway.invoke_structured(
            GatewayInvocation(
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=None,
                agent_key=CHAT_PROMPT.agent_key,
                agent_tier=AgentTier.DEFAULT,
                prompt_version=CHAT_PROMPT.version,
                system_prompt=CHAT_PROMPT.system_prompt,
                instruction=CHAT_PROMPT.instruction,
                context={
                    "question": question,
                    "references": [
                        item.model_dump(mode="json", exclude={"href"}) for item in evidence
                    ],
                },
            ),
            ChatAssessment,
        )
        if result.status == "degraded" or result.output is None:
            return ChatResult(
                status="unavailable",
                answer=None,
                citations=(),
                error_code=result.error_code or "MODEL_UNAVAILABLE",
            )
        if result.output.disposition == "insufficient_evidence":
            return ChatResult(status="insufficient_evidence", answer=None, citations=())
        by_id = {item.reference_id: item for item in evidence}
        requested_ids = tuple(
            dict.fromkeys(
                citation_id for claim in result.output.claims for citation_id in claim.citation_ids
            )
        )
        if any(citation_id not in by_id for citation_id in requested_ids):
            return ChatResult(
                status="insufficient_evidence",
                answer=None,
                citations=(),
                error_code="CITATION_SCOPE_INVALID",
            )
        return ChatResult(
            status="answered",
            answer="\n".join(claim.text.strip() for claim in result.output.claims),
            citations=tuple(by_id[citation_id] for citation_id in requested_ids),
        )
