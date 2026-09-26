"""Keep approved experiment plans intact when responsibility needs to change."""

from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import Connection, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.experiments import PLAN_FIELDS
from app.domain.product_workspace import ProductWorkError, _emit


def source_info(c: Connection, context: AuthContext, row: Any) -> dict[str, Any]:
    o = tables.opportunities
    opportunity = (
        c.execute(
            select(o).where(o.c.tenant_id == context.tenant.id, o.c.id == row["opportunity_id"])
        )
        .mappings()
        .one()
    )
    newer = c.execute(
        select(o.c.id).where(
            o.c.tenant_id == context.tenant.id, o.c.supersedes_id == opportunity["id"]
        )
    ).first()
    return {
        "title": row["hypothesis"],
        "source_is_current": row["state"] == "draft"
        or (opportunity["state"] != "closed" and newer is None),
    }


def transfer(
    c: Connection,
    context: AuthContext,
    space: UUID,
    row: Any,
    owner: UUID,
    request_id: UUID,
    signature: str,
    reason: str,
) -> Any:
    if not source_info(c, context, row)["source_is_current"]:
        raise ProductWorkError("原机会已关闭或修订；请核对当前方案重新准备实验，原实验保持不变")
    t = tables.experiments
    now = datetime.now(UTC)
    closed = (
        c.execute(
            t.update()
            .where(t.c.tenant_id == context.tenant.id, t.c.id == row["id"])
            .values(
                state="cancelled",
                cancellation_reason=reason,
                version=row["version"] + 1,
                updated_at=now,
            )
            .returning(t)
        )
        .mappings()
        .one()
    )
    next_id = uuid5(
        NAMESPACE_URL,
        f"pdos:experiment-succession:{context.tenant.id}:{context.user.id}:{request_id}",
    )
    values = {key: row[key] for key in PLAN_FIELDS}
    values["owner_user_id"] = owner
    successor = (
        c.execute(
            t.insert()
            .values(
                **values,
                id=next_id,
                tenant_id=context.tenant.id,
                market_space_id=space,
                product_line_id=row["product_line_id"],
                opportunity_id=row["opportunity_id"],
                solution_id=row["solution_id"],
                created_by_user_id=context.user.id,
                request_id=next_id,
                request_digest=signature,
            )
            .returning(t)
        )
        .mappings()
        .one()
    )
    _emit(c, context, space, "experiment", "cancelled_for_succession", closed, before=row)
    _emit(c, context, space, "experiment", "created_from_succession", successor)
    return successor
