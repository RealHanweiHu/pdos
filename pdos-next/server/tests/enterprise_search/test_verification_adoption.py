"""Native adoption retains fixed commands and derives provenance from receipts."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from pdos_next.agent_kernel.models import AgentRun
from pdos_next.contracts import Command
from pdos_next.enterprise_search import verification_adoption as adoption
from pdos_next.errors import DomainError
from pdos_next.service import Context
from tests.enterprise_search.test_verification_candidates import fixture


def sql(statement):
    return str(statement.compile(dialect=postgresql.dialect(),
                                 compile_kwargs={"literal_binds": True}))


@pytest.fixture
def case(monkeypatch):
    run, _selection, command, preparation, receipt = fixture()
    ctx = Context(run.tenant_id, run.requester_id, run.requester_id, category_id=run.category_id)
    event = SimpleNamespace(id=uuid4(), run_id=run.id)
    proof = {"digest": "server-frozen-proof"}
    view = {"command": command.model_dump(mode="json"), "source_proof": proof}
    calls = []

    class Session:
        events = [event]
        pairs = [(receipt, event)]

        def scalars(self, statement):
            compiled = sql(statement)
            assert str(ctx.tenant_id) in compiled
            assert str(command.command_id) in compiled
            assert "verification_candidate" in compiled
            return SimpleNamespace(all=lambda: self.events)

        def execute(self, statement):
            compiled = sql(statement)
            assert str(ctx.tenant_id) in compiled and str(preparation.id) in compiled
            assert str(preparation.product_id) in compiled and str(ctx.category_id) in compiled
            assert "verification_preparation" in compiled
            assert "verification.preparation.record" in compiled
            assert "subject_revision = 1" in compiled
            assert "CAST(action_receipts.command_id AS TEXT)" in compiled
            return SimpleNamespace(all=lambda: self.pairs)

        def get(self, model, identity):
            assert model is AgentRun and identity == run.id
            return run

    session = Session()

    def read(actual_session, actual_ctx, run_id, event_id):
        assert actual_session is session and actual_ctx is ctx
        assert run_id == run.id and event_id == event.id
        calls.append("bridge.read")
        return deepcopy(view)

    def recheck(actual_session, actual_ctx, actual_run, frozen, *, preparation_id):
        assert actual_session is session and actual_ctx is ctx and actual_run is run
        assert frozen == proof and preparation_id == preparation.id
        calls.append("source.recheck")
        return {"target": {"preparation_id": str(preparation.id),
                           "preparation_revision": preparation.revision,
                           "preparation_sha256": preparation.snapshot_sha256}}

    monkeypatch.setattr(adoption.bridge, "read", read)
    monkeypatch.setattr(adoption, "recheck", recheck)
    return SimpleNamespace(run=run, ctx=ctx, command=command, preparation=preparation,
                           receipt=receipt, event=event, view=view, calls=calls, session=session)


def test_native_t1_may_add_only_its_confirmation_token(case):
    raw = case.command.model_dump(mode="json")
    raw["payload"]["confirmation_token"] = "native-confirmation-token-value"
    confirmed = Command.model_validate(raw)
    adoption.recheck_preparation(case.session, case.ctx, confirmed)
    assert case.calls == ["bridge.read"]
    assert case.command.payload.get("confirmation_token") is None


@pytest.mark.parametrize("field,value", [
    ("command_id", str(uuid4())), ("idempotency_key", "changed-command-key"),
    ("expected_revision", 999), ("product_id", str(uuid4())),
    ("category_id", str(uuid4())), ("source_read_set", []),
    ("operation", "verification.request.create"),
    ("payload.reason", "替换原候选内容"), ("payload.build_id", str(uuid4())),
    ("payload.items", [{"id": "changed", "feature": "changed", "sample_count": 1}]),
])
def test_candidate_envelope_and_business_inputs_are_fixed(case, field, value):
    raw = case.command.model_dump(mode="json")
    target = raw
    *parents, key = field.split(".")
    for parent in parents:
        target = target[parent]
    target[key] = value
    with pytest.raises(DomainError, match="复验办理"):
        adoption._same_command(Command.model_validate(raw), case.command)


def test_native_preview_does_not_accept_a_changed_frozen_candidate(case):
    case.view["command"]["payload"]["title"] = "changed"
    with pytest.raises(DomainError):
        adoption.recheck_preparation(case.session, case.ctx, case.command)
    assert case.calls == ["bridge.read"]


def test_manual_preparation_and_request_keep_native_path(case):
    case.session.events = []
    case.session.pairs = []
    adoption.recheck_preparation(case.session, case.ctx, case.command)
    adoption.recheck_request(case.session, case.ctx, case.preparation)
    assert not case.calls


def test_request_uses_actual_receipt_and_parent_read_then_rechecks_saved_preparation(case):
    adoption.recheck_request(case.session, case.ctx, case.preparation)
    assert case.calls == ["bridge.read", "source.recheck"]


@pytest.mark.parametrize("field,value", [
    ("command_id", uuid4()), ("subject_id", uuid4()), ("subject_revision", 8),
    ("requester_id", uuid4()), ("operation", "verification.request.create"),
])
def test_receipt_binding_cannot_be_replaced(case, field, value):
    setattr(case.receipt, field, value)
    with pytest.raises(DomainError):
        adoption.recheck_request(case.session, case.ctx, case.preparation)
    assert case.calls == ["bridge.read"]


def test_request_propagates_current_auxiliary_source_revocation(case, monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise DomainError("SOURCE_UNAVAILABLE", "辅助依据已撤回。")

    monkeypatch.setattr(adoption, "recheck", unavailable)
    with pytest.raises(DomainError) as error:
        adoption.recheck_request(case.session, case.ctx, case.preparation)
    assert error.value.reason == "SOURCE_UNAVAILABLE"


def test_request_rejects_a_different_preparation_after_recheck(case, monkeypatch):
    monkeypatch.setattr(adoption, "recheck", lambda *_args, **_kwargs: {"target": {
        "preparation_id": str(uuid4()), "preparation_revision": case.preparation.revision,
        "preparation_sha256": case.preparation.snapshot_sha256,
    }})
    with pytest.raises(DomainError):
        adoption.recheck_request(case.session, case.ctx, case.preparation)


def test_ambiguous_server_lineage_is_rejected(case):
    case.session.events *= 2
    with pytest.raises(DomainError):
        adoption.recheck_preparation(case.session, case.ctx, case.command)
    case.session.pairs *= 2
    with pytest.raises(DomainError):
        adoption.recheck_request(case.session, case.ctx, case.preparation)
    assert not case.calls
