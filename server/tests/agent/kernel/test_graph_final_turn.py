"""P122 (D477): the main graph's last turn is for answering, and a result that only failed
the structure check keeps the model's own summary. Scripted host; no provider, no database.
"""

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from pdos_next.agent.kernel.graph import FINAL_TURN, UNVERIFIED, AgentKernel, Budget
from pdos_next.agent.kernel.tools import default_registry
from pdos_next.agent.kernel.types import ModelTurn, ToolCall
from pdos_next.errors import DomainError
from tests.agent.kernel.test_graph import Host, final, scope

WITHHELD = "结果未通过完整核对。"


def read(identity="r"):
    return ModelTurn(calls=(ToolCall(id=identity, name="category.read", arguments={}),))


def asking(depends_on, *, summary="需要先确认范围。"):
    return ModelTurn(structured={
        "status": "needs_input", "summary": summary, "result": {}, "unfinished": ["核对范围"],
        "questions": [{"id": "q", "question": "哪个品类？", "why": "范围越具体越好找",
                       "options": [], "depends_on": depends_on}],
    })


def run(host, budget, **kwargs):
    # The node bodies under test are the ones the plugin path runs; only the wiring differs.
    return AgentKernel(host, default_registry(), budget=budget).execute(
        scope(**kwargs), goal="Synthetic question", checkpointer=InMemorySaver(),
        execution_key="final-turn")


def notes(host):
    return [[message["content"] for message in messages if message["content"] == FINAL_TURN]
            for messages in host.captured_model_messages]


def test_only_the_last_turn_is_told_to_answer_and_the_prefix_does_not_change():
    host = Host([read(), final()])
    result = run(host, Budget(model_turns=2))
    assert result["output"]["status"] == "completed"
    assert notes(host) == [[], [FINAL_TURN]]
    assert host.captured_model_messages[1][-1] == {"role": "user", "content": FINAL_TURN}
    assert host.prefixes[0] == host.prefixes[1]  # Same system prompt and tool definitions.


def test_a_tool_called_on_the_last_turn_still_runs_and_the_run_ends_as_before():
    host = Host([read()])
    result = run(host, Budget(model_turns=1))
    assert result["output"]["status"] == "partial"
    assert result["output"]["summary"].startswith("运行预算已用完")
    assert len(result["output"]["result"]["actions"]) == 1 and len(host.prefixes) == 1


def test_spent_tool_allowance_now_gets_one_turn_to_answer():
    host = Host([read(), final()])
    result = run(host, Budget(model_turns=5, tool_calls=1))
    assert result["output"]["status"] == "completed"
    assert result["output"]["summary"] == "Synthetic verified"
    assert notes(host) == [[], [FINAL_TURN]]


def test_calls_after_the_tool_allowance_is_spent_are_not_run():
    host = Host([read("first"), read("second")])
    result = run(host, Budget(model_turns=5, tool_calls=1))
    assert result["output"]["status"] == "partial"
    assert result["output"]["summary"].startswith("运行预算已用完")
    actions = result["output"]["result"]["actions"]
    assert len(actions) == 1 and len(host.prefixes) == 2  # The second call never ran.


def test_a_question_on_the_last_turn_becomes_an_unfinished_item_not_a_wait():
    host = Host([asking([])])
    result = run(host, Budget(model_turns=1))
    assert "__interrupt__" not in result
    output = result["output"]
    assert output["status"] == "partial" and output["questions"] == []
    assert output["summary"] == "需要先确认范围。"
    assert output["unfinished"] == ["核对范围", "待你确认：哪个品类？"]
    assert not any(event["type"] == "needs_input" for event in host.events)


def test_structure_failure_after_the_repairs_keeps_the_summary_marked_unverified():
    host = Host([asking(""), asking("")])
    result = run(host, Budget(validation_retries=1))
    output = result["output"]
    assert output["status"] == "partial" and len(host.prefixes) == 2
    assert output["summary"] == "需要先确认范围。" + UNVERIFIED
    assert "未经系统核对" in output["summary"]
    assert output["questions"] == [] and output["result"] == {"actions": []}
    assert output["unfinished"] == ["最终结构或引用尚未核对"]
    assert not any(event["type"] == "needs_input" for event in host.events)


def test_structure_failure_on_the_last_turn_keeps_the_summary_without_another_call():
    broken = ModelTurn(structured={"status": "completed", "summary": "查到两条记录。",
                                   "result": None, "questions": [], "unfinished": []})
    host = Host([broken])
    result = run(host, Budget(model_turns=1))
    assert len(host.prefixes) == 1
    assert result["output"]["summary"] == "查到两条记录。" + UNVERIFIED
    assert result["output"]["status"] == "partial"


@pytest.mark.parametrize("output", [{}, {"summary": "  "}, {"summary": ["不是文字"]}])
def test_without_a_usable_summary_the_result_is_withheld_as_before(output):
    host = Host([ModelTurn(structured={"status": "completed", "result": None, **output})])
    result = run(host, Budget(validation_retries=0))
    assert result["output"]["summary"] == WITHHELD


def test_a_result_rejected_by_reference_verification_is_still_withheld():
    class Rejecting(Host):
        def verify(self, _, result, tool_results):
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "引用不在已核对台账里。")

    host = Rejecting([final()])
    result = run(host, Budget(validation_retries=0))
    assert result["output"]["summary"] == WITHHELD
    assert "Synthetic verified" not in result["output"]["summary"]


def test_isolated_children_keep_the_old_behaviour():
    told = Host([read(), final()])
    run(told, Budget(model_turns=2), isolation="research")
    assert notes(told) == [[], []]
    spent = Host([read(), final()])
    result = run(spent, Budget(model_turns=5, tool_calls=1), isolation="research")
    assert result["output"]["summary"].startswith("运行预算已用完") and len(spent.prefixes) == 1
    broken = Host([asking(""), asking("")])
    result = run(broken, Budget(validation_retries=1), isolation="research")
    assert result["output"]["summary"] == WITHHELD
