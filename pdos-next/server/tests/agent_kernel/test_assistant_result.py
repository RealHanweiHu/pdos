from copy import deepcopy

import pytest

from pdos_next.agent_kernel.assistant_result import attach


@pytest.mark.parametrize("tools", [[], [{"tool": "skill.load"}]])
def test_no_lookup_marks_not_run(tools):
    original = {"result": {"assistant": {"lookup": "invented"}}}
    before = deepcopy(original)
    assert attach(original, tools)["result"]["assistant"] == {
        "version": 1, "kind": "general", "lookup": "not_run",
    }
    assert original == before


@pytest.mark.parametrize("body", [{}, {"assistant": {"lookup": "not_run"}}])
def test_other_tools_remove_model_authored_assistant(body):
    assert "assistant" not in attach({"result": body}, [{"tool": "category.read"}])["result"]


def test_non_dict_result_is_unchanged():
    assert attach({"result": "answer"}, []) == {"result": "answer"}
