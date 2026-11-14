"""Pure graph: a candidate waits for an actual server adoption witness.

How a wait is released by a committed reference, in any order and never twice, is
tested on the plugin hooks in ``test_plugin_graph_waits``.
"""

from copy import deepcopy
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from pdos_next.agent.kernel.graph import AgentKernel, VerifiedCategoryAdoption
from pdos_next.agent.kernel.registry import ToolRegistry, ToolSpec
from pdos_next.agent.kernel.types import ModelTurn, RunScope, ToolCall
from pdos_next.errors import DomainError
from tests.agent.kernel import pure_graph
from tests.agent.kernel.test_graph import Host, final


class CategoryHost(Host):
    def __init__(self, scope, *, count=1, question=False):
        calls = tuple(ToolCall(id=f"category-{i}", name="category.create", arguments={})
                      for i in range(count))
        turns = [ModelTurn(calls=calls, ledger_call_id=uuid4())]
        if question:
            turns.append(ModelTurn(structured={
                "status": "needs_input", "summary": "Next question", "result": {},
                "unfinished": [], "questions": [
                    {"id": "next", "question": "Continue?", "why": "Direction", "options": []},
                ],
            }))
        turns.append(final())
        super().__init__(turns)
        self.candidates = [{
            "event_id": str(uuid4()), "requires_human": True,
            "payload": {"prepared_by_run_id": str(scope.run_id),
                        "candidate_digest": f"{i + 1:064x}"},
        } for i in range(count)]
        self.contexts = 0

    def context(self, *args):
        self.contexts += 1
        return super().context(*args)

    def prepare(self, scope, spec, arguments, intent):
        self.prepared.append((spec.name, intent))
        return deepcopy(self.candidates[len(self.prepared) - 1])


def fixture(*, count=1, question=False):
    scope = RunScope(*(uuid4() for _ in range(5)), category_id=None)
    host = CategoryHost(scope, count=count, question=question)
    registry = ToolRegistry([ToolSpec(
        "category.create", "Synthetic candidate", {"type": "object"}, {}, "write", "T1",
        "category.create",
    )])
    return scope, host, AgentKernel(host, registry), InMemorySaver()


def start(scope, kernel, saver):
    return pure_graph.execute(kernel, scope, goal="Synthetic category", checkpointer=saver,
                          preload=("category_framing",))


def proof(scope, host, index=0):
    candidate = host.candidates[index]
    return VerifiedCategoryAdoption(str(uuid4()), {
        "candidate_event_id": candidate["event_id"],
        "candidate_digest": candidate["payload"]["candidate_digest"],
        "run_id": str(scope.run_id), "receipt_id": str(uuid4()), "category_id": str(uuid4()),
        "cancel_epoch": scope.cancel_epoch,
    })


def test_candidate_waits_without_another_model_and_resume_does_not_reprepare():
    scope, host, kernel, saver = fixture()
    paused = start(scope, kernel, saver)
    assert paused["__interrupt__"][0].value == {
        "type": "category_adoption", "event_id": host.candidates[0]["event_id"],
        "run_id": str(scope.run_id), "candidate_digest": "1".zfill(64),
    }
    assert len(host.prefixes) == len(host.prepared) == host.contexts == 1
    answer = proof(scope, host)
    result = pure_graph.execute(kernel, scope, answer=answer, checkpointer=saver)
    assert result["output"]["status"] == "completed"
    assert result["consumed_input_refs"] == [answer.input_ref]
    assert result["pending_categories"] == []
    assert len(host.prepared) == host.contexts == 1 and len(host.prefixes) == 2
    again = pure_graph.execute(kernel, scope, answer=answer, checkpointer=saver)
    assert again == result and len(host.prefixes) == 2


def test_reload_same_wait_does_not_rerun_tools_or_model():
    scope, host, kernel, saver = fixture()
    original = start(scope, kernel, saver)
    again = pure_graph.execute(kernel, scope, goal="cannot replace goal", checkpointer=saver)
    assert again["__interrupt__"] == original["__interrupt__"]
    assert again["goal"] == "Synthetic category"
    assert len(host.prepared) == len(host.prefixes) == host.contexts == 1


def test_input_without_checkpoint_cannot_start_a_fresh_goal():
    scope, host, kernel, saver = fixture()
    with pytest.raises(DomainError):
        pure_graph.execute(kernel, scope, answer=proof(scope, host), checkpointer=saver)
    assert not host.prepared and not host.prefixes


def test_cancelled_run_does_not_resume_adoption():
    scope, host, kernel, saver = fixture()
    start(scope, kernel, saver)
    host.cancelled = True
    with pytest.raises(DomainError):
        pure_graph.execute(kernel, scope, answer=proof(scope, host), checkpointer=saver)
    assert len(host.prefixes) == 1


@pytest.mark.parametrize("field", ["event_id", "prepared_by_run_id", "candidate_digest"])
def test_invalid_candidate_wait_reference_fails_closed(field):
    scope, host, kernel, saver = fixture()
    if field == "event_id":
        host.candidates[0][field] = "invalid"
    else:
        host.candidates[0]["payload"][field] = "invalid"
    with pytest.raises(DomainError):
        start(scope, kernel, saver)
    assert len(host.prefixes) == len(host.prepared) == 1
