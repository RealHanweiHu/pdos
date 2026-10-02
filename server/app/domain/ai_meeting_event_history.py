"""Scoped, immutable trigger receipts alongside current meeting run status."""

from typing import Any
from uuid import UUID

from sqlalchemy import Engine, select, tuple_

from app.ai.meeting_event_queue import REASONS
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.meetings import MeetingService, MeetingStateError


class AiMeetingEventHistory:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(
        self,
        tenant_id: UUID,
        project_id: UUID,
        meeting_id: UUID,
        actor_id: UUID,
        before: UUID | None = None,
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            KnowledgeCorrectionService._authorize(
                c, tenant_id, actor_id, project_id, Action.MEETING_VIEW
            )
            MeetingService._get(
                c, tenant_id=tenant_id, project_id=project_id, meeting_id=meeting_id
            )
            t, e, r = tables.ai_meeting_event_receipts, tables.events, tables.agent_runs
            scope = (
                t.c.tenant_id == tenant_id,
                t.c.project_id == project_id,
                t.c.meeting_id == meeting_id,
            )
            query = (
                select(
                    t.c.id,
                    t.c.created_at,
                    t.c.operation_key,
                    t.c.status,
                    t.c.reason,
                    t.c.transcript_id,
                    e.c.timestamp.label("event_at"),
                    e.c.payload["action"].as_string().label("event_action"),
                    r.c.id.label("run_id"),
                    r.c.status.label("run_status"),
                    r.c.error_code.label("run_error"),
                )
                .select_from(t)
                .outerjoin(
                    e,
                    (e.c.tenant_id == t.c.tenant_id)
                    & (e.c.project_id == t.c.project_id)
                    & (e.c.entity_id == t.c.meeting_id)
                    & (e.c.id == t.c.event_row_id),
                )
                .outerjoin(
                    r,
                    (r.c.tenant_id == t.c.tenant_id)
                    & (r.c.project_id == t.c.project_id)
                    & (r.c.id == t.c.run_id),
                )
                .where(*scope)
            )
            if before is not None:
                cursor = c.execute(
                    select(t.c.created_at, t.c.id).where(*scope, t.c.id == before)
                ).first()
                if cursor is None:
                    raise MeetingStateError("历史位置已不可用，请刷新会后触发记录")
                query = query.where(tuple_(t.c.created_at, t.c.id) < tuple_(cursor[0], cursor[1]))
            rows = (
                c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21))
                .mappings()
                .all()
            )
            return {
                "items": [
                    {
                        "id": str(row["id"]),
                        "created_at": row["created_at"].isoformat(),
                        "event_at": row["event_at"].isoformat() if row["event_at"] else None,
                        "event_action": row["event_action"],
                        "operation_key": row["operation_key"],
                        "status": row["status"],
                        "reason": REASONS.get(
                            row["reason"], "触发条件尚待核对，请查看当前自动模式和项目起草范围。"
                        ),
                        "transcript_id": str(row["transcript_id"])
                        if row["transcript_id"]
                        else None,
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
                "next_before": str(rows[19]["id"]) if len(rows) > 20 else None,
            }
