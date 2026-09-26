"""Bind named compensation reviews to current, authorized business references."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, and_, or_, select

from app.auth.repository import AuthContext
from app.domain.conversations import ConversationError
from app.domain.issue_intake_references import KINDS, ReferenceKind, query_for, reference_view
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.knowledge_push import KnowledgeAccessError


class BusinessReferenceReview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: ReferenceKind
    id: UUID
    path_id: UUID
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    result: Literal["unaffected", "handled", "follow_up"]
    explanation: str = Field(min_length=1, max_length=4000)


def reference_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return str(item["kind"]), str(item["id"]), str(item["path_id"])


def resolve(
    c: Connection,
    ctx: AuthContext,
    project: UUID,
    source: dict[str, Any],
    issue: UUID,
    requested: list[dict[str, Any]],
    *,
    strict: bool = False,
) -> dict[tuple[str, str, str], dict[str, Any] | None]:
    """One query per requested kind; omitted keys are unreadable, None means no longer linked."""
    result: dict[tuple[str, str, str], dict[str, Any] | None] = {}
    for kind in sorted({str(item["kind"]) for item in requested}):
        if kind not in KINDS:
            if strict:
                raise ConversationError("所选业务引用类型不可用，请重新读取")
            continue
        try:
            KnowledgeCorrectionService._authorize(
                c, ctx.tenant.id, ctx.user.id, project, KINDS[kind][1]
            )
        except KnowledgeAccessError:
            if strict:
                raise KnowledgeAccessError(
                    "所选业务引用已不可读取，请重新核对本次办理范围"
                ) from None
            continue
        targets = {reference_key(item) for item in requested if item["kind"] == kind}
        query, table = query_for(kind, ctx.tenant.id, project, source)
        if strict:
            # Keep the selected original records stable through the result transaction.
            c.execute(
                select(table.c.id)
                .where(
                    table.c.tenant_id == ctx.tenant.id,
                    table.c.project_id == project,
                    table.c.id.in_([UUID(key[1]) for key in targets]),
                )
                .order_by(table.c.id)
                .with_for_update()
            ).all()
        q = query.subquery()
        rows = c.execute(
            select(q).where(
                q.c.referenced_issue_id == issue,
                or_(
                    *[and_(q.c.id == UUID(key[1]), q.c.path_id == UUID(key[2])) for key in targets]
                ),
            )
        ).mappings()
        result.update({key: None for key in targets})
        for row in rows:
            value = reference_view(kind, project, row)
            result[reference_key(value)] = value
    return result


def freeze_reviews(
    c: Connection,
    ctx: AuthContext,
    project: UUID,
    source: dict[str, Any],
    issue: UUID,
    requested: list[BusinessReferenceReview],
) -> list[dict[str, Any]]:
    values = [item.model_dump(mode="json") for item in requested]
    current = resolve(c, ctx, project, source, issue, values, strict=True)
    frozen = []
    for item in values:
        actual = current[reference_key(item)]
        if actual is None or actual["digest"] != item["expected_digest"]:
            raise ConversationError("所选业务记录或引用关系已变化，请重新读取并核对该项结果")
        frozen.append(item | {"snapshot": actual})
    return frozen


def visible_reviews(
    saved: list[dict[str, Any]],
    current: dict[tuple[str, str, str], dict[str, Any] | None],
) -> list[dict[str, Any]]:
    visible = []
    for item in saved:
        key = reference_key(item)
        if key not in current:
            continue
        actual = current[key]
        visible.append(
            item
            | {
                "current": actual,
                "changed": actual is None or actual["digest"] != item["expected_digest"],
            }
        )
    return visible
