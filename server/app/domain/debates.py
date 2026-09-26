"""Debate sessions, seats, transcript and Decision Brief (vNext V2-9, D26).

A debate is only worth more than a single model call if the seats genuinely
disagree from *different evidence*. That is what the stance projection buys:
before the first word, the server anchors each seat to a specific, listed set of
objects it may argue from. A seat cannot cite outside its anchors, so
"multi-agent" cannot decay into one model producing six paraphrases of itself.

Four limits keep a debate bounded and honest:

* **The projection is frozen server-side.** Written once at convene, never
  updated. Nothing a model emits can widen its own reach.
* **Every turn is attributed and citable.** Seat, round and citations are
  recorded, so a brief can be traced back to the arguments that produced it.
* **The budget is a hard stop.** Token spend is checked before each turn; when
  it is gone the session stops as `budget_stopped` with whatever it has, rather
  than quietly truncating and presenting the result as complete.
* **Promotion is human.** A brief is a draft until a person validates it. D26's
  "一场人工比对合格即转正" is a status transition with a named validator, not an
  automatic hand-off.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, func, select

from app.db.schema import tables
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

DebateList = list

SEAT_KEYS = (
    "id_designer",
    "firmware_engineer",
    "sqe",
    "ie",
    "product_manager",
    "project_manager",
    "structure_engineer",
    "hardware_engineer",
    "dqe",
    "supplier",
)
TOPIC_ENTITIES = frozenset(
    {
        "engineering_change_request",
        "gate",
        "issue",
        "customer_change_request",
        "requirement",
        "specification",
        "product_definition",
        "meeting",
        "risk",
    }
)
ACTIVE_STATUSES = frozenset({"convened", "arguing"})


class DebateNotFoundError(LookupError):
    """Raised when the session is absent from the tenant."""


class DebateStateError(ValueError):
    """Raised when the requested step does not fit the session state."""


class DebateSeatAuthorityError(PermissionError):
    """Raised when a seat argues from outside its frozen stance projection."""


class DebateBudgetExhaustedError(RuntimeError):
    """Raised when the token budget is gone before a turn could be taken."""


@dataclass(frozen=True)
class SeatSpec:
    """What the server anchors a seat to before the debate starts."""

    seat_key: str
    agent_key: str
    # {"kind": [ids...]} — the exact objects this seat may cite.
    anchors: dict[str, list[str]]
    persona_version: str = "v1"


@dataclass(frozen=True)
class SeatRecord:
    id: UUID
    seat_key: str
    agent_key: str
    stance_projection: dict[str, Any]
    persona_version: str


@dataclass(frozen=True)
class DebateRecord:
    id: UUID
    project_id: UUID | None
    topic_entity: str
    topic_entity_id: UUID
    question: str
    initiated_by: str
    initiator_ref: str
    status: str
    budget_tokens: int
    spent_tokens: int
    round_count: int
    max_rounds: int
    stop_reason: str | None

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.budget_tokens - self.spent_tokens)


@dataclass(frozen=True)
class TurnRecord:
    id: UUID
    round_number: int
    sequence: int
    speaker_kind: str
    seat_id: UUID | None
    author_user_id: UUID | None
    content: str
    citations: list[dict[str, Any]]
    repetition_of_turn_id: UUID | None
    created_at: datetime


@dataclass(frozen=True)
class BriefRecord:
    id: UUID
    session_id: UUID
    summary: str
    agreements: list[Any]
    disagreements: list[Any]
    recommended_action: str
    zone: str
    status: str
    rests_on_untrusted_only: bool
    validated_by_user_id: UUID | None
    validated_at: datetime | None
    rejection_note: str | None


def _debate(row: RowMapping) -> DebateRecord:
    return DebateRecord(
        id=row["id"],
        project_id=row["project_id"],
        topic_entity=row["topic_entity"],
        topic_entity_id=row["topic_entity_id"],
        question=row["question"],
        initiated_by=row["initiated_by"],
        initiator_ref=row["initiator_ref"],
        status=row["status"],
        budget_tokens=row["budget_tokens"],
        spent_tokens=row["spent_tokens"],
        round_count=row["round_count"],
        max_rounds=row["max_rounds"],
        stop_reason=row["stop_reason"],
    )


def _seat(row: RowMapping) -> SeatRecord:
    return SeatRecord(
        id=row["id"],
        seat_key=row["seat_key"],
        agent_key=row["agent_key"],
        stance_projection=row["stance_projection"],
        persona_version=row["persona_version"],
    )


def _turn(row: RowMapping) -> TurnRecord:
    return TurnRecord(
        id=row["id"],
        round_number=row["round_number"],
        sequence=row["sequence"],
        speaker_kind=row["speaker_kind"],
        seat_id=row["seat_id"],
        author_user_id=row["author_user_id"],
        content=row["content"],
        citations=list(row["citations"] or []),
        repetition_of_turn_id=row["repetition_of_turn_id"],
        created_at=row["created_at"],
    )


def _brief(row: RowMapping) -> BriefRecord:
    return BriefRecord(
        id=row["id"],
        session_id=row["session_id"],
        summary=row["summary"],
        agreements=list(row["agreements"] or []),
        disagreements=list(row["disagreements"] or []),
        recommended_action=row["recommended_action"],
        zone=row["zone"],
        status=row["status"],
        rests_on_untrusted_only=row["rests_on_untrusted_only"],
        validated_by_user_id=row["validated_by_user_id"],
        validated_at=row["validated_at"],
        rejection_note=row["rejection_note"],
    )


def _snapshot(record: DebateRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "topic_entity": record.topic_entity,
        "status": record.status,
        "round_count": record.round_count,
        "spent_tokens": record.spent_tokens,
        "stop_reason": record.stop_reason,
    }


def normalize_for_repetition(content: str) -> str:
    """Collapse a turn to its comparable core.

    Repetition detection has to survive cosmetic rewording, so casing,
    whitespace and common padding punctuation are removed before comparison.
    """
    lowered = content.lower()
    kept = [character for character in lowered if character.isalnum() or character.isspace()]
    return " ".join("".join(kept).split())


class DebateService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def convene(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID | None,
        topic_entity: str,
        topic_entity_id: UUID,
        question: str,
        seats: list[SeatSpec],
        budget_tokens: int,
        initiated_by: str,
        initiator_ref: str,
        initiated_by_user_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        max_rounds: int = 4,
        now: datetime | None = None,
    ) -> DebateRecord:
        """Open a debate and freeze every seat's stance projection.

        D26 sets no scenario allowlist — an agent may convene on any registered
        topic entity. The control is the projection, not a list of permitted
        occasions.
        """
        if topic_entity not in TOPIC_ENTITIES:
            raise DebateStateError(f"unknown topic entity: {topic_entity}")
        if len(seats) < 2:
            raise DebateStateError("a debate needs at least two seats to disagree")
        seat_keys = [seat.seat_key for seat in seats]
        if len(set(seat_keys)) != len(seat_keys):
            raise DebateStateError("each seat may be filled once")
        for seat in seats:
            if seat.seat_key not in SEAT_KEYS:
                raise DebateStateError(f"unknown seat: {seat.seat_key}")
            if not seat.anchors or not any(seat.anchors.values()):
                # A seat with no anchors can only speculate.
                raise DebateStateError(
                    f"seat {seat.seat_key} has no anchored objects to argue from"
                )
        if budget_tokens <= 0:
            raise DebateStateError("a debate needs a positive token budget")

        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        session_id = uuid4()
        with self._engine.begin() as connection:
            connection.execute(
                tables.debate_sessions.insert(),
                {
                    "id": session_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "topic_entity": topic_entity,
                    "topic_entity_id": topic_entity_id,
                    "question": question,
                    "initiated_by": initiated_by,
                    "initiator_ref": initiator_ref,
                    "initiated_by_user_id": initiated_by_user_id,
                    "status": "convened",
                    "budget_tokens": budget_tokens,
                    "spent_tokens": 0,
                    "round_count": 0,
                    "max_rounds": max_rounds,
                    "created_at": occurred_at,
                    "updated_at": occurred_at,
                },
            )
            connection.execute(
                tables.debate_seats.insert(),
                [
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "session_id": session_id,
                        "seat_key": seat.seat_key,
                        "agent_key": seat.agent_key,
                        "stance_projection": {"anchors": seat.anchors},
                        "persona_version": seat.persona_version,
                        "created_at": occurred_at,
                    }
                    for seat in seats
                ],
            )
            record = self._get(connection, tenant_id=tenant_id, session_id=session_id)
            self._emit(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                record=record,
                action="convened",
                before=None,
                occurred_at=occurred_at,
            )
            return record

    def seats(self, *, tenant_id: UUID, session_id: UUID) -> DebateList[SeatRecord]:
        with self._engine.connect() as connection:
            return self._seats(connection, tenant_id=tenant_id, session_id=session_id)

    def transcript(self, *, tenant_id: UUID, session_id: UUID) -> DebateList[TurnRecord]:
        """The full replayable record, in the order it happened (UX7)."""
        with self._engine.connect() as connection:
            self._get(connection, tenant_id=tenant_id, session_id=session_id)
            return [
                _turn(row)
                for row in connection.execute(
                    select(tables.debate_turns)
                    .where(
                        tables.debate_turns.c.tenant_id == tenant_id,
                        tables.debate_turns.c.session_id == session_id,
                    )
                    .order_by(tables.debate_turns.c.sequence)
                ).mappings()
            ]

    def append_seat_turn(
        self,
        *,
        tenant_id: UUID,
        session_id: UUID,
        seat_id: UUID,
        round_number: int,
        content: str,
        citations: list[dict[str, Any]],
        input_tokens: int = 0,
        output_tokens: int = 0,
        now: datetime | None = None,
    ) -> TurnRecord:
        """Record one seat's argument, refusing anything outside its anchors."""
        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.begin() as connection:
            record = self._get(connection, tenant_id=tenant_id, session_id=session_id)
            if record.status not in ACTIVE_STATUSES:
                raise DebateStateError(f"session is {record.status}, not arguing")
            if record.spent_tokens >= record.budget_tokens:
                raise DebateBudgetExhaustedError("token budget is exhausted; the session must stop")
            seat = self._seat_row(
                connection, tenant_id=tenant_id, session_id=session_id, seat_id=seat_id
            )
            self._assert_within_projection(seat, citations)

            repeated_of = self._find_repetition(
                connection,
                tenant_id=tenant_id,
                session_id=session_id,
                seat_id=seat_id,
                content=content,
            )
            sequence = self._next_sequence(connection, tenant_id=tenant_id, session_id=session_id)
            turn_id = uuid4()
            connection.execute(
                tables.debate_turns.insert(),
                {
                    "id": turn_id,
                    "tenant_id": tenant_id,
                    "session_id": session_id,
                    "round_number": round_number,
                    "sequence": sequence,
                    "speaker_kind": "seat",
                    "seat_id": seat_id,
                    "author_user_id": None,
                    "content": content,
                    "citations": citations,
                    "repetition_of_turn_id": repeated_of,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "created_at": occurred_at,
                },
            )
            connection.execute(
                tables.debate_sessions.update()
                .where(
                    tables.debate_sessions.c.tenant_id == tenant_id,
                    tables.debate_sessions.c.id == session_id,
                )
                .values(
                    status="arguing",
                    spent_tokens=record.spent_tokens + input_tokens + output_tokens,
                    round_count=max(record.round_count, round_number),
                    updated_at=occurred_at,
                )
            )
            return self._turn_by_id(connection, tenant_id=tenant_id, turn_id=turn_id)

    def append_moderator_turn(
        self,
        *,
        tenant_id: UUID,
        session_id: UUID,
        round_number: int,
        content: str,
        now: datetime | None = None,
    ) -> TurnRecord:
        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.begin() as connection:
            self._get(connection, tenant_id=tenant_id, session_id=session_id)
            sequence = self._next_sequence(connection, tenant_id=tenant_id, session_id=session_id)
            turn_id = uuid4()
            connection.execute(
                tables.debate_turns.insert(),
                {
                    "id": turn_id,
                    "tenant_id": tenant_id,
                    "session_id": session_id,
                    "round_number": round_number,
                    "sequence": sequence,
                    "speaker_kind": "moderator",
                    "seat_id": None,
                    "author_user_id": None,
                    "content": content,
                    "citations": [],
                    "created_at": occurred_at,
                },
            )
            return self._turn_by_id(connection, tenant_id=tenant_id, turn_id=turn_id)

    def interject(
        self,
        *,
        tenant_id: UUID,
        session_id: UUID,
        author_user_id: UUID,
        content: str,
        now: datetime | None = None,
    ) -> TurnRecord:
        """A person's input becomes a turn in the debate (UX7).

        Human input is not bounded by any stance projection: a person may
        contribute knowledge the seats were never anchored to, which is the
        whole reason for letting them interrupt.
        """
        if not content.strip():
            raise DebateStateError("an interjection needs content")
        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.begin() as connection:
            record = self._get(connection, tenant_id=tenant_id, session_id=session_id)
            if record.status not in ACTIVE_STATUSES | {"converged"}:
                raise DebateStateError(f"session is {record.status}; it can no longer take input")
            sequence = self._next_sequence(connection, tenant_id=tenant_id, session_id=session_id)
            turn_id = uuid4()
            connection.execute(
                tables.debate_turns.insert(),
                {
                    "id": turn_id,
                    "tenant_id": tenant_id,
                    "session_id": session_id,
                    "round_number": record.round_count,
                    "sequence": sequence,
                    "speaker_kind": "human",
                    "seat_id": None,
                    "author_user_id": author_user_id,
                    "content": content,
                    "citations": [],
                    "created_at": occurred_at,
                },
            )
            return self._turn_by_id(connection, tenant_id=tenant_id, turn_id=turn_id)

    def stop(
        self,
        *,
        tenant_id: UUID,
        session_id: UUID,
        status: str,
        stop_reason: str,
        actor_user_id: UUID | None = None,
        now: datetime | None = None,
    ) -> DebateRecord:
        if status not in {"converged", "budget_stopped", "cancelled", "completed", "interrupted"}:
            raise DebateStateError(f"{status} is not a stopping status")
        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.begin() as connection:
            before = self._get(connection, tenant_id=tenant_id, session_id=session_id)
            if before.status not in ACTIVE_STATUSES:
                raise DebateStateError(f"session is already {before.status}")
            connection.execute(
                tables.debate_sessions.update()
                .where(
                    tables.debate_sessions.c.tenant_id == tenant_id,
                    tables.debate_sessions.c.id == session_id,
                )
                .values(status=status, stop_reason=stop_reason, updated_at=occurred_at)
            )
            record = self._get(connection, tenant_id=tenant_id, session_id=session_id)
            self._emit(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                record=record,
                action=f"stopped_{status}",
                before=before,
                occurred_at=occurred_at,
            )
            return record

    def write_brief(
        self,
        *,
        tenant_id: UUID,
        session_id: UUID,
        summary: str,
        agreements: list[Any],
        disagreements: list[Any],
        recommended_action: str,
        zone: str,
        rests_on_untrusted_only: bool = False,
        actor_user_id: UUID | None = None,
        now: datetime | None = None,
    ) -> BriefRecord:
        """Record the Decision Brief as a draft. Promotion is a separate act."""
        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.begin() as connection:
            record = self._get(connection, tenant_id=tenant_id, session_id=session_id)
            if record.status not in {"converged", "budget_stopped", "completed"}:
                raise DebateStateError(
                    f"a brief summarises a finished debate; this one is {record.status}"
                )
            brief_id = uuid4()
            connection.execute(
                tables.debate_briefs.insert(),
                {
                    "id": brief_id,
                    "tenant_id": tenant_id,
                    "session_id": session_id,
                    "summary": summary,
                    "agreements": agreements,
                    "disagreements": disagreements,
                    "recommended_action": recommended_action,
                    "zone": zone,
                    "status": "draft",
                    "rests_on_untrusted_only": rests_on_untrusted_only,
                    "created_at": occurred_at,
                },
            )
            connection.execute(
                tables.debate_sessions.update()
                .where(
                    tables.debate_sessions.c.tenant_id == tenant_id,
                    tables.debate_sessions.c.id == session_id,
                )
                .values(status="briefed", updated_at=occurred_at)
            )
            briefed = self._get(connection, tenant_id=tenant_id, session_id=session_id)
            self._emit(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                record=briefed,
                action="briefed",
                before=record,
                occurred_at=occurred_at,
            )
            return self._brief_by_id(connection, tenant_id=tenant_id, brief_id=brief_id)

    def validate_brief(
        self,
        *,
        tenant_id: UUID,
        brief_id: UUID,
        actor_user_id: UUID,
        accept: bool,
        rejection_note: str | None = None,
        now: datetime | None = None,
    ) -> BriefRecord:
        """The human comparison D26 requires before a brief may be acted on."""
        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        if not accept and not (rejection_note or "").strip():
            raise DebateStateError("rejecting a brief requires a stated reason")
        with self._engine.begin() as connection:
            before = self._brief_by_id(connection, tenant_id=tenant_id, brief_id=brief_id)
            if before.status != "draft":
                raise DebateStateError(f"brief is already {before.status}")
            values: dict[str, Any] = (
                {
                    "status": "human_validated",
                    "validated_by_user_id": actor_user_id,
                    "validated_at": occurred_at,
                }
                if accept
                else {"status": "rejected", "rejection_note": rejection_note}
            )
            connection.execute(
                tables.debate_briefs.update()
                .where(
                    tables.debate_briefs.c.tenant_id == tenant_id,
                    tables.debate_briefs.c.id == brief_id,
                )
                .values(**values)
            )
            return self._brief_by_id(connection, tenant_id=tenant_id, brief_id=brief_id)

    def brief_for(self, *, tenant_id: UUID, session_id: UUID) -> BriefRecord:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(tables.debate_briefs).where(
                        tables.debate_briefs.c.tenant_id == tenant_id,
                        tables.debate_briefs.c.session_id == session_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise DebateNotFoundError
            return _brief(row)

    def get(self, *, tenant_id: UUID, session_id: UUID) -> DebateRecord:
        with self._engine.connect() as connection:
            return self._get(connection, tenant_id=tenant_id, session_id=session_id)

    def list_sessions(
        self, *, tenant_id: UUID, project_id: UUID | None = None
    ) -> DebateList[DebateRecord]:
        statement = select(tables.debate_sessions).where(
            tables.debate_sessions.c.tenant_id == tenant_id
        )
        if project_id is not None:
            statement = statement.where(tables.debate_sessions.c.project_id == project_id)
        with self._engine.connect() as connection:
            return [
                _debate(row)
                for row in connection.execute(
                    statement.order_by(tables.debate_sessions.c.created_at.desc())
                ).mappings()
            ]

    @staticmethod
    def _assert_within_projection(seat: SeatRecord, citations: list[dict[str, Any]]) -> None:
        """A seat may only cite what the server anchored it to.

        This is the seat-authority boundary: without it a seat could claim
        support from any object in the tenant simply by naming it, and the
        frozen projection would be decoration.
        """
        anchors: dict[str, Any] = seat.stance_projection.get("anchors", {})
        for citation in citations:
            kind = citation.get("kind")
            reference = citation.get("reference")
            if not isinstance(kind, str) or not isinstance(reference, str):
                raise DebateSeatAuthorityError(
                    f"seat {seat.seat_key} produced a malformed citation"
                )
            permitted = anchors.get(kind)
            if not permitted or reference not in permitted:
                raise DebateSeatAuthorityError(
                    f"seat {seat.seat_key} cited {kind} {reference}, "
                    "which is outside its frozen stance projection"
                )

    @staticmethod
    def _find_repetition(
        connection: Connection,
        *,
        tenant_id: UUID,
        session_id: UUID,
        seat_id: UUID,
        content: str,
    ) -> UUID | None:
        """Flag a seat restating itself.

        Detection is per seat: two seats independently reaching the same
        conclusion is agreement and worth keeping, while one seat repeating
        itself is filler that burns budget without adding information.
        """
        normalized = normalize_for_repetition(content)
        for row in connection.execute(
            select(tables.debate_turns.c.id, tables.debate_turns.c.content).where(
                tables.debate_turns.c.tenant_id == tenant_id,
                tables.debate_turns.c.session_id == session_id,
                tables.debate_turns.c.seat_id == seat_id,
            )
        ).all():
            if normalize_for_repetition(row.content) == normalized:
                repeated: UUID = row.id
                return repeated
        return None

    @staticmethod
    def _next_sequence(connection: Connection, *, tenant_id: UUID, session_id: UUID) -> int:
        highest = connection.execute(
            select(func.max(tables.debate_turns.c.sequence)).where(
                tables.debate_turns.c.tenant_id == tenant_id,
                tables.debate_turns.c.session_id == session_id,
            )
        ).scalar_one_or_none()
        return int(highest or 0) + 1

    @staticmethod
    def _seats(
        connection: Connection, *, tenant_id: UUID, session_id: UUID
    ) -> DebateList[SeatRecord]:
        return [
            _seat(row)
            for row in connection.execute(
                select(tables.debate_seats)
                .where(
                    tables.debate_seats.c.tenant_id == tenant_id,
                    tables.debate_seats.c.session_id == session_id,
                )
                .order_by(tables.debate_seats.c.seat_key)
            ).mappings()
        ]

    @staticmethod
    def _seat_row(
        connection: Connection, *, tenant_id: UUID, session_id: UUID, seat_id: UUID
    ) -> SeatRecord:
        row = (
            connection.execute(
                select(tables.debate_seats).where(
                    tables.debate_seats.c.tenant_id == tenant_id,
                    tables.debate_seats.c.session_id == session_id,
                    tables.debate_seats.c.id == seat_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise DebateNotFoundError
        return _seat(row)

    @staticmethod
    def _turn_by_id(connection: Connection, *, tenant_id: UUID, turn_id: UUID) -> TurnRecord:
        row = (
            connection.execute(
                select(tables.debate_turns).where(
                    tables.debate_turns.c.tenant_id == tenant_id,
                    tables.debate_turns.c.id == turn_id,
                )
            )
            .mappings()
            .one()
        )
        return _turn(row)

    @staticmethod
    def _brief_by_id(connection: Connection, *, tenant_id: UUID, brief_id: UUID) -> BriefRecord:
        row = (
            connection.execute(
                select(tables.debate_briefs).where(
                    tables.debate_briefs.c.tenant_id == tenant_id,
                    tables.debate_briefs.c.id == brief_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise DebateNotFoundError
        return _brief(row)

    @staticmethod
    def _get(connection: Connection, *, tenant_id: UUID, session_id: UUID) -> DebateRecord:
        row = (
            connection.execute(
                select(tables.debate_sessions).where(
                    tables.debate_sessions.c.tenant_id == tenant_id,
                    tables.debate_sessions.c.id == session_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise DebateNotFoundError
        return _debate(row)

    @staticmethod
    def _emit(
        connection: Connection,
        *,
        tenant_id: UUID,
        actor_user_id: UUID | None,
        record: DebateRecord,
        action: str,
        before: DebateRecord | None,
        occurred_at: datetime,
    ) -> None:
        EventAuditWriter(
            connection,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            project_id=record.project_id,
        ).record(
            EventDraft(
                event_id=f"debate:{record.id}:{action}:{uuid4()}",
                event_type="DEBATE_STATE_CHANGED",
                source="debate_service",
                entity_id=record.id,
                payload={
                    "session_id": str(record.id),
                    "topic_entity": record.topic_entity,
                    "status": record.status,
                    "action": action,
                },
                occurred_at=occurred_at,
            ),
            AuditDraft(
                action=f"debate.{action}",
                before_snapshot=_snapshot(before) if before else None,
                after_snapshot=_snapshot(record),
            ),
        )
