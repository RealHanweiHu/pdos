"""Citable transcript reads and explicit human speaker attribution."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, select

from app.auth.roles import Action
from app.db.schema import tables
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.knowledge_push import KnowledgeVersionError
from app.domain.meeting_preparation import MeetingPreparationService
from app.domain.meetings import MeetingNotFoundError, MeetingService, MeetingStateError
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope


def transcript_snapshot(
    connection: Connection, tenant_id: UUID, meeting_id: UUID, transcript_id: UUID
) -> dict[str, Any]:
    transcript = (
        connection.execute(
            select(tables.meeting_transcripts).where(
                tables.meeting_transcripts.c.tenant_id == tenant_id,
                tables.meeting_transcripts.c.meeting_id == meeting_id,
                tables.meeting_transcripts.c.id == transcript_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if transcript is None:
        raise MeetingNotFoundError
    segments = [
        dict(row)
        for row in connection.execute(
            select(tables.meeting_transcript_segments)
            .where(
                tables.meeting_transcript_segments.c.tenant_id == tenant_id,
                tables.meeting_transcript_segments.c.transcript_id == transcript_id,
            )
            .order_by(tables.meeting_transcript_segments.c.sequence)
        ).mappings()
    ]
    original = transcript["original_content"]
    offset = 0
    complete = original is not None and bool(segments)
    for segment in segments:
        start = original.find(segment["content"], offset) if original is not None else -1
        complete = complete and start >= 0
        offset = start + len(segment["content"]) if start >= 0 else offset
    source = {
        key: value
        for key, value in dict(transcript).items()
        if key not in {"original_content", "storage_key", "speaker_labeled"}
    }
    return _plain(
        {
            "transcript": source,
            "content": original,
            "segments": segments,
            "source_complete": complete,
            "superseded": transcript["superseded_at"] is not None,
            "digest": digest(
                _plain(
                    {
                        "transcript": source,
                        "segments": segments,
                        "original_available": original is not None,
                    }
                )
            ),
        }
    )


class MeetingTranscriptService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        meeting_id: UUID,
        transcript_id: UUID,
        actor_id: UUID,
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
            snapshot = transcript_snapshot(connection, tenant_id, meeting_id, transcript_id)
            history = [
                dict(row)
                for row in connection.execute(
                    select(
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
                        tables.audit_log.c.action == "meeting.transcript_speakers_confirmed",
                        tables.audit_log.c.context["transcript_id"].as_string()
                        == str(transcript_id),
                    )
                    .order_by(tables.audit_log.c.id.desc())
                    .limit(20)
                ).mappings()
            ]
            return _plain(
                {
                    **snapshot,
                    "editable": not meeting.archived_at
                    and not meeting.deleted_at
                    and not snapshot["superseded"]
                    and snapshot["source_complete"],
                    "members": MeetingPreparationService.members(connection, tenant_id, project_id),
                    "history": history,
                }
            )

    def attribute(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        meeting_id: UUID,
        transcript_id: UUID,
        actor_id: UUID,
        request_id: UUID,
        expected_digest: str,
        reason: str,
        bindings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not reason.strip() or len(reason) > 3000 or not bindings or len(bindings) > 1000:
            raise MeetingStateError("请明确需要校正的发言片段及核对依据")
        signature = digest(
            _plain(
                {
                    "expected_digest": expected_digest,
                    "reason": reason.strip(),
                    "bindings": bindings,
                    "transcript_id": transcript_id,
                }
            )
        )
        with self.engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise MeetingNotFoundError
            KnowledgeCorrectionService._authorize(
                connection, tenant_id, actor_id, project_id, Action.MEETING_TRANSCRIPT_UPLOAD
            )
            meeting = MeetingService._get(
                connection, tenant_id=tenant_id, project_id=project_id, meeting_id=meeting_id
            )
            event_id = f"meeting:{meeting_id}:attribution:{request_id}"
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
            if receipt:
                if (
                    receipt["actor_user_id"] != actor_id
                    or receipt["context"].get("request_digest") != signature
                ):
                    raise KnowledgeVersionError("本请求已用于其他说话人校正")
                return dict(receipt["context"]["result"])
            snapshot = transcript_snapshot(connection, tenant_id, meeting_id, transcript_id)
            if meeting.archived_at or meeting.deleted_at or snapshot["superseded"]:
                raise MeetingStateError("本会议或转写稿已只读")
            if not snapshot["source_complete"]:
                raise MeetingStateError("原文或引用片段尚不完整，请先补齐原始转写")
            if snapshot["digest"] != expected_digest:
                raise KnowledgeVersionError("转写或说话人校正已变化，请刷新后重新核对")
            current = {segment["id"]: segment for segment in snapshot["segments"]}
            seen: set[str] = set()
            before = []
            after = []
            for binding in bindings:
                key = str(binding["segment_id"])
                label = (binding.get("speaker_label") or "").strip() or None
                user_id = binding.get("speaker_user_id")
                if key in seen or key not in current or (label is not None and len(label) > 128):
                    raise MeetingStateError("请核对片段、标签长度及重复的校正记录")
                if user_id is not None and label is None:
                    raise MeetingStateError("具名归属须保留已核对的说话人标签；不确定时保持未绑定")
                seen.add(key)
                old = current[key]
                value = {
                    "segment_id": key,
                    "speaker_label": label,
                    "speaker_user_id": str(user_id) if user_id else None,
                }
                original = {
                    "segment_id": key,
                    "speaker_label": old["speaker_label"],
                    "speaker_user_id": old["speaker_user_id"],
                }
                if value != original:
                    before.append(original)
                    after.append(value)
            if not after:
                raise MeetingStateError("说话人信息没有变化")
            MeetingService._require_project_members(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                user_ids=[
                    UUID(item["speaker_user_id"]) for item in after if item["speaker_user_id"]
                ],
            )
            for item in after:
                connection.execute(
                    tables.meeting_transcript_segments.update()
                    .where(
                        tables.meeting_transcript_segments.c.tenant_id == tenant_id,
                        tables.meeting_transcript_segments.c.transcript_id == transcript_id,
                        tables.meeting_transcript_segments.c.id == UUID(item["segment_id"]),
                    )
                    .values(
                        speaker_label=item["speaker_label"],
                        speaker_user_id=UUID(item["speaker_user_id"])
                        if item["speaker_user_id"]
                        else None,
                    )
                )
            updated = transcript_snapshot(connection, tenant_id, meeting_id, transcript_id)
            connection.execute(
                tables.meeting_transcripts.update()
                .where(
                    tables.meeting_transcripts.c.tenant_id == tenant_id,
                    tables.meeting_transcripts.c.id == transcript_id,
                )
                .values(
                    speaker_labeled=any(
                        item["speaker_label"] is not None for item in updated["segments"]
                    )
                )
            )
            result = {
                "transcript_id": str(transcript_id),
                "digest": updated["digest"],
                "changed_segments": len(after),
            }
            MeetingService._emit(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_id,
                record=meeting,
                before=meeting,
                action="transcript_speakers_confirmed",
                occurred_at=datetime.now(UTC),
                event_id=event_id,
                audit_context={
                    "transcript_id": str(transcript_id),
                    "request_digest": signature,
                    "basis_digest": expected_digest,
                    "reason": reason.strip(),
                    "before_bindings": before,
                    "after_bindings": after,
                    "result": result,
                },
            )
            return result
