"""Actual adoption/dispatch rows and PostgreSQL checkpoints; synthetic model turns."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent.kernel.category_adoption import dispatch_reference, resolve
from pdos_next.agent.kernel.graph import VerifiedCategoryAdoption
from pdos_next.agent.kernel.models import AgentEvent, AgentInput
from pdos_next.core.database import tenant_session
from pdos_next.core.dispatch.outbox import acknowledge, claim_events, delivery_unknown
from pdos_next.core.models import Grant, Outbox
from pdos_next.core.service import digest
from pdos_next.errors import DomainError
from pdos_next.workflows.transport import TemporalSender
from tests.agent.kernel.test_category_candidate_transactions import adopted, personal_fixture
from tests.confirmation_fixture import confirmation_clock  # noqa: F401


def test_adoption_resolves_without_agent_grant_and_dispatches_same_reference(setup, tmp_path):
    f = personal_fixture(setup, tmp_path)
    receipt, _ = adopted(setup, f)
    identity = receipt["result"]["adoption_input_ref"]
    witness = resolve(setup.engine, f.scope, identity)
    assert isinstance(witness, VerifiedCategoryAdoption)
    assert witness.category_adoption["category_id"] == receipt["subject_id"]
    events = claim_events(setup.dispatch, setup.tenant)
    assert len(events) == 1
    reference = dispatch_reference(setup.dispatch, events[0])
    assert reference == {"tenant_id": setup.tenant, "run_id": f.run.id, "input_ref": UUID(identity)}
    assert (
        dispatch_reference(setup.dispatch, replace(events[0], tenant_id=str(setup.other_tenant)))
        is None
    )
    with pytest.raises(DBAPIError):
        dispatch_reference(setup.engine, events[0])
    signals = []

    class Client:
        def get_workflow_handle(self, key):
            assert key.endswith(str(f.run.id))

            async def signal(_, input_ref):
                signals.append(input_ref)
                if len(signals) == 1:
                    raise RuntimeError("synthetic unknown delivery")

            return SimpleNamespace(signal=signal)

    sender = TemporalSender(Client(), dispatch_engine=setup.dispatch)
    with pytest.raises(RuntimeError, match="unknown delivery"):
        asyncio.run(sender(events[0]))
    assert delivery_unknown(setup.dispatch, events[0])
    assert asyncio.run(sender(events[0])).endswith(str(f.run.id))
    assert acknowledge(setup.dispatch, events[0], workflow_id="synthetic-category-workflow")
    assert signals == [identity, identity]
    with Session(setup.admin) as session:
        assert session.get(Outbox, UUID(events[0].event_id)).delivered_at
        assert (
            session.scalar(
                select(Grant.id).where(
                    Grant.category_id == UUID(receipt["subject_id"]),
                    Grant.principal_id == setup.agent,
                )
            )
            is None
        )


@pytest.mark.parametrize("change", ["requester", "reserved", "immutable_input", "immutable_event"])
@pytest.mark.usefixtures("confirmation_clock")
def test_sql_adoption_and_input_kinship_cannot_be_forged(setup, tmp_path, change):
    f = personal_fixture(setup, tmp_path, sources=False)
    if change in {"requester", "reserved"}:
        with f.store.transaction(f.scope, lock=True) as (_, run):
            run.state = "waiting_input"
        person = setup.peer if change == "requester" else setup.human
        answers = (
            {"type": "category_adoption", "receipt_id": str(uuid4())}
            if change == "reserved"
            else {"q": "answer"}
        )
        with pytest.raises(DBAPIError):
            with tenant_session(setup.engine, setup.tenant, actor_id=person) as session:
                session.add(
                    AgentInput(
                        tenant_id=setup.tenant,
                        run_id=f.run.id,
                        requester_id=person,
                        idempotency_key=str(uuid4()),
                        answers=answers,
                        payload_digest=digest(answers),
                    )
                )
        return
    receipt, _ = adopted(setup, f)
    with pytest.raises(DBAPIError):
        with tenant_session(setup.engine, setup.tenant, actor_id=setup.human) as session:
            if change == "immutable_input":
                row = session.get(AgentInput, UUID(receipt["result"]["adoption_input_ref"]))
                row.answers = {"forged": True}
            else:
                row = session.scalar(
                    select(AgentEvent).where(
                        AgentEvent.run_id == f.run.id,
                        AgentEvent.body["type"].astext == "category_adopted",
                    )
                )
                row.body = {"type": "category_adopted", "receipt_id": str(uuid4())}
            session.flush()


def test_terminal_candidate_not_signalled_and_receipt_authority_loss_rejects_recovery(
    setup, tmp_path
):
    f = personal_fixture(setup, tmp_path)
    with f.store.transaction(f.scope, lock=True) as (_, run):
        run.state = "completed"
    receipt, _ = adopted(setup, f)
    assert "continuation_state" not in receipt
    events = claim_events(setup.dispatch, setup.tenant)
    assert dispatch_reference(setup.dispatch, events[0]) is None
    with Session(setup.admin) as session, session.begin():
        session.execute(
            text("DELETE FROM grants WHERE tenant_id=:t AND category_id=:c"),
            {"t": setup.tenant, "c": UUID(receipt["subject_id"])},
        )
    with pytest.raises(DomainError):
        resolve(setup.engine, f.scope, receipt["result"]["adoption_input_ref"])
