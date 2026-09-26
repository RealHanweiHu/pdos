"""Current knowledge access is checked for every admitted event context."""

from collections.abc import Sequence
from uuid import UUID

import pytest

from app.ai import runtime_factory
from app.ai.executor import AgentLoopStep, GatewayAgentModelInvoker
from app.ai.gateway import GatewayInvocation, GatewayResult
from app.ai.model_budget import InputTokenMeter
from app.ai.model_catalog import ResolvedModelRoute
from app.ai.observations import AgentObservations
from app.ai.provider_adapters import ChatMessage
from app.ai.tools import AgentReadTools, ToolPage
from app.contracts.runtime_records import ContextManifest
from app.db.schema import tables
from tests.test_agent_database_security import FakeEmbeddingGateway, seed_verified_memory
from tests.test_agent_database_security import (
    secured_agent_database_url as secured_agent_database_url,
)
from tests.test_agent_tool_loop import LoopSetup
from tests.test_agent_tool_loop import loop_setup as loop_setup
from tests.test_event_budget_adoption import event_scope as event_scope
from tests.test_event_budget_adoption import scope_id
from tests.test_model_budget_controller import rows


@pytest.mark.parametrize(
    "when", ["before_first_model", "between_models", "after_manifest", "before_finding"]
)
def test_revoked_knowledge_cannot_be_used_by_next_model_attempt(
    loop_setup: LoopSetup, monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    owner, _, _, ids, env, calls, _ = loop_setup
    memory = seed_verified_memory(
        owner,
        tenant_id=scope_id(ids, "tenant_a"),
        project_id=scope_id(ids, "project_a"),
        suffix="a-manifest",
    )

    def revoke() -> None:
        with owner.begin() as c:
            c.execute(
                tables.memories.update()
                .where(tables.memories.c.id == memory)
                .values(status="draft", verified_by_user_id=None, verified_at=None)
            )

    with runtime_factory.configured_agent_runtime(env) as runtime:
        runtime.executor._embedding_gateway = FakeEmbeddingGateway()
        invoker = runtime.executor._model_invoker
        assert isinstance(invoker, GatewayAgentModelInvoker)
        controller = invoker._gateway._budget_controller
        assert controller is not None
        meters = controller._meters
        meter = next(iter(meters.values())).meter
        count = meter.count
        measured: list[int] = []

        def measure(
            self: InputTokenMeter, route: ResolvedModelRoute, messages: Sequence[ChatMessage]
        ) -> int:
            measured.append(1)
            return count(route, messages)

        monkeypatch.setattr(type(meter), "count", measure)
        if when == "before_first_model":
            original = AgentReadTools.search_memory

            def read(
                self: AgentReadTools,
                *,
                project_id: UUID,
                query: str,
                offset: int = 0,
                limit: int = 20,
            ) -> ToolPage:
                result = original(
                    self, project_id=project_id, query=query, offset=offset, limit=limit
                )
                revoke()
                return result

            monkeypatch.setattr(AgentReadTools, "search_memory", read)
        elif when == "after_manifest":
            from app.ai import context_manifests

            freeze = context_manifests.freeze_manifest

            def freeze_then_revoke(
                port: AgentObservations,
                *,
                receipt_id: UUID,
                attempt_id: UUID,
                qualification: dict[str, object],
                removed_paths: tuple[str, ...],
            ) -> ContextManifest | None:
                result = freeze(
                    port,
                    receipt_id=receipt_id,
                    attempt_id=attempt_id,
                    qualification=qualification,
                    removed_paths=removed_paths,
                )
                revoke()
                return result

            monkeypatch.setattr(context_manifests, "freeze_manifest", freeze_then_revoke)
        else:
            original_decide = invoker.decide

            def decide(invocation: GatewayInvocation) -> GatewayResult[AgentLoopStep]:
                result = original_decide(invocation)
                if when == "between_models" or len(calls) == 2:
                    revoke()
                return result

            monkeypatch.setattr(runtime.executor._model_invoker, "decide", decide)
        result = runtime.executor.execute_next()
    prefix = "BUDGET" if when == "after_manifest" else "AGENT"
    assert result.error_code == prefix + "_MANIFEST_SOURCE_ACCESS_CHANGED", result
    assert (
        len(calls)
        == {"before_first_model": 0, "between_models": 1, "after_manifest": 0, "before_finding": 2}[
            when
        ]
    )
    assert len(rows(owner, tables.agent_context_manifests)) == len(calls) + (
        when == "after_manifest"
    )
    assert rows(owner, tables.findings) == []
    cancelled = [j for j in rows(owner) if j["reservation_status"] == "cancelled_before_dispatch"]
    assert len(cancelled) == (1 if when == "after_manifest" else 0)
    assert (
        len(measured)
        == {"before_first_model": 0, "between_models": 1, "after_manifest": 1, "before_finding": 2}[
            when
        ]
    )
    assert all(j["held_tokens"] == 0 for j in cancelled)
