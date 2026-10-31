"""Deterministic delivery nodes registered as the same 小Pai; no model/gateway path."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from pdos_agent_runtime.graph import registered_graph_context

from .schemas import ChannelReference, DeliveryReference


class State(TypedDict, total=False):
    reference: dict
    delivery: dict


def execute(service, reference):
    ref = (
        DeliveryReference.model_validate(reference)
        if "phase" in reference
        else (ChannelReference.model_validate(reference))
    )
    graph = StateGraph(State)
    # State contains UUID references and status metadata only. Durable sending,
    # P26 and provider receipts live in the SQL journal, not a second fact cache.
    graph.add_node("deliver_dingtalk", lambda _: {"delivery": service.tick(ref)})
    graph.add_edge(START, "deliver_dingtalk")
    graph.add_edge("deliver_dingtalk", END)
    compiled = graph.compile(name="xiaopai")
    with registered_graph_context("xiaopai"):
        return compiled.invoke({"reference": reference})["delivery"]
