"""P91: registered sources the Human requester can read now, across their categories.

Metadata only (no original text). Each row keeps its actual category and is
checked by the same per-category source head as the category picker.
"""

from uuid import UUID

from pydantic import Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import load_only

from pdos_next.core.models import Artifact, Category
from pdos_next.core.schema_base import StrictModel
from pdos_next.errors import DomainError

from .personal_sources import _require_human_self, category_context
from .source_views import ARTIFACT_FIELDS, _head, _metadata


class PersonalSourcePage(StrictModel):
    cursor: UUID | None = None
    page_size: int = Field(default=20, ge=1, le=50)


def read_list(session, ctx, page):
    _require_human_self(session, ctx)
    # No category GUC: ordinary RLS returns only categories the requester belongs to.
    query = (
        select(Artifact)
        .where(Artifact.tenant_id == ctx.tenant_id)
        .options(
            load_only(*(getattr(Artifact, field) for field in ARTIFACT_FIELDS), raiseload=True)
        )
    )
    if page.cursor is not None:
        anchor = session.scalar(query.where(Artifact.id == page.cursor))
        if anchor is None:
            raise DomainError("FORBIDDEN_SCOPE", "资料分页位置已不可读，请刷新。", 403)
        query = query.where(
            or_(
                Artifact.created_at < anchor.created_at,
                and_(Artifact.created_at == anchor.created_at, Artifact.id < anchor.id),
            )
        )
    rows = list(
        session.scalars(
            query.order_by(Artifact.created_at.desc(), Artifact.id.desc()).limit(page.page_size + 1)
        )
    )
    visible = rows[: page.page_size]
    names = (
        dict(
            session.execute(
                select(Category.id, Category.name).where(
                    Category.tenant_id == ctx.tenant_id,
                    Category.id.in_({row.category_id for row in visible}),
                )
            ).all()
        )
        if visible
        else {}
    )
    items = []
    for row in visible:
        scoped = category_context(ctx, row)
        head = _head(session, scoped, row.product_id, row, _metadata(session, [row], scoped, None))
        items.append(
            {
                **head,
                "category": {"id": str(row.category_id), "name": names.get(row.category_id)},
            }
        )
    return {
        "version": "personal-input-sources/v1",
        "principal_id": str(ctx.requester_id),
        "as_of": session.scalar(select(func.transaction_timestamp())).isoformat(),
        "items": items,
        "next_cursor": str(visible[-1].id) if len(rows) > page.page_size else None,
    }
