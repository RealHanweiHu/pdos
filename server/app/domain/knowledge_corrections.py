"""Human-authored knowledge corrections with versioned review and replacement."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select, update

from app.ai.embeddings import EmbeddingGateway
from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain.knowledge_categories import KNOWLEDGE_KIND_LABELS, require_knowledge_kind
from app.domain.knowledge_push import (
    KnowledgeAccessError,
    KnowledgeVersionError,
    authorize_knowledge_project,
    knowledge_scope,
)
from app.domain.knowledge_sources import KnowledgeSourceSelection, resolve_selections
from app.domain.memories import MemoryDraft, MemoryService, _record, _snapshot, memory_content_hash
from app.domain.product_workspace import _plain
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class KnowledgeCorrectionService:
    def __init__(self, engine: Engine):
        self.engine = engine

    @staticmethod
    def _authorize(
        connection: Connection, tenant_id: UUID, actor_id: UUID, project_id: UUID, action: Action
    ) -> None:
        unrestricted, principals = knowledge_scope(connection, tenant_id, actor_id)
        authorize_knowledge_project(connection, tenant_id, project_id, unrestricted, principals)
        role = connection.execute(
            select(tables.users.c.role).where(
                tables.users.c.tenant_id == tenant_id,
                tables.users.c.id == actor_id,
                tables.users.c.is_active.is_(True),
            )
        ).scalar_one_or_none()
        if role is None or not is_allowed(Role(role), action):
            raise KnowledgeAccessError("当前角色没有此项操作权限")

    def list(self, *, tenant_id: UUID, actor_id: UUID, project_id: UUID) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            self._authorize(connection, tenant_id, actor_id, project_id, Action.MEMORY_VIEW)
            rows = connection.execute(
                select(
                    tables.knowledge_corrections,
                    tables.memories.c.status.label("source_current_status"),
                    tables.memories.c.content_sha256.label("source_current_sha256"),
                )
                .join(
                    tables.memories,
                    (tables.memories.c.tenant_id == tables.knowledge_corrections.c.tenant_id)
                    & (tables.memories.c.id == tables.knowledge_corrections.c.source_memory_id),
                )
                .where(
                    tables.knowledge_corrections.c.tenant_id == tenant_id,
                    tables.knowledge_corrections.c.project_id == project_id,
                )
                .order_by(tables.knowledge_corrections.c.created_at.desc())
            ).mappings()
            return [_plain(row) for row in rows]

    def propose(
        self,
        *,
        tenant_id: UUID,
        actor_id: UUID,
        project_id: UUID,
        memory_id: UUID,
        request_id: UUID,
        expected_content_sha256: str,
        draft: MemoryDraft,
        reason: str,
        source_selections: tuple[KnowledgeSourceSelection, ...] | None = None,
    ) -> dict[str, Any]:
        normalized = MemoryService._normalized_draft(draft)
        require_knowledge_kind(normalized.knowledge_kind)
        proposal = dict(
            title=normalized.title,
            content=normalized.content,
            applicability=normalized.applicability,
            tags=list(normalized.tags),
            knowledge_kind=normalized.knowledge_kind,
        )
        proposal_hash = memory_content_hash(normalized)
        if not reason.strip() or len(reason.strip()) > 5000:
            raise KnowledgeVersionError("请填写修正理由")
        choices = (
            [item.model_dump(mode="json") for item in source_selections]
            if source_selections is not None
            else None
        )
        if choices == []:
            raise KnowledgeVersionError("重新选择来源时至少提供一个当前依据")
        with self.engine.begin() as connection:
            self._authorize(connection, tenant_id, actor_id, project_id, Action.MEMORY_DRAFT)
            # Serialize retries and all proposals/publications for the same source.
            source = (
                connection.execute(
                    select(tables.memories)
                    .where(
                        tables.memories.c.tenant_id == tenant_id,
                        tables.memories.c.project_id == project_id,
                        tables.memories.c.id == memory_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if source is None:
                raise KnowledgeAccessError("知识不存在或不能访问")
            previous = (
                connection.execute(
                    select(tables.knowledge_corrections).where(
                        tables.knowledge_corrections.c.tenant_id == tenant_id,
                        tables.knowledge_corrections.c.id == request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if previous is not None:
                if (
                    previous["project_id"],
                    previous["source_memory_id"],
                    previous["proposer_user_id"],
                    previous["source_content_sha256"],
                    previous["proposal_sha256"],
                    previous["reason"],
                    previous["source_selections"],
                ) != (
                    project_id,
                    memory_id,
                    actor_id,
                    expected_content_sha256,
                    proposal_hash,
                    reason.strip(),
                    choices,
                ):
                    raise KnowledgeVersionError("请求已用于其他修正，请重新打开表单")
                return _plain(previous)
            if (
                source["status"] != "verified"
                or source["content_sha256"] != expected_content_sha256
            ):
                raise KnowledgeVersionError("原经验已变化，请刷新后提出修正")
            refs = (
                resolve_selections(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    actor_id=actor_id,
                    selections=source_selections,
                )
                if source_selections is not None
                else None
            )
            if proposal_hash == expected_content_sha256 and (
                refs is None or refs == source["source_refs"]
            ):
                raise KnowledgeVersionError("修正内容或适用依据须与原经验不同")
            row = dict(
                source_selections=choices,
                proposed_source_refs=refs,
                id=request_id,
                tenant_id=tenant_id,
                project_id=project_id,
                source_memory_id=memory_id,
                proposer_user_id=actor_id,
                source_content_sha256=expected_content_sha256,
                source_snapshot=_snapshot(_record(source)),
                proposal=proposal,
                proposal_sha256=proposal_hash,
                reason=reason.strip(),
                status="pending",
                replacement_memory_id=None,
                reviewed_by_user_id=None,
                review_reason=None,
                reviewed_at=None,
                created_at=datetime.now(UTC),
            )
            connection.execute(tables.knowledge_corrections.insert(), row)
            result = _plain(row)
            self._event(
                connection,
                tenant_id,
                actor_id,
                project_id,
                request_id,
                "KNOWLEDGE_CORRECTION_PROPOSED",
                "pending",
                result,
            )
            return result

    def _review_basis(
        self,
        connection: Connection,
        tenant_id: UUID,
        actor_id: UUID,
        project_id: UUID,
        correction_id: UUID,
        expected_proposal_sha256: str,
        action: str,
        reason: str,
        *,
        lock: bool,
    ) -> tuple[Any, Any]:
        self._authorize(connection, tenant_id, actor_id, project_id, Action.MEMORY_VERIFY)
        statement = select(tables.knowledge_corrections).where(
            tables.knowledge_corrections.c.tenant_id == tenant_id,
            tables.knowledge_corrections.c.project_id == project_id,
            tables.knowledge_corrections.c.id == correction_id,
        )
        candidate = connection.execute(statement).mappings().one_or_none()
        if candidate is None:
            raise KnowledgeAccessError("修正候选不存在或不能访问")
        source_query = select(tables.memories).where(
            tables.memories.c.tenant_id == tenant_id,
            tables.memories.c.project_id == project_id,
            tables.memories.c.id == candidate["source_memory_id"],
        )
        source = (
            connection.execute(source_query.with_for_update() if lock else source_query)
            .mappings()
            .one()
        )
        # Lock source first in every mutation, then refresh the candidate.
        candidate = (
            connection.execute(statement.with_for_update() if lock else statement).mappings().one()
        )
        if candidate["proposer_user_id"] == actor_id:
            raise KnowledgeAccessError("修正须由另一位有权限的成员审核")
        if candidate["proposal_sha256"] != expected_proposal_sha256:
            raise KnowledgeVersionError("候选版本不一致，请刷新")
        if candidate["status"] != "pending":
            if (
                candidate["status"],
                candidate["reviewed_by_user_id"],
                candidate["review_reason"],
            ) != ("published" if action == "publish" else "rejected", actor_id, reason.strip()):
                raise KnowledgeVersionError("此修正已处理，请刷新查看原回执")
            return candidate, source
        if action == "publish":
            require_knowledge_kind(candidate["proposal"].get("knowledge_kind"))
        if action == "publish" and (
            source["status"] != "verified"
            or source["content_sha256"] != candidate["source_content_sha256"]
        ):
            raise KnowledgeVersionError(
                "原经验已归档或被替代；可退回此候选，并基于当前版本重新修正"
            )
        if action == "publish" and candidate["source_selections"] is not None:
            refs = resolve_selections(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_id=actor_id,
                selections=tuple(
                    KnowledgeSourceSelection.model_validate(item)
                    for item in candidate["source_selections"]
                ),
            )
            if refs != candidate["proposed_source_refs"]:
                raise KnowledgeVersionError("候选依据已变化，请基于当前版本重新提出修正")
        return candidate, source

    def review(
        self,
        *,
        tenant_id: UUID,
        actor_id: UUID,
        project_id: UUID,
        correction_id: UUID,
        expected_proposal_sha256: str,
        action: str,
        reason: str,
        gateway: EmbeddingGateway | None = None,
    ) -> dict[str, Any]:
        if action not in {"publish", "reject"} or not 1 <= len(reason.strip()) <= 5000:
            raise KnowledgeVersionError("请选择处理方式并填写审核理由")
        with self.engine.connect() as connection:
            candidate, _ = self._review_basis(
                connection,
                tenant_id,
                actor_id,
                project_id,
                correction_id,
                expected_proposal_sha256,
                action,
                reason,
                lock=False,
            )
            if candidate["status"] != "pending":
                return _plain(candidate)
        embedding = None
        if action == "publish":
            if gateway is None:
                raise KnowledgeVersionError("知识检索服务暂不可用，修正尚未发布")
            proposal = candidate["proposal"]
            parts = [
                proposal["title"],
                proposal["content"],
                "Knowledge kind: " + KNOWLEDGE_KIND_LABELS[proposal["knowledge_kind"]],
            ]
            if proposal["applicability"]:
                parts.append(f"Applicability: {proposal['applicability']}")
            if proposal["tags"]:
                parts.append("Tags: " + ", ".join(proposal["tags"]))
            embedding = gateway.embed("\n\n".join(parts))
            MemoryService._validate_embedding_route(gateway, embedding)
        with self.engine.begin() as connection:
            candidate, source = self._review_basis(
                connection,
                tenant_id,
                actor_id,
                project_id,
                correction_id,
                expected_proposal_sha256,
                action,
                reason,
                lock=True,
            )
            if candidate["status"] != "pending":
                return _plain(candidate)
            now = datetime.now(UTC)
            replacement_id = None
            writer = EventAuditWriter(
                connection, tenant_id=tenant_id, actor_user_id=actor_id, project_id=project_id
            )
            if action == "publish":
                assert embedding is not None
                replacement_id = uuid4()
                values = dict(
                    id=replacement_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    source_finding_id=None,
                    source_ncr_id=None,
                    source_issue_id=None,
                    created_by_user_id=candidate["proposer_user_id"],
                    verified_by_user_id=actor_id,
                    archived_by_user_id=None,
                    **candidate["proposal"],
                    source_refs=[
                        *(
                            candidate["proposed_source_refs"]
                            if candidate["proposed_source_refs"] is not None
                            else source["source_refs"]
                        ),
                        {
                            "kind": "memory_correction",
                            "reference": str(source["id"]),
                            "content_sha256": source["content_sha256"],
                            "correction_id": str(correction_id),
                        },
                    ],
                    content_sha256=candidate["proposal_sha256"],
                    status="verified",
                    verified_at=now,
                    archived_at=None,
                    created_at=now,
                    updated_at=now,
                )
                connection.execute(tables.memories.insert(), values)
                fresh = _record(
                    connection.execute(
                        select(tables.memories).where(
                            tables.memories.c.tenant_id == tenant_id,
                            tables.memories.c.id == replacement_id,
                        )
                    )
                    .mappings()
                    .one()
                )
                MemoryService._insert_embedding(
                    connection,
                    memory=fresh,
                    actor_user_id=actor_id,
                    embedding=embedding,
                    created_at=now,
                )
                connection.execute(
                    update(tables.memories)
                    .where(
                        tables.memories.c.tenant_id == tenant_id,
                        tables.memories.c.id == source["id"],
                    )
                    .values(
                        status="archived",
                        archived_by_user_id=actor_id,
                        archived_at=now,
                        updated_at=now,
                    )
                )
                old_snapshot = {
                    **_snapshot(_record(source)),
                    "status": "archived",
                    "archived_by_user_id": str(actor_id),
                    "archived_at": now.isoformat(),
                }
                for record, event_type, snapshot in (
                    (fresh, "MEMORY_VERIFIED", _snapshot(fresh)),
                    (_record(source), "MEMORY_ARCHIVED", old_snapshot),
                ):
                    writer.record(
                        EventDraft(
                            event_id=f"memory:{record.id}:{event_type.lower()}",
                            event_type=event_type,
                            source="memory_service",
                            entity_id=record.id,
                            payload={
                                "memory_id": str(record.id),
                                "content_sha256": record.content_sha256,
                            },
                            occurred_at=now,
                        ),
                        AuditDraft(
                            action="memory.correction_publish",
                            before_snapshot=_snapshot(_record(source))
                            if event_type == "MEMORY_ARCHIVED"
                            else None,
                            after_snapshot=snapshot,
                        ),
                    )
                MemoryService._record_embedding_event(
                    writer, memory=fresh, embedding=embedding, occurred_at=now
                )
            changes = dict(
                status="published" if action == "publish" else "rejected",
                replacement_memory_id=replacement_id,
                reviewed_by_user_id=actor_id,
                review_reason=reason.strip(),
                reviewed_at=now,
            )
            connection.execute(
                update(tables.knowledge_corrections)
                .where(
                    tables.knowledge_corrections.c.tenant_id == tenant_id,
                    tables.knowledge_corrections.c.id == correction_id,
                )
                .values(**changes)
            )
            if replacement_id is not None:
                MemoryService._require_source_basis(connection, tenant_id, replacement_id)
            result = _plain({**candidate, **changes})
            self._event(
                connection,
                tenant_id,
                actor_id,
                project_id,
                correction_id,
                "KNOWLEDGE_CORRECTION_REVIEWED",
                "published" if action == "publish" else "rejected",
                result,
            )
            return result

    @staticmethod
    def _event(
        connection: Connection,
        tenant_id: UUID,
        actor_id: UUID,
        project_id: UUID,
        correction_id: UUID,
        event_type: str,
        status: str,
        snapshot: dict[str, Any],
    ) -> None:
        EventAuditWriter(
            connection, tenant_id=tenant_id, actor_user_id=actor_id, project_id=project_id
        ).record(
            EventDraft(
                event_id=f"knowledge-correction:{correction_id}:{status}",
                event_type=event_type,
                source="knowledge_correction_service",
                entity_id=correction_id,
                payload={"correction_id": str(correction_id), "status": status},
            ),
            AuditDraft(action="knowledge.correction", after_snapshot=snapshot),
        )
