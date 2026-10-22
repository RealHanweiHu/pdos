"""A saved child restores authority from actual read calls, never checkpoint text alone."""

from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.models import AgentToolCall
from pdos_next.agent_kernel.research_checkpoint import restore_reads
from pdos_next.agent_kernel.research_read_ledger import restore_page
from pdos_next.errors import DomainError
from pdos_next.research.service import ResearchChild
from pdos_next.research.tools import ReadInput
from pdos_next.research.types import ResearchTask
from tests.agent_kernel.research.test_research import service
from tests.agent_kernel.test_snapshot_candidates_pg import fixture


@pytest.mark.parametrize("change", ["none", "missing", "forged_call", "changed_result"])
def test_saved_read_is_revalidated_without_new_network_or_call(setup, tmp_path, change):
    f = fixture(setup, tmp_path, completed=False)
    with f.store.transaction(f.scope) as (session, _):
        call = session.scalar(select(AgentToolCall).where(
            AgentToolCall.run_id == f.scope.run_id, AgentToolCall.tool == "research.read",
        ))
        value = {**call.result, "execution_ref": {
            "call_id": str(call.id), "read_kind": "ordinary/v1",
        }}
    with Session(setup.admin) as session:
        before = session.scalar(select(func.count()).select_from(AgentToolCall).where(
            AgentToolCall.run_id == f.scope.run_id,
        ))
    state = {"tool_results": [{"tool": "research.read", "tier": "READ", "value": value}]}
    if change == "missing":
        f.artifacts._path(f.scope, f.snapshot.id).unlink()
    elif change == "forged_call":
        value["execution_ref"]["call_id"] = str(uuid4())
    elif change == "changed_result":
        value["markdown"] = "invented checkpoint text"
    child = ResearchChild(service(), f.scope.child("research"), ResearchTask("source", "read"))

    def read(bound, spec, arguments, intent, *, source):
        return f.host.read_callback(
            bound, spec, arguments, intent, source=source,
            callback=lambda *_: pytest.fail("Checkpoint replay must not make a fresh request"),
            restore=lambda previous: restore_page(
                child, ReadInput.model_validate(arguments), previous,
                artifacts=f.artifacts, current=f.store.current,
            ),
        )

    if change == "none":
        restore_reads(f.host, child, deepcopy(state), read)
        assert len(child.pages) == len(child.reads) == 1
        assert next(iter(child.pages.values())).snapshot.id == f.snapshot.id
    else:
        with pytest.raises(DomainError):
            restore_reads(f.host, child, state, read)
        assert not child.pages
    assert not child._service.transport.requests and not child._service.search_adapter.queries
    with Session(setup.admin) as session:
        assert session.scalar(select(func.count()).select_from(AgentToolCall).where(
            AgentToolCall.run_id == f.scope.run_id,
        )) == before


def test_composition_fence_is_exclusive_and_released(setup, tmp_path):
    f = fixture(setup, tmp_path, completed=False)
    with f.store.composition_lock(f.scope, "same-server-read-intent"):
        with pytest.raises(RuntimeError, match="already advancing"):
            with f.store.composition_lock(f.scope, "same-server-read-intent"):
                pytest.fail("Another connection cannot enter this composition")
    with f.store.composition_lock(f.scope, "same-server-read-intent"):
        pass


@pytest.mark.parametrize("tool", ["research.search", "research.read", "model"])
def test_resumable_orchestrator_flag_cannot_reissue_external_calls(setup, tool):
    from pdos_next.agent_kernel.persistence import KernelStore

    with pytest.raises(DomainError) as error:
        KernelStore(None).claim(None, "key", tool, {}, resume_started=True, execution_binding={
            "kind": "read", "read_kind": "ordinary/v1", "isolation": "main",
        })
    assert error.value.code == "FORBIDDEN_SCOPE"
