"""Owner/Admin model and daily-budget governance HTTP boundary."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine, select

from app.ai.golden_suite import GoldenSuiteFileError, load_golden_suite
from app.ai.model_catalog import ModelCatalog, ProtocolKind, ProviderName
from app.ai.qualifications import GoldenQualificationFileError, load_golden_qualifications
from app.api.auth import current_context, no_store
from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.db.engine import get_engine
from app.db.schema import tables
from app.domain.model_governance import (
    BudgetSnapshot,
    ModelGovernanceService,
    ModelGovernanceSnapshot,
    ModelNotEligibleError,
    ModelSelection,
    ModelSettingsUpdate,
)

router = APIRouter(prefix="/api/ai/governance", tags=["ai-governance"])
DEFAULT_QUALIFICATIONS_PATH = (
    Path(__file__).resolve().parents[2] / "golden" / "model-qualifications.json"
)
DEFAULT_GOLDEN_SUITE_PATH = Path(__file__).resolve().parents[2] / "golden" / "model-gateway-v1.json"


class EligibleModelResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: ProviderName
    model: str
    protocol: ProtocolKind


class ModelSelectionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: ProviderName
    model: str
    available: bool


class BudgetResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    daily_token_budget: int
    used_tokens_today: int
    remaining_tokens_today: int
    exhausted: bool


class ModelGovernanceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    eligible_models: list[EligibleModelResponse]
    selection: ModelSelectionResponse | None
    budget: BudgetResponse


class ModelGovernanceUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: ProviderName
    model: str = Field(min_length=1, max_length=128)
    daily_token_budget: int = Field(ge=1, le=1_000_000_000)

    @field_validator("model", mode="before")
    @classmethod
    def normalize_model(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class AgentSubscriptionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_key: str
    status: str
    consecutive_failure_count: int
    failure_threshold: int
    paused_reason: str | None
    updated_at: datetime


def require_action(context: AuthContext, action: Action) -> None:
    if not is_allowed(context.user.role, action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "OBJECT_PERMISSION_DENIED",
                "message": "Model governance is restricted to tenant administrators",
            },
        )


def get_model_governance_service(
    engine: Annotated[Engine, Depends(get_engine)],
) -> ModelGovernanceService:
    qualification_path = Path(
        os.environ.get(
            "PDOS_LLM_GOLDEN_QUALIFICATIONS_PATH",
            str(DEFAULT_QUALIFICATIONS_PATH),
        )
    )
    try:
        trusted_suite = load_golden_suite(DEFAULT_GOLDEN_SUITE_PATH)
        qualifications = load_golden_qualifications(
            qualification_path,
            trusted_suite=trusted_suite,
        )
        default_budget = int(os.environ.get("PDOS_AI_DAILY_TOKEN_BUDGET", "2000000"))
        return ModelGovernanceService(
            engine,
            catalog=ModelCatalog.from_environment(os.environ),
            qualifications=qualifications,
            default_daily_token_budget=default_budget,
        )
    except (GoldenQualificationFileError, GoldenSuiteFileError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "MODEL_CATALOG_UNAVAILABLE",
                "message": "The qualified model catalog is unavailable",
            },
        ) from error


def selection_response(selection: ModelSelection | None) -> ModelSelectionResponse | None:
    if selection is None:
        return None
    return ModelSelectionResponse(
        provider=selection.provider,
        model=selection.model,
        available=selection.available,
    )


def budget_response(budget: BudgetSnapshot) -> BudgetResponse:
    return BudgetResponse(
        daily_token_budget=budget.daily_token_budget,
        used_tokens_today=budget.used_tokens_today,
        remaining_tokens_today=budget.remaining_tokens_today,
        exhausted=budget.exhausted,
    )


def governance_response(snapshot: ModelGovernanceSnapshot) -> ModelGovernanceResponse:
    return ModelGovernanceResponse(
        eligible_models=[
            EligibleModelResponse(
                provider=item.provider,
                model=item.model,
                protocol=item.protocol,
            )
            for item in snapshot.eligible_models
        ],
        selection=selection_response(snapshot.selection),
        budget=budget_response(snapshot.budget),
    )


@router.get("/model", response_model=ModelGovernanceResponse)
def get_model_governance(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    service: Annotated[ModelGovernanceService, Depends(get_model_governance_service)],
) -> ModelGovernanceResponse:
    require_action(context, Action.MODEL_GOVERNANCE_VIEW)
    no_store(response)
    return governance_response(service.get(tenant_id=context.tenant.id))


@router.patch("/model", response_model=ModelGovernanceResponse)
def update_model_governance(
    payload: ModelGovernanceUpdateRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    service: Annotated[ModelGovernanceService, Depends(get_model_governance_service)],
) -> ModelGovernanceResponse:
    require_action(context, Action.MODEL_GOVERNANCE_MANAGE)
    try:
        snapshot = service.update(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            changes=ModelSettingsUpdate(
                provider=payload.provider,
                model=payload.model,
                daily_token_budget=payload.daily_token_budget,
            ),
        )
    except ModelNotEligibleError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "MODEL_NOT_ELIGIBLE",
                "message": "The model is not configured and golden-qualified",
            },
        ) from error
    no_store(response)
    return governance_response(snapshot)


@router.get("/agents", response_model=list[AgentSubscriptionResponse])
def get_agent_subscriptions(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> list[AgentSubscriptionResponse]:
    require_action(context, Action.MODEL_GOVERNANCE_VIEW)
    with engine.connect() as connection:
        rows = list(
            connection.execute(
                select(tables.agent_subscriptions)
                .where(tables.agent_subscriptions.c.tenant_id == context.tenant.id)
                .order_by(tables.agent_subscriptions.c.agent_key)
            ).mappings()
        )
    no_store(response)
    return [
        AgentSubscriptionResponse(
            agent_key=str(row["agent_key"]),
            status=str(row["status"]),
            consecutive_failure_count=int(row["consecutive_failure_count"]),
            failure_threshold=int(row["failure_threshold"]),
            paused_reason=row["paused_reason"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]
