"""Human-confirmed retrospective versions with an auditable learning source."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, select

from app.auth.roles import Action
from app.db.schema import tables
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.knowledge_push import KnowledgeVersionError
from app.domain.knowledge_sources import KnowledgeSourceSelection, resolve_selections
from app.domain.meetings import MeetingNotFoundError, MeetingService, MeetingStateError, _snapshot
from app.domain.product_workspace import _plain
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


def _digest(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


class MeetingRetrospectiveService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def history(
        self, *, tenant_id: UUID, project_id: UUID, meeting_id: UUID, actor_id: UUID
    ) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            KnowledgeCorrectionService._authorize(
                connection, tenant_id, actor_id, project_id, Action.MEETING_VIEW
            )
            MeetingService._get(
                connection, tenant_id=tenant_id, project_id=project_id, meeting_id=meeting_id
            )
            rows = connection.execute(
                select(
                    tables.audit_log.c.after_snapshot,
                    tables.audit_log.c.context,
                    tables.audit_log.c.timestamp,
                    tables.users.c.display_name.label("confirmed_by"),
                )
                .join(
                    tables.users,
                    (tables.users.c.tenant_id == tables.audit_log.c.tenant_id)
                    & (tables.users.c.id == tables.audit_log.c.actor_user_id),
                )
                .where(
                    tables.audit_log.c.tenant_id == tenant_id,
                    tables.audit_log.c.project_id == project_id,
                    tables.audit_log.c.entity_id == meeting_id,
                    tables.audit_log.c.action == "meeting.retrospective_confirmed",
                )
                .order_by(tables.audit_log.c.id.desc())
                .limit(100)
            ).mappings()
            return [_plain(row) for row in rows]

    def confirm(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        meeting_id: UUID,
        actor_id: UUID,
        request_id: UUID,
        expected_version: int,
        conclusion: str,
        applicability: str,
        reason: str,
        sources: tuple[KnowledgeSourceSelection, ...],
    ) -> dict[str, Any]:
        conclusion, applicability, reason = (
            conclusion.strip(),
            applicability.strip(),
            reason.strip(),
        )
        if not (
            1 <= len(conclusion) <= 15000
            and 1 <= len(applicability) <= 3000
            and 1 <= len(reason) <= 3000
        ):
            raise MeetingStateError("请填写完整的结论、适用条件和确认理由")
        signature = _digest(
            dict(
                expected_version=expected_version,
                conclusion=conclusion,
                applicability=applicability,
                reason=reason,
                sources=[source.model_dump(mode="json") for source in sources],
            )
        )
        event_id = f"meeting:{meeting_id}:retrospective:{request_id}"
        with self.engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise MeetingNotFoundError
            KnowledgeCorrectionService._authorize(
                connection, tenant_id, actor_id, project_id, Action.MEETING_MANAGE
            )
            before = MeetingService._get(
                connection, tenant_id=tenant_id, project_id=project_id, meeting_id=meeting_id
            )
            receipt = (
                connection.execute(
                    select(tables.audit_log).where(
                        tables.audit_log.c.tenant_id == tenant_id,
                        tables.audit_log.c.event_id == event_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if receipt is not None:
                if (
                    receipt["actor_user_id"] != actor_id
                    or receipt["context"].get("request_digest") != signature
                ):
                    raise KnowledgeVersionError("本次请求标识已用于另一份结论，请重新核对后提交")
                return {
                    "replayed": True,
                    "confirmed_version": receipt["after_snapshot"]["retrospective_version"],
                }
            if before.meeting_type != "project_retrospective" or before.status != "completed":
                raise MeetingStateError("仅已完成的项目复盘可确认结论")
            if before.archived_at is not None or before.deleted_at is not None:
                raise MeetingStateError("会议已归档或删除，不能修订结论")
            if expected_version != before.retrospective_version:
                raise KnowledgeVersionError("复盘结论已被修订，请刷新并核对当前版本")
            refs = resolve_selections(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_id=actor_id,
                selections=sources,
            )
            digest = _digest(dict(conclusion=conclusion, applicability=applicability, sources=refs))
            if digest == before.retrospective_digest:
                raise KnowledgeVersionError("结论、适用条件和依据没有变化，无需创建新版本")
            now = datetime.now(UTC)
            version = before.retrospective_version + 1
            connection.execute(
                tables.meetings.update()
                .where(
                    tables.meetings.c.tenant_id == tenant_id,
                    tables.meetings.c.project_id == project_id,
                    tables.meetings.c.id == meeting_id,
                )
                .values(
                    retrospective_conclusion=conclusion,
                    retrospective_applicability=applicability,
                    retrospective_source_refs=list(refs),
                    retrospective_version=version,
                    retrospective_digest=digest,
                    retrospective_confirmed_by_user_id=actor_id,
                    retrospective_confirmed_at=now,
                    updated_at=now,
                )
            )
            after = MeetingService._get(
                connection, tenant_id=tenant_id, project_id=project_id, meeting_id=meeting_id
            )
            EventAuditWriter(
                connection, tenant_id=tenant_id, project_id=project_id, actor_user_id=actor_id
            ).record(
                EventDraft(
                    event_id=event_id,
                    event_type="MEETING_STATE_CHANGED",
                    source="meeting_service",
                    entity_id=meeting_id,
                    payload={
                        "meeting_id": str(meeting_id),
                        "meeting_type": after.meeting_type,
                        "status": after.status,
                        "action": "retrospective_confirmed",
                    },
                    occurred_at=now,
                ),
                AuditDraft(
                    action="meeting.retrospective_confirmed",
                    before_snapshot=_snapshot(before),
                    after_snapshot=_snapshot(after),
                    context={"request_digest": signature, "reason": reason},
                ),
            )
            return {"replayed": False, "confirmed_version": version}
