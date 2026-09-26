"""Human-requested internal project reports; export never sends externally."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response

from app.api.auth import no_store
from app.api.product_workspace import Context, Database
from app.domain.audit_report_bundles import (
    AuditReportBundleService,
    BundleHistory,
    BundlePreview,
    BundleSave,
)
from app.domain.product_workspace import ProductWorkError
from app.domain.project_report_exports import (
    History,
    Options,
    Preview,
    ProjectReportExportService,
    Save,
    Withdraw,
)
from app.exports.audit_report_sources import AuditOptions
from app.storage.documents import DocumentObjectStore, get_document_object_store

router = APIRouter(prefix="/api/projects/{project_id}/reports", tags=["project-reports"])


def failure(error: Exception) -> HTTPException:
    if isinstance(error, PermissionError):
        return HTTPException(
            403,
            detail={"code": "REPORT_ACCESS_DENIED", "message": "无权读取所选项目或该类业务资料"},
            headers={"Cache-Control": "no-store"},
        )
    if isinstance(error, ProductWorkError):
        return HTTPException(
            409,
            detail={"code": "REPORT_INPUT_CHANGED", "message": str(error)},
            headers={"Cache-Control": "no-store"},
        )
    raise error


@router.post("/options")
def options(
    project_id: UUID, body: Options, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectReportExportService(engine).options(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/preview")
def preview(
    project_id: UUID, body: Preview, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectReportExportService(engine).preview(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/save")
def save(
    project_id: UUID, body: Save, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectReportExportService(engine).save(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/history")
def history(
    project_id: UUID, body: History, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectReportExportService(engine).history(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.get("/{record_id}/download")
def download(project_id: UUID, record_id: UUID, context: Context, engine: Database) -> Response:
    try:
        content, mime, filename = ProjectReportExportService(engine).download(
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
    project_id: UUID, body: AuditOptions, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectReportExportService(engine).audit_options(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/withdraw")
def withdraw(
    project_id: UUID, body: Withdraw, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return ProjectReportExportService(engine).withdraw(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/bundle-preview")
def bundle_preview(
    project_id: UUID, body: BundlePreview, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return AuditReportBundleService(engine).preview(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/bundle-save")
def bundle_save(
    project_id: UUID,
    body: BundleSave,
    context: Context,
    engine: Database,
    response: Response,
    store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
) -> dict[str, Any]:
    no_store(response)
    try:
        return AuditReportBundleService(engine, store).save(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.post("/bundle-history")
def bundle_history(
    project_id: UUID, body: BundleHistory, context: Context, engine: Database, response: Response
) -> dict[str, Any]:
    no_store(response)
    try:
        return AuditReportBundleService(engine).history(context, project_id, body)
    except Exception as error:
        raise failure(error) from error


@router.get("/{bundle_id}/bundle-download")
def bundle_download(
    project_id: UUID, bundle_id: UUID, context: Context, engine: Database
) -> Response:
    try:
        content, filename = AuditReportBundleService(engine).download(
            context, project_id, bundle_id
        )
        response = Response(
            content,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Content-Type-Options": "nosniff",
            },
        )
        no_store(response)
        return response
    except Exception as error:
        raise failure(error) from error
