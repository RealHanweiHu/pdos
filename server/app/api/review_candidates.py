"""Read-only risk candidate aggregation for the AI Review Inbox."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.api.issue_risks import RiskCandidateListResponse, risk_response
from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.db.engine import get_engine
from app.domain.risk_candidates import RiskCandidateService

router = APIRouter(prefix="/api/ai", tags=["ai-review"])


@router.get("/risk-candidates", response_model=RiskCandidateListResponse)
def list_review_candidates(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> RiskCandidateListResponse:
    no_store(response)
    if not is_allowed(context.user.role, Action.FINDING_VIEW):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "REVIEW_CANDIDATES_FORBIDDEN",
                "message": "This role cannot view review candidates",
            },
        )
    return RiskCandidateListResponse(
        items=[
            risk_response(item)
            for item in RiskCandidateService(engine).list_visible_candidates(
                tenant_id=context.tenant.id,
                member_user_id=(
                    None if context.user.role in {"owner", "admin"} else context.user.id
                ),
            )
        ]
    )
