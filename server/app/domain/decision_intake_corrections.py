"""Append reviewed corrections to historical Decision/Issue source relationships."""

from contextlib import nullcontext
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.conversations import ConversationError
from app.domain.decision_intake_state import source_states
from app.domain.decision_intake_targets import read_target, snapshot
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.knowledge_push import KnowledgeAccessError
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class DecisionSourceCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_revision: int = Field(ge=0)
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    action: Literal["withdraw", "reassign"]
    target_decision_id: UUID | None = None
    expected_decision_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    target_issue_id: UUID | None = None
    expected_issue_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=2000)
    impact_note: str = Field(min_length=1, max_length=4000)
    acknowledge_history: Literal[True]

    @model_validator(mode="after")
    def targets(self) -> "DecisionSourceCorrection":
        if self.action == "reassign":
            if self.target_decision_id is None or self.expected_decision_digest is None:
                raise ValueError("请读取并核对目标决策当前版本")
            if (self.target_issue_id is None) != (self.expected_issue_digest is None):
                raise ValueError("所选问题及当前版本须同时提供")
        elif any(
            v is not None
            for v in (
                self.target_decision_id,
                self.expected_decision_digest,
                self.target_issue_id,
                self.expected_issue_digest,
            )
        ):
            raise ValueError("撤回来源关联不应选择新目标")
        return self


def source(
    c: Connection, ctx: AuthContext, project: UUID, identity: UUID, *, write: bool = False
) -> Any:
    KnowledgeCorrectionService._authorize(
        c,
        ctx.tenant.id,
        ctx.user.id,
        project,
        Action.WORK_ITEM_EDIT if write else Action.WORK_ITEM_VIEW,
    )
    t = tables.decision_intake_rows
    q = select(t).where(
        t.c.tenant_id == ctx.tenant.id, t.c.project_id == project, t.c.id == identity
    )
    row = c.execute(q.with_for_update() if write else q).mappings().one_or_none()
    if row is None:
        raise ConversationError("当前项目没有这条历史决策来源")
    return row


def basis(
    c: Connection, tenant: UUID, project: UUID, row: Any, *, lock: bool = False
) -> dict[str, Any]:
    state = source_states(c, tenant, [row])[row["id"]]
    values = {}
    for kind in ("decision", "issue"):
        identity = state[f"current_{kind}_id"]
        target = (
            read_target(c, tenant, project, kind, UUID(identity), lock=lock) if identity else None
        )
        values[f"current_{kind}"] = snapshot(target, kind) if target is not None else None
    result = {**state, **values}
    result["digest"] = digest(result)
    for kind in ("decision", "issue"):
        value = values[f"current_{kind}"]
        result[f"current_{kind}_digest"] = digest(value) if value is not None else None
    return result


class DecisionIntakeCorrections:
    def __init__(self, engine: Engine):
        self.engine = engine

    def detail(
        self, ctx: AuthContext, project: UUID, identity: UUID, *, before_revision: int | None = None
    ) -> dict[str, Any]:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            row = source(c, ctx, project, identity)
            value = basis(c, ctx.tenant.id, project, row)
            t, u = tables.decision_intake_corrections, tables.users
            query = (
                select(t, u.c.display_name.label("actor_name"))
                .join(u, (u.c.tenant_id == t.c.tenant_id) & (u.c.id == t.c.created_by_user_id))
                .where(t.c.tenant_id == ctx.tenant.id, t.c.source_row_id == identity)
            )
            if before_revision is not None:
                query = query.where(t.c.revision < before_revision)
            history = c.execute(query.order_by(t.c.revision.desc()).limit(21)).mappings().all()
            can_edit = True
            try:
                KnowledgeCorrectionService._authorize(
                    c, ctx.tenant.id, ctx.user.id, project, Action.WORK_ITEM_EDIT
                )
            except KnowledgeAccessError:
                can_edit = False
            return {
                **value,
                "can_edit": can_edit,
                "source": {
                    key: v
                    for key, v in _plain(row).items()
                    if key not in {"tenant_id", "preview_id"}
                },
                "history": [_plain(item) for item in history[:20]],
                "next_before_revision": history[19]["revision"] if len(history) > 20 else None,
            }

    def correct(
        self,
        ctx: AuthContext,
        project: UUID,
        identity: UUID,
        body: DecisionSourceCorrection,
        *,
        connection: Connection | None = None,
    ) -> dict[str, Any]:
        signature = digest(body.model_dump(mode="json", exclude={"request_id"}))
        with nullcontext(connection) if connection is not None else self.engine.begin() as c:
            if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
                raise ConversationError("项目当前不可办理")
            row = source(c, ctx, project, identity, write=True)
            t = tables.decision_intake_corrections
            prior = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.source_row_id == identity,
                        t.c.request_id == body.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior is not None:
                if prior["request_digest"] != signature:
                    raise ConversationError("此请求号已对应其他纠错内容，请读取原回执")
                return {"receipt": _plain(prior)}
            current = basis(c, ctx.tenant.id, project, row, lock=True)
            if (
                current["revision"] != body.expected_revision
                or current["digest"] != body.expected_digest
            ):
                raise ConversationError("来源关系或当前业务内容已变化，请刷新后核对影响")
            old_decision = (
                UUID(current["current_decision_id"]) if current["current_decision_id"] else None
            )
            old_issue = UUID(current["current_issue_id"]) if current["current_issue_id"] else None
            if (old_decision, old_issue) == (body.target_decision_id, body.target_issue_id):
                raise ConversationError("当前关联与本次目标相同，无需重复保存")
            targets = {}
            for kind, target_id, expected in (
                ("decision", body.target_decision_id, body.expected_decision_digest),
                ("issue", body.target_issue_id, body.expected_issue_digest),
            ):
                record = (
                    read_target(c, ctx.tenant.id, project, kind, target_id, lock=True)
                    if target_id
                    else None
                )
                value = snapshot(record, kind) if record is not None else None
                if target_id and (
                    value is None
                    or (
                        kind == "issue"
                        and record is not None
                        and record.get("withdrawn_at") is not None
                    )
                    or digest(value) != expected
                ):
                    raise ConversationError("目标决策或问题已变化，请重新读取并核对")
                targets[kind] = value
            receipt = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=ctx.tenant.id,
                        project_id=project,
                        source_row_id=identity,
                        revision=current["revision"] + 1,
                        action=body.action,
                        previous_decision_id=old_decision,
                        previous_issue_id=old_issue,
                        target_decision_id=body.target_decision_id,
                        target_issue_id=body.target_issue_id,
                        request_id=body.request_id,
                        request_digest=signature,
                        reason=body.reason,
                        impact_note=body.impact_note,
                        before_snapshot={
                            "decision": current["current_decision"],
                            "issue": current["current_issue"],
                        },
                        after_snapshot=targets,
                        created_by_user_id=ctx.user.id,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            EventAuditWriter(
                c, tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, project_id=project
            ).record(
                EventDraft(
                    event_id=f"decision-intake:{identity}:correction:{receipt['revision']}",
                    event_type="DECISION_INTAKE_SOURCE_RECORDED",
                    source="decision_intake_service",
                    entity_id=identity,
                    payload={
                        "source_row_id": str(identity),
                        "record_id": str(receipt["id"]),
                        "action": body.action,
                    },
                ),
                AuditDraft(
                    action="decision_intake.source_correct",
                    before_snapshot=current,
                    after_snapshot=_plain(receipt),
                ),
            )
            return {"receipt": _plain(receipt)}
