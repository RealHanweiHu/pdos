"""Project source history with current actor-private run receipts, never raw payloads."""

from typing import Any
from uuid import UUID

from sqlalchemy import Engine, literal, or_, select, tuple_

from app.ai.issue_event_proposal import OPERATION, IssueEventProposalError
from app.ai.issue_event_queue import REASONS
from app.ai.issue_event_runs import _access
from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.ai_issue_event_sources import read_event_source


class IssueEventHistory:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(
        self, context: AuthContext, project: UUID, event_id: int, before_id: UUID | None = None
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            tenant, actor = context.tenant.id, context.user.id
            _access(c, tenant, actor, project)
            source = read_event_source(c, tenant, project, event_id)
            t, e, r = tables.ai_issue_event_receipts, tables.events, tables.agent_runs
            query = (
                select(
                    t.c.id,
                    t.c.created_at,
                    t.c.status,
                    t.c.reason,
                    e.c.timestamp.label("event_at"),
                    e.c.event_type,
                    r.c.id.label("run_id"),
                    r.c.status.label("run_status"),
                    r.c.error_code.label("run_error"),
                )
                .join(
                    e,
                    (e.c.tenant_id == t.c.tenant_id)
                    & (e.c.project_id == t.c.project_id)
                    & (e.c.id == t.c.event_row_id),
                )
                .outerjoin(
                    r,
                    (r.c.tenant_id == t.c.tenant_id)
                    & (r.c.project_id == t.c.project_id)
                    & (r.c.id == t.c.run_id),
                )
                .where(
                    t.c.tenant_id == tenant,
                    t.c.project_id == project,
                    t.c.operation_key == OPERATION,
                    t.c.event_row_id == event_id,
                    or_(t.c.run_id.is_(None), r.c.requested_by_user_id == actor),
                )
            )
            if before_id is not None:
                cursor = c.execute(query.where(t.c.id == before_id)).mappings().one_or_none()
                if cursor is None:
                    raise IssueEventProposalError("history_cursor_invalid", "请从原来源继续翻页")
                query = query.where(
                    tuple_(t.c.created_at, t.c.id)
                    < tuple_(literal(cursor["created_at"]), literal(before_id))
                )
            rows = list(
                c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21)).mappings()
            )
            return {
                "items": [
                    {
                        "id": str(row["id"]),
                        "created_at": row["created_at"].isoformat(),
                        "event_at": row["event_at"].isoformat(),
                        "event_type": row["event_type"],
                        "status": row["status"],
                        "reason": REASONS.get(row["reason"], "触发依据待核对"),
                        "source_href": source.get("source_href"),
                        "run": {
                            "id": str(row["run_id"]),
                            "status": row["run_status"],
                            "error": row["run_error"],
                        }
                        if row["run_id"]
                        else None,
                    }
                    for row in rows[:20]
                ],
                "next_before_id": str(rows[19]["id"]) if len(rows) > 20 else None,
            }
