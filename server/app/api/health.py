from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    service: Literal["pdos-api"] = "pdos-api"
    version: Literal["0.1.0"] = "0.1.0"


@router.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    """Report process liveness without touching external dependencies."""
    return HealthResponse()
