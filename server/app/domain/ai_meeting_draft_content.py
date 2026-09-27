"""Typed content adapters for minutes, action and decision drafts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, select

from app.db.schema import tables
from app.domain.meeting_action_proposals import MeetingActionPayload, apply_action, validate_quotes
from app.domain.meeting_decision_proposals import MeetingDecisionPayload, apply_decision
from app.domain.meeting_minutes_proposals import MeetingMinutesPayload, validate_minutes_payload
from app.domain.meetings import MeetingStateError

DraftKind = Literal["minutes", "actions", "decisions"]
OPERATIONS: dict[DraftKind, str] = {
    "minutes": "meeting.minutes.draft",
    "actions": "meeting.actions.draft",
    "decisions": "meeting.decisions.draft",
}
CAPABILITIES: dict[DraftKind, str] = {
    "minutes": "knowledge_lite.meeting_minutes",
    "actions": "knowledge_lite.meeting_actions",
    "decisions": "knowledge_lite.meeting_decisions",
}
LABELS: dict[DraftKind, str] = {"minutes": "纪要", "actions": "行动项", "decisions": "决策"}


def validate_source(
    c: Connection,
    tenant: UUID,
    project: UUID,
    kind: DraftKind,
    snapshot: dict[str, Any],
    content: dict[str, Any],
) -> None:
    if kind == "minutes":
        validate_minutes_payload(
            c,
            tenant_id=tenant,
            project_id=project,
            snapshot=snapshot,
            payload=MeetingMinutesPayload.model_validate(content),
        )
        return
    from app.ai.meeting_reading import source_state

    parsed = (
        MeetingActionPayload.model_validate(content)
        if kind == "actions"
        else MeetingDecisionPayload.model_validate(content)
    )
    if (
        str(parsed.meeting_id) != snapshot["meeting_id"]
        or str(parsed.transcript_id) != snapshot["transcript_id"]
        or parsed.source_digest != snapshot["transcript_digest"]
    ):
        raise MeetingStateError("草稿来源与本次运行不一致")
    current = source_state(c, tenant, project, parsed.meeting_id, parsed.transcript_id)
    original = {
        k: v for k, v in snapshot.items() if k not in {"action_options", "decision_options"}
    }
    if current != original or current["meeting_status"] != "completed":
        raise MeetingStateError("会议、转录或说话人已变化，请重新生成草稿")
    validate_quotes(snapshot, parsed.citations)


def edit_content(
    kind: DraftKind, original: dict[str, Any], proposed: dict[str, Any]
) -> dict[str, Any]:
    if kind == "minutes":
        raise MeetingStateError("纪要请使用正文和未决事项字段修订")
    try:
        parsed = (
            MeetingActionPayload.model_validate(proposed)
            if kind == "actions"
            else MeetingDecisionPayload.model_validate(proposed)
        )
    except ValueError as error:
        raise MeetingStateError("草稿字段不完整或超出长度限制，请核对后保存") from error
    saved = parsed.model_dump(mode="json")
    frozen: tuple[str, ...] = (
        "meeting_id",
        "transcript_id",
        "source_digest",
        "member_options",
        "citations",
    )
    if kind == "actions":
        frozen += ("owner_text", "date_text", "agenda_options")
    if any(saved[key] != original[key] for key in frozen):
        raise MeetingStateError("不能改写草稿的原始来源、人员选项或引用")
    return saved


def body_text(kind: DraftKind, content: dict[str, Any]) -> tuple[str, str]:
    if kind == "minutes":
        return content["body"], content["unresolved_points"]
    if kind == "actions":
        return content["description"], content.get("expected_output") or "完成标准待具名核对"
    return content.get("context") or content["title"], content.get(
        "follow_up_note"
    ) or "正式批准前核对执行要求"


def consumed(c: Connection, draft: RowMapping) -> UUID | None:
    kind = draft["draft_kind"]
    if kind == "minutes":
        t = tables.meeting_minutes_versions
        return c.execute(
            select(t.c.id).where(
                t.c.tenant_id == draft["tenant_id"], t.c.source_finding_id == draft["finding_id"]
            )
        ).scalar_one_or_none()
    # Includes records created through the old human application path.
    if kind == "decisions":
        t = tables.decisions
        return c.execute(
            select(t.c.id).where(
                t.c.tenant_id == draft["tenant_id"], t.c.source_finding_id == draft["finding_id"]
            )
        ).scalar_one_or_none()
    t = tables.meeting_agenda_actions
    return c.execute(
        select(t.c.task_id).where(
            t.c.tenant_id == draft["tenant_id"], t.c.source_finding_id == draft["finding_id"]
        )
    ).scalar_one_or_none()


def require_unpublished_origin(
    c: Connection, tenant: UUID, project: UUID, finding_type: str, origin_key: str
) -> None:
    f, a, d = tables.findings, tables.ai_meeting_draft_actions, tables.ai_meeting_drafts
    previous = c.execute(
        select(a.c.id)
        .join(d, (a.c.tenant_id == d.c.tenant_id) & (a.c.draft_id == d.c.id))
        .join(f, (d.c.tenant_id == f.c.tenant_id) & (d.c.finding_id == f.c.id))
        .where(
            f.c.tenant_id == tenant,
            f.c.project_id == project,
            f.c.finding_type == finding_type,
            f.c.origin_key == origin_key,
            a.c.action == "publish",
        )
        .limit(1)
    ).first()
    if previous:
        from app.domain.findings import FindingGroundTruthConflictError

        raise FindingGroundTruthConflictError("相同来源已正式办理，请回查原任务或决策")


def publish_work(
    engine: Engine,
    c: Connection,
    draft: RowMapping,
    content: dict[str, Any],
    actor: UUID,
    now: datetime,
) -> tuple[UUID | None, UUID | None]:
    from app.domain.findings import FindingService

    finding = FindingService._get(c, tenant_id=draft["tenant_id"], finding_id=draft["finding_id"])
    try:
        if draft["draft_kind"] == "actions":
            task = apply_action(
                engine,
                c,
                finding=finding,
                payload=MeetingActionPayload.model_validate(content),
                actor_user_id=actor,
                applied_at=now,
            )
            return task, None
        decision = apply_decision(
            engine,
            c,
            finding=finding,
            payload=MeetingDecisionPayload.model_validate(content),
            actor_user_id=actor,
            applied_at=now,
        )
        return None, decision
    except ValueError as error:
        raise MeetingStateError(str(error) or "请补齐正式办理资料") from error


def record_publication_finding(
    c: Connection,
    draft: RowMapping,
    content: dict[str, Any],
    actor: UUID,
    now: datetime,
    reason: str,
    *,
    entity_id: UUID | None = None,
) -> None:
    """Bridge the named human publication to the original immutable-origin guards.

    Called before and after the formal domain operation in the same transaction.
    Draft confirmation alone never accepts a formal Finding. A failed publication
    rolls back both this receipt and the domain write; no accepted item is queued.
    """
    from app.domain.findings import FindingService
    from app.domain.meeting_action_proposals import validate_action
    from app.domain.meeting_decision_proposals import validate_decision
    from app.domain.meeting_minutes_proposals import validate_finding_minutes

    before = FindingService._get(c, tenant_id=draft["tenant_id"], finding_id=draft["finding_id"])
    kind = draft["draft_kind"]
    entity_type = {"minutes": "meeting_minutes", "actions": "task", "decisions": "decision"}[kind]
    values: dict[str, Any]
    if entity_id is None:
        if before.status != "archived":
            raise MeetingStateError("原候选已沿其他流程办理，请刷新草稿")
        try:
            if kind == "minutes":
                validate_finding_minutes(c, before, MeetingMinutesPayload.model_validate(content))
            elif kind == "actions":
                validate_action(c, before, MeetingActionPayload.model_validate(content))
            else:
                validate_decision(c, before, MeetingDecisionPayload.model_validate(content))
        except ValueError as error:
            raise MeetingStateError(str(error)) from error
        # Re-enter the original finite-state machine only inside this human
        # publication transaction; no pending-review item escapes the commit.
        c.execute(
            tables.findings.update()
            .where(
                tables.findings.c.tenant_id == draft["tenant_id"],
                tables.findings.c.id == before.id,
            )
            .values(status="pending_review", updated_at=now)
        )
        restored = FindingService._get(c, tenant_id=draft["tenant_id"], finding_id=before.id)
        FindingService._record_lifecycle_action(
            c,
            before=before,
            after=restored,
            actor_user_id=actor,
            action="restored",
            from_status="archived",
            to_status="pending_review",
            detail={"source": "ai_draft_human_publication", "draft_id": str(draft["id"])},
            occurred_at=now,
        )
        before = restored
        decision = "accepted"
        values = {
            "status": decision,
            "accepted_payload": content,
            "reviewed_by_user_id": actor,
            "reviewed_at": now,
            "review_comment": reason,
            "updated_at": now,
        }
    else:
        if before.status != "accepted":
            raise MeetingStateError("正式办理缺少本次具名确认")
        decision = "applied"
        values = {
            "status": decision,
            "applied_by_user_id": actor,
            "applied_at": now,
            "applied_entity_type": entity_type,
            "applied_entity_id": entity_id,
            "updated_at": now,
        }
    c.execute(
        tables.findings.update()
        .where(tables.findings.c.tenant_id == draft["tenant_id"], tables.findings.c.id == before.id)
        .values(**values)
    )
    c.execute(
        tables.finding_actions.insert().values(
            id=uuid4(),
            tenant_id=draft["tenant_id"],
            project_id=draft["project_id"],
            finding_id=before.id,
            action=decision,
            actor_user_id=actor,
            from_status=before.status,
            to_status=decision,
            detail={
                "source": "ai_draft_human_publication",
                "draft_id": str(draft["id"]),
                "comment": reason,
                "entity_type": entity_type if entity_id else None,
                "entity_id": str(entity_id) if entity_id else None,
            },
            created_at=now,
        )
    )
    after = FindingService._get(c, tenant_id=draft["tenant_id"], finding_id=before.id)
    FindingService._feedback_event(
        c, before=before, after=after, actor_user_id=actor, decision=decision, occurred_at=now
    )
