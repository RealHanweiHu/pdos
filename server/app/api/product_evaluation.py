"""Private product evaluation plane; ordinary employee routes remain rollout gated."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field

from app.ai import application_gateway
from app.ai.product_evaluation import MAX_SUITE_BYTES, LoadedProductSuite, ProductEvaluationBinding
from app.ai.product_shadow_evaluation import ProductShadowEvaluation, Request, Selection, source
from app.api.auth import no_store
from app.api.product_research import _failure
from app.api.product_workspace import Context, Database

router = APIRouter(
    prefix="/api/product-work/spaces/{space_id}/evaluation", tags=["product-evaluation"]
)


class SuiteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evaluation_id: UUID
    suite_document: str = Field(min_length=1, max_length=MAX_SUITE_BYTES)
    suite_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    binding: ProductEvaluationBinding


@router.post("/suite")
def evaluate_suite(
    space_id: UUID, body: SuiteRequest, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    from app.ai.product_shadow_evaluation import authorize

    no_store(response)
    try:
        with engine.connect() as c:
            authorize(c, context, space_id)
        with application_gateway.configured_application_gateway(engine) as gateway:
            return ProductShadowEvaluation(engine, gateway=gateway).evaluate(
                context,
                space_id,
                LoadedProductSuite(body.suite_document.encode(), body.suite_sha256),
                body.binding,
                body.evaluation_id,
            )
    except Exception as error:
        if isinstance(error, (ValueError, KeyError, TypeError)):
            from fastapi import HTTPException

            raise HTTPException(
                409,
                detail={
                    "code": "PRODUCT_EVALUATION_INPUT_INVALID",
                    "message": "评测原件、范围或参考答案不可用，请重新核对",
                },
            ) from error
        raise _failure(error) from error


@router.post("/prepare")
def prepare(
    space_id: UUID, body: Selection, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductShadowEvaluation(engine).prepare(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.post("/runs")
def create(
    space_id: UUID, body: Request, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        # Reject unauthorized requests before opening provider configuration.
        with engine.connect() as c:
            source(c, context, space_id, body.selection)
        with application_gateway.configured_application_gateway(engine) as gateway:
            return ProductShadowEvaluation(engine, gateway=gateway).create(context, space_id, body)
    except Exception as error:
        raise _failure(error) from error


@router.get("/runs/{run_id}")
def read(
    space_id: UUID, run_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProductShadowEvaluation(engine).read(context, space_id, run_id)
    except Exception as error:
        raise _failure(error) from error
