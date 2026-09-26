"""Source-domain access remains required for notice-derived model outputs."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from app.db.schema import tables
from app.domain.product_workspace import ProductWorkAccessError


def require(c: Connection, record: Any, actor_id: UUID | None) -> None:
    if record.finding_type == "cost_reduction":
        from app.domain.cost_reduction_findings import authorize

        if actor_id is None:
            raise ProductWorkAccessError("读取成本建议须核对当前具名读取人")
        authorize(c, record, actor_id, write=False)
        return
    if record.finding_type != "change_work_package":
        return
    from app.ai.change_notice_preparation import is_notice, require_disclosure
    from app.domain.supplier_notice_impact import actor

    rc = c.execute(
        select(tables.agent_runs.c.run_context).where(
            tables.agent_runs.c.tenant_id == record.tenant_id,
            tables.agent_runs.c.id == record.run_id,
        )
    ).scalar_one()
    source = rc.get("impact_source", {})
    if not is_notice(source):
        return
    if actor_id is None:
        raise ProductWorkAccessError("读取通告分析须核对当前具名读取人")
    require_disclosure(c, actor(c, record.tenant_id, actor_id), source)


def visible(c: Connection, record: Any, actor_id: UUID | None) -> bool:
    try:
        require(c, record, actor_id)
    except (ValueError, LookupError, PermissionError):
        return False
    return True
