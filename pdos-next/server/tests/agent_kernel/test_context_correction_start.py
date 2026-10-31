"""Execute the actual public start endpoint with the delivered API patch in a temp copy."""

import asyncio
import importlib.util
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from pdos_next.agent_kernel import context_corrections, conversation, work_state
from pdos_next.contracts import SourceRead
from pdos_next.errors import DomainError
from pdos_next.service import Context, digest
from tests.agent_kernel.test_context_corrections import case


def patched_api(tmp_path):
    # In the integrated tree the root applies the public API hook itself. The
    # stage alone leaves api.py immutable and validates its separate patch here.
    from pdos_next.agent_kernel import api as actual

    if "context_revision" in actual.StartInput.model_fields:
        return actual
    stage = Path(__file__).parents[4]
    relative = Path("pdos-next/server/pdos_next/agent_kernel/api.py")
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    target.write_bytes((stage / relative).read_bytes())
    subprocess.run(
        ["git", "apply", "--check", str(stage / "api-context-corrections.patch")],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "apply", str(stage / "api-context-corrections.patch")],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    name = "pdos_next.agent_kernel._context_correction_api_test"
    spec = importlib.util.spec_from_file_location(name, target)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_actual_start_freezes_only_original_human_sources_before_dispatch(monkeypatch, tmp_path):
    api = patched_api(tmp_path)
    run, _ctx, ref = case()
    ref.update(source_type="artifact", object_id=ref["source_id"])
    ctx = Context(run.tenant_id, run.requester_id, run.requester_id, category_id=run.category_id)
    original_ref = SourceRead(artifact_id=UUID(ref["source_id"]), expected_revision=2)
    auto_ref = SourceRead(artifact_id=uuid4(), expected_revision=1)
    data = api.StartInput(
        goal="只看所选资料", idempotency_key="context-public-start", sources=[original_ref]
    )
    effective = data.model_copy(update={"session_id": uuid4(), "sources": [original_ref, auto_ref]})
    run.session_id, run.state, run.continued_from_id = effective.session_id, "queued", None
    events, dispatched, reads = [], [], []
    scalars = iter([None, None, run, True, run])
    session = SimpleNamespace(
        execute=lambda *_args, **_kwargs: None,
        scalar=lambda *_args: next(scalars),
        add=events.append,
    )

    @contextmanager
    def transaction(*_args, **_kwargs):
        yield session

    def resolve(_session, _ctx, _run, choices):
        reads.append(choices)
        assert len(choices) == 1 and choices[0].source_id == original_ref.artifact_id
        return [ref]

    async def dispatch(_reference):
        condition, configured = context_corrections.requested(run)
        assert configured and condition["sources"] == [ref]
        assert run.versions["requested_context_selection_digest"] == digest(condition)
        dispatched.append(run.id)

    monkeypatch.setattr(api, "tenant_session", transaction)
    created = []

    def create(*_args, **kwargs):
        run.intent_digest = kwargs["request_digest"]
        created.append(kwargs)
        return run

    monkeypatch.setattr(api, "create_run", create)
    monkeypatch.setattr(api, "require_access", lambda *_args: None)
    monkeypatch.setattr(conversation, "prepare", lambda *_args: (effective, None))
    monkeypatch.setattr(context_corrections, "resolve", resolve)
    monkeypatch.setattr(work_state, "latest", lambda *_: None)
    binding = SimpleNamespace(
        private_context=True, data_categories=["internal"], customer_identities=[], read_sources=[]
    )
    ports = api.ApiPorts(
        writer_for=lambda *_args: uuid4(),
        binding_for=lambda *_args: binding,
        start_workflow=dispatch,
        signal_workflow=None,
        cancel_workflow=None,
    )
    router = api.router(None, context_dependency=lambda: ctx, ports=ports)
    endpoint = next(
        route.endpoint
        for route in router.routes
        if getattr(route, "path", None) == "/v1/categories/{category_id}/agent-runs"
        and "POST" in route.methods
    )
    result = asyncio.run(endpoint(data, ctx=ctx))
    assert result["run_id"] == str(run.id) and dispatched == [run.id] and len(reads) == 1
    assert (
        len(effective.sources) == 2
        and len(run.versions["requested_context_selection"]["sources"]) == 1
    )

    legacy = data.model_dump(
        exclude={
            "idempotency_key",
            "project_id",
            "requested_skills",
            "search_preferences",
            "verification_action",
            "lookup_depth",
            "context_revision",
            "work_followup_action",
            "restart_from_run_id",
            "excluded_continued_skills",
        }
    )
    assert run.intent_digest == digest({"category_id": ctx.category_id, "request": legacy})
    monkeypatch.setattr(
        context_corrections,
        "configure_start",
        lambda *_args: pytest.fail("accepted intent must not reconfigure"),
    )
    replay = asyncio.run(endpoint(data, ctx=ctx))
    assert replay["run_id"] == result["run_id"] and len(created) == len(reads) == 1
    with pytest.raises(DomainError) as conflict:
        asyncio.run(endpoint(data.model_copy(update={"context_revision": 1}), ctx=ctx))
    assert conflict.value.code == "DUPLICATE_INTENT_CONFLICT"


def test_actual_prepare_checks_context_revision_under_original_lock_order(monkeypatch, tmp_path):
    api = patched_api(tmp_path)
    parent, ctx, _ref = case()
    parent.session_id, parent.reverted_at, parent.state = uuid4(), None, "completed"
    state = SimpleNamespace(revision=7, body={})
    conversation_row = SimpleNamespace(owner_id=parent.requester_id)
    events = []
    monkeypatch.setattr(conversation, "owner", lambda *_: None)
    monkeypatch.setattr(conversation, "current_proposal_id", lambda *_: None)
    monkeypatch.setattr(work_state, "_lock", lambda *_: events.append("work-state advisory"))
    monkeypatch.setattr(work_state, "latest", lambda *_: events.append("latest") or state)
    data = api.StartInput(
        goal="按本次选择重新查",
        idempotency_key="context-cas-original",
        continue_from_run_id=parent.id,
        context_revision=6,
    )

    def session():
        sequence = iter([parent, None, conversation_row])

        def scalar(statement):
            value = next(sequence)
            if value is parent:
                assert statement._for_update_arg is not None
                events.append("Run lock")
            return value

        return SimpleNamespace(scalar=scalar)

    with pytest.raises(DomainError) as stale:
        conversation.prepare(session(), ctx, data)
    assert stale.value.code == "VERSION_CONFLICT"
    assert events == ["Run lock", "work-state advisory", "latest"]
    events.clear()
    effective, actual_parent = conversation.prepare(
        session(), ctx, data.model_copy(update={"context_revision": 7})
    )
    assert actual_parent is parent and effective.session_id == parent.session_id
    assert effective.product_id == parent.product_id and effective.project_id == parent.project_id
    legacy, legacy_parent = conversation.prepare(
        SimpleNamespace(),
        ctx,
        api.StartInput(goal="普通旧请求", idempotency_key="legacy-no-context-cas"),
    )
    assert legacy.context_revision is None and legacy_parent is None
    with pytest.raises(DomainError):
        conversation.prepare(
            SimpleNamespace(),
            ctx,
            api.StartInput(
                goal="新会话不能夹带版本", idempotency_key="bad-context-cas", context_revision=7
            ),
        )
