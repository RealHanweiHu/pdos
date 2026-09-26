"""Versioned succession of research and scoped work, with original scope preserved."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, exists, or_, select, text

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _line,
    _member,
    _plain,
    _role,
    _space,
    digest,
)
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

Kind = Literal[
    "research",
    "work",
    "definition",
    "package",
    "strategy",
    "experiment",
    "opportunity",
    "space",
    "node",
    "subscription",
]
AUDIT_ACTION = "preproject.responsibility.changed"
TABLES = {
    "research": tables.research_tasks,
    "work": tables.scoped_work_items,
    "definition": tables.product_definitions,
    "package": tables.definition_requirement_packages,
    "strategy": tables.product_strategies,
    "experiment": tables.experiments,
    "opportunity": tables.opportunities,
    "space": tables.market_spaces,
    "node": tables.product_nodes,
    "subscription": tables.research_subscriptions,
}


class Reassign(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    role: Literal["owner", "receiver", "reviewer", "item_owner"]
    key: str | None = Field(default=None, min_length=1, max_length=128)
    user_id: UUID
    reason: str = Field(min_length=1, max_length=2048)


def changeable(kind: Kind, row: Any) -> bool:
    if kind == "subscription":
        return row["status"] in ("active", "paused", "quarantined")
    if kind in ("space", "node"):
        return row["lifecycle"] not in ("archived", "retired")
    if kind == "opportunity":
        return row["state"] in ("exploring", "evaluating", "selected", "deferred")
    if kind == "experiment":
        return row["state"] in ("draft", "approved", "running")
    if kind == "package":
        return row["state"] in ("pending_review", "accepted")
    return (
        row["state"] in ("draft", "in_review")
        if kind in ("definition", "strategy")
        else row["state"] not in ("completed", "cancelled")
    )


def responsibilities(kind: Kind, row: Any) -> list[dict[str, Any]]:
    result = [
        {
            "role": "owner",
            "key": None,
            "label": "负责人",
            "user_id": str(row["owner_user_id"]) if row["owner_user_id"] else None,
        }
    ]
    if kind == "work" and row["acceptance_required"]:
        result.append(
            {
                "role": "receiver",
                "key": None,
                "label": "接收人",
                "user_id": str(row["receiver_user_id"]) if row["receiver_user_id"] else None,
            }
        )
    if kind == "definition":
        for discipline in ("id", "md", "ee", "fw", "dqe"):
            result.append(
                {
                    "role": "reviewer",
                    "key": discipline,
                    "label": f"{discipline.upper()} 专业协审人",
                    "user_id": row["content"]["reviewers"].get(discipline),
                }
            )
        for item in row["content"]["items"]:
            result.append(
                {
                    "role": "item_owner",
                    "key": item["item_key"],
                    "label": f"规格 {item['item_key']} · {item['title']} 验证负责人",
                    "user_id": item.get("owner_user_id"),
                }
            )
    return result


def record(c: Connection, context: AuthContext, space: UUID, kind: Kind, id: UUID) -> Any:
    if kind in ("package", "opportunity"):
        _role(context, Action.REQUIREMENT_VIEW)
    t = TABLES[kind]
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == context.tenant.id,
                (t.c.id == space if kind == "space" else t.c.market_space_id == space),
                t.c.id == id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkAccessError("原工作不存在或不可访问")
    _line(c, context, space, row.get("product_line_id"))
    return row


def manage(c: Connection, context: AuthContext, space: UUID, row: Any) -> None:
    _role(context, Action.PRODUCT_WORK_MANAGE)
    _space(c, context, space, access="manager")
    _line(c, context, space, row.get("product_line_id"), access="manager", writable=True)


def eligible(
    c: Connection,
    context: AuthContext,
    space: UUID,
    line: UUID | None,
    kind: Kind = "work",
    line_owner: bool = False,
) -> list[dict[str, Any]]:
    u, m = tables.users, tables.market_space_members
    q = (
        select(u.c.id, u.c.display_name)
        .join(m, (m.c.tenant_id == u.c.tenant_id) & (m.c.user_id == u.c.id))
        .where(
            u.c.tenant_id == context.tenant.id,
            u.c.is_active.is_(True),
            u.c.role.in_(("owner", "admin", "project_manager", "engineer", "quality")),
            m.c.market_space_id == space,
            m.c.access.in_(("contributor", "manager")),
        )
    )
    if kind == "space":
        q = q.where(m.c.access == "manager", u.c.role.in_(("owner", "admin", "project_manager")))
    if kind == "subscription":
        q = q.where(
            u.c.role.in_([role.value for role in Role if is_allowed(role, Action.EVIDENCE_CAPTURE)])
        )
    if kind == "package":
        q = q.where(
            u.c.role.in_(
                [
                    role.value
                    for role in Role
                    if is_allowed(role, Action.REQUIREMENT_CREATE)
                    and is_allowed(role, Action.REQUIREMENT_EDIT)
                ]
            )
        )
    if line:
        grant = tables.product_line_members
        q = q.join(grant, (grant.c.tenant_id == u.c.tenant_id) & (grant.c.user_id == u.c.id)).where(
            grant.c.product_line_id == line,
            grant.c.access.in_(("manager",) if line_owner else ("contributor", "manager")),
        )
    return [_plain(r) for r in c.execute(q.order_by(u.c.display_name, u.c.id)).mappings()]


def history_statement(
    tenant: UUID, space: UUID, kind: Kind, id: UUID, before: int | None = None
) -> Any:
    a = tables.audit_log
    q = select(
        a.c.id,
        a.c.timestamp.label("created_at"),
        a.c.actor_user_id,
        a.c.before_snapshot,
        a.c.after_snapshot,
        a.c.context,
    ).where(
        a.c.tenant_id == tenant,
        or_(a.c.entity_id == id, a.c.context["replacement_id"].as_string() == str(id)),
        a.c.action == AUDIT_ACTION,
        a.c.context["market_space_id"].as_string() == str(space),
        a.c.context["kind"].as_string() == kind,
    )
    if before is not None:
        q = q.where(a.c.id < before)
    return q.order_by(a.c.id.desc()).limit(21)


def read(
    engine: Engine, context: AuthContext, space: UUID, kind: Kind, id: UUID, before: int | None
) -> dict[str, Any]:
    _role(context, Action.PRODUCT_WORK_VIEW)
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        _space(c, context, space)
        row = record(c, context, space, kind, id)
        extra = {}
        if kind == "package":
            from app.domain.requirement_package_succession import source_info

            extra = source_info(c, context, space, row)
        elif kind == "opportunity":
            from app.domain.opportunity_succession import is_latest

            extra = {"source_is_current": is_latest(c, context.tenant.id, id)}
        elif kind == "experiment":
            from app.domain.experiment_succession import source_info as experiment_info

            extra = experiment_info(c, context, row)
        try:
            manage(c, context, space, row)
            if kind == "subscription":
                _role(context, Action.RESEARCH_SOURCE_MANAGE)
            if kind == "package":
                _role(context, Action.REQUIREMENT_CREATE)
                _role(context, Action.REQUIREMENT_EDIT)
            can_manage = changeable(kind, row) and extra.get("source_is_current", True)
        except (ProductWorkError, ProductWorkAccessError):
            can_manage = False
        people = {
            str(r["id"]): r["display_name"]
            for r in c.execute(
                select(tables.users.c.id, tables.users.c.display_name).where(
                    tables.users.c.tenant_id == context.tenant.id,
                    tables.users.c.id.in_(
                        [UUID(r["user_id"]) for r in responsibilities(kind, row) if r["user_id"]]
                    ),
                )
            ).mappings()
        }
        history = (
            c.execute(history_statement(context.tenant.id, space, kind, id, before))
            .mappings()
            .all()
        )
        return {
            "record": _plain(row),
            **extra,
            "responsibilities": responsibilities(kind, row),
            "digest": digest(_plain(row)),
            "can_manage": can_manage,
            "people": people,
            "members": eligible(
                c,
                context,
                space,
                row.get("product_line_id"),
                kind,
                kind == "node" and row["level"] == "line",
            ),
            "history": [_plain(r) for r in history[:20]],
            "next_before_id": history[19]["id"] if len(history) > 20 else None,
        }


def reassign(
    engine: Engine, context: AuthContext, space: UUID, kind: Kind, id: UUID, command: Reassign
) -> dict[str, Any]:
    _role(context, Action.PRODUCT_WORK_MANAGE)
    with engine.begin() as c:
        c.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"preproject-owner:{context.tenant.id}:{context.user.id}:{command.request_id}"},
        )
        _space(c, context, space, access="manager", lock=True)
        row = record(c, context, space, kind, id)
        manage(c, context, space, row)
        if kind == "subscription":
            _role(context, Action.RESEARCH_SOURCE_MANAGE)
        if kind == "package":
            _role(context, Action.REQUIREMENT_CREATE)
            _role(context, Action.REQUIREMENT_EDIT)
        signature = digest(
            {
                "space_id": str(space),
                "kind": kind,
                "record_id": str(id),
                **command.model_dump(
                    mode="json", exclude={"key"} if command.key is None else set()
                ),
            }
        )
        a = tables.audit_log
        prior = (
            c.execute(
                select(a).where(
                    a.c.tenant_id == context.tenant.id,
                    a.c.actor_user_id == context.user.id,
                    a.c.action == AUDIT_ACTION,
                    a.c.context["request_id"].as_string() == str(command.request_id),
                )
            )
            .mappings()
            .one_or_none()
        )
        if prior:
            if prior["context"]["request_digest"] != signature:
                raise ProductWorkError("此请求编号已用于另一项责任调整")
            return {
                "request_id": str(command.request_id),
                "audit_id": prior["id"],
                "record": prior["after_snapshot"],
            }
        if digest(_plain(row)) != command.expected_digest:
            raise ProductWorkError("工作版本或办理进展已变化，请刷新后重新核对")
        if not changeable(kind, row):
            raise ProductWorkError("已结束或已发布记录保留原责任，不再改派")
        selected = next(
            (
                r
                for r in responsibilities(kind, row)
                if r["role"] == command.role and r["key"] == command.key
            ),
            None,
        )
        if selected is None:
            raise ProductWorkError("此记录不存在所选职责，请重新读取原记录")
        if selected["user_id"] == str(command.user_id):
            raise ProductWorkError("请选择不同的接手人")
        _member(c, context, space, command.user_id, row.get("product_line_id"))
        if kind == "package" and str(command.user_id) not in {
            r["id"]
            for r in eligible(
                c,
                context,
                space,
                row.get("product_line_id"),
                kind,
                False,
            )
        }:
            raise ProductWorkError("接手人须有此范围的需求创建和编辑权限")
        if kind in ("space", "node") and str(command.user_id) not in {
            r["id"]
            for r in eligible(
                c,
                context,
                space,
                row.get("product_line_id"),
                kind,
                kind == "node" and row["level"] == "line",
            )
        }:
            raise ProductWorkError("空间或产品线负责人须已有对应管理权限；移交不自动增加权限")
        if kind == "subscription" and str(command.user_id) not in {
            r["id"] for r in eligible(c, context, space, row.get("product_line_id"), kind)
        }:
            raise ProductWorkError("接手人须有原范围协作资格及证据采集权限")
        field = f"{command.role}_user_id"
        values: dict[str, Any] = {
            "version": row["version"] + 1,
            "updated_at": datetime.now(UTC),
        }
        if kind == "definition":
            content = _plain(row["content"])
            if command.role == "owner":
                content["owner_user_id"] = str(command.user_id)
                values["owner_user_id"] = command.user_id
            elif command.role == "reviewer":
                content["reviewers"][command.key] = str(command.user_id)
            else:
                for item in content["items"]:
                    if item["item_key"] == command.key:
                        item["owner_user_id"] = str(command.user_id)
            values.update(content=content, review_digest=None)
            if row["state"] == "in_review":
                # Existing DB contract allows content changes only between drafts.
                # Return and edit share the original space lock and transaction.
                t = TABLES[kind]
                c.execute(
                    t.update()
                    .where(t.c.tenant_id == context.tenant.id, t.c.id == id)
                    .values(
                        state="draft",
                        review_digest=None,
                        version=row["version"] + 1,
                        updated_at=values["updated_at"],
                    )
                )
                values["version"] += 1
        else:
            values[field] = command.user_id
            if kind == "strategy" and row["state"] == "in_review":
                t = TABLES[kind]
                c.execute(
                    t.update()
                    .where(t.c.tenant_id == context.tenant.id, t.c.id == id)
                    .values(
                        state="draft",
                        version=row["version"] + 1,
                        updated_at=values["updated_at"],
                    )
                )
                values["version"] += 1
        if kind == "work":
            if row["state"] == "pending_assignment":
                owner = values.get("owner_user_id", row["owner_user_id"])
                receiver = values.get("receiver_user_id", row["receiver_user_id"])
                if owner and (not row["acceptance_required"] or receiver):
                    values["state"] = "ready"
            elif row["state"] == "submitted" and command.role == "owner":
                # The incoming owner must review and resubmit; old output remains visible.
                values.update(state="in_progress", accepted_by_user_id=None, accepted_at=None)
        if kind == "subscription":
            from app.domain.research_subscriptions import _cancel_attempt

            _cancel_attempt(c, row, command.reason)
            values.update(
                status="paused", next_due_at=None, lease_token=None, lease_expires_at=None
            )
        t = TABLES[kind]
        if kind == "package":
            from app.domain.requirement_package_succession import transfer

            after = transfer(c, context, space, row, command.user_id, command.request_id, signature)
        elif kind == "opportunity":
            from app.domain.opportunity_succession import transfer as opportunity_transfer

            after = opportunity_transfer(
                c, context, space, row, command.user_id, command.request_id, signature
            )
        elif kind == "experiment" and row["state"] != "draft":
            from app.domain.experiment_succession import transfer as experiment_transfer

            after = experiment_transfer(
                c,
                context,
                space,
                row,
                command.user_id,
                command.request_id,
                signature,
                command.reason,
            )
        else:
            after = (
                c.execute(
                    t.update()
                    .where(
                        t.c.tenant_id == context.tenant.id,
                        (t.c.id == space if kind == "space" else t.c.market_space_id == space),
                        t.c.id == id,
                    )
                    .values(**values)
                    .returning(t)
                )
                .mappings()
                .one()
            )
        ids = [context.user.id, command.user_id]
        if selected["user_id"]:
            ids.append(UUID(selected["user_id"]))
        people = {
            str(r["id"]): r["display_name"]
            for r in c.execute(
                select(tables.users.c.id, tables.users.c.display_name).where(
                    tables.users.c.tenant_id == context.tenant.id, tables.users.c.id.in_(ids)
                )
            ).mappings()
        }
        written = EventAuditWriter(
            c, tenant_id=context.tenant.id, actor_user_id=context.user.id, project_id=None
        ).record(
            EventDraft(
                event_id=f"preproject-owner:{id}:{context.user.id}:{command.request_id}",
                event_type="PREPROJECT_RECORD_CHANGED",
                source="product_workspace_service",
                entity_id=id,
                payload={
                    "market_space_id": str(space),
                    "record_kind": {
                        "research": "research_task",
                        "work": "scoped_work_item",
                        "definition": "product_definition",
                        "package": "definition_requirement_package",
                        "strategy": "product_strategy",
                        "experiment": "experiment",
                        "opportunity": "opportunity",
                        "space": "market_space",
                        "node": "product_node",
                        "subscription": "research_subscription",
                    }[kind],
                    "action": "responsibility_changed",
                    "object_version": row["version"]
                    if kind == "opportunity"
                    else row["version"] + 1
                    if after["id"] != row["id"]
                    else after["version"],
                },
            ),
            AuditDraft(
                action=AUDIT_ACTION,
                before_snapshot=_plain(row),
                after_snapshot=_plain(after),
                context={
                    "market_space_id": str(space),
                    "kind": kind,
                    "role": command.role,
                    "key": command.key,
                    **({"replacement_id": str(after["id"])} if after["id"] != row["id"] else {}),
                    "responsibility_label": selected["label"],
                    "previous_user_id": selected["user_id"],
                    "next_user_id": str(command.user_id),
                    "request_id": str(command.request_id),
                    "request_digest": signature,
                    "reason": command.reason,
                    "people": people,
                },
            ),
        )
        return {
            "request_id": str(command.request_id),
            "audit_id": written.audit_row_id,
            "record": _plain(after),
        }


def definition_obligations(c: Connection, tenant: UUID, user: UUID) -> list[dict[str, Any]]:
    """Embedded named duties absent from the definition's top-level owner field."""
    d, r = tables.product_definitions, tables.definition_reviews
    newer = d.alias("newer_handover_definition")
    query = (
        select(d)
        .where(
            d.c.tenant_id == tenant,
            d.c.state.in_(("draft", "in_review")),
            or_(
                d.c.content["items"].contains([{"owner_user_id": str(user)}]),
                *[
                    d.c.content["reviewers"][key].as_string() == str(user)
                    for key in ("id", "md", "ee", "fw", "dqe")
                ],
            ),
            ~exists(
                select(newer.c.id).where(
                    newer.c.tenant_id == tenant, newer.c.supersedes_id == d.c.id
                )
            ),
        )
        .order_by(d.c.id)
    )
    items = []
    for row in c.execute(query).mappings():
        completed = (
            set(
                c.execute(
                    select(r.c.discipline).where(
                        r.c.tenant_id == tenant,
                        r.c.definition_id == row["id"],
                        r.c.review_round == row["review_round"],
                        r.c.review_digest == row["review_digest"],
                    )
                ).scalars()
            )
            if row["state"] == "in_review"
            else set()
        )
        for duty in responsibilities("definition", row):
            if duty["role"] == "owner" or duty["user_id"] != str(user):
                continue
            if duty["role"] == "reviewer" and duty["key"] in completed:
                continue
            items.append(
                {
                    "id": f"{row['id']}:{duty['role']}:{duty['key']}",
                    "title": f"{row['title']} · {duty['label']}",
                    "project_id": None,
                    "href": (
                        f"/product-work?space={row['market_space_id']}"
                        f"&responsibility_kind=definition&responsibility_id={row['id']}"
                    ),
                    "basis": digest({"record": _plain(row), "responsibility": duty}),
                }
            )
    return (
        [
            {
                "key": "definition_named_responsibilities",
                "label": "未发布产品定义的协审及规格验证责任",
                "count": len(items),
                "can_transfer": False,
                "reasons": ["在原定义中调整具名责任并重新送审；已提交意见保持原签名"],
                "items": items,
            }
        ]
        if items
        else []
    )
