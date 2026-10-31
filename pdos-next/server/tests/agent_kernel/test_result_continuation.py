"""Real host provenance/claim/restore with synthetic durable rows; no provider or DB."""

import json
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest

from pdos_next.agent_kernel.bindings import execution_key
from pdos_next.agent_kernel.context_budget import estimate_tokens
from pdos_next.agent_kernel.models import AgentToolCall
from pdos_next.agent_kernel.read_execution import ReadSource
from pdos_next.agent_kernel.registry import ToolRegistry
from pdos_next.agent_kernel.result_continuation import (
    ResultReadInput,
    handle_for,
    page_view,
    serialized,
)
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.errors import DomainError
from pdos_next.service import digest
from tests.agent_kernel.test_bound_read_host import make_host, read


def host():
    f = make_host()
    registry = ToolRegistry([f.spec, default_registry().get("result.read")])
    f.host.adapters = replace(f.host.adapters, tool_registry=registry)
    binding = {**f.model.execution_binding,
               "tool_definitions_digest": digest(registry.definitions())}
    f.model.execution_binding = binding
    f.run.versions["tool_definitions"]["main"] = binding["tool_definitions_digest"]
    f.result = {"items": [{"value": "合成正文\\\n\"" * 4_000}]}

    def scalar(statement):
        params = statement.compile().params
        calls = [row for (kind, _), row in f.store.session.rows.items()
                 if kind is AgentToolCall]
        if "call_key_1" in params:
            return next((row for row in calls if row.call_key == params["call_key_1"]), None)
        if "id_1" in params:
            return f.store.session.rows.get((AgentToolCall, params["id_1"]))
        return None

    f.store.session.scalar = scalar
    f.store.composition_lock = lambda *args, **kwargs: nullcontext()
    return f


def page_request(f, handle, page=2):
    arguments = {"handle": handle, "page": page}
    model = AgentToolCall(
        id=uuid4(), tenant_id=f.scope.tenant_id, run_id=f.scope.run_id, tool="model",
        state="completed", error_code=None, receipt_id=None,
        execution_binding=deepcopy(f.model.execution_binding),
        result={"calls": [{"id": "page", "name": "result.read", "arguments": arguments}]},
    )
    f.store.session.rows[AgentToolCall, model.id] = model
    return arguments, ReadSource(model_call_id=model.id, response_index=0)


def continue_page(f, arguments, source):
    return f.host.read(
        f.scope, f.host.adapters.tool_registry.get("result.read"), arguments,
        execution_key(f.scope.run_id, source.model_call_id, source.response_index), source=source,
    )


def test_bound_result_limit_full_ledger_and_every_page_replay_rechecks_source():
    f = host()
    full = read(f)
    original = f.store.session.call
    preview = f.host.tool_message(f.scope, f.spec, full)
    assert preview["truncated"] and preview["total_items"] == 1
    assert estimate_tokens(serialized(preview)) <= f.spec.max_result_tokens
    assert original.result == f.result and "execution_ref" not in original.result
    arguments, source = page_request(f, preview["result_handle"])
    second = continue_page(f, arguments, source)
    assert estimate_tokens(serialized(second)) <= 4_000
    assert second["page"] == 2 and f.callbacks == 2
    assert continue_page(f, arguments, source) == second and f.callbacks == 3
    assert len([row for (kind, _), row in f.store.session.rows.items()
                if kind is AgentToolCall and row.tool == "result.read"]) == 1
    f.callback_error = DomainError("FORBIDDEN_SCOPE", "Synthetic source revoked")
    with pytest.raises(DomainError) as error:
        continue_page(f, arguments, source)
    assert error.value.code == "FORBIDDEN_SCOPE" and f.callbacks == 4


def test_pages_reconstruct_exact_result_including_json_escapes():
    f = host()
    full = read(f)
    preview = f.host.tool_message(f.scope, f.spec, full)
    fragments = [preview["preview"]]
    for page in range(2, preview["total_pages"] + 1):
        current = f.host.continue_result(
            f.scope, ResultReadInput(handle=preview["result_handle"], page=page),
        )
        assert estimate_tokens(serialized(current)) <= 4_000
        fragments.append(current["preview"])
    assert json.loads("".join(fragments)) == full


@pytest.mark.parametrize("change", ["content", "run", "tenant", "isolation", "fingerprint"])
def test_continuation_denies_stale_foreign_or_wrong_isolation_handles(change):
    f = host()
    full = read(f)
    handle = f.host.tool_message(f.scope, f.spec, full)["result_handle"]
    scope = f.scope
    if change == "content":
        f.result["items"][0]["value"] = "Changed after original read"
    elif change in {"run", "tenant"}:
        scope = replace(scope, **{change + "_id": uuid4()})
    elif change == "isolation":
        scope = replace(scope, isolation="extract")
    else:
        handle = handle[:-1] + ("a" if handle[-1] != "a" else "b")
    with pytest.raises(DomainError) as error:
        f.host.continue_result(scope, ResultReadInput(handle=handle, page=1))
    assert error.value.code == ("SOURCE_STALE" if change == "content" else "FORBIDDEN_SCOPE")


def test_model_ledger_json_cannot_become_a_read_handle():
    f = host()
    with pytest.raises(DomainError) as error:
        f.host.continue_result(f.scope, ResultReadInput(
            handle=handle_for(f.model.id, f.model.result), page=1,
        ))
    assert error.value.code == "FORBIDDEN_SCOPE"


def test_invalid_page_and_small_page_limit_are_explicit():
    handle = handle_for(uuid4(), {"value": "data"})
    with pytest.raises(DomainError):
        page_view({"value": "data"}, handle, 2)
    for page in [1, 2, 3]:
        view = page_view({"value": "汉\\\n\"" * 2_000}, handle, page, 512)
        assert estimate_tokens(serialized(view)) <= 512


def test_interrupted_page_resumes_original_claim_without_repeating_effects():
    f = host()
    full = read(f)
    preview = f.host.tool_message(f.scope, f.spec, full)
    arguments, source = page_request(f, preview["result_handle"])
    settle = f.store.settle
    class WorkerInterrupted(BaseException):
        pass
    def stop_before_settle(*args, **kwargs):
        raise WorkerInterrupted()
    f.store.settle = stop_before_settle
    with pytest.raises(WorkerInterrupted):
        continue_page(f, arguments, source)
    interrupted = f.store.session.call
    assert interrupted.tool == "result.read" and interrupted.state == "started"
    f.store.settle = settle
    result = continue_page(f, arguments, source)
    assert result["execution_ref"]["call_id"] == str(interrupted.id)
    assert interrupted.state == "completed"
    assert len([row for (kind, _), row in f.store.session.rows.items()
                if kind is AgentToolCall and row.tool == "result.read"]) == 1


def test_isolated_original_text_never_appears_in_main_disclosure():
    registry = default_registry()
    assert "result.read" in {item["name"] for item in registry.definitions()}
    for isolation in ("research", "extract", "mcp", "assistant_extract", "assistant_compare"):
        assert "result.read" in {item["name"] for item in registry.definitions(isolation)}
    assert "evidence.artifact.read" not in {item["name"] for item in registry.definitions()}


@pytest.mark.parametrize("source_status", ["current", "updated", "hidden"])
def test_history_continuation_rechecks_parent_metadata_once_without_replaying_reader(
    source_status, monkeypatch
):
    from pdos_next.agent_kernel import conversation_acl
    from pdos_next.agent_kernel.conversation import classify_turn

    f = host()
    full = read(f)
    preview = f.host.tool_message(f.scope, f.spec, full)
    arguments, source = page_request(f, preview["result_handle"])
    continue_page(f, arguments, source)
    f.run.result = {"summary": "保留原回答", "unfinished": []}
    identity = str(f.scope.category_id)
    access = {str(f.run.id): {"dependencies": [
        conversation_acl.dependency("category", identity, 1)],
        "citations": [], "prepared": False, "unverified": [], "research": []}}
    batches = []
    def metadata(_session, deps):
        batches.append(deps)
        return {} if source_status == "hidden" else {("category", identity): [{
            "revision": 2 if source_status == "updated" else 1}]}
    monkeypatch.setattr(conversation_acl, "metadata", metadata)
    def forbidden(*_args):
        pytest.fail("Historical result pages must not replay the original reader")
    result = classify_turn(None, f.run, {"category.read": forbidden}, f.scope, access=access)
    assert result["state"] == source_status and len(batches) == 1
    if source_status != "hidden":
        assert result["outcome"]["summary"] == "保留原回答"
        assert "未复核" not in str(result["outcome"]["notes"])


@pytest.mark.parametrize("complete", [False, True])
def test_isolated_graph_requires_delivered_fragments_before_source_verification(complete):
    from pdos_next.agent_kernel.graph import AgentKernel
    from pdos_next.agent_kernel.types import ModelTurn, ToolCall
    from tests.agent_kernel.test_graph import Host, final, scope

    turns = [ModelTurn(calls=(ToolCall(id="raw", name="evidence.artifact.read", arguments={}),))]
    if complete:
        turns.append(ModelTurn(calls=(ToolCall(id="rest", name="result.read", arguments={
            "handle": "synthetic", "page": 2,
        }),)))
    turns.extend([final(), final(), final()])
    host = Host(turns)
    host.tool_message = lambda bound, spec, value: value if spec.name == "result.read" else {
        "result_handle": "synthetic", "truncated": True, "page": 1,
        "total_pages": 2, "preview": "first JSON fragment",
    }
    host.read = lambda bound, spec, arguments, intent: {
        "result_handle": "synthetic", "page": 2, "total_pages": 2,
    } if spec.name == "result.read" else {"raw": "full server original"}
    state = AgentKernel(host, default_registry()).execute(
        scope(isolation="extract"), goal="Synthetic isolated extraction",
        execution_key={"synthetic_fragment_test": True},
    )
    assert state["output"]["status"] == ("completed" if complete else "partial")
    if not complete:
        assert "missing_pages" in str(host.captured_model_messages[-1])
