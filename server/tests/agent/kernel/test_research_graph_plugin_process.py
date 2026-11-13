"""The research child on the plugin path, through the production worker entry (P100).

Runs the existing default API/Worker research case unchanged, with the tenant switch
on: the worker process is the real ``pdos_next.workflows.worker.main``, and the
``restart`` case kills it twice while the isolated research child is working inside
the plugin graph's ``tools`` node.
"""

import os

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent.kernel.models import AgentRun, AgentToolCall
from pdos_next.agent.kernel.temporal_port import SWITCH
from tests.agent.kernel import test_research_runtime_process as original
from tests.agent.kernel.test_worker_process_recovery import temporal_state

pytestmark = pytest.mark.skipif(
    os.environ.get("PDOS_WORKER_PROCESS_CHECK") != "verified-local-synthetic",
    reason="Explicit verified local Temporal/PG process profile required",
)


@pytest.mark.parametrize("confirmation", ["api", "restart"])
def test_research_child_runs_and_survives_worker_kills_on_the_plugin_path(
    setup, monkeypatch, tmp_path, confirmation, capfd
):
    # Read by the API process here and inherited by the worker process it starts.
    monkeypatch.setenv(SWITCH, str(setup.tenant))
    original.test_default_research_worker_retains_child_checkpoint_and_actual_snapshot(
        setup, monkeypatch, tmp_path, confirmation,
    )
    with Session(setup.admin) as session:
        # The fixtures add ledger runs of their own; this is the one the API accepted.
        run = session.scalar(select(AgentRun).where(
            AgentRun.tenant_id == setup.tenant,
            AgentRun.goal == "Synthetic default host public research",
        ))
        assert run.state == "completed"
        assert run.versions["execution_engine"] == "temporal-langgraph/v1"
        calls = session.scalars(
            select(AgentToolCall).where(AgentToolCall.run_id == run.id)
        ).all()
        identity = run.id
    isolations = {call.execution_binding.get("isolation") for call in calls}
    assert {"main", "research"} <= isolations
    assert all(call.state == "completed" for call in calls)
    assert temporal_state(identity, setup)[1] == "COMPLETED"
    worker_log = (tmp_path / "research-worker.log").read_text()
    # Each outbound research request left the worker exactly once, restarts included.
    assert worker_log.count('"transport": "search"') == 1
    assert worker_log.count('"transport": "web"') == 1
