"""Human-verified project Memory lifecycle and pgvector retrieval."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, select, text, update
from sqlalchemy.exc import IntegrityError

from app.ai.embeddings import EmbeddingGateway, EmbeddingResult
from app.db.schema import tables
from app.domain.knowledge_categories import (
    KNOWLEDGE_KIND_LABELS,
    KNOWLEDGE_KINDS,
    KnowledgeKind,
    require_knowledge_kind,
)
from app.domain.knowledge_sources import KnowledgeSourceSelection, resolve_selections
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class MemoryNotFoundError(LookupError):
    pass


class MemoryInvalidTransitionError(ValueError):
    pass


class MemoryFourEyesError(ValueError):
    pass


class MemorySourceError(ValueError):
    pass


class MemoryContentConflictError(ValueError):
    pass


@dataclass(frozen=True)
class MemoryDraft:
    title: str
    content: str
    applicability: str | None = None
    tags: tuple[str, ...] = ()
    knowledge_kind: KnowledgeKind | None = None


@dataclass(frozen=True)
class MemoryRecord:
    id: UUID
    tenant_id: UUID
    project_id: UUID
    source_finding_id: UUID | None
    source_ncr_id: UUID | None
    source_issue_id: UUID | None
    created_by_user_id: UUID
    verified_by_user_id: UUID | None
    archived_by_user_id: UUID | None
    title: str
    content: str
    applicability: str | None
    tags: tuple[str, ...]
    source_refs: tuple[dict[str, object], ...]
    content_sha256: str
    status: Literal["draft", "verified", "archived"]
    verified_at: datetime | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    last_edited_by_user_id: UUID | None = None
    knowledge_kind: KnowledgeKind | None = None


@dataclass(frozen=True)
class MemorySearchResult:
    memory: MemoryRecord
    similarity: float
    embedding_provider: str
    embedding_model: str


def memory_content_hash(draft: MemoryDraft) -> str:
    # Preserve legacy digests when classification has never been supplied.
    value: dict[str, object] = {
        "title": draft.title.strip(),
        "content": draft.content.strip(),
        "applicability": draft.applicability.strip() if draft.applicability else None,
        "tags": list(draft.tags),
    }
    if draft.knowledge_kind is not None:
        value["knowledge_kind"] = draft.knowledge_kind
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _embedding_text(record: MemoryRecord) -> str:
    parts = [record.title, record.content]
    if record.knowledge_kind is not None:
        parts.append("Knowledge kind: " + KNOWLEDGE_KIND_LABELS[record.knowledge_kind])
    if record.applicability:
        parts.append(f"Applicability: {record.applicability}")
    if record.tags:
        parts.append("Tags: " + ", ".join(record.tags))
    return "\n\n".join(parts)


def _record(row: RowMapping) -> MemoryRecord:
    return MemoryRecord(
        id=row["id"],
        tenant_id=row["tenant_id"],
        project_id=row["project_id"],
        source_finding_id=row["source_finding_id"],
        source_ncr_id=row["source_ncr_id"],
        source_issue_id=row["source_issue_id"],
        created_by_user_id=row["created_by_user_id"],
        verified_by_user_id=row["verified_by_user_id"],
        archived_by_user_id=row["archived_by_user_id"],
        title=str(row["title"]),
        content=str(row["content"]),
        applicability=row["applicability"],
        tags=tuple(str(value) for value in row["tags"]),
        source_refs=tuple(dict(value) for value in row["source_refs"]),
        content_sha256=str(row["content_sha256"]),
        status=row["status"],
        verified_at=row["verified_at"],
        archived_at=row["archived_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_edited_by_user_id=row.get("last_edited_by_user_id"),
        knowledge_kind=row.get("knowledge_kind"),
    )


def _snapshot(record: MemoryRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "project_id": str(record.project_id),
        "source_finding_id": (str(record.source_finding_id) if record.source_finding_id else None),
        "source_ncr_id": str(record.source_ncr_id) if record.source_ncr_id else None,
        "source_issue_id": str(record.source_issue_id) if record.source_issue_id else None,
        "created_by_user_id": str(record.created_by_user_id),
        "verified_by_user_id": (
            str(record.verified_by_user_id) if record.verified_by_user_id else None
        ),
        "archived_by_user_id": (
            str(record.archived_by_user_id) if record.archived_by_user_id else None
        ),
        "last_edited_by_user_id": str(record.last_edited_by_user_id)
        if record.last_edited_by_user_id
        else None,
        "title": record.title,
        "content": record.content,
        "applicability": record.applicability,
        "tags": list(record.tags),
        "knowledge_kind": record.knowledge_kind,
        "source_refs": list(record.source_refs),
        "content_sha256": record.content_sha256,
        "status": record.status,
        "verified_at": record.verified_at.isoformat() if record.verified_at else None,
        "archived_at": record.archived_at.isoformat() if record.archived_at else None,
    }


def memory_review_digest(record: MemoryRecord) -> str:
    basis = {**_snapshot(record), "updated_at": record.updated_at.isoformat()}
    return hashlib.sha256(
        json.dumps(basis, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


class MemoryService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        status: str | None = None,
    ) -> Sequence[MemoryRecord]:
        statement = select(tables.memories).where(
            tables.memories.c.tenant_id == tenant_id,
            tables.memories.c.project_id == project_id,
        )
        if status is not None:
            statement = statement.where(tables.memories.c.status == status)
        with self._engine.connect() as connection:
            rows = connection.execute(
                statement.order_by(tables.memories.c.updated_at.desc(), tables.memories.c.id)
            ).mappings()
            return [_record(row) for row in rows]

    def get(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        memory_id: UUID,
    ) -> MemoryRecord:
        with self._engine.connect() as connection:
            return self._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                memory_id=memory_id,
            )

    def create(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        draft: MemoryDraft,
        source_finding_id: UUID | None = None,
        source_ncr_id: UUID | None = None,
        source_issue_id: UUID | None = None,
        source_refs: tuple[dict[str, object], ...] = (),
        source_selections: tuple[KnowledgeSourceSelection, ...] = (),
        now: datetime | None = None,
        connection: Connection | None = None,
    ) -> MemoryRecord:
        created_at = (now or datetime.now(UTC)).astimezone(UTC)
        normalized = self._normalized_draft(draft)
        memory_id = uuid4()
        with self._engine.begin() if connection is None else nullcontext(connection) as connection:
            source_refs = (
                *source_refs,
                *resolve_selections(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    actor_id=actor_user_id,
                    selections=source_selections,
                ),
            )
            self._validate_source(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                source_finding_id=source_finding_id,
                source_ncr_id=source_ncr_id,
            )
            try:
                connection.execute(
                    tables.memories.insert(),
                    {
                        "id": memory_id,
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "source_finding_id": source_finding_id,
                        "source_ncr_id": source_ncr_id,
                        "source_issue_id": source_issue_id,
                        "created_by_user_id": actor_user_id,
                        "title": normalized.title,
                        "content": normalized.content,
                        "applicability": normalized.applicability,
                        "tags": list(normalized.tags),
                        "knowledge_kind": normalized.knowledge_kind,
                        "source_refs": list(source_refs),
                        "content_sha256": memory_content_hash(normalized),
                        "status": "draft",
                        "created_at": created_at,
                        "updated_at": created_at,
                    },
                )
            except IntegrityError as error:
                raise MemorySourceError from error
            record = self._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                memory_id=memory_id,
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"memory:{memory_id}:draft-created",
                    event_type="MEMORY_DRAFT_CREATED",
                    source="memory_service",
                    entity_id=memory_id,
                    payload={
                        "memory_id": str(memory_id),
                        "source_type": (
                            "finding"
                            if source_finding_id
                            else "ncr"
                            if source_ncr_id
                            else "issue"
                            if source_issue_id
                            else "business_record"
                            if any(ref.get("kind") == "event" for ref in source_refs)
                            else "manual"
                        ),
                    },
                    occurred_at=created_at,
                ),
                AuditDraft(action="memory.create", after_snapshot=_snapshot(record)),
            )
            return record

    def create_from_ncr(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        ncr_id: UUID,
        draft: MemoryDraft,
        now: datetime | None = None,
    ) -> MemoryRecord:
        return self.create(
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=actor_user_id,
            draft=draft,
            source_ncr_id=ncr_id,
            source_refs=({"kind": "ncr", "reference": str(ncr_id)},),
            now=now,
        )

    def edit(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        memory_id: UUID,
        draft: MemoryDraft,
        expected_review_digest: str | None = None,
        source_selections: tuple[KnowledgeSourceSelection, ...] | None = None,
        now: datetime | None = None,
    ) -> MemoryRecord:
        updated_at = (now or datetime.now(UTC)).astimezone(UTC)
        normalized = self._normalized_draft(draft)
        with self._engine.begin() as connection:
            before = self._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                memory_id=memory_id,
                for_update=True,
            )
            if before.status != "draft":
                raise MemoryInvalidTransitionError
            if (
                expected_review_digest is not None
                and memory_review_digest(before) != expected_review_digest
            ):
                raise MemoryContentConflictError
            refs = list(before.source_refs)
            if source_selections is not None:
                if expected_review_digest is None or not source_selections:
                    raise MemoryContentConflictError
                refs = [
                    ref
                    for ref in refs
                    if ref.get("kind") not in {"document", "specification", "evidence_snapshot"}
                ]
                refs.extend(
                    resolve_selections(
                        connection,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        actor_id=actor_user_id,
                        selections=source_selections,
                    )
                )
            connection.execute(
                update(tables.memories)
                .where(
                    tables.memories.c.tenant_id == tenant_id,
                    tables.memories.c.project_id == project_id,
                    tables.memories.c.id == memory_id,
                    tables.memories.c.status == "draft",
                )
                .values(
                    last_edited_by_user_id=actor_user_id,
                    source_refs=refs,
                    title=normalized.title,
                    content=normalized.content,
                    applicability=normalized.applicability,
                    tags=list(normalized.tags),
                    knowledge_kind=normalized.knowledge_kind,
                    content_sha256=memory_content_hash(normalized),
                    updated_at=updated_at,
                )
            )
            after = self._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                memory_id=memory_id,
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"memory:{memory_id}:draft-updated:{memory_review_digest(after)}",
                    event_type="MEMORY_DRAFT_UPDATED",
                    source="memory_service",
                    entity_id=memory_id,
                    payload={"memory_id": str(memory_id), "content_sha256": after.content_sha256},
                    occurred_at=updated_at,
                ),
                AuditDraft(
                    action="memory.update",
                    before_snapshot=_snapshot(before),
                    after_snapshot=_snapshot(after),
                ),
            )
            return after

    def verify(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        memory_id: UUID,
        gateway: EmbeddingGateway,
        expected_review_digest: str | None = None,
        now: datetime | None = None,
    ) -> MemoryRecord:
        candidate = self.get(
            tenant_id=tenant_id,
            project_id=project_id,
            memory_id=memory_id,
        )
        if candidate.status != "draft":
            raise MemoryInvalidTransitionError
        if actor_user_id in {candidate.created_by_user_id, candidate.last_edited_by_user_id}:
            raise MemoryFourEyesError
        if (
            expected_review_digest is not None
            and memory_review_digest(candidate) != expected_review_digest
        ):
            raise MemoryContentConflictError
        require_knowledge_kind(candidate.knowledge_kind)
        with self._engine.connect() as connection:
            self._require_source_basis(connection, tenant_id, memory_id)
        embedding = gateway.embed(_embedding_text(candidate))
        self._validate_embedding_route(gateway, embedding)
        verified_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.begin() as connection:
            before = self._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                memory_id=memory_id,
                for_update=True,
            )
            if before.status != "draft":
                raise MemoryInvalidTransitionError
            if actor_user_id in {before.created_by_user_id, before.last_edited_by_user_id}:
                raise MemoryFourEyesError
            if memory_review_digest(before) != memory_review_digest(candidate):
                raise MemoryContentConflictError
            self._require_source_basis(connection, tenant_id, memory_id)
            self._insert_embedding(
                connection,
                memory=before,
                actor_user_id=actor_user_id,
                embedding=embedding,
                created_at=verified_at,
            )
            connection.execute(
                update(tables.memories)
                .where(
                    tables.memories.c.tenant_id == tenant_id,
                    tables.memories.c.project_id == project_id,
                    tables.memories.c.id == memory_id,
                    tables.memories.c.status == "draft",
                    tables.memories.c.content_sha256 == candidate.content_sha256,
                )
                .values(
                    status="verified",
                    verified_by_user_id=actor_user_id,
                    verified_at=verified_at,
                    updated_at=verified_at,
                )
            )
            after = self._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                memory_id=memory_id,
            )
            writer = EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            )
            writer.record(
                EventDraft(
                    event_id=f"memory:{memory_id}:verified",
                    event_type="MEMORY_VERIFIED",
                    source="memory_service",
                    entity_id=memory_id,
                    payload={"memory_id": str(memory_id), "content_sha256": after.content_sha256},
                    occurred_at=verified_at,
                ),
                AuditDraft(
                    action="memory.verify",
                    before_snapshot=_snapshot(before),
                    after_snapshot=_snapshot(after),
                ),
            )
            self._record_embedding_event(
                writer,
                memory=after,
                embedding=embedding,
                occurred_at=verified_at,
            )
            return after

    def archive(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        memory_id: UUID,
        now: datetime | None = None,
    ) -> MemoryRecord:
        archived_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.begin() as connection:
            before = self._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                memory_id=memory_id,
                for_update=True,
            )
            if before.status != "verified":
                raise MemoryInvalidTransitionError
            connection.execute(
                update(tables.memories)
                .where(
                    tables.memories.c.tenant_id == tenant_id,
                    tables.memories.c.project_id == project_id,
                    tables.memories.c.id == memory_id,
                    tables.memories.c.status == "verified",
                )
                .values(
                    status="archived",
                    archived_by_user_id=actor_user_id,
                    archived_at=archived_at,
                    updated_at=archived_at,
                )
            )
            after = self._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                memory_id=memory_id,
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"memory:{memory_id}:archived",
                    event_type="MEMORY_ARCHIVED",
                    source="memory_service",
                    entity_id=memory_id,
                    payload={"memory_id": str(memory_id), "content_sha256": after.content_sha256},
                    occurred_at=archived_at,
                ),
                AuditDraft(
                    action="memory.archive",
                    before_snapshot=_snapshot(before),
                    after_snapshot=_snapshot(after),
                ),
            )
            return after

    def reembed(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        memory_id: UUID,
        gateway: EmbeddingGateway,
        now: datetime | None = None,
    ) -> MemoryRecord:
        candidate = self.get(
            tenant_id=tenant_id,
            project_id=project_id,
            memory_id=memory_id,
        )
        if candidate.status != "verified":
            raise MemoryInvalidTransitionError
        embedding = gateway.embed(_embedding_text(candidate))
        self._validate_embedding_route(gateway, embedding)
        embedded_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.begin() as connection:
            current = self._get(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                memory_id=memory_id,
                for_update=True,
            )
            if current.status != "verified":
                raise MemoryInvalidTransitionError
            if current.content_sha256 != candidate.content_sha256:
                raise MemoryContentConflictError
            self._insert_embedding(
                connection,
                memory=current,
                actor_user_id=actor_user_id,
                embedding=embedding,
                created_at=embedded_at,
            )
            self._record_embedding_event(
                EventAuditWriter(
                    connection,
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    project_id=project_id,
                ),
                memory=current,
                embedding=embedding,
                occurred_at=embedded_at,
            )
            return current

    def search(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        query: str,
        gateway: EmbeddingGateway,
        limit: int = 10,
        knowledge_kind: str | None = None,
    ) -> Sequence[MemorySearchResult]:
        normalized = query.strip()
        if not normalized or len(normalized) > 500 or not 1 <= limit <= 20:
            raise ValueError("memory search parameters invalid")
        if knowledge_kind is not None and knowledge_kind not in KNOWLEDGE_KINDS | {"unclassified"}:
            raise ValueError("unknown knowledge classification")
        embedding = gateway.embed(normalized)
        self._validate_embedding_route(gateway, embedding)
        vector = self._vector_literal(embedding.values)
        statement = text(
            "SELECT m.*, 1 - (e.embedding <=> CAST(:embedding AS vector)) AS similarity "
            "FROM cehub_memory.memories m "
            "JOIN cehub_memory.memory_embeddings e "
            "ON e.tenant_id = m.tenant_id AND e.project_id = m.project_id "
            "AND e.memory_id = m.id AND e.content_sha256 = m.content_sha256 "
            "WHERE m.tenant_id = :tenant_id AND m.project_id = :project_id "
            "AND m.status = 'verified' AND EXISTS ("
            "SELECT 1 FROM cehub_memory.memory_source_assessments a "
            "WHERE a.tenant_id=m.tenant_id AND a.memory_id=m.id "
            "AND a.state IN ('current','manual')) "
            "AND (CAST(:knowledge_kind AS varchar) IS NULL OR m.knowledge_kind=:knowledge_kind "
            "OR (:knowledge_kind='unclassified' AND m.knowledge_kind IS NULL)) "
            "AND e.provider = :provider "
            "AND e.model = :model AND e.dimensions = :dimensions "
            "ORDER BY e.embedding <=> CAST(:embedding AS vector), m.id LIMIT :limit"
        )
        with self._engine.connect() as connection:
            rows = connection.execute(
                statement,
                {
                    "embedding": vector,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "provider": embedding.provider,
                    "model": embedding.model,
                    "dimensions": embedding.dimensions,
                    "limit": limit,
                    "knowledge_kind": knowledge_kind,
                },
            ).mappings()
            return [
                MemorySearchResult(
                    memory=_record(row),
                    similarity=float(row["similarity"]),
                    embedding_provider=embedding.provider,
                    embedding_model=embedding.model,
                )
                for row in rows
            ]

    @staticmethod
    def _require_source_basis(connection: Connection, tenant_id: UUID, memory_id: UUID) -> None:
        bad = connection.execute(
            text(
                "SELECT EXISTS(SELECT 1 FROM cehub_memory.memory_source_assessments a, "
                "LATERAL jsonb_array_elements(a.sources) source "
                "WHERE a.tenant_id=:tenant AND a.memory_id=:memory "
                "AND source->>'state' IN ('stale','unavailable','needs_review'))"
            ),
            {"tenant": tenant_id, "memory": memory_id},
        ).scalar_one()
        if bad:
            raise MemorySourceError

    @staticmethod
    def _normalized_draft(draft: MemoryDraft) -> MemoryDraft:
        title = draft.title.strip()
        content = draft.content.strip()
        applicability = draft.applicability.strip() if draft.applicability else None
        tags = tuple(dict.fromkeys(tag.strip() for tag in draft.tags if tag.strip()))
        if draft.knowledge_kind is not None:
            require_knowledge_kind(draft.knowledge_kind)
            tags = tuple(tag for tag in tags if tag != "classification_pending")
        if not title or len(title) > 512 or not content or len(content) > 20_000:
            raise ValueError("memory draft invalid")
        if applicability and len(applicability) > 5_000:
            raise ValueError("memory draft invalid")
        if len(tags) > 50 or any(len(tag) > 64 for tag in tags):
            raise ValueError("memory draft invalid")
        return MemoryDraft(
            title=title,
            content=content,
            applicability=applicability,
            tags=tags,
            knowledge_kind=draft.knowledge_kind,
        )

    @staticmethod
    def _validate_source(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        source_finding_id: UUID | None,
        source_ncr_id: UUID | None,
    ) -> None:
        if source_finding_id and source_ncr_id:
            raise MemorySourceError
        if source_finding_id:
            finding = connection.execute(
                select(tables.findings.c.status, tables.findings.c.finding_type).where(
                    tables.findings.c.tenant_id == tenant_id,
                    tables.findings.c.project_id == project_id,
                    tables.findings.c.id == source_finding_id,
                )
            ).one_or_none()
            if (
                finding is None
                or finding.status != "accepted"
                or finding.finding_type != "knowledge_draft"
            ):
                raise MemorySourceError
        if source_ncr_id:
            ncr_status = connection.execute(
                select(tables.nonconformance_reports.c.status).where(
                    tables.nonconformance_reports.c.tenant_id == tenant_id,
                    tables.nonconformance_reports.c.project_id == project_id,
                    tables.nonconformance_reports.c.id == source_ncr_id,
                )
            ).scalar_one_or_none()
            if ncr_status != "closed":
                raise MemorySourceError

    @staticmethod
    def _validate_embedding_route(
        gateway: EmbeddingGateway,
        result: EmbeddingResult,
    ) -> None:
        if (
            result.provider != gateway.provider
            or result.model != gateway.model
            or result.dimensions != gateway.dimensions
            or not result.values
        ):
            raise MemoryContentConflictError

    @staticmethod
    def _insert_embedding(
        connection: Connection,
        *,
        memory: MemoryRecord,
        actor_user_id: UUID,
        embedding: EmbeddingResult,
        created_at: datetime,
    ) -> None:
        exists = connection.execute(
            select(tables.memory_embeddings.c.id).where(
                tables.memory_embeddings.c.tenant_id == memory.tenant_id,
                tables.memory_embeddings.c.memory_id == memory.id,
                tables.memory_embeddings.c.provider == embedding.provider,
                tables.memory_embeddings.c.model == embedding.model,
                tables.memory_embeddings.c.dimensions == embedding.dimensions,
                tables.memory_embeddings.c.content_sha256 == memory.content_sha256,
            )
        ).scalar_one_or_none()
        if exists is None:
            connection.execute(
                tables.memory_embeddings.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": memory.tenant_id,
                    "project_id": memory.project_id,
                    "memory_id": memory.id,
                    "created_by_user_id": actor_user_id,
                    "provider": embedding.provider,
                    "model": embedding.model,
                    "dimensions": embedding.dimensions,
                    "content_sha256": memory.content_sha256,
                    "embedding": [value for value in embedding.values],
                    "created_at": created_at,
                },
            )

    @staticmethod
    def _record_embedding_event(
        writer: EventAuditWriter,
        *,
        memory: MemoryRecord,
        embedding: EmbeddingResult,
        occurred_at: datetime,
    ) -> None:
        route_key = hashlib.sha256(
            f"{embedding.provider}\0{embedding.model}\0{embedding.dimensions}".encode()
        ).hexdigest()[:16]
        embedding_key = hashlib.sha256(
            f"{memory.content_sha256}\0{route_key}".encode()
        ).hexdigest()[:24]
        writer.record(
            EventDraft(
                event_id=f"memory:{memory.id}:embedded:{embedding_key}",
                event_type="MEMORY_EMBEDDED",
                source="memory_service",
                entity_id=memory.id,
                payload={
                    "memory_id": str(memory.id),
                    "provider": embedding.provider,
                    "model": embedding.model,
                    "dimensions": embedding.dimensions,
                    "content_sha256": memory.content_sha256,
                },
                occurred_at=occurred_at,
            ),
            AuditDraft(
                action="memory.embed",
                after_snapshot={
                    "memory_id": str(memory.id),
                    "provider": embedding.provider,
                    "model": embedding.model,
                    "dimensions": embedding.dimensions,
                    "content_sha256": memory.content_sha256,
                },
            ),
        )

    @staticmethod
    def _vector_literal(values: tuple[float, ...]) -> str:
        return "[" + ",".join(format(value, ".17g") for value in values) + "]"

    @staticmethod
    def _get(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        memory_id: UUID,
        for_update: bool = False,
    ) -> MemoryRecord:
        statement = select(tables.memories).where(
            tables.memories.c.tenant_id == tenant_id,
            tables.memories.c.project_id == project_id,
            tables.memories.c.id == memory_id,
        )
        if for_update:
            statement = statement.with_for_update()
        row = connection.execute(statement).mappings().one_or_none()
        if row is None:
            raise MemoryNotFoundError
        return _record(row)
