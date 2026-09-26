"""Unified search HTTP boundary (vNext V2-10, G11)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.api.work_items import authorize_project
from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.db.engine import get_engine
from app.domain.search import SampleMatcher, SearchAccessError, SearchQueryError, SearchService

router = APIRouter(prefix="/api/search", tags=["search"])


class SearchHitResponse(BaseModel):
    kind: str
    id: UUID
    project_id: UUID | None
    title: str
    excerpt: str
    score: int
    occurred_at: datetime
    project_name: str | None = None
    status: str | None = None
    locator: str | None = None
    fragment_ordinal: int | None = None
    fragment_count: int = 0
    href: str


class SearchResponse(BaseModel):
    items: list[SearchHitResponse]
    truncated: bool
    next_cursor: str | None = None
    terms: tuple[str, ...] = ()
    terms_truncated: bool = False


@router.get("", response_model=SearchResponse)
def search(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    q: Annotated[str, Query(min_length=1, max_length=200)],
    kinds: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    project_id: UUID | None = None,
    cursor: Annotated[str | None, Query(max_length=2000)] = None,
) -> SearchResponse:
    no_store(response)
    # Search spans work items, so the work-item read action is the gate; per-hit
    # reach is enforced inside the query itself.
    if not is_allowed(context.user.role, Action.WORK_ITEM_VIEW):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "SEARCH_FORBIDDEN", "message": "Search access denied"},
        )
    selected = tuple(part for part in (kinds or "").split(",") if part) or None
    try:
        result = SearchService(engine).search(
            tenant_id=context.tenant.id,
            user_id=context.user.id,
            role=context.user.role,
            query=q,
            kinds=selected,
            limit=limit,
            project_id=project_id,
            cursor=cursor,
        )
    except SearchAccessError as error:
        raise HTTPException(
            403, detail={"code": "SEARCH_FORBIDDEN", "message": str(error)}
        ) from error
    except SearchQueryError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "SEARCH_QUERY_INVALID", "message": str(error)},
        ) from error
    return SearchResponse(
        items=[SearchHitResponse(**asdict(hit)) for hit in result.hits],
        truncated=result.truncated,
        next_cursor=result.next_cursor,
        terms=result.terms,
        terms_truncated=result.terms_truncated,
    )


@router.get("/sources/{kind}/{identity}")
def source_detail(
    kind: str,
    identity: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    fragment: Annotated[int, Query(ge=1, le=100000)] = 1,
    offset: Annotated[int, Query(ge=0, le=2000000)] = 0,
    length: Annotated[int, Query(ge=1, le=12000)] = 6000,
) -> dict[str, Any]:
    no_store(response)
    try:
        return SearchService(engine).source(
            tenant_id=context.tenant.id,
            user_id=context.user.id,
            role=context.user.role,
            kind=kind,
            identity=identity,
            fragment=fragment,
            offset=offset,
            length=length,
        )
    except SearchQueryError as error:
        raise HTTPException(
            400, detail={"code": "SEARCH_QUERY_INVALID", "message": str(error)}
        ) from error
    except SearchAccessError as error:
        raise HTTPException(
            404, detail={"code": "SEARCH_SOURCE_UNAVAILABLE", "message": str(error)}
        ) from error


class SampleMatchResponse(BaseModel):
    sample_id: UUID
    serial_number: str
    project_id: UUID


class SampleMatchListResponse(BaseModel):
    items: list[SampleMatchResponse]
    ambiguous: bool


class SampleMatchRequest(BaseModel):
    text: str


@router.post("/projects/{project_id}/sample-matches", response_model=SampleMatchListResponse)
def match_samples(
    project_id: UUID,
    body: SampleMatchRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> SampleMatchListResponse:
    """Find which prototypes a field note refers to (G14/D37, no scanning).

    Returns every match. Two serials in one note is reported as ambiguous so
    the caller asks, rather than the server guessing which prototype a defect
    belongs to.
    """
    no_store(response)
    authorize_project(
        engine=engine,
        context=context,
        project_id=project_id,
        action=Action.WORK_ITEM_VIEW,
    )
    matches = SampleMatcher(engine).match(
        tenant_id=context.tenant.id, project_id=project_id, text_value=body.text
    )
    return SampleMatchListResponse(
        items=[
            SampleMatchResponse(
                sample_id=match.sample_id,
                serial_number=match.serial_number,
                project_id=match.project_id,
            )
            for match in matches
        ],
        ambiguous=len(matches) > 1,
    )
