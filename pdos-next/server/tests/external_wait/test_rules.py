"""Waiting facts distinguish delivery evidence, claims and accepted responsibility."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from pdos_next.domain.external_wait import rules
from pdos_next.domain.external_wait.schemas import Payload
from pdos_next.errors import DomainError

AT = datetime(2026, 10, 19, 10, tzinfo=UTC)
A, B, OWNER, PROJECT, WAIT, ART = [uuid4() for _ in range(6)]
SOURCE = {
    "kind": "artifact",
    "id": str(ART),
    "revision": 1,
    "position": "line:1;quote_sha256:" + "a" * 64,
}
CALENDAR = {
    "calendar_id": "actual",
    "version": "v1",
    "timezone": "UTC",
    "weekly": [
        {"weekday": d, "intervals": [{"start_minute": 540, "end_minute": 1020}]} for d in range(5)
    ],
    "exceptions": [],
    "ambiguous_time": "earlier",
    "timezone_rules_sha256": None,
}


def payload(record, old=None):
    return Payload.model_validate(
        {
            "project_id": PROJECT,
            "wait": {"id": old.wait_id, "revision": old.revision} if old else None,
            "sources": [SOURCE],
            "reason": "Synthetic actual evidence",
            "record": record,
        }
    )


def apply(record, old=None, actor=A, human=True, at=AT):
    return rules.transition(
        payload(record, old),
        current=old,
        wait_id=WAIT,
        actor_id=actor,
        requester_id=actor,
        project_owner_id=OWNER,
        at=at,
        human_actor=human,
    )


def create(**kw):
    return apply(
        {
            "action": "create",
            "title": "Wait for supplier",
            "target": "Supplier",
            "request_content": "Clarification",
            "closure_condition": "Named review",
            "blocking": True,
            "next_check_at": AT - timedelta(hours=1),
            "original_timezone": "UTC",
            **kw,
        }
    )


def test_no_delivery_has_no_response_clock_even_if_claim_and_internal_check_due():
    old = create()
    claim = apply(
        {
            "action": "commitment",
            "promised_at": AT - timedelta(days=2),
            "text": "Counterparty statement",
            "original_timezone": "UTC",
        },
        old,
    )
    clock = rules.clock(claim, at=AT, calendar=CALENDAR)
    assert clock["status"] == "delivery_unknown" and clock["working_minutes"] is None
    assert clock["claimed_commitment_due"] is None and clock["check_due"] is True
    assert clock["escalation"] == "check_due"


def test_actual_delivery_and_work_calendar_are_both_needed():
    value = apply(
        {
            "action": "delivery",
            "status": "effective",
            "at": AT - timedelta(hours=1),
            "text": "Actual receipt",
            "original_timezone": "UTC",
        },
        create(),
    )
    assert rules.clock(value, at=AT)["status"] == "calendar_unknown"
    clock = rules.clock(value, at=AT, calendar=CALENDAR)
    assert (
        clock["working_minutes"] == 60
        and clock["response_started_at"] == (AT - timedelta(hours=1)).isoformat()
    )
    closed = apply({"action": "close", "result": "Internal waiting resolved"}, value)
    later = rules.clock(closed, at=AT + timedelta(days=10), calendar=CALENDAR)
    assert later["status"] == "closed" and later["working_minutes"] == 60
    assert closed.delivery == value.delivery
    reopened = apply({"action": "reopen"}, closed)
    assert reopened.delivery == value.delivery and reopened.responsible_id == A


def test_claim_is_not_actual_and_ai_cannot_attest_or_correct_delivery():
    old = create()
    r = {
        "action": "delivery",
        "status": "effective",
        "at": AT,
        "text": "Actual",
        "original_timezone": "UTC",
    }
    with pytest.raises(DomainError):
        apply(r, old, human=False)
    actual = apply(r, old)
    unknown = {**r, "status": "unverified", "at": None}
    with pytest.raises(DomainError):
        apply(unknown, actual, human=False)
    corrected = apply(unknown, actual)
    assert corrected.delivery.at is None and corrected.delivery.time_basis == "human_recorded"
    assert rules.clock(corrected, at=AT, calendar=CALENDAR)["working_minutes"] is None


def test_transfer_keeps_old_responsibility_until_exact_target_human_accepts():
    old = create()
    pending = apply({"action": "transfer_request", "to_id": B}, old)
    assert pending.responsible_id == A
    action = {"action": "transfer_accept", "request_id": pending.transfer.request_id}
    for actor, human in [(A, True), (OWNER, True), (B, False)]:
        with pytest.raises(DomainError):
            apply(action, pending, actor=actor, human=human)
    with pytest.raises(DomainError):
        apply({**action, "request_id": uuid4()}, pending, actor=B)
    accepted = apply(action, pending, actor=B)
    assert accepted.responsible_id == B and accepted.transfer is None
    assert old.target == accepted.target and old.request_content == accepted.request_content


def test_closed_only_reopen_and_fixed_targets_remain_independent():
    old = create()
    closed = apply({"action": "close", "result": "Internal close"}, old)
    with pytest.raises(DomainError):
        apply(
            {
                "action": "reply",
                "at": None,
                "text": "Unknown",
                "status": "unknown",
                "original_timezone": "UTC",
            },
            closed,
        )
    replacement = create(replaces={"id": old.wait_id, "revision": old.revision})
    assert (
        replacement.delivery is None
        and replacement.initiation is None
        and replacement.reply is None
    )
    assert closed.state == "closed"


def test_calendar_failure_preserves_unknown_not_zero():
    old = apply(
        {
            "action": "delivery",
            "status": "effective",
            "at": AT,
            "text": "Actual",
            "original_timezone": "UTC",
        },
        create(),
    )
    clock = rules.clock(old, at=AT, unavailable=True)
    assert clock["status"] == "calendar_unavailable" and clock["working_minutes"] is None
