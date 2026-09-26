"""Real Requirement references pinned to opportunity revisions, in both directions."""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, or_, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role
from app.contracts.common_objects import Contract, Digest, SourceRef, Text
from app.db.schema import tables
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _line_filter,
    _plain,
    _role,
    _space,
    digest,
)


class RequirementLinkDraft(Contract):
    requirement_id: UUID
    payload_digest: Digest
    rationale: Text


def requirement_snapshot(row: Any) -> dict[str, Any]:
    return _plain(dict(row))


def links_for(
    connection: Connection, context: AuthContext, opportunity_id: UUID
) -> list[dict[str, Any]]:
    _role(context, Action.REQUIREMENT_VIEW)
    table = tables.opportunity_requirements
    rows = connection.execute(
        select(
            table,
            tables.requirements.c.updated_at.label("current_updated_at"),
            tables.requirements.c.status.label("current_status"),
        )
        .join(
            tables.requirements,
            (tables.requirements.c.tenant_id == table.c.tenant_id)
            & (tables.requirements.c.id == table.c.requirement_id),
        )
        .where(table.c.tenant_id == context.tenant.id, table.c.opportunity_id == opportunity_id)
        .order_by(table.c.created_at, table.c.id)
    ).mappings()
    result = []
    for row in rows:
        current = (
            connection.execute(
                select(tables.requirements).where(
                    tables.requirements.c.tenant_id == context.tenant.id,
                    tables.requirements.c.id == row["requirement_id"],
                )
            )
            .mappings()
            .one()
        )
        result.append(
            {
                **_plain(row),
                "has_changed": digest(requirement_snapshot(current)) != row["reference"]["digest"],
            }
        )
    return result


def save_links(
    connection: Connection,
    context: AuthContext,
    space_id: UUID,
    opportunity_id: UUID,
    previous_id: UUID | None,
    links: tuple[RequirementLinkDraft, ...],
) -> list[dict[str, Any]]:
    _role(context, Action.REQUIREMENT_VIEW)
    table = tables.opportunity_requirements
    previous = (
        {
            item["requirement_id"]: item
            for item in connection.execute(
                select(table).where(
                    table.c.tenant_id == context.tenant.id, table.c.opportunity_id == previous_id
                )
            ).mappings()
        }
        if previous_id
        else {}
    )
    # Stable ordering also avoids inversions when different spaces reference the same requirements.
    for link in sorted(links, key=lambda item: str(item.requirement_id)):
        row = (
            connection.execute(
                select(tables.requirements)
                .where(
                    tables.requirements.c.tenant_id == context.tenant.id,
                    tables.requirements.c.id == link.requirement_id,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ProductWorkAccessError("所选需求不存在或不可访问")
        snapshot = requirement_snapshot(row)
        fingerprint = digest(snapshot)
        prior = previous.get(link.requirement_id)
        if fingerprint == link.payload_digest:
            reference = SourceRef(
                tenant_id=context.tenant.id,
                kind="requirement",
                ref_id=row["id"],
                as_of=row["updated_at"],
                digest=fingerprint,
            ).model_dump(mode="json")
        elif prior is not None and prior["reference"]["digest"] == link.payload_digest:
            snapshot, reference = prior["requirement_snapshot"], prior["reference"]
        else:
            raise ProductWorkError("需求在选取后发生变化，请刷新需求并确认引用版本")
        connection.execute(
            table.insert().values(
                id=uuid4(),
                tenant_id=context.tenant.id,
                market_space_id=space_id,
                opportunity_id=opportunity_id,
                requirement_id=link.requirement_id,
                requirement_snapshot=snapshot,
                reference=reference,
                rationale=link.rationale,
            )
        )
    return links_for(connection, context, opportunity_id)


class OpportunityRequirementService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def options(self, context: AuthContext, space_id: UUID, query: str = "") -> dict[str, Any]:
        _role(context, Action.REQUIREMENT_VIEW)
        with self.engine.connect() as connection:
            _space(connection, context, space_id)
            table = tables.requirements
            statement = select(table).where(table.c.tenant_id == context.tenant.id)
            if query.strip():
                statement = statement.where(
                    or_(
                        table.c.code.icontains(query.strip(), autoescape=True),
                        table.c.title.icontains(query.strip(), autoescape=True),
                    )
                )
            rows = list(
                connection.execute(
                    statement.order_by(table.c.updated_at.desc(), table.c.id).limit(101)
                ).mappings()
            )
            return {
                "items": [
                    {
                        **requirement_snapshot(row),
                        "payload_digest": digest(requirement_snapshot(row)),
                    }
                    for row in rows[:100]
                ],
                "has_more": len(rows) > 100,
            }

    def backlinks(self, context: AuthContext, requirement_id: UUID) -> dict[str, Any]:
        _role(context, Action.REQUIREMENT_VIEW)
        _role(context, Action.PRODUCT_WORK_VIEW)
        with self.engine.connect() as connection:
            current = (
                connection.execute(
                    select(tables.requirements).where(
                        tables.requirements.c.tenant_id == context.tenant.id,
                        tables.requirements.c.id == requirement_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if current is None:
                raise ProductWorkAccessError("需求不存在或不可访问")
            link, opportunity, space = (
                tables.opportunity_requirements,
                tables.opportunities,
                tables.market_spaces,
            )
            successor = opportunity.alias("next_opportunity")
            statement = (
                select(
                    link,
                    opportunity.c.title.label("opportunity_title"),
                    opportunity.c.version.label("opportunity_version"),
                    opportunity.c.state.label("opportunity_state"),
                    opportunity.c.product_line_id,
                    space.c.title.label("space_title"),
                    (
                        ~select(successor.c.id)
                        .where(
                            successor.c.tenant_id == opportunity.c.tenant_id,
                            successor.c.supersedes_id == opportunity.c.id,
                        )
                        .exists()
                    ).label("is_latest"),
                )
                .join(
                    opportunity,
                    (opportunity.c.tenant_id == link.c.tenant_id)
                    & (opportunity.c.id == link.c.opportunity_id),
                )
                .join(
                    space,
                    (space.c.tenant_id == link.c.tenant_id)
                    & (space.c.id == link.c.market_space_id),
                )
                .where(
                    link.c.tenant_id == context.tenant.id,
                    link.c.requirement_id == requirement_id,
                    _line_filter(opportunity, context),
                )
            )
            if context.user.role not in {Role.OWNER, Role.ADMIN}:
                statement = statement.where(
                    space.c.id.in_(
                        select(tables.market_space_members.c.market_space_id).where(
                            tables.market_space_members.c.tenant_id == context.tenant.id,
                            tables.market_space_members.c.user_id == context.user.id,
                        )
                    )
                )
            rows = list(
                connection.execute(
                    statement.order_by(link.c.created_at.desc()).limit(201)
                ).mappings()
            )
            fingerprint = digest(requirement_snapshot(current))
            return {
                "items": [
                    {**_plain(row), "has_changed": row["reference"]["digest"] != fingerprint}
                    for row in rows[:200]
                ],
                "has_more": len(rows) > 200,
            }
