"""One live rule projection for directory and project views, including personal scope."""

from dataclasses import replace

from sqlalchemy import select

from pdos_next.database import tenant_session

from .models import GovernanceEvent
from .service import view


def summary(s, ctx, project):
    present = s.scalar(
        select(GovernanceEvent.id)
        .where(GovernanceEvent.tenant_id == ctx.tenant_id, GovernanceEvent.project_id == project.id)
        .limit(1)
    )
    if not present:
        return {
            "current_stage": None,
            "stages": [],
            "health": {"state": "unknown", "label": "待核对", "reason": "尚未采用阶段模板"},
            "gate_state": "UNKNOWN",
            "next_gate_name": None,
            "timeline": None,
            "completed": False,
        }
    if ctx.category_id is None:
        scoped = replace(ctx, category_id=project.category_id)
        with tenant_session(
            s.get_bind(),
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=project.category_id,
            read_snapshot=True,
        ) as reading:
            data = view(reading, scoped, project.product_id, project.id)
    else:
        data = view(s, ctx, project.product_id, project.id)
    return {
        key: data[key] for key in ("current_stage", "stages", "health", "timeline", "completed")
    } | {
        "gate_state": data["gate"]["state"],
        "next_gate_name": data["current_stage"]["name"] + "出口" if data["current_stage"] else None,
    }
