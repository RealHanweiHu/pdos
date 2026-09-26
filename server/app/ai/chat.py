"""Evidence-scoped, citation-enforced project chat."""

from __future__ import annotations

import re
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, RowMapping, desc, select

from app.ai.application_gateway import ApplicationModelGateway
from app.ai.call_identity import ModelCallSlot, model_call_id
from app.ai.chat_runs import ChatRunStore
from app.ai.embeddings import EmbeddingError, EmbeddingGateway
from app.ai.gateway import GatewayInvocation
from app.ai.model_catalog import AgentTier
from app.auth.errors import ObjectPermissionDeniedError
from app.auth.project_access import ProjectAccessService, SqlProjectAccessRepository
from app.auth.repository import AuthContext, AuthRepository
from app.auth.roles import Action, is_allowed
from app.db.schema import tables
from app.domain.memories import MemoryService

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


class ChatResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
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
    def __init__(
        self, engine: Engine, *, embedding_gateway: EmbeddingGateway | None = None
    ) -> None:
        self._engine = engine
        self._embedding_gateway = embedding_gateway

    def collect(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        question: str,
        actor_user_id: UUID | None = None,
        attachment_ids: tuple[UUID, ...] = (),
        object_focus: dict[str, Any] | None = None,
    ) -> tuple[ChatEvidence, ...]:
        if object_focus is not None:
            from app.domain.conversation_focus import current

            if actor_user_id is None or attachment_ids:
                raise ObjectPermissionDeniedError
            with self._engine.connect() as connection:
                value = current(connection, tenant_id, project_id, actor_user_id, object_focus)
            import json

            return (
                ChatEvidence(
                    reference_id=f"work-card:{value['kind']}:{value['id']}:{value['digest']}",
                    entity=value["kind"],
                    entity_id=value["id"],
                    label=value["title"],
                    href=value["href"],
                    excerpt="本次选定对象的当前字段；长字段只显示片段，未提供关联原件全文或其他对象，不据此认定全范围已完成。\n"
                    + json.dumps(value["fields"], ensure_ascii=False),
                ),
            )
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
        if self._embedding_gateway is not None:
            evidence.extend(
                self._memory_evidence(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    question=question,
                )
            )
        from app.domain.conversation_attachments import attachment_evidence

        evidence.extend(
            attachment_evidence(
                self._engine,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                attachment_ids=attachment_ids,
                question=question,
            )
        )
        return tuple(evidence)

    def still_current(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        question: str,
        actor_user_id: UUID | None = None,
        attachment_ids: tuple[UUID, ...] = (),
        object_focus: dict[str, Any] | None = None,
        evidence: tuple[ChatEvidence, ...],
    ) -> bool:
        # Revalidate frozen source excerpts without running embedding/model search again.
        try:
            current = {
                item.reference_id: item
                for item in ChatEvidenceRepository(self._engine).collect(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    question=question,
                    actor_user_id=actor_user_id,
                    attachment_ids=attachment_ids,
                    object_focus=object_focus,
                )
            }
        except (ValueError, PermissionError):
            if object_focus is not None:
                return False
            raise
        memory_ids = [UUID(item.entity_id) for item in evidence if item.entity == "memory"]
        if memory_ids:
            with self._engine.connect() as connection:
                rows = connection.execute(
                    select(tables.memories).where(
                        tables.memories.c.tenant_id == tenant_id,
                        tables.memories.c.project_id == project_id,
                        tables.memories.c.status == "verified",
                        tables.memories.c.id.in_(memory_ids),
                    )
                ).mappings()
                for row in rows:
                    item = ChatEvidence(
                        reference_id=f"memory:{row['id']}",
                        entity="memory",
                        entity_id=str(row["id"]),
                        label=row["title"],
                        href=f"/knowledge?project={project_id}&memory={row['id']}",
                        excerpt=_excerpt(
                            row["content"],
                            row["applicability"],
                            "tags=" + ", ".join(row["tags"]) if row["tags"] else None,
                        ),
                    )
                    current[item.reference_id] = item
        return all(current.get(item.reference_id) == item for item in evidence)

    def _memory_evidence(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        question: str,
    ) -> list[ChatEvidence]:
        if self._embedding_gateway is None:
            return []
        results = MemoryService(self._engine).search(
            tenant_id=tenant_id,
            project_id=project_id,
            query=question,
            gateway=self._embedding_gateway,
            limit=5,
        )
        return [
            ChatEvidence(
                reference_id=f"memory:{result.memory.id}",
                entity="memory",
                entity_id=str(result.memory.id),
                label=result.memory.title,
                href=f"/knowledge?project={project_id}&memory={result.memory.id}",
                excerpt=_excerpt(
                    result.memory.content,
                    result.memory.applicability,
                    "tags=" + ", ".join(result.memory.tags) if result.memory.tags else None,
                ),
            )
            for result in results
        ]

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
    def __init__(
        self,
        engine: Engine,
        *,
        gateway: ApplicationModelGateway,
        embedding_gateway: EmbeddingGateway | None = None,
    ) -> None:
        self._engine = engine
        self._gateway = gateway
        self._embedding_gateway = embedding_gateway

    def _authorize(self, context: AuthContext, project_id: UUID) -> None:
        authorize_chat(self._engine, context, project_id)

    def answer(
        self,
        *,
        context: AuthContext,
        project_id: UUID,
        question: str,
        request_id: str,
        attachment_ids: tuple[UUID, ...] = (),
        object_focus: dict[str, Any] | None = None,
    ) -> ChatResult:
        self._authorize(context, project_id)
        tenant_id = context.tenant.id
        store = ChatRunStore(self._engine, gateway=self._gateway)
        row, created = store.start(
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=context.user.id,
            auth_version=context.user.auth_version,
            request_id=request_id,
            question=question,
            attachment_ids=attachment_ids,
            object_focus=object_focus,
        )
        run_id = row["id"]
        repository = ChatEvidenceRepository(self._engine, embedding_gateway=self._embedding_gateway)
        if not created:
            return self.read_result(context=context, row=row)
        try:
            try:
                from app.ai.application_recovery import is_recovery, original_observation

                if is_recovery(self._gateway, tenant_id, run_id):
                    with self._engine.connect() as connection:
                        saved = original_observation(connection, row)
                    evidence = tuple(
                        ChatEvidence.model_validate(item) for item in saved["output_body"]
                    )
                else:
                    evidence = repository.collect(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        question=question,
                        actor_user_id=context.user.id,
                        attachment_ids=attachment_ids,
                        object_focus=object_focus,
                    )
            except EmbeddingError as error:
                result = ChatResult(
                    status="unavailable", answer=None, citations=(), error_code=error.code
                )
            else:
                store.save_evidence(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    evidence=[item.model_dump(mode="json") for item in evidence],
                )
                self._authorize(context, project_id)
                if repository.still_current(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    question=question,
                    evidence=evidence,
                    actor_user_id=context.user.id,
                    attachment_ids=attachment_ids,
                    object_focus=object_focus,
                ):
                    result = self._generate(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        question=question,
                        run_id=run_id,
                        evidence=evidence,
                    )
                    self._authorize(context, project_id)
                    if result.status == "answered" and not repository.still_current(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        question=question,
                        evidence=evidence,
                        actor_user_id=context.user.id,
                        attachment_ids=attachment_ids,
                        object_focus=object_focus,
                    ):
                        result = ChatResult(
                            status="unavailable",
                            answer=None,
                            citations=(),
                            error_code="CHAT_EVIDENCE_CHANGED",
                        )
                else:
                    result = ChatResult(
                        status="unavailable",
                        answer=None,
                        citations=(),
                        error_code="CHAT_EVIDENCE_CHANGED",
                    )
            store.finish(tenant_id=tenant_id, run_id=run_id, result=result.model_dump(mode="json"))
            return result
        except Exception:
            # Failure never mints another request or permits re-dispatch on replay.
            with suppress(Exception):
                store.finish(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    result={
                        "status": "unavailable",
                        "answer": None,
                        "citations": [],
                        "error_code": "CHAT_REQUEST_FAILED",
                    },
                )
            raise

    def read_result(self, *, context: AuthContext, row: RowMapping) -> ChatResult:
        return read_chat_result(self._engine, context=context, row=row)

    def _generate(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        question: str,
        run_id: UUID,
        evidence: tuple[ChatEvidence, ...],
    ) -> ChatResult:
        from app.ai.application_context import record_chat_context

        record_chat_context(
            self._engine,
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run_id,
            model_call_id=model_call_id(run_id, ModelCallSlot.CHAT_ANSWER),
            question=question,
            evidence=evidence,
        )
        result = self._gateway.invoke_structured(
            GatewayInvocation(
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run_id,
                model_call_id=model_call_id(run_id, ModelCallSlot.CHAT_ANSWER),
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


def authorize_chat(engine: Engine, context: AuthContext, project_id: UUID) -> None:
    current = AuthRepository(engine).find_user_context(context.user.id)
    if (
        current is None
        or current.tenant.id != context.tenant.id
        or current.tenant.status != "active"
        or not current.user.is_active
        or current.user.auth_version != context.user.auth_version
        or not is_allowed(current.user.role, Action.AI_CHAT_USE)
    ):
        raise ObjectPermissionDeniedError
    ProjectAccessService(SqlProjectAccessRepository(engine)).authorize(
        context=current, project_id=project_id, action=Action.PROJECT_VIEW
    )


def read_chat_result(engine: Engine, *, context: AuthContext, row: RowMapping) -> ChatResult:
    """Revalidate saved output without constructing or invoking any model gateway."""
    tenant_id, project_id = row["tenant_id"], row["project_id"]
    if tenant_id != context.tenant.id or row["requested_by_user_id"] != context.user.id:
        raise ObjectPermissionDeniedError
    question = row["run_context"]["chat_question"]
    repository = ChatEvidenceRepository(engine)
    result = ChatResult.model_validate(
        row["run_context"].get("chat_result")
        or {
            "status": "unavailable",
            "answer": None,
            "citations": [],
            "error_code": row["error_code"] or "CHAT_REQUEST_INCOMPLETE",
        }
    )
    evidence = tuple(
        ChatEvidence.model_validate(item) for item in row["run_context"].get("chat_evidence", [])
    )
    authorize_chat(engine, context, project_id)
    try:
        current = (
            repository.still_current(
                tenant_id=tenant_id,
                project_id=project_id,
                question=question,
                evidence=evidence,
                object_focus=row["run_context"].get("chat_object_focus"),
                actor_user_id=context.user.id,
                attachment_ids=tuple(
                    UUID(a) for a in row["run_context"].get("chat_attachment_ids", [])
                ),
            )
            if result.status == "answered"
            else True
        )
    except (ValueError, PermissionError):
        current = False
    if not current:
        return ChatResult(
            status="unavailable",
            answer=None,
            citations=(),
            error_code="CHAT_EVIDENCE_CHANGED",
        )
    return result
