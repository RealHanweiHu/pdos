"""Append-only corrections to source associations, preserving every business Issue."""

from contextlib import nullcontext
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, or_, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.conversations import ConversationError
from app.domain.issue_intake_reuse import target_snapshot
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class SourceCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_revision: int = Field(ge=0)
    expected_current_updated_at: AwareDatetime | None = None
    action: Literal["withdraw", "reassign"]
    target_issue_id: UUID | None = None
    expected_target_updated_at: AwareDatetime | None = None
    reason: str = Field(min_length=1, max_length=2000)
    impact_note: str = Field(min_length=1, max_length=4000)
    acknowledge_history: Literal[True]

    @model_validator(mode="after")
    def target(self) -> "SourceCorrection":
        if self.action == "reassign":
            if self.target_issue_id is None or self.expected_target_updated_at is None:
                raise ValueError("请读取并核对重新关联的原问题")
        elif self.target_issue_id is not None or self.expected_target_updated_at is not None:
            raise ValueError("撤回关联不应指定新问题")
        return self


def source_states(c: Connection, tenant: UUID, sources: list[Any]) -> dict[UUID, dict[str, Any]]:
    if not sources:
        return {}
    t = tables.issue_intake_corrections
    rows = c.execute(
        select(t.c.source_row_id, t.c.revision, t.c.target_issue_id)
        .where(t.c.tenant_id == tenant, t.c.source_row_id.in_([source["id"] for source in sources]))
        .distinct(t.c.source_row_id)
        .order_by(t.c.source_row_id, t.c.revision.desc())
    ).mappings()
    latest = {row["source_row_id"]: row for row in rows}
    result = {}
    for source in sources:
        row = latest.get(source["id"])
        active = row["target_issue_id"] if row is not None else source["issue_id"]
        result[source["id"]] = {
            "source_row_id": str(source["id"]),
            "revision": row["revision"] if row is not None else 0,
            "state": "active" if active is not None else "withdrawn",
            "current_issue_id": str(active) if active else None,
            "current_issue_href": (
                f"/projects?project={source['project_id']}&tab=work-items&entity_id={active}"
            )
            if active
            else None,
        }
    return result


def source_state(c: Connection, tenant: UUID, source: Any) -> dict[str, Any]:
    return source_states(c, tenant, [source])[source["id"]]


def public_source(row: Any) -> dict[str, Any]:
    return {
        key: value for key, value in _plain(row).items() if key not in {"tenant_id", "preview_id"}
    } | {
        "document_href": (
            f"/projects?project={row['project_id']}&tab=documents&entity_id={row['document_id']}"
        ),
        "issue_href": (
            f"/projects?project={row['project_id']}&tab=work-items&entity_id={row['issue_id']}"
        ),
    }


class IssueIntakeCorrections:
    def __init__(self, engine: Engine):
        self.engine = engine

    @staticmethod
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
        t = tables.issue_intake_rows
        query = select(t).where(
            t.c.tenant_id == ctx.tenant.id, t.c.project_id == project, t.c.id == identity
        )
        row = c.execute(query.with_for_update() if write else query).mappings().one_or_none()
        if row is None:
            raise ConversationError("当前项目没有这条问题导入来源")
        return row

    @staticmethod
    def issue(c: Connection, tenant: UUID, project: UUID, identity: UUID) -> Any:
        t = tables.issues
        return (
            c.execute(
                select(t).where(
                    t.c.tenant_id == tenant, t.c.project_id == project, t.c.id == identity
                )
            )
            .mappings()
            .one_or_none()
        )

    def detail(
        self, ctx: AuthContext, project: UUID, identity: UUID, *, before_revision: int | None = None
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            source = self.source(c, ctx, project, identity)
            state = source_state(c, ctx.tenant.id, source)
            t = tables.issue_intake_corrections
            query = (
                select(t, tables.users.c.display_name.label("actor_name"))
                .join(
                    tables.users,
                    (tables.users.c.tenant_id == t.c.tenant_id)
                    & (tables.users.c.id == t.c.created_by_user_id),
                )
                .where(t.c.tenant_id == ctx.tenant.id, t.c.source_row_id == identity)
            )
            if before_revision is not None:
                query = query.where(t.c.revision < before_revision)
            history = c.execute(query.order_by(t.c.revision.desc()).limit(51)).mappings().all()
            current = (
                self.issue(c, ctx.tenant.id, project, UUID(state["current_issue_id"]))
                if state["current_issue_id"]
                else None
            )
            original = self.issue(c, ctx.tenant.id, project, source["issue_id"])
            return {
                "source": public_source(source),
                **state,
                "current_issue": target_snapshot(current) if current else None,
                "original_issue": target_snapshot(original) if original else None,
                "history": [_plain(row) for row in history[:50]],
                "next_before_revision": history[49]["revision"] if len(history) > 50 else None,
            }

    def correct(
        self,
        ctx: AuthContext,
        project: UUID,
        identity: UUID,
        body: SourceCorrection,
        *,
        connection: Connection | None = None,
    ) -> dict[str, Any]:
        signature = digest(body.model_dump(mode="json", exclude={"request_id"}))
        with nullcontext(connection) if connection is not None else self.engine.begin() as c:
            if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
                raise ConversationError("项目当前不可办理")
            source = self.source(c, ctx, project, identity, write=True)
            t = tables.issue_intake_corrections
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
                    raise ConversationError("此请求号已对应其他来源处理，请读取原回执")
                return {"receipt": _plain(prior)}
            state = source_state(c, ctx.tenant.id, source)
            if state["revision"] != body.expected_revision:
                raise ConversationError("来源关联已有后续处理，请刷新后重新核对")
            previous = UUID(state["current_issue_id"]) if state["current_issue_id"] else None
            if body.action == "withdraw" and previous is None:
                raise ConversationError("此来源关联已经撤回，历史保留，无需重复撤回")
            if body.action == "reassign" and previous == body.target_issue_id:
                raise ConversationError("所选问题已是当前关联，请核对是否需要其他纠正")
            before = self.issue(c, ctx.tenant.id, project, previous) if previous else None
            if (
                before is not None and before["updated_at"] != body.expected_current_updated_at
            ) or (before is None and body.expected_current_updated_at is not None):
                raise ConversationError("当前关联问题已变化，请刷新后重新核对影响说明")
            after = (
                self.issue(c, ctx.tenant.id, project, body.target_issue_id)
                if body.target_issue_id
                else None
            )
            if body.action == "reassign" and (
                after is None or after["updated_at"] != body.expected_target_updated_at
            ):
                raise ConversationError("新关联问题已变化或不可用，请重新读取并核对")
            receipt = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=ctx.tenant.id,
                        project_id=project,
                        source_row_id=identity,
                        revision=state["revision"] + 1,
                        action=body.action,
                        previous_issue_id=previous,
                        target_issue_id=body.target_issue_id,
                        request_id=body.request_id,
                        request_digest=signature,
                        reason=body.reason,
                        impact_note=body.impact_note,
                        before_snapshot=target_snapshot(before) if before else {},
                        after_snapshot=target_snapshot(after) if after else {},
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
                    event_id=f"issue-intake-source:{identity}:correction:{receipt['id']}",
                    event_type="ISSUE_INTAKE_SOURCE_RECORDED",
                    source="issue_intake_service",
                    entity_id=identity,
                    payload={
                        "source_row_id": str(identity),
                        "record_id": str(receipt["id"]),
                        "action": body.action,
                    },
                ),
                AuditDraft(
                    action="issue_intake.source_correct",
                    before_snapshot={
                        "issue_id": str(previous) if previous else None,
                        "revision": state["revision"],
                    },
                    after_snapshot={
                        "issue_id": str(body.target_issue_id) if body.target_issue_id else None,
                        "revision": receipt["revision"],
                        "record_id": str(receipt["id"]),
                    },
                    context={"reason": body.reason, "impact_note": body.impact_note},
                ),
            )
            return {"receipt": _plain(receipt)}

    def for_issue(self, ctx: AuthContext, project: UUID, issue: UUID) -> dict[str, Any]:
        with self.engine.connect() as c:
            KnowledgeCorrectionService._authorize(
                c, ctx.tenant.id, ctx.user.id, project, Action.WORK_ITEM_VIEW
            )
            t, h = tables.issue_intake_rows, tables.issue_intake_corrections
            touched = (
                select(h.c.id)
                .where(
                    h.c.tenant_id == ctx.tenant.id,
                    h.c.source_row_id == t.c.id,
                    or_(h.c.previous_issue_id == issue, h.c.target_issue_id == issue),
                )
                .exists()
            )
            rows = (
                c.execute(
                    select(t, tables.users.c.display_name.label("confirmed_by"))
                    .join(
                        tables.users,
                        (tables.users.c.tenant_id == t.c.tenant_id)
                        & (tables.users.c.id == t.c.created_by_user_id),
                    )
                    .where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.project_id == project,
                        or_(t.c.issue_id == issue, touched),
                    )
                    .order_by(t.c.created_at, t.c.id)
                )
                .mappings()
                .all()
            )
            states = source_states(c, ctx.tenant.id, list(rows))
            items = []
            for row in rows:
                state = states[row["id"]]
                items.append(
                    public_source(row)
                    | state
                    | {"on_this_issue": state["current_issue_id"] == str(issue)}
                )
            return {"items": items}
