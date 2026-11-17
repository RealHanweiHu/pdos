"""业务事件扇出与每日维护 (memory design §7.5, §14.6, §14.9; P88 第 1 项; D508).

Four handlers per business event, each recorded once in the maintenance ledger
under (task, event, event digest):

* ``staleness`` (记忆失效检查): for 改版 events, ``memory_flag_object_update``
  flags every active scope note and personal note whose current version
  references the event's object at an older version. The review owner (the
  author, or the attached object's owner once the author left or when 小Pai
  wrote it; the owner for a personal note) gets a 待复核 item in 我的工作. This
  is a system-rule write in SQL, keyed on the outbox event; no model.
* ``distillation`` (经验沉淀): asks the preset drafting rules
  (``distillation.dispatch``). While the skill is a draft every trigger is held
  with its reason.
* ``scope_recent`` (范围近况): computed when read, so there is no cache to drop.
* ``index`` (增量索引): business events already reach enterprise search through
  its own projection sender; memory keeps no business-object index.

The daily pass hands notes of departed authors to the attached object's owner
and runs the procedural summary. Neither the handlers nor the daily pass read
or copy note text.
"""

import json
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import text

from pdos_next.core.service import digest

from .distillation import REVISION_EVENTS, RULES

FANOUT_EVENTS = frozenset(
    {*REVISION_EVENTS, *(event for rule in RULES.values() for event in rule.events)})
WORKFLOW_PREFIX = "pdos-memory-fanout"
DAILY_PREFIX = "pdos-memory-daily"


def reference(event):
    return {"tenant_id": event.tenant_id, "event_id": event.event_id,
            "event_type": event.event_type, "subject_id": event.subject_id,
            "subject_revision": event.subject_revision}


def workflow_id(event):
    return f"{WORKFLOW_PREFIX}:{UUID(event.tenant_id)}:{UUID(event.event_id)}"


async def start(client, task_queue, event):
    """Called by the shared outbox consumer before it acknowledges the event."""
    if event.event_type not in FANOUT_EVENTS:
        return None
    from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from .fanout_workflow import MemoryEventFanout

    identity = workflow_id(event)
    try:
        await client.start_workflow(
            MemoryEventFanout.run, reference(event), id=identity, task_queue=task_queue,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE)
    except WorkflowAlreadyStartedError:
        pass
    return identity


def _watermark(value):
    return digest(["memory-maintenance/v1", value])


def record(session, tenant_id, task, subject, watermark, outcome, detail):
    return bool(session.scalar(
        text("SELECT public.memory_ledger_record(:t, :task, :subject, :mark, :outcome, "
             "CAST(:detail AS jsonb))"),
        {"t": tenant_id, "task": task, "subject": subject, "mark": watermark,
         "outcome": outcome, "detail": json.dumps(detail, sort_keys=True)}))


def handle(session, value, *, start_distillation=None, catalog=None):
    """One handler for one event; replaying it records nothing new."""
    from .distillation import dispatch

    tenant = UUID(value["tenant_id"])
    handler = value["handler"]
    mark = _watermark([value["event_id"], value["event_type"], value.get("subject_revision")])
    if handler == "staleness":
        if value["event_type"] in REVISION_EVENTS:
            flagged = session.scalar(text("SELECT public.memory_flag_object_update(:t, :e)"),
                                     {"t": tenant, "e": UUID(value["event_id"])})
            outcome, detail = "done", {"flagged": flagged}
        else:
            outcome, detail = "skipped", {"reason": "not_a_revision_event"}
    elif handler == "distillation":
        outcome, detail = dispatch(session, tenant, value, start=start_distillation,
                                   catalog=catalog)
    elif handler == "scope_recent":
        outcome, detail = "skipped", {"reason": "computed_on_read"}
    elif handler == "index":
        outcome, detail = "skipped", {"reason": "enterprise_projection_handles_events"}
    else:
        raise ValueError("Unknown memory fan-out handler")
    added = record(session, tenant, f"fanout.{handler}", value["event_id"], mark, outcome,
                   detail)
    return {"handler": handler, "outcome": outcome, "detail": detail, "new": added}


def handle_event(engine, value, **ports):
    from pdos_next.core.database import tenant_session

    with tenant_session(engine, UUID(value["tenant_id"])) as session:
        return handle(session, value, **ports)


def daily(session, tenant_id, task, *, day=None, now=None):
    from .procedural import summarize

    day = day or date.today().isoformat()
    if task == "departure":
        detail = {"handed_over": session.scalar(
            text("SELECT public.memory_flag_departed_authors(:t)"), {"t": tenant_id})}
    elif task == "procedural":
        detail = {"candidates": summarize(session, tenant_id, as_of=now or datetime.now(UTC))}
    else:
        raise ValueError("Unknown memory daily task")
    added = record(session, tenant_id, f"daily.{task}", str(tenant_id), _watermark(day), "done",
                   detail)
    return {"task": task, "detail": detail, "new": added}


def daily_task(engine, value):
    from pdos_next.core.database import tenant_session

    with tenant_session(engine, UUID(value["tenant_id"])) as session:
        return daily(session, UUID(value["tenant_id"]), value["task"], day=value["day"])


_STARTED = {}


async def start_daily(client, task_queue, tenant_id, *, today=None):
    """Once per tenant and day from the worker's discovery loop."""
    day = (today or date.today()).isoformat()
    if _STARTED.get(str(tenant_id)) == day:
        return None
    from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from .fanout_workflow import MemoryDailyMaintenance

    identity = f"{DAILY_PREFIX}:{UUID(str(tenant_id))}:{day}"
    try:
        await client.start_workflow(
            MemoryDailyMaintenance.run, {"tenant_id": str(tenant_id), "day": day},
            id=identity, task_queue=task_queue,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE)
    except WorkflowAlreadyStartedError:
        pass
    _STARTED[str(tenant_id)] = day
    return identity
