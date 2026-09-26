"""Freeze actual restricted project observations without invoking a provider."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import Engine

from app.ai.context_builder import RunContextBuilder
from app.ai.context_manifests import bind_bundle
from app.ai.gateway import GatewayInvocation
from app.ai.observations import AgentObservations, context_receipt_body
from app.ai.run_store import ClaimedAgentRun, RestrictedAgentRunStore
from app.ai.tools import AgentReadTools
from tests.test_model_gateway import RiskOutput, invocation


def freeze_project_invocation(
    agent: Engine,
    store: RestrictedAgentRunStore,
    claim: ClaimedAgentRun,
    *,
    tenant_id: UUID,
    project_id: UUID,
    output_type: type[BaseModel] = RiskOutput,
) -> GatewayInvocation:
    port = AgentObservations(agent, store)
    bind_bundle(port, claim.values["agent_key"], loop=False)
    with agent.begin() as connection:
        store.bind(connection)
        context = RunContextBuilder().build(
            connection, run=claim.values, built_at=datetime.now(UTC), projection_only=True
        )
    model_call_id = uuid4()
    call_key = f"budget-fixture.{model_call_id}"
    arguments: dict[str, object] = {"project_id": str(context.project_id)}
    intent = port.prepare(
        context=context, call_key=call_key, tool_key="get_project_context", arguments=arguments
    )
    port.dispatch(intent)
    output = AgentReadTools(agent, run_context=context, run_store=store).get_project_context(
        project_id=context.project_id
    )
    observation = port.append(
        context=context,
        call_key=call_key,
        tool_key="get_project_context",
        arguments=arguments,
        output=output.model_dump(mode="json"),
    )
    inv = invocation(
        tenant_id,
        project_id=project_id,
        run_id=claim.id,
        model_call_id=model_call_id,
        context={"project": output.project},
    )
    receipt = port.freeze(
        model_call_id,
        context_receipt_body(
            context=inv.context,
            prompt_version=inv.prompt_version,
            system_prompt=inv.system_prompt,
            instruction=inv.instruction,
            output_type=output_type,
        ),
        (observation.id,),
    )
    return inv.model_copy(update={"context_receipt_id": receipt})
