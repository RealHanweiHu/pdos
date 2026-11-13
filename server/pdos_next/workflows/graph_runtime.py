"""Workflow-side driver shared by plugin-executed graphs (P100).

Deterministic: no clock, randomness, environment or I/O. A human answer travels as its
committed reference only; the interrupted node reads the answer itself in an Activity.
"""

import re
from datetime import timedelta
from uuid import UUID

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command
    from temporalio.langgraph import graph

REFERENCE = frozenset({"tenant_id", "category_id", "actor_id", "requester_id", "subject_id"})
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,99}")


def check_reference(reference):
    if (
        not isinstance(reference, dict)
        or set(reference) != REFERENCE
        or any(not isinstance(value, str) for value in reference.values())
    ):
        raise ApplicationError(
            "Graph workflow requires its fixed server scope envelope", non_retryable=True,
        )


class AnswerRefs:
    """Committed answer references: duplicates and any delivery order are normal."""

    def __init__(self):
        self.queue, self.seen = [], set()

    def offer(self, answer_ref):
        try:
            if not isinstance(answer_ref, str):
                return
            canonical = str(UUID(answer_ref))
        except ValueError:
            return
        if canonical not in self.seen:
            self.queue.append(canonical)
            self.seen.add(canonical)


def stop_code(error: ActivityError):
    """The registered code of a node that stopped the run, or None if attempts ran out."""
    cause = error.cause
    code = getattr(cause, "type", None)
    if isinstance(cause, ApplicationError) and cause.non_retryable and isinstance(code, str) \
            and _CODE.fullmatch(code):
        return code
    return None


async def drive(name, payload, context, answers, *, waiting=None, cache=None, carried=None,
                rollover=None):
    """Run a registered graph to its end, resuming each interrupt with one answer ref.

    ``carried`` is the state a previous execution of this workflow handed over when it
    continued as new: the graph resumes after the node that last wrote it. ``rollover``
    receives the current state when the graph asks for such a hand-over.
    """
    app = graph(name, cache=cache).compile(checkpointer=InMemorySaver())
    config = {
        "configurable": {"thread_id": workflow.info().workflow_id},
        "recursion_limit": 200,
    }
    if carried is not None:
        await app.aupdate_state(config, carried["values"], as_node=carried["after"])
        payload = None
    while True:
        result = await app.ainvoke(payload, config, context=dict(context), version="v2")
        if not result.interrupts:
            if waiting:
                waiting(None)
            return result.value
        asked = [item.value for item in result.interrupts]
        if rollover and any(
            isinstance(value, dict) and value.get("type") == "rollover" for value in asked
        ):
            rollover((await app.aget_state(config)).values)
        if waiting:
            waiting(asked)
        await workflow.wait_condition(lambda: bool(answers.queue))
        if waiting:
            waiting(None)
        payload = Command(resume={"answer_ref": answers.queue.pop(0)})


RECONCILE = {
    "start_to_close_timeout": timedelta(minutes=1),
    # Technical cleanup must survive a database/service outage.
    # It never repeats inference or an external/business action.
    "retry_policy": RetryPolicy(maximum_interval=timedelta(minutes=1)),
}


async def close_run(reference, error: ActivityError, *, grace_seconds=300):
    """Record a failed graph without repeating inference or a business action."""
    code = stop_code(error)
    if code is None:
        # Attempts or time ran out with the outcome unknown: the existing technical
        # reconciliation decides from the run's own ledgers.
        return await workflow.execute_activity(
            "reconcile_xiaopai_run", {**reference, "activity_exhausted": True}, **RECONCILE,
        )
    closed = await workflow.execute_activity(
        "close_xiaopai_graph_run", {**reference, "error_code": code}, **RECONCILE,
    )
    if closed["status"] != "needs_reconciliation":
        return closed
    # Grace before the automatic receipt check; the value was recorded by open.
    await workflow.sleep(timedelta(seconds=grace_seconds))
    return await workflow.execute_activity("reconcile_xiaopai_run", reference, **RECONCILE)
