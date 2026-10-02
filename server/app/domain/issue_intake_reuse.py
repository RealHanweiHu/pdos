"""Explicit same-project Issue selection; similar text never implies an automatic merge."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, or_, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.conversations import ConversationError
from app.domain.issue_intake_preview import IssueIntakePreviews
from app.domain.product_workspace import _plain


class IssueIntakeReuse(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    row: int = Field(ge=1, le=1048576)
    issue_id: UUID
    expected_updated_at: AwareDatetime
    reason: str = Field(min_length=1, max_length=2000)


SUMMARY_FIELDS = ("id", "title", "status", "issue_type", "severity", "target_date", "updated_at")
TARGET_FIELDS = SUMMARY_FIELDS + (
    "description",
    "root_cause",
    "resolution",
    "closure_criteria",
    "closure_evidence_ref",
    "owner_user_id",
    "verifier_user_id",
    "sample_id",
    "stage_id",
    "closed_at",
    "reopen_count",
    "template_fields",
)


def target_snapshot(row: Any) -> dict[str, Any]:
    return _plain({key: row[key] for key in TARGET_FIELDS})


def issue_options(
    engine: Engine,
    ctx: AuthContext,
    conversation: UUID,
    preview: UUID,
    *,
    search: str = "",
    issue_id: UUID | None = None,
    before_updated_at: datetime | None = None,
    before_id: UUID | None = None,
) -> dict[str, Any]:
    if (before_updated_at is None) != (before_id is None):
        raise ConversationError("分页位置不完整，请重新查询")
    with engine.connect() as c:
        conv = IssueIntakePreviews(engine).scope(c, ctx, conversation)
        p = tables.issue_intake_previews
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
            raise ConversationError("此映射草稿不属于当前会话")
        return project_issue_options(
            c,
            ctx.tenant.id,
            conv["project_id"],
            search=search,
            issue_id=issue_id,
            before_updated_at=before_updated_at,
            before_id=before_id,
        )


def project_issue_options(
    c: Connection,
    tenant: UUID,
    project: UUID,
    *,
    search: str = "",
    issue_id: UUID | None = None,
    before_updated_at: datetime | None = None,
    before_id: UUID | None = None,
) -> dict[str, Any]:
    """Read options only after the caller has authorized this project and its source."""
    if (before_updated_at is None) != (before_id is None):
        raise ConversationError("分页位置不完整，请重新查询")
    t = tables.issues
    query = select(t).where(
        t.c.tenant_id == tenant, t.c.project_id == project, t.c.withdrawn_at.is_(None)
    )
    if issue_id is not None:
        row = c.execute(query.where(t.c.id == issue_id)).mappings().one_or_none()
        if row is None:
            raise ConversationError("所选问题当前不属于本项目或已不可读取")
        return {"target": target_snapshot(row)}
    if search.strip():
        word = search.strip()
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
    items = [_plain({key: row[key] for key in SUMMARY_FIELDS}) for row in rows[:50]]
    return {
        "items": items,
        "next": {"before_updated_at": items[-1]["updated_at"], "before_id": items[-1]["id"]}
        if len(rows) > 50
        else None,
    }
