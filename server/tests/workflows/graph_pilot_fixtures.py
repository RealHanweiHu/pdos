"""Synthetic stand-ins for the plugin pilot tests: no database, model or outbound call.

The personal summary graph, its node shell, its workflow and the worker's plugin wiring
are the real ones. Only the run's database reads and writes are replaced, and each call
is appended to a journal file so a second worker process can be compared with the first.
"""

import os
import time
from datetime import timedelta
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from temporalio import activity
from temporalio.common import RetryPolicy

from pdos_next.domain.my_work import summary_plugin_graph
from pdos_next.errors import DomainError
from pdos_next.workflows.graph_nodes import activity_node

BINARY = Path(__file__).resolve().parents[3] / ".local/tools/temporal"
SECRET = "sk-synthetic-credential-must-never-enter-history"


def journal():
    return Path(os.environ["PDOS_GRAPH_PILOT_JOURNAL"])


def note(line):
    with journal().open("a") as handle:
        handle.write(line + "\n")


def notes():
    return journal().read_text().split() if journal().exists() else []


def flag(name):
    return journal().with_suffix("." + name)


def patch_summary(monkeypatch=None):
    """Replace only the summary's database access; the graph and shell stay real."""

    def generate(_store, _scope):
        note("generate")
        if flag("fail-generate").exists():
            raise DomainError("FORBIDDEN_SCOPE", "synthetic stop")
        return {"complete": True, "items": ["具名登记：合成摘要条目"]}

    def persist(_store, _scope, value):
        note("persist:start")
        while flag("block-persist").exists():
            time.sleep(0.05)
        note("persist:done")
        return {"status": "completed", "summary": "本人结构摘要已生成。", "result": value}

    values = {
        (summary_plugin_graph, "_bound"): lambda state, context: (None, None),
        (summary_plugin_graph.runtime, "generate"): generate,
        (summary_plugin_graph.runtime, "persist"): persist,
    }
    for (target, name), value in values.items():
        if monkeypatch is None:
            setattr(target, name, value)
        else:
            monkeypatch.setattr(target, name, value)


@activity.defn(name="open_xiaopai_graph_run")
def open_run(reference):
    note("open")
    return {"run_id": reference["subject_id"], "status": "running",
            "kind": "personal_summary", "cancel_epoch": 0,
            "writer_id": reference["actor_id"], "reconcile_after_seconds": 1}


@activity.defn(name="close_xiaopai_graph_run")
def close_run_activity(reference):
    note("close:" + reference["error_code"])
    return {"run_id": reference["subject_id"], "status": "failed",
            "error_code": reference["error_code"]}


@activity.defn(name="reconcile_xiaopai_run")
def reconcile(reference):
    note("reconcile")
    return {"run_id": reference["subject_id"], "status": "failed",
            "error_code": "EXTERNAL_OUTCOME_UNKNOWN"}


RUN_ACTIVITIES = [open_run, close_run_activity, reconcile]


# A second, test-only graph that asks twice, to exercise the shared driver's interrupt,
# signal and retry behaviour that the summary graph (which never asks) cannot reach.

class AskState(TypedDict, total=False):
    answers: list
    slow: bool
    done: bool


def prepare(state, context, _stop):
    note("prepare")
    return {"answers": []}


def ask(state, context, _stop):
    note("ask:enter")
    answer = interrupt({"type": "question", "asked": len(state["answers"])})
    note("ask:answered")
    return {"answers": [*state["answers"], answer["answer_ref"]]}


def finish(state, context, stop):
    note(f"finish:attempt{activity.info().attempt}")
    if state.get("slow") and activity.info().attempt == 1:
        # Longer than this node's start-to-close timeout; Temporal gives the attempt up.
        time.sleep(4)
        note("finish:abandoned-stop=" + str(stop.is_set()))
        return {"done": False}
    return {"done": True}


async def more(state):
    return "ask" if len(state["answers"]) < 2 else "finish"


def build_ask():
    quick = {"execute_in": "activity", "start_to_close_timeout": timedelta(seconds=20),
             "retry_policy": RetryPolicy(maximum_attempts=3)}
    graph = StateGraph(AskState)
    graph.add_node("prepare", activity_node(prepare), metadata=dict(quick))
    graph.add_node("ask", activity_node(ask), metadata=dict(quick))
    graph.add_node("finish", activity_node(finish), metadata={
        **quick, "start_to_close_timeout": timedelta(seconds=2),
        "retry_policy": RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=1)),
    })
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "ask")
    graph.add_conditional_edges("ask", more, ["ask", "finish"])
    graph.add_edge("finish", END)
    return graph
