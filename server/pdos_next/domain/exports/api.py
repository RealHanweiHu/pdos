"""GET routes for `export.workbook.download` (READ, named human only)."""

from urllib.parse import quote
from uuid import UUID

from fastapi import Request
from fastapi.responses import Response

from pdos_next.core.service import Context
from pdos_next.errors import DomainError

from .service import XLSX, export

_BINARY = {200: {"content": {XLSX: {"schema": {"type": "string", "format": "binary"}}}}}


def _query(request, allowed):
    if any(key not in allowed for key in request.query_params) or any(
        len(request.query_params.getlist(key)) != 1 for key in request.query_params
    ):
        raise DomainError("VALIDATION_FAILED", "请只指定一个明确的导出范围。", 422)


def _deliver(export_id, filename, rendered):
    return Response(
        rendered.content,
        media_type=XLSX,
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "X-PDOS-Export-Id": str(export_id),
            "X-PDOS-Export-Rows": str(rendered.row_count),
            "X-PDOS-Export-AI-Rows": str(rendered.ai_row_count),
            "X-PDOS-Export-AI-Cells": str(rendered.ai_cell_count),
        },
    )


def register_routes(app, engine, auth_dependency):
    @app.get(
        "/v1/categories/{category_id}/products/{product_id}/exports/project",
        response_class=Response,
        responses=_BINARY,
    )
    def export_project(
        request: Request, product_id: UUID, project_id: UUID, ctx: Context = auth_dependency
    ):
        _query(request, {"project_id"})
        return _deliver(
            *export(engine, ctx, "project", product_id=product_id, project_id=project_id)
        )

    @app.get(
        "/v1/categories/{category_id}/products/{product_id}/exports/bom-diff",
        response_class=Response,
        responses=_BINARY,
    )
    def export_bom_diff(
        request: Request, product_id: UUID, bom_id: UUID, ctx: Context = auth_dependency
    ):
        _query(request, {"bom_id"})
        return _deliver(*export(engine, ctx, "bom_diff", product_id=product_id, bom_id=bom_id))

    @app.get(
        "/v1/categories/{category_id}/products/{product_id}/exports/test-summary",
        response_class=Response,
        responses=_BINARY,
    )
    def export_test_summary(
        request: Request, product_id: UUID, build_id: UUID, ctx: Context = auth_dependency
    ):
        _query(request, {"build_id"})
        return _deliver(
            *export(engine, ctx, "test_summary", product_id=product_id, build_id=build_id)
        )

    @app.get("/v1/personal/exports/my-work", response_class=Response, responses=_BINARY)
    def export_my_work(request: Request, ctx: Context = auth_dependency):
        _query(request, set())
        return _deliver(*export(engine, ctx, "my_work"))
