"""The one durable 小Pai workflow: the registered graph runs one Activity per node.

Temporal owns node execution, waiting, cancellation and recovery (P100). Questions and
confirmations resume the same graph by committed answer reference.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from pdos_next.workflows.graph_runtime import AnswerRefs, check_reference, close_run, drive

GRAPHS = {"kernel": "xiaopai", "personal_summary": "personal-summary"}
OPEN = {
    "start_to_close_timeout": timedelta(minutes=1),
    "retry_policy": RetryPolicy(maximum_interval=timedelta(minutes=1)),
}


@workflow.defn
class XiaopaiGraphWork:
    def __init__(self):
        self.answers = AnswerRefs()
        self.waiting = None

    @workflow.signal
    def resume(self, answer_ref: str):
        # A committed answer reference, never answer text or authorization.
        self.answers.offer(answer_ref)

    @workflow.query
    def pending_input(self):
        return self.waiting

    def _waiting(self, value):
        self.waiting = value

    def _rollover(self, reference, opened):
        def hand_over(values):
            workflow.continue_as_new(args=[reference, {
                "opened": opened,
                "values": {**values, "rolled_at": values.get("turns", 0)},
                "answers": list(self.answers.queue),
                "seen": sorted(self.answers.seen),
            }])

        return hand_over

    @workflow.run
    async def run(self, reference: dict, carried: dict | None = None):
        check_reference(reference)
        if carried is not None:
            opened = carried["opened"]
            self.answers.queue = list(carried["answers"])
            self.answers.seen = set(carried["seen"])
        else:
            # A reference this workflow may not run fails here and leaves the run as
            # it was; only a failure inside the graph closes the run.
            while True:
                opened = await workflow.execute_activity(
                    "open_xiaopai_graph_run", {**reference, "kind": "any"}, **OPEN,
                )
                if opened["status"] != "waiting_input":
                    break
                # The worker has no model configuration: wait for the person to retry.
                await workflow.wait_condition(lambda: bool(self.answers.queue))
                self.answers.queue.pop(0)
            if opened["status"] != "running":
                return opened
        try:
            state = await drive(
                GRAPHS[opened["kind"]],
                {key: opened[key] for key in ("run_id", "cancel_epoch", "goal") if key in opened},
                {**reference, "writer_id": opened["writer_id"]},
                self.answers,
                waiting=self._waiting,
                carried=None if carried is None else {
                    "values": carried["values"], "after": "tools",
                },
                rollover=self._rollover(reference, opened),
            )
        except ActivityError as error:
            return await close_run(
                reference, error, grace_seconds=opened["reconcile_after_seconds"],
            )
        return {"run_id": reference["subject_id"], "status": state["output"]["status"]}
