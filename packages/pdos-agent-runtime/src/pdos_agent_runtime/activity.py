"""Execute a host-registered capability using persistent LangGraph checkpoints."""

import re
from threading import Event, Thread

from langgraph.checkpoint.postgres import PostgresSaver
from temporalio import activity
from temporalio.exceptions import ApplicationError

from pdos_agent_runtime.graph import execute_graph


class AgentActivities:
    def __init__(self, store, handlers: dict, *, checkpoint_url: str):
        self.store, self.handlers, self.checkpoint_url = store, handlers, checkpoint_url

    @activity.defn(name="pdos_execute_agent_graph")
    def execute(self, ref: dict) -> dict:
        try:
            row = self.store.read(ref)
            handler = self.handlers.get(row["handler"])
            if handler is None:
                raise ValueError("Unregistered capability")
            if row["state"] in {"completed", "failed"}:
                return {"job_id": ref["job_id"], "state": row["state"]}
            claimed = self.store.claim(ref)
            stopped = Event()
            activity.info()  # The Activity context must be copied to the heartbeat.
            from contextvars import copy_context

            heartbeat_context = copy_context()

            def heartbeat():
                while not stopped.wait(10):
                    activity.heartbeat(ref["job_id"])

            thread = Thread(
                target=lambda: heartbeat_context.run(heartbeat), daemon=True
            )
            thread.start()
            try:
                with PostgresSaver.from_conn_string(self.checkpoint_url) as saver:
                    config = {
                        "configurable": {"thread_id": f"{ref['realm']}:{ref['job_id']}"}
                    }
                    # A crash inside an uncheckpointed business action is uncertain.
                    # Inspect durable node results before allowing a recovery attempt.
                    if not claimed:
                        saved = saver.get_tuple(config)
                        if (
                            not saved
                            or "result" not in saved.checkpoint["channel_values"]
                        ):
                            self.store.require_reconciliation(ref)
                            return {
                                "job_id": ref["job_id"],
                                "state": "needs_reconciliation",
                            }
                    result = execute_graph(
                        lambda payload: handler(
                            payload, lambda event: self.store.emit(ref, event)
                        ),
                        row["payload"],
                        thread_id=f"{ref['realm']}:{ref['job_id']}",
                        checkpointer=saver,
                    )
                    self.store.finish(ref, result)
                return {"job_id": ref["job_id"], "state": "completed"}
            finally:
                stopped.set()
                thread.join(timeout=1)
        except Exception as error:
            code = getattr(error, "code", "AGENT_EXECUTION_FAILED")
            if not isinstance(code, str) or not re.fullmatch(
                r"[A-Z][A-Z0-9_]{0,99}", code
            ):
                code = "AGENT_EXECUTION_FAILED"
            # Exceptions never cause an LLM fallback or an unreceipted second action.
            self.store.fail(ref, code)
            raise ApplicationError(
                "Agent execution requires its original receipt",
                type=code,
                non_retryable=True,
            ) from None
