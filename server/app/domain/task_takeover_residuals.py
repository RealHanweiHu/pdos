"""Explicit links from a handoff to the existing owners and dates of residual work."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, exists, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.resource_reservations import _project
from app.domain.tasks import TaskNotFoundError

Kind = Literal["task", "issue", "risk"]


class Residual(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Kind
    id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    note: str = Field(min_length=1, max_length=4000)


def statement(kind: Kind, tenant: UUID, project: UUID) -> Any:
    t = {"task": tables.tasks, "issue": tables.issues, "risk": tables.risks}[kind]
    owner = t.c.assignee_user_id if kind == "task" else t.c.owner_user_id
    due = t.c.due_date if kind == "task" else t.c.target_date
    u, m = tables.users, tables.project_members
    query = (
        select(
            t.c.id,
            t.c.title,
            t.c.status,
            t.c.updated_at,
            owner.label("owner_user_id"),
            due.label("due_date"),
            u.c.display_name.label("owner_name"),
            u.c.is_active.label("owner_active"),
            exists(
                select(m.c.id).where(
                    m.c.tenant_id == t.c.tenant_id,
                    m.c.project_id == t.c.project_id,
                    m.c.user_id == owner,
                )
            ).label("owner_member"),
        )
        .select_from(t.outerjoin(u, (u.c.tenant_id == t.c.tenant_id) & (u.c.id == owner)))
        .where(t.c.tenant_id == tenant, t.c.project_id == project)
    )
    return query.where(t.c.draft_state == "confirmed") if kind == "risk" else query


def snapshot(kind: Kind, project: UUID, value: Any) -> dict[str, Any]:
    result = _plain(dict(value) | {"kind": kind})
    result["href"] = f"/projects?project={project}&tab=work-items&entity_id={result['id']}"
    result["digest"] = digest(result)
    return result


def current(
    c: Connection, tenant: UUID, project: UUID, refs: list[dict[str, Any]]
) -> dict[tuple[str, str], dict[str, Any]]:
    result = {}
    for kind in ("task", "issue", "risk"):
        ids = [UUID(ref["id"]) for ref in refs if ref["kind"] == kind]
        if not ids:
            continue
        q = statement(kind, tenant, project)
        for value in c.execute(q.where(q.selected_columns.id.in_(ids))).mappings():
            result[(kind, str(value["id"]))] = snapshot(kind, project, value)
    return result


def freeze(
    c: Connection, tenant: UUID, project: UUID, task: UUID, refs: list[Residual]
) -> list[dict[str, Any]]:
    original = [ref.model_dump(mode="json") for ref in refs]
    live = current(c, tenant, project, original)
    result = []
    for ref in original:
        value = live.get((ref["kind"], ref["id"]))
        if ref["kind"] == "task" and ref["id"] == str(task):
            raise ProductWorkError("交接任务本身不能再作为自己的遗留项")
        if value is None or value["digest"] != ref["expected_digest"]:
            raise ProductWorkError("遗留项或责任安排已变化，请重新选择核对")
        if value["status"] not in {"done", "skipped", "closed", "cancelled"} and (
            not value["owner_active"] or not value["owner_member"] or not value["due_date"]
        ):
            raise ProductWorkError("未完成遗留项须先在原业务中补齐有效负责人和办理期限")
        result.append(ref | {"snapshot": value})
    return result


def options(
    engine: Engine,
    ctx: AuthContext,
    project: UUID,
    task: UUID,
    kind: Kind,
    search: str,
    after_id: UUID | None,
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
        _project(c, ctx, project)
        if (
            c.execute(
                select(tables.tasks.c.id).where(
                    tables.tasks.c.tenant_id == ctx.tenant.id,
                    tables.tasks.c.project_id == project,
                    tables.tasks.c.id == task,
                )
            ).first()
            is None
        ):
            raise TaskNotFoundError
        q = statement(kind, ctx.tenant.id, project)
        columns = q.selected_columns
        if kind == "task":
            q = q.where(columns.id != task)
        if search.strip():
            escaped = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            q = q.where(columns.title.ilike(f"%{escaped}%", escape="\\"))
        if after_id:
            q = q.where(columns.id > after_id)
        items = c.execute(q.order_by(columns.id).limit(51)).mappings().all()
        return {
            "items": [snapshot(kind, project, value) for value in items[:50]],
            "next_after_id": str(items[49]["id"]) if len(items) > 50 else None,
        }
