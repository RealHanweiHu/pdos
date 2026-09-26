"""Version-bound original quality operations and their human workspace."""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine

from app.ai.quality_work_package_runs import Request as PreparationRequest
from app.api.auth import current_context, no_store
from app.api.quality_capa import capa_error
from app.auth.repository import AuthContext
from app.db.engine import get_engine
from app.domain import quality_operations as service
from app.domain.product_workspace import ProductWorkError

router = APIRouter(prefix="/api/projects/{project_id}/quality/ncrs/{ncr_id}", tags=["quality"])
Context = Annotated[AuthContext, Depends(current_context)]
Database = Annotated[Engine, Depends(get_engine)]
Offset = Annotated[int, Query(ge=0, le=100000)]


def error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(
            403,
            detail={"code": "QUALITY_OPERATION_DENIED", "message": "当前人员没有此质量操作权限"},
        )
    if isinstance(exc, ProductWorkError):
        return HTTPException(
            409, detail={"code": "QUALITY_OPERATION_CONFLICT", "message": str(exc)}
        )
    return capa_error(exc)


@router.get("/workspace")
def workspace(
    project_id: UUID,
    ncr_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    offset: Offset = 0,
) -> dict[str, Any]:
    no_store(response)
    try:
        return service.workspace(engine, context, project_id, ncr_id, offset)
    except Exception as exc:
        raise error(exc) from exc


@router.get("/evidence")
def evidence(
    project_id: UUID,
    ncr_id: UUID,
    kind: Literal["document", "event", "test_run"],
    response: Response,
    context: Context,
    engine: Database,
    offset: Offset = 0,
) -> dict[str, Any]:
    no_store(response)
    try:
        return service.evidence_options(engine, context, project_id, ncr_id, kind, offset)
    except Exception as exc:
        raise error(exc) from exc


@router.post("/operations")
def operate(
    project_id: UUID,
    ncr_id: UUID,
    body: service.Command,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    try:
        return service.execute(engine, context, project_id, ncr_id, body)
    except Exception as exc:
        raise error(exc) from exc


@router.get("/work-packages")
def applied_work_packages(
    project_id: UUID,
    ncr_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    offset: Offset = 0,
) -> dict[str, Any]:
    from app.auth.roles import Action
    from app.domain.quality_work_packages import applications

    no_store(response)
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
            service.authorize(c, context, project_id, Action.QUALITY_VIEW)
            service.authorize(c, context, project_id, Action.WORK_ITEM_VIEW)
            service.state(c, context.tenant.id, project_id, ncr_id)
            return applications(c, context.tenant.id, project_id, ncr_id, offset)
    except Exception as exc:
        raise error(exc) from exc


class PreparationSources(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selections: list[service.Evidence] = Field(default_factory=list, max_length=50)


@router.post("/preparation-context")
def preparation_context(
    project_id: UUID,
    ncr_id: UUID,
    body: PreparationSources,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    from app.ai.capability_contract import resolve_capability
    from app.ai.quality_preparation import source_state
    from app.ai.quality_work_package_runs import KEY
    from app.auth.roles import Action, is_allowed

    no_store(response)
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
            service.authorize(c, context, project_id, Action.QUALITY_VIEW)
            service.authorize(c, context, project_id, Action.WORK_ITEM_VIEW)
            snapshot = source_state(c, context.tenant.id, project_id, ncr_id, body.selections)
            return {
                "digest": snapshot["digest"],
                **snapshot["model_context"],
                "rollout": resolve_capability(KEY).rollout.value,
                "can_request": is_allowed(context.user.role, Action.CAPA_EXECUTE),
            }
    except Exception as exc:
        raise error(exc) from exc


@router.get("/preparation-runs")
def preparation_runs(
    project_id: UUID,
    ncr_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    before_id: UUID | None = None,
) -> dict[str, Any]:
    from app.ai.quality_work_package_runs import QualityWorkPackageRuns

    no_store(response)
    try:
        return QualityWorkPackageRuns.list_results(
            engine, context=context, project_id=project_id, ncr_id=ncr_id, before_id=before_id
        )
    except Exception as exc:
        raise error(exc) from exc


@router.post("/preparation-runs")
def prepare_quality_work(
    project_id: UUID,
    ncr_id: UUID,
    body: PreparationRequest,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    from app.ai.application_gateway import configured_application_gateway
    from app.ai.budget_ledger import BudgetLedgerError
    from app.ai.quality_work_package_runs import KEY, QualityWorkPackageRuns, _access
    from app.ai.rollout_guard import CapabilityUnavailableError, require_live_key
    from app.auth.roles import Action

    no_store(response)
    try:
        _access(engine, context, project_id, Action.CAPA_EXECUTE)
        require_live_key(KEY)
        with configured_application_gateway(engine) as gateway:
            return QualityWorkPackageRuns(engine, gateway=gateway).create(
                context=context, project_id=project_id, ncr_id=ncr_id, request=body
            )
    except (BudgetLedgerError, CapabilityUnavailableError) as exc:
        raise HTTPException(
            409, detail={"code": exc.code, "message": "本次品质准备的能力、预算或授权尚未就绪"}
        ) from exc
    except Exception as exc:
        raise error(exc) from exc
