"""The release replay check catches an unpatched workflow change (D212).

Runs a private in-memory Temporal dev server from the inspected local binary; no
network, database or model is used.
"""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
import replay_fixture_workflows as fixture
import workflow_replay_check as check

BINARY = Path(__file__).resolve().parents[2] / ".local/tools/temporal"
pytestmark = pytest.mark.skipif(not BINARY.is_file(), reason="local Temporal binary missing")


async def _waiting_history(directory: Path, running=fixture.Original):
    from concurrent.futures import ThreadPoolExecutor

    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    environment = await WorkflowEnvironment.start_local(dev_server_existing_path=str(BINARY))
    try:
        queue = "replay-fixture-" + str(uuid4())
        with ThreadPoolExecutor(max_workers=2) as executor:
            async with Worker(
                environment.client,
                task_queue=queue,
                workflows=[running],
                activities=[fixture.step],
                activity_executor=executor,
            ):
                handle = await environment.client.start_workflow(
                    running.run, id="replay-fixture-" + str(uuid4()), task_queue=queue
                )
                for _ in range(100):
                    history = await handle.fetch_history()
                    if any(
                        e.HasField("activity_task_completed_event_attributes")
                        for e in history.events
                    ):
                        break
                    await asyncio.sleep(0.1)
                else:
                    raise AssertionError("fixture workflow did not reach its wait")
        # The worker is gone and the workflow is still waiting: the release situation.
        return await check.export(environment.client, directory, check.DEFAULT_QUERY, 10)
    finally:
        await environment.shutdown()


def test_unpatched_change_fails_and_patched_change_passes(tmp_path):
    saved = asyncio.run(_waiting_history(tmp_path / "histories"))
    assert [row["workflow_type"] for row in saved] == [fixture.NAME]
    index = json.loads((tmp_path / "histories" / "index.json").read_text())
    assert (
        index == saved and (tmp_path / "histories" / index[0]["file"]).stat().st_mode & 0o077 == 0
    )

    same = asyncio.run(check.replay(tmp_path / "histories", classes=[fixture.Original]))
    assert same["passed"] and same["histories"] == 1 and same["failures"] == []

    broken = asyncio.run(check.replay(tmp_path / "histories", classes=[fixture.UnpatchedChange]))
    assert not broken["passed"]
    [failure] = broken["failures"]
    assert (
        failure["workflow_type"] == fixture.NAME
        and "Nondeterminism" in failure["message"] + failure["error"]
    )

    patched = asyncio.run(check.replay(tmp_path / "histories", classes=[fixture.PatchedChange]))
    assert patched["passed"] and patched["failures"] == []


def test_unregistered_workflow_type_blocks_release(tmp_path):
    saved = asyncio.run(_waiting_history(tmp_path / "histories"))
    assert saved
    report = asyncio.run(check.replay(tmp_path / "histories", classes=[]))
    # An empty class list falls back to the worker's registered workflows,
    # which do not include the fixture type: the history has no code to resume it.
    assert report["unregistered_types"] == [fixture.NAME] and not report["passed"]


def test_worker_registration_list_is_what_the_check_replays():
    from pdos_next.workflows.worker import registered_workflows

    names = [cls.__temporal_workflow_definition.name for cls in check.workflows()]
    assert names == [cls.__temporal_workflow_definition.name for cls in registered_workflows()]
    # 16 on the W11 branch; M2a's MemoryEpisodeVectors makes 17 after the 11-09 merge;
    # P101 replaced XiaopaiWork with XiaopaiGraphWork on the plugin path: still 17.
    assert len(names) == len(set(names)) == 17


def test_rolling_back_after_the_patched_code_ran_fails_replay(tmp_path):
    # Once new code has recorded a patch marker, the old code cannot resume that
    # history: worker rollback is only safe when this check passes with the old code.
    asyncio.run(_waiting_history(tmp_path / "histories", running=fixture.PatchedChange))
    new = asyncio.run(check.replay(tmp_path / "histories", classes=[fixture.PatchedChange]))
    assert new["passed"]
    old = asyncio.run(check.replay(tmp_path / "histories", classes=[fixture.Original]))
    assert not old["passed"] and "patch marker" in old["failures"][0]["message"]
