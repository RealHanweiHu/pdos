"""One conversation thread, independent Run checkpoints and legacy restoration."""

from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch
from uuid import uuid4

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.memory import InMemorySaver

from pdos_next.agent_kernel.graph import AgentKernel
from pdos_next.agent_kernel.session_checkpoints import (
    SESSION_LAYOUT,
    SessionRunSaver,
    main_checkpoint_config,
)
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.agent_kernel.types import ModelTurn
from pdos_next.errors import DomainError
from tests.agent_kernel.test_graph import Host, final, scope


class ConversationHost(Host):
    def checkpoint_layout(self, _):
        return SESSION_LAYOUT


def question():
    return ModelTurn(structured={
        "status": "needs_input", "summary": "Synthetic pending scope",
        "questions": [{"id": "region", "question": "Region?", "why": "Scope"}],
    })


def test_one_thread_keeps_waiting_and_finished_runs_independent_across_graph_recreation():
    root = scope()
    child = replace(root, run_id=uuid4())
    saver = InMemorySaver()
    first = ConversationHost([question(), final()])
    second = ConversationHost([final()])
    assert AgentKernel(first, default_registry()).execute(
        root, goal="Synthetic first request", checkpointer=saver
    )["__interrupt__"]
    root_address = main_checkpoint_config(root, SESSION_LAYOUT)
    before = saver.get_tuple(root_address)
    assert before is not None
    child_state = AgentKernel(second, default_registry()).execute(
        child, goal="Synthetic next request", checkpointer=saver
    )
    assert child_state["run_id"] == str(child.run_id)
    assert "Synthetic first request" not in str(child_state["messages"])
    assert saver.get_tuple(root_address) == before
    resumed = AgentKernel(first, default_registry()).execute(
        root, answer={"region": "US"}, checkpointer=saver
    )
    assert resumed["run_id"] == str(root.run_id)
    assert resumed["output"]["status"] == "completed"
    assert len(first.prefixes) == 2 and len(second.prefixes) == 1
    # Re-delivery of a finished child consumes no model turn or write.
    repeated = AgentKernel(second, default_registry()).execute(child, checkpointer=saver)
    assert repeated["output"] == child_state["output"] and len(second.prefixes) == 1
    checkpoints = list(saver.list({"configurable": {"thread_id": before.config[
        "configurable"]["thread_id"]}}))
    assert {c.config["configurable"]["thread_id"] for c in checkpoints} == {
        f"xiaopai:{root.tenant_id}:{root.session_id}"
    }
    assert {c.config["configurable"]["checkpoint_ns"] for c in checkpoints} == {
        f"run:{root.run_id}", f"run:{child.run_id}"
    }


def test_adapter_roundtrip_parent_pending_writes_list_and_nested_namespace():
    bound = scope()
    storage = InMemorySaver()
    adapter = SessionRunSaver(storage, bound)
    config = {"configurable": {"thread_id": adapter.thread, "checkpoint_ns": "subtask:1"}}
    first = empty_checkpoint()
    saved = adapter.put(config, first, {"source": "input", "step": -1}, {})
    second = empty_checkpoint()
    later = adapter.put(saved, second, {"source": "loop", "step": 0}, {})
    adapter.put_writes(later, [("result", {"synthetic": True})], "task-1", "path")
    found = adapter.get_tuple(later)
    assert found.config == later and found.parent_config == saved
    assert found.pending_writes == [("task-1", "result", {"synthetic": True})]
    assert found.metadata["pdos_run_id"] == str(bound.run_id)
    assert found.metadata["pdos_session_id"] == str(bound.session_id)
    assert [v.checkpoint["id"] for v in adapter.list(config)] == [second["id"], first["id"]]
    assert [v.checkpoint["id"] for v in adapter.list(config, before=later, limit=1)] == [
        first["id"]
    ]
    assert len(list(adapter.list(config, filter={"step": 0}))) == 1
    assert list(adapter.list(None)) == []  # Bound root namespace; no global enumeration.
    raw = next(storage.list({"configurable": {"thread_id": adapter.thread}}))
    assert raw.config["configurable"]["checkpoint_ns"] == adapter.prefix + "|subtask:1"
    with patch.object(storage, "get_next_version", return_value="storage-version") as version:
        assert adapter.get_next_version("previous", None) == "storage-version"
        version.assert_called_once_with("previous", None)
    derived = InMemorySaver()
    extra = [("pdos_next", "agent_kernel", "types", "RunScope")]
    with patch.object(storage, "with_allowlist", return_value=derived) as allowlist:
        allowed = adapter.with_allowlist(extra)
        allowlist.assert_called_once_with(extra)
    assert allowed.saver is derived and allowed.serde is derived.serde and allowed.scope is bound


def test_adapter_never_resolves_another_run_checkpoint_or_session():
    bound = scope()
    storage = InMemorySaver()
    first = SessionRunSaver(storage, bound)
    second = SessionRunSaver(storage, replace(bound, run_id=uuid4()))
    config = {"configurable": {"thread_id": first.thread}}
    saved = first.put(config, empty_checkpoint(), {"source": "input", "step": -1}, {})
    assert second.get_tuple(saved) is None
    assert list(second.list(None)) == []
    for bad in [
        {"configurable": {"thread_id": "other-session"}},
        main_checkpoint_config(bound, SESSION_LAYOUT),
    ]:
        with pytest.raises(DomainError, match="检查点") as failure:
            second.get_tuple(bad)
        assert failure.value.code == "FORBIDDEN_SCOPE"


def test_legacy_wait_restores_original_thread_and_unknown_layout_never_calls_model():
    bound, storage = scope(), InMemorySaver()
    host = Host([question(), final()])
    AgentKernel(host, default_registry()).execute(
        bound, goal="Synthetic legacy", checkpointer=storage
    )
    legacy_address = main_checkpoint_config(bound)
    original = storage.get_tuple(legacy_address)
    assert original is not None
    # Before this layout, persisted graph state had no server Run marker.
    legacy_checkpoint = deepcopy(original.checkpoint)
    legacy_checkpoint["channel_values"].pop("run_id")
    legacy_checkpoint["channel_versions"].pop("run_id")
    for seen in legacy_checkpoint["versions_seen"].values():
        seen.pop("run_id", None)
    storage.put(original.parent_config or legacy_address, legacy_checkpoint, original.metadata, {})
    assert "run_id" not in storage.get_tuple(legacy_address).checkpoint["channel_values"]
    result = AgentKernel(host, default_registry()).execute(
        bound, answer={"region": "US"}, checkpointer=storage
    )
    assert result["output"]["status"] == "completed" and len(host.prefixes) == 2
    assert main_checkpoint_config(bound)["configurable"]["thread_id"].endswith(str(bound.run_id))
    host.checkpoint_layout = lambda _: "unknown-layout"
    with pytest.raises(DomainError) as failure:
        AgentKernel(host, default_registry()).execute(bound, checkpointer=storage)
    assert failure.value.code == "VERSION_CONFLICT" and len(host.prefixes) == 2
