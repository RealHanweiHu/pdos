"""Durable meeting-event requests reuse the budgeted meeting application service.

The event actor supplies current source-reading authority, not the AI writer's
permissions. Draft writes independently require the pinned AI principal/scope;
no event run can publish minutes, issue an action or approve a decision.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import Connection, RowMapping, func, select

from app.ai.application_queue_claim import claim_application_queue
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.rollout_guard import require_live_key
from app.ai.run_budget_creation import freeze_created_application_run
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.ai_meeting_draft_content import CAPABILITIES, OPERATIONS, DraftKind
from app.domain.ai_meeting_drafts import latest_scope, policy
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.meetings import MeetingNotFoundError, MeetingService, MeetingStateError
from app.domain.product_workspace import digest
from app.domain.project_write_lock import lock_project_write_scope

if TYPE_CHECKING:
    from app.ai.meeting_reading import MeetingReadingService

EVENT_ACTIONS = frozenset(
    {
        "status_completed",
        "transcript_uploaded",
        "transcript_original_restored",
        "transcript_speakers_confirmed",
    }
)


def original_event(
    c: Connection, tenant_id: UUID, event_row_id: int
) -> tuple[RowMapping, RowMapping]:
    event = (
        c.execute(
            select(tables.events).where(
                tables.events.c.tenant_id == tenant_id,
                tables.events.c.id == event_row_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if event is None or event["event_type"] != "MEETING_STATE_CHANGED":
        raise MeetingStateError("MEETING_EVENT_SOURCE_INVALID")
    audit = (
        c.execute(
            select(tables.audit_log).where(
                tables.audit_log.c.tenant_id == tenant_id,
                tables.audit_log.c.event_id == event["event_id"],
                tables.audit_log.c.project_id == event["project_id"],
                tables.audit_log.c.entity_id == event["entity_id"],
            )
        )
        .mappings()
        .one_or_none()
    )
    if (
        audit is None
        or audit["actor_user_id"] is None
        or event["payload"].get("action") not in EVENT_ACTIONS
        or audit["action"] != "meeting." + event["payload"]["action"]
    ):
        raise MeetingStateError("MEETING_EVENT_SOURCE_INVALID")
    return event, audit


def authority(
    c: Connection,
    *,
    event: Mapping[str, Any],
    meeting_id: UUID,
    kind: DraftKind,
    principal_id: UUID,
    policy_id: UUID,
    scope_revision_id: UUID,
) -> RowMapping:
    """Recheck immutable trigger against current read and independent write grants."""
    original, audit = original_event(c, event["tenant_id"], int(event["id"]))
    if (
        original["project_id"] != event["project_id"]
        or original["entity_id"] != meeting_id
        or original["payload"].get("meeting_id") != str(meeting_id)
    ):
        raise MeetingStateError("MEETING_EVENT_SOURCE_INVALID")
    settings = policy(c, original["tenant_id"])
    grant = latest_scope(c, original["tenant_id"], original["project_id"], OPERATIONS[kind])
    if (
        settings is None
        or grant is None
        or settings["id"] != policy_id
        or settings["principal_id"] != principal_id
        or grant["id"] != scope_revision_id
        or grant["principal_id"] != principal_id
        or not grant["enabled"]
        or settings["mode"] != "tiered"
        or settings["operation_settings"].get(OPERATIONS[kind], {}).get("mode") != "automatic"
        or original["timestamp"] < settings["created_at"]
        or original["timestamp"] < grant["created_at"]
    ):
        raise MeetingStateError("MEETING_EVENT_AUTHORITY_CHANGED")
    require_live_key("knowledge_lite.meeting_reading")
    require_live_key(CAPABILITIES[kind])
    actor = audit["actor_user_id"]
    KnowledgeCorrectionService._authorize(
        c, original["tenant_id"], actor, original["project_id"], Action.MEETING_TRANSCRIPT_UPLOAD
    )
    user = (
        c.execute(
            select(tables.users).where(
                tables.users.c.tenant_id == original["tenant_id"],
                tables.users.c.id == actor,
                tables.users.c.is_active.is_(True),
            )
        )
        .mappings()
        .one_or_none()
    )
    if user is None:
        raise MeetingStateError("MEETING_EVENT_ACTOR_UNAVAILABLE")
    meeting = MeetingService._get(
        c, tenant_id=original["tenant_id"], project_id=original["project_id"], meeting_id=meeting_id
    )
    if meeting.status != "completed" or meeting.deleted_at or meeting.archived_at:
        raise MeetingStateError("MEETING_EVENT_SOURCE_CHANGED")
    return user


def require_current(c: Connection, row: RowMapping) -> None:
    trigger = row["run_context"].get("reading_event_trigger")
    if trigger is None:
        return
    if not isinstance(trigger, dict) or trigger.get("version") != "meeting-event.v1":
        raise MeetingStateError("MEETING_EVENT_SOURCE_INVALID")
    kind: DraftKind = trigger["kind"]
    if kind not in OPERATIONS:
        raise MeetingStateError("MEETING_EVENT_SOURCE_INVALID")
    user = authority(
        c,
        event={
            "id": trigger["event_row_id"],
            "tenant_id": row["tenant_id"],
            "project_id": row["project_id"],
        },
        meeting_id=UUID(row["run_context"]["reading_meeting_id"]),
        kind=kind,
        principal_id=UUID(trigger["principal_id"]),
        policy_id=UUID(trigger["policy_id"]),
        scope_revision_id=UUID(trigger["scope_revision_id"]),
    )
    if (
        user["id"] != row["requested_by_user_id"]
        or user["auth_version"] != trigger["auth_version"]
        or row["event_row_ids"] != []
        or row["event_count"] != 0
    ):
        raise MeetingStateError("MEETING_EVENT_AUTHORITY_CHANGED")


def enqueue_event(
    c: Connection,
    gateway: Any,
    *,
    event: Mapping[str, Any],
    meeting_id: UUID,
    transcript_id: UUID,
    kind: DraftKind,
    principal_id: UUID,
    policy_id: UUID,
    scope_revision_id: UUID,
) -> dict[str, Any]:
    from app.ai.meeting_reading import source_state

    tenant, project = event["tenant_id"], event["project_id"]
    c.execute(select(tables.tenants.c.id).where(tables.tenants.c.id == tenant).with_for_update())
    if not lock_project_write_scope(c, tenant_id=tenant, project_id=project):
        raise MeetingNotFoundError
    actor = authority(
        c,
        event=event,
        meeting_id=meeting_id,
        kind=kind,
        principal_id=principal_id,
        policy_id=policy_id,
        scope_revision_id=scope_revision_id,
    )
    snapshot = source_state(
        c,
        tenant,
        project,
        meeting_id,
        transcript_id,
        include_minutes=kind == "minutes",
        include_actions=kind == "actions",
        include_decisions=kind == "decisions",
    )
    original, audit = original_event(c, tenant, int(event["id"]))
    event_transcript = audit["context"].get("transcript_id")
    if event_transcript is not None and event_transcript != str(transcript_id):
        raise MeetingStateError("MEETING_EVENT_SOURCE_INVALID")
    later_source_change = c.execute(
        select(tables.audit_log.c.id)
        .where(
            tables.audit_log.c.tenant_id == tenant,
            tables.audit_log.c.project_id == project,
            tables.audit_log.c.entity_id == meeting_id,
            tables.audit_log.c.action.in_(
                (
                    "meeting.transcript_speakers_confirmed",
                    "meeting.transcript_original_restored",
                )
            ),
            tables.audit_log.c.context["transcript_id"].as_string() == str(transcript_id),
            tables.audit_log.c.timestamp > original["timestamp"],
        )
        .limit(1)
    ).first()
    if later_source_change is not None:
        raise MeetingStateError("MEETING_EVENT_SOURCE_CHANGED")
    source_digest = digest(snapshot)
    request_id = uuid5(
        NAMESPACE_URL,
        "pdos:meeting-event:"
        + digest(
            {
                "tenant": str(tenant),
                "project": str(project),
                "kind": kind,
                "source_digest": source_digest,
                "policy": str(policy_id),
                "scope": str(scope_revision_id),
            }
        ),
    )
    old = (
        c.execute(
            select(tables.agent_runs).where(
                tables.agent_runs.c.tenant_id == tenant,
                tables.agent_runs.c.project_id == project,
                tables.agent_runs.c.agent_key == "knowledge_lite",
                tables.agent_runs.c.request_id == str(request_id),
            )
        )
        .mappings()
        .one_or_none()
    )
    if old is not None:
        return {
            "run_id": old["id"],
            "status": old["status"],
            "reused": True,
            "source_digest": source_digest,
        }
    if getattr(gateway, "creation_budget_profile", None) is None:
        raise BudgetLedgerError("APPLICATION_QUEUE_BUDGET_REQUIRED")
    now = c.execute(select(func.clock_timestamp())).scalar_one()
    trigger = {
        "version": "meeting-event.v1",
        "event_row_id": int(original["id"]),
        "event_id": original["event_id"],
        "audit_id": str(audit["id"]),
        "kind": kind,
        "principal_id": str(principal_id),
        "policy_id": str(policy_id),
        "scope_revision_id": str(scope_revision_id),
        "auth_version": actor["auth_version"],
    }
    context = {
        "reading_meeting_id": str(meeting_id),
        "reading_transcript_id": str(transcript_id),
        "reading_expected_digest": snapshot["transcript_digest"],
        f"reading_propose_{kind}": True,
        "reading_source": snapshot,
        "reading_source_digest": source_digest,
        "reading_event_trigger": trigger,
        "application_queue_version": "1",
    }
    if kind == "minutes":
        context["reading_expected_minutes_version"] = snapshot["minutes_base"]["version"]
    row = (
        c.execute(
            tables.agent_runs.insert()
            .values(
                id=uuid4(),
                tenant_id=tenant,
                project_id=project,
                agent_key="knowledge_lite",
                request_id=str(request_id),
                requested_by_user_id=actor["id"],
                status="running",
                # Application runs retain their existing shape. The exact event FK is
                # stored in the immutable trigger receipt, with this matching context.
                event_count=0,
                event_row_ids=[],
                window_started_at=now,
                window_ended_at=now,
                context_version=f"meeting-{kind}-request-v1",
                created_at=now,
                updated_at=now,
                started_at=now,
                run_context=context,
            )
            .returning(tables.agent_runs)
        )
        .mappings()
        .one()
    )
    freeze_created_application_run(
        c,
        gateway,
        tenant_id=tenant,
        run_id=row["id"],
        actor_user_id=actor["id"],
        purpose=f"meeting_{kind}",
        auth_version=actor["auth_version"],
        issue_lease=False,
    )
    # Creation authorization and its budget must freeze against a fresh running
    # row in this top-level transaction; publish it to workers only once frozen.
    c.execute(
        tables.agent_runs.update()
        .where(tables.agent_runs.c.id == row["id"])
        .values(status="queued", started_at=None)
    )
    return {
        "run_id": row["id"],
        "status": "queued",
        "reused": False,
        "source_digest": source_digest,
    }


def execute_queued(service: MeetingReadingService, run_id: UUID) -> dict[str, Any]:
    from app.ai.meeting_reading import source_state

    with service.engine.begin() as c:
        row = (
            c.execute(
                select(tables.agent_runs).where(tables.agent_runs.c.id == run_id).with_for_update()
            )
            .mappings()
            .one()
        )
        if row["status"] != "queued":
            return service._receipt(row)
        try:
            with c.begin_nested():
                require_current(c, row)
                trigger = row["run_context"].get("reading_event_trigger")
                if trigger is None:
                    raise MeetingStateError("MEETING_EVENT_SOURCE_INVALID")
                kind = trigger["kind"]
                snapshot = source_state(
                    c,
                    row["tenant_id"],
                    row["project_id"],
                    UUID(row["run_context"]["reading_meeting_id"]),
                    UUID(row["run_context"]["reading_transcript_id"]),
                    include_minutes=kind == "minutes",
                    include_actions=kind == "actions",
                    include_decisions=kind == "decisions",
                )
                if digest(snapshot) != row["run_context"]["reading_source_digest"]:
                    raise MeetingStateError("MEETING_EVENT_SOURCE_CHANGED")
                claimed = claim_application_queue(
                    c,
                    service.gateway,
                    row,
                    auth_version=trigger["auth_version"],
                    purpose=f"meeting_{kind}",
                )
        except (
            MeetingStateError,
            MeetingNotFoundError,
            BudgetLedgerError,
            PermissionError,
        ) as error:
            raw = getattr(error, "code", str(error))
            code = (
                raw
                if raw.startswith(("MEETING_", "APPLICATION_", "BUDGET_", "CAPABILITY_"))
                and len(raw) <= 128
                else "MEETING_EVENT_AUTHORITY_CHANGED"
            )
            stopped = (
                c.execute(
                    tables.agent_runs.update()
                    .where(tables.agent_runs.c.id == run_id)
                    .values(
                        status="failed",
                        error_code=code,
                        completed_at=func.clock_timestamp(),
                        updated_at=func.clock_timestamp(),
                    )
                    .returning(tables.agent_runs)
                )
                .mappings()
                .one()
            )
            return service._receipt(stopped)
    return service._execute(claimed, snapshot)
