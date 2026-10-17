"""Ordinary storage doubles exercise actual adoption records, authority and transport."""

import asyncio
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from pdos_next.agent_kernel import activities
from pdos_next.agent_kernel import category_adoption as adoption
from pdos_next.agent_kernel.graph import VerifiedCategoryAdoption
from pdos_next.agent_kernel.models import AgentEvent, AgentRun
from pdos_next.agent_kernel.persistence import record_answers
from pdos_next.agent_kernel.temporal_port import workflow_id
from pdos_next.agent_kernel.types import RunScope
from pdos_next.dispatch import outbox
from pdos_next.errors import DomainError
from pdos_next.models import Category, Principal, Receipt
from pdos_next.service import Context, digest
from pdos_next.workflows.transport import TemporalSender
from pdos_next.workflows.xiaopai import XiaopaiWork


class MemorySession:
    def __init__(self, scope):
        self.scope, self.rows, self.info, self.transactions = scope, {}, {}, []
        self.transaction = object()
        self.grant = NS(can_write=True, expires_at=None, access_epoch=1)
        self.adopted = []

    def put(self, cls, row):
        self.rows[cls, row.id] = row
        return row

    def get(self, cls, identity):
        row = self.rows.get((cls, identity))
        if row is not None and row.tenant_id != self.info["scope"][0]:
            return None
        return row

    def get_transaction(self):
        return self.transaction

    def scalar(self, query):
        assert "max(" in str(query)
        return max((r.sequence for (cls, _) , r in self.rows.items()
                    if cls is AgentEvent), default=0)

    def scalars(self, query):
        # Mirror the ordinary query's tenant/run/type/input_ref filters, not proof logic.
        params = query.compile().params
        identities = {str(value) for value in params.values()}
        rows = [r for r in self.adopted if r.tenant_id == self.scope.tenant_id
                and r.run_id == self.scope.run_id and r.body.get("type") == adoption.ADOPTED
                and r.body.get("input_ref") in identities]
        return NS(all=lambda: rows)

    def execute(self, query):
        assert query.column_descriptions[0]["entity"] is Principal
        actor = self.info["scope"][1]
        # Only the actual Human has a grant; the personal Agent has none.
        principal = self.get(Principal, actor)
        rows = [(principal, self.grant)] if actor == self.scope.requester_id and self.grant else []
        return NS(all=lambda: rows)

    def add_all(self, rows):
        for row in rows:
            row.id = row.id or uuid4()
            self.put(type(row), row)
            if isinstance(row, AgentEvent):
                self.adopted.append(row)

    def add(self, row):
        self.add_all([row])

    @contextmanager
    def bound(self, engine, tenant_id, *, actor_id=None, requester_id=None, category_id=None):
        self.info = {"scope": (tenant_id, actor_id, requester_id, category_id)}
        self.transaction = object()
        self.transactions.append(self.info["scope"])
        yield self


@pytest.fixture
def ledger(monkeypatch):
    scope = RunScope(*(uuid4() for _ in range(5)), category_id=None)
    session = MemorySession(scope)
    session.info = {"scope": (scope.tenant_id, scope.requester_id, scope.requester_id, None)}
    fields = asdict(scope)
    fields["id"] = fields.pop("run_id")
    run = session.put(AgentRun, NS(**fields, state="waiting_input", reverted_at=None,
                                   goal="Synthetic category", error_code=None))
    for identity, kind in ((scope.requester_id, "human"), (scope.writer_id, "agent")):
        session.put(Principal, NS(id=identity, tenant_id=scope.tenant_id, kind=kind,
                                  active=True, access_epoch=1))
    event = session.put(AgentEvent, NS(
        id=uuid4(), tenant_id=scope.tenant_id, run_id=run.id, sequence=3,
        body={"type": "category_candidate", "candidate_digest": "a" * 64, "cancel_epoch": 0},
    ))
    category = session.put(Category, NS(
        id=uuid4(), tenant_id=scope.tenant_id, owner_id=scope.requester_id,
        created_by_run_id=run.id, revision=1, name="Synthetic", lifecycle_epoch=1,
    ))
    receipt = session.put(Receipt, NS(
        id=uuid4(), tenant_id=scope.tenant_id, category_id=category.id, subject_id=category.id,
        actor_id=scope.requester_id, requester_id=scope.requester_id, operation="category.create",
        subject_type="category", agent_run_id=None,
        result={"origin": "ai_draft", "prepared_by_run_id": str(run.id),
                "category_candidate_event_id": str(event.id), "candidate_digest": "a" * 64},
    ))
    entry = adoption.record(session, NS(run=run, event=event), receipt)
    monkeypatch.setattr(adoption, "tenant_session", session.bound)
    return NS(scope=scope, s=session, run=run, candidate=event, category=category,
              receipt=receipt, entry=entry, adopted=session.adopted[0], engine=NS())


def resolve(f):
    return adoption.resolve(f.engine, f.scope, f.entry.id)


def test_real_record_and_resolve_use_human_grant_without_granting_personal_agent(ledger):
    f = ledger
    result = resolve(f)
    assert isinstance(result, VerifiedCategoryAdoption)
    assert result.input_ref == str(f.entry.id)
    assert result.category_adoption["receipt_id"] == str(f.receipt.id)
    assert f.adopted.sequence == f.candidate.sequence + 1
    assert f.entry.payload_digest == digest(f.entry.answers)
    assert f.receipt.result["adoption_input_ref"] == str(f.entry.id)
    assert f.adopted.body == {**f.entry.answers, "type": "category_adopted",
                              "input_ref": str(f.entry.id)}
    assert f.s.transactions == [(f.scope.tenant_id, f.scope.requester_id,
                                f.scope.requester_id, None)]
    assert f.run.category_id is None


@pytest.mark.parametrize("state", ["completed", "partial"])
def test_historical_terminal_adoption_does_not_mutate_or_reopen_run(ledger, state):
    ledger.run.state = state
    assert isinstance(resolve(ledger), VerifiedCategoryAdoption)
    assert ledger.run.state == state


@pytest.mark.parametrize("change", [
    "other_requester", "other_input_run", "other_writer", "other_candidate_run", "other_tenant",
    "failed", "cancelled", "reverted", "epoch", "digest", "input_type", "candidate_type",
    "candidate_digest", "candidate_epoch", "receipt_actor", "receipt_requester",
    "receipt_operation",
    "receipt_category", "receipt_subject", "receipt_type", "receipt_agent", "receipt_origin",
    "receipt_run", "receipt_candidate", "receipt_digest", "receipt_input", "missing_receipt",
    "missing_candidate", "missing_event", "event_type", "event_body", "double_event",
    "category_owner", "category_run", "grant_missing", "grant_expired", "human_inactive",
])
def test_actual_identity_receipt_candidate_and_adoption_are_all_required(ledger, change):
    f = ledger
    if change == "other_requester":
        f.entry.requester_id = uuid4()
    elif change == "other_input_run":
        f.entry.run_id = uuid4()
    elif change == "other_writer":
        f.run.writer_id = uuid4()
    elif change == "other_candidate_run":
        f.candidate.run_id = uuid4()
    elif change == "other_tenant":
        f.receipt.tenant_id = uuid4()
    elif change in {"failed", "cancelled"}:
        f.run.state = change
    elif change == "reverted":
        f.run.reverted_at = datetime.now(UTC)
    elif change == "epoch":
        f.run.cancel_epoch += 1
    elif change == "digest":
        f.entry.payload_digest = "f" * 64
    elif change == "input_type":
        f.entry.answers["proof_version"] = True
        f.entry.payload_digest = digest(f.entry.answers)
    elif change.startswith("candidate_"):
        key = change.removeprefix("candidate_")
        field = {"type": "type", "digest": "candidate_digest", "epoch": "cancel_epoch"}[key]
        f.candidate.body[field] = "bad"
    elif change.startswith("receipt_"):
        key = change.removeprefix("receipt_")
        fields = {"actor": "actor_id", "requester": "requester_id", "operation": "operation",
                  "category": "category_id", "subject": "subject_id", "type": "subject_type",
                  "agent": "agent_run_id"}
        if key in fields:
            setattr(f.receipt, fields[key], uuid4())
        else:
            field = {"origin": "origin", "run": "prepared_by_run_id",
                     "candidate": "category_candidate_event_id", "digest": "candidate_digest",
                     "input": "adoption_input_ref"}[key]
            f.receipt.result[field] = "bad"
    elif change.startswith("missing_"):
        key = change.removeprefix("missing_")
        if key == "event":
            f.s.adopted = []
        else:
            row = f.receipt if key == "receipt" else f.candidate
            cls = Receipt if key == "receipt" else AgentEvent
            del f.s.rows[cls, row.id]
    elif change == "event_type":
        f.adopted.body["type"] = "untrusted"
    elif change == "event_body":
        f.adopted.body["receipt_id"] = str(uuid4())
    elif change == "double_event":
        f.s.adopted.append(deepcopy(f.adopted))
    elif change == "category_owner":
        f.category.owner_id = uuid4()
    elif change == "category_run":
        f.category.created_by_run_id = uuid4()
    elif change == "grant_missing":
        f.s.grant = None
    elif change == "grant_expired":
        f.s.grant.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    else:
        f.s.get(Principal, f.scope.requester_id).active = False
    with pytest.raises(DomainError):
        resolve(f)


def test_ordinary_lookalike_answers_never_gain_server_proof_type(ledger):
    f = ledger
    f.entry.answers = {"input_ref": str(f.entry.id), "category_adoption": {
        key: value for key, value in f.entry.answers.items() if key not in {"type", "proof_version"}
    }}
    f.entry.payload_digest = digest(f.entry.answers)
    result = resolve(f)
    assert type(result) is dict and not isinstance(result, VerifiedCategoryAdoption)


@pytest.mark.parametrize("answers,key", [
    ({"type": "category_adoption"}, "human-answer-1"), ({}, "category-adoption:forged"),
])
def test_public_answer_writer_cannot_claim_reserved_adoption(ledger, answers, key):
    f = ledger
    ctx = Context(f.scope.tenant_id, f.scope.requester_id, f.scope.requester_id)
    with pytest.raises(DomainError):
        record_answers(f.s, ctx, f.run.id, answers=answers, idempotency_key=key)


def event_for(f):
    return outbox.Envelope(
        event_id=str(uuid4()), tenant_id=str(f.scope.tenant_id), category_id=str(f.category.id),
        product_id=None, subject_id=str(f.category.id), subject_revision=1,
        event_type="category.created", schema_version=1, correlation_id=str(uuid4()),
        lease_id=str(uuid4()), actor_id=str(f.scope.requester_id),
        requester_id=str(f.scope.requester_id),
    )


class TemporalClient:
    def __init__(self):
        self.calls = []
        self.fail = False

    def get_workflow_handle(self, identity):
        async def signal(method, value):
            self.calls.append((identity, method, value))
            if self.fail:
                raise OSError("Synthetic uncertain signal")
        return NS(signal=signal)


def test_transport_sends_only_exact_three_uuid_metadata(ledger, monkeypatch):
    f, client = ledger, TemporalClient()
    event = event_for(f)
    meta = {"tenant_id": f.scope.tenant_id, "run_id": f.scope.run_id, "input_ref": f.entry.id}
    monkeypatch.setattr(adoption, "dispatch_reference", lambda engine, actual: meta)
    identity = asyncio.run(TemporalSender(client, dispatch_engine=object())(event))
    assert identity == workflow_id(f.scope.tenant_id, f.scope.run_id)
    assert client.calls == [(identity, XiaopaiWork.resume, str(f.entry.id))]


def test_outbox_unknown_retries_same_input_reference_then_acknowledges(ledger, monkeypatch):
    f, client = ledger, TemporalClient()
    event, finished = event_for(f), []
    meta = {"tenant_id": f.scope.tenant_id, "run_id": f.scope.run_id, "input_ref": f.entry.id}
    monkeypatch.setattr(adoption, "dispatch_reference", lambda engine, actual: meta)
    monkeypatch.setattr(outbox, "claim_events", lambda *_: [event])
    monkeypatch.setattr(outbox, "_finish", lambda engine, actual, identity, unknown:
                        finished.append((actual.event_id, actual.lease_id, identity, unknown))
                        or True)
    sender = TemporalSender(client, dispatch_engine=object())
    client.fail = True
    assert asyncio.run(outbox.dispatch_once(object(), f.scope.tenant_id, sender)) == {
        "delivered": 0, "unknown": 1,
    }
    client.fail = False
    assert asyncio.run(outbox.dispatch_once(object(), f.scope.tenant_id, sender)) == {
        "delivered": 1, "unknown": 0,
    }
    assert len(client.calls) == 2 and client.calls[0] == client.calls[1]
    assert finished[0][3] is True and finished[1][3] is False
    assert finished[0][:2] == finished[1][:2]


def test_nonadoption_or_terminal_metadata_miss_does_not_signal(ledger, monkeypatch):
    client = TemporalClient()
    monkeypatch.setattr(adoption, "dispatch_reference", lambda *_: None)
    assert asyncio.run(TemporalSender(client, dispatch_engine=object())(event_for(ledger))) is None
    assert not client.calls


def test_activity_delivers_proof_and_never_reopens_terminal_run(ledger, monkeypatch):
    f = ledger
    monkeypatch.setattr(activities, "tenant_session", f.s.bound)
    adapters = NS(preload=None, tool_registry=object())
    f.engine._pdos_agent_kernel_adapters = adapters
    runner = activities.KernelActivities(f.engine, checkpoint_url="synthetic")

    @contextmanager
    def transaction(*args, **kwargs):
        yield f.s, f.run

    runner.store = NS(scope=lambda **kwargs: f.scope, transaction=transaction)
    monkeypatch.setattr(activities, "BoundHost", lambda *_: NS(
        catalog=object(), gateway=NS(close=lambda: None),
    ))
    captured = []

    class Kernel:
        def __init__(self, *args, **kwargs):
            pass

        def execute(self, scope, **kwargs):
            captured.append((scope, kwargs["answer"]))
            return {"__interrupt__": ["synthetic next wait"]}

    @contextmanager
    def saver(url):
        yield object()

    monkeypatch.setattr(activities, "AgentKernel", Kernel)
    monkeypatch.setattr(activities, "PostgresSaver", NS(from_conn_string=saver))
    monkeypatch.setattr(activities, "verified_checkpoint_url", lambda url: url)
    monkeypatch.setattr(activities.activity, "heartbeat", lambda *_: None)
    ref = {"tenant_id": str(f.scope.tenant_id), "category_id": "",
           "actor_id": str(f.scope.requester_id), "requester_id": str(f.scope.requester_id),
           "subject_id": str(f.scope.run_id), "answer_ref": str(f.entry.id)}
    assert runner.advance(ref)["status"] == "needs_input"
    assert captured[0][0] == f.scope and isinstance(captured[0][1], VerifiedCategoryAdoption)
    for state in ("completed", "partial"):
        f.run.state = state
        assert runner.advance(ref)["status"] == state
        assert f.run.state == state and len(captured) == 1
    f.run.state = "waiting_input"
    f.entry.payload_digest = "f" * 64
    failed = runner.advance(ref)
    assert failed["status"] == "failed" and failed["error_code"] == "FORBIDDEN_SCOPE"
    assert len(captured) == 1 and f.run.state == "failed"
    assert f.run.error_code == "FORBIDDEN_SCOPE"
    assert [row.body for row in f.s.adopted if row.body.get("type") == "run_state"] == [{
        "type": "run_state", "status": "failed", "error_code": "FORBIDDEN_SCOPE",
    }]


def test_dispatch_reference_queries_only_metadata_using_actual_event_uuid(ledger, monkeypatch):
    f = ledger
    event = event_for(f)
    seen = []
    metadata = {"tenant_id": f.scope.tenant_id, "run_id": f.scope.run_id, "input_ref": f.entry.id}

    @contextmanager
    def transaction(engine, tenant_id):
        seen.append((engine, tenant_id))

        def execute(statement, parameters):
            seen.append((str(statement), parameters))
            return NS(mappings=lambda: NS(one_or_none=lambda: metadata))

        yield NS(execute=execute)

    monkeypatch.setattr(adoption, "tenant_session", transaction)
    engine = object()
    assert adoption.dispatch_reference(engine, event) == metadata
    from uuid import UUID

    assert seen == [(engine, f.scope.tenant_id), (
        "SELECT * FROM kernel_category_adoption_dispatch(:event)", {"event": UUID(event.event_id)},
    )]


@pytest.mark.parametrize("field", ["tenant_id", "run_id", "input_ref"])
def test_invalid_dispatch_reference_never_reaches_temporal_signal(ledger, monkeypatch, field):
    client = TemporalClient()
    meta = {"tenant_id": ledger.scope.tenant_id, "run_id": ledger.scope.run_id,
            "input_ref": ledger.entry.id}
    meta[field] = "not-a-uuid"
    monkeypatch.setattr(adoption, "dispatch_reference", lambda *_: meta)
    with pytest.raises(ValueError):
        asyncio.run(TemporalSender(client, dispatch_engine=object())(event_for(ledger)))
    assert not client.calls


def test_repeated_resolve_keeps_the_same_committed_input_and_receipt(ledger):
    first = resolve(ledger)
    second = resolve(ledger)
    assert first.envelope() == second.envelope()
    assert first.input_ref == str(ledger.entry.id)
    assert len(ledger.s.adopted) == 1
