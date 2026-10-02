"""Read-only trigger history; current source access is checked on every read."""

from uuid import UUID

from fastapi import APIRouter, Response

from app.api.ai_issue_event_runs import Context, Database, EventId, _invoke
from app.domain.ai_issue_event_history import IssueEventHistory

router = APIRouter(prefix="/api/projects/{project_id}/ai-issue-event-history", tags=["work-items"])


@router.get("")
def history(
    project_id: UUID,
    event_row_id: EventId,
    response: Response,
    context: Context,
    engine: Database,
    before_id: UUID | None = None,
) -> dict[str, object]:
    return _invoke(
        response,
        lambda: IssueEventHistory(engine).get(context, project_id, event_row_id, before_id),
    )
