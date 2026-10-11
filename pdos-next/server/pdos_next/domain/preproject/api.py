"""M3 reads use the same authenticated category root and common command endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import Query
from sqlalchemy import select, text

from pdos_next.database import tenant_session
from pdos_next.service import Context, require_access


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

    @app.get("/v1/categories/{category_id}/parameters")
    def parameters(
        parameter_ids: Annotated[list[UUID] | None, Query()] = None,
        include_history: bool = False,
        cursor: str | None = None,
        page_size: int = Query(default=50, ge=1, le=200),
        ctx: Context = auth_dependency,
    ):
        from .category_reads import parameters as read_parameters

        with scope(ctx) as s:
            return read_parameters(
                s,
                ctx,
                parameter_ids=parameter_ids,
                include_history=include_history,
                cursor=cursor,
                page_size=page_size,
            )

    @app.get("/v1/categories/{category_id}/knowledge")
    def knowledge(
        kind: str | None = None,
        status: str | None = "active",
        origin: str | None = None,
        region: str | None = None,
        include_history: bool = False,
        cursor: str | None = None,
        page_size: int = Query(default=50, ge=1, le=200),
        ctx: Context = auth_dependency,
    ):
        from .category_reads import knowledge as read_knowledge

        with scope(ctx) as s:
            return read_knowledge(
                s,
                ctx,
                kind=kind,
                status=status,
                origin=origin,
                region=region,
                include_history=include_history,
                cursor=cursor,
                page_size=page_size,
            )

    @app.get("/v1/categories/{category_id}/promotion-proofs/{proof_id}")
    def promotion_proof(proof_id: UUID, ctx: Context = auth_dependency):
        from .category_reads import promotion_proof as read_proof

        with scope(ctx) as s:
            return read_proof(s, ctx, proof_id)

    @app.get("/v1/categories/{category_id}/proposals")
    def proposals(
        cursor: UUID | None = None,
        page_size: int = Query(default=50, ge=1, le=200),
        ctx: Context = auth_dependency,
    ):
        from .access import installed
        from .models import Proposal

        with scope(ctx) as s:
            require_access(s, ctx, None)
            installed(s)
            query = select(Proposal).order_by(Proposal.id).limit(page_size + 1)
            if cursor:
                query = query.where(Proposal.id > cursor)
            rows = list(s.scalars(query))
            return {
                "items": [
                    {
                        "id": str(p.id),
                        "title": p.title,
                        "status": p.status,
                        "revision": p.revision,
                        "owner_id": str(p.owner_id),
                        "visibility": p.effective_visibility,
                    }
                    for p in rows[:page_size]
                ],
                "next_cursor": str(rows[page_size - 1].id) if len(rows) > page_size else None,
                "as_of": s.scalar(text("SELECT transaction_timestamp()")).isoformat(),
            }

    @app.get("/v1/categories/{category_id}/proposals/{proposal_id}")
    def proposal_read(proposal_id: UUID, ctx: Context = auth_dependency):
        from .views import read

        with scope(ctx) as s:
            require_access(s, ctx, None)
            return read(s, ctx, proposal_id)

    @app.get("/v1/categories/{category_id}/proposals/{proposal_id}/items")
    def proposal_items(
        proposal_id: UUID, include_history: bool = False, ctx: Context = auth_dependency
    ):
        from .access import proposal
        from .views import items

        with scope(ctx) as s:
            require_access(s, ctx, None)
            return {
                "items": items(s, proposal(s, ctx, proposal_id), include_history=include_history)
            }

    @app.get("/v1/categories/{category_id}/proposals/{proposal_id}/participants")
    def proposal_participants(proposal_id: UUID, ctx: Context = auth_dependency):
        from pdos_next.clock import now
        from pdos_next.models import Grant, Principal

        from .access import proposal

        with scope(ctx) as s:
            require_access(s, ctx, None)
            row = proposal(s, ctx, proposal_id)
            query = (
                select(Principal, Grant)
                .join(
                    Grant,
                    (Grant.tenant_id == Principal.tenant_id) & (Grant.principal_id == Principal.id),
                )
                .where(
                    Grant.category_id == ctx.category_id,
                    Principal.active.is_(True),
                    Principal.kind == "human",
                    Grant.expires_at.is_(None) | (Grant.expires_at > now()),
                )
            )
            return {
                "items": [
                    {
                        "id": str(person.id),
                        "name": person.name,
                        "can_write": grant.can_write,
                        "reviewer_eligible": grant.product_manager and person.id != row.owner_id,
                    }
                    for person, grant in s.execute(query)
                ]
            }

    @app.get("/v1/categories/{category_id}/views/definition-maturity")
    def definition_maturity(proposal_id: UUID, ctx: Context = auth_dependency):
        from .access import proposal
        from .views import document, maturity

        with scope(ctx) as s:
            require_access(s, ctx, None)
            return maturity(document(s, proposal(s, ctx, proposal_id)))

    @app.get("/v1/categories/{category_id}/projects/{project_id}/open-items")
    def project_items(project_id: UUID, ctx: Context = auth_dependency):
        from .models import ProjectOpenItem

        with scope(ctx) as s:
            require_access(s, ctx, None)
            return {
                "items": [
                    {
                        "id": str(item.id),
                        "kind": item.kind,
                        "title": item.title,
                        "owner_id": str(item.owner_id),
                        "due_date": item.due_date.isoformat(),
                        "status": item.status,
                        "g0_decision_id": str(item.g0_decision_id),
                    }
                    for item in s.scalars(
                        select(ProjectOpenItem).where(ProjectOpenItem.project_id == project_id)
                    )
                ]
            }

    @app.get("/v1/categories/{category_id}/g0-definitions/{definition_id}")
    def g0_definition(definition_id: UUID, ctx: Context = auth_dependency):
        from .access import fail, installed

        with scope(ctx) as s:
            require_access(s, ctx, None)
            installed(s)
            row = (
                s.execute(
                    text(
                        "SELECT id,product_id,revision,sealed,source_proposal_id,"
                        "source_submission_id,source_proposal_revision,g0_decision_id "
                        "FROM definition_revisions WHERE id=:id AND sealed"
                    ),
                    {"id": definition_id},
                )
                .mappings()
                .first()
            )
            if not row:
                fail("NOT_FOUND", "definition_not_found", "定义不存在或不可读。", 404)
            specs = s.execute(
                text(
                    "SELECT id,key,parameter,value_type,value,lower,upper,text AS text_value,"
                    "unit,condition_note,method AS verification_method,acceptance_criterion,"
                    "item_status,availability,nature,modality,exceptions,applicable_variants,"
                    "source_refs,origin,writer_id,run_id,confirmed_by FROM definition_specs "
                    "WHERE definition_id=:id ORDER BY key"
                ),
                {"id": definition_id},
            ).mappings()
            return {**row, "specs": [dict(spec) for spec in specs]}
