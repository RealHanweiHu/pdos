"""Actual adoption/dispatch rows and PostgreSQL checkpoints; synthetic model turns."""

import asyncio
import os
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.category_adoption import dispatch_reference, resolve
from pdos_next.agent_kernel.graph import AgentKernel, VerifiedCategoryAdoption
from pdos_next.agent_kernel.host import BoundHost, KernelAdapters
from pdos_next.agent_kernel.models import AgentEvent, AgentInput, AgentRun
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.database import tenant_session
from pdos_next.dispatch.outbox import acknowledge, claim_events, delivery_unknown
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Outbox
from pdos_next.service import digest
from pdos_next.workflows.checkpoints import verified_checkpoint_url
from pdos_next.workflows.transport import TemporalSender
from tests.agent_kernel.test_category_candidate_transactions import adopted, personal_fixture


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


def test_category_wait_survives_postgres_checkpoint_and_new_host(setup, tmp_path):
    f = personal_fixture(setup, tmp_path)
    adapters = KernelAdapters(
        route_for=lambda *_: f.route,
        project_context=f.bootstrap.project_context,
        verify_result=lambda _, result, __: result,
        prepare_candidate=f.bootstrap.prepare_candidate,
        execute_command=lambda *_: pytest.fail("No direct write"),
        tool_registry=f.registry,
        skill_catalog=f.catalog,
    )

    class Host(BoundHost):
        def __init__(self, turns):
            super().__init__(f.store, adapters)
            self.turns, self.model_count = iter(turns), 0

        def model(self, *_args, **_kwargs):
            self.model_count += 1
            return next(self.turns)

    target = verified_checkpoint_url(
        os.environ["M2_TEST_CHECKPOINT_URL"].replace(
            "postgresql://",
            "postgresql+psycopg://",
            1,
        )
    )
    first_host = Host(
        [
            ModelTurn(
                calls=(
                    ToolCall(
                        id="synthetic-native",
                        name="category.create",
                        arguments=f.arguments,
                    ),
                ),
                ledger_call_id=f.model_id,
            )
        ]
    )
    with PostgresSaver.from_conn_string(target) as saver:
        first = AgentKernel(first_host, f.registry, catalog=f.catalog).execute(
            f.scope,
            goal="synthetic category",
            preload=["category_framing"],
            checkpointer=saver,
        )
        assert first["__interrupt__"] and first_host.model_count == 1
    receipt, _ = adopted(setup, f)
    witness = resolve(setup.engine, f.scope, receipt["result"]["adoption_input_ref"])
    restored = Host(
        [
            ModelTurn(
                structured={
                    "status": "completed",
                    "summary": "合成采用完成",
                    "result": {},
                    "questions": [],
                    "unfinished": [],
                }
            )
        ]
    )
    with PostgresSaver.from_conn_string(target) as saver:
        graph = AgentKernel(restored, f.registry, catalog=f.catalog)
        with pytest.raises(DomainError):
            graph.execute(f.scope, answer=witness.envelope(), checkpointer=saver)
        second = graph.execute(f.scope, answer=witness, checkpointer=saver)
        assert second["output"]["status"] == "completed" and restored.model_count == 1
        assert (
            graph.execute(f.scope, answer=witness, checkpointer=saver)["output"] == second["output"]
        )
        assert restored.model_count == 1
    with Session(setup.admin) as session:
        assert session.get(AgentRun, f.run.id).state == "completed"


@pytest.mark.parametrize("change", ["requester", "reserved", "immutable_input", "immutable_event"])
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
