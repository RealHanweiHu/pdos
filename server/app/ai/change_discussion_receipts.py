"""Read linked discussion and follow-up status for both engineering and private conversations."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from app.ai.capability_contract import resolve_capability
from app.ai.discussion_sources import require_disclosure
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain


def linked(c: Connection, row: Any, actor: UUID) -> dict[str, Any]:
    from app.ai import change_notice_preparation as notices
    from app.ai.change_work_package_runs import receipt
    from app.ai.discussion_followup import require_current
    from app.ai.discussion_lineage import cancellation

    b, r, s = tables.debate_run_bindings, tables.agent_runs, tables.debate_sessions
    bound = (
        c.execute(
            select(b).where(b.c.tenant_id == row["tenant_id"], b.c.origin_run_id == row["id"])
        )
        .mappings()
        .one_or_none()
    )
    if bound is None:
        return {"discussion_runtime": None, "discussion_followup": None}
    require_disclosure(c, row["tenant_id"], actor, bound)
    child = (
        c.execute(
            select(
                r.c.id,
                r.c.status,
                r.c.error_code,
                r.c.run_context,
                s.c.status.label("session_status"),
                s.c.stop_reason,
            )
            .join(s, (s.c.tenant_id == r.c.tenant_id) & (s.c.id == bound["session_id"]))
            .where(r.c.tenant_id == row["tenant_id"], r.c.id == bound["run_id"])
        )
        .mappings()
        .one()
    )
    followup = (
        c.execute(
            select(r)
            .join(
                tables.change_discussion_inputs,
                (tables.change_discussion_inputs.c.tenant_id == r.c.tenant_id)
                & (tables.change_discussion_inputs.c.run_id == r.c.id),
            )
            .where(
                r.c.tenant_id == row["tenant_id"],
                r.c.project_id == row["project_id"],
                tables.change_discussion_inputs.c.origin_run_id == row["id"],
            )
        )
        .mappings()
        .one_or_none()
    )
    result = None
    if followup is not None:
        current = True
        try:
            require_current(c, row["tenant_id"], followup["run_context"]["impact_source"])
        except ProductWorkError:
            current = False
        result = {
            **receipt(followup),
            "discussion_current": current,
            "requested_by_me": followup["requested_by_user_id"] == actor,
        }
    return _plain(
        {
            "discussion_runtime": {
                "run_id": child["id"],
                "status": child["status"],
                "error_code": child["error_code"],
                "session_status": child["session_status"],
                "stop_reason": child["stop_reason"],
                "recovery_requested": child["run_context"].get(
                    "discussion_recovery_requested", False
                ),
                "related_request_cancelled": cancellation(c, row["tenant_id"], child["id"]),
            },
            "discussion_followup": result,
            "followup_available": (
                not notices.is_notice(row["run_context"]["impact_source"])
                or notices.discussion_available()
            )
            and all(
                resolve_capability(key).rollout.value == "live"
                for key in (
                    "engineering_intelligence.change_work_package",
                    "engineering_intelligence.discussion_followup",
                )
            ),
        }
    )
