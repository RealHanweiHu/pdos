"""Stage 1 pilot of the Temporal LangGraph plugin (P100): the no-model personal summary.

Started only by tests and evaluation tools. Production summary runs stay on
``XiaopaiWork`` until the switch in the decision record is implemented and opened.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from pdos_next.workflows.graph_runtime import AnswerRefs, check_reference, close_run, drive

GRAPH = "personal-summary"


@workflow.defn
class PersonalSummaryGraphWork:
    def __init__(self):
        self.answers = AnswerRefs()
        self.waiting = None

    @workflow.signal
    def resume(self, answer_ref: str):
        # Same contract as XiaopaiWork.resume, so the Outbox needs no second transport.
        self.answers.offer(answer_ref)

    @workflow.query
    def pending_input(self):
        return self.waiting

    def _waiting(self, value):
        self.waiting = value

    @workflow.run
    async def run(self, reference: dict):
        check_reference(reference)
        # A reference this workflow may not run is refused before the run is touched:
        # the open Activity's stop fails the workflow and leaves the run as it was.
        opened = await workflow.execute_activity(
            "open_xiaopai_graph_run",
            {**reference, "kind": "personal_summary"},
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_interval=timedelta(minutes=1)),
        )
        if opened["status"] != "running":
            return opened
        try:
            state = await drive(
                GRAPH,
                {"run_id": opened["run_id"], "cancel_epoch": opened["cancel_epoch"]},
                {**reference, "writer_id": opened["writer_id"]},
                self.answers,
                waiting=self._waiting,
            )
        except ActivityError as error:
            return await close_run(reference, error)
        return {"run_id": reference["subject_id"], "status": state["output"]["status"]}
