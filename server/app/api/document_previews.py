"""Authenticated original downloads and explicit page comparison."""

from typing import Annotated, Any
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import Engine

from app.api.auth import current_context, no_store
from app.api.work_items import authorize_project
from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.db.engine import get_engine
from app.domain.document_previews import (
    DocumentPreviewError,
    DocumentPreviewMissing,
    DocumentPreviewService,
)
from app.domain.documents import MAX_PDF_PAGES
from app.storage.documents import DocumentObjectStore, get_document_object_store

router = APIRouter(
    prefix="/api/document-previews/projects/{project_id}", tags=["document-previews"]
)
Context = Annotated[AuthContext, Depends(current_context)]
Database = Annotated[Engine, Depends(get_engine)]
PageNumber = Annotated[int, Query(ge=1, le=MAX_PDF_PAGES)]


def access(engine: Engine, context: AuthContext, project: UUID) -> None:
    if not is_allowed(context.user.role, Action.DOCUMENT_ANALYZE):
        raise HTTPException(403, detail={"message": "当前无权查看文档"})
    authorize_project(
        engine=engine, context=context, project_id=project, action=Action.PROJECT_VIEW
    )


def error_response(error: Exception) -> HTTPException:
    if isinstance(error, DocumentPreviewMissing):
        return HTTPException(404, detail={"message": str(error)})
    if isinstance(error, DocumentPreviewError):
        return HTTPException(400, detail={"message": str(error)})
    return HTTPException(503, detail={"message": "文档暂不可读取，请稍后重试"})


@router.get("/compare")
def compare(
    project_id: UUID,
    left: UUID,
    right: UUID,
    left_page: PageNumber,
    right_page: PageNumber,
    response: Response,
    context: Context,
    engine: Database,
) -> dict[str, Any]:
    no_store(response)
    access(engine, context, project_id)
    try:
        return DocumentPreviewService(engine).compare(
            context.tenant.id, project_id, left, right, left_page, right_page
        )
    except Exception as error:
        raise error_response(error) from error


@router.get("/{document_id}")
def info(
    project_id: UUID, document_id: UUID, response: Response, context: Context, engine: Database
) -> dict[str, Any]:
    no_store(response)
    access(engine, context, project_id)
    try:
        return DocumentPreviewService(engine).info(context.tenant.id, project_id, document_id)
    except Exception as error:
        raise error_response(error) from error


@router.get("/{document_id}/text")
def page_text(
    project_id: UUID,
    document_id: UUID,
    page: PageNumber,
    response: Response,
    context: Context,
    engine: Database,
    offset: Annotated[int, Query(ge=0, le=2_000_000)] = 0,
) -> dict[str, Any]:
    no_store(response)
    access(engine, context, project_id)
    try:
        return DocumentPreviewService(engine).page_text(
            context.tenant.id, project_id, document_id, page, offset
        )
    except Exception as error:
        raise error_response(error) from error


@router.get("/{document_id}/original")
def original(
    project_id: UUID,
    document_id: UUID,
    context: Context,
    engine: Database,
    store: Annotated[DocumentObjectStore, Depends(get_document_object_store)],
) -> Response:
    access(engine, context, project_id)
    try:
        meta, content, pages = DocumentPreviewService(engine, store).original(
            context.tenant.id, project_id, document_id
        )
        return Response(
            content,
            media_type=meta["media_type"],
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": "attachment; filename*=UTF-8''"
                + quote(meta["filename"], safe=""),
                "X-Document-SHA256": meta["sha256"],
                "X-Document-Pages": str(pages or 0),
            },
        )
    except Exception as error:
        raise error_response(error) from error


@router.get("/{document_id}/email-text")
def email_text(
    project_id: UUID,
    document_id: UUID,
    response: Response,
    context: Context,
    engine: Database,
    after_ordinal: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    no_store(response)
    access(engine, context, project_id)
    try:
        return DocumentPreviewService(engine).email_text(
            context.tenant.id, project_id, document_id, after_ordinal
        )
    except Exception as error:
        raise error_response(error) from error
