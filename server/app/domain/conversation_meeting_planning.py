"""Bind a conversation request to an explicitly selected, immutable meeting brief."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, RowMapping

from app.ai.budget_ledger import BudgetLedgerError
from app.ai.meeting_planning_context import bound_source, fixed_context
from app.ai.meeting_planning_runs import brief
from app.auth.repository import AuthContext
from app.domain.meeting_planning import authorize_sources
from app.domain.meetings import MeetingStateError


def label(row: RowMapping | dict[str, Any]) -> str:
    return (
        f"按已核对的会议要求起草：《{row['source_snapshot']['title']}》（版本 {row['version']}）。"
    )


def source(
    c: Connection,
    ctx: AuthContext,
    project: UUID,
    identity: UUID,
    expected_digest: str,
    *,
    current: bool = True,
) -> RowMapping:
    authorize_sources(c, ctx, project)
    row = brief(c, ctx, project, identity)
    if row["source_digest"] != expected_digest:
        raise MeetingStateError("所选起草版本与消息不一致，请重新核对")
    if current:
        try:
            bound_source(c, ctx.tenant.id, project, ctx.user.id, fixed_context(row))
        except BudgetLedgerError as error:
            raise MeetingStateError(
                "起草资料、候选人员或当前业务依据已变化，请修订并重新核对"
            ) from error
    return row
