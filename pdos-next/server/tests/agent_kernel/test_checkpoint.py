import os

from langgraph.checkpoint.postgres import PostgresSaver

from pdos_next.agent_kernel.graph import AgentKernel
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.agent_kernel.types import ModelTurn
from pdos_next.workflows.checkpoints import verified_checkpoint_url
from tests.agent_kernel.test_graph import Host, final, scope


def test_graph_interrupt_survives_new_host_and_same_session_postgres_checkpoint():
    bound = scope()
    question = ModelTurn(
        structured={
            "status": "needs_input",
            "summary": "Need region",
            "result": {},
            "questions": [
                {
                    "id": "region",
                    "question": "Region?",
                    "why": "Changes research scope",
                    "options": [{"value": "US", "label": "United States"}],
                }
            ],
            "unfinished": [],
        }
    )
    host = Host([question])
    target = verified_checkpoint_url(
        os.environ["M2_TEST_CHECKPOINT_URL"].replace("postgresql://", "postgresql+psycopg://", 1)
    )
    with PostgresSaver.from_conn_string(target) as saver:
        first = AgentKernel(host, default_registry()).execute(
            bound, goal="Synthetic pump research", checkpointer=saver
        )
        assert first["__interrupt__"] and len(host.prefixes) == 1
    restored = Host([final()])
    with PostgresSaver.from_conn_string(target) as saver:
        second = AgentKernel(restored, default_registry()).execute(
            bound, answer={"region": "US"}, checkpointer=saver
        )
        assert second["output"]["status"] == "completed" and len(restored.prefixes) == 1
    assert host.prefixes[0][0] == restored.prefixes[0][0]
