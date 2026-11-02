"""Authenticated owner-only Session presentation routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from .session_presentation import (
    ConversationPage,
    PresentationInput,
    PresentationScope,
    change,
    read_list,
    read_request,
)


def router(*, transaction, context_dependency):
    result = APIRouter()

    @result.get("/v1/personal/agent-conversations")
    @result.get("/v1/categories/{category_id}/agent-conversations")
    def listing(page: Annotated[ConversationPage, Query()], ctx=context_dependency):
        with transaction(ctx, read_snapshot=True) as session:
            return read_list(session, ctx, page)

    @result.post("/v1/personal/agent-sessions/{session_id}/presentation")
    @result.post("/v1/categories/{category_id}/agent-sessions/{session_id}/presentation")
    def changing(
        session_id: UUID,
        data: PresentationInput,
        page: Annotated[PresentationScope, Query()],
        ctx=context_dependency,
    ):
        with transaction(ctx) as session:
            return change(session, ctx, session_id, data, page.proposal_id)

    @result.get("/v1/personal/agent-sessions/{session_id}/presentation/requests/{request_key}")
    @result.get(
        "/v1/categories/{category_id}/agent-sessions/{session_id}"
        "/presentation/requests/{request_key}"
    )
    def recovering(
        session_id: UUID,
        request_key: UUID,
        page: Annotated[PresentationScope, Query()],
        ctx=context_dependency,
    ):
        with transaction(ctx, read_snapshot=True) as session:
            return read_request(session, ctx, session_id, request_key, page.proposal_id)

    return result
