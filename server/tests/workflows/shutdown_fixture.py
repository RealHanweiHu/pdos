"""One workflow and three Activities for the worker shutdown and metrics tests.

Kept free of PDOS imports so the workflow sandbox loads it quickly.
"""

import threading
import time
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

STARTED = threading.Event()
RELEASE = threading.Event()


@activity.defn(name="shutdown_fixture_hold")
def hold(seconds: float) -> str:
    """Blocks inside one C call until released: cancellation cannot reach it."""
    STARTED.set()
    RELEASE.wait(seconds)
    return "released" if RELEASE.is_set() else "timed out"


@activity.defn(name="shutdown_fixture_cooperative")
def cooperative(seconds: float) -> str:
    """Returns to Python often, so a cancellation raised in its thread arrives."""
    STARTED.set()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        time.sleep(0.05)
    return "done"


@activity.defn(name="shutdown_fixture_fail")
def fail(seconds: float) -> str:
    raise ApplicationError("fixture failure", non_retryable=True)


ACTIVITIES = [hold, cooperative, fail]


@workflow.defn(name="ShutdownFixture")
class RunOne:
    @workflow.run
    async def run(self, name: str, seconds: float) -> str:
        return await workflow.execute_activity(
            name,
            seconds,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
