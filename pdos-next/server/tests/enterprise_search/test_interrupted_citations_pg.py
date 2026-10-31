"""Completed metadata survives interruption; old execution and business proofs do not."""

import json
from dataclasses import replace
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.deterministic_proofs import _historical_read, archived_citation_read
from pdos_next.agent_kernel.execution import scope_for_run
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall
from pdos_next.agent_kernel.persistence import cancel_run
from pdos_next.agent_kernel.work_state import record_finish
from pdos_next.database import tenant_session
from pdos_next.enterprise_search import assistant_ledger as ledger
from pdos_next.enterprise_search.assistant_sources import human_snapshot
from pdos_next.errors import DomainError
from pdos_next.models import Artifact
from tests.enterprise_search.test_assistant_pg import execute, fixture
from tests.enterprise_search.test_citation_inheritance_pg import FollowupClient, parent


class StopAfterMetadata(FollowupClient):
    def turn(self, route, **kwargs):
        values = [json.loads(row["content"]) for row in kwargs["messages"] if row["role"] == "tool"]
        if values and "items" in values[-1]:
            self.delivered = values[-1]["items"][0]
            raise ConnectionError("synthetic interruption after metadata")
        return super().turn(route, **kwargs)


@pytest.mark.parametrize("terminal", ["failed", "cancelled"])
def test_metadata_outside_preview_survives_interruption_without_reviving_old_run(setup, terminal):
    _ids, owner, root, _adapter, _output = parent(setup, count=5)
    with owner.store.transaction(root) as (session, run):
        sid = run.session_id
        root_cid, root_item = list(ledger.search_issued(session, root).items())[3]
    client = StopAfterMetadata(selector={"reference_id": root_cid})
    middle_owner, middle, middle_host, _adapter = fixture(
        setup, client, session_id=sid, continued_from_id=root.run_id
    )
    frozen = middle_owner.project_context(middle, "核对第四条来源")["work_state"]
    assert root_cid not in {ref["origin_citation_id"] for ref in frozen["citations"]}

    def stop():
        if terminal == "cancelled":
            with tenant_session(
                setup.engine, setup.tenant, actor_id=setup.human, requester_id=setup.human
            ) as session:
                cancel_run(session, replace(setup.ctx, category_id=None), middle.run_id)
        else:
            with middle_owner.store.transaction(middle, lock=True) as (session, run):
                run.state, run.error_code = "failed", "INVALID_PAYLOAD"
                record_finish(session, run, {})

    with pytest.raises(DomainError):
        execute(middle_owner, middle, middle_host)
    # Like the Activity failure path, settle the failed model reservation before
    # recording its terminal Run; the completed metadata read is already sealed.
    stop()
    assert client.delivered["origin_citation_id"] == root_cid
    alias = client.delivered["citation_id"]
    detail = setup.client.get(f"/v1/personal/agent-runs/{middle.run_id}", headers=setup.headers)
    assert detail.status_code == 200 and detail.json()["status"] == terminal, detail.text
    events = setup.client.get(
        f"/v1/personal/agent-runs/{middle.run_id}/events", headers=setup.headers
    )
    assert events.status_code == 200, events.text
    with human_snapshot(setup.engine, middle) as session:
        run = session.get(AgentRun, middle.run_id)
        assert run.state == terminal
        canonical = scope_for_run(run)
        call = session.scalar(
            select(AgentToolCall).where(
                AgentToolCall.run_id == run.id, AgentToolCall.tool == "assistant.citations.read"
            )
        )
        assert call.state == "completed"
        archived_citation_read(session, canonical, call.id, deny=ledger.deny)
        with pytest.raises(DomainError):
            _historical_read(session, canonical, call.id, "ordinary/v1", deny=ledger.deny)
        with pytest.raises(DomainError):
            archived_citation_read(
                session, replace(canonical, requester_id=setup.peer), call.id, deny=ledger.deny
            )
    child_client = FollowupClient(selector={"reference_id": alias})
    child_owner, child, host, adapter = fixture(
        setup, child_client, session_id=sid, continued_from_id=middle.run_id
    )
    output = execute(child_owner, child, host)
    assert output["status"] == "completed", output
    answer = output["result"]["assistant"]
    assert (
        answer["lookup"] == "cited" and answer["sources"][0]["source_id"] == root_item["source_id"]
    )
    assert answer["citation_ids"][0] not in {alias, root_cid}
    with child_owner.store.transaction(child) as (session, _run):
        assert not session.scalar(
            select(AgentToolCall.id).where(
                AgentToolCall.run_id == child.run_id, AgentToolCall.tool == "assistant.search"
            )
        )
        selected = ledger.issued(session, child)[answer["citation_ids"][0]]
        assert selected["origin_run_id"] == str(root.run_id)
    assert child_client.calls == 5
    with Session(setup.admin) as session, session.begin():
        session.get(Artifact, UUID(root_item["source_id"])).status = "withdrawn"
    with pytest.raises(DomainError):
        adapter.guard(child)


def test_archived_reader_never_accepts_extraction_or_a_different_scope(setup):
    _ids, owner, scope, _adapter, _output = parent(setup)
    with owner.store.transaction(scope) as (session, _run):
        call = session.scalar(
            select(AgentToolCall).where(
                AgentToolCall.run_id == scope.run_id, AgentToolCall.tool == "assistant.extract"
            )
        )
        with pytest.raises(DomainError) as error:
            archived_citation_read(session, scope, call.id, deny=ledger.deny)
        assert error.value.detail["reason_key"] == "assistant_archive_tool_invalid"
