"""Proactive knowledge push at the moments it pays off (vNext V1-B9, axis 10).

Search only helps the person who already suspects an answer exists. The value
of organizational memory shows up when nobody thought to look: starting a new
project, raising a change, choosing a part. This retrieves verified memories
**across projects** at exactly those moments and records what was surfaced, so
the hit rate is measured rather than assumed.

Boundaries that keep this honest:
- **Verified only.** Drafts never get pushed; an unreviewed note presented as
  organizational knowledge is worse than silence.
- **Cross-project, membership-scoped.** The point is learning from other
  projects, but a non-admin only ever sees memories from projects they belong
  to. Tenant isolation is absolute.
- **De-noised.** A similarity floor, a small cap, and a per-context uniqueness
  rule so the same suggestion is not re-surfaced after someone skipped it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, Row, func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from app.ai.embeddings import EmbeddingGateway
from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain.memories import MemoryRecord, MemoryService, _record
from app.domain.organization import active_delegated_principals
from app.domain.product_workspace import _plain
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

CONTEXT_KINDS = ("project_kickoff", "change_request", "part_selection", "task_takeover")

# Below this the neighbour is noise dressed as a recommendation.
MIN_SIMILARITY = 0.30
MAX_PUSHES = 5


class KnowledgeAccessError(PermissionError):
    pass


class KnowledgeVersionError(ValueError):
    pass


def knowledge_scope(
    connection: Connection, tenant_id: UUID, actor_user_id: UUID
) -> tuple[bool, tuple[UUID, ...]]:
    user = (
        connection.execute(
            select(tables.users).where(
                tables.users.c.tenant_id == tenant_id,
                tables.users.c.id == actor_user_id,
                tables.users.c.is_active.is_(True),
            )
        )
        .mappings()
        .one_or_none()
    )
    if user is None or not is_allowed(Role(user["role"]), Action.MEMORY_VIEW):
        raise KnowledgeAccessError("当前不能查看知识")
    return user["role"] in {"owner", "admin"}, (
        actor_user_id,
        *active_delegated_principals(
            connection, tenant_id=tenant_id, delegate_user_id=actor_user_id
        ),
    )


def authorize_knowledge_project(
    connection: Connection,
    tenant_id: UUID,
    project_id: UUID,
    unrestricted: bool,
    principals: tuple[UUID, ...],
) -> None:
    if (
        not unrestricted
        and connection.execute(
            select(tables.project_members.c.id).where(
                tables.project_members.c.tenant_id == tenant_id,
                tables.project_members.c.project_id == project_id,
                tables.project_members.c.user_id.in_(principals),
            )
        ).first()
        is None
    ):
        raise KnowledgeAccessError("知识来源或使用项目的权限已变化")


class UnknownContextError(ValueError):
    """Raised for a context kind outside the closed list."""


class ContextNotFoundError(LookupError):
    """Raised when the triggering object does not exist in the project."""


class PushNotFoundError(LookupError):
    """Raised when engaging a push that is absent from the tenant."""


@dataclass(frozen=True)
class PushedMemory:
    push_id: UUID
    memory: MemoryRecord
    similarity: float
    rank: int
    source_project_id: UUID
    already_seen: bool
    feedback: dict[str, Any] | None = None


@dataclass(frozen=True)
class PushMetrics:
    pushed_count: int
    engaged_count: int
    hit_rate_basis_points: int | None
    by_context: dict[str, dict[str, int]]


def _query_for_context(kind: str, row: Row[Any]) -> str:
    """Build the retrieval query deterministically from the triggering object."""
    if kind == "project_kickoff":
        return " ".join(part for part in (row.name, row.description) if part)
    if kind == "change_request":
        return " ".join(part for part in (row.title, row.reason) if part)
    if kind == "task_takeover":
        return " ".join(part for part in (row.title, row.description, row.expected_output) if part)
    return " ".join(part for part in (row.title, row.acceptance_criteria) if part)


class KnowledgePushService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._memories = MemoryService(engine)

    def push_for_context(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        context_kind: str,
        context_entity_id: UUID,
        gateway: EmbeddingGateway,
        member_scoped: bool,
        now: datetime | None = None,
        expected_context_sha256: str | None = None,
    ) -> tuple[PushedMemory, ...]:
        if context_kind not in CONTEXT_KINDS:
            raise UnknownContextError(context_kind)
        pushed_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.connect() as connection:
            unrestricted, principals = knowledge_scope(connection, tenant_id, actor_user_id)
            authorize_knowledge_project(connection, tenant_id, project_id, unrestricted, principals)
        query = self._context_query(
            tenant_id=tenant_id,
            project_id=project_id,
            context_kind=context_kind,
            context_entity_id=context_entity_id,
        )
        if not query.strip():
            return ()
        context_sha256 = sha256(query.encode()).hexdigest()
        if expected_context_sha256 is not None and context_sha256 != expected_context_sha256:
            raise KnowledgeVersionError("业务内容已变化，停止使用原触发请求")

        embedding = gateway.embed(query[:500])
        MemoryService._validate_embedding_route(gateway, embedding)
        vector = MemoryService._vector_literal(embedding.values)

        # The current database role and effective delegations determine scope.
        # The legacy member_scoped argument cannot widen source visibility.
        statement = text(
            "SELECT m.*, 1 - (e.embedding <=> CAST(:embedding AS vector)) AS similarity "
            "FROM cehub_memory.memories m "
            "JOIN cehub_memory.memory_embeddings e "
            "ON e.tenant_id = m.tenant_id AND e.project_id = m.project_id "
            "AND e.memory_id = m.id AND e.content_sha256 = m.content_sha256 "
            "WHERE m.tenant_id = :tenant_id AND m.status = 'verified' "
            "AND EXISTS (SELECT 1 FROM cehub_memory.memory_source_assessments a "
            "WHERE a.tenant_id=m.tenant_id AND a.memory_id=m.id "
            "AND a.state IN ('current','manual')) "
            "AND e.provider = :provider AND e.model = :model "
            "AND e.dimensions = :dimensions "
            # Explicit casts keep boolean and UUID-array bind types unambiguous.
            "AND (CAST(:unrestricted AS boolean) OR EXISTS ("
            "  SELECT 1 FROM cehub_project.project_members pm "
            "  WHERE pm.tenant_id = m.tenant_id AND pm.project_id = m.project_id "
            "  AND pm.user_id = ANY(CAST(:principal_ids AS uuid[])))) "
            "AND NOT EXISTS (SELECT 1 FROM cehub_memory.knowledge_pushes p "
            " JOIN cehub_memory.knowledge_push_feedback f "
            " ON f.tenant_id=p.tenant_id AND f.push_id=p.id "
            " WHERE p.tenant_id=m.tenant_id AND p.memory_id=m.id "
            " AND p.context_kind=:context_kind AND p.context_entity_id=:context_entity_id "
            " AND p.context_sha256=:context_sha256 AND f.actor_user_id=:actor_user_id "
            " AND f.action='not_useful') "
            "AND 1 - (e.embedding <=> CAST(:embedding AS vector)) >= :floor "
            "ORDER BY e.embedding <=> CAST(:embedding AS vector), m.id LIMIT :limit"
        )
        with self._engine.begin() as connection:
            unrestricted, principals = knowledge_scope(connection, tenant_id, actor_user_id)
            authorize_knowledge_project(connection, tenant_id, project_id, unrestricted, principals)
            if query != self._context_query(
                tenant_id=tenant_id,
                project_id=project_id,
                context_kind=context_kind,
                context_entity_id=context_entity_id,
                connection=connection,
            ):
                raise KnowledgeVersionError("业务内容已变化，请重新查找相关经验")
            rows = (
                connection.execute(
                    statement,
                    {
                        "embedding": vector,
                        "tenant_id": tenant_id,
                        "provider": embedding.provider,
                        "model": embedding.model,
                        "dimensions": embedding.dimensions,
                        "unrestricted": unrestricted,
                        "principal_ids": list(principals),
                        "floor": MIN_SIMILARITY,
                        "context_kind": context_kind,
                        "context_entity_id": context_entity_id,
                        "context_sha256": context_sha256,
                        "actor_user_id": actor_user_id,
                        "limit": MAX_PUSHES,
                    },
                )
                .mappings()
                .all()
            )
            seen = {
                row.memory_id: row.id
                for row in connection.execute(
                    select(
                        tables.knowledge_pushes.c.id,
                        tables.knowledge_pushes.c.memory_id,
                    ).where(
                        tables.knowledge_pushes.c.tenant_id == tenant_id,
                        tables.knowledge_pushes.c.context_sha256 == context_sha256,
                        tables.knowledge_pushes.c.context_kind == context_kind,
                        tables.knowledge_pushes.c.context_entity_id == context_entity_id,
                    )
                )
            }
            feedback = {
                row["push_id"]: _plain(row)
                for row in connection.execute(
                    select(tables.knowledge_push_feedback).where(
                        tables.knowledge_push_feedback.c.tenant_id == tenant_id,
                        tables.knowledge_push_feedback.c.actor_user_id == actor_user_id,
                        tables.knowledge_push_feedback.c.push_id.in_(seen.values()),
                    )
                ).mappings()
            }
            pushed: list[PushedMemory] = []
            for rank, row in enumerate(rows, start=1):
                memory = _record(row)
                similarity = float(row["similarity"])
                existing_push_id = seen.get(memory.id)
                push_id = existing_push_id or uuid4()
                if existing_push_id is None:
                    connection.execute(
                        insert(tables.knowledge_pushes).on_conflict_do_nothing(
                            constraint="uq_knowledge_pushes_context_memory"
                        ),
                        {
                            "id": push_id,
                            "tenant_id": tenant_id,
                            "project_id": project_id,
                            "memory_id": memory.id,
                            "context_sha256": context_sha256,
                            "context_kind": context_kind,
                            "context_entity_id": context_entity_id,
                            "rank": rank,
                            "similarity_basis_points": round(
                                max(-1.0, min(1.0, similarity)) * 10_000
                            ),
                            "pushed_at": pushed_at,
                        },
                    )
                if existing_push_id is None:
                    push_id = connection.execute(
                        select(tables.knowledge_pushes.c.id).where(
                            tables.knowledge_pushes.c.tenant_id == tenant_id,
                            tables.knowledge_pushes.c.context_sha256 == context_sha256,
                            tables.knowledge_pushes.c.context_kind == context_kind,
                            tables.knowledge_pushes.c.context_entity_id == context_entity_id,
                            tables.knowledge_pushes.c.memory_id == memory.id,
                        )
                    ).scalar_one()
                pushed.append(
                    PushedMemory(
                        push_id=push_id,
                        memory=memory,
                        similarity=similarity,
                        rank=rank,
                        source_project_id=memory.project_id,
                        already_seen=existing_push_id is not None,
                        feedback=feedback.get(push_id),
                    )
                )
            return tuple(pushed)

    def engage(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        push_id: UUID,
        now: datetime | None = None,
    ) -> None:
        """Record that a pushed memory was actually opened (the citation count)."""
        engaged_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.begin() as connection:
            self._authorized_push(connection, tenant_id, actor_user_id, push_id)
            result = connection.execute(
                update(tables.knowledge_pushes)
                .where(
                    tables.knowledge_pushes.c.tenant_id == tenant_id,
                    tables.knowledge_pushes.c.id == push_id,
                    # First engagement wins; re-opening must not inflate the count.
                    tables.knowledge_pushes.c.engaged_at.is_(None),
                )
                .values(engaged_at=engaged_at, engaged_by_user_id=actor_user_id)
            )
            if result.rowcount:
                return
            exists = connection.execute(
                select(tables.knowledge_pushes.c.id).where(
                    tables.knowledge_pushes.c.tenant_id == tenant_id,
                    tables.knowledge_pushes.c.id == push_id,
                )
            ).scalar_one_or_none()
            if exists is None:
                raise PushNotFoundError

    def _authorized_push(
        self,
        connection: Connection,
        tenant_id: UUID,
        actor_user_id: UUID,
        push_id: UUID,
        *,
        lock: bool = True,
    ) -> tuple[Any, Any]:
        unrestricted, principals = knowledge_scope(connection, tenant_id, actor_user_id)
        push_query = select(tables.knowledge_pushes).where(
            tables.knowledge_pushes.c.tenant_id == tenant_id,
            tables.knowledge_pushes.c.id == push_id,
        )
        push = (
            connection.execute(push_query.with_for_update() if lock else push_query)
            .mappings()
            .one_or_none()
        )
        if push is None:
            raise PushNotFoundError
        memory_query = select(tables.memories).where(
            tables.memories.c.tenant_id == tenant_id,
            tables.memories.c.id == push["memory_id"],
        )
        memory = (
            connection.execute(memory_query.with_for_update() if lock else memory_query)
            .mappings()
            .one()
        )
        for project_id in (push["project_id"], memory["project_id"]):
            authorize_knowledge_project(connection, tenant_id, project_id, unrestricted, principals)
        if memory["status"] != "verified":
            raise KnowledgeVersionError("经验已归档，不能再作为当前依据采用")
        source_state = connection.execute(
            text(
                "SELECT state FROM cehub_memory.memory_source_assessments "
                "WHERE tenant_id=:tenant AND memory_id=:memory"
            ),
            {"tenant": tenant_id, "memory": memory["id"]},
        ).scalar_one()
        if source_state not in {"current", "manual"}:
            raise KnowledgeVersionError("知识来源已失效或需要版本复核，暂不能作为当前依据")
        query = self._context_query(
            tenant_id=tenant_id,
            project_id=push["project_id"],
            context_kind=push["context_kind"],
            context_entity_id=push["context_entity_id"],
            connection=connection,
        )
        if (
            not push["context_sha256"]
            or sha256(query.encode()).hexdigest() != push["context_sha256"]
        ):
            raise KnowledgeVersionError("业务内容已变化或旧推荐缺少版本依据，请重新查找相关经验")
        return push, memory

    def record_feedback(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        push_id: UUID,
        action: str,
        reason: str,
        expected_content_sha256: str,
    ) -> dict[str, Any]:
        if action not in {"adopted", "not_useful"} or not 1 <= len(reason.strip()) <= 5000:
            raise ValueError("请填写采用位置或不适用原因")
        with self._engine.begin() as connection:
            push, memory = self._authorized_push(connection, tenant_id, actor_user_id, push_id)
            previous = (
                connection.execute(
                    select(tables.knowledge_push_feedback).where(
                        tables.knowledge_push_feedback.c.tenant_id == tenant_id,
                        tables.knowledge_push_feedback.c.push_id == push_id,
                        tables.knowledge_push_feedback.c.actor_user_id == actor_user_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if previous is not None:
                if (previous["action"], previous["reason"], previous["memory_content_sha256"]) != (
                    action,
                    reason.strip(),
                    expected_content_sha256,
                ):
                    raise KnowledgeVersionError("本次使用反馈已记录，请刷新查看原记录")
                return _plain(previous)
            if memory["content_sha256"] != expected_content_sha256:
                raise KnowledgeVersionError("知识版本已变化，请刷新后重新确认")
            created_at = datetime.now(UTC)
            receipt = dict(
                id=uuid4(),
                tenant_id=tenant_id,
                push_id=push_id,
                actor_user_id=actor_user_id,
                action=action,
                reason=reason.strip(),
                memory_content_sha256=expected_content_sha256,
                created_at=created_at,
            )
            connection.execute(tables.knowledge_push_feedback.insert(), receipt)
            snapshot = _plain(receipt)
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=push["project_id"],
            ).record(
                EventDraft(
                    event_id=f"knowledge-use:{receipt['id']}",
                    event_type="KNOWLEDGE_USE_RECORDED",
                    source="knowledge_push_service",
                    entity_id=push_id,
                    payload={
                        "push_id": str(push_id),
                        "feedback_id": str(receipt["id"]),
                        "action": action,
                    },
                    occurred_at=created_at,
                ),
                AuditDraft(action="knowledge.use", after_snapshot=snapshot),
            )
            return snapshot

    def metrics(self, *, tenant_id: UUID) -> PushMetrics:
        engaged_flag = tables.knowledge_pushes.c.engaged_at.is_not(None)
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(
                    tables.knowledge_pushes.c.context_kind,
                    func.count().label("pushed"),
                    func.count().filter(engaged_flag).label("engaged"),
                )
                .where(tables.knowledge_pushes.c.tenant_id == tenant_id)
                .group_by(tables.knowledge_pushes.c.context_kind)
            ).all()
        by_context = {
            row.context_kind: {"pushed": int(row.pushed), "engaged": int(row.engaged)}
            for row in rows
        }
        pushed = sum(entry["pushed"] for entry in by_context.values())
        engaged = sum(entry["engaged"] for entry in by_context.values())
        return PushMetrics(
            pushed_count=pushed,
            engaged_count=engaged,
            hit_rate_basis_points=(round(engaged / pushed * 10_000) if pushed else None),
            by_context=by_context,
        )

    def _context_query(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        context_kind: str,
        context_entity_id: UUID,
        connection: Connection | None = None,
    ) -> str:
        sources = {
            "project_kickoff": (
                select(tables.projects.c.name, tables.projects.c.description).where(
                    tables.projects.c.tenant_id == tenant_id,
                    tables.projects.c.id == context_entity_id,
                    tables.projects.c.id == project_id,
                )
            ),
            "change_request": (
                select(
                    tables.engineering_change_requests.c.title,
                    tables.engineering_change_requests.c.reason,
                ).where(
                    tables.engineering_change_requests.c.tenant_id == tenant_id,
                    tables.engineering_change_requests.c.project_id == project_id,
                    tables.engineering_change_requests.c.id == context_entity_id,
                )
            ),
            "task_takeover": select(
                tables.tasks.c.title, tables.tasks.c.description, tables.tasks.c.expected_output
            ).where(
                tables.tasks.c.tenant_id == tenant_id,
                tables.tasks.c.project_id == project_id,
                tables.tasks.c.id == context_entity_id,
            ),
            "part_selection": (
                select(
                    tables.specifications.c.title,
                    tables.specifications.c.acceptance_criteria,
                ).where(
                    tables.specifications.c.tenant_id == tenant_id,
                    tables.specifications.c.project_id == project_id,
                    tables.specifications.c.id == context_entity_id,
                )
            ),
        }
        if connection is not None:
            row = connection.execute(sources[context_kind]).one_or_none()
        else:
            with self._engine.connect() as own_connection:
                row = own_connection.execute(sources[context_kind]).one_or_none()
        if row is None:
            raise ContextNotFoundError
        return _query_for_context(context_kind, row)
