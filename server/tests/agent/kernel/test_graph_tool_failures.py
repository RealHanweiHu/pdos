"""D479: a tool that fails must neither end the run early nor leave it shown as completed."""

import json
from types import SimpleNamespace

import pytest

from pdos_next.agent.kernel import domain_adapter
from pdos_next.agent.kernel.graph import AgentKernel
from pdos_next.agent.kernel.read_failures import NOTE, attach
from pdos_next.agent.kernel.tools import default_registry
from pdos_next.agent.kernel.types import ModelTurn, ToolCall
from pdos_next.errors import DomainError
from tests.agent.kernel import pure_graph
from tests.agent.kernel.test_graph import Host, final, scope


def run(host, goal="Synthetic tool failure"):
    return pure_graph.execute(AgentKernel(host, default_registry()), scope(), goal=goal)


def tool_answers(host, turn=1):
    return {
        msg["tool_call_id"]: json.loads(msg["content"])
        for msg in host.captured_model_messages[turn] if msg["role"] == "tool"
    }


def test_unregistered_tool_name_is_a_tool_error_and_the_rest_of_the_batch_still_runs():
    host = Host([
        ModelTurn(calls=(
            ToolCall(id="known", name="category.read", arguments={}),
            ToolCall(id="made-up", name="category.lookup_everything", arguments={}),
        )),
        final(),
    ])
    result = run(host)
    answers = tool_answers(host)
    assert answers["known"]["actual"] == "category.read"
    assert answers["made-up"]["error"]["code"] == "FORBIDDEN_SCOPE"
    assert answers["made-up"]["error"]["detail"]["reason_key"] == "tool_not_registered"
    assert result["output"]["status"] == "completed"
    recorded = {item["tool"]: item for item in result["tool_results"]}
    # Nothing ran for the made-up name: its entry is only the server's refusal.
    assert recorded["category.lookup_everything"]["tier"] == "READ"
    assert recorded["category.lookup_everything"]["value"] == answers["made-up"]


def test_only_unregistered_names_still_reach_the_model_as_errors():
    host = Host([
        ModelTurn(calls=(ToolCall(id="a", name="nope.one", arguments={}),
                         ToolCall(id="b", name="nope.two", arguments={}))),
        final(),
    ])
    result = run(host)
    assert {v["error"]["code"] for v in tool_answers(host).values()} == {"FORBIDDEN_SCOPE"}
    assert result["output"]["status"] == "completed"
    assert result["tools_used"] == 2


class FailingRead(Host):
    """``category.read`` fails with the given codes in order, then succeeds."""

    def __init__(self, turns, codes):
        super().__init__(turns)
        self.codes = list(codes)

    def read(self, _, spec, arguments, intent_key):
        if spec.name == "category.read" and self.codes:
            code = self.codes.pop(0)
            if code:
                raise DomainError(code, "Synthetic read failure")
        return {"actual": spec.name}


def read_turn(identity="r"):
    return ModelTurn(calls=(ToolCall(id=identity, name="category.read", arguments={}),))


@pytest.mark.parametrize("code", ["SOURCE_UNAVAILABLE", "SOURCE_STALE"])
def test_a_read_that_never_succeeded_cannot_be_reported_as_completed(code):
    host = FailingRead([read_turn(), final()], [code])
    output = run(host)["output"]
    assert output["status"] == "partial"
    assert output["unfinished"] == [NOTE.format(tools="category.read")]
    assert output["summary"] == "Synthetic verified"  # The model's own text is kept.


def test_a_later_successful_read_of_the_same_tool_clears_the_failure():
    host = FailingRead([read_turn("first"), read_turn("second"), final()],
                       ["SOURCE_UNAVAILABLE", None])
    output = run(host)["output"]
    assert output["status"] == "completed" and output["unfinished"] == []


def test_a_refusal_the_model_caused_itself_does_not_downgrade_the_result():
    host = FailingRead([read_turn(), final()], ["FORBIDDEN_SCOPE"])
    assert run(host)["output"]["status"] == "completed"


def test_attach_leaves_non_completed_results_and_writes_alone():
    failed = {"tool": "memory.search", "tier": "READ",
              "value": {"error": {"code": "SOURCE_UNAVAILABLE"}}}
    asked = {"status": "needs_input", "summary": "s", "result": {}, "questions": [],
             "unfinished": []}
    assert attach(asked, [failed]) == asked
    done = {**asked, "status": "completed"}
    write = {**failed, "tool": "work.task.create", "tier": "T1"}
    assert attach(done, [write]) == done
    assert attach(done, [failed])["unfinished"] == [NOTE.format(tools="memory.search")]
    assert done["unfinished"] == []  # The input is not modified.


def test_wrong_write_arguments_are_a_tool_error_with_the_failing_fields(monkeypatch):
    monkeypatch.setattr(domain_adapter, "check_run_binding", lambda run, scope: None)
    run_row = SimpleNamespace(product_id=None, proposal_id=None)
    session = SimpleNamespace(get=lambda model, identity: run_row)
    commands = domain_adapter.DomainCommands(None, catalog=None, registry=None, route=None)
    with pytest.raises(DomainError) as refused:
        commands.command(session, scope(), "work.task.create", {"title": ["not text"]}, "intent")
    assert refused.value.code == "VALIDATION_FAILED"
    paths = {field["path"] for field in refused.value.detail["fields"]}
    assert "title" in paths and "project_id" in paths


# D246: each failure tells the model what to do next, and a repeated one says stop.

def step(host, turn=1, identity="r"):
    return tool_answers(host, turn)[identity]["error"]["next_step"]


@pytest.mark.parametrize(("reason", "code", "action"), [
    ("MODEL_BUDGET_EXCEEDED", "RATE_LIMITED", "deliver_partial"),
    ("SOURCE_UNAVAILABLE", "SOURCE_UNAVAILABLE", "retry_once"),
    ("FORBIDDEN_SCOPE", "FORBIDDEN_SCOPE", "respect_boundary"),
    ("INVALID_PAYLOAD", "VALIDATION_FAILED", "fix_arguments"),
    ("SOURCE_STALE", "SOURCE_STALE", "reread"),
])
def test_the_public_code_stays_and_the_model_is_told_the_next_step(reason, code, action):
    host = FailingRead([read_turn(), final()], [reason])
    result = run(host)
    error = tool_answers(host)["r"]["error"]
    assert error["code"] == code and error["detail"]["reason"] == reason
    assert error["next_step"]["action"] == action and error["next_step"]["hint"]
    # What the run records is what the model saw.
    assert result["tool_results"][0]["value"]["error"] == error


def test_a_transient_failure_gets_one_retry_then_the_model_is_told_to_stop():
    host = FailingRead([read_turn("first"), read_turn("second"), final()],
                       ["SOURCE_UNAVAILABLE", "SOURCE_UNAVAILABLE"])
    run(host)
    first = step(host, 1, "first")
    assert first["action"] == "retry_once" and "failures" not in first
    second = step(host, 2, "second")
    assert second["action"] == "stop" and second["failures"] == 2
    assert "category.read" in second["hint"]


def test_a_success_in_between_resets_the_count():
    host = FailingRead(
        [read_turn("a"), read_turn("b"), read_turn("c"), final()],
        ["SOURCE_UNAVAILABLE", None, "SOURCE_UNAVAILABLE"],
    )
    run(host)
    assert step(host, 3, "c") == {"action": "retry_once", "hint": step(host, 1, "a")["hint"]}


def test_an_unregistered_name_is_told_to_use_the_disclosed_tools():
    host = Host([ModelTurn(calls=(ToolCall(id="x", name="nope.one", arguments={}),)), final()])
    run(host)
    assert step(host, 1, "x")["action"] == "change_approach"


def test_classify_uses_the_reason_where_the_category_misleads():
    from pdos_next.agent.kernel.tool_failures import CITATION_HINT, classify

    citation = {"code": "FORBIDDEN_SCOPE",
                "detail": {"reason": "FORBIDDEN_SCOPE", "reason_key": "assistant_unknown_citation"}}
    assert classify(citation) == ("fix_arguments", CITATION_HINT)
    skill = {"code": "FORBIDDEN_SCOPE", "detail": {"reason_key": "write_skill_required"}}
    assert classify(skill)[0] == "fix_arguments"
    assert classify({"code": "INTERNAL_ERROR", "detail": {}})[0] == "stop"
    assert classify({"code": "RATE_LIMITED", "detail": {"reason": "RATE_LIMITED"}})[0] \
        == "retry_once"


def test_fixable_arguments_get_two_attempts_and_other_tools_do_not_count():
    from pdos_next.agent.kernel.tool_failures import annotate

    bad = {"error": {"code": "VALIDATION_FAILED", "detail": {"reason": "INVALID_PAYLOAD"}}}
    history = []
    actions = []
    for tool in ("a.read", "b.read", "a.read", "a.read"):
        value = annotate(bad, tool, history)
        history.append({"tool": tool, "value": value})
        actions.append(value["error"]["next_step"]["action"])
    assert actions == ["fix_arguments", "fix_arguments", "fix_arguments", "stop"]
    assert annotate({"ok": True}, "a.read", history) == {"ok": True}
    assert "next_step" not in bad["error"]  # The input is not modified.
