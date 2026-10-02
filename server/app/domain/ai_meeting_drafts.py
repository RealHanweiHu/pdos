"""Source-bound AI minutes, a single trial confirmation and reversible draft history.

The AI principal may prepare minutes only under a separately granted project
scope. Humans retain all authority to confirm, edit, withdraw or publish.
Automatic qualification is deliberately not inferred from a model's confidence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, RowMapping, select, text, tuple_

from app.ai.rollout_guard import require_live_key
from app.auth.roles import Action, is_allowed
from app.db.schema import tables
from app.domain.ai_meeting_draft_content import (
    CAPABILITIES,
    OPERATIONS,
    DraftKind,
    body_text,
    consumed,
    edit_content,
    publish_work,
    record_publication_finding,
    validate_source,
)
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.knowledge_push import KnowledgeAccessError, KnowledgeVersionError
from app.domain.meeting_minutes import MeetingMinutesService
from app.domain.meeting_minutes_proposals import MeetingMinutesPayload
from app.domain.meetings import MeetingNotFoundError, MeetingService, MeetingStateError
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

OPERATION = "meeting.minutes.draft"
CAPABILITY = "knowledge_lite.meeting_minutes"


class ScopeChange(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_revision: int = Field(ge=0)
    enabled: bool
    reason: str = Field(min_length=1, max_length=1000)


class DraftChange(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_revision: int = Field(ge=0)
    action: Literal["confirm", "edit", "withdraw", "publish"]
    reason: str = Field(min_length=1, max_length=1000)
    payload: dict[str, Any] | None = None
    body: str | None = Field(default=None, min_length=1, max_length=20000)
    unresolved_points: str | None = Field(default=None, min_length=1, max_length=5000)


def latest_scope(
    c: Connection, tenant: UUID, project: UUID, operation: str = OPERATION
) -> RowMapping | None:
    t = tables.ai_write_scope_revisions
    return (
        c.execute(
            select(t)
            .where(
                t.c.tenant_id == tenant, t.c.project_id == project, t.c.operation_key == operation
            )
            .order_by(t.c.revision.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def policy(c: Connection, tenant: UUID) -> RowMapping | None:
    t = tables.ai_write_policies
    return (
        c.execute(select(t).where(t.c.tenant_id == tenant).order_by(t.c.revision.desc()).limit(1))
        .mappings()
        .one_or_none()
    )


def capture_minutes_draft(
    c: Connection,
    *,
    row: RowMapping,
    finding_id: UUID,
    payload: Any,
    snapshot: dict[str, Any],
    invocation_id: UUID,
    now: datetime,
    kind: DraftKind = "minutes",
) -> UUID | None:
    """Capture trial or qualified direct drafts; neither is a formal version."""
    c.execute(
        select(tables.tenants.c.id).where(tables.tenants.c.id == row["tenant_id"]).with_for_update()
    )
    if not lock_project_write_scope(c, tenant_id=row["tenant_id"], project_id=row["project_id"]):
        raise MeetingNotFoundError
    operation, capability = OPERATIONS[kind], CAPABILITIES[kind]
    if row["run_context"].get("reading_event_trigger") is not None:
        from app.ai.meeting_event_runs import require_current

        require_current(c, row)
    settings = policy(c, row["tenant_id"])
    if settings is None or settings["mode"] != "tiered":
        return None
    preference = settings["operation_settings"].get(operation, {}).get("mode", "disabled")
    if preference == "disabled":
        return None
    grant = latest_scope(c, row["tenant_id"], row["project_id"], operation)
    if grant is None or not grant["enabled"] or grant["principal_id"] != settings["principal_id"]:
        return None
    require_live_key(capability)
    try:
        KnowledgeCorrectionService._authorize(
            c, row["tenant_id"], row["requested_by_user_id"], row["project_id"], Action.MEETING_VIEW
        )
    except KnowledgeAccessError as error:
        raise MeetingStateError("请求人的当前会议读取范围已失效") from error

    invocation = c.execute(
        select(tables.model_invocations.c.id).where(
            tables.model_invocations.c.tenant_id == row["tenant_id"],
            tables.model_invocations.c.project_id == row["project_id"],
            tables.model_invocations.c.run_id == row["id"],
            tables.model_invocations.c.id == invocation_id,
            tables.model_invocations.c.status == "succeeded",
        )
    ).scalar_one_or_none()
    if invocation is None or row["requested_by_user_id"] is None:
        raise MeetingStateError("AI草稿缺少实际调用或具名请求来源")
    validate_source(
        c, row["tenant_id"], row["project_id"], kind, snapshot, payload.model_dump(mode="json")
    )
    t = tables.ai_meeting_drafts
    existing = c.execute(
        select(t.c.id).where(t.c.tenant_id == row["tenant_id"], t.c.finding_id == finding_id)
    ).scalar_one_or_none()
    if existing is not None:
        return UUID(str(existing))
    draft_id = uuid4()
    values = dict(
        id=draft_id,
        tenant_id=row["tenant_id"],
        project_id=row["project_id"],
        meeting_id=payload.meeting_id,
        principal_id=grant["principal_id"],
        policy_id=settings["id"],
        scope_revision_id=grant["id"],
        finding_id=finding_id,
        run_id=row["id"],
        model_invocation_id=invocation_id,
        requested_by_user_id=row["requested_by_user_id"],
        origin="ai",
        capture_mode="trial",
        draft_kind=kind,
        payload=payload.model_dump(mode="json"),
        source_snapshot=snapshot,
        created_at=now,
    )
    write_receipt = None
    if preference == "automatic":
        from app.domain.ai_meeting_direct_route import resolve_direct_route

        write_receipt = resolve_direct_route(
            c, draft=values, setting=settings["operation_settings"][operation], as_of=now
        )
        values["capture_mode"] = "direct" if write_receipt["route"] == "direct" else "trial"
    if write_receipt is not None:
        values["write_receipt"] = write_receipt
    c.execute(t.insert().values(**values))
    EventAuditWriter(
        c, tenant_id=row["tenant_id"], project_id=row["project_id"], actor_user_id=None
    ).record(
        EventDraft(
            event_id=f"ai-minutes:{draft_id}:created",
            event_type="AI_MINUTES_DRAFT_CREATED",
            source="ai_minutes_service",
            entity_id=draft_id,
            occurred_at=now,
            payload={
                "draft_id": str(draft_id),
                "principal_id": str(grant["principal_id"]),
                "run_id": str(row["id"]),
            },
        ),
        AuditDraft(
            action="ai_minutes.direct_write"
            if values["capture_mode"] == "direct"
            else "ai_minutes.prefill",
            after_snapshot={"origin": "ai", "draft_id": str(draft_id)},
            context={
                "writer_principal_id": str(grant["principal_id"]),
                "requested_by_user_id": str(row["requested_by_user_id"]),
                "model_invocation_id": str(invocation_id),
                "scope_revision_id": str(grant["id"]),
                "policy_id": str(settings["id"]),
                "write_receipt": write_receipt,
                **(
                    {"trigger_event": row["run_context"]["reading_event_trigger"]}
                    if row["run_context"].get("reading_event_trigger") is not None
                    else {}
                ),
            },
        ),
    )
    return draft_id


def _actions(c: Connection, draft: RowMapping, before: int | None = None) -> list[RowMapping]:
    t = tables.ai_meeting_draft_actions
    query = (
        select(t, tables.users.c.display_name.label("actor_name"))
        .join(
            tables.users,
            (tables.users.c.tenant_id == t.c.tenant_id) & (tables.users.c.id == t.c.actor_user_id),
        )
        .where(t.c.tenant_id == draft["tenant_id"], t.c.draft_id == draft["id"])
    )
    if before is not None:
        query = query.where(t.c.revision < before)
    return list(c.execute(query.order_by(t.c.revision.desc()).limit(21)).mappings())


def _serialize(c: Connection, draft: RowMapping) -> dict[str, Any]:
    actions = _actions(c, draft)
    last = actions[0] if actions else None
    consumed_id = consumed(c, draft)
    current = True
    try:
        validate_source(
            c,
            draft["tenant_id"],
            draft["project_id"],
            draft["draft_kind"],
            draft["source_snapshot"],
            draft["payload"],
        )
    except (ValueError, MeetingNotFoundError):
        current = False
    initial_body, initial_unresolved = body_text(draft["draft_kind"], draft["payload"])
    stop = None
    if draft["capture_mode"] == "direct":
        stops = tables.ai_write_runtime_stops
        stop = c.execute(
            select(stops.c.id).where(
                stops.c.tenant_id == draft["tenant_id"],
                stops.c.project_id == draft["project_id"],
                stops.c.policy_id == draft["policy_id"],
                stops.c.operation_key == OPERATIONS[draft["draft_kind"]],
                stops.c.binding_digest == (draft["write_receipt"] or {}).get("binding_digest"),
            )
        ).scalar_one_or_none()
    return _plain(
        {
            **dict(draft),
            "current_payload": (
                {
                    **draft["payload"],
                    "body": last["body"],
                    "unresolved_points": last["unresolved_points"],
                }
                if draft["draft_kind"] == "minutes" and last
                else last["payload"]
                if last and last["payload"] is not None
                else draft["payload"]
            ),
            "writer_name": "PDOS Agent",
            "automatic_stop_reason": (
                "该版本自动草稿因撤回比例超限已暂停，后续生成需逐次确认。"
                if stop is not None
                else None
            ),
            "revision": last["revision"] if last else 0,
            "state": "published"
            if consumed_id
            else "withdrawn"
            if last and last["action"] == "withdraw"
            else "active"
            if last or draft["capture_mode"] == "direct"
            else "pending_confirmation",
            "review_required": bool(
                draft["capture_mode"] == "direct"
                and (draft["write_receipt"] or {}).get("sampled") is True
                and not last
                and not consumed_id
            ),
            "body": last["body"] if last else initial_body,
            "unresolved_points": last["unresolved_points"] if last else initial_unresolved,
            "human_edited": c.execute(
                select(tables.ai_meeting_draft_actions.c.id)
                .where(
                    tables.ai_meeting_draft_actions.c.tenant_id == draft["tenant_id"],
                    tables.ai_meeting_draft_actions.c.draft_id == draft["id"],
                    tables.ai_meeting_draft_actions.c.action == "edit",
                )
                .limit(1)
            ).first()
            is not None,
            "source_current": current,
            "published_entity_id": consumed_id,
            "official_minutes_id": consumed_id if draft["draft_kind"] == "minutes" else None,
            "history": [dict(a) for a in actions[:20]],
            "history_next_before": actions[19]["revision"] if len(actions) > 20 else None,
        }
    )


class AiMinutesDraftService:
    def __init__(self, engine: Engine, kind: DraftKind = "minutes") -> None:
        self.engine = engine
        self.kind = kind
        self.operation = OPERATIONS[kind]
        self.capability = CAPABILITIES[kind]
        self.manage_action = Action.WORK_ITEM_EDIT if kind == "decisions" else Action.MEETING_MANAGE

    def get(
        self, tenant: UUID, project: UUID, meeting: UUID, actor: UUID, before: UUID | None = None
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            KnowledgeCorrectionService._authorize(c, tenant, actor, project, Action.MEETING_VIEW)
            MeetingService._get(c, tenant_id=tenant, project_id=project, meeting_id=meeting)
            role = c.execute(
                select(tables.users.c.role).where(
                    tables.users.c.tenant_id == tenant, tables.users.c.id == actor
                )
            ).scalar_one()
            scope = latest_scope(c, tenant, project, self.operation)
            settings = policy(c, tenant)
            t = tables.ai_meeting_drafts
            query = select(t).where(
                t.c.tenant_id == tenant,
                t.c.project_id == project,
                t.c.draft_kind == self.kind,
                t.c.meeting_id == meeting,
            )
            if before:
                anchor = c.execute(
                    select(t.c.created_at, t.c.id).where(
                        t.c.tenant_id == tenant,
                        t.c.project_id == project,
                        t.c.draft_kind == self.kind,
                        t.c.meeting_id == meeting,
                        t.c.id == before,
                    )
                ).one_or_none()
                if anchor is None:
                    raise KnowledgeVersionError("草稿分页位置已不可用")
                query = query.where(
                    tuple_(t.c.created_at, t.c.id) < tuple_(anchor.created_at, anchor.id)
                )
            rows = (
                c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21))
                .mappings()
                .all()
            )
            return _plain(
                {
                    "items": [_serialize(c, r) for r in rows[:20]],
                    "current_user_id": str(actor),
                    "draft_kind": self.kind,
                    "next_before": rows[19]["id"] if len(rows) > 20 else None,
                    "scope": {
                        "revision": scope["revision"] if scope else 0,
                        "enabled": bool(scope and scope["enabled"]),
                    },
                    "can_manage_scope": is_allowed(role, Action.MODEL_GOVERNANCE_MANAGE),
                    "can_manage": is_allowed(role, self.manage_action),
                    "policy_ready": bool(
                        settings
                        and settings["mode"] == "tiered"
                        and settings["operation_settings"][self.operation]["mode"] != "disabled"
                    ),
                    "notice": "草稿按当前授权和资格采用自动写入或逐次确认；抽检单独标记。"
                    "正式发布仍由具名人员办理。",
                }
            )

    def history(
        self,
        tenant: UUID,
        project: UUID,
        meeting: UUID,
        draft_id: UUID,
        actor: UUID,
        before: int | None,
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            KnowledgeCorrectionService._authorize(c, tenant, actor, project, Action.MEETING_VIEW)
            t = tables.ai_meeting_drafts
            draft = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == tenant,
                        t.c.project_id == project,
                        t.c.draft_kind == self.kind,
                        t.c.meeting_id == meeting,
                        t.c.id == draft_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if draft is None:
                raise MeetingNotFoundError
            rows = _actions(c, draft, before)
            return _plain(
                {
                    "items": [dict(r) for r in rows[:20]],
                    "next_before": rows[19]["revision"] if len(rows) > 20 else None,
                }
            )

    def change_scope(
        self, tenant: UUID, project: UUID, actor: UUID, change: ScopeChange
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            c.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"ai-minutes:{tenant}:{actor}:{change.request_id}"},
            )
            if not lock_project_write_scope(c, tenant_id=tenant, project_id=project):
                raise MeetingNotFoundError
            KnowledgeCorrectionService._authorize(
                c, tenant, actor, project, Action.MODEL_GOVERNANCE_MANAGE
            )
            # Scope revisions never borrow the human's membership or permission.
            settings = policy(c, tenant)
            if settings is None:
                raise KnowledgeVersionError("请先在AI治理页保存租户政策，登记独立AI身份")
            t = tables.ai_write_scope_revisions
            signature = digest(
                {
                    "kind": self.kind,
                    "project_id": str(project),
                    **change.model_dump(mode="json", exclude={"request_id"}),
                }
            )
            old = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == tenant,
                        t.c.actor_user_id == actor,
                        t.c.request_id == change.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old:
                if old["request_digest"] != signature:
                    raise KnowledgeVersionError("本请求已用于其他范围设置")
                return {"revision": old["revision"], "reused": True}
            current = latest_scope(c, tenant, project, self.operation)
            revision = current["revision"] if current else 0
            if change.expected_revision != revision:
                raise KnowledgeVersionError("项目AI范围已变化，请刷新后核对")
            row_id, now = uuid4(), datetime.now(UTC)
            c.execute(
                t.insert().values(
                    id=row_id,
                    tenant_id=tenant,
                    project_id=project,
                    principal_id=settings["principal_id"],
                    operation_key=self.operation,
                    revision=revision + 1,
                    enabled=change.enabled,
                    actor_user_id=actor,
                    request_id=change.request_id,
                    request_digest=signature,
                    reason=change.reason,
                    created_at=now,
                )
            )
            EventAuditWriter(c, tenant_id=tenant, project_id=project, actor_user_id=actor).record(
                EventDraft(
                    event_id=f"ai-scope:{row_id}",
                    event_type="AI_WRITE_SCOPE_REVISED",
                    source="ai_minutes_service",
                    entity_id=row_id,
                    payload={
                        "operation_key": self.operation,
                        "revision": revision + 1,
                        "enabled": change.enabled,
                    },
                ),
                AuditDraft(
                    action="ai_scope.revise",
                    before_snapshot={"enabled": bool(current and current["enabled"])},
                    after_snapshot={"enabled": change.enabled},
                    context={
                        "reason": change.reason,
                        "principal_id": str(settings["principal_id"]),
                    },
                ),
            )
            return {"revision": revision + 1, "reused": False}

    def change(
        self,
        tenant: UUID,
        project: UUID,
        meeting: UUID,
        draft_id: UUID,
        actor: UUID,
        change: DraftChange,
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            c.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"ai-minutes:{tenant}:{actor}:{change.request_id}"},
            )
            if not lock_project_write_scope(c, tenant_id=tenant, project_id=project):
                raise MeetingNotFoundError
            KnowledgeCorrectionService._authorize(c, tenant, actor, project, self.manage_action)
            t = tables.ai_meeting_drafts
            draft = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == tenant,
                        t.c.project_id == project,
                        t.c.draft_kind == self.kind,
                        t.c.meeting_id == meeting,
                        t.c.id == draft_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if draft is None:
                raise MeetingNotFoundError
            return self._change(c, draft, actor, change)

    def _change(
        self, c: Connection, draft: RowMapping, actor: UUID, change: DraftChange
    ) -> dict[str, Any]:
        t = tables.ai_meeting_draft_actions
        signature = digest(
            {"draft_id": str(draft["id"]), **change.model_dump(mode="json", exclude={"request_id"})}
        )
        replay = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == draft["tenant_id"],
                    t.c.actor_user_id == actor,
                    t.c.request_id == change.request_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if replay:
            if replay["request_digest"] != signature:
                raise KnowledgeVersionError("本请求已用于其他草稿操作")
            return {"receipt": _plain(dict(replay)), "reused": True}
        state = _serialize(c, draft)
        if state["revision"] != change.expected_revision:
            raise KnowledgeVersionError("草稿已有新版本，请刷新后核对")
        if state["state"] in {"published", "withdrawn"}:
            raise KnowledgeVersionError("草稿已发布或撤回，历史保留只读")
        if change.action == "withdraw" and state["human_edited"]:
            raise KnowledgeVersionError("已有人修改本稿，请保留人工内容；不能直接撤回AI原稿")
        if change.action in {"confirm", "publish"}:
            require_live_key(self.capability)
        if change.action != "withdraw" and not state["source_current"]:
            raise KnowledgeVersionError("原转录或正式纪要已变化，请基于当前来源重新生成")
        if (
            change.action == "confirm"
            and state["state"] != "pending_confirmation"
            and not state["review_required"]
        ):
            raise KnowledgeVersionError("本稿已确认，无需再次确认")
        if change.action in {"edit", "publish"} and state["state"] != "active":
            raise KnowledgeVersionError("请先确认采用草稿，再修订或正式发布")
        content = state["current_payload"]
        if change.action != "edit" and any(
            value is not None for value in (change.body, change.unresolved_points, change.payload)
        ):
            raise MeetingStateError("仅修订操作可提交正文")
        if change.action == "edit":
            if self.kind == "minutes":
                if (
                    change.body is None
                    or change.unresolved_points is None
                    or change.payload is not None
                ):
                    raise MeetingStateError("纪要修订须填写正文及未决事项")
                content = {
                    **content,
                    "body": change.body,
                    "unresolved_points": change.unresolved_points,
                }
            else:
                if (
                    change.payload is None
                    or change.body is not None
                    or change.unresolved_points is not None
                ):
                    raise MeetingStateError("请填写该类草稿的完整修订内容")
                content = edit_content(self.kind, draft["payload"], change.payload)
            if content == state["current_payload"]:
                raise MeetingStateError("草稿内容未变化")
        body, unresolved = body_text(self.kind, content)
        finding = (
            c.execute(
                select(tables.findings)
                .where(
                    tables.findings.c.tenant_id == draft["tenant_id"],
                    tables.findings.c.id == draft["finding_id"],
                )
                .with_for_update()
            )
            .mappings()
            .one()
        )
        if finding["status"] not in {"pending_review", "archived"}:
            raise KnowledgeVersionError("原候选已沿其他流程办理，请回查原候选")
        now = datetime.now(UTC)
        if finding["status"] == "pending_review":
            c.execute(
                tables.findings.update()
                .where(tables.findings.c.id == finding["id"])
                .values(status="archived", updated_at=now)
            )
            c.execute(
                tables.finding_actions.insert().values(
                    id=uuid4(),
                    tenant_id=draft["tenant_id"],
                    project_id=draft["project_id"],
                    finding_id=finding["id"],
                    action="archived",
                    actor_user_id=actor,
                    from_status="pending_review",
                    to_status="archived",
                    detail={"reason": "转入AI会议草稿办理", "draft_id": str(draft["id"])},
                    created_at=now,
                )
            )
        official = task_id = decision_id = None
        if change.action == "publish":
            record_publication_finding(c, draft, content, actor, now, change.reason)
        if change.action == "publish" and self.kind == "minutes":
            payload = MeetingMinutesPayload.model_validate(draft["payload"])
            result = MeetingMinutesService(self.engine).confirm(
                tenant_id=draft["tenant_id"],
                project_id=draft["project_id"],
                meeting_id=draft["meeting_id"],
                actor_id=actor,
                request_id=change.request_id,
                expected_version=payload.base_version,
                body=body,
                unresolved_points=unresolved,
                reason=change.reason,
                source_finding_id=draft["finding_id"],
                connection=c,
                now=now,
                citations=[
                    {
                        "transcript_id": payload.transcript_id,
                        "segment_id": q.segment_id,
                        "expected_digest": payload.source_digest,
                        "exact_quote": q.exact_quote,
                    }
                    for q in payload.citations
                ],
            )
            official = UUID(result["id"])
        elif change.action == "publish":
            task_id, decision_id = publish_work(self.engine, c, draft, content, actor, now)
        if change.action == "publish":
            target = official or task_id or decision_id
            if target is None:
                raise MeetingStateError("正式办理未返回实际业务记录")
            # Preserve the original strictly ordered review/application receipts.
            # This is the observed completion time, not a fabricated clock offset.
            completed_at = datetime.now(UTC)
            if completed_at <= now:
                raise MeetingStateError("当前时钟无法记录办理先后顺序，请稍后重试")
            record_publication_finding(
                c, draft, content, actor, completed_at, change.reason, entity_id=target
            )
            now = completed_at
        values = dict(
            id=uuid4(),
            tenant_id=draft["tenant_id"],
            project_id=draft["project_id"],
            draft_id=draft["id"],
            revision=state["revision"] + 1,
            action=change.action,
            actor_user_id=actor,
            request_id=change.request_id,
            request_digest=signature,
            reason=change.reason,
            body=body,
            unresolved_points=unresolved,
            official_minutes_id=official,
            published_task_id=task_id,
            published_decision_id=decision_id,
            payload=content if self.kind != "minutes" else None,
            created_at=now,
        )
        c.execute(t.insert().values(**values))
        if change.action == "withdraw" and draft["capture_mode"] == "direct":
            from app.contracts.ai_write_qualification import QualificationConfiguration
            from app.domain.ai_meeting_write_monitor import quality_monitor

            original_receipt = draft["write_receipt"]
            quality_monitor(
                c,
                tenant_id=draft["tenant_id"],
                project_id=draft["project_id"],
                policy_id=draft["policy_id"],
                operation_key=self.operation,
                binding_digest=original_receipt["binding_digest"],
                configuration=QualificationConfiguration.model_validate(
                    original_receipt["configuration"]
                ),
                as_of=now,
            )
        EventAuditWriter(
            c, tenant_id=draft["tenant_id"], project_id=draft["project_id"], actor_user_id=actor
        ).record(
            EventDraft(
                event_id=f"ai-minutes:{draft['id']}:{values['revision']}",
                event_type="AI_MINUTES_DRAFT_CHANGED",
                source="ai_minutes_service",
                entity_id=draft["id"],
                payload={
                    "action": change.action,
                    "revision": values["revision"],
                    "draft_id": str(draft["id"]),
                },
            ),
            AuditDraft(
                action=f"ai_minutes.{change.action}",
                before_snapshot={"revision": state["revision"], "state": state["state"]},
                after_snapshot={"revision": values["revision"], "action": change.action},
                context={
                    "reason": change.reason,
                    "original_writer_principal_id": str(draft["principal_id"]),
                },
            ),
        )
        return {"receipt": _plain(values), "reused": False}

    def withdraw_run(
        self,
        tenant: UUID,
        project: UUID,
        meeting: UUID,
        run_id: UUID,
        actor: UUID,
        request_id: UUID,
        reason: str,
    ) -> dict[str, Any]:
        """Undo this minutes-generation run; preserve edited or consumed records."""
        from uuid import uuid5

        signature = digest(
            {
                "kind": self.kind,
                "project": str(project),
                "meeting": str(meeting),
                "run": str(run_id),
                "reason": reason,
            }
        )
        key = "ai-minutes-run:" + digest(
            {"tenant": str(tenant), "actor": str(actor), "request": str(request_id)}
        )
        with self.engine.begin() as c:
            c.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": key})
            if not lock_project_write_scope(c, tenant_id=tenant, project_id=project):
                raise MeetingNotFoundError
            KnowledgeCorrectionService._authorize(c, tenant, actor, project, self.manage_action)
            replay = c.execute(
                select(tables.events.c.payload).where(
                    tables.events.c.tenant_id == tenant,
                    tables.events.c.project_id == project,
                    tables.events.c.source == "ai_minutes_service",
                    tables.events.c.event_id == key,
                )
            ).scalar_one_or_none()
            if replay:
                if replay["request_digest"] != signature:
                    raise KnowledgeVersionError("本请求已用于其他纪要运行撤回")
                return {"items": replay["items"], "reused": True}
            t = tables.ai_meeting_drafts
            drafts = (
                c.execute(
                    select(t)
                    .where(
                        t.c.tenant_id == tenant,
                        t.c.project_id == project,
                        t.c.draft_kind == self.kind,
                        t.c.meeting_id == meeting,
                        t.c.run_id == run_id,
                    )
                    .order_by(t.c.id)
                )
                .mappings()
                .all()
            )
            if not drafts:
                raise MeetingNotFoundError
            items = []
            for draft in drafts:
                state = _serialize(c, draft)
                skip = (
                    "已被正式业务记录引用"
                    if state["state"] == "published"
                    else "已有人工修改"
                    if state["human_edited"]
                    else "已撤回"
                    if state["state"] == "withdrawn"
                    else None
                )
                if skip:
                    items.append(
                        {"draft_id": str(draft["id"]), "result": "skipped", "reason": skip}
                    )
                    continue
                self._change(
                    c,
                    draft,
                    actor,
                    DraftChange(
                        request_id=uuid5(request_id, str(draft["id"])),
                        expected_revision=state["revision"],
                        action="withdraw",
                        reason=reason,
                    ),
                )
                items.append(
                    {
                        "draft_id": str(draft["id"]),
                        "result": "withdrawn",
                        "reason": "已生成反向回执",
                    }
                )
            EventAuditWriter(c, tenant_id=tenant, project_id=project, actor_user_id=actor).record(
                EventDraft(
                    event_id=key,
                    event_type="AI_MINUTES_RUN_WITHDRAWN",
                    source="ai_minutes_service",
                    entity_id=run_id,
                    payload={"request_digest": signature, "items": items},
                ),
                AuditDraft(
                    action="ai_minutes.withdraw_run",
                    after_snapshot={"items": items},
                    context={"reason": reason},
                ),
            )
            return {"items": items, "reused": False}
