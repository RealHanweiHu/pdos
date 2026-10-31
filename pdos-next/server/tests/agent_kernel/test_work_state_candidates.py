"""Real native proof validators and small storage doubles; no DB, model or network."""
# ruff: noqa: F811 -- imported native proof fixtures retain their original registration

from contextlib import contextmanager
from dataclasses import asdict
from types import SimpleNamespace as NS
from uuid import UUID, uuid4

import pytest

from pdos_next.agent_kernel import category_adoption, category_candidate, domain_candidates
from pdos_next.agent_kernel import work_state_candidates as metadata
from pdos_next.agent_kernel.models import AgentInput, AgentRun
from pdos_next.agent_kernel.types import RunScope
from pdos_next.errors import DomainError
from pdos_next.models import Principal
from pdos_next.service import Context
from tests.agent_kernel.test_category_adoption import ledger as adopted_ledger  # noqa: F401
from tests.agent_kernel.test_category_candidate import ledger as pending_ledger  # noqa: F401
from tests.agent_kernel.test_category_candidate import prepare


class Reading:
    def __init__(self):
        self.scope = RunScope(*(uuid4() for _ in range(6)))
        fields = asdict(self.scope)
        fields["id"] = fields.pop("run_id")
        self.run = NS(**fields, state="completed", reverted_at=None, versions={},
                      continued_from_id=None)
        self.rows, self.statements = [], []
        self.info = {"scope": (self.scope.tenant_id, self.scope.requester_id,
                               self.scope.requester_id, self.scope.category_id)}
        self.owner = Context(self.scope.tenant_id, self.scope.requester_id,
                             self.scope.requester_id, category_id=self.scope.category_id)

    def get(self, model, identity):
        if model is AgentRun and identity == self.run.id:
            return self.run
        if model is Principal and identity == self.run.requester_id:
            return NS(kind="human", active=True)
        return None

    def execute(self, statement):
        self.statements.append(statement)
        return NS(all=lambda: self.rows)


def event(reading, kind):
    return NS(id=uuid4(), tenant_id=reading.run.tenant_id, run_id=reading.run.id,
              body={"type": kind})


def test_old_json_adopted_flags_are_selectors_only_and_native_metadata_is_whitelisted(monkeypatch):
    reading = Reading()
    item = event(reading, "domain_candidate")
    reading.rows = [(item, reading.run)]
    receipt = str(uuid4())
    calls = []

    def native(session, owner, run, rows):
        calls.append((session, owner, run, rows))
        return [{"event_id": str(item.id), "state": "adopted", "operation": "proposal.create",
                 "receipt": {"id": receipt, "body": "DO_NOT_COPY"},
                 "command": {"payload": "DO_NOT_COPY"}, "source_proof": "DO_NOT_COPY"}]

    monkeypatch.setattr(domain_candidates, "project_rows", native)
    refs = [{"event_id": str(item.id), "run_id": str(reading.run.id),
             "state": "pending", "receipt_id": str(uuid4()), "payload": "FORGED"}]
    value, missing = metadata.project(reading, reading.owner, reading.run, refs)
    assert not missing
    assert value == [{"event_id": str(item.id), "run_id": str(reading.run.id),
                      "kind": "domain", "operation": "proposal.create",
                      "state": "adopted", "receipt_id": receipt}]
    assert "DO_NOT_COPY" not in str(value) and "FORGED" not in str(value)
    assert calls[0][1].actor_id == reading.run.requester_id
    query = reading.statements[0]
    assert query._for_update_arg is None
    sql = str(query)
    assert "agent_runs.session_id =" in sql and "agent_runs.requester_id =" in sql
    assert "agent_runs.tenant_id =" in sql
    assert reading.run.session_id in query.compile().params.values()


@pytest.mark.parametrize("kind", ["snapshot_candidate", "verification_candidate"])
def test_snapshot_and_verification_use_the_same_native_projection_without_payload(
    monkeypatch, kind,
):
    reading = Reading()
    item = event(reading, kind)
    reading.rows = [(item, reading.run)]
    monkeypatch.setattr(domain_candidates, "project_rows", lambda *_: [
        {"event_id": str(item.id), "state": "pending", "operation": "native.operation",
         "command": {"payload": "SECRET"}}
    ])
    value, missing = metadata.project(
        reading, reading.owner, reading.run,
        [{"event_id": str(item.id), "run_id": str(reading.run.id), "state": "adopted"}],
    )
    assert not missing and value[0]["state"] == "pending"
    assert value[0]["receipt_id"] is None and "SECRET" not in str(value)


def test_foreign_or_now_hidden_origin_is_absent_instead_of_echoing_old_identifiers():
    reading = Reading()
    reference = {"event_id": str(uuid4()), "run_id": str(uuid4())}
    value, missing = metadata.project(reading, reading.owner, reading.run, [reference])
    assert value == [] and missing


def test_projection_cannot_borrow_a_peer_or_an_unbound_agent_requester():
    reading = Reading()
    ref = {"event_id": str(uuid4()), "run_id": str(reading.run.id)}
    for ctx in [
        Context(reading.run.tenant_id, uuid4(), uuid4(), category_id=reading.run.category_id),
        Context(reading.run.tenant_id, reading.run.writer_id, reading.run.requester_id,
                category_id=reading.run.category_id),
    ]:
        with pytest.raises(DomainError):
            metadata.project(reading, ctx, reading.run, [ref])
    assert not reading.statements


def test_agent_owner_read_snapshot_is_derived_only_from_its_actual_run(monkeypatch):
    reading = Reading()
    item = event(reading, "domain_candidate")
    reading.rows = [(item, reading.run)]
    scope = reading.scope
    ctx = Context(scope.tenant_id, scope.writer_id, scope.requester_id,
                  category_id=scope.category_id, agent_run_id=scope.run_id,
                  cancel_epoch=scope.cancel_epoch)
    outer = Reading()
    outer.scope, outer.run = reading.scope, reading.run
    outer.info["scope"] = (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id)
    outer.get_bind = lambda: "same-engine"
    from pdos_next.enterprise_search import assistant_sources

    observed = []

    @contextmanager
    def snapshot(engine, bound):
        observed.append((engine, bound))
        yield reading

    monkeypatch.setattr(assistant_sources, "human_snapshot", snapshot)
    monkeypatch.setattr(domain_candidates, "project_rows", lambda *_: [
        {"event_id": str(item.id), "state": "pending", "operation": "proposal.create"}])
    value, missing = metadata.project(
        outer, ctx, outer.run, [{"event_id": str(item.id), "run_id": str(scope.run_id)}],
    )
    assert not missing and value[0]["state"] == "pending"
    assert observed == [("same-engine", scope)]
    assert outer.run.writer_id == scope.writer_id and not outer.statements


def test_category_pending_reuses_native_proof_without_locks_and_execution_still_locks(
    pending_ledger, monkeypatch,
):
    f = pending_ledger
    prepared = prepare(f)
    item = next(row for (kind, _), row in f.s.rows.items()
                if kind is not AgentRun and getattr(row, "id", None) == UUID(prepared["event_id"]))
    ctx = Context(f.run.tenant_id, f.run.requester_id, f.run.requester_id)
    f.s.info["scope"] = (ctx.tenant_id, ctx.actor_id, ctx.requester_id, None)
    queries, scalar = [], f.s.scalar

    def record(query):
        queries.append(query)
        return scalar(query)

    monkeypatch.setattr(f.s, "scalar", record)
    value = category_candidate.read_metadata(f.s, ctx, f.run, item)
    assert value == {"operation": "category.create", "state": "pending", "receipt_id": None}
    assert all(query._for_update_arg is None for query in queries)
    category_candidate.validate(
        f.s, ctx, category_candidate.CategoryCreate.model_validate(prepared["payload"]),
    )
    assert any(query._for_update_arg is not None for query in queries)


def test_category_adopted_reuses_actual_receipt_in_same_read_session_without_write_locks(
    adopted_ledger, monkeypatch,
):
    f = adopted_ledger
    scalar = f.s.scalar
    monkeypatch.setattr(f.s, "scalar", lambda query: f.entry if (
        query.column_descriptions[0]["entity"] is AgentInput
    ) else scalar(query))
    queries, execute = [], f.s.execute

    def record(query):
        queries.append(query)
        return execute(query)

    monkeypatch.setattr(f.s, "execute", record)
    owner = Context(f.scope.tenant_id, f.scope.requester_id, f.scope.requester_id)
    value = category_adoption.read_metadata(f.s, owner, f.run, f.candidate)
    assert value == {"operation": "category.create", "state": "adopted",
                     "receipt_id": str(f.receipt.id)}
    assert not f.s.transactions  # No resolve(engine,...) transaction or borrowed write session.
    assert queries and all(query._for_update_arg is None for query in queries)


@pytest.mark.parametrize("change", ["receipt", "receipt_operation", "grant"])
def test_readonly_category_adoption_never_trusts_an_event_label_without_native_facts(
    adopted_ledger, monkeypatch, change,
):
    f = adopted_ledger
    monkeypatch.setattr(f.s, "scalar", lambda _query: f.entry)
    if change == "receipt":
        from pdos_next.models import Receipt

        del f.s.rows[Receipt, f.receipt.id]
    elif change == "receipt_operation":
        f.receipt.operation = "forged"
    else:
        f.s.grant = None
    f.candidate.body["state"] = "adopted"
    owner = Context(f.scope.tenant_id, f.scope.requester_id, f.scope.requester_id)
    with pytest.raises(DomainError):
        category_adoption.read_metadata(f.s, owner, f.run, f.candidate)


@pytest.mark.parametrize("state", ["adopted", "cancelled", "unavailable"])
def test_current_native_status_does_not_rewrite_the_running_frozen_snapshot(monkeypatch, state):
    from pdos_next.agent_kernel import work_state

    ref = {"event_id": str(uuid4()), "run_id": str(uuid4()), "state": "pending"}
    frozen = {"revision": 1, "focus_objects": [], "candidates": [ref]}
    run = NS(session_id=uuid4(), versions={"work_state": frozen})
    session = NS(scalar=lambda _query: object())
    monkeypatch.setattr(work_state, "_project", lambda *_args, **_kwargs: {
        "focus_objects": [], "candidates": [{**ref, "state": state}],
    })
    work_state.check_frozen(session, run, object())
    assert run.versions["work_state"] is frozen and ref["state"] == "pending"
    monkeypatch.setattr(work_state, "_project", lambda *_args, **_kwargs: {
        "focus_objects": [], "candidates": [],
    })
    with pytest.raises(DomainError) as denied:
        work_state.check_frozen(session, run, object())
    assert denied.value.code == "FORBIDDEN_SCOPE"
    assert denied.value.reason == "CONVERSATION_HISTORY_REVOKED"
    assert run.versions["work_state"] is frozen
