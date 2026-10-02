"""Current authorization and independent AI scope for confirmed event-Issue writes.

These checks never grant automatic qualification. The application service owns
its tenant -> project locks and checks the completed adapter before writing.
"""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, func, select

from app.ai.issue_event_proposal import KEY, OPERATION
from app.ai.rollout_guard import require_live_key
from app.ai.write_policy import POLICY_VERSION
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.ai_meeting_drafts import ScopeChange, latest_scope, policy
from app.domain.ai_write_policy import WritePolicyError
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

READ_ACTIONS = (Action.WORK_ITEM_VIEW, Action.QUALITY_VIEW, Action.PRODUCT_ENGINEERING_VIEW)


def authorize(c: Connection, context: AuthContext, project_id: UUID, *, write: bool) -> None:
    p, t = tables.projects, tables.tenants
    available = c.execute(
        select(p.c.id)
        .join(t, t.c.id == p.c.tenant_id)
        .where(
            p.c.tenant_id == context.tenant.id,
            p.c.id == project_id,
            t.c.status == "active",
        )
    ).first()
    if available is None:
        raise LookupError("项目不存在或当前不可用")
    for action in (*READ_ACTIONS, *((Action.WORK_ITEM_EDIT,) if write else ())):
        KnowledgeCorrectionService._authorize(
            c, context.tenant.id, context.user.id, project_id, action
        )


def _principal(c: Connection, tenant: UUID, principal_id: UUID) -> RowMapping:
    t = tables.ai_principals
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == tenant,
                t.c.id == principal_id,
                t.c.principal_kind == "ai",
                t.c.principal_key == "pdos-agent",
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise WritePolicyError("AI_ISSUE_PRINCIPAL_UNAVAILABLE", "当前独立 AI 写入身份不可用")
    return row


def write_settings(c: Connection, tenant: UUID, project: UUID) -> tuple[RowMapping, RowMapping]:
    """Read current controls under the application's existing tenant/project locks."""
    settings = policy(c, tenant)
    if (
        settings is None
        or settings["mode"] != "tiered"
        or settings["contract_version"] != POLICY_VERSION
    ):
        raise WritePolicyError("AI_ISSUE_POLICY_REQUIRED", "请先登记当前分级写入政策")
    mode = settings["operation_settings"].get(OPERATION, {}).get("mode", "disabled")
    if mode not in {"confirm", "automatic"}:
        raise WritePolicyError("AI_ISSUE_POLICY_DISABLED", "当前政策未开放事件问题建议的确认应用")
    grant = latest_scope(c, tenant, project, OPERATION)
    if grant is None or not grant["enabled"] or grant["principal_id"] != settings["principal_id"]:
        raise WritePolicyError("AI_ISSUE_SCOPE_REQUIRED", "当前项目尚无匹配的独立 AI 建单授权")
    _principal(c, tenant, settings["principal_id"])
    require_live_key(KEY)
    return settings, grant


class ScopeService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, context: AuthContext, project_id: UUID) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            authorize(c, context, project_id, write=False)
            current = latest_scope(c, context.tenant.id, project_id, OPERATION)
            settings = policy(c, context.tenant.id)
            try:
                KnowledgeCorrectionService._authorize(
                    c,
                    context.tenant.id,
                    context.user.id,
                    project_id,
                    Action.MODEL_GOVERNANCE_MANAGE,
                )
                can_manage = True
            except PermissionError:
                can_manage = False
            return _plain(
                {
                    "operation_key": OPERATION,
                    "scope": {
                        "revision": current["revision"] if current else 0,
                        "enabled": bool(current and current["enabled"]),
                        "principal_id": current["principal_id"] if current else None,
                    },
                    "policy_id": settings["id"] if settings else None,
                    "principal_id": settings["principal_id"] if settings else None,
                    "can_manage_scope": can_manage,
                    "notice": "此授权仅用于事件问题建议的具名确认应用，不授予自动建单资格。",
                }
            )

    def change(self, context: AuthContext, project_id: UUID, change: ScopeChange) -> dict[str, Any]:
        tenant, actor = context.tenant.id, context.user.id
        with self.engine.begin() as c:
            # Same order as policy changes and actual AI business application.
            state = c.execute(
                select(tables.tenants.c.status)
                .where(tables.tenants.c.id == tenant)
                .with_for_update()
            ).scalar_one_or_none()
            if state != "active" or not lock_project_write_scope(
                c, tenant_id=tenant, project_id=project_id
            ):
                raise LookupError("项目不存在或当前不可用")
            authorize(c, context, project_id, write=False)
            KnowledgeCorrectionService._authorize(
                c, tenant, actor, project_id, Action.MODEL_GOVERNANCE_MANAGE
            )
            t = tables.ai_write_scope_revisions
            signature = digest(
                {
                    "operation_key": OPERATION,
                    "project_id": str(project_id),
                    **change.model_dump(mode="json", exclude={"request_id"}),
                }
            )
            previous = (
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
            if previous is not None:
                if (
                    previous["request_digest"] != signature
                    or previous["operation_key"] != OPERATION
                    or previous["project_id"] != project_id
                ):
                    raise WritePolicyError(
                        "AI_ISSUE_SCOPE_REQUEST_CONFLICT", "本请求已用于其他授权设置"
                    )
                return {"revision": previous["revision"], "reused": True}
            settings = policy(c, tenant)
            if settings is None:
                raise WritePolicyError(
                    "AI_ISSUE_POLICY_REQUIRED", "请先在 AI 治理页登记独立 AI 身份与政策"
                )
            _principal(c, tenant, settings["principal_id"])
            current = latest_scope(c, tenant, project_id, OPERATION)
            revision = current["revision"] if current else 0
            if revision != change.expected_revision:
                raise WritePolicyError(
                    "AI_ISSUE_SCOPE_CHANGED", "项目 AI 授权已有变化，请刷新后核对"
                )
            identity = uuid4()
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            c.execute(
                t.insert().values(
                    id=identity,
                    tenant_id=tenant,
                    project_id=project_id,
                    principal_id=settings["principal_id"],
                    operation_key=OPERATION,
                    revision=revision + 1,
                    enabled=change.enabled,
                    actor_user_id=actor,
                    request_id=change.request_id,
                    request_digest=signature,
                    reason=change.reason,
                    created_at=now,
                )
            )
            EventAuditWriter(
                c, tenant_id=tenant, project_id=project_id, actor_user_id=actor
            ).record(
                EventDraft(
                    event_id=f"ai-scope:{identity}",
                    event_type="AI_WRITE_SCOPE_REVISED",
                    # Retain the catalog's existing producer for this shared event.
                    source="ai_minutes_service",
                    entity_id=identity,
                    occurred_at=now,
                    payload={
                        "operation_key": OPERATION,
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
                        "operation_key": OPERATION,
                        "policy_id": str(settings["id"]),
                    },
                ),
            )
            return {"revision": revision + 1, "reused": False}
