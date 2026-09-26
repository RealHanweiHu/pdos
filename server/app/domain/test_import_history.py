"""Plan-scoped report history, including batches without generated test runs."""

from typing import Any
from uuid import UUID

from sqlalchemy import Engine, func, select, tuple_

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.product_workspace import _plain
from app.domain.test_import_preview import authorize_preview
from app.domain.test_report_workbook import ImportError_


def history(
    engine: Engine, context: AuthContext, project_id: UUID, plan_id: UUID, before_id: UUID | None
) -> dict[str, Any]:
    authorize_preview(engine, context, project_id)
    b, d, p = tables.test_report_import_batches, tables.documents, tables.test_plans
    with engine.connect() as c:
        if (
            c.scalar(
                select(p.c.id).where(
                    p.c.tenant_id == context.tenant.id,
                    p.c.project_id == project_id,
                    p.c.id == plan_id,
                )
            )
            is None
        ):
            raise ImportError_("IMPORT_PLAN_NOT_FOUND", "测试计划不存在")
        scope = (
            b.c.tenant_id == context.tenant.id,
            b.c.project_id == project_id,
            b.c.plan_id == plan_id,
        )
        query = (
            select(
                b.c.id,
                b.c.document_id,
                d.c.filename,
                b.c.status,
                b.c.created_at,
                b.c.confirmed_at,
                b.c.parent_batch_id,
                b.c.superseded_by_batch_id,
                func.jsonb_array_length(b.c.created_run_ids).label("run_count"),
                func.jsonb_array_length(b.c.skipped_rows).label("skipped_count"),
            )
            .join(
                d,
                (d.c.tenant_id == b.c.tenant_id)
                & (d.c.project_id == b.c.project_id)
                & (d.c.id == b.c.document_id),
            )
            .where(*scope)
        )
        if before_id:
            cursor = c.execute(
                select(b.c.created_at, b.c.id).where(*scope, b.c.id == before_id)
            ).one_or_none()
            if cursor is None:
                raise ImportError_("IMPORT_HISTORY_CURSOR_CHANGED", "历史位置不可用，请重新读取")
            query = query.where(
                tuple_(b.c.created_at, b.c.id) < tuple_(cursor.created_at, cursor.id)
            )
        records = (
            c.execute(query.order_by(b.c.created_at.desc(), b.c.id.desc()).limit(21))
            .mappings()
            .all()
        )
        return {
            "items": [_plain(record) for record in records[:20]],
            "next_before_id": str(records[19]["id"]) if len(records) > 20 else None,
        }
