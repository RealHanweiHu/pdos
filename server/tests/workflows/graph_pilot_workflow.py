"""Test-only workflow for the shared graph driver. Kept apart from the fixtures: a
workflow module is imported again inside the Temporal sandbox, where database and
domain modules must not be loaded."""

from temporalio import workflow
from temporalio.exceptions import ActivityError

from pdos_next.workflows.graph_runtime import AnswerRefs, check_reference, close_run, drive


@workflow.defn
class AskWork:
    def __init__(self):
        self.answers = AnswerRefs()
        self.waiting = None

    @workflow.signal
    def resume(self, answer_ref: str):
        self.answers.offer(answer_ref)

    @workflow.query
    def pending_input(self):
        return self.waiting

    def _waiting(self, value):
        self.waiting = value

    @workflow.run
    async def run(self, reference: dict, slow: bool):
        check_reference(reference)
        try:
            return await drive("ask", {"slow": slow}, reference, self.answers,
                               waiting=self._waiting)
        except ActivityError as error:
            return await close_run(reference, error)
