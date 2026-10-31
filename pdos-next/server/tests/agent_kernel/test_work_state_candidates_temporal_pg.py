"""Registered Xiaopai graph→verification candidate→Human receipt→readonly work state."""

# ruff: noqa: F401, F811 -- native professional fixtures keep their real dependency tree

import asyncio
import os

import pytest
from build_operational_facts.fixtures import configuration, definition, operational_work, project
from build_start.test_transactions import ready_work
from verification_handoff.fixtures import artifact, handoff_work, known_configuration

from pdos_next.agent_kernel.models import AgentRun
from pdos_next.database import tenant_session
from tests.agent_kernel.test_work_state_candidates_pg import candidate
from tests.enterprise_search.test_verification_action_temporal_pg import (
    continuation,
    discussion,
    materials,
    prepared,
)
from tests.enterprise_search.verification_action_harness import VerificationClient, actual_runtime

pytestmark = pytest.mark.skipif(
    not os.environ.get("PDOS_TEMPORAL_ADDRESS")
    or not os.environ.get("PDOS_CHECKPOINT_DATABASE_URL"),
    reason="Explicit guarded PG, verified local Temporal and checkpoint runtime required",
)


def test_actual_main_graph_verification_candidate_is_carried_without_a_second_model(
    handoff_work, monkeypatch,
):
    person, selection, _discussion, execution = materials(handoff_work)
    provider = VerificationClient(execution, handoff_work.scope.purpose)

    async def actual():
        async with actual_runtime(person, provider, monkeypatch) as runtime:
            parent, answer = await discussion(runtime, selection)
            identity, pending = await continuation(runtime, parent, answer, selection)
            with tenant_session(person.engine, person.tenant, actor_id=person.human,
                                category_id=person.category) as session:
                session_id = session.get(AgentRun, identity).session_id
            path = f"/v1/categories/{person.category}/agent-sessions/{session_id}/work-state"
            response = await runtime.http.get(path, headers=person.headers)
            assert response.status_code == 200, response.text
            before = response.json()
            row = candidate(before, pending["event_id"])
            assert row["kind"] == "verification_preparation" and row["state"] == "pending"
            calls = provider.calls
            saved = await prepared(runtime, identity, pending, lose=True)
            response = await runtime.http.get(path, headers=person.headers)
            assert response.status_code == 200, response.text
            after = response.json()
            current = candidate(after, pending["event_id"])
            assert current == {**row, "state": "adopted", "receipt_id": saved["receipt"]["id"]}
            assert after["revision"] == before["revision"] and provider.calls == calls
            assert runtime.transport.lost == 1
            assert all(key not in current for key in ("payload", "command", "source_proof"))

    asyncio.run(actual())
