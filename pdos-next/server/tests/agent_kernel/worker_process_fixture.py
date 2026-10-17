"""Offline provider ports around the unmodified production Worker entry point."""

import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path
from uuid import UUID

from pdos_next.agent_kernel.bootstrap import Bootstrap, RuntimePorts
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.database import configured_engines
from pdos_next.model_configuration.ports import SecretBinding
from pdos_next.providers.types import ProviderUsage
from pdos_next.workflows.worker import main
from tests.agent_kernel.test_model_configuration_transactions import SyntheticSecrets


class OfflineClient:
    def __init__(self, arguments):
        self.arguments = arguments

    def turn(self, route, **kwargs):
        from pdos_agent_runtime.graph import in_registered_agent_graph

        assert in_registered_agent_graph() and route.version == "synthetic@1"
        messages = kwargs["messages"]
        answered = any(
            row.get("role") == "user" and '"answers"' in str(row.get("content"))
            for row in messages
        )
        tool_returned = any(row.get("role") == "tool" for row in messages)
        context = json.loads(messages[0]["content"])["context"]
        conversation = context.get("conversation")
        if conversation:
            assert conversation["root_goal"] == "Synthetic actual process recovery"
            assert len(conversation["turns"]) == 1
            prior = conversation["turns"][0]
            assert prior["status"] == "completed"
            assert prior["historical_outcome"]["summary"] == "Synthetic recovered domain candidate"
            assert not tool_returned  # Old tool messages are not inherited by the follow-up.
            phase = "followup_final" if answered else "followup_question"
            result = ModelTurn(
                usage=ProviderUsage(20, 10),
                structured={
                    "status": "completed" if answered else "needs_input",
                    "summary": "Synthetic continued scope" if answered else "Confirm next scope",
                    "result": {},
                    "questions": [] if answered else [
                        {"id": "followup_scope", "question": "Next scope?", "why": "Continuation"},
                    ],
                },
            )
        elif not answered:
            phase = "question"
            result = ModelTurn(
                usage=ProviderUsage(20, 10),
                structured={
                    "status": "needs_input",
                    "summary": "Synthetic scope confirmation",
                    "questions": [{"id": "region", "question": "Region?", "why": "Scope"}],
                },
            )
        elif not tool_returned:
            phase = "claim_candidate"
            result = ModelTurn(
                usage=ProviderUsage(20, 10),
                calls=(ToolCall(
                    id="process-claim", name="evidence.claim.record", arguments=self.arguments
                ),),
            )
        else:
            phase = "final"
            result = ModelTurn(
                usage=ProviderUsage(20, 10),
                structured={
                    "status": "completed", "summary": "Synthetic recovered domain candidate",
                    "result": {},
                },
            )
        print(json.dumps({"event": "offline_model_turn", "phase": phase}), flush=True)
        return result

    def close(self):
        pass


if __name__ == "__main__":
    fixture = json.loads(Path(os.environ["PDOS_WORKER_FIXTURE"]).read_text())
    secrets = SyntheticSecrets(UUID(fixture["tenant_id"]))
    secrets.binding = SecretBinding(
        UUID(fixture["tenant_id"]), UUID(fixture["secret_reference"]),
        UUID(fixture["secret_version"]), "openai-compatible", True,
    )
    engine, auth = configured_engines()
    ports = RuntimePorts(secrets=secrets, provider_client=OfflineClient(fixture["arguments"]))
    adapters = replace(
        Bootstrap(engine, ports=ports).adapters(),
        provider_for=lambda *_: "synthetic-offline-provider", cost_required=False,
        preload=lambda _: ("public_research",),
    )
    try:
        asyncio.run(main(agent_kernel_adapters=adapters))
    finally:
        engine.dispose()
        auth.dispose()
