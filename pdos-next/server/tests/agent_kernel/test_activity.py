import os
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.activities import KernelActivities, configure_agent_kernel
from pdos_next.agent_kernel.host import KernelAdapters
from pdos_next.agent_kernel.models import AgentEvent, AgentRun
from pdos_next.agent_kernel.persistence import record_answers
from pdos_next.agent_kernel.types import ModelTurn
from pdos_next.models import Grant, now
from pdos_next.providers.types import ProviderError, ProviderUsage
from tests.agent_kernel.test_gateway import configured_route
from tests.agent_kernel.test_transactions import human_session, run


def test_activity_restarts_with_committed_answer_and_persistent_graph_checkpoint(
    setup, monkeypatch
):
    from temporalio import activity

    monkeypatch.setattr(activity, "heartbeat", lambda *_: None)
    store, bound = run(setup, token_limit=500000)

    class Client:
        def __init__(self):
            self.calls = []

        def turn(self, route, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return ModelTurn(
                    usage=ProviderUsage(20, 10),
                    structured={
                        "status": "needs_input",
                        "summary": "Region required",
                        "result": {},
                        "questions": [
                            {
                                "id": "region",
                                "question": "Region?",
                                "why": "Determines research scope",
                                "options": [{"value": "US", "label": "United States"}],
                            }
                        ],
                        "unfinished": [],
                    },
                )
            return ModelTurn(
                usage=ProviderUsage(22, 10),
                structured={
                    "status": "completed",
                    "summary": "Synthetic verified",
                    "result": {"region": "US"},
                    "questions": [],
                    "unfinished": [],
                },
            )

        def close(self):
            pass

    client = Client()
    adapters = KernelAdapters(
        route_for=lambda _: configured_route(),
        project_context=lambda _, goal, __: {"goal": goal, "sources": []},
        verify_result=lambda _, result, tools: result,
        prepare_candidate=lambda *_: None,
        execute_command=lambda *_: None,
        provider_client=client,
        cost_required=False,
    )
    monkeypatch.setattr(setup.engine, "_pdos_agent_kernel_adapters", None, raising=False)
    configure_agent_kernel(setup.engine, adapters)
    reference = {
        "tenant_id": str(setup.tenant),
        "category_id": str(setup.category),
        "actor_id": str(setup.human),
        "requester_id": str(setup.human),
        "subject_id": str(bound.run_id),
    }
    checkpoint = os.environ["M2_TEST_CHECKPOINT_URL"].replace(
        "postgresql://", "postgresql+psycopg://", 1
    )
    first = KernelActivities(setup.engine, checkpoint_url=checkpoint).advance(reference)
    assert first["status"] == "needs_input" and len(client.calls) == 1
    with human_session(setup) as s:
        answer_id = record_answers(
            s,
            setup.ctx,
            bound.run_id,
            answers={"region": "US"},
            idempotency_key="same committed answer",
        ).id
    second = KernelActivities(setup.engine, checkpoint_url=checkpoint).advance(
        {**reference, "answer_ref": str(answer_id)}
    )
    assert second["status"] == "completed" and len(client.calls) == 2
    assert client.calls[0]["system"] == client.calls[1]["system"]
    with store.transaction(bound) as (s, row):
        assert (
            row.result["result"] == {"region": "US"}
            and row.held_tokens == 0
            and row.used_tokens == 62
        )
        assert s.scalar(select(AgentEvent.id).where(AgentEvent.run_id == bound.run_id))
    # A completed Activity replay returns prior status without another provider attempt.
    assert (
        KernelActivities(setup.engine, checkpoint_url=checkpoint).advance(reference)["status"]
        == "completed"
    )
    assert len(client.calls) == 2 and UUID(first["run_id"]) == bound.run_id


@pytest.mark.parametrize("native_cancellation", [False, True])
def test_activity_revocation_during_provider_attempt_has_visible_terminal_failure(
    setup, monkeypatch, native_cancellation
):
    from temporalio import activity

    from tests.agent_kernel.test_gateway import Client

    monkeypatch.setattr(activity, "heartbeat", lambda *_: None)
    _, bound = run(setup, token_limit=500000)

    def revoke(_):
        with Session(setup.admin) as s, s.begin():
            grant = s.scalar(select(Grant).where(Grant.principal_id == setup.agent))
            grant.expires_at = now() - timedelta(seconds=1)
        if native_cancellation:
            assert _["cancelled"]()
            raise ProviderError("MODEL_CANCELLED", unknown=True)
        return ModelTurn(usage=ProviderUsage(2, 2), structured={"status": "completed"})

    client = Client(revoke)
    monkeypatch.setattr(setup.engine, "_pdos_agent_kernel_adapters", None, raising=False)
    configure_agent_kernel(
        setup.engine,
        KernelAdapters(
            route_for=lambda _: configured_route(),
            project_context=lambda _, goal, __: {"goal": goal, "sources": []},
            verify_result=lambda _, output, __: output,
            prepare_candidate=lambda *_: None,
            execute_command=lambda *_: None,
            provider_client=client,
            cost_required=False,
        ),
    )
    checkpoint = os.environ["M2_TEST_CHECKPOINT_URL"].replace(
        "postgresql://", "postgresql+psycopg://", 1
    )
    result = KernelActivities(
        setup.engine, checkpoint_url=checkpoint, technical_engine=setup.dispatch
    ).advance(
        {
            "tenant_id": str(setup.tenant),
            "category_id": str(setup.category),
            "actor_id": str(setup.human),
            "requester_id": str(setup.human),
            "subject_id": str(bound.run_id),
        }
    )
    assert result["status"] == "failed" and client.calls == 1
    with Session(setup.admin) as s:
        row = s.get(AgentRun, bound.run_id)
        assert row.state == "failed" and row.error_code == "FORBIDDEN_SCOPE"
        assert row.held_tokens == 0 and row.result is None
