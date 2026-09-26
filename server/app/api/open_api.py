"""Scoped external operations and authenticated project credential administration."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.auth import no_store
from app.api.product_workspace import Context, Database
from app.api.project_reports import failure
from app.domain.open_api_calls import (
    ApiCall,
    FileRead,
    FileReceipt,
    OpenApiCallService,
    OpenApiError,
    ReportQuery,
    ReportRead,
    WorkQuery,
)
from app.domain.open_api_credentials import (
    CallHistory,
    CredentialCreate,
    CredentialHistory,
    CredentialRevoke,
    OpenApiCredentialService,
)

router = APIRouter(prefix="/api/projects/{project_id}/open-api", tags=["open-api-administration"])
external_router = APIRouter(
    prefix="/api/open/v1/projects/{project_id}", tags=["controlled-external-api"]
)
Bearer = Annotated[
    HTTPAuthorizationCredentials | None,
    Depends(HTTPBearer(auto_error=False, scheme_name="PDOSExternalCredential")),
]


@router.post("/options")
def options(
    project_id: UUID, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return OpenApiCredentialService(engine).options(context, project_id)
    except Exception as error:
        raise failure(error) from error


@router.post("/create")
def create(
    project_id: UUID, body: CredentialCreate, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return OpenApiCredentialService(engine).create(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/revoke")
def revoke(
    project_id: UUID, body: CredentialRevoke, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return OpenApiCredentialService(engine).revoke(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/history")
def history(
    project_id: UUID,
    body: CredentialHistory,
    context: Context,
    engine: Database,
    response: Response,
) -> dict[str, Any]:
    no_store(response)
    try:
        return OpenApiCredentialService(engine).history(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/calls")
def calls(
    project_id: UUID, body: CallHistory, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return OpenApiCredentialService(engine).calls(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


def execute(
    project: UUID,
    body: ApiCall,
    auth: HTTPAuthorizationCredentials | None,
    engine: Any,
    operation: str,
) -> Response:
    if auth is None or auth.scheme.lower() != "bearer":
        raise HTTPException(
            401, detail={"message": "需要受控接口凭据"}, headers={"Cache-Control": "no-store"}
        )
    try:
        status, payload, binary = OpenApiCallService(engine).invoke(
            auth.credentials, project, operation, body
        )
    except OpenApiError as error:
        raise HTTPException(
            error.status, detail={"message": error.message}, headers={"Cache-Control": "no-store"}
        ) from error
    headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "X-PDOS-Call-ID": payload["call_id"],
        "X-PDOS-Replayed": str(payload["replayed"]).lower(),
    }
    if binary is not None:
        content, mime, filename = binary
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        headers["X-Content-SHA256"] = payload["result"]["file"]["content_digest"]
        return Response(content, media_type=mime, headers=headers)
    return JSONResponse(payload, status_code=status, headers=headers)


@external_router.post("/work/query")
def work(project_id: UUID, body: WorkQuery, auth: Bearer, engine: Database) -> Response:
    return execute(project_id, body, auth, engine, "work.query")


@external_router.post("/customer-reports/query")
def reports(project_id: UUID, body: ReportQuery, auth: Bearer, engine: Database) -> Response:
    return execute(project_id, body, auth, engine, "customer_reports.query")


@external_router.post("/customer-reports/read")
def report(project_id: UUID, body: ReportRead, auth: Bearer, engine: Database) -> Response:
    return execute(project_id, body, auth, engine, "customer_reports.read")


@external_router.post("/customer-files/read")
def file(project_id: UUID, body: FileRead, auth: Bearer, engine: Database) -> Response:
    return execute(project_id, body, auth, engine, "customer_files.read")


@external_router.post("/customer-receipts/record")
def receipt(project_id: UUID, body: FileReceipt, auth: Bearer, engine: Database) -> Response:
    return execute(project_id, body, auth, engine, "customer_receipts.record")
