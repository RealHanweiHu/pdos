"""Frozen, run-scoped read-only tools available to PDOS Agents."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, func, select, text

from app.ai.embeddings import EmbeddingGateway
from app.ai.run_store import AgentRunStore
from app.ai.runtime_contract import AgentKey, FrozenRunContext
from app.db.schema import tables


class ToolScopeViolationError(PermissionError):
    """Raised when a model-provided scope does not match the server-bound run."""


class ToolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    description: str
    input_example: dict[str, object]


# V2-8 (D25). Reach tools are available to every seat, so they live in the
# common set rather than behind an agent-specific branch.
REACH_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="web_search",
        description=(
            "Use when the Agent needs candidate public URLs for a research question. Do not "
            "use to read a page; search returns links and snippets only. Negative example: "
            "never treat a search snippet as a fact — fetch the page and cite the snapshot. "
            "Boundary: results are filtered by the reach blocklist, and the tool fails with "
            "an explicit unavailable error when no search provider is configured rather than "
            "returning an empty list."
        ),
        input_example={"query": "锂电池气泵 噪声 标准", "limit": 10},
    ),
    ToolDefinition(
        name="web_fetch",
        description=(
            "Use when the Agent needs the text of a specific public page. Do not use for "
            "internal hosts, login or OAuth pages, or downloads; only read-only GET is "
            "possible and no credentials are ever sent. Negative example: never fetch an "
            "address inside the network, including via a redirect. Boundary: every fetch is "
            "stored as an evidence snapshot marked untrusted_external, and conclusions must "
            "cite the returned snapshot_id rather than the returned text."
        ),
        input_example={"url": "https://example.com/products/pump-a"},
    ),
    ToolDefinition(
        name="source_snapshot",
        description=(
            "Use when the Agent needs to re-read evidence already captured in this tenant by "
            "its snapshot id. Do not use to fetch anything new or to reach another tenant. "
            "Negative example: never assume a snapshot is current — check its staleness "
            "before relying on it. Boundary: tenant comes only from the run, and a superseded "
            "or expired snapshot is returned marked stale rather than silently refreshed."
        ),
        input_example={"snapshot_id": "9a7b1a4f-8d8b-4a8b-a3c7-e9fb8198e268"},
    ),
)

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

ENGINEERING_EVIDENCE_TOOL = ToolDefinition(
    name="get_engineering_evidence",
    description=(
        "Use when Engineering Intelligence needs allowlisted Development BOM and engineering "
        "change summaries for the current Project. Do not use for ERP execution facts or raw "
        "BOM attributes. Negative example: never infer another Project's affected parts. "
        "Boundary: the server-bound tenant and Project are immutable; results are explicitly "
        "paginated and contain summaries, not business-write authority."
    ),
    input_example={
        "project_id": "9a7b1a4f-8d8b-4a8b-a3c7-e9fb8198e268",
        "offset": 0,
        "limit": 20,
    },
)

QUALITY_EVIDENCE_TOOL = ToolDefinition(
    name="get_quality_evidence",
    description=(
        "Use when Quality Intelligence needs allowlisted failed-test, Complaint, and NCR "
        "summaries for the current Project. Do not use for Customer identity, attachments, or "
        "unapproved root-cause claims. Negative example: never call correlation a proven root "
        "cause. Boundary: the server-bound tenant and Project are immutable; results are "
        "explicitly paginated and cannot update quality records."
    ),
    input_example={
        "project_id": "9a7b1a4f-8d8b-4a8b-a3c7-e9fb8198e268",
        "offset": 0,
        "limit": 20,
    },
)

SUPPLIER_DELAY_EVIDENCE_TOOL = ToolDefinition(
    name="get_supplier_delay_evidence",
    description=(
        "Use when Supplier Intelligence needs bounded supplier-delay summaries across the run "
        "tenant. Do not use for supplier contacts, commercial terms, raw Event payloads, or "
        "another tenant. Negative example: never infer a supplier commitment from a report. "
        "Boundary: tenant comes only from the run; project_id must match the trigger Project "
        "and results are explicitly paginated read-only summaries."
    ),
    input_example={
        "project_id": "9a7b1a4f-8d8b-4a8b-a3c7-e9fb8198e268",
        "offset": 0,
        "limit": 20,
    },
)

PORTFOLIO_BRIEF_TOOL = ToolDefinition(
    name="get_portfolio_brief",
    description=(
        "Use when Executive Intelligence needs a bounded cross-Project summary for the run "
        "tenant. Do not use for user identity, Customer details, raw descriptions, or project "
        "facts outside the tenant. Negative example: never rank people from Project counts. "
        "Boundary: tenant comes only from the run; project_id must match the trigger Project "
        "and at most 20 non-identity summaries are returned per page."
    ),
    input_example={
        "project_id": "9a7b1a4f-8d8b-4a8b-a3c7-e9fb8198e268",
        "offset": 0,
        "limit": 20,
    },
)


# Reach is part of every seat's surface (D25: 全体席位可用).
TOOL_DEFINITIONS = (*TOOL_DEFINITIONS, *REACH_TOOL_DEFINITIONS)


def tool_definitions_for_agent(agent_key: AgentKey) -> tuple[ToolDefinition, ...]:
    if agent_key is AgentKey.PRODUCT_MANAGEMENT_INTELLIGENCE:
        return ()
    if agent_key is AgentKey.ENGINEERING_INTELLIGENCE:
        return (*TOOL_DEFINITIONS, ENGINEERING_EVIDENCE_TOOL)
    if agent_key is AgentKey.QUALITY_INTELLIGENCE:
        return (*TOOL_DEFINITIONS, QUALITY_EVIDENCE_TOOL)
    if agent_key is AgentKey.SUPPLIER_INTELLIGENCE:
        return (*TOOL_DEFINITIONS, SUPPLIER_DELAY_EVIDENCE_TOOL)
    if agent_key is AgentKey.EXECUTIVE_INTELLIGENCE:
        return (*TOOL_DEFINITIONS, PORTFOLIO_BRIEF_TOOL)
    return TOOL_DEFINITIONS


_ENGINEERING_EVIDENCE_SQL = """
SELECT
    'development_bom'::text AS entity,
    bom.id AS entity_id,
    bom.code || ' · ' || bom.name || ' · v' || bom.version::text AS label,
    concat(
        'type=', bom.bom_type,
        '; item_count=', count(item.id)::text,
        CASE
            WHEN nullif(btrim(coalesce(bom.notes, '')), '') IS NULL THEN ''
            ELSE '; notes=' || left(bom.notes, 2000)
        END
    ) AS excerpt,
    bom.updated_at AS observed_at
FROM cehub_product.development_boms AS bom
LEFT JOIN cehub_product.development_bom_items AS item
  ON item.tenant_id = bom.tenant_id
 AND item.project_id = bom.project_id
 AND item.bom_id = bom.id
WHERE bom.tenant_id = :tenant_id AND bom.project_id = :project_id
GROUP BY bom.id
UNION ALL
SELECT
    'engineering_change_request'::text AS entity,
    ecr.id AS entity_id,
    ecr.code || ' · ' || ecr.title AS label,
    concat(
        'status=', ecr.status,
        '; affected_bom_count=', count(affected.bom_id)::text,
        '; reason=', left(ecr.reason, 2000)
    ) AS excerpt,
    ecr.updated_at AS observed_at
FROM cehub_product.engineering_change_requests AS ecr
LEFT JOIN cehub_product.ecr_affected_boms AS affected
  ON affected.tenant_id = ecr.tenant_id
 AND affected.project_id = ecr.project_id
 AND affected.ecr_id = ecr.id
WHERE ecr.tenant_id = :tenant_id AND ecr.project_id = :project_id
GROUP BY ecr.id
"""

_QUALITY_EVIDENCE_SQL = """
SELECT
    'test_case'::text AS entity,
    test_case.id AS entity_id,
    test_case.title AS label,
    concat(
        'category=', test_case.category,
        '; severity=', test_case.severity,
        '; status=', test_case.status,
        CASE
            WHEN nullif(btrim(coalesce(test_case.result_notes, '')), '') IS NULL THEN ''
            ELSE '; result=' || left(test_case.result_notes, 2000)
        END
    ) AS excerpt,
    test_case.updated_at AS observed_at
FROM cehub_quality.test_cases AS test_case
WHERE test_case.tenant_id = :tenant_id
  AND test_case.project_id = :project_id
  AND test_case.status IN ('failed', 'blocked')
UNION ALL
SELECT
    'complaint'::text AS entity,
    complaint.id AS entity_id,
    complaint.code || ' · ' || complaint.title AS label,
    concat(
        'severity=', complaint.severity,
        '; status=', complaint.status,
        '; description=', left(complaint.description, 2000),
        CASE
            WHEN nullif(btrim(coalesce(complaint.affected_scope, '')), '') IS NULL THEN ''
            ELSE '; affected_scope=' || left(complaint.affected_scope, 1000)
        END
    ) AS excerpt,
    complaint.updated_at AS observed_at
FROM cehub_quality.complaints AS complaint
WHERE complaint.tenant_id = :tenant_id AND complaint.project_id = :project_id
UNION ALL
SELECT
    'nonconformance_report'::text AS entity,
    ncr.id AS entity_id,
    ncr.code AS label,
    concat(
        'severity=', ncr.severity,
        '; status=', ncr.status,
        '; nonconformity=', left(ncr.nonconformity, 2000),
        '; approved_root_cause=', coalesce(left(root_cause.root_cause, 1500), 'none'),
        '; capa_action_count=', count(action.id)::text
    ) AS excerpt,
    ncr.updated_at AS observed_at
FROM cehub_quality.nonconformance_reports AS ncr
LEFT JOIN cehub_quality.root_cause_analyses AS root_cause
  ON root_cause.tenant_id = ncr.tenant_id
 AND root_cause.project_id = ncr.project_id
 AND root_cause.ncr_id = ncr.id
 AND root_cause.status = 'approved'
LEFT JOIN cehub_quality.capa_actions AS action
  ON action.tenant_id = ncr.tenant_id
 AND action.project_id = ncr.project_id
 AND action.ncr_id = ncr.id
WHERE ncr.tenant_id = :tenant_id AND ncr.project_id = :project_id
GROUP BY ncr.id, root_cause.root_cause
"""

_SUPPLIER_DELAY_EVIDENCE_SQL = """
SELECT
    event.id AS event_row_id,
    event.project_id,
    project.code AS project_code,
    supplier.code AS supplier_code,
    supplier.name AS supplier_name,
    event.payload->>'expected_date' AS expected_date,
    event.payload->>'reported_date' AS reported_date,
    event.timestamp AS observed_at
FROM cehub_event.events AS event
JOIN cehub_project.projects AS project
  ON project.tenant_id = event.tenant_id
 AND project.id = event.project_id
JOIN cehub_supplier.suppliers AS supplier
  ON supplier.tenant_id = event.tenant_id
 AND supplier.id::text = event.payload->>'supplier_id'
WHERE event.tenant_id = :tenant_id
  AND event.event_type = 'SUPPLIER_DELAY_REPORTED'
"""

_PORTFOLIO_BRIEF_SQL = """
SELECT
    project.id AS project_id,
    project.code,
    project.name,
    project.status,
    coalesce(stage.code, 'unassigned') AS stage_code,
    (
        SELECT count(*) FROM cehub_project.issues AS issue
        WHERE issue.tenant_id = project.tenant_id
          AND issue.project_id = project.id
          AND issue.status <> 'closed'
    ) AS open_issue_count,
    (
        SELECT count(*) FROM cehub_project.risks AS risk
        WHERE risk.tenant_id = project.tenant_id
          AND risk.project_id = project.id
          AND risk.status <> 'closed'
    ) AS open_risk_count,
    (
        SELECT count(*) FROM cehub_project.tasks AS task
        WHERE task.tenant_id = project.tenant_id
          AND task.project_id = project.id
          AND task.due_date < CURRENT_DATE
          AND task.status NOT IN ('done', 'skipped')
    ) AS overdue_task_count,
    (
        SELECT count(*) FROM cehub_project.gates AS gate
        WHERE gate.tenant_id = project.tenant_id
          AND gate.project_id = project.id
          AND gate.status IN ('preparing', 'reviewing')
    ) AS pending_gate_count,
    project.updated_at AS observed_at
FROM cehub_project.projects AS project
LEFT JOIN cehub_project.stages AS stage
  ON stage.tenant_id = project.tenant_id
 AND stage.workflow_id = project.workflow_id
 AND stage.id = project.current_stage_id
WHERE project.tenant_id = :tenant_id
  AND project.status IN ('approved', 'active', 'on_hold')
"""


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
        embedding_gateway: EmbeddingGateway | None = None,
    ) -> None:
        self._engine = engine
        self._context = run_context
        self._run_store = run_store
        self._embedding_gateway = embedding_gateway

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

    def recent_events_anchor(self, *, project_id: UUID, through_id: int, limit: int = 20) -> int:
        """Return the after_id that makes get_recent_events page the newest events up to through_id.

        get_recent_events pages forward from after_id; starting at 0 would show the oldest
        Project history and never reach the trigger in a busy Project.
        """
        self._assert_scope(project_id)
        self._validate_page(after_id=through_id, limit=limit)
        with self._engine.connect() as connection:
            if self._run_store is not None and self._run_store.projection_only:
                self._run_store.bind(connection)
                anchor = connection.execute(
                    text(
                        "SELECT id FROM cehub_ai.agent_event_projection WHERE id <= :through_id "
                        "ORDER BY id DESC OFFSET :limit LIMIT 1"
                    ),
                    {"through_id": through_id, "limit": limit},
                ).scalar_one_or_none()
            else:
                anchor = connection.execute(
                    select(tables.events.c.id)
                    .where(
                        tables.events.c.tenant_id == self._context.tenant_id,
                        tables.events.c.project_id == self._context.project_id,
                        tables.events.c.id <= through_id,
                    )
                    .order_by(tables.events.c.id.desc())
                    .offset(limit)
                    .limit(1)
                ).scalar_one_or_none()
        return int(anchor) if anchor is not None else 0

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
        if self._embedding_gateway is None:
            return ToolPage(
                items=(),
                shown_count=0,
                total_count=0,
                truncated=False,
                next_after_id=None,
                continuation="已显示 0 之 0 条；verified memory 数据源尚未启用，无需续读。",
                source_status="not_enabled",
            )
        embedding = self._embedding_gateway.embed(query.strip())
        if (
            embedding.provider != self._embedding_gateway.provider
            or embedding.model != self._embedding_gateway.model
            or embedding.dimensions != self._embedding_gateway.dimensions
            or not embedding.values
        ):
            raise ValueError("memory embedding route changed during search")
        vector = "[" + ",".join(format(value, ".17g") for value in embedding.values) + "]"
        parameters: dict[str, object] = {
            "embedding": vector,
            "provider": embedding.provider,
            "model": embedding.model,
            "dimensions": embedding.dimensions,
            "offset": offset,
            "limit": limit,
        }
        with self._engine.connect() as connection:
            if self._run_store is not None and self._run_store.projection_only:
                self._run_store.bind(connection)
                source = "cehub_ai.agent_memory_projection"
                scope = ""
            else:
                source = (
                    "cehub_memory.memories m JOIN cehub_memory.memory_embeddings e "
                    "ON e.tenant_id = m.tenant_id AND e.project_id = m.project_id "
                    "AND e.memory_id = m.id AND e.content_sha256 = m.content_sha256"
                )
                scope = "m.tenant_id = :tenant_id AND m.project_id = :project_id AND "
                parameters.update(
                    {"tenant_id": self._context.tenant_id, "project_id": self._context.project_id}
                )
            filters = (
                f"{scope}m.status = 'verified' AND EXISTS ("
                "SELECT 1 FROM cehub_memory.memory_source_assessments a "
                "WHERE a.tenant_id=m.tenant_id AND a.memory_id=m.id "
                "AND a.state IN ('current','manual')) AND e.provider = :provider "
                "AND e.model = :model AND e.dimensions = :dimensions"
            )
            if source == "cehub_ai.agent_memory_projection":
                filters = "provider = :provider AND model = :model AND dimensions = :dimensions"
                total_statement = f"SELECT count(*) FROM {source} WHERE {filters}"
                search_statement = (
                    "SELECT memory_id, title, content, applicability, tags, source_refs, "
                    "content_sha256, 1 - (embedding <=> CAST(:embedding AS vector)) AS similarity "
                    f"FROM {source} WHERE {filters} "
                    "ORDER BY embedding <=> CAST(:embedding AS vector), memory_id "
                    "OFFSET :offset LIMIT :limit"
                )
            else:
                total_statement = f"SELECT count(*) FROM {source} WHERE {filters}"
                search_statement = (
                    "SELECT m.id AS memory_id, m.title, m.content, m.applicability, m.tags, "
                    "m.source_refs, m.content_sha256, "
                    "1 - (e.embedding <=> CAST(:embedding AS vector)) AS similarity "
                    f"FROM {source} WHERE {filters} "
                    "ORDER BY e.embedding <=> CAST(:embedding AS vector), m.id "
                    "OFFSET :offset LIMIT :limit"
                )
            total = int(connection.execute(text(total_statement), parameters).scalar_one())
            rows = list(connection.execute(text(search_statement), parameters).mappings())
        items = tuple(
            {
                "memory_id": str(row["memory_id"]),
                "title": str(row["title"]),
                "content": str(row["content"])[:4_000],
                "applicability": row["applicability"],
                "tags": list(row["tags"]),
                "source_refs": list(row["source_refs"]),
                "content_sha256": str(row["content_sha256"]),
                "similarity": float(row["similarity"]),
            }
            for row in rows
        )
        next_offset = offset + len(items) if offset + len(items) < total else None
        return ToolPage(
            items=items,
            shown_count=len(items),
            total_count=total,
            truncated=next_offset is not None,
            next_after_id=next_offset,
            continuation=(
                f"已显示 {offset + len(items)} 之 {total} 条；使用 offset={next_offset} 续读。"
                if next_offset is not None
                else f"已显示 {offset + len(items)} 之 {total} 条；无需续读。"
            ),
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

    def get_engineering_evidence(
        self,
        *,
        project_id: UUID,
        offset: int = 0,
        limit: int = 20,
    ) -> ToolPage:
        return self._domain_evidence(
            project_id=project_id,
            offset=offset,
            limit=limit,
            projection="cehub_ai.agent_engineering_evidence_projection",
            owner_sql=_ENGINEERING_EVIDENCE_SQL,
        )

    def get_quality_evidence(
        self,
        *,
        project_id: UUID,
        offset: int = 0,
        limit: int = 20,
    ) -> ToolPage:
        return self._domain_evidence(
            project_id=project_id,
            offset=offset,
            limit=limit,
            projection="cehub_ai.agent_quality_evidence_projection",
            owner_sql=_QUALITY_EVIDENCE_SQL,
        )

    def get_supplier_delay_evidence(
        self,
        *,
        project_id: UUID,
        offset: int = 0,
        limit: int = 20,
    ) -> ToolPage:
        return self._portfolio_evidence(
            project_id=project_id,
            offset=offset,
            limit=limit,
            projection="cehub_ai.agent_supplier_delay_projection",
            owner_sql=_SUPPLIER_DELAY_EVIDENCE_SQL,
            columns=(
                "event_row_id",
                "project_id",
                "project_code",
                "supplier_code",
                "supplier_name",
                "expected_date",
                "reported_date",
            ),
        )

    def get_portfolio_brief(
        self,
        *,
        project_id: UUID,
        offset: int = 0,
        limit: int = 20,
    ) -> ToolPage:
        return self._portfolio_evidence(
            project_id=project_id,
            offset=offset,
            limit=limit,
            projection="cehub_ai.agent_portfolio_projection",
            owner_sql=_PORTFOLIO_BRIEF_SQL,
            columns=(
                "project_id",
                "code",
                "name",
                "status",
                "stage_code",
                "open_issue_count",
                "open_risk_count",
                "overdue_task_count",
                "pending_gate_count",
            ),
        )

    def _portfolio_evidence(
        self,
        *,
        project_id: UUID,
        offset: int,
        limit: int,
        projection: str,
        owner_sql: str,
        columns: tuple[str, ...],
    ) -> ToolPage:
        self._assert_scope(project_id)
        self._validate_page(after_id=offset, limit=limit)
        parameters: dict[str, object] = {
            "tenant_id": self._context.tenant_id,
            "offset": offset,
            "limit": limit,
        }
        with self._engine.connect() as connection:
            if self._run_store is not None and self._run_store.projection_only:
                self._run_store.bind(connection)
                source = projection
                source_parameters: dict[str, object] = {"offset": offset, "limit": limit}
            else:
                source = f"({owner_sql}) AS evidence"
                source_parameters = parameters
            total = int(
                connection.execute(
                    text(f"SELECT count(*) FROM {source}"), source_parameters
                ).scalar_one()
            )
            rows = list(
                connection.execute(
                    text(
                        f"SELECT {', '.join(columns)} FROM {source} "
                        "ORDER BY observed_at DESC, 1 OFFSET :offset LIMIT :limit"
                    ),
                    source_parameters,
                ).mappings()
            )
        if "event_row_id" in columns:
            items = tuple(
                {
                    "reference_id": f"supplier-delay:{row['event_row_id']}",
                    "entity": "supplier_delay",
                    "entity_id": str(row["project_id"]),
                    "label": (
                        f"{row['project_code']} · {row['supplier_code']} · {row['supplier_name']}"
                    ),
                    "excerpt": (
                        f"expected_date={row['expected_date']}; "
                        f"reported_date={row['reported_date']}"
                    ),
                }
                for row in rows
            )
        else:
            items = tuple(
                {
                    "reference_id": f"portfolio-project:{row['project_id']}",
                    "entity": "project",
                    "entity_id": str(row["project_id"]),
                    "label": f"{row['code']} · {row['name']}",
                    "excerpt": (
                        f"status={row['status']}; stage={row['stage_code']}; "
                        f"open_issues={row['open_issue_count']}; "
                        f"open_risks={row['open_risk_count']}; "
                        f"overdue_tasks={row['overdue_task_count']}; "
                        f"pending_gates={row['pending_gate_count']}"
                    ),
                }
                for row in rows
            )
        next_offset = offset + len(items) if offset + len(items) < total else None
        return ToolPage(
            items=items,
            shown_count=len(items),
            total_count=total,
            truncated=next_offset is not None,
            next_after_id=next_offset,
            continuation=(
                f"已显示 {offset + len(items)} 之 {total} 条；使用 offset={next_offset} 续读。"
                if next_offset is not None
                else f"已显示 {offset + len(items)} 之 {total} 条；无需续读。"
            ),
        )

    def _domain_evidence(
        self,
        *,
        project_id: UUID,
        offset: int,
        limit: int,
        projection: str,
        owner_sql: str,
    ) -> ToolPage:
        self._assert_scope(project_id)
        self._validate_page(after_id=offset, limit=limit)
        parameters = {
            "tenant_id": self._context.tenant_id,
            "project_id": self._context.project_id,
            "offset": offset,
            "limit": limit,
        }
        with self._engine.connect() as connection:
            if self._run_store is not None and self._run_store.projection_only:
                self._run_store.bind(connection)
                source = projection
                source_parameters: dict[str, object] = {"offset": offset, "limit": limit}
            else:
                source = f"({owner_sql}) AS evidence"
                source_parameters = parameters
            total = int(
                connection.execute(
                    text(f"SELECT count(*) FROM {source}"),
                    source_parameters,
                ).scalar_one()
            )
            rows = list(
                connection.execute(
                    text(
                        "SELECT entity, entity_id, label, excerpt, observed_at "
                        f"FROM {source} ORDER BY observed_at DESC, entity, entity_id "
                        "OFFSET :offset LIMIT :limit"
                    ),
                    source_parameters,
                ).mappings()
            )
        items = tuple(
            {
                "reference_id": f"{row['entity']}:{row['entity_id']}",
                "entity": str(row["entity"]),
                "entity_id": str(row["entity_id"]),
                "label": str(row["label"]),
                "excerpt": str(row["excerpt"])[:1_000],
            }
            for row in rows
        )
        next_offset = offset + len(items) if offset + len(items) < total else None
        return ToolPage(
            items=items,
            shown_count=len(items),
            total_count=total,
            truncated=next_offset is not None,
            next_after_id=next_offset,
            continuation=(
                f"已显示 {offset + len(items)} 之 {total} 条；使用 offset={next_offset} 续读。"
                if next_offset is not None
                else f"已显示 {offset + len(items)} 之 {total} 条；无需续读。"
            ),
        )

    def _assert_scope(self, claimed_project_id: UUID) -> None:
        if claimed_project_id != self._context.project_id:
            raise ToolScopeViolationError("tool Project scope does not match the Agent run")
        # Imported here because capability registration owns the tool declarations.
        from app.ai.rollout_guard import require_employee_agent

        require_employee_agent(self._context.agent_key)

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
