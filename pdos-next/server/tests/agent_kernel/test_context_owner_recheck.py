"""The real pin recheck uses only the stored requester's ordinary read-only projection."""

from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from pdos_next.agent_kernel import context_corrections as corrections
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.models import Principal
from pdos_next.service import Context, digest
from tests.agent_kernel.test_context_corrections import case, selection


def fixture(monkeypatch):
    run, _ctx, ref = case()
    run.category_id = None
    run.writer_id, run.session_id = uuid4(), uuid4()
    run.cancel_epoch, run.state, run.reverted_at, run.trigger = 0, "queued", None, "conversation"
    condition = selection(ref, focus=None, sources=[ref])
    run.versions = {
        "requested_context_selection": condition,
        "requested_context_selection_digest": digest(condition),
    }
    ctx = Context(run.tenant_id, run.writer_id, run.requester_id, category_id=None,
                  agent_run_id=run.id, cancel_epoch=0)
    engine, seen = object(), []
    retained = deepcopy(run)
    source_row = {
        **ref, "source_id": UUID(ref["source_id"]), "object_id": UUID(ref["object_id"]),
        "category_id": UUID(ref["category_id"]),
    }
    human_scope = (run.tenant_id, run.requester_id, run.requester_id, None)

    def get(model, identity):
        seen.append(("ordinary_get", model, identity))
        if model is AgentRun:
            return retained
        assert model is Principal and identity == run.requester_id
        return SimpleNamespace(tenant_id=run.tenant_id, active=True, kind="human")

    reading = SimpleNamespace(info={"scope": human_scope}, get=get)
    writer = SimpleNamespace(
        info={"scope": (run.tenant_id, run.writer_id, run.requester_id, None)},
        get=lambda model, identity: run if model is AgentRun and identity == run.id else None,
        get_bind=lambda: engine,
    )

    @contextmanager
    def human_snapshot(actual_engine, actual_scope):
        assert actual_engine is engine
        assert actual_scope.run_id == run.id and actual_scope.writer_id == run.writer_id
        assert actual_scope.requester_id == run.requester_id and actual_scope.category_id is None
        seen.append(("human_snapshot", actual_scope))
        yield reading

    def rows(actual_session, actual_run, choices):
        assert actual_session is reading  # querying the writer would hide the second category
        assert actual_run is retained
        assert [str(row.source_id) for row in choices] == [ref["source_id"]]
        seen.append(("metadata", actual_run.id))
        return [source_row]

    def current(actual_session, values):
        assert actual_session is reading
        seen.append(("source_dependency_scan", list(values)))
        return {key: value for key, value in values.items()}, {}

    monkeypatch.setattr(
        "pdos_next.enterprise_search.assistant_sources.human_snapshot", human_snapshot
    )
    monkeypatch.setattr("pdos_next.enterprise_search.assistant_sources.current", current)
    monkeypatch.setattr(corrections, "_rows", rows)
    return SimpleNamespace(run=run, ctx=ctx, ref=ref, condition=condition, writer=writer,
                           reading=reading, retained=retained, seen=seen, rows=rows)


def test_writer_recheck_preserves_fixed_cross_category_pin_under_actual_human(monkeypatch):
    f = fixture(monkeypatch)
    result = corrections.recheck(f.writer, f.ctx, f.run, f.condition)
    assert result == f.condition and result is not f.condition
    assert [entry[0] for entry in f.seen].count("human_snapshot") == 1
    assert "metadata" in [entry[0] for entry in f.seen]
    assert f.run.read_sources == [] and f.run.category_id is None
    assert f.writer.info["scope"][1] == f.run.writer_id  # no GUC/role mutation


def test_human_api_recheck_stays_in_original_uow_without_snapshot_or_human_write(monkeypatch):
    f = fixture(monkeypatch)
    monkeypatch.setattr(corrections, "_rows", lambda session, *_: (
        pytest.fail("unexpected transaction") if session is not f.reading else [
            {**f.ref, "source_id": UUID(f.ref["source_id"]),
             "object_id": UUID(f.ref["object_id"]), "category_id": UUID(f.ref["category_id"])}
        ]
    ))
    human = Context(f.run.tenant_id, f.run.requester_id, f.run.requester_id)
    assert corrections.recheck(f.reading, human, f.retained, f.condition) == f.condition
    assert not any(entry[0] == "human_snapshot" for entry in f.seen)


@pytest.mark.parametrize(
    "failure", ["requester", "writer", "run_id", "category", "epoch", "transaction", "pin"]
)
def test_unbound_owner_or_source_cannot_open_human_projection(monkeypatch, failure):
    from dataclasses import replace

    from pdos_next.errors import DomainError

    f = fixture(monkeypatch)
    ctx, condition = f.ctx, deepcopy(f.condition)
    if failure == "requester":
        ctx = replace(ctx, requester_id=uuid4())
    elif failure == "writer":
        ctx = replace(ctx, actor_id=uuid4())
    elif failure == "run_id":
        ctx = replace(ctx, agent_run_id=uuid4())
    elif failure == "category":
        ctx = replace(ctx, category_id=uuid4())
    elif failure == "epoch":
        ctx = replace(ctx, cancel_epoch=1)
    elif failure == "transaction":
        f.writer.info["scope"] = (f.run.tenant_id, f.run.writer_id, uuid4(), None)
    else:
        condition["sources"][0]["source_id"] = str(uuid4())
    with pytest.raises(DomainError):
        corrections.recheck(f.writer, ctx, f.run, condition)
    assert not f.seen


@pytest.mark.parametrize("failure", ["revoked", "body_changed", "scan_changed"])
def test_owner_snapshot_retains_ordinary_revocation_hash_and_scan_rejection(monkeypatch, failure):
    from pdos_next.errors import DomainError

    f = fixture(monkeypatch)
    monkeypatch.setattr("pdos_next.enterprise_search.assistant_sources.current",
                        lambda *_: ({}, {"0": failure}))
    with pytest.raises(DomainError) as rejected:
        corrections.recheck(f.writer, f.ctx, f.run, f.condition)
    assert rejected.value.code == "SOURCE_UNAVAILABLE"


def test_retained_run_must_still_match_actual_binding_before_reading_pin(monkeypatch):
    from pdos_next.errors import DomainError

    f = fixture(monkeypatch)
    f.retained.requester_id = uuid4()
    with pytest.raises(DomainError):
        corrections.recheck(f.writer, f.ctx, f.run, f.condition)
    assert not any(entry[0] == "metadata" for entry in f.seen)


def test_reused_snapshot_is_read_only_for_actual_requester(monkeypatch):
    from pdos_next.enterprise_search import assistant_sources

    owner, agent, tenant = uuid4(), uuid4(), uuid4()
    scope = SimpleNamespace(tenant_id=tenant, requester_id=owner, writer_id=agent, category_id=None)
    captured = []

    @contextmanager
    def transaction(engine, actual_tenant, **kwargs):
        captured.append((engine, actual_tenant, kwargs))
        yield "readonly"

    monkeypatch.setattr(assistant_sources, "tenant_session", transaction)
    with assistant_sources.human_snapshot("engine", scope) as reader:
        assert reader == "readonly"
    assert captured == [("engine", tenant, {
        "actor_id": owner, "requester_id": owner, "category_id": None, "read_snapshot": True,
    })]
