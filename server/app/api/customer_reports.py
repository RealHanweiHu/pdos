"""Customer-visible report preparation, independent approval, and local downloads."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.auth import no_store
from app.api.product_workspace import Context, Database
from app.api.project_reports import failure
from app.domain.audit_customer_projection import (
    AuditDisclosureOptions,
    AuditPackageDraft,
    AuditPackageSave,
)
from app.domain.customer_report_packages import (
    CustomerReportService,
    PackageDecision,
    PackageDraft,
    PackageExport,
    PackageHistory,
    PackageOptions,
    PackageRead,
    PackageSave,
)
from app.storage.documents import DocumentObjectStore, get_document_object_store

router = APIRouter(prefix="/api/projects/{project_id}/customer-reports", tags=["customer-reports"])


@router.post("/options")
def options(
    project_id: UUID, body: PackageOptions, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return CustomerReportService(engine).options(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/preview")
def preview(
    project_id: UUID,
    body: PackageDraft | AuditPackageDraft,
    context: Context,
    engine: Database,
    response: Response,
) -> dict[str, Any]:
    no_store(response)
    try:
        return CustomerReportService(engine).preview(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/save")
def save(
    project_id: UUID,
    body: PackageSave | AuditPackageSave,
    context: Context,
    engine: Database,
    response: Response,
) -> dict[str, Any]:
    no_store(response)
    try:
        return CustomerReportService(engine).save(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/read")
def read(
    project_id: UUID, body: PackageRead, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return CustomerReportService(engine).read(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/decide")
def decide(
    project_id: UUID, body: PackageDecision, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return CustomerReportService(engine).decide(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/export")
def export(
    project_id: UUID,
    body: PackageExport,
    context: Context,
    engine: Database,
    response: Response,
    store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return CustomerReportService(engine, store).export(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/history")
def history(
    project_id: UUID, body: PackageHistory, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return CustomerReportService(engine).history(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.get("/{record_id}/download")
def download(project_id: UUID, record_id: UUID, context: Context, engine: Database) -> Response:
    try:
        content, mime, filename = CustomerReportService(engine).download(
            context, project_id, record_id
        )
        response = Response(
            content,
            media_type=mime,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Content-Type-Options": "nosniff",
            },
        )
        no_store(response)
        return response
    except Exception as error:
        raise failure(error) from error


@router.post("/audit-options")
def audit_options(
    project_id: UUID,
    body: AuditDisclosureOptions,
    context: Context,
    engine: Database,
    response: Response,
) -> dict[str, Any]:
    no_store(response)
    try:
        return CustomerReportService(engine).audit_options(context, project_id, body)
    except Exception as error:
        raise failure(error) from error
