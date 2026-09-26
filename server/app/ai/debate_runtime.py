"""Debate graph: moderator, seats, convergence, budget breaker (vNext V2-9, D26).

The graph is deliberately boring. All the judgement lives in the seat model
calls; everything the graph itself does is arithmetic and bookkeeping that must
be deterministic — whose turn it is, whether the budget is gone, whether anyone
said anything new. Putting convergence and the budget breaker in the graph
rather than in a prompt means a model cannot talk its way past either.

Runs off the request path (UX7): the caller drives it in a worker and the
session row carries the state, so a debate that takes minutes never blocks a UI.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from app.domain.debates import (
    DebateBudgetExhaustedError,
    DebateRecord,
    DebateSeatAuthorityError,
    DebateService,
    SeatRecord,
)

# Two consecutive rounds where every seat only restated itself: nobody is
# moving, so more rounds buy nothing but tokens.
STALE_ROUNDS_BEFORE_CONVERGENCE = 2


@dataclass(frozen=True)
class SeatArgument:
    """What a seat model returns for one turn."""

    content: str
    citations: list[dict[str, Any]]
    input_tokens: int = 0
    output_tokens: int = 0


class SeatSpeaker(Protocol):
    """Produces one seat's argument. Injected so tests need no model."""

    def speak(
        self,
        *,
        session: DebateRecord,
        seat: SeatRecord,
        round_number: int,
        transcript: Sequence[Any],
    ) -> SeatArgument: ...


class DebateState(TypedDict, total=False):
    tenant_id: UUID
    session_id: UUID
    round_number: int
    stale_rounds: int
    stop_reason: str | None
    status: str


@dataclass
class DebateRunResult:
    session: DebateRecord
    rounds_run: int
    stop_reason: str


class DebateRuntime:
    def __init__(
        self,
        *,
        service: DebateService,
        speaker: SeatSpeaker,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._service = service
        self._speaker = speaker
        self._clock = clock or (lambda: datetime.now(UTC))
        self._graph = self._build_graph()

    def run(self, *, tenant_id: UUID, session_id: UUID) -> DebateRunResult:
        final: DebateState = self._graph.invoke(
            {
                "tenant_id": tenant_id,
                "session_id": session_id,
                "round_number": 0,
                "stale_rounds": 0,
                "stop_reason": None,
            }
        )
        session = self._service.get(tenant_id=tenant_id, session_id=session_id)
        return DebateRunResult(
            session=session,
            rounds_run=final.get("round_number", 0),
            stop_reason=final.get("stop_reason") or "unknown",
        )

    def _build_graph(self) -> Any:
        graph = StateGraph(DebateState)
        graph.add_node("moderate", self._moderate)
        graph.add_node("seats_argue", self._seats_argue)
        graph.add_node("converge", self._converge)
        graph.add_node("stop", self._stop)
        graph.add_edge(START, "moderate")
        graph.add_edge("moderate", "seats_argue")
        graph.add_edge("seats_argue", "converge")
        graph.add_conditional_edges(
            "converge",
            self._next_step,
            {"continue": "moderate", "stop": "stop"},
        )
        graph.add_edge("stop", END)
        return graph.compile()

    def _moderate(self, state: DebateState) -> DebateState:
        round_number = state["round_number"] + 1
        self._service.append_moderator_turn(
            tenant_id=state["tenant_id"],
            session_id=state["session_id"],
            round_number=round_number,
            content=f"第 {round_number} 轮：各席位按各自锚定证据陈述立场与分歧。",
            now=self._clock(),
        )
        return {**state, "round_number": round_number}

    def _seats_argue(self, state: DebateState) -> DebateState:
        tenant_id = state["tenant_id"]
        session_id = state["session_id"]
        session = self._service.get(tenant_id=tenant_id, session_id=session_id)
        seats = self._service.seats(tenant_id=tenant_id, session_id=session_id)
        transcript = self._service.transcript(tenant_id=tenant_id, session_id=session_id)

        repeated_seats = 0
        spoke = 0
        for seat in seats:
            # The breaker is checked before each seat, not once per round: a
            # single expensive turn should not be allowed to overshoot.
            current = self._service.get(tenant_id=tenant_id, session_id=session_id)
            if current.remaining_tokens <= 0:
                return {**state, "stop_reason": "budget_exhausted"}

            argument = self._speaker.speak(
                session=session,
                seat=seat,
                round_number=state["round_number"],
                transcript=transcript,
            )
            try:
                turn = self._service.append_seat_turn(
                    tenant_id=tenant_id,
                    session_id=session_id,
                    seat_id=seat.id,
                    round_number=state["round_number"],
                    content=argument.content,
                    citations=argument.citations,
                    input_tokens=argument.input_tokens,
                    output_tokens=argument.output_tokens,
                    now=self._clock(),
                )
            except DebateBudgetExhaustedError:
                return {**state, "stop_reason": "budget_exhausted"}
            except DebateSeatAuthorityError as error:
                # An out-of-projection citation is recorded as a moderator note
                # rather than silently dropped: a seat trying to argue outside
                # its anchors is itself a finding worth seeing in the replay.
                self._service.append_moderator_turn(
                    tenant_id=tenant_id,
                    session_id=session_id,
                    round_number=state["round_number"],
                    content=f"席位越权，本轮发言未采纳：{error}",
                    now=self._clock(),
                )
                continue

            spoke += 1
            if turn.repetition_of_turn_id is not None:
                repeated_seats += 1

        # A round where everyone who spoke merely restated themselves is stale.
        stale = state["stale_rounds"] + 1 if spoke and repeated_seats == spoke else 0
        return {**state, "stale_rounds": stale}

    def _converge(self, state: DebateState) -> DebateState:
        if state.get("stop_reason"):
            return state
        session = self._service.get(tenant_id=state["tenant_id"], session_id=state["session_id"])
        if session.remaining_tokens <= 0:
            return {**state, "stop_reason": "budget_exhausted"}
        if state["stale_rounds"] >= STALE_ROUNDS_BEFORE_CONVERGENCE:
            return {**state, "stop_reason": "no_new_arguments"}
        if state["round_number"] >= session.max_rounds:
            return {**state, "stop_reason": "max_rounds_reached"}
        return state

    def _stop(self, state: DebateState) -> DebateState:
        reason = state.get("stop_reason") or "max_rounds_reached"
        # Budget exhaustion is reported as its own status: a debate cut short by
        # cost is not the same object as one that actually converged, and
        # collapsing them would let a truncated argument look complete.
        status = "budget_stopped" if reason == "budget_exhausted" else "converged"
        self._service.stop(
            tenant_id=state["tenant_id"],
            session_id=state["session_id"],
            status=status,
            stop_reason=reason,
            now=self._clock(),
        )
        return {**state, "status": status}

    @staticmethod
    def _next_step(state: DebateState) -> str:
        return "stop" if state.get("stop_reason") else "continue"
