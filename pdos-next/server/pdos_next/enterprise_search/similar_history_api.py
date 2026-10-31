"""Ordinary authenticated page queries and explicit private feedback; no Run or egress."""

from typing import Annotated
from uuid import UUID

from fastapi import Query
from sqlalchemy.exc import OperationalError

from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.service import Context

from .similar_history import feedback, feedback_change, read, read_change, read_title
from .similar_history_schemas import (
    SimilarHistoryFeedback,
    SimilarHistoryInput,
    SimilarHistoryTitleInput,
)


def register_routes(app, engine, auth_dependency):
    path = ("/v1/categories/{category_id}/products/{product_id}"
            "/quality-issues/{issue_id}/similar-history")

    def perform(ctx, action, *, writing=False):
        try:
            with tenant_session(
                engine, ctx.tenant_id, actor_id=ctx.actor_id, requester_id=ctx.requester_id,
                category_id=ctx.category_id, read_snapshot=not writing,
            ) as session:
                return action(session)
        except OperationalError:
            raise DomainError("SOURCE_UNAVAILABLE", "相似历史暂不可读，请稍后重试。", 503) from None

    @app.get(path)
    def similar_history(product_id: UUID, issue_id: UUID,
                        data: Annotated[SimilarHistoryInput, Query()],
                        ctx: Context = auth_dependency):
        return perform(ctx, lambda session: read(
            session, ctx, product_id, issue_id, data.version_id,
        ))

    @app.post(path + "/feedback")
    def similar_history_feedback(product_id: UUID, issue_id: UUID,
                                 data: SimilarHistoryFeedback, ctx: Context = auth_dependency):
        return perform(ctx, lambda session: feedback(
            session, ctx, product_id, issue_id, data,
        ), writing=True)


    change_path = ("/v1/categories/{category_id}/products/{product_id}"
                   "/change-execution/{change_id}/similar-history")

    @app.get(change_path)
    def change_similar_history(product_id: UUID, change_id: UUID,
                               data: Annotated[SimilarHistoryInput, Query()],
                               ctx: Context = auth_dependency):
        return perform(ctx, lambda session: read_change(
            session, ctx, product_id, change_id, data.version_id,
        ))

    @app.post(change_path + "/feedback")
    def change_similar_history_feedback(product_id: UUID, change_id: UUID,
                                        data: SimilarHistoryFeedback,
                                        ctx: Context = auth_dependency):
        return perform(ctx, lambda session: feedback_change(
            session, ctx, product_id, change_id, data,
        ), writing=True)

    @app.get("/v1/categories/{category_id}/products/{product_id}/similar-history")
    def title_similar_history(product_id: UUID,
                              data: Annotated[SimilarHistoryTitleInput, Query()],
                              ctx: Context = auth_dependency):
        return perform(ctx, lambda session: read_title(session, ctx, product_id, data))
