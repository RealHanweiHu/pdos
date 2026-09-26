"""Meeting, agenda and transcript contract (vNext V2-1, D6/D35).

Everything downstream in V2 — 会前例外装配, Minutes 提案, 会后闭环 — hangs off
these objects, so this layer settles three things the later slices assume:

* **Authorization has an anchor.** A meeting is always project-scoped, because
  project membership is the only reach check this system has. "未授权会议不可
  接入" is enforced here, not by trusting the caller's provider payload.
* **An external conference is bound as a unit.** Provider, conference id, join
  URL, who bound it and when move together or not at all; a half-bound row is
  exactly how an unvetted link gets in front of participants.
* **A transcript is content-addressed.** Re-uploading identical bytes is a
  no-op rather than a second transcript, so the citations V2-5 produces keep
  pointing at one stable spoken record.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, select

from app.db.schema import tables
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

# `MeetingService.list` shadows the builtin inside the class body, so
# annotations there use this alias.
MeetingList = list

MEETING_TYPES = frozenset(
    {
        "weekly",
        "material",
        "special",
        "technical_review",
        "decision_checkpoint",
        "pilot_review",
        "project_retrospective",
    }
)
# Conference products only. A chat thread is not a meeting: it has no roster to
# check membership against, which is the whole point of 私聊不可接入.
EXTERNAL_PROVIDERS = frozenset({"dingtalk", "tencent_meeting"})
ACTIVE_STATUSES = frozenset({"scheduled", "in_progress"})


class MeetingNotFoundError(LookupError):
    """Raised when the meeting is absent from the project."""


class MeetingScopeError(ValueError):
    """Raised when a referenced user or agenda source is out of scope."""


class MeetingStateError(ValueError):
    """Raised when the requested change does not fit the meeting's state."""


class MeetingLinkError(ValueError):
    """Raised when an external conference cannot be bound to the meeting."""


@dataclass(frozen=True)
class MeetingRecord:
    id: UUID
    project_id: UUID
    meeting_type: str
    title: str
    status: str
    scheduled_start_at: datetime
    scheduled_end_at: datetime
    actual_start_at: datetime | None
    actual_end_at: datetime | None
    organizer_user_id: UUID
    source: str
    external_provider: str | None
    external_meeting_id: str | None
    external_join_url: str | None
    retention_policy: str
    archived_at: datetime | None
    deleted_at: datetime | None
    cancelled_reason: str | None
    created_at: datetime
    updated_at: datetime
    retrospective_conclusion: str | None = None
    retrospective_applicability: str | None = None
    retrospective_source_refs: tuple[dict[str, Any], ...] = ()
    retrospective_version: int = 0
    retrospective_digest: str | None = None
    retrospective_confirmed_by_user_id: UUID | None = None
    retrospective_confirmed_at: datetime | None = None


@dataclass(frozen=True)
class ParticipantRecord:
    id: UUID
    user_id: UUID
    participation: str
    attendance: str


@dataclass(frozen=True)
class AgendaItemRecord:
    id: UUID
    position: int
    title: str
    item_kind: str
    detail: str | None
    owner_user_id: UUID | None
    source_kind: str | None
    source_entity_id: UUID | None
    carried_from_item_id: UUID | None
    resolution_status: str
    source_digest: str | None = None


@dataclass(frozen=True)
class TranscriptSegmentDraft:
    sequence: int
    content: str
    speaker_label: str | None = None
    started_offset_ms: int = 0
    ended_offset_ms: int | None = None


@dataclass(frozen=True)
class TranscriptRecord:
    id: UUID
    meeting_id: UUID
    source: str
    language: str
    content_digest: str
    storage_key: str
    byte_size: int
    segment_count: int
    speaker_labeled: bool
    uploaded_by_user_id: UUID
    uploaded_at: datetime
    reused_existing: bool


def _meeting(row: RowMapping) -> MeetingRecord:
    return MeetingRecord(
        id=row["id"],
        project_id=row["project_id"],
        meeting_type=row["meeting_type"],
        title=row["title"],
        status=row["status"],
        scheduled_start_at=row["scheduled_start_at"],
        scheduled_end_at=row["scheduled_end_at"],
        actual_start_at=row["actual_start_at"],
        actual_end_at=row["actual_end_at"],
        organizer_user_id=row["organizer_user_id"],
        source=row["source"],
        external_provider=row["external_provider"],
        external_meeting_id=row["external_meeting_id"],
        external_join_url=row["external_join_url"],
        retention_policy=row["retention_policy"],
        archived_at=row["archived_at"],
        deleted_at=row["deleted_at"],
        cancelled_reason=row["cancelled_reason"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        retrospective_conclusion=row.get("retrospective_conclusion"),
        retrospective_applicability=row.get("retrospective_applicability"),
        retrospective_source_refs=tuple(row.get("retrospective_source_refs", [])),
        retrospective_version=row.get("retrospective_version", 0),
        retrospective_digest=row.get("retrospective_digest"),
        retrospective_confirmed_by_user_id=row.get("retrospective_confirmed_by_user_id"),
        retrospective_confirmed_at=row.get("retrospective_confirmed_at"),
    )


def _snapshot(record: MeetingRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "meeting_type": record.meeting_type,
        "title": record.title,
        "status": record.status,
        "scheduled_start_at": record.scheduled_start_at.isoformat(),
        "external_provider": record.external_provider,
        "external_meeting_id": record.external_meeting_id,
        "archived_at": record.archived_at.isoformat() if record.archived_at else None,
        "conclusion_confirmed": record.retrospective_version > 0,
        "retrospective_conclusion": record.retrospective_conclusion,
        "retrospective_applicability": record.retrospective_applicability,
        "retrospective_source_refs": list(record.retrospective_source_refs),
        "retrospective_version": record.retrospective_version,
        "retrospective_digest": record.retrospective_digest,
        "retrospective_confirmed_by_user_id": str(record.retrospective_confirmed_by_user_id)
        if record.retrospective_confirmed_by_user_id
        else None,
        "retrospective_confirmed_at": record.retrospective_confirmed_at.isoformat()
        if record.retrospective_confirmed_at
        else None,
    }


def transcript_digest(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()


def prepare_transcript_segments(
    content: str, segments: Sequence[TranscriptSegmentDraft]
) -> list[TranscriptSegmentDraft]:
    if not content.strip() or len(content.encode("utf-8")) > 524288 or "\x00" in content:
        raise MeetingStateError("转写原文须非空、无空字符且不超过512KB")
    result = list(segments)
    if not result:
        # Exact substrings only: no inferred speakers, timestamps or paraphrases.
        chunks = [
            line[start : start + 16000]
            for line in content.splitlines()
            for start in range(0, len(line), 16000)
            if line[start : start + 16000].strip()
        ]
        result = [
            TranscriptSegmentDraft(sequence=index + 1, content=chunk)
            for index, chunk in enumerate(chunks)
        ]
    if not result or len(result) > 1000:
        raise MeetingStateError("转写须包含1至1000个可引用片段")
    offset = 0
    for index, segment in enumerate(result):
        start = content.find(segment.content, offset)
        if (
            segment.sequence != index + 1
            or not segment.content.strip()
            or len(segment.content) > 20000
            or start < 0
            or segment.started_offset_ms < 0
            or (
                segment.ended_offset_ms is not None
                and segment.ended_offset_ms < segment.started_offset_ms
            )
            or (
                segment.speaker_label is not None
                and (not segment.speaker_label.strip() or len(segment.speaker_label) > 128)
            )
        ):
            raise MeetingStateError("请按原文顺序提供连续编号、原文片段及有效的说话人标签/时间")
        offset = start + len(segment.content)
    return result


class MeetingService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        include_deleted: bool = False,
    ) -> list[MeetingRecord]:
        statement = select(tables.meetings).where(
            tables.meetings.c.tenant_id == tenant_id,
            tables.meetings.c.project_id == project_id,
        )
        if not include_deleted:
            statement = statement.where(tables.meetings.c.deleted_at.is_(None))
        with self._engine.connect() as connection:
            return [
                _meeting(row)
                for row in connection.execute(
                    statement.order_by(tables.meetings.c.scheduled_start_at.desc())
                ).mappings()
            ]

    def get(self, *, tenant_id: UUID, project_id: UUID, meeting_id: UUID) -> MeetingRecord:
        with self._engine.connect() as connection:
            return self._get(
                connection,
                tenant_id=tenant_id,
                meeting_id=meeting_id,
                project_id=project_id,
            )

    def create(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        meeting_type: str,
        title: str,
        scheduled_start_at: datetime,
        scheduled_end_at: datetime,
        organizer_user_id: UUID | None = None,
        participants: Sequence[tuple[UUID, str]] = (),
        source: str = "manual",
        retention_policy: str = "standard",
        now: datetime | None = None,
        connection: Connection | None = None,
    ) -> MeetingRecord:
        if meeting_type not in MEETING_TYPES:
            raise MeetingStateError(f"unknown meeting type: {meeting_type}")
        if scheduled_end_at <= scheduled_start_at:
            raise MeetingStateError("meeting must end after it starts")
        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        organizer = organizer_user_id or actor_user_id
        meeting_id = uuid4()
        with (
            nullcontext(connection)
            if connection is not None
            else self._engine.begin() as connection
        ):
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise MeetingNotFoundError
            self._require_project_members(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                user_ids=[organizer, *(user_id for user_id, _ in participants)],
            )
            connection.execute(
                tables.meetings.insert(),
                {
                    "id": meeting_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "meeting_type": meeting_type,
                    "title": title,
                    "status": "scheduled",
                    "scheduled_start_at": scheduled_start_at,
                    "scheduled_end_at": scheduled_end_at,
                    "organizer_user_id": organizer,
                    "source": source,
                    "retention_policy": retention_policy,
                    "created_at": occurred_at,
                    "updated_at": occurred_at,
                },
            )
            roster = dict.fromkeys((user_id for user_id, _ in participants), "required")
            for user_id, participation in participants:
                roster[user_id] = participation
            roster[organizer] = "organizer"
            connection.execute(
                tables.meeting_participants.insert(),
                [
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "meeting_id": meeting_id,
                        "user_id": user_id,
                        "participation": participation,
                        "attendance": "unknown",
                        "added_at": occurred_at,
                    }
                    for user_id, participation in roster.items()
                ],
            )
            record = self._get(connection, tenant_id=tenant_id, meeting_id=meeting_id)
            self._emit(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                record=record,
                action="created",
                before=None,
                occurred_at=occurred_at,
            )
            return record

    def bind_external_conference(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        meeting_id: UUID,
        actor_user_id: UUID,
        provider: str,
        external_meeting_id: str,
        join_url: str,
        now: datetime | None = None,
    ) -> MeetingRecord:
        """Attach a conference link (D35).

        The provider allowlist and the https check are the "未授权会议不可接入"
        gate: a chat deep link or an http link is refused before it can reach a
        participant's notification.
        """
        if provider not in EXTERNAL_PROVIDERS:
            raise MeetingLinkError(f"unsupported conference provider: {provider}")
        if not join_url.startswith("https://"):
            raise MeetingLinkError("conference join URL must be https")
        if not external_meeting_id.strip():
            raise MeetingLinkError("conference id is required")
        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise MeetingNotFoundError
            before = self._get(
                connection,
                tenant_id=tenant_id,
                meeting_id=meeting_id,
                project_id=project_id,
            )
            if before.status not in ACTIVE_STATUSES:
                raise MeetingStateError(f"cannot bind a conference to a {before.status} meeting")
            if before.external_provider is not None:
                raise MeetingLinkError("meeting already has a conference bound; unbind it first")
            connection.execute(
                tables.meetings.update()
                .where(
                    tables.meetings.c.tenant_id == tenant_id,
                    tables.meetings.c.id == meeting_id,
                )
                .values(
                    external_provider=provider,
                    external_meeting_id=external_meeting_id,
                    external_join_url=join_url,
                    external_bound_at=occurred_at,
                    external_bound_by_user_id=actor_user_id,
                    source=provider,
                    updated_at=occurred_at,
                )
            )
            record = self._get(connection, tenant_id=tenant_id, meeting_id=meeting_id)
            self._emit(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                record=record,
                action="conference_bound",
                before=before,
                occurred_at=occurred_at,
            )
            return record

    def replace_agenda(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        meeting_id: UUID,
        actor_user_id: UUID,
        items: Sequence[dict[str, Any]],
        now: datetime | None = None,
        connection: Connection | None = None,
        expected_digest: str | None = None,
    ) -> MeetingList[AgendaItemRecord]:
        from app.auth.roles import Action
        from app.domain.knowledge_corrections import KnowledgeCorrectionService
        from app.domain.knowledge_push import KnowledgeVersionError
        from app.domain.meeting_preparation import (
            MeetingPreparationService,
            preparation_digest,
            write_agenda,
        )

        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        with (
            nullcontext(connection)
            if connection is not None
            else self._engine.begin() as connection
        ):
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise MeetingNotFoundError
            KnowledgeCorrectionService._authorize(
                connection, tenant_id, actor_user_id, project_id, Action.MEETING_MANAGE
            )
            record = self._get(
                connection, tenant_id=tenant_id, project_id=project_id, meeting_id=meeting_id
            )
            if record.status not in ACTIVE_STATUSES or record.archived_at or record.deleted_at:
                raise MeetingStateError("会议已经结束、取消或归档，议程不能再修改")
            if expected_digest is not None and expected_digest != preparation_digest(
                connection, tenant_id, meeting_id
            ):
                raise KnowledgeVersionError("议程已被修改，请刷新核对")
            before = MeetingPreparationService._state(connection, tenant_id, meeting_id)
            write_agenda(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                meeting_id=meeting_id,
                items=list(items),
                now=occurred_at,
            )
            self._emit(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                record=record,
                action="agenda_replaced",
                before=record,
                occurred_at=occurred_at,
                audit_context={
                    "before_preparation": before,
                    "after_preparation": MeetingPreparationService._state(
                        connection, tenant_id, meeting_id
                    ),
                },
            )
            return self._agenda(connection, tenant_id=tenant_id, meeting_id=meeting_id)

    def agenda(
        self, *, tenant_id: UUID, project_id: UUID, meeting_id: UUID
    ) -> MeetingList[AgendaItemRecord]:
        with self._engine.connect() as connection:
            self._get(
                connection,
                tenant_id=tenant_id,
                meeting_id=meeting_id,
                project_id=project_id,
            )
            return self._agenda(connection, tenant_id=tenant_id, meeting_id=meeting_id)

    def participants(
        self, *, tenant_id: UUID, project_id: UUID, meeting_id: UUID
    ) -> MeetingList[ParticipantRecord]:
        with self._engine.connect() as connection:
            self._get(
                connection,
                tenant_id=tenant_id,
                meeting_id=meeting_id,
                project_id=project_id,
            )
            return [
                ParticipantRecord(
                    id=row["id"],
                    user_id=row["user_id"],
                    participation=row["participation"],
                    attendance=row["attendance"],
                )
                for row in connection.execute(
                    select(tables.meeting_participants)
                    .where(
                        tables.meeting_participants.c.tenant_id == tenant_id,
                        tables.meeting_participants.c.meeting_id == meeting_id,
                    )
                    .order_by(tables.meeting_participants.c.added_at)
                ).mappings()
            ]

    def upload_transcript(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        meeting_id: UUID,
        actor_user_id: UUID,
        content: str,
        segments: Sequence[TranscriptSegmentDraft],
        source: str = "manual_upload",
        language: str = "zh-CN",
        authorized_source: bool = False,
        now: datetime | None = None,
    ) -> TranscriptRecord:
        """Store a transcript and its citable segments.

        Uploading the same bytes twice returns the existing transcript rather
        than forking the record every citation already points at.
        """
        from app.auth.roles import Action
        from app.domain.knowledge_corrections import KnowledgeCorrectionService

        if not authorized_source:
            raise MeetingStateError("请确认本稿来自已获授权且明确纳入当前项目的会议")
        if source not in {"manual_upload", "dingtalk_export", "tencent_meeting_export"}:
            raise MeetingStateError("请选择支持的会议转写来源")
        segments = prepare_transcript_segments(content, segments)
        digest = transcript_digest(content)
        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise MeetingNotFoundError
            KnowledgeCorrectionService._authorize(
                connection, tenant_id, actor_user_id, project_id, Action.MEETING_TRANSCRIPT_UPLOAD
            )
            record = self._get(
                connection,
                tenant_id=tenant_id,
                meeting_id=meeting_id,
                project_id=project_id,
            )
            if record.deleted_at is not None or record.archived_at is not None:
                raise MeetingStateError("已归档或删除的会议不能新增转写资料")
            existing = (
                connection.execute(
                    select(tables.meeting_transcripts).where(
                        tables.meeting_transcripts.c.tenant_id == tenant_id,
                        tables.meeting_transcripts.c.meeting_id == meeting_id,
                        tables.meeting_transcripts.c.content_digest == digest,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                if existing["original_content"] is None:
                    # Restore exact bytes only; keep existing citation anchors and labels.
                    if existing["segment_count"] == 0:
                        connection.execute(
                            tables.meeting_transcript_segments.insert(),
                            [
                                {
                                    "id": uuid4(),
                                    "tenant_id": tenant_id,
                                    "transcript_id": existing["id"],
                                    "sequence": segment.sequence,
                                    "speaker_label": segment.speaker_label,
                                    "speaker_user_id": None,
                                    "started_offset_ms": segment.started_offset_ms,
                                    "ended_offset_ms": segment.ended_offset_ms,
                                    "content": segment.content,
                                }
                                for segment in segments
                            ],
                        )
                    connection.execute(
                        tables.meeting_transcripts.update()
                        .where(
                            tables.meeting_transcripts.c.tenant_id == tenant_id,
                            tables.meeting_transcripts.c.id == existing["id"],
                        )
                        .values(
                            original_content=content,
                            segment_count=existing["segment_count"] or len(segments),
                            speaker_labeled=existing["speaker_labeled"]
                            or (
                                existing["segment_count"] == 0
                                and any(segment.speaker_label is not None for segment in segments)
                            ),
                        )
                    )
                    self._emit(
                        connection,
                        tenant_id=tenant_id,
                        actor_user_id=actor_user_id,
                        record=record,
                        action="transcript_original_restored",
                        before=record,
                        occurred_at=occurred_at,
                        audit_context={
                            "transcript_id": str(existing["id"]),
                            "source_authorized": True,
                            "content_digest": digest,
                        },
                    )
                    existing = (
                        connection.execute(
                            select(tables.meeting_transcripts).where(
                                tables.meeting_transcripts.c.tenant_id == tenant_id,
                                tables.meeting_transcripts.c.id == existing["id"],
                            )
                        )
                        .mappings()
                        .one()
                    )
                return _transcript(existing, reused_existing=True)

            transcript_id = uuid4()
            speaker_labeled = any(segment.speaker_label is not None for segment in segments)
            connection.execute(
                tables.meeting_transcripts.insert(),
                {
                    "id": transcript_id,
                    "tenant_id": tenant_id,
                    "meeting_id": meeting_id,
                    "source": source,
                    "language": language,
                    "content_digest": digest,
                    "original_content": content,
                    "storage_key": f"postgres:cehub_project.meeting_transcripts:{transcript_id}",
                    "byte_size": len(content.encode("utf-8")),
                    "segment_count": len(segments),
                    "speaker_labeled": speaker_labeled,
                    "uploaded_by_user_id": actor_user_id,
                    "uploaded_at": occurred_at,
                },
            )
            if segments:
                connection.execute(
                    tables.meeting_transcript_segments.insert(),
                    [
                        {
                            "id": uuid4(),
                            "tenant_id": tenant_id,
                            "transcript_id": transcript_id,
                            "sequence": segment.sequence,
                            "speaker_label": segment.speaker_label,
                            "speaker_user_id": None,
                            "started_offset_ms": segment.started_offset_ms,
                            "ended_offset_ms": segment.ended_offset_ms,
                            "content": segment.content,
                        }
                        for segment in segments
                    ],
                )
            self._emit(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                record=record,
                action="transcript_uploaded",
                before=record,
                occurred_at=occurred_at,
                audit_context={
                    "transcript_id": str(transcript_id),
                    "source_authorized": True,
                    "content_digest": digest,
                    "source": source,
                    "original_labels": [
                        {"sequence": segment.sequence, "speaker_label": segment.speaker_label}
                        for segment in segments
                    ],
                },
            )
            row = (
                connection.execute(
                    select(tables.meeting_transcripts).where(
                        tables.meeting_transcripts.c.tenant_id == tenant_id,
                        tables.meeting_transcripts.c.id == transcript_id,
                    )
                )
                .mappings()
                .one()
            )
            return _transcript(row, reused_existing=False)

    def transcripts(
        self, *, tenant_id: UUID, project_id: UUID, meeting_id: UUID
    ) -> MeetingList[TranscriptRecord]:
        with self._engine.connect() as connection:
            self._get(
                connection,
                tenant_id=tenant_id,
                meeting_id=meeting_id,
                project_id=project_id,
            )
            return [
                _transcript(row, reused_existing=False)
                for row in connection.execute(
                    select(tables.meeting_transcripts)
                    .where(
                        tables.meeting_transcripts.c.tenant_id == tenant_id,
                        tables.meeting_transcripts.c.meeting_id == meeting_id,
                    )
                    .order_by(tables.meeting_transcripts.c.uploaded_at.desc())
                ).mappings()
            ]

    def archive(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        meeting_id: UUID,
        actor_user_id: UUID,
        now: datetime | None = None,
    ) -> MeetingRecord:
        """Archive a meeting. Retention policy applies from this point.

        Archival is the only route to deletion (the DB enforces it), so a
        transcript can never disappear without leaving the archive trail.
        """
        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise MeetingNotFoundError
            before = self._get(
                connection,
                tenant_id=tenant_id,
                meeting_id=meeting_id,
                project_id=project_id,
            )
            if before.archived_at is not None:
                return before
            if before.status in ACTIVE_STATUSES:
                raise MeetingStateError("complete or cancel the meeting before archiving it")
            connection.execute(
                tables.meetings.update()
                .where(
                    tables.meetings.c.tenant_id == tenant_id,
                    tables.meetings.c.id == meeting_id,
                )
                .values(archived_at=occurred_at, updated_at=occurred_at)
            )
            record = self._get(connection, tenant_id=tenant_id, meeting_id=meeting_id)
            self._emit(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                record=record,
                action="archived",
                before=before,
                occurred_at=occurred_at,
            )
            return record

    def change_status(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        meeting_id: UUID,
        actor_user_id: UUID,
        status: str,
        cancelled_reason: str | None = None,
        now: datetime | None = None,
    ) -> MeetingRecord:
        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        if status == "cancelled" and not (cancelled_reason or "").strip():
            raise MeetingStateError("cancelling a meeting requires a reason")
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise MeetingNotFoundError
            before = self._get(
                connection,
                tenant_id=tenant_id,
                meeting_id=meeting_id,
                project_id=project_id,
            )
            allowed = _NEXT_STATUSES.get(before.status, frozenset())
            if status not in allowed:
                raise MeetingStateError(f"cannot move a {before.status} meeting to {status}")
            values: dict[str, Any] = {"status": status, "updated_at": occurred_at}
            if status == "in_progress":
                values["actual_start_at"] = occurred_at
            elif status == "completed" and before.actual_start_at is not None:
                # Only meetings we watched start get an observed end time.
                # Completing one straight from `scheduled` means nobody marked
                # it started, so there is no honest start to pair an end with —
                # inventing one from the schedule would turn a plan into a fact.
                values["actual_end_at"] = occurred_at
            elif status == "cancelled":
                values["cancelled_reason"] = cancelled_reason
            connection.execute(
                tables.meetings.update()
                .where(
                    tables.meetings.c.tenant_id == tenant_id,
                    tables.meetings.c.id == meeting_id,
                )
                .values(**values)
            )
            record = self._get(connection, tenant_id=tenant_id, meeting_id=meeting_id)
            self._emit(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                record=record,
                action=f"status_{status}",
                before=before,
                occurred_at=occurred_at,
            )
            return record

    @staticmethod
    def _agenda(
        connection: Connection, *, tenant_id: UUID, meeting_id: UUID
    ) -> MeetingList[AgendaItemRecord]:
        return [
            AgendaItemRecord(
                id=row["id"],
                position=row["position"],
                title=row["title"],
                item_kind=row["item_kind"],
                detail=row["detail"],
                owner_user_id=row["owner_user_id"],
                source_kind=row["source_kind"],
                source_entity_id=row["source_entity_id"],
                carried_from_item_id=row["carried_from_item_id"],
                resolution_status=row["resolution_status"],
                source_digest=row.get("source_digest"),
            )
            for row in connection.execute(
                select(tables.meeting_agenda_items)
                .where(
                    tables.meeting_agenda_items.c.tenant_id == tenant_id,
                    tables.meeting_agenda_items.c.meeting_id == meeting_id,
                )
                .order_by(tables.meeting_agenda_items.c.position)
            ).mappings()
        ]

    @staticmethod
    def _require_project_members(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        user_ids: Iterable[UUID],
    ) -> None:
        """Every named user must already be on the project.

        This is the concrete form of 未授权会议不可接入: a meeting cannot pull
        someone into a project's material by listing them on the invite.
        """
        wanted = {user_id for user_id in user_ids}
        if not wanted:
            return
        present = {
            row.user_id
            for row in connection.execute(
                select(tables.project_members.c.user_id)
                .join(
                    tables.users,
                    (tables.users.c.tenant_id == tables.project_members.c.tenant_id)
                    & (tables.users.c.id == tables.project_members.c.user_id),
                )
                .where(
                    tables.users.c.is_active.is_(True),
                    tables.project_members.c.tenant_id == tenant_id,
                    tables.project_members.c.project_id == project_id,
                    tables.project_members.c.user_id.in_(wanted),
                )
            ).all()
        }
        missing = wanted - present
        if missing:
            raise MeetingScopeError(
                "not project members: " + ", ".join(sorted(str(item) for item in missing))
            )

    @staticmethod
    def _emit(
        connection: Connection,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        record: MeetingRecord,
        action: str,
        before: MeetingRecord | None,
        occurred_at: datetime,
        event_id: str | None = None,
        audit_context: dict[str, Any] | None = None,
    ) -> None:
        EventAuditWriter(
            connection,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            project_id=record.project_id,
        ).record(
            EventDraft(
                event_id=event_id or f"meeting:{record.id}:{action}:{uuid4()}",
                event_type="MEETING_STATE_CHANGED",
                source="meeting_service",
                entity_id=record.id,
                payload={
                    "meeting_id": str(record.id),
                    "meeting_type": record.meeting_type,
                    "status": record.status,
                    "action": action,
                },
                occurred_at=occurred_at,
            ),
            AuditDraft(
                action=f"meeting.{action}",
                before_snapshot=_snapshot(before) if before else None,
                after_snapshot=_snapshot(record),
                context=audit_context or {},
            ),
        )

    @staticmethod
    def _get(
        connection: Connection,
        *,
        tenant_id: UUID,
        meeting_id: UUID,
        project_id: UUID | None = None,
    ) -> MeetingRecord:
        statement = select(tables.meetings).where(
            tables.meetings.c.tenant_id == tenant_id,
            tables.meetings.c.id == meeting_id,
        )
        if project_id is not None:
            statement = statement.where(tables.meetings.c.project_id == project_id)
        row = connection.execute(statement).mappings().one_or_none()
        if row is None:
            raise MeetingNotFoundError
        return _meeting(row)


_NEXT_STATUSES: dict[str, frozenset[str]] = {
    "scheduled": frozenset({"in_progress", "completed", "cancelled"}),
    # A meeting that started can still be cut short, but never un-started.
    "in_progress": frozenset({"completed", "cancelled"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
}


def _transcript(row: RowMapping, *, reused_existing: bool) -> TranscriptRecord:
    return TranscriptRecord(
        id=row["id"],
        meeting_id=row["meeting_id"],
        source=row["source"],
        language=row["language"],
        content_digest=row["content_digest"],
        storage_key=row["storage_key"],
        byte_size=row["byte_size"],
        segment_count=row["segment_count"],
        speaker_labeled=row["speaker_labeled"],
        uploaded_by_user_id=row["uploaded_by_user_id"],
        uploaded_at=row["uploaded_at"],
        reused_existing=reused_existing,
    )
