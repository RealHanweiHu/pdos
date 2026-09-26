"""Actual pre-project scope and object references for participant observations."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Table, select

from app.auth.repository import AuthContext, UserRecord
from app.auth.roles import Action, Role
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

SUBJECTS = {
    "research_task": "research_tasks",
    "scoped_work_item": "scoped_work_items",
    "opportunity": "opportunities",
    "strategy": "product_strategies",
    "definition": "product_definitions",
}


def authorize_scope(
    c: Connection,
    context: AuthContext,
    space: UUID,
    line: UUID | None,
    *,
    access: str = "viewer",
    writable: bool = False,
    lock: bool = False,
) -> None:
    _role(
        context,
        Action.PRODUCT_WORK_MANAGE
        if access == "manager"
        else Action.PRODUCT_WORK_CONTRIBUTE
        if writable
        else Action.PRODUCT_WORK_VIEW,
    )
    space_row = _space(
        c,
        context,
        space,
        access="viewer" if line else access,
        lock=lock,
        allow_archived=not writable,
    )
    if writable and space_row["lifecycle"] == "archived":
        raise ProductWorkError("已归档市场空间只读，仍可读取或撤回本人原授权")
    _line(c, context, space, line, access=access, writable=writable)


def participant(
    c: Connection,
    context: AuthContext,
    space: UUID,
    line: UUID | None,
    user: UUID,
) -> AuthContext:
    """An administrator is not automatically an actual study participant."""
    _member(c, context, space, user, line)
    u = tables.users
    row = (
        c.execute(
            select(u.c.id, u.c.username, u.c.display_name, u.c.role, u.c.auth_version).where(
                u.c.tenant_id == context.tenant.id, u.c.id == user, u.c.is_active.is_(True)
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkAccessError("参与者不再是有效成员")
    result = AuthContext(
        tenant=context.tenant,
        user=UserRecord(
            id=row["id"],
            tenant_id=context.tenant.id,
            username=row["username"],
            display_name=row["display_name"],
            role=Role(row["role"]),
            email=None,
            password_hash=None,
            auth_version=row["auth_version"],
            is_active=True,
        ),
    )
    authorize_scope(c, result, space, line)
    return result


def subject_table(kind: str) -> Table:
    if kind not in SUBJECTS:
        raise ProductWorkError("请选择已接入的实际立项前工作对象")
    table: Table = getattr(tables, SUBJECTS[kind])
    return table


def _snapshot(kind: str, row: Any) -> dict[str, Any]:
    # Keep source identity and the actual work objective. Nested evidence, other
    # people's deliberations and project documents require their original readers.
    keys = (
        "id",
        "market_space_id",
        "product_line_id",
        "series_id",
        "supersedes_id",
        "version",
        "revision_number",
        "title",
        "question",
        "state",
        "owner_user_id",
        "receiver_user_id",
        "expected_output",
        "completion_criteria",
        "expected_decision",
        "method",
        "time_scope",
        "action_type",
        "created_at",
        "updated_at",
    )
    result = _plain({k: row[k] for k in keys if k in row})
    result["kind"] = kind
    result["series_id"] = str(row.get("series_id") or row["id"])
    result["title"] = row.get("title") or row.get("question")
    return result


def source(
    c: Connection,
    context: AuthContext,
    space: UUID,
    line: UUID | None,
    kind: str,
    identity: UUID,
) -> dict[str, Any]:
    authorize_scope(c, context, space, line)
    t = subject_table(kind)
    scope = (
        t.c.tenant_id == context.tenant.id,
        t.c.market_space_id == space,
        t.c.product_line_id.is_not_distinct_from(line),
    )
    original = c.execute(select(t).where(*scope, t.c.id == identity)).mappings().one_or_none()
    if original is None:
        raise ProductWorkAccessError("实际工作对象不存在或不属于原观察范围")
    current = original
    if "series_id" in t.c:
        order = t.c.revision_number if "revision_number" in t.c else t.c.version
        current = (
            c.execute(
                select(t)
                .where(*scope, t.c.series_id == original["series_id"])
                .order_by(order.desc(), t.c.id.desc())
                .limit(1)
            )
            .mappings()
            .one()
        )
    fixed, now = _snapshot(kind, original), _snapshot(kind, current)
    return {
        "kind": kind,
        "id": str(identity),
        "series_id": fixed["series_id"],
        "created_at": fixed["created_at"],
        "original": fixed,
        "current": now,
        "source_changed": digest(fixed) != digest(now),
        "scope_note": "原对象身份及工作要求；完整业务内容、证据及批准沿原工作入口读取。",
    }


def source_options(
    c: Connection,
    context: AuthContext,
    space: UUID,
    line: UUID | None,
    kind: str,
    query: str = "",
    before_id: UUID | None = None,
) -> dict[str, Any]:
    authorize_scope(c, context, space, line)
    t = subject_table(kind)
    conditions = [
        t.c.tenant_id == context.tenant.id,
        t.c.market_space_id == space,
        t.c.product_line_id.is_not_distinct_from(line),
    ]
    if before_id:
        conditions.append(t.c.id < before_id)
    if query:
        title = t.c.question if kind == "research_task" else t.c.title
        conditions.append(title.icontains(query, autoescape=True))
    found = (
        c.execute(select(t).where(*conditions).order_by(t.c.id.desc()).limit(31)).mappings().all()
    )
    return {
        "items": [_snapshot(kind, row) for row in found[:30]],
        "next_before_id": str(found[29]["id"]) if len(found) > 30 else None,
    }
