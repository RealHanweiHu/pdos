from dataclasses import replace
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from pdos_next.agent_kernel.graph import AgentKernel, Budget
from pdos_next.agent_kernel.registry import ToolRegistry, command_tools
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.agent_kernel.types import ModelTurn, RunScope, ToolCall
from pdos_next.errors import DomainError
from pdos_next.schema_base import StrictModel


def scope(**kwargs):
    return RunScope(*(uuid4() for _ in range(6)), **kwargs)


class Host:
    def __init__(self, turns):
        self.turns, self.writes, self.prepared, self.events, self.prefixes = (
            iter(turns),
            [],
            [],
            [],
            [],
        )
        self.cancelled = False
        self.captured_model_messages = []

    def current(self, _):
        if self.cancelled:
            raise DomainError("CANCELLED_RUN", "Synthetic cancelled")

    def context(self, *_):
        return {"visible": "synthetic public context"}

    def enabled(self, *_):
        return True

    def qualified(self, *_):
        return False

    def model(self, _, **kwargs):
        from pdos_agent_runtime.graph import in_agent_graph

        assert in_agent_graph()
        self.prefixes.append((kwargs["system"], kwargs["tools"]))
        self.captured_model_messages.append(kwargs["messages"])
        return next(self.turns)

    def read(self, _, spec, arguments, intent_key):
        return {"actual": spec.name, "arguments": arguments}

    def prepare(self, _, spec, arguments, intent):
        self.prepared.append((spec.name, intent))
        return {"candidate": arguments, "tier": spec.tier, "requires_human": True}

    def write(self, *args):
        self.writes.append(args)
        return {"bad": "success text"}

    def receipt(self, *_):
        raise DomainError("VALIDATION_FAILED", "No actual receipt")

    def verify(self, _, result, tool_results):
        result["result"]["tool_count"] = len(tool_results)
        return result

    def emit(self, _, e):
        self.events.append(e)
        return uuid4()  # Synthetic server event reference; never a model-generated identity.

    def finish(self, _, result):
        self.result = result


def final():
    return ModelTurn(
        structured={
            "status": "completed",
            "summary": "Synthetic verified",
            "result": {},
            "questions": [],
            "unfinished": [],
        }
    )


def test_progressive_load_preserves_prefix_and_unqualified_t0_becomes_candidate():
    """The system prefix is frozen; the disclosed tool list only grows by loading.

    Before the per-skill disclosure this asserted the tool list never changed at
    all. It now changes in exactly one way: loading a skill adds that skill's own
    commands and nothing else, so what 小Pai can see still comes only from a
    server-verified skill load.
    """
    host = Host(
        [
            ModelTurn(
                calls=(
                    ToolCall(id="load", name="skill.load", arguments={"name": "proposal_drafting"}),
                )
            ),
            ModelTurn(
                calls=(
                    ToolCall(id="write", name="proposal.item.patch", arguments={"text": "draft"}),
                )
            ),
            final(),
        ]
    )
    kernel = AgentKernel(host, default_registry())
    kernel.catalog.validate_registry(kernel.registry)
    state = kernel.execute(scope(), goal="Synthetic proposal")
    assert state["output"]["result"]["tool_count"] == 2
    assert len(host.prepared) == 1 and not host.writes
    systems = [system for system, _ in host.prefixes]
    assert systems[0] == systems[1] == systems[2]
    names = [tuple(item["name"] for item in tools) for _, tools in host.prefixes]
    # The first call had no skill loaded, so the write command was not even visible.
    assert "proposal.item.patch" not in names[0]
    assert set(names[0]) < set(names[1]) and names[1] == names[2]
    gained = set(names[1]) - set(names[0])
    skill = kernel.catalog.configuration("proposal_drafting")
    assert gained <= skill.operations and "proposal.item.patch" in gained
    assert host.events[1]["type"] == "skill_loaded"


def test_raw_read_and_model_authority_are_rejected_before_host_callback():
    host = Host(
        [
            ModelTurn(
                calls=(
                    ToolCall(id="raw", name="evidence.artifact.read", arguments={}),
                    ToolCall(
                        id="fake", name="category.read", arguments={"tenant_id": str(uuid4())}
                    ),
                    ToolCall(
                        id="fake-agent", name="category.read",
                        arguments={"agent_run_id": str(uuid4())},
                    ),
                )
            ),
            final(),
        ]
    )
    result = AgentKernel(host, default_registry()).execute(scope(), goal="Synthetic injection")
    assert all(v["value"]["error"]["code"] == "FORBIDDEN_SCOPE" for v in result["tool_results"])
    assert not host.prepared and not host.writes


def test_t2_has_no_executing_operation_and_only_prepares():
    host = Host(
        [
            ModelTurn(
                calls=(ToolCall(id="p", name="project.create", arguments={"name": "suggestion"}),)
            ),
            final(),
        ]
    )
    kernel = AgentKernel(host, default_registry())
    assert kernel.registry.get("project.create").operation_key is None
    kernel.execute(scope(), goal="Synthetic decision", preload=["proposal_drafting"])
    assert len(host.prepared) == 1 and not host.writes


def test_whole_run_revert_target_is_t1_preparation_and_never_execution_identity():
    class RevertTarget(StrictModel):
        run_id: str

    target = str(uuid4())
    registry = ToolRegistry(command_tools(
        {"ai.run.revert": RevertTarget}, {"ai.run.revert": "T0"}
    ))
    spec = registry.get("ai.run.revert")
    assert spec.tier == "T1" and "run_id" in spec.input_schema["properties"]
    host = Host([
        ModelTurn(calls=(
            ToolCall(id="revert", name="ai.run.revert", arguments={"run_id": target}),
        )),
        final(),
    ])
    host.qualified = lambda *_: True
    kernel = AgentKernel(host, registry)
    base = kernel.catalog._skills["proposal_drafting"]
    kernel.catalog._skills["proposal_drafting"] = replace(
        base, operations=frozenset({"ai.run.revert"})
    )
    actual = scope()
    kernel.execute(actual, goal="Synthetic whole-run reversal", preload=["proposal_drafting"])
    assert host.prepared and not host.writes and str(actual.run_id) != target
    with pytest.raises(DomainError):
        registry.authorize(
            actual, "ai.run.revert", {"agent_run_id": target}, [base], lambda *_: True
        )


def test_private_context_cannot_promote_shared_knowledge():
    host = Host(
        [
            ModelTurn(
                calls=(
                    ToolCall(id="w", name="category.knowledge.add", arguments={"text": "private"}),
                )
            ),
            final(),
        ]
    )
    result = AgentKernel(host, default_registry()).execute(
        scope(private_context=True), goal="Synthetic private", preload=["public_research"]
    )
    assert result["tool_results"][0]["value"]["error"]["code"] == "FORBIDDEN_SCOPE"
    assert not host.prepared


def test_interrupt_resumes_same_thread_without_repeating_model_or_actions():
    host = Host(
        [
            ModelTurn(
                structured={
                    "status": "needs_input",
                    "summary": "Need scope",
                    "result": {},
                    "unfinished": [],
                    "questions": [
                        {"id": "q", "question": "Region?", "why": "Changes research", "options": []}
                    ],
                }
            ),
            final(),
        ]
    )
    kernel, bound, saver = AgentKernel(host, default_registry()), scope(), InMemorySaver()
    result = kernel.execute(bound, goal="Synthetic question", checkpointer=saver)
    assert result["__interrupt__"]
    result = kernel.execute(bound, answer={"q": "US"}, checkpointer=saver)
    assert result["output"]["status"] == "completed" and len(host.prefixes) == 2


@pytest.mark.parametrize("repair", [True, False])
def test_malformed_question_enters_bounded_repair_instead_of_crashing(repair):
    malformed = ModelTurn(structured={
        "status": "needs_input", "summary": "Need scope", "result": {},
        "questions": [{
            "id": "q", "question": "Which scope?", "why": "Needs scope",
            "options": [], "depends_on": "",
        }], "unfinished": [],
    })
    host = Host([malformed, final() if repair else malformed])
    result = AgentKernel(host, default_registry(), budget=Budget(validation_retries=1)).execute(
        scope(), goal="你好", checkpointer=InMemorySaver(),
    )
    assert result["output"]["status"] == ("completed" if repair else "partial")
    assert len(host.prefixes) == 2
    feedback = host.captured_model_messages[1][-1]["content"]
    assert "questions.0.depends_on" in feedback and "list_type" in feedback
    assert "JSON 数组" in feedback and "input" not in feedback
    assert not any(event["type"] == "needs_input" for event in host.events)
    assert not host.writes and not host.prepared


def test_graph_resume_answer_cannot_replace_actual_category_run_or_identity():
    checked = []

    class ScopedHost(Host):
        def current(self, actual):
            checked.append(actual)
            super().current(actual)

    host = ScopedHost([
        ModelTurn(structured={
            "status": "needs_input", "summary": "Need region", "result": {},
            "unfinished": [], "questions": [
                {"id": "q", "question": "Region?", "why": "Research scope", "options": []},
            ],
        }),
        final(),
    ])
    actual, saver = scope(), InMemorySaver()
    kernel = AgentKernel(host, default_registry())
    paused = kernel.execute(actual, goal="Synthetic question", checkpointer=saver)
    assert paused["__interrupt__"]
    resumed = kernel.execute(actual, answer={
        "q": "US", "category_id": str(uuid4()), "run_id": str(uuid4()),
        "tenant_id": str(uuid4()), "writer_id": str(uuid4()),
    }, checkpointer=saver)
    assert resumed["output"]["status"] == "completed"
    assert checked and all(bound == actual for bound in checked)
    assert len(host.prefixes) == 2 and not host.writes


def test_budget_forced_partial_keeps_actual_tool_results():
    host = Host([ModelTurn(calls=(ToolCall(id="r", name="category.read", arguments={}),))])
    result = AgentKernel(host, default_registry(), budget=Budget(model_turns=1)).execute(
        scope(), goal="Synthetic budget"
    )
    assert result["output"]["status"] == "partial"
    assert len(result["output"]["result"]["actions"]) == 1


def test_cancel_never_calls_model():
    host = Host([])
    host.cancelled = True
    with pytest.raises(DomainError) as e:
        AgentKernel(host, default_registry()).execute(scope(), goal="Synthetic cancel")
    assert e.value.code == "CANCELLED_RUN" and host.prefixes == []


def test_durable_wallet_limit_returns_partial_without_retrying_model():
    class Limited(Host):
        def model(self, bound, **kwargs):
            if len(self.prefixes) == 1:
                raise DomainError("RATE_LIMITED", "Synthetic global wallet exhausted")
            return super().model(bound, **kwargs)

    host = Limited([ModelTurn(calls=(ToolCall(id="r", name="category.read", arguments={}),))])
    result = AgentKernel(host, default_registry()).execute(scope(), goal="Synthetic budget")
    assert result["output"]["status"] == "partial"
    assert len(result["output"]["result"]["actions"]) == 1 and len(host.prefixes) == 1


def test_interleaved_runs_in_same_session_cannot_resume_each_others_checkpoint():
    class Capture(Host):
        def model(self, bound, **kwargs):
            self.messages = kwargs["messages"]
            return super().model(bound, **kwargs)

    question = ModelTurn(
        structured={
            "status": "needs_input",
            "summary": "Need scope",
            "result": {},
            "unfinished": [],
            "questions": [
                {"id": "q", "question": "Region?", "why": "Changes research", "options": []}
            ],
        }
    )
    original, saver = scope(), InMemorySaver()
    later = replace(original, run_id=uuid4())
    first, second = Capture([question]), Capture([question])
    assert AgentKernel(first, default_registry()).execute(
        original, goal="original goal", checkpointer=saver
    )["__interrupt__"]
    assert AgentKernel(second, default_registry()).execute(
        later, goal="later goal", checkpointer=saver
    )["__interrupt__"]
    restored = Capture([final()])
    output = AgentKernel(restored, default_registry()).execute(
        original, answer={"q": "US"}, checkpointer=saver
    )
    assert output["output"]["status"] == "completed"
    assert "original goal" in restored.messages[0]["content"]
    assert "later goal" not in restored.messages[0]["content"]


def test_revoked_history_stops_with_partial_before_model_egress():
    host = Host([])

    def revoked(*_args, **_kwargs):
        raise DomainError("CONVERSATION_HISTORY_REVOKED", "synthetic revocation")

    host.model = revoked
    result = AgentKernel(host, default_registry()).execute(scope(), goal="继续")
    assert result["output"]["status"] == "partial"
    assert result["output"]["summary"] == (
        "会话中引用的资料已无权读取或已撤回，本次处理已停止。请重新发起，小Pai会按当前权限重新整理。"
    )


def test_required_work_state_over_budget_stops_partial_without_model():
    host = Host([])
    host.context = lambda *_: {"work_state": {"context_incomplete": True,
                                            "missing": ["必需约束超出预算"]}}
    result = AgentKernel(host, default_registry()).execute(scope(), goal="保留全部明确约束")
    assert result["output"]["status"] == "partial"
    assert result["output"]["result"]["context_incomplete"] is True
    assert result["output"]["unfinished"] == ["必需约束超出预算"]
    assert host.captured_model_messages == []
