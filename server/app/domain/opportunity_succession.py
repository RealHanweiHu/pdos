"""Append an ownership-only opportunity revision and retain its pinned requirements."""

from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import Connection, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.opportunity_requirements import RequirementLinkDraft, save_links
from app.domain.product_workspace import ProductWorkError, _emit, _role


def is_latest(c: Connection, tenant: UUID, id: UUID) -> bool:
    t = tables.opportunities
    return (
        c.execute(select(t.c.id).where(t.c.tenant_id == tenant, t.c.supersedes_id == id)).first()
        is None
    )


def transfer(
    c: Connection,
    context: AuthContext,
    space: UUID,
    row: Any,
    owner: UUID,
    request_id: UUID,
    signature: str,
) -> Any:
    _role(context, Action.REQUIREMENT_VIEW)
    if not is_latest(c, context.tenant.id, row["id"]):
        raise ProductWorkError("机会已有新版本，请从最新版本接续责任")
    t = tables.opportunities
    next_id = uuid5(
        NAMESPACE_URL,
        f"pdos:opportunity-succession:{context.tenant.id}:{context.user.id}:{request_id}",
    )
    values = {
        k: v
        for k, v in row.items()
        if k
        not in {
            "id",
            "owner_user_id",
            "version",
            "supersedes_id",
            "request_id",
            "request_digest",
            "created_at",
        }
    }
    successor = (
        c.execute(
            t.insert()
            .values(
                **values,
                id=next_id,
                owner_user_id=owner,
                version=row["version"] + 1,
                supersedes_id=row["id"],
                request_id=next_id,
                request_digest=signature,
            )
            .returning(t)
        )
        .mappings()
        .one()
    )
    link_table = tables.opportunity_requirements
    drafts = tuple(
        RequirementLinkDraft(
            requirement_id=r["requirement_id"],
            payload_digest=r["reference"]["digest"],
            rationale=r["rationale"],
        )
        for r in c.execute(
            select(link_table).where(
                link_table.c.tenant_id == context.tenant.id,
                link_table.c.opportunity_id == row["id"],
            )
        ).mappings()
    )
    links = save_links(c, context, space, next_id, row["id"], drafts)
    _emit(
        c,
        context,
        space,
        "opportunity",
        "responsibility_revision",
        {**successor, "requirement_links": links},
        before=row,
    )
    return successor
