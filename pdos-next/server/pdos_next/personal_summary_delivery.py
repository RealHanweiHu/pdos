"""Own completed-summary feed derived from Runs; no message or notification writes."""

from typing import Annotated
from uuid import UUID

from fastapi import Query
from pydantic import Field
from sqlalchemy import and_, func, or_, select

from pdos_next.agent_kernel.models import AgentRun
from pdos_next.database import tenant_session
from pdos_next.domain.automations.models import AutomationRuleVersion as Version
from pdos_next.domain.automations.service_models import AutomationServiceAttempt as Attempt
from pdos_next.domain.automations.service_models import AutomationServiceGrant as Grant
from pdos_next.errors import DomainError
from pdos_next.models import Category, Principal, Receipt
from pdos_next.personal_views import _personal
from pdos_next.schema_base import StrictModel
from pdos_next.service import Context


class Page(StrictModel):
    cursor: UUID | None = None
    page_size: int = Field(default=25, ge=1, le=100)


def query(ctx):
    """Only original owner, actual admitted service binding and T1 publication."""
    r, a, g, v = AgentRun, Attempt, Grant, Version
    return (
        select(
            r.id.label("run_id"), r.category_id, Category.name.label("category_name"),
            r.created_at, r.state.label("status"), r.cancel_epoch,
            v.spec["name"].astext.label("title"),
            r.result["result"]["personal_summary"]["as_of"].astext.label("as_of"),
        )
        .join(a, and_(a.tenant_id == r.tenant_id, a.run_id == r.id,
                     a.category_id == r.category_id, a.owner_id == r.requester_id,
                     a.writer_id == r.writer_id, a.request_digest == r.intent_digest))
        .join(g, and_(g.tenant_id == a.tenant_id, g.id == a.service_grant_id,
                     g.category_id == a.category_id, g.owner_id == a.owner_id,
                     g.writer_id == a.writer_id, g.rule_id == a.rule_id,
                     g.published_version_id == a.published_version_id))
        .join(v, and_(v.tenant_id == g.tenant_id, v.id == g.published_version_id,
                     v.category_id == g.category_id, v.rule_id == g.rule_id,
                     v.owner_id == g.owner_id, v.receipt_id == g.receipt_id))
        .join(Receipt, and_(Receipt.tenant_id == v.tenant_id, Receipt.id == v.receipt_id,
                           Receipt.category_id == v.category_id,
                           Receipt.subject_id == v.id, Receipt.subject_revision == v.revision,
                           Receipt.operation == "ai.automation.activate",
                           Receipt.subject_type == "automation_rule",
                           Receipt.actor_id == v.owner_id, Receipt.requester_id == v.owner_id,
                           Receipt.confirmation_id == v.confirmation_id,
                           Receipt.command_id == v.command_id,
                           Receipt.request_digest == v.request_digest,
                           Receipt.intent_digest == v.intent_digest))
        .join(Category, and_(Category.tenant_id == r.tenant_id, Category.id == r.category_id))
        .where(
            r.tenant_id == ctx.tenant_id, r.requester_id == ctx.requester_id,
            r.trigger == "automation_service", r.state.in_(("completed", "partial")),
            r.reverted_at.is_(None), a.state == "admitted", v.action == "activate",
            v.state == "active", v.confirmation_id.is_not(None),
            v.operation == "ai.automation.activate",
            v.actor_id == r.requester_id, v.requester_id == r.requester_id,
            a.trigger_kind == v.spec["trigger_kind"].astext,
            func.jsonb_typeof(v.spec["personal_summary"]) == "object",
            r.result["result"]["personal_summary"]["version"].astext == "personal-summary/v1",
        )
    )


def read(s, ctx, *, cursor=None, page_size=25):
    _personal(s, ctx)
    principal = s.get(Principal, ctx.requester_id)
    if (s.info.get("read_snapshot") is not True or not principal or not principal.active
            or principal.tenant_id != ctx.tenant_id or principal.kind != "human"
            or ctx.agent_run_id is not None or ctx.run_id is not None):
        raise DomainError("FORBIDDEN_SCOPE", "摘要收件列表须由当前本人只读。", 403)
    base = query(ctx)
    if cursor is not None:
        anchor = s.execute(base.where(AgentRun.id == cursor)).mappings().first()
        if anchor is None:
            raise DomainError("FORBIDDEN_SCOPE", "摘要列表位置已不可读，请刷新。", 403)
        base = base.where(or_(
            AgentRun.created_at < anchor["created_at"],
            (AgentRun.created_at == anchor["created_at"]) & (AgentRun.id < cursor),
        ))
    rows = s.execute(base.order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
                     .limit(page_size + 1)).mappings().all()
    return {
        "version": "personal-summary-feed/v1", "principal_id": str(ctx.requester_id),
        "as_of": s.scalar(select(func.transaction_timestamp())).isoformat(),
        "items": [{
            "run_id": str(row["run_id"]), "category_id": str(row["category_id"]),
            "category_name": row["category_name"], "title": row["title"],
            "status": row["status"], "created_at": row["created_at"].isoformat(),
            "as_of": row["as_of"], "reading_token": f"{row['status']}:{row['cancel_epoch']}",
        } for row in rows[:page_size]],
        "next_cursor": str(rows[page_size - 1]["run_id"]) if len(rows) > page_size else None,
    }


class OptionsQuery(StrictModel):
    category_id: UUID
    product_id: UUID | None = None


def register_routes(app, engine, auth_dependency):
    from pdos_next.personal_summary_channels import register_routes as register_channels

    register_channels(app, engine, auth_dependency)

    @app.get("/v1/personal/inbox/summary-options")
    def summary_options(page: Annotated[OptionsQuery, Query()],
                        ctx: Context = auth_dependency):
        from pdos_next import personal_summary_templates

        with tenant_session(engine, ctx.tenant_id, actor_id=ctx.actor_id,
                            requester_id=ctx.requester_id, read_snapshot=True) as s:
            return personal_summary_templates.read(s, ctx, page.category_id, page.product_id)

    @app.get("/v1/personal/inbox/summaries")
    def summaries(page: Annotated[Page, Query()], ctx: Context = auth_dependency):
        with tenant_session(engine, ctx.tenant_id, actor_id=ctx.actor_id,
                            requester_id=ctx.requester_id, read_snapshot=True) as s:
            return read(s, ctx, cursor=page.cursor, page_size=page.page_size)
