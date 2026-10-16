"""Small object metadata lookup inside the personal caller's existing RR/RLS snapshot."""

from uuid import UUID

from sqlalchemy import and_, case, func, literal, or_, select, union_all

from pdos_next.domain.preproject.models import Proposal
from pdos_next.domain.projects.models import Project
from pdos_next.errors import DomainError
from pdos_next.models import Category, Product
from pdos_next.service import digest


def search(session, ctx, query, *, kind="all", cursor=None, page_size=20):
    pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    try:
        identity = UUID(query)
    except ValueError:
        identity = None
    branches = []
    for label, model, title in (
        ("category", Category, Category.name),
        ("project", Project, Project.name),
        ("product", Product, Product.name),
        ("proposal", Proposal, Proposal.title),
    ):
        if kind not in {"all", label}:
            continue
        category_id = model.id if model is Category else model.category_id
        exact = model.id == identity if identity else literal(False)
        branch = select(
            literal(label).label("kind"),
            model.id.label("id"),
            title.label("title"),
            category_id.label("category_id"),
            Category.name.label("category_name"),
            (
                model.product_id
                if model is Project
                else model.id
                if model is Product
                else literal(None, type_=model.id.type)
            ).label("product_id"),
            model.created_at.label("created_at"),
            case((exact, 2), (func.lower(title) == query.lower(), 1), else_=0).label("rank"),
        ).where(
            model.tenant_id == ctx.tenant_id,
            or_(exact, title.ilike(pattern, escape="\\")),
        )
        if model is not Category:
            branch = branch.join(
                Category,
                and_(
                    Category.id == category_id,
                    Category.tenant_id == model.tenant_id,
                ),
            )
        branches.append(branch)
    matches = union_all(*branches).subquery("object_matches")
    request_digest = digest([query, kind])[:16]
    statement = select(matches)
    if cursor:
        anchor_kind, anchor_id, fingerprint = cursor.split(":")
        if fingerprint != request_digest:
            raise DomainError("SOURCE_STALE", "搜索条件已变化，请重新搜索。")
        anchor = session.execute(
            select(matches).where(
                matches.c.kind == anchor_kind,
                matches.c.id == UUID(anchor_id),
            )
        ).first()
        if not anchor:
            raise DomainError("SOURCE_STALE", "分页位置已不可读，请重新搜索。")
        statement = statement.where(
            or_(
                matches.c.rank < anchor.rank,
                and_(matches.c.rank == anchor.rank, matches.c.created_at < anchor.created_at),
                and_(
                    matches.c.rank == anchor.rank,
                    matches.c.created_at == anchor.created_at,
                    matches.c.kind > anchor.kind,
                ),
                and_(
                    matches.c.rank == anchor.rank,
                    matches.c.created_at == anchor.created_at,
                    matches.c.kind == anchor.kind,
                    matches.c.id > anchor.id,
                ),
            )
        )
    rows = session.execute(
        statement.order_by(
            matches.c.rank.desc(),
            matches.c.created_at.desc(),
            matches.c.kind,
            matches.c.id,
        ).limit(page_size + 1)
    ).all()
    page = rows[:page_size]
    return {
        "query": query,
        "kind": kind,
        "items": [
            {
                "kind": row.kind,
                "id": str(row.id),
                "title": row.title,
                "category_id": str(row.category_id),
                "category_name": row.category_name,
                "product_id": str(row.product_id) if row.product_id else None,
            }
            for row in page
        ],
        "next_cursor": f"{page[-1].kind}:{page[-1].id}:{request_digest}"
        if len(rows) > page_size
        else None,
        "as_of": session.scalar(select(func.transaction_timestamp())).isoformat(),
    }
