"""Workflow unit harness: signal references only, no Temporal service."""

import asyncio
from uuid import uuid4

import pytest

from pdos_next.workflows import xiaopai


def reference():
    return {key: str(uuid4()) for key in (
        "tenant_id", "category_id", "actor_id", "requester_id", "subject_id",
    )}


def test_signal_queue_preserves_distinct_refs_and_deduplicates():
    work = xiaopai.XiaopaiWork()
    first, second = str(uuid4()), str(uuid4())
    work.resume(first)
    work.resume(second)
    work.resume(first)
    assert work.answer_refs == [first, second]
    assert work.seen_answer_refs == {first, second}


@pytest.mark.parametrize("value", [None, {}, {"receipt_id": str(uuid4())}, 1, "", "approved"])
def test_signal_payload_cannot_supply_business_answer_or_receipt(value):
    work = xiaopai.XiaopaiWork()
    work.resume(value)
    assert work.answer_refs == [] and work.seen_answer_refs == set()


def test_signals_arriving_during_activity_are_delivered_in_order(monkeypatch):
    work = xiaopai.XiaopaiWork()
    first, second = str(uuid4()), str(uuid4())
    observed = []

    async def execute(name, payload, **kwargs):
        observed.append(dict(payload))
        assert name == "advance_xiaopai_run"
        if len(observed) == 1:
            work.resume(first)
            work.resume(second)
            work.resume(first)
            return {"status": "needs_input"}
        if len(observed) == 2:
            work.resume(first)  # Redelivery while its activity is already running.
            return {"status": "needs_input"}
        return {"status": "completed"}

    async def wait(predicate):
        assert predicate()

    monkeypatch.setattr(xiaopai.workflow, "execute_activity", execute)
    monkeypatch.setattr(xiaopai.workflow, "wait_condition", wait)
    ref = reference()
    result = asyncio.run(work.run(ref))
    assert result["status"] == "completed"
    assert observed == [ref, {**ref, "answer_ref": first}, {**ref, "answer_ref": second}]
    assert work.answer_refs == []


def test_retry_policy_keeps_the_same_input_reference_payload(monkeypatch):
    work = xiaopai.XiaopaiWork()
    identity = str(uuid4())
    work.resume(identity)
    observed = []

    async def execute(name, payload, **kwargs):
        assert kwargs["retry_policy"].maximum_attempts == 3
        # Temporal retries this one invocation's immutable payload, not a new queued answer.
        observed.extend(dict(payload) for _ in range(3))
        work.resume(identity)
        return {"status": "completed"}

    monkeypatch.setattr(xiaopai.workflow, "execute_activity", execute)
    asyncio.run(work.run(reference()))
    assert all(item["answer_ref"] == identity for item in observed)
    assert work.answer_refs == []
