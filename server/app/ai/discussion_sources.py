"""Source routing for explicit discussion scopes; a topic is not a business whitelist."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from app.auth.roles import Action
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkAccessError, _role


def current(c: Connection, tenant: UUID, project: UUID, bound: Any) -> dict[str, Any]:
    if bound["source"].get("source_kind") == "project_discussion":
        from app.ai.project_discussion_sources import state

        return state(
            c, tenant, project, UUID(bound["source"]["actor_id"]), bound["source"]["selections"]
        )
    from app.ai.change_notice_preparation import rebuild

    return rebuild(c, tenant, project, bound["source"])


def require_disclosure(c: Connection, tenant: UUID, actor_id: UUID, bound: Any) -> None:
    from app.ai.discussion_research import require_disclosure as research_disclosure

    research_disclosure(c, tenant, actor_id, bound["run_id"])
    if bound["config"]["request"].get("research_steps"):
        from app.ai.project_discussion_sources import actor as research_actor

        _role(research_actor(c, tenant, actor_id), Action.EVIDENCE_VIEW)
    if bound["source"].get("source_kind") != "project_discussion":
        from app.ai.change_notice_preparation import is_notice
        from app.ai.change_notice_preparation import require_disclosure as notice_disclosure
        from app.ai.project_discussion_sources import actor

        if is_notice(bound["source"]):
            notice_disclosure(c, actor(c, tenant, actor_id), bound["source"])
        return
    from app.ai.project_discussion_sources import actor
    from app.domain.product_definitions import _row

    if str(actor_id) != bound["source"]["actor_id"]:
        raise ProductWorkAccessError("此主题讨论属于原发起人的工作会话")
    context = actor(c, tenant, actor_id)
    for source in bound["source"]["selections"]:
        from app.ai.cost_discussion_sources import KINDS as COST_KINDS
        from app.ai.cost_discussion_sources import authorize as cost_authorize

        if source["kind"] in COST_KINDS:
            cost_authorize(c, context, UUID(str(bound["project_id"])))
        if source["kind"] != "product_definition":
            continue
        _role(context, Action.PRODUCT_WORK_VIEW)
        table = tables.product_definitions
        definition = (
            c.execute(
                select(table).where(table.c.tenant_id == tenant, table.c.id == UUID(source["id"]))
            )
            .mappings()
            .one_or_none()
        )
        if definition is None:
            raise ProductWorkAccessError("原产品资料已不可访问")
        _row(c, context, definition["market_space_id"], definition["id"])
