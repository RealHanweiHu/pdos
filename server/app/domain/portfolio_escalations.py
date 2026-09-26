"""Named internal follow-up on a real management queue item, separate from approval."""

from dataclasses import replace
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, func, or_, select, text, true
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.my_work import _page_summary
from app.domain.portfolio_control_queue import LABELS, Kind, link, queue_query
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.project_execution import _person
from app.domain.resource_reservations import _project
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

TERMINAL = ("return", "close", "withdraw")


class EscalationSource(Contract):
    project_id: UUID
    source_kind: Kind
    source_id: UUID
    expected_source_digest: Digest


class EscalationDraft(EscalationSource):
    recipient_user_id: UUID
    due_date: date
    reason: Text
    requested_outcome: Text


class EscalationSave(EscalationDraft):
    request_id: UUID
    expected_preview_digest: Digest


class EscalationReply(Contract):
    escalation_id: UUID
    expected_version: int = Field(ge=0)
    action: Literal["accept", "update", "return", "close", "withdraw"]
    note: Text
    evidence: Text | None = None
    due_date: date | None = None
    request_id: UUID

    @model_validator(mode="after")
    def shape(self) -> "EscalationReply":
        if (self.action in ("accept", "update")) != (self.due_date is not None):
            raise ValueError("接手或进展须明确跟进期限；其他操作不改期限")
        if self.action == "close" and not self.evidence:
            raise ValueError("结束跟进须登记实际协调结果及依据，不代表原事项已经批准或执行")
        return self


class EscalationRead(Contract):
    project_id: UUID | None = None
    mode: Literal["all", "sent", "received"] = "all"
    include_closed: bool = False
    offset: int = Field(default=0, ge=0)
    revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class EscalationHistory(Contract):
    escalation_id: UUID
    before_version: int | None = Field(default=None, ge=1)


def source(
    c: Connection, context: AuthContext, now: datetime, project: UUID, kind: str, identity: UUID
) -> dict[str, Any] | None:
    if not is_allowed(context.user.role, Action.WORK_ITEM_VIEW):
        return None
    query = queue_query(c, context, now)[0]
    columns = query.selected_columns
    row = (
        c.execute(
            query.where(columns.project_id == project, columns.kind == kind, columns.id == identity)
        )
        .mappings()
        .one_or_none()
    )
    return _plain(row) if row else None


def source_access(c: Connection, context: AuthContext, row: Any) -> bool:
    kind = row["source_kind"]
    actions = [Action.WORK_ITEM_VIEW]
    if kind.startswith("gate_"):
        actions.append(Action.GATE_VIEW)
    if kind.startswith("id_freeze_") or kind in ("cost_approval", "cost_gap"):
        actions.append(Action.PRODUCT_ENGINEERING_VIEW)
    if kind in ("ecr_approval", "ecn_effectivity", "discussion_brief"):
        actions.append(Action.CHANGE_VIEW)
    if kind == "discussion_brief":
        actions.append(Action.QUALITY_VIEW)
    if not all(is_allowed(context.user.role, action) for action in actions):
        return False
    if kind == "discussion_brief":
        return bool(
            c.execute(
                select(tables.agent_runs.c.id).where(
                    tables.agent_runs.c.tenant_id == context.tenant.id,
                    tables.agent_runs.c.project_id == row["project_id"],
                    tables.agent_runs.c.id == row["source_id"],
                    tables.agent_runs.c.requested_by_user_id == context.user.id,
                )
            ).first()
        )
    if kind.startswith("cross_"):
        from app.domain.cross_project_schedule import _pair, _shared_reader

        t = tables.cross_project_schedule_proposals
        original = (
            c.execute(
                select(t).where(t.c.tenant_id == context.tenant.id, t.c.id == row["source_id"])
            )
            .mappings()
            .one_or_none()
        )
        if original is None:
            return False
        try:
            _pair(c, context, original)
            return True
        except ProductWorkAccessError:
            return _shared_reader(c, context, row["project_id"], original)
    return True


def latest_reply(c: Connection, tenant: UUID, escalation: UUID) -> Any:
    t = tables.portfolio_escalation_replies
    return (
        c.execute(
            select(t)
            .where(t.c.tenant_id == tenant, t.c.escalation_id == escalation)
            .order_by(t.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def own(c: Connection, context: AuthContext, identity: UUID) -> Any:
    _role(context, Action.WORK_ITEM_VIEW)
    t = tables.portfolio_escalations
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == context.tenant.id,
                t.c.id == identity,
                or_(
                    t.c.created_by_user_id == context.user.id,
                    t.c.recipient_user_id == context.user.id,
                ),
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("升级跟进不存在或不属于本人")
    _project(c, context, row["project_id"])
    return row


def record(
    c: Connection,
    context: AuthContext,
    project: UUID,
    identity: UUID,
    action: str,
    value: dict[str, Any],
) -> None:
    EventAuditWriter(
        c, tenant_id=context.tenant.id, project_id=project, actor_user_id=context.user.id
    ).record(
        EventDraft(
            event_id=f"portfolio-escalation:{identity}:{uuid4()}",
            event_type="PORTFOLIO_ESCALATION_CHANGED",
            source="portfolio_escalation",
            entity_id=identity,
            payload={"action": action},
        ),
        AuditDraft(action=f"portfolio_escalation.{action}", after_snapshot=value),
    )


def preview(c: Connection, context: AuthContext, command: EscalationDraft) -> dict[str, Any]:
    _role(context, Action.WORK_ITEM_EDIT)
    _project(c, context, command.project_id)
    _person(c, context, command.project_id, context.user.id)
    if command.recipient_user_id == context.user.id:
        raise ProductWorkError("请选择另一名具名负责人承担升级跟进")
    now = c.execute(select(func.clock_timestamp())).scalar_one()
    if command.due_date < now.astimezone(ZoneInfo("Asia/Shanghai")).date():
        raise ProductWorkError("跟进期限不能早于当前业务日")
    current = source(c, context, now, command.project_id, command.source_kind, command.source_id)
    if current is None or digest(current) != command.expected_source_digest:
        raise ProductWorkError("原待办、权限或来源已有变化，请刷新队列后发起")
    person = _person(c, context, command.project_id, command.recipient_user_id)
    target = replace(
        context,
        user=replace(
            context.user,
            id=person["id"],
            role=Role(person["role"]),
            display_name=person["display_name"],
        ),
    )
    if (
        not is_allowed(target.user.role, Action.WORK_ITEM_EDIT)
        or source(c, target, now, command.project_id, command.source_kind, command.source_id)
        is None
    ):
        raise ProductWorkError(
            "接收人当前不能读取并跟进这条原待办；私人摘要或未授权跨项目资料不会随升级开放"
        )
    result = {
        "source": current,
        "source_digest": digest(current),
        "recipient": _plain(person),
        "command": command.model_dump(mode="json"),
        "label": LABELS[command.source_kind],
        "href": link(current),
    }
    return {**result, "preview_digest": digest(result)}


class PortfolioEscalationService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def options(self, context: AuthContext, command: EscalationSource) -> dict[str, Any]:
        _role(context, Action.WORK_ITEM_EDIT)
        with self.engine.connect() as c:
            _project(c, context, command.project_id)
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            current = source(
                c, context, now, command.project_id, command.source_kind, command.source_id
            )
            if current is None or digest(current) != command.expected_source_digest:
                raise ProductWorkError("原队列事项已变化，请刷新后再选接收人")
            u, m = tables.users, tables.project_members
            people = c.execute(
                select(u.c.id, u.c.display_name, u.c.role)
                .where(
                    u.c.tenant_id == context.tenant.id,
                    u.c.is_active.is_(True),
                    u.c.id != context.user.id,
                    or_(
                        u.c.role.in_(("owner", "admin")),
                        u.c.id.in_(
                            select(m.c.user_id).where(
                                m.c.tenant_id == context.tenant.id,
                                m.c.project_id == command.project_id,
                            )
                        ),
                    ),
                )
                .order_by(u.c.display_name, u.c.id)
            ).mappings()
            return {
                "people": [
                    _plain(v) for v in people if is_allowed(Role(v["role"]), Action.WORK_ITEM_EDIT)
                ],
                "source": current,
                "label": LABELS[command.source_kind],
            }

    def preview(self, context: AuthContext, command: EscalationDraft) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return preview(c, context, command)

    def save(self, context: AuthContext, command: EscalationSave) -> dict[str, Any]:
        try:
            with self.engine.begin() as c:
                _role(context, Action.WORK_ITEM_EDIT)
                _project(c, context, command.project_id, write=True)
                t = tables.portfolio_escalations
                signature = digest(command.model_dump(mode="json"))
                prior = (
                    c.execute(
                        select(t.c.id, t.c.request_digest).where(
                            t.c.tenant_id == context.tenant.id,
                            t.c.created_by_user_id == context.user.id,
                            t.c.request_id == command.request_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if prior:
                    if prior["request_digest"] != signature:
                        raise ProductWorkError("请求编号已用于另一升级跟进")
                    return {"id": str(prior["id"]), "reused": True}
                value = preview(
                    c,
                    context,
                    EscalationDraft.model_validate(
                        command.model_dump(exclude={"request_id", "expected_preview_digest"})
                    ),
                )
                if value["preview_digest"] != command.expected_preview_digest:
                    raise ProductWorkError("原待办或接收人已变化，请重新预览")
                identity = uuid4()
                now = c.execute(select(func.clock_timestamp())).scalar_one()
                c.execute(
                    t.insert().values(
                        id=identity,
                        tenant_id=context.tenant.id,
                        project_id=command.project_id,
                        source_kind=command.source_kind,
                        source_id=command.source_id,
                        source_digest=value["source_digest"],
                        snapshot=value,
                        recipient_user_id=command.recipient_user_id,
                        due_date=command.due_date,
                        reason=command.reason,
                        requested_outcome=command.requested_outcome,
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=signature,
                        created_at=now,
                    )
                )
                record(
                    c,
                    context,
                    command.project_id,
                    identity,
                    "requested",
                    {"id": str(identity), **value},
                )
                return {"id": str(identity), "reused": False}
        except IntegrityError as error:
            raise ProductWorkError(
                "同一事项仍有未结束的升级跟进，或原记录已变化；请读取原跟进"
            ) from error

    def reply(self, context: AuthContext, command: EscalationReply) -> dict[str, Any]:
        _role(context, Action.WORK_ITEM_EDIT)
        with self.engine.begin() as c:
            row = own(c, context, command.escalation_id)
            _person(c, context, row["project_id"], context.user.id)
            c.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"portfolio-escalation:{row['id']}"},
            )
            t = tables.portfolio_escalation_replies
            signature = digest(command.model_dump(mode="json"))
            prior = (
                c.execute(
                    select(t.c.id, t.c.request_digest).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.created_by_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != signature:
                    raise ProductWorkError("请求编号已用于另一跟进回执")
                return {"id": str(prior["id"]), "reused": True}
            previous = latest_reply(c, context.tenant.id, row["id"])
            version = previous["version"] if previous else 0
            state = previous["action"] if previous else "pending"
            if command.expected_version != version or state in TERMINAL:
                raise ProductWorkError("跟进状态或版本已变化，请刷新后办理")
            if command.action == "withdraw":
                permitted = row["created_by_user_id"] == context.user.id
            else:
                permitted = row["recipient_user_id"] == context.user.id and (
                    command.action == "return"
                    or (command.action == "accept" and state == "pending")
                    or (command.action in ("update", "close") and state in ("accept", "update"))
                )
            if not permitted:
                raise ProductWorkError("由当前具名接收人或原发起人按跟进状态办理")
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            if (
                command.due_date
                and command.due_date < now.astimezone(ZoneInfo("Asia/Shanghai")).date()
            ):
                raise ProductWorkError("新的跟进期限不能早于当前业务日")
            current = source(
                c, context, now, row["project_id"], row["source_kind"], row["source_id"]
            )
            if (
                not source_access(c, context, row)
                or (current is None and command.action != "close")
            ) and command.action not in ("return", "withdraw"):
                raise ProductWorkError(
                    "原事项不在当前可见待办范围，请先在原入口核对；可退回或撤回本次跟进"
                )
            identity = uuid4()
            value = dict(
                id=identity,
                tenant_id=context.tenant.id,
                project_id=row["project_id"],
                escalation_id=row["id"],
                version=version + 1,
                action=command.action,
                note=command.note,
                evidence=command.evidence,
                due_date=command.due_date,
                source_digest=digest(current) if current else None,
                created_by_user_id=context.user.id,
                request_id=command.request_id,
                request_digest=signature,
                created_at=now,
            )
            c.execute(t.insert().values(**value))
            record(c, context, row["project_id"], row["id"], command.action, _plain(value))
            return {"id": str(identity), "version": version + 1, "reused": False}

    def read(self, context: AuthContext, command: EscalationRead) -> dict[str, Any]:
        _role(context, Action.WORK_ITEM_VIEW)
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            visible = queue_query(c, context, now)[3]
            t, r = tables.portfolio_escalations, tables.portfolio_escalation_replies
            last = (
                select(r.c.version, r.c.action, r.c.due_date)
                .where(r.c.tenant_id == t.c.tenant_id, r.c.escalation_id == t.c.id)
                .order_by(r.c.version.desc())
                .limit(1)
                .lateral("latest_escalation_reply")
            )
            deadline = r.alias("escalation_latest_deadline")
            current_deadline = (
                select(deadline.c.due_date)
                .where(
                    deadline.c.tenant_id == t.c.tenant_id,
                    deadline.c.escalation_id == t.c.id,
                    deadline.c.due_date.is_not(None),
                )
                .order_by(deadline.c.version.desc())
                .limit(1)
                .correlate(t)
                .scalar_subquery()
            )
            a, b = (
                tables.users.alias("escalation_sender"),
                tables.users.alias("escalation_receiver"),
            )
            query = (
                select(
                    t,
                    func.coalesce(last.c.version, 0).label("reply_version"),
                    func.coalesce(last.c.action, "pending").label("state"),
                    func.coalesce(current_deadline, t.c.due_date).label("current_due_date"),
                    a.c.display_name.label("sender_name"),
                    b.c.display_name.label("recipient_name"),
                )
                .select_from(
                    t.outerjoin(last, true())
                    .join(a, (a.c.tenant_id == t.c.tenant_id) & (a.c.id == t.c.created_by_user_id))
                    .join(b, (b.c.tenant_id == t.c.tenant_id) & (b.c.id == t.c.recipient_user_id))
                )
                .where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.project_id.in_(visible),
                    or_(
                        t.c.created_by_user_id == context.user.id,
                        t.c.recipient_user_id == context.user.id,
                    ),
                )
            )
            if command.project_id:
                query = query.where(t.c.project_id == command.project_id)
            if command.mode != "all":
                query = query.where(
                    (t.c.created_by_user_id if command.mode == "sent" else t.c.recipient_user_id)
                    == context.user.id
                )
            if not command.include_closed:
                query = query.where(func.coalesce(last.c.action, "pending").not_in(TERMINAL))
            order = (t.c.created_at.desc(), t.c.id)
            count, revision = c.execute(_page_summary(query, order)).one()
            if command.offset and revision != command.revision:
                raise ProductWorkError("跟进记录或读取范围已变化，请刷新第一页")
            records = list(
                c.execute(query.order_by(*order).offset(command.offset).limit(21)).mappings()
            )
            items = []
            for row in records[:20]:
                current = source(
                    c, context, now, row["project_id"], row["source_kind"], row["source_id"]
                )
                value = _plain(row)
                value.update(
                    source_available=source_access(c, context, row),
                    source_pending=current is not None,
                    source_current=current is not None and digest(current) == row["source_digest"],
                    href=link(
                        {
                            "project_id": str(row["project_id"]),
                            "kind": row["source_kind"],
                            "id": str(row["source_id"]),
                            "relation_id": row["snapshot"]["source"].get("relation_id"),
                        }
                    ),
                    is_sender=row["created_by_user_id"] == context.user.id,
                    is_recipient=row["recipient_user_id"] == context.user.id,
                    overdue=row["state"] not in TERMINAL
                    and row["current_due_date"] < now.astimezone(ZoneInfo("Asia/Shanghai")).date(),
                )
                if not value["source_available"]:
                    value.update(snapshot=None, reason=None, requested_outcome=None)
                items.append(value)
            return {
                "items": items,
                "total": count,
                "revision": revision,
                "as_of": now.isoformat(),
                "can_reply": is_allowed(context.user.role, Action.WORK_ITEM_EDIT),
                "next_offset": command.offset + 20 if len(records) > 20 else None,
            }

    def history(self, context: AuthContext, command: EscalationHistory) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            row = own(c, context, command.escalation_id)
            available = source_access(c, context, row)
            r = tables.portfolio_escalation_replies
            query = select(r).where(
                r.c.tenant_id == context.tenant.id, r.c.escalation_id == row["id"]
            )
            if command.before_version:
                query = query.where(r.c.version < command.before_version)
            records = list(c.execute(query.order_by(r.c.version.desc()).limit(31)).mappings())
            items = []
            for v in records[:30]:
                item = _plain(v)
                if not available:
                    item.update(note=None, evidence=None)
                items.append(item)
            return {
                "items": items,
                "source_available": available,
                "next_before_version": records[29]["version"] if len(records) > 30 else None,
            }
