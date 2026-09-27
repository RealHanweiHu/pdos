"""Human-authored official minutes with immutable versions and transcript citations."""

from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, func, select

from app.auth.roles import Action
from app.db.schema import tables
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.knowledge_push import KnowledgeVersionError
from app.domain.meeting_transcripts import transcript_snapshot
from app.domain.meetings import MeetingNotFoundError, MeetingService, MeetingStateError
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope


class MeetingMinutesService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        meeting_id: UUID,
        actor_id: UUID,
        before_version: int | None = None,
        record_id: UUID | None = None,
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(
                isolation_level="REPEATABLE READ"
            ) as connection,
            connection.begin(),
        ):
            KnowledgeCorrectionService._authorize(
                connection, tenant_id, actor_id, project_id, Action.MEETING_VIEW
            )
            meeting = MeetingService._get(
                connection, tenant_id=tenant_id, project_id=project_id, meeting_id=meeting_id
            )
            if record_id is not None and before_version is not None:
                raise MeetingStateError("指定纪要版本不能同时使用历史分页")
            query = (
                select(
                    tables.meeting_minutes_versions,
                    tables.users.c.display_name.label("confirmed_by"),
                )
                .join(
                    tables.users,
                    (tables.users.c.tenant_id == tables.meeting_minutes_versions.c.tenant_id)
                    & (tables.users.c.id == tables.meeting_minutes_versions.c.confirmed_by_user_id),
                )
                .where(
                    tables.meeting_minutes_versions.c.tenant_id == tenant_id,
                    tables.meeting_minutes_versions.c.meeting_id == meeting_id,
                    tables.meeting_minutes_versions.c.project_id == project_id,
                )
            )
            if before_version is not None:
                query = query.where(tables.meeting_minutes_versions.c.version_no < before_version)
            if record_id is not None:
                query = query.where(tables.meeting_minutes_versions.c.id == record_id)
            fetched = (
                connection.execute(
                    query.order_by(tables.meeting_minutes_versions.c.version_no.desc()).limit(21)
                )
                .mappings()
                .all()
            )
            rows = fetched[:20]
            if record_id is not None and not rows:
                raise MeetingNotFoundError
            current_version = (
                connection.execute(
                    select(func.max(tables.meeting_minutes_versions.c.version_no)).where(
                        tables.meeting_minutes_versions.c.tenant_id == tenant_id,
                        tables.meeting_minutes_versions.c.meeting_id == meeting_id,
                    )
                ).scalar_one()
                or 0
            )
            sources = [
                dict(row)
                for row in connection.execute(
                    select(
                        tables.meeting_transcripts.c.id,
                        tables.meeting_transcripts.c.source,
                        tables.meeting_transcripts.c.uploaded_at,
                        tables.meeting_transcripts.c.segment_count,
                        tables.meeting_transcripts.c.superseded_at,
                    )
                    .where(
                        tables.meeting_transcripts.c.tenant_id == tenant_id,
                        tables.meeting_transcripts.c.meeting_id == meeting_id,
                    )
                    .order_by(tables.meeting_transcripts.c.uploaded_at.desc())
                ).mappings()
            ]
            current_sources: dict[str, str | None] = {}
            items = []
            for row in rows:
                for citation in row["citations"]:
                    key = citation["transcript_id"]
                    if key not in current_sources:
                        try:
                            snapshot = transcript_snapshot(
                                connection, tenant_id, meeting_id, UUID(key)
                            )
                            current_sources[key] = (
                                snapshot["digest"]
                                if snapshot["source_complete"] and not snapshot["superseded"]
                                else None
                            )
                        except MeetingNotFoundError:
                            current_sources[key] = None
                items.append(
                    {
                        **dict(row),
                        "source_current": all(
                            current_sources[citation["transcript_id"]] == citation["source_digest"]
                            for citation in row["citations"]
                        ),
                    }
                )
            return _plain(
                {
                    "current_version": current_version,
                    "next_before": rows[-1]["version_no"] if len(fetched) > 20 else None,
                    "items": items,
                    "sources": sources,
                    "editable": meeting.status == "completed"
                    and not meeting.archived_at
                    and not meeting.deleted_at,
                }
            )

    def confirm(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        meeting_id: UUID,
        actor_id: UUID,
        request_id: UUID,
        expected_version: int,
        body: str,
        unresolved_points: str,
        reason: str,
        citations: list[dict[str, Any]],
        connection: Connection | None = None,
        source_finding_id: UUID | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        body, unresolved_points, reason = body.strip(), unresolved_points.strip(), reason.strip()
        if not (
            1 <= len(body) <= 20000
            and 1 <= len(unresolved_points) <= 5000
            and 1 <= len(reason) <= 3000
            and 1 <= len(citations) <= 100
        ):
            raise MeetingStateError("请填写纪要正文、未决事项、确认依据及1至100处原文引用")
        signature = digest(
            _plain(
                {
                    "meeting_id": meeting_id,
                    "expected_version": expected_version,
                    "body": body,
                    "unresolved_points": unresolved_points,
                    "reason": reason,
                    "citations": citations,
                    **({"source_finding_id": source_finding_id} if source_finding_id else {}),
                }
            )
        )
        with (
            nullcontext(connection) if connection is not None else self.engine.begin()
        ) as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise MeetingNotFoundError
            KnowledgeCorrectionService._authorize(
                connection, tenant_id, actor_id, project_id, Action.MEETING_MANAGE
            )
            meeting = MeetingService._get(
                connection, tenant_id=tenant_id, project_id=project_id, meeting_id=meeting_id
            )
            receipt = (
                connection.execute(
                    select(tables.meeting_minutes_versions).where(
                        tables.meeting_minutes_versions.c.tenant_id == tenant_id,
                        tables.meeting_minutes_versions.c.confirmed_by_user_id == actor_id,
                        tables.meeting_minutes_versions.c.request_id == request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if receipt is not None:
                if receipt["request_digest"] != signature or receipt["meeting_id"] != meeting_id:
                    raise KnowledgeVersionError("本请求已用于其他纪要确认")
                return {"id": str(receipt["id"]), "version": receipt["version_no"], "reused": True}
            if meeting.status != "completed" or meeting.archived_at or meeting.deleted_at:
                raise MeetingStateError("请在会议已结束且未归档时确认正式纪要")
            previous = (
                connection.execute(
                    select(tables.meeting_minutes_versions)
                    .where(
                        tables.meeting_minutes_versions.c.tenant_id == tenant_id,
                        tables.meeting_minutes_versions.c.meeting_id == meeting_id,
                    )
                    .order_by(tables.meeting_minutes_versions.c.version_no.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            version = previous["version_no"] if previous else 0
            if version != expected_version:
                raise KnowledgeVersionError("已有新版正式纪要，请刷新后基于新版修订")
            snapshots: dict[UUID, dict[str, Any]] = {}
            seen: set[tuple[UUID, str]] = set()
            stored = []
            for citation in citations:
                transcript_id, segment_id = citation["transcript_id"], citation["segment_id"]
                quote = citation["exact_quote"]
                if (segment_id, quote) in seen or not quote.strip() or len(quote) > 2000:
                    raise MeetingStateError("请核对原句引用长度及重复片段")
                seen.add((segment_id, quote))
                if transcript_id not in snapshots:
                    snapshots[transcript_id] = transcript_snapshot(
                        connection, tenant_id, meeting_id, transcript_id
                    )
                snapshot = snapshots[transcript_id]
                if (
                    snapshot["digest"] != citation["expected_digest"]
                    or not snapshot["source_complete"]
                    or snapshot["superseded"]
                ):
                    raise KnowledgeVersionError("引用转写或说话人已变化，请先逐项复核原句")
                segment = next(
                    (item for item in snapshot["segments"] if item["id"] == str(segment_id)), None
                )
                if segment is None or quote not in segment["content"]:
                    raise MeetingStateError("引用必须来自本次会议所选转写中的原句片段")
                stored.append(
                    {
                        "transcript_id": str(transcript_id),
                        "segment_id": str(segment_id),
                        "source_digest": snapshot["digest"],
                        "content_digest": snapshot["transcript"]["content_digest"],
                        "sequence": segment["sequence"],
                        "exact_quote": quote,
                        "speaker_label": segment["speaker_label"],
                        "speaker_user_id": segment["speaker_user_id"],
                    }
                )
            document_digest = digest(
                {"body": body, "unresolved_points": unresolved_points, "citations": stored}
            )
            if previous is not None and previous["document_digest"] == document_digest:
                raise MeetingStateError("纪要正文、未决事项和引用均未变化，无需重复确认新版")
            minutes_id, now = uuid4(), now or datetime.now(UTC)
            connection.execute(
                tables.meeting_minutes_versions.insert().values(
                    id=minutes_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    meeting_id=meeting_id,
                    version_no=version + 1,
                    previous_version_id=previous["id"] if previous else None,
                    source_finding_id=source_finding_id,
                    body=body,
                    unresolved_points=unresolved_points,
                    citations=stored,
                    document_digest=document_digest,
                    confirmed_by_user_id=actor_id,
                    confirmed_at=now,
                    reason=reason,
                    request_id=request_id,
                    request_digest=signature,
                )
            )
            MeetingService._emit(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_id,
                record=meeting,
                before=meeting,
                action="minutes_confirmed",
                occurred_at=now,
                event_id=f"meeting-minutes:{minutes_id}:confirmed",
                audit_context={
                    "minutes_id": str(minutes_id),
                    "version": version + 1,
                    "previous_version_id": str(previous["id"]) if previous else None,
                    "document_digest": document_digest,
                    "reason": reason,
                    "origin": "finding_applied" if source_finding_id else "human_authored",
                    "source_finding_id": str(source_finding_id) if source_finding_id else None,
                    "request_id": str(request_id),
                },
            )
            return {"id": str(minutes_id), "version": version + 1, "reused": False}
