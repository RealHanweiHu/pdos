"""Pure graph checkpoints: a candidate waits for an actual server adoption witness."""

from copy import deepcopy
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from pdos_next.agent_kernel.graph import AgentKernel, VerifiedCategoryAdoption
from pdos_next.agent_kernel.registry import ToolRegistry, ToolSpec
from pdos_next.agent_kernel.types import ModelTurn, RunScope, ToolCall
from pdos_next.errors import DomainError
from tests.agent_kernel.test_graph import Host, final


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
    return kernel.execute(scope, goal="Synthetic category", checkpointer=saver,
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
    result = kernel.execute(scope, answer=answer, checkpointer=saver)
    assert result["output"]["status"] == "completed"
    assert result["consumed_input_refs"] == [answer.input_ref]
    assert result["pending_categories"] == []
    assert len(host.prepared) == host.contexts == 1 and len(host.prefixes) == 2
    again = kernel.execute(scope, answer=answer, checkpointer=saver)
    assert again == result and len(host.prefixes) == 2


def test_reload_same_wait_does_not_rerun_tools_or_model():
    scope, host, kernel, saver = fixture()
    original = start(scope, kernel, saver)
    again = kernel.execute(scope, goal="cannot replace goal", checkpointer=saver)
    assert again["__interrupt__"] == original["__interrupt__"]
    assert again["goal"] == "Synthetic category"
    assert len(host.prepared) == len(host.prefixes) == host.contexts == 1


@pytest.mark.parametrize("value", [{}, {"approved": True}, "approved", None])
def test_ordinary_answer_is_not_an_adoption(value):
    scope, host, kernel, saver = fixture()
    start(scope, kernel, saver)
    if value is None:
        value = proof(scope, host).envelope()  # Exact matching JSON still lacks server witness.
    with pytest.raises(DomainError):
        kernel.execute(scope, answer=value, checkpointer=saver)
    assert len(host.prepared) == len(host.prefixes) == 1
    assert kernel.execute(scope, answer=proof(scope, host), checkpointer=saver)["output"]


@pytest.mark.parametrize("key,value", [
    ("candidate_event_id", str(uuid4())), ("candidate_digest", "f" * 64),
    ("run_id", str(uuid4())), ("cancel_epoch", 1), ("cancel_epoch", False),
    ("receipt_id", "not-a-uuid"), ("category_id", None), ("extra", True),
])
def test_wrong_or_malformed_verified_input_cannot_poison_pending_checkpoint(key, value):
    scope, host, kernel, saver = fixture()
    start(scope, kernel, saver)
    answer = proof(scope, host)
    answer.category_adoption[key] = value
    with pytest.raises(DomainError):
        kernel.execute(scope, answer=answer, checkpointer=saver)
    assert kernel.execute(scope, answer=proof(scope, host), checkpointer=saver)["output"]
    assert len(host.prepared) == 1


def test_multiple_candidates_queue_and_duplicate_cannot_release_next_candidate():
    scope, host, kernel, saver = fixture(count=2)
    start(scope, kernel, saver)
    first = proof(scope, host)
    waiting = kernel.execute(scope, answer=first, checkpointer=saver)
    assert waiting["__interrupt__"][0].value["event_id"] == host.candidates[1]["event_id"]
    repeated = kernel.execute(scope, answer=first, checkpointer=saver)
    assert repeated["__interrupt__"] == waiting["__interrupt__"]
    assert repeated["consumed_input_refs"] == [first.input_ref]
    assert len(host.prepared) == 2 and len(host.prefixes) == 1
    result = kernel.execute(scope, answer=proof(scope, host, 1), checkpointer=saver)
    assert result["output"]["status"] == "completed"
    assert len(host.prepared) == len(host.prefixes) == 2


@pytest.mark.parametrize("before_wait", [False, True])
def test_verified_candidates_can_be_adopted_out_of_order(before_wait):
    scope, host, kernel, saver = fixture(count=2)
    if before_wait:
        compiled = kernel.compile(scope, checkpointer=saver, preload=("category_framing",))
        config = {"configurable": {
            "thread_id": f"xiaopai:{scope.tenant_id}:{scope.session_id}:{scope.run_id}",
        }}
        from pdos_agent_runtime.graph import registered_graph_context

        with registered_graph_context("xiaopai"):
            compiled.invoke({"goal": "Synthetic category"}, config,
                            interrupt_before=["await_category_adoption"])
    else:
        start(scope, kernel, saver)
    second = proof(scope, host, 1)
    waiting = kernel.execute(scope, answer=second, checkpointer=saver)
    assert waiting["__interrupt__"][0].value["event_id"] == host.candidates[0]["event_id"]
    assert waiting["consumed_input_refs"] == [second.input_ref]
    repeated = kernel.execute(scope, answer=second, checkpointer=saver)
    assert repeated["__interrupt__"] == waiting["__interrupt__"]
    first = proof(scope, host)
    result = kernel.execute(scope, answer=first, checkpointer=saver)
    assert result["output"]["status"] == "completed"
    assert result["consumed_input_refs"] == [second.input_ref, first.input_ref]
    assert not result["pending_categories"]
    assert len(host.prepared) == len(host.prefixes) == 2


def test_duplicate_adoption_cannot_answer_the_next_human_question():
    scope, host, kernel, saver = fixture(question=True)
    start(scope, kernel, saver)
    answer = proof(scope, host)
    waiting = kernel.execute(scope, answer=answer, checkpointer=saver)
    assert waiting["__interrupt__"][0].value["questions"][0]["id"] == "next"
    assert kernel.execute(scope, answer=answer, checkpointer=saver)["__interrupt__"]
    assert len(host.prefixes) == 2
    result = kernel.execute(scope, answer={"next": "yes"}, checkpointer=saver)
    assert result["output"]["status"] == "completed" and len(host.prefixes) == 3


def test_new_adoption_cannot_answer_an_unrelated_question():
    scope, host, kernel, saver = fixture(question=True)
    start(scope, kernel, saver)
    kernel.execute(scope, answer=proof(scope, host), checkpointer=saver)
    with pytest.raises(DomainError):
        kernel.execute(scope, answer=proof(scope, host), checkpointer=saver)
    assert len(host.prefixes) == 2


@pytest.mark.parametrize("early_adoption", [False, True])
def test_recover_checkpoint_after_tools_before_interrupt_without_restarting_goal(early_adoption):
    scope, host, kernel, saver = fixture()
    compiled = kernel.compile(scope, checkpointer=saver, preload=("category_framing",))
    config = {"configurable": {
        "thread_id": f"xiaopai:{scope.tenant_id}:{scope.session_id}:{scope.run_id}",
    }}
    from pdos_agent_runtime.graph import registered_graph_context

    with registered_graph_context("xiaopai"):
        compiled.invoke({"goal": "Synthetic category"}, config,
                        interrupt_before=["await_category_adoption"])
    saved = compiled.get_state(config)
    assert saved.next == ("await_category_adoption",)
    assert not any(task.interrupts for task in saved.tasks)
    result = kernel.execute(scope, answer=proof(scope, host) if early_adoption else None,
                            checkpointer=saver)
    assert result["output"] if early_adoption else result["__interrupt__"]
    assert len(host.prepared) == host.contexts == 1
    assert len(host.prefixes) == (2 if early_adoption else 1)


def test_input_without_checkpoint_cannot_start_a_fresh_goal():
    scope, host, kernel, saver = fixture()
    with pytest.raises(DomainError):
        kernel.execute(scope, answer=proof(scope, host), checkpointer=saver)
    assert not host.prepared and not host.prefixes


def test_cancelled_run_does_not_resume_adoption():
    scope, host, kernel, saver = fixture()
    start(scope, kernel, saver)
    host.cancelled = True
    with pytest.raises(DomainError):
        kernel.execute(scope, answer=proof(scope, host), checkpointer=saver)
    assert len(host.prefixes) == 1


def test_verified_early_input_survives_checkpoint_before_candidate_tools():
    scope, host, kernel, saver = fixture()
    compiled = kernel.compile(scope, checkpointer=saver, preload=("category_framing",))
    config = {"configurable": {
        "thread_id": f"xiaopai:{scope.tenant_id}:{scope.session_id}:{scope.run_id}",
    }}
    from pdos_agent_runtime.graph import registered_graph_context

    with registered_graph_context("xiaopai"):
        compiled.invoke({"goal": "Synthetic category"}, config, interrupt_before=["tools"])
    assert not host.prepared
    result = kernel.execute(scope, answer=proof(scope, host), checkpointer=saver)
    assert result["output"]["status"] == "completed"
    assert len(host.prepared) == host.contexts == 1 and len(host.prefixes) == 2


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
