"""Human provider agreement registration over the existing named domain service."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import Query
from pydantic import Field
from sqlalchemy import select

from pdos_next.database import category_transaction, tenant_session
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal, now
from pdos_next.schema_base import StrictModel
from pdos_next.service import Context, require_access

from .management import AgreementInput, agreement_receipt, register_agreement
from .models import ProviderDataAgreement, TenantAdministrator


class AgreementRequest(AgreementInput):
    provider: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9:_.@/-]{0,159}$")
    data_categories: list[
        Literal["public", "synthetic", "internal", "customer", "customer_original"]
    ] = Field(min_length=1)
    decision: Literal["批准"]


class AgreementQuery(StrictModel):
    provider: str | None = Field(default=None, min_length=1, max_length=160)
    cursor: str | None = Field(default=None, min_length=1, max_length=160)
    page_size: int = Field(default=50, ge=1, le=200)


def human(session, ctx):
    require_access(session, ctx, None)
    actor = session.get(Principal, ctx.actor_id)
    if (
        ctx.actor_id != ctx.requester_id
        or not actor
        or not actor.active
        or actor.kind != "human"
        or ctx.run_id
        or ctx.agent_run_id
    ):
        raise DomainError("NAMED_DECISION_REQUIRED", "请由本人会话读取或登记服务商协议。", 403)


def reading(session, ctx, page):
    human(session, ctx)
    admin = session.scalar(
        select(TenantAdministrator.id).where(
            TenantAdministrator.tenant_id == ctx.tenant_id,
            TenantAdministrator.principal_id == ctx.actor_id,
            TenantAdministrator.active.is_(True),
        )
    )
    grant = session.scalar(
        select(Grant.can_write).where(
            Grant.tenant_id == ctx.tenant_id,
            Grant.category_id == ctx.category_id,
            Grant.principal_id == ctx.actor_id,
        )
    )
    latest = (
        select(ProviderDataAgreement)
        .where(
            ProviderDataAgreement.tenant_id == ctx.tenant_id,
        )
        .distinct(ProviderDataAgreement.provider)
        .order_by(
            ProviderDataAgreement.provider,
            ProviderDataAgreement.revision.desc(),
        )
        .subquery()
    )
    query = select(latest)
    if page.provider:
        query = query.where(latest.c.provider == page.provider)
    if page.cursor:
        query = query.where(latest.c.provider > page.cursor)
    rows = session.execute(query.order_by(latest.c.provider).limit(page.page_size + 1)).all()
    people = (
        dict(
            session.execute(
                select(Principal.id, Principal.name).where(
                    Principal.tenant_id == ctx.tenant_id,
                    Principal.id.in_({row.registered_by for row in rows}),
                )
            ).all()
        )
        if rows
        else {}
    )
    instant = now()
    return {
        "can_edit": bool(admin and grant),
        "items": [
            {
                "id": str(row.id),
                "provider": row.provider,
                "revision": row.revision,
                "signed_on": row.signed_on.isoformat(),
                "expires_at": row.expires_at.isoformat(),
                "data_categories": row.data_categories,
                "retention_terms": row.retention_terms,
                "training_terms": row.training_terms,
                "active": row.active,
                "registered_by": str(row.registered_by),
                "registered_by_name": people.get(row.registered_by),
                "receipt_id": str(row.receipt_id) if row.receipt_id else None,
                "status": "inactive"
                if not row.active
                else "expired"
                if row.expires_at <= instant
                else "not_started"
                if row.signed_on > instant
                else "active",
            }
            for row in rows[: page.page_size]
        ],
        "next_cursor": rows[page.page_size - 1].provider if len(rows) > page.page_size else None,
        "as_of": instant.isoformat(),
    }


def register_routes(app, engine, auth_dependency):
    def scope(ctx):
        return tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=True,
        )

    @app.get("/v1/categories/{category_id}/provider-agreements")
    def agreements(
        category_id: UUID, page: Annotated[AgreementQuery, Query()], ctx: Context = auth_dependency
    ):
        with scope(ctx) as session:
            return reading(session, ctx, page)

    @app.post("/v1/categories/{category_id}/provider-agreements/recover")
    def recover(category_id: UUID, data: AgreementRequest, ctx: Context = auth_dependency):
        with scope(ctx) as session:
            human(session, ctx)
            return {"receipt": agreement_receipt(session, ctx, data)}

    @app.post("/v1/categories/{category_id}/provider-agreements")
    def register(category_id: UUID, data: AgreementRequest, ctx: Context = auth_dependency):
        def execute(session):
            human(session, ctx)
            require_access(session, ctx, None, write=True, lock=True)
            return register_agreement(session, ctx, data)

        return category_transaction(engine, ctx, execute)
