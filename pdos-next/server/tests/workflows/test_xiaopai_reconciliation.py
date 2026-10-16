"""Durable scheduling decisions; no model, database or network in this unit harness."""

import asyncio

from pdos_next.workflows import xiaopai
from tests.workflows.test_xiaopai_input_queue import reference


def test_unknown_outcome_waits_five_minutes_then_only_reconciles_original_work(monkeypatch):
    work, observed, delays = xiaopai.XiaopaiWork(), [], []

    async def execute(name, payload, **options):
        observed.append((name, dict(payload)))
        if name == "reconcile_xiaopai_run":
            assert options["retry_policy"].maximum_attempts == 0
            assert options["retry_policy"].maximum_interval.total_seconds() == 60
        return (
            {"status": "needs_reconciliation"}
            if name == "advance_xiaopai_run"
            else {"status": "failed"}
        )

    async def sleep(delay):
        delays.append(delay.total_seconds())

    monkeypatch.setattr(xiaopai.workflow, "execute_activity", execute)
    monkeypatch.setattr(xiaopai.workflow, "patched", lambda *_: True)
    monkeypatch.setattr(xiaopai.workflow, "sleep", sleep)
    ref = reference()
    assert asyncio.run(work.run(ref))["status"] == "failed"
    assert delays == [300] and observed == [
        ("advance_xiaopai_run", ref),
        ("reconcile_xiaopai_run", ref),
    ]


def test_exhausted_activity_retries_have_a_technical_exit_without_another_model_attempt(
    monkeypatch,
):
    class Exhausted(Exception):
        pass

    observed = []

    async def execute(name, payload, **options):
        observed.append((name, dict(payload)))
        assert options["retry_policy"].maximum_attempts == (
            3 if name == "advance_xiaopai_run" else 0
        )
        if name == "advance_xiaopai_run":
            raise Exhausted
        return {"status": "failed"}

    monkeypatch.setattr(xiaopai, "ActivityError", Exhausted)
    monkeypatch.setattr(xiaopai.workflow, "patched", lambda *_: True)
    monkeypatch.setattr(xiaopai.workflow, "execute_activity", execute)
    ref = reference()
    assert asyncio.run(xiaopai.XiaopaiWork().run(ref))["status"] == "failed"
    assert observed == [
        ("advance_xiaopai_run", ref),
        ("reconcile_xiaopai_run", {**ref, "activity_exhausted": True}),
    ]


def test_patch_preserves_old_workflow_wait_history(monkeypatch):
    work, observed = xiaopai.XiaopaiWork(), []

    async def execute(name, payload, **options):
        observed.append(name)
        if len(observed) == 1:
            work.resume(reference()["subject_id"])
            return {"status": "needs_reconciliation"}
        return {"status": "failed"}

    async def wait(predicate):
        assert predicate()

    monkeypatch.setattr(xiaopai.workflow, "execute_activity", execute)
    monkeypatch.setattr(xiaopai.workflow, "patched", lambda *_: False)
    monkeypatch.setattr(xiaopai.workflow, "wait_condition", wait)
    assert asyncio.run(work.run(reference()))["status"] == "failed"
    assert observed == ["advance_xiaopai_run", "advance_xiaopai_run"]
