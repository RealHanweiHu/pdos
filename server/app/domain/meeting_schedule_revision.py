"""Reviewed recurrence timing revisions preserve every materialised occurrence."""

from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine

from app.auth.repository import AuthContext
from app.contracts.common_objects import Digest, Text
from app.db.schema import tables
from app.domain.meeting_recurrence_commands import (
    Timing,
    Window,
    authorize,
    existing_in_window,
    existing_item,
    receipt,
    replay,
)
from app.domain.meeting_recurrence_roster import record
from app.domain.meeting_scheduling import (
    RecurrenceValidationError,
    _recurrence,
    occurrence_times,
    occurrences_between,
)
from app.domain.meetings import MeetingStateError
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope

ACTION = "meeting_recurrence.schedule_changed"


class Revision(Timing, Window):
    request_id: UUID
    expected_digest: Digest
    reason: Text


class Save(Revision):
    preview_digest: Digest


def review(
    c: Connection, ctx: AuthContext, project: UUID, id: UUID, command: Revision
) -> dict[str, Any]:
    row = record(c, ctx, project, id)
    if command.expected_digest != digest(_plain(row)):
        raise MeetingStateError("周期配置已变化，请重新读取后编辑")
    old = _recurrence(row)
    timing = {key: getattr(command, key) for key in Timing.model_fields}
    new = replace(old, **timing)
    window = Window(since=command.since, through=command.through)
    existing = existing_in_window(c, ctx, project, old, window)
    existing.update(existing_in_window(c, ctx, project, new, window))
    items = []
    old_errors = []
    for rec in (old, new):
        proposed = []
        for day in occurrences_between(rec, start=window.since, end=window.through):
            if day in existing:
                proposed.append(existing_item(existing[day]))
            else:
                try:
                    start, end = occurrence_times(rec, day)
                except RecurrenceValidationError as error:
                    if rec is new:
                        raise
                    old_errors.append({"date": str(day), "message": str(error)})
                    continue
                proposed.append(
                    {
                        "date": str(day),
                        "start_at": start.isoformat(),
                        "end_at": end.isoformat(),
                        "meeting_id": None,
                        "status": None,
                    }
                )
        items.append(proposed)
    result = {
        "before": _plain(asdict(old)),
        "after": _plain(asdict(new)),
        "old_items": items[0],
        "old_errors": old_errors,
        "new_items": items[1],
        "retained_items": [
            existing_item(r)
            for r in sorted(existing.values(), key=lambda r: (r["scheduled_start_at"], r["id"]))
        ],
        "since": str(command.since),
        "through": str(command.through),
    }
    return {**result, "preview_digest": digest(result)}


def preview(
    engine: Engine, ctx: AuthContext, project: UUID, id: UUID, command: Revision
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        authorize(c, ctx, project, write=True)
        return review(c, ctx, project, id, command)


def save(
    engine: Engine, ctx: AuthContext, project: UUID, id: UUID, command: Save
) -> dict[str, Any]:
    signature = digest({"recurrence_id": str(id), **command.model_dump(mode="json")})
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
            raise MeetingStateError("项目不存在")
        authorize(c, ctx, project, write=True)
        prior = replay(c, ctx, project, ACTION, command.request_id, signature)
        if prior:
            return prior
        result = review(c, ctx, project, id, command)
        if result["preview_digest"] != command.preview_digest:
            raise MeetingStateError("预览中的场次已经变化，请重新核对")
        before = _plain(record(c, ctx, project, id))
        t = tables.meeting_recurrences
        c.execute(
            t.update()
            .where(t.c.tenant_id == ctx.tenant.id, t.c.project_id == project, t.c.id == id)
            .values(
                **{key: getattr(command, key) for key in Timing.model_fields},
                updated_at=datetime.now(UTC),
            )
        )
        after = record(c, ctx, project, id)
        return receipt(
            c,
            ctx,
            project,
            _recurrence(after),
            ACTION,
            command.request_id,
            signature,
            command.reason,
            before,
            {"recurrence_id": str(id), "record": _plain(after), "review": result},
        )
