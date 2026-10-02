"""Read original abnormality events and their actual existing Issue links."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import Engine, and_, or_, select

from app.api.auth import current_context, no_store
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.engine import get_engine
from app.db.schema import tables
from app.domain.ai_issue_event_sources import read_event_source
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.knowledge_push import KnowledgeAccessError

router = APIRouter(prefix="/api/projects/{project_id}", tags=["work-items"])


def public_source(item: dict[str, Any]) -> dict[str, Any]:
    """Keep business evidence readable without publishing authorization internals."""
    raw = item["source"]
    source = {
        key: raw[key]
        for key in (
            "version",
            "source_key",
            "origin_kind",
            "original_result",
            "current_case",
            "current_run",
            "original_review",
            "latest_review",
            "current_assessment",
            "exception",
        )
        if key in raw
    }
    human = raw.get("human")
    if human:
        source["human"] = {key: human[key] for key in ("id", "display_name")}
    batch = raw.get("import_batch")
    if batch:
        source["import_batch"] = {
            key: batch.get(key)
            for key in (
                "id",
                "document_id",
                "plan_id",
                "created_run_ids",
                "confirmed_at",
                "superseded_by_batch_id",
            )
        }
    issue = item.get("existing_issue")
    return {
        **item,
        "source": source,
        "existing_issue": {key: issue[key] for key in ("id", "title", "status", "href")}
        if issue
        else None,
    }


def source_events(tenant: UUID, project: UUID) -> Any:
    e = tables.events
    return select(e.c.id).where(
        e.c.tenant_id == tenant,
        e.c.project_id == project,
        or_(
            e.c.event_type == "TEST_FAILED",
            and_(
                e.c.event_type == "NPI_RECORD_CHANGED",
                e.c.payload["record_type"].as_string() == "material_exception",
                e.c.payload["action"].as_string().in_(("confirmed", "reviewed")),
            ),
        ),
    )


@router.get("/ai-issue-event-sources")
def get_sources(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    before: Annotated[int | None, Query(gt=0, le=9007199254740991)] = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 20,
) -> dict[str, Any]:
    no_store(response)
    with (
        engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
        c.begin(),
    ):
        try:
            KnowledgeCorrectionService._authorize(
                c, context.tenant.id, context.user.id, project_id, Action.WORK_ITEM_VIEW
            )
            KnowledgeCorrectionService._authorize(
                c, context.tenant.id, context.user.id, project_id, Action.QUALITY_VIEW
            )
            KnowledgeCorrectionService._authorize(
                c, context.tenant.id, context.user.id, project_id, Action.PRODUCT_ENGINEERING_VIEW
            )
        except KnowledgeAccessError as error:
            raise HTTPException(status_code=403, detail="当前没有项目异常来源读取权限") from error
        if (
            c.execute(
                select(tables.projects.c.id).where(
                    tables.projects.c.tenant_id == context.tenant.id,
                    tables.projects.c.id == project_id,
                )
            ).first()
            is None
        ):
            raise HTTPException(status_code=404, detail="项目不存在或不在当前范围内")
        query = source_events(context.tenant.id, project_id)
        if before is not None:
            if c.execute(query.where(tables.events.c.id == before)).first() is None:
                raise HTTPException(status_code=409, detail="来源分页位置已不可用，请刷新")
            query = query.where(tables.events.c.id < before)
        ids = c.execute(query.order_by(tables.events.c.id.desc()).limit(limit + 1)).scalars().all()
        return {
            "items": [
                public_source(read_event_source(c, context.tenant.id, project_id, i))
                for i in ids[:limit]
            ],
            "next_before": ids[limit - 1] if len(ids) > limit else None,
            "notice": "按原事件核对异常和已有问题；已有关联问题时继续办理原单。"
            "当前核对不会创建问题或改变业务状态。",
        }
