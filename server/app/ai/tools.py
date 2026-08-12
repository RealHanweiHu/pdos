"""Frozen, run-scoped read-only tools available to the Phase 1 Agents."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, func, select, text

from app.ai.run_store import AgentRunStore
from app.ai.runtime_contract import FrozenRunContext
from app.db.schema import tables


class ToolScopeViolationError(PermissionError):
    """Raised when a model-provided scope does not match the server-bound run."""


class ToolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    description: str
    input_example: dict[str, object]


TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="get_project_context",
        description=(
            "Use when the Agent needs the server-frozen Project snapshot and deterministic "
            "execution metrics. Do not use when a recent event or verified memory is needed. "
            "Negative example: never request another Project to compare tenants. Boundary: "
            "project_id must exactly match the run scope; the server rejects any mismatch."
        ),
        input_example={"project_id": "9a7b1a4f-8d8b-4a8b-a3c7-e9fb8198e268"},
    ),
    ToolDefinition(
        name="search_memory",
        description=(
            "Use when the Agent needs concise, human-verified organizational memory relevant "
            "to a query. Do not use for raw documents, drafts, or current event history. Negative "
            "example: never treat an unverified document upload as memory. Boundary: tenant and "
            "Project come only from the run; pagination is explicit and results may be empty."
        ),
        input_example={
            "project_id": "9a7b1a4f-8d8b-4a8b-a3c7-e9fb8198e268",
            "query": "gate readiness lessons",
            "offset": 0,
            "limit": 20,
        },
    ),
    ToolDefinition(
        name="get_recent_events",
        description=(
            "Use when the Agent needs recent allowlisted event references for the current "
            "Project. Do not use to reconstruct full business state or read event payloads. "
            "Negative example: never pass a different Project id supplied by model text. "
            "Boundary: server-bound tenant/Project only; after_id and limit paginate explicitly."
        ),
        input_example={
            "project_id": "9a7b1a4f-8d8b-4a8b-a3c7-e9fb8198e268",
            "after_id": 0,
            "limit": 20,
        },
    ),
)


class ToolPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[dict[str, Any], ...]
    shown_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    truncated: bool
    next_after_id: int | None = Field(default=None, ge=1)
    continuation: str
    source_status: Literal["ready", "not_enabled"] = "ready"


class ProjectContextResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project: dict[str, Any]
    execution: dict[str, Any]
    shown_count: Literal[1] = 1
    total_count: Literal[1] = 1
    truncated: Literal[False] = False
    continuation: str = "已显示 1 之 1 条；无需续读。"


class AgentReadTools:
    def __init__(
        self,
        engine: Engine,
        *,
        run_context: FrozenRunContext,
        run_store: AgentRunStore | None = None,
    ) -> None:
        self._engine = engine
        self._context = run_context
        self._run_store = run_store

    def get_project_context(self, *, project_id: UUID) -> ProjectContextResult:
        self._assert_scope(project_id)
        return ProjectContextResult(
            project=self._context.project,
            execution=self._context.execution,
        )

    def get_recent_events(
        self,
        *,
        project_id: UUID,
        after_id: int = 0,
        limit: int = 20,
    ) -> ToolPage:
        self._assert_scope(project_id)
        self._validate_page(after_id=after_id, limit=limit)
        with self._engine.connect() as connection:
            if self._run_store is not None and self._run_store.projection_only:
                self._run_store.bind(connection)
                total = int(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM cehub_ai.agent_event_projection "
                            "WHERE id > :after_id"
                        ),
                        {"after_id": after_id},
                    ).scalar_one()
                )
                rows = list(
                    connection.execute(
                        text(
                            "SELECT id, event_type, entity, entity_id, timestamp "
                            "FROM cehub_ai.agent_event_projection WHERE id > :after_id "
                            "ORDER BY id LIMIT :limit"
                        ),
                        {"after_id": after_id, "limit": limit},
                    ).mappings()
                )
            else:
                filters = (
                    tables.events.c.tenant_id == self._context.tenant_id,
                    tables.events.c.project_id == self._context.project_id,
                    tables.events.c.id > after_id,
                )
                total = int(
                    connection.execute(
                        select(func.count()).select_from(tables.events).where(*filters)
                    ).scalar_one()
                )
                rows = list(
                    connection.execute(
                        select(
                            tables.events.c.id,
                            tables.events.c.event_type,
                            tables.events.c.entity,
                            tables.events.c.entity_id,
                            tables.events.c.timestamp,
                        )
                        .where(*filters)
                        .order_by(tables.events.c.id)
                        .limit(limit)
                    ).mappings()
                )
        items = tuple(
            {
                "id": int(row["id"]),
                "event_type": str(row["event_type"]),
                "entity": str(row["entity"]),
                "entity_id": str(row["entity_id"]),
                "timestamp": row["timestamp"].isoformat(),
            }
            for row in rows
        )
        next_after_id = int(rows[-1]["id"]) if total > len(rows) and rows else None
        return ToolPage(
            items=items,
            shown_count=len(items),
            total_count=total,
            truncated=total > len(items),
            next_after_id=next_after_id,
            continuation=self._continuation(
                shown=len(items),
                total=total,
                next_after_id=next_after_id,
            ),
        )

    def search_memory(
        self,
        *,
        project_id: UUID,
        query: str,
        offset: int = 0,
        limit: int = 20,
    ) -> ToolPage:
        self._assert_scope(project_id)
        if not query.strip() or len(query) > 500:
            raise ValueError("memory query must contain between 1 and 500 characters")
        self._validate_page(after_id=offset, limit=limit)
        # S4-2 owns the verified-memory persistence and retrieval pipeline. Keep
        # this frozen S2-2 port fail-closed until that trusted source exists.
        return ToolPage(
            items=(),
            shown_count=0,
            total_count=0,
            truncated=False,
            next_after_id=None,
            continuation="已显示 0 之 0 条；verified memory 数据源尚未启用，无需续读。",
            source_status="not_enabled",
        )

    def get_document_fragments(
        self,
        *,
        project_id: UUID,
        document_id: UUID,
        offset: int = 0,
        limit: int = 20,
    ) -> ToolPage:
        """Return extracted text fragments; object keys and original files never cross this port."""
        self._assert_scope(project_id)
        self._validate_page(after_id=offset, limit=limit)
        with self._engine.connect() as connection:
            if self._run_store is not None and self._run_store.projection_only:
                self._run_store.bind(connection)
                filters = "document_id = :document_id AND ordinal > :offset"
                total = int(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM cehub_ai.agent_document_fragment_projection "
                            f"WHERE {filters}"
                        ),
                        {"document_id": document_id, "offset": offset},
                    ).scalar_one()
                )
                rows = list(
                    connection.execute(
                        text(
                            "SELECT document_id, ordinal, locator, text, filename, classification "
                            "FROM cehub_ai.agent_document_fragment_projection "
                            f"WHERE {filters} ORDER BY ordinal LIMIT :limit"
                        ),
                        {"document_id": document_id, "offset": offset, "limit": limit},
                    ).mappings()
                )
            else:
                scoped = (
                    tables.document_fragments.c.tenant_id == self._context.tenant_id,
                    tables.document_fragments.c.project_id == self._context.project_id,
                    tables.document_fragments.c.document_id == document_id,
                    tables.document_fragments.c.ordinal > offset,
                    tables.documents.c.classification == "internal",
                )
                total = int(
                    connection.execute(
                        select(func.count())
                        .select_from(
                            tables.document_fragments.join(
                                tables.documents,
                                (
                                    tables.documents.c.tenant_id
                                    == tables.document_fragments.c.tenant_id
                                )
                                & (
                                    tables.documents.c.id == tables.document_fragments.c.document_id
                                ),
                            )
                        )
                        .where(*scoped)
                    ).scalar_one()
                )
                rows = list(
                    connection.execute(
                        select(
                            tables.document_fragments.c.document_id,
                            tables.document_fragments.c.ordinal,
                            tables.document_fragments.c.locator,
                            tables.document_fragments.c.text,
                            tables.documents.c.filename,
                            tables.documents.c.classification,
                        )
                        .select_from(
                            tables.document_fragments.join(
                                tables.documents,
                                (
                                    tables.documents.c.tenant_id
                                    == tables.document_fragments.c.tenant_id
                                )
                                & (
                                    tables.documents.c.id == tables.document_fragments.c.document_id
                                ),
                            )
                        )
                        .where(*scoped)
                        .order_by(tables.document_fragments.c.ordinal)
                        .limit(limit)
                    ).mappings()
                )
        items = tuple(
            {
                "document_id": str(row["document_id"]),
                "ordinal": int(row["ordinal"]),
                "locator": str(row["locator"]),
                "text": str(row["text"]),
                "filename": str(row["filename"]),
                "classification": str(row["classification"]),
            }
            for row in rows
        )
        next_after_id = int(rows[-1]["ordinal"]) if total > len(rows) and rows else None
        return ToolPage(
            items=items,
            shown_count=len(items),
            total_count=total,
            truncated=total > len(items),
            next_after_id=next_after_id,
            continuation=self._continuation(
                shown=len(items), total=total, next_after_id=next_after_id
            ),
        )

    def _assert_scope(self, claimed_project_id: UUID) -> None:
        if claimed_project_id != self._context.project_id:
            raise ToolScopeViolationError("tool Project scope does not match the Agent run")

    @staticmethod
    def _validate_page(*, after_id: int, limit: int) -> None:
        if after_id < 0:
            raise ValueError("pagination cursor must be nonnegative")
        if not 1 <= limit <= 100:
            raise ValueError("tool page limit must be between 1 and 100")

    @staticmethod
    def _continuation(*, shown: int, total: int, next_after_id: int | None) -> str:
        if next_after_id is None:
            return f"已显示 {shown} 之 {total} 条；无需续读。"
        return f"已显示 {shown} 之 {total} 条；使用 after_id={next_after_id} 续读。"
