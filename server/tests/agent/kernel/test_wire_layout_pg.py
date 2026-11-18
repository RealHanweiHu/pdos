"""The gateway sends message layout 2 only for a prompt version that describes it.

Real ledger and run rows; the provider client is a stub.
"""

import json

from pdos_agent_runtime.graph import registered_graph_context

from pdos_next.agent.kernel.gateway import AgentGateway
from pdos_next.agent.kernel.prompts import PromptCatalog
from pdos_next.agent.kernel.types import ModelTurn
from pdos_next.agent.kernel.wire_layout import OPENING_REPLY
from pdos_next.providers.types import ProviderUsage
from tests.agent.kernel.test_gateway import Client, configured_route
from tests.agent.kernel.test_transactions import run

SCHEMA = {"type": "object"}


def gateway_for(store, seen):
    def reply(kwargs):
        seen.append(kwargs["messages"])
        return ModelTurn("done", usage=ProviderUsage(40, 3, 20), structured={"ok": True})

    client = Client(reply)
    return client, AgentGateway(store, cost_required=False,
                                route_for=lambda _: configured_route(), client=client)


def envelope(goal):
    return [{"role": "user", "content": json.dumps({"goal": goal, "context": {}},
                                                   ensure_ascii=False)}]


def test_layout_2_is_sent_and_recorded_for_the_draft_prompt_only(setup):
    system, identity = PromptCatalog().version("1.2.0-layout-draft").compose([])
    store, scope = run(setup)
    seen = []
    client, gateway = gateway_for(store, seen)
    messages = envelope("合成题：核对缺口")
    with registered_graph_context("xiaopai"):
        first = gateway.turn(scope, system=system, messages=messages, tools=[],
                             output_schema=SCHEMA, prompt_identity=identity)
        again = gateway.turn(scope, system=system, messages=messages, tools=[],
                             output_schema=SCHEMA, prompt_identity=identity)
    sent = seen[0]
    assert [message["role"] for message in sent] == ["user", "assistant", "user"]
    assert sent[1] == {"role": "assistant", "content": OPENING_REPLY}
    assert json.loads(sent[0]["content"])["type"] == "skill_body"
    wire = json.loads(sent[2]["content"])
    assert wire["type"] == "run_envelope" and list(wire)[-1] == "goal"
    assert wire["goal"] == "合成题：核对缺口"
    # The same admitted messages are the same ledger call: replayed, not sent twice.
    assert client.calls == 1 and again.ledger_call_id == first.ledger_call_id
    assert messages == envelope("合成题：核对缺口")  # The caller's messages are untouched.


def test_the_active_prompt_still_sends_the_messages_as_given(setup):
    system, identity = PromptCatalog().active.compose([])
    store, scope = run(setup)
    seen = []
    _, gateway = gateway_for(store, seen)
    messages = envelope("合成题：核对缺口")
    with registered_graph_context("xiaopai"):
        gateway.turn(scope, system=system, messages=messages, tools=[],
                     output_schema=SCHEMA, prompt_identity=identity)
    assert seen[0] == messages
