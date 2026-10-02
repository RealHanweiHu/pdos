"""Human-selected current Decision and Issue targets for historical source rows."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, or_, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.conversations import ConversationError
from app.domain.decision_intake_preview import DecisionIntakePreviews
from app.domain.issue_intake_reuse import target_snapshot as issue_snapshot
from app.domain.product_workspace import _plain, digest


class IntakeTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    row: int = Field(ge=1, le=1048576)
    id: UUID
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=2000)


def decision_snapshot(row: Any) -> dict[str, Any]:
    return _plain({key: value for key, value in row.items() if key != "tenant_id"})


def snapshot(row: Any, kind: str) -> dict[str, Any]:
    return decision_snapshot(row) if kind == "decision" else issue_snapshot(row)


def read_target(
    c: Connection, tenant: UUID, project: UUID, kind: str, identity: UUID, *, lock: bool = False
) -> Any:
    t = tables.decisions if kind == "decision" else tables.issues
    query = select(t).where(t.c.tenant_id == tenant, t.c.project_id == project, t.c.id == identity)
    return c.execute(query.with_for_update() if lock else query).mappings().one_or_none()


def options(
    engine: Engine,
    ctx: AuthContext,
    conversation: UUID,
    preview: UUID,
    *,
    kind: Literal["decision", "issue"],
    search: str = "",
    target_id: UUID | None = None,
    before_updated_at: datetime | None = None,
    before_id: UUID | None = None,
) -> dict[str, Any]:
    if (before_updated_at is None) != (before_id is None):
        raise ConversationError("分页位置不完整，请重新查询")
    with engine.connect() as c:
        conv = DecisionIntakePreviews(engine).scope.scope(c, ctx, conversation)
        p = tables.decision_intake_previews
        if (
            c.execute(
                select(p.c.id).where(
                    p.c.tenant_id == ctx.tenant.id,
                    p.c.conversation_id == conversation,
                    p.c.id == preview,
                )
            ).scalar_one_or_none()
            is None
        ):
            raise ConversationError("此决策草稿不属于当前会话")
        return project_options(
            c,
            ctx.tenant.id,
            conv["project_id"],
            kind=kind,
            search=search,
            target_id=target_id,
            before_updated_at=before_updated_at,
            before_id=before_id,
        )


def project_options(
    c: Connection,
    tenant: UUID,
    project: UUID,
    *,
    kind: Literal["decision", "issue"],
    search: str = "",
    target_id: UUID | None = None,
    before_updated_at: datetime | None = None,
    before_id: UUID | None = None,
) -> dict[str, Any]:
    """Caller must authorize the project and original source before reading targets."""
    if (before_updated_at is None) != (before_id is None):
        raise ConversationError("分页位置不完整，请重新查询")
    if target_id is not None:
        row = read_target(c, tenant, project, kind, target_id)
        if row is None or (kind == "issue" and row.get("withdrawn_at") is not None):
            raise ConversationError("所选记录当前不属于本项目、已撤回或已不可读取")
        value = snapshot(row, kind)
        return {"target": value | {"digest": digest(value)}}
    t = tables.decisions if kind == "decision" else tables.issues
    query = select(t).where(t.c.tenant_id == tenant, t.c.project_id == project)
    if kind == "issue":
        query = query.where(t.c.withdrawn_at.is_(None))
    if word := search.strip():
        try:
            identity = UUID(word)
        except ValueError:
            identity = None
        query = query.where(or_(t.c.title.icontains(word, autoescape=True), t.c.id == identity))
    if before_updated_at is not None:
        query = query.where(
            or_(
                t.c.updated_at < before_updated_at,
                (t.c.updated_at == before_updated_at) & (t.c.id < before_id),
            )
        )
    rows = (
        c.execute(query.order_by(t.c.updated_at.desc(), t.c.id.desc()).limit(51)).mappings().all()
    )
    fields = (
        ("id", "title", "updated_at", "decision_kind", "outcome", "follow_up_state")
        if kind == "decision"
        else ("id", "title", "updated_at", "status", "severity")
    )
    items = [_plain({key: row[key] for key in fields}) for row in rows[:50]]
    return {
        "items": items,
        "next": {"before_updated_at": items[-1]["updated_at"], "before_id": items[-1]["id"]}
        if len(rows) > 50
        else None,
    }
