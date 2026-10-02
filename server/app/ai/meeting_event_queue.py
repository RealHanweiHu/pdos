"""Durable meeting-event projection into authorized application runs.

Dispatch is database-only. An independent cursor serializes consumers; immutable
per-event receipts, not the largest observed event ID, prove completion. This
also admits late commits below the cursor without replaying completed receipts.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, Engine, Select, func, select, update

from app.ai.application_gateway import ApplicationModelGateway
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.meeting_reading import KEY, MeetingReadingService
from app.ai.rollout_guard import CapabilityUnavailableError, require_live_key
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.ai_meeting_draft_content import CAPABILITIES, OPERATIONS, DraftKind
from app.domain.ai_meeting_drafts import latest_scope, policy
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.knowledge_push import KnowledgeAccessError, KnowledgeVersionError
from app.domain.meeting_transcripts import transcript_snapshot
from app.domain.meetings import MeetingNotFoundError, MeetingService, MeetingStateError
from app.domain.product_workspace import _plain
from app.domain.project_write_lock import lock_project_write_scope
from app.worker.dispatcher import AgentDispatcher

CONSUMER_KEY = "meeting_aftercare_events_v1"
TRIGGER_ACTIONS = frozenset(
    {
        "status_completed",
        "transcript_uploaded",
        "transcript_original_restored",
        "transcript_speakers_confirmed",
    }
)
REASONS = {
    "queued": "已按原事件、资料与当前授权排队。",
    "reused": "相同资料和授权已有生成任务，已回查原任务。",
    "action_not_supported": "该会议事件不触发会后草稿。",
    "event_not_completed": "事件发生时会议尚未结束。",
    "event_source_invalid": "原事件与会议或具名审计不一致。",
    "actor_unauthorized": "原事件发起人当前没有会议资料读取或转写权限。",
    "meeting_unavailable": "原会议不存在、未结束或已归档删除。",
    "transcript_missing": "事件没有对应的完整有效转写稿。",
    "transcript_ambiguous": "会议有多份有效转写稿，需明确所用原稿。",
    "transcript_changed": "事件绑定的转写依据已变化，保留原事件而不替换资料。",
    "automatic_not_enabled": "当前政策未启用该类草稿的自动处理。",
    "scope_not_enabled": "当前项目没有该类草稿的有效独立 AI 授权。",
    "event_before_authorization": "事件早于当前政策或范围授权，不补触发历史资料。",
    "capability_unavailable": "相关会议能力尚未开放实际运行。",
    "budget_unavailable": "当前预算或运行授权不足，未排入模型调用。",
    "source_unavailable": "当前会议资料不满足生成条件。",
}


class MeetingDispatchResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    scanned_event_count: int = 0
    queued_count: int = 0
    reused_count: int = 0
    skipped_count: int = 0


class SkipMeetingEvent(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def pending_events_query() -> Select[Any]:
    event, receipt = tables.events, tables.ai_meeting_event_receipts
    completed = (
        select(func.count(receipt.c.id))
        .where(
            receipt.c.tenant_id == event.c.tenant_id,
            receipt.c.event_row_id == event.c.id,
            receipt.c.operation_key.in_(tuple(OPERATIONS.values())),
        )
        .correlate(event)
        .scalar_subquery()
    )
    return select(event).where(
        event.c.event_type == "MEETING_STATE_CHANGED",
        event.c.project_id.is_not(None),
        completed < len(OPERATIONS),
    )


def trigger_action(event: Mapping[str, Any]) -> str:
    payload = event["payload"]
    action = payload.get("action")
    if action not in TRIGGER_ACTIONS:
        raise SkipMeetingEvent("action_not_supported")
    if payload.get("status") != "completed":
        raise SkipMeetingEvent("event_not_completed")
    if (
        event["source"] != "meeting_service"
        or event["entity"] != "meeting"
        or payload.get("meeting_id") != str(event["entity_id"])
    ):
        raise SkipMeetingEvent("event_source_invalid")
    return str(action)


def event_audit(c: Connection, event: Mapping[str, Any], action: str) -> Mapping[str, Any]:
    audit = tables.audit_log
    rows = (
        c.execute(
            select(audit).where(
                audit.c.tenant_id == event["tenant_id"],
                audit.c.project_id == event["project_id"],
                audit.c.event_id == event["event_id"],
                audit.c.entity == "meeting",
                audit.c.entity_id == event["entity_id"],
                audit.c.action == f"meeting.{action}",
                audit.c.timestamp == event["timestamp"],
            )
        )
        .mappings()
        .all()
    )
    if len(rows) != 1 or rows[0]["actor_user_id"] is None:
        raise SkipMeetingEvent("event_source_invalid")
    return dict(rows[0])


def select_transcript(
    c: Connection,
    event: Mapping[str, Any],
    audit: Mapping[str, Any],
    action: str,
) -> tuple[UUID, str]:
    tenant, meeting = event["tenant_id"], event["entity_id"]
    if action == "status_completed":
        t = tables.meeting_transcripts
        candidates = c.execute(
            select(t.c.id)
            .where(
                t.c.tenant_id == tenant,
                t.c.meeting_id == meeting,
                t.c.superseded_at.is_(None),
                t.c.uploaded_at <= event["timestamp"],
            )
            .order_by(t.c.uploaded_at, t.c.id)
        ).scalars()
        valid = []
        for identity in candidates:
            snapshot = transcript_snapshot(c, tenant, meeting, identity)
            if snapshot["source_complete"] and not snapshot["superseded"]:
                valid.append((identity, snapshot["digest"]))
            if len(valid) > 1:
                raise SkipMeetingEvent("transcript_ambiguous")
        if not valid:
            raise SkipMeetingEvent("transcript_missing")
        return valid[0]
    context = audit["context"]
    try:
        identity = UUID(context["transcript_id"])
    except (ValueError, TypeError, KeyError) as error:
        raise SkipMeetingEvent("event_source_invalid") from error
    snapshot = transcript_snapshot(c, tenant, meeting, identity)
    if not snapshot["source_complete"] or snapshot["superseded"]:
        raise SkipMeetingEvent("transcript_missing")
    if action == "transcript_speakers_confirmed":
        result = context.get("result", {})
        if (
            result.get("transcript_id") != str(identity)
            or result.get("digest") != snapshot["digest"]
        ):
            raise SkipMeetingEvent("transcript_changed")
    elif (
        context.get("source_authorized") is not True
        or context.get("content_digest") != snapshot["transcript"]["content_digest"]
    ):
        raise SkipMeetingEvent("transcript_changed")
    return identity, str(snapshot["digest"])


class MeetingEventQueue:
    def __init__(self, engine: Engine, gateway: ApplicationModelGateway) -> None:
        self.engine, self.gateway = engine, gateway

    def _enqueue(
        self,
        c: Connection,
        event: Mapping[str, Any],
        kind: DraftKind,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        action = trigger_action(event)
        audit = event_audit(c, event, action)
        evidence.update(audit_row_id=audit["id"], actor_user_id=audit["actor_user_id"])
        tenant, project, meeting = event["tenant_id"], event["project_id"], event["entity_id"]
        for permission in (Action.MEETING_VIEW, Action.MEETING_TRANSCRIPT_UPLOAD):
            KnowledgeCorrectionService._authorize(
                c, tenant, audit["actor_user_id"], project, permission
            )
        if not lock_project_write_scope(c, tenant_id=tenant, project_id=project):
            raise SkipMeetingEvent("meeting_unavailable")
        current = MeetingService._get(c, tenant_id=tenant, project_id=project, meeting_id=meeting)
        if current.status != "completed" or current.deleted_at or current.archived_at:
            raise SkipMeetingEvent("meeting_unavailable")
        settings = policy(c, tenant)
        if (
            settings is None
            or settings["mode"] != "tiered"
            or settings["operation_settings"].get(OPERATIONS[kind], {}).get("mode") != "automatic"
        ):
            raise SkipMeetingEvent("automatic_not_enabled")
        evidence["policy_id"] = settings["id"]
        grant = latest_scope(c, tenant, project, OPERATIONS[kind])
        if (
            grant is None
            or not grant["enabled"]
            or grant["principal_id"] != settings["principal_id"]
        ):
            raise SkipMeetingEvent("scope_not_enabled")
        evidence.update(scope_revision_id=grant["id"], principal_id=grant["principal_id"])
        if event["timestamp"] < max(settings["created_at"], grant["created_at"]):
            raise SkipMeetingEvent("event_before_authorization")
        principal = tables.ai_principals
        if (
            c.execute(
                select(principal.c.id).where(
                    principal.c.tenant_id == tenant,
                    principal.c.id == grant["principal_id"],
                    principal.c.principal_kind == "ai",
                    principal.c.principal_key == "pdos-agent",
                )
            ).scalar_one_or_none()
            is None
        ):
            raise SkipMeetingEvent("scope_not_enabled")
        require_live_key(KEY)
        require_live_key(CAPABILITIES[kind])
        transcript, source_digest = select_transcript(c, event, audit, action)
        evidence.update(transcript_id=transcript, source_digest=source_digest)
        result = MeetingReadingService(self.engine, gateway=self.gateway).enqueue_event(
            c,
            event={**dict(event), "actor_user_id": audit["actor_user_id"]},
            meeting_id=meeting,
            transcript_id=transcript,
            kind=kind,
            principal_id=grant["principal_id"],
            policy_id=settings["id"],
            scope_revision_id=grant["id"],
        )
        return dict(result)

    def _lock(self, c: Connection, tenant: UUID) -> Mapping[str, Any]:
        dispatcher = AgentDispatcher(self.engine, consumer_key=CONSUMER_KEY)
        dispatcher._lock_tenant_consumer(c, tenant_id=tenant)
        cursor = dispatcher._cursor(c, tenant_id=tenant)
        # Same lock order as policy and application request creation.
        c.execute(
            select(tables.tenants.c.id).where(tables.tenants.c.id == tenant).with_for_update()
        )
        return dict(cursor)

    @staticmethod
    def _receipt_exists(c: Connection, event: Mapping[str, Any], operation: str) -> bool:
        receipt = tables.ai_meeting_event_receipts
        return (
            c.execute(
                select(receipt.c.id).where(
                    receipt.c.tenant_id == event["tenant_id"],
                    receipt.c.event_row_id == event["id"],
                    receipt.c.operation_key == operation,
                )
            ).scalar_one_or_none()
            is not None
        )

    @staticmethod
    def _record(
        c: Connection,
        event: Mapping[str, Any],
        operation: str,
        status: str,
        reason: str,
        evidence: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        now = c.execute(select(func.clock_timestamp())).scalar_one()
        body = _plain(
            {
                "version": "meeting-event-receipt.v1",
                "consumer_key": CONSUMER_KEY,
                "event_row_id": event["id"],
                "event_id": event["event_id"],
                "event_action": event["payload"].get("action"),
                "operation_key": operation,
                "status": status,
                "reason": reason,
                "message": REASONS[reason],
                "source": evidence,
                "run": result,
                "created_at": now,
            }
        )
        c.execute(
            tables.ai_meeting_event_receipts.insert().values(
                id=uuid4(),
                tenant_id=event["tenant_id"],
                project_id=event["project_id"],
                meeting_id=event["entity_id"],
                event_row_id=event["id"],
                operation_key=operation,
                transcript_id=evidence.get("transcript_id"),
                source_digest=result.get("source_digest", evidence.get("source_digest")),
                run_id=UUID(str(result["run_id"])) if result else None,
                principal_id=evidence.get("principal_id"),
                status=status,
                reason=reason,
                receipt=body,
                created_at=now,
            )
        )

    def _project_operation(self, event: Mapping[str, Any], kind: DraftKind) -> str | None:
        operation = OPERATIONS[kind]
        evidence: dict[str, Any] = {}
        # Budget freezing verifies the new run's xmin against the top-level
        # transaction. Do not introduce a savepoint around creation or freezing.
        try:
            with self.engine.begin() as c:
                self._lock(c, event["tenant_id"])
                if self._receipt_exists(c, event, operation):
                    return None
                result = self._enqueue(c, event, kind, evidence)
                status = "reused" if result["reused"] else "queued"
                self._record(c, event, operation, status, status, evidence, result)
            return status
        except SkipMeetingEvent as error:
            reason = error.reason
        except CapabilityUnavailableError as error:
            reason = "capability_unavailable"
            evidence["error_code"] = error.code
        except BudgetLedgerError as error:
            reason = "budget_unavailable"
            evidence["error_code"] = error.code
        except KnowledgeAccessError:
            reason = "actor_unauthorized"
        except KnowledgeVersionError:
            reason = "transcript_changed"
        except MeetingNotFoundError:
            reason = "meeting_unavailable"
        except MeetingStateError:
            reason = "source_unavailable"
        # The failed run/authorization/budget transaction has fully rolled back.
        # A concurrent consumer may have completed it meanwhile: lock and check
        # again, never replace a queued receipt with this attempted skip.
        with self.engine.begin() as c:
            self._lock(c, event["tenant_id"])
            if self._receipt_exists(c, event, operation):
                return None
            self._record(c, event, operation, "skipped", reason, evidence, {})
        return "skipped"

    def _project_event(self, event: Mapping[str, Any]) -> dict[str, int]:
        counts = {"queued": 0, "reused": 0, "skipped": 0}
        for kind in OPERATIONS:
            status = self._project_operation(event, kind)
            if status is not None:
                counts[status] += 1
        return counts

    def dispatch_once(self, batch_size: int = 100) -> MeetingDispatchResult:
        if not 1 <= batch_size <= 1000:
            raise ValueError("meeting event batch size must be between 1 and 1000")
        pending = pending_events_query().subquery()
        with self.engine.connect() as c:
            tenants = (
                c.execute(
                    select(pending.c.tenant_id)
                    .distinct()
                    .order_by(pending.c.tenant_id)
                    .limit(batch_size)
                )
                .scalars()
                .all()
            )
        totals = {"queued": 0, "reused": 0, "skipped": 0}
        scanned = 0
        for tenant in tenants:
            if scanned >= batch_size:
                break
            with self.engine.connect() as c:
                rows = (
                    c.execute(
                        pending_events_query()
                        .where(tables.events.c.tenant_id == tenant)
                        .order_by(tables.events.c.id)
                        .limit(batch_size - scanned)
                    )
                    .mappings()
                    .all()
                )
            for event in rows:
                counts = self._project_event(dict(event))
                for status in totals:
                    totals[status] += counts[status]
                # Cursor is scan progress only; missing per-operation receipts
                # remain discoverable even if a different worker moves it ahead.
                with self.engine.begin() as c:
                    cursor = self._lock(c, tenant)
                    c.execute(
                        update(tables.agent_dispatcher_cursors)
                        .where(
                            tables.agent_dispatcher_cursors.c.id == cursor["id"],
                            tables.agent_dispatcher_cursors.c.tenant_id == tenant,
                        )
                        .values(
                            last_event_row_id=max(cursor["last_event_row_id"], event["id"]),
                            updated_at=func.clock_timestamp(),
                        )
                    )
                scanned += 1
        return MeetingDispatchResult(
            scanned_event_count=scanned,
            queued_count=totals["queued"],
            reused_count=totals["reused"],
            skipped_count=totals["skipped"],
        )

    def execute_next(self) -> bool:
        run, receipt = tables.agent_runs, tables.ai_meeting_event_receipts
        with self.engine.connect() as c:
            identity = c.execute(
                select(run.c.id)
                .where(
                    run.c.status == "queued",
                    select(receipt.c.id)
                    .where(
                        receipt.c.tenant_id == run.c.tenant_id,
                        receipt.c.run_id == run.c.id,
                        receipt.c.status.in_(("queued", "reused")),
                    )
                    .correlate(run)
                    .exists(),
                )
                .order_by(run.c.created_at, run.c.id)
                .limit(1)
            ).scalar_one_or_none()
        if identity is None:
            return False
        # The service owns claiming, original authority checks and lease fencing.
        MeetingReadingService(self.engine, gateway=self.gateway).execute_queued(identity)
        return True
