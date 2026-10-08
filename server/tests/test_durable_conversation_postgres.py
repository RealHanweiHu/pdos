"""Actual API capability, gateway, leases and receipts through real local Temporal.

Only provider HTTP/qualification fixture is synthetic; it grants no real qualification.
"""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import UUID

import pytest
from pdos_agent_runtime.activity import AgentActivities
from pdos_agent_runtime.graph import in_agent_graph
from pdos_agent_runtime.workflow import AgentWork
from sqlalchemy import select
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from app.ai import application_gateway, provider_streaming
from app.ai.budget_adoption import METER_DIGEST_KEY, METER_PATH_KEY
from app.ai.conversation_reply import ConversationReplies, identity
from app.ai.durable_worker import handlers
from app.auth.repository import AuthRepository
from app.db.schema import tables
from tests import test_application_budget_factory as factory
from tests.test_application_budget_factory import factory_setup as factory_setup
from tests.test_durable_runtime_postgres import owned_store
from tests.test_input_metering import publication
from tests.test_model_budget_controller import response
from tests.test_product_conversations_api import candidate as candidate
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database
from tests.test_xiaopai_conversation_reply_api import save


def test_original_capability_uses_temporal_graph_current_authority_and_original_receipts(
    candidate, factory_setup, monkeypatch, tmp_path
):
    c = candidate
    monkeypatch.setattr(provider_streaming, "enabled", lambda: False)

    def generated():
        assert in_agent_graph()
        return response('{"answer":"合成执行链结果","citation_ids":[]}')

    monkeypatch.setattr(factory, "response", generated)
    conversation = c.create("personal")
    message = save(c, conversation, "验证共同执行框架")
    context = AuthRepository(c.scope.engine).find_user_context(c.scope.owner_id)
    assert context is not None

    async def scenario():
        store = owned_store()
        async with await WorkflowEnvironment.start_local(
            namespace="agent-convergence-domain",
            dev_server_existing_path=os.environ["PDOS_TEMPORAL_TEST_BINARY"],
            dev_server_database_filename=str(tmp_path / "temporal.sqlite"),
        ) as env:
            environment, calls, _ = factory_setup
            (tmp_path / "durable-meter").mkdir()
            meter_path, _, meter_digest = publication(
                tmp_path / "durable-meter", qualified_input_limit=4096
            )
            environment = {
                **environment,
                METER_PATH_KEY: str(meter_path),
                METER_DIGEST_KEY: meter_digest,
                "PDOS_AGENT_RUNTIME_DATABASE_URL": store.url,
                "PDOS_AGENT_RUNTIME_DB_MARKER": store.marker,
                "PDOS_TEMPORAL_ADDRESS": env.client.service_client.config.target_host,
                "PDOS_TEMPORAL_NAMESPACE": env.client.namespace,
            }
            monkeypatch.setenv("PDOS_AGENT_RUNTIME_MODE", "durable-test")
            real_factory = application_gateway.configured_application_gateway

            @contextmanager
            def host_factory(engine, **kwargs):
                with real_factory(engine, environment, **kwargs) as gateway:
                    yield gateway

            monkeypatch.setattr(application_gateway, "configured_application_gateway", host_factory)
            activities = AgentActivities(store, handlers(c.scope.engine), checkpoint_url=store.url)
            with ThreadPoolExecutor(max_workers=2) as pool:
                async with Worker(
                    env.client,
                    task_queue="pdos-agent-v1",
                    workflows=[AgentWork],
                    activities=[activities.execute],
                    activity_executor=pool,
                ):
                    with host_factory(c.scope.engine) as gateway:
                        assert gateway.durable_runtime is not None and gateway.require_agent_graph
                        replies = ConversationReplies(c.scope.engine, gateway)
                        events = []
                        arguments = (
                            context,
                            UUID(conversation["id"]),
                            UUID(message["id"]),
                            events.append,
                        )
                        result = await asyncio.wait_for(
                            asyncio.to_thread(replies.answer, *arguments), 30
                        )
                        assert result["status"] == "answered", result.get("error_code")
                        assert result["answer"] == "合成执行链结果"
                        assert events and len(calls) == 1
                        replay = await asyncio.to_thread(replies.answer, *arguments)
                        assert replay == result and len(calls) == 1
                        with c.scope.engine.connect() as connection:
                            run_id = identity(UUID(message["id"]))
                            assert connection.execute(
                                select(tables.application_authorizations.c.id).where(
                                    tables.application_authorizations.c.run_id == run_id
                                )
                            ).first()
                            assert connection.execute(
                                select(tables.budget_journal.c.id).where(
                                    tables.budget_journal.c.run_id == run_id
                                )
                            ).first()
                        with store.connection() as connection:
                            row = connection.execute(
                                "SELECT * FROM agent_runtime_jobs WHERE tenant_id=%s",
                                (str(context.tenant.id),),
                            ).fetchone()
                        assert row["state"] == "completed"
                        history = await env.client.get_workflow_handle(
                            f"pdos-agent:pdos:{row['id']}"
                        ).fetch_history()
                        assert "验证共同执行框架" not in history.to_json()
                        assert "合成执行链结果" not in history.to_json()
                        with c.scope.engine.begin() as connection:
                            connection.execute(
                                tables.users.update()
                                .where(tables.users.c.id == context.user.id)
                                .values(is_active=False)
                            )
                        with pytest.raises(PermissionError):
                            await asyncio.to_thread(replies.answer, *arguments)
                        assert len(calls) == 1

    asyncio.run(scenario())
