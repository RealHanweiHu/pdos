"""Read-only matrix inputs in the existing private product conversation scope."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from app.ai.product_matrix_preparation import source_state
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.product_matrix_explanation import MatrixExplanationSelection
from app.db.schema import tables
from app.domain.product_matrix_records import record_row, visible
from app.domain.product_workspace import ProductWorkAccessError, _line, _plain, _role, _space


def authorize_scope(c: Connection, context: AuthContext, conversation: Any) -> None:
    if conversation["scope_kind"] not in {"market_space", "product_line"}:
        raise ProductWorkAccessError("矩阵解释需要已授权市场空间或产品线会话")
    _role(context, Action.PRODUCT_WORK_VIEW)
    _space(c, context, conversation["market_space_id"])
    _line(c, context, conversation["market_space_id"], conversation["product_line_id"])


def authorize_selection(
    c: Connection,
    context: AuthContext,
    conversation: Any,
    selection: MatrixExplanationSelection,
) -> Any:
    authorize_scope(c, context, conversation)
    saved = record_row(c, context, conversation["market_space_id"], selection.record_id)
    if saved["product_line_id"] != conversation["product_line_id"]:
        raise ProductWorkAccessError("所选矩阵记录不属于本会话的产品线范围")
    return saved


def prepare(
    c: Connection, context: AuthContext, conversation: Any, selection: dict[str, Any]
) -> dict[str, Any]:
    selected = MatrixExplanationSelection.model_validate(selection)
    authorize_selection(c, context, conversation, selected)
    snapshot = source_state(c, context, conversation["market_space_id"], selected)
    return {
        "kind": "matrix",
        "selection": selected.model_dump(mode="json"),
        "expected_digest": snapshot["digest"],
        "product_line_id": str(conversation["product_line_id"])
        if conversation["product_line_id"] is not None
        else None,
    }


def options(
    c: Connection,
    context: AuthContext,
    conversation: Any,
    before_id: UUID | None = None,
) -> dict[str, Any]:
    authorize_scope(c, context, conversation)
    t = tables.product_matrix_records
    query = select(t).where(
        t.c.tenant_id == context.tenant.id,
        t.c.market_space_id == conversation["market_space_id"],
        t.c.product_line_id.is_not_distinct_from(conversation["product_line_id"]),
        visible(context),
    )
    if before_id is not None:
        before = c.execute(query.where(t.c.id == before_id)).mappings().one_or_none()
        if before is None:
            raise ProductWorkAccessError("请从本会话可见的矩阵记录继续翻页")
        query = query.where(
            (t.c.created_at < before["created_at"])
            | ((t.c.created_at == before["created_at"]) & (t.c.id < before["id"]))
        )
    rows = list(
        c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(31)).mappings()
    )
    return _plain(
        {
            "items": [{k: row[k] for k in ("id", "title", "version")} for row in rows[:30]],
            "next_before": rows[29]["id"] if len(rows) > 30 else None,
        }
    )
