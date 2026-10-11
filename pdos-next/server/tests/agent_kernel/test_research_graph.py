import asyncio
import json
from contextlib import nullcontext

from langgraph.checkpoint.memory import InMemorySaver

from pdos_next.agent_kernel.research_graph import ResearchGraph
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.research import ResearchTask
from tests.agent_kernel.research.test_research import scope, service
from tests.agent_kernel.test_graph import Host


def test_read_only_child_uses_registered_graph_and_returns_exact_quoted_ledger():
    class ResearchHost(Host):
        def __init__(self):
            super().__init__([])
            self.calls = 0

        def model(self, bound, **kwargs):
            from pdos_agent_runtime.graph import in_agent_graph

            assert in_agent_graph() and bound.isolation == "research"
            assert {tool["name"] for tool in kwargs["tools"]} == {
                "research.search",
                "research.read",
            }
            self.calls += 1
            messages = kwargs["messages"]
            if self.calls == 1:
                return ModelTurn(
                    calls=(
                        ToolCall(
                            id="search",
                            name="research.search",
                            arguments={"query": "pump pressure"},
                        ),
                    )
                )
            previous = json.loads(messages[-1]["content"])
            if self.calls == 2:
                return ModelTurn(
                    calls=(
                        ToolCall(
                            id="read",
                            name="research.read",
                            arguments={"url": previous["hits"][0]["url"]},
                        ),
                    )
                )
            row = {
                "brand": "Maker",
                "model": "P1",
                "free_key": "pressure",
                "value": 20,
                "unit": "psi",
                "quote": "Pressure: 20 psi",
                "snapshot_id": previous["snapshot_id"],
                "locator": previous["locator"],
            }
            return ModelTurn(
                structured={
                    "status": "completed",
                    "summary": "Synthetic read",
                    "result": {"rows": [row]},
                    "questions": [],
                    "unfinished": [],
                }
            )

    host = ResearchHost()
    memory = InMemorySaver()
    research = ResearchGraph(host, checkpointer_factory=lambda: nullcontext(memory))
    result = asyncio.run(
        service().fanout(scope(), [ResearchTask("maker", "public pump pressure")], research)
    )
    assert result.status == "completed" and len(result.ledger) == 1 and host.calls == 3
    assert result.ledger[0].quote == "Pressure: 20 psi"
    assert result.coverage[0].accepted_rows == 1 and len(result.coverage[0].reads) == 1
    assert not hasattr(host, "result")  # The child never completes or overwrites the parent Run.
    assert "markdown" not in str(result.to_dict())
    assert all(event["type"] == "research_child" and "text" not in event for event in host.events)
