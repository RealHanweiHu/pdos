"""Three versions of one waiting workflow for the replay check test (D212).

``Original`` is what is running. ``UnpatchedChange`` inserts a step in place, which
cannot replay an existing history. ``PatchedChange`` makes the same change behind
``workflow.patched``, so old histories keep the old path and new runs take the new one.
"""

from datetime import timedelta

from temporalio import activity, workflow

NAME = "ReleaseReplayFixture"


@activity.defn(name="replay_fixture_step")
def step(value: str) -> str:
    return value


async def _first_step():
    return await workflow.execute_activity(
        "replay_fixture_step", "first", start_to_close_timeout=timedelta(seconds=10)
    )


@workflow.defn(name=NAME)
class Original:
    def __init__(self):
        self.answered = False

    @workflow.signal
    def answer(self):
        self.answered = True

    @workflow.run
    async def run(self) -> str:
        await _first_step()
        await workflow.wait_condition(lambda: self.answered)
        return "done"


@workflow.defn(name=NAME)
class UnpatchedChange(Original):
    @workflow.run
    async def run(self) -> str:
        await workflow.sleep(timedelta(seconds=1))
        await _first_step()
        await workflow.wait_condition(lambda: self.answered)
        return "done"


@workflow.defn(name=NAME)
class PatchedChange(Original):
    @workflow.run
    async def run(self) -> str:
        if workflow.patched("replay-fixture-sleep-v1"):
            await workflow.sleep(timedelta(seconds=1))
        await _first_step()
        await workflow.wait_condition(lambda: self.answered)
        return "done"
