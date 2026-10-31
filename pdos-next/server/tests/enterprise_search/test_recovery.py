"""Deterministic recovery integrity, fixed batches and honest partial summaries."""

import asyncio
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.enterprise_search.events import ProjectionSender
from pdos_next.enterprise_search.indexing import _same_chunks
from pdos_next.enterprise_search.recovery import context_reference, validate_plan
from pdos_next.enterprise_search.recovery_workflow import EnterpriseRebuild, finish_rebuild
from pdos_next.errors import DomainError
from pdos_next.service import Context, digest


def manifest(count=2):
    ctx = Context(uuid4(), uuid4(), uuid4(), category_id=uuid4())
    value = {
        "version": 1,
        "context": context_reference(ctx),
        "source_as_of": "2026-10-29T00:00:00+00:00",
        "targets": [
            {
                "source_type": "artifact",
                "source_id": str(uuid4()),
                "category_id": str(ctx.category_id),
                "source_revision": 1,
                "content_hash": "a" * 64,
            }
            for _ in range(count)
        ],
    }
    return ctx, {**value, "manifest_digest": digest(value)}


@pytest.mark.parametrize(
    "field",
    [
        "text",
        "locator",
        "chunk_hash",
        "term_counts",
        "title_counts",
        "token_count",
        "category_id",
    ],
)
def test_idempotence_requires_actual_derived_fields_not_just_key_and_count(field):
    value = {
        "id": uuid4(),
        "text": "原记录",
        "locator": {"line_start": 1},
        "chunk_hash": "fixed",
        "term_counts": {"原": 1},
        "title_counts": {},
        "token_count": 1,
        "category_id": uuid4(),
        "terms": object(),
        "created_at": object(),
    }
    old = SimpleNamespace(**deepcopy(value))
    assert _same_chunks([old], [value])
    setattr(old, field, None)
    assert not _same_chunks([old], [value])


def test_manifest_detects_mutation_duplicate_sources_and_cross_category_scope():
    ctx, plan = manifest()
    assert validate_plan(plan) == ctx
    mutated = deepcopy(plan)
    mutated["targets"][0]["source_revision"] += 1
    with pytest.raises(DomainError):
        validate_plan(mutated)
    for targets in (
        [plan["targets"][0]] * 2,
        [{**plan["targets"][0], "category_id": str(uuid4())}],
    ):
        invalid = {**plan, "targets": targets}
        invalid["manifest_digest"] = digest(
            {key: value for key, value in invalid.items() if key != "manifest_digest"}
        )
        with pytest.raises(DomainError):
            validate_plan(invalid)


@pytest.mark.parametrize(
    "field,value",
    [("source_id", "bad"), ("source_revision", True), ("content_hash", ""), ("category_id", None)],
)
def test_malformed_recovery_target_is_a_reported_input_error(field, value):
    _ctx, plan = manifest()
    plan["targets"][0][field] = value
    plan["manifest_digest"] = digest(
        {key: value for key, value in plan.items() if key != "manifest_digest"}
    )
    with pytest.raises(DomainError) as error:
        validate_plan(plan)
    assert error.value.reason == "INVALID_PAYLOAD"


def test_summary_never_calls_partial_or_unacknowledged_work_current():
    _ctx, plan = manifest()
    row = {**plan["targets"][0], "code": None}
    batch = {"rows": [row], "changed": 1, "indexed_as_of": "2026-10-29T01:00:00+00:00"}
    value = finish_rebuild(plan, [batch])
    assert value["status"] == "partial" and value["ready"] == 1 and value["total"] == 2
    failed = {**plan["targets"][1], "code": "SOURCE_STALE"}
    value = finish_rebuild(plan, [batch, {**batch, "rows": [failed], "changed": 0}])
    assert value["status"] == "partial" and value["failed"] == 1
    assert value["unavailable"] == [failed] and value["source_as_of"] == plan["source_as_of"]


def test_workflow_retries_the_same_fixed_slice_then_continues_independent_work(monkeypatch):
    from pdos_next.enterprise_search import recovery_workflow as module

    _ctx, plan = manifest()
    calls, attempts = [], {}

    async def activity(name, reference, **_options):
        calls.append((name, deepcopy(reference)))
        if name == "plan_enterprise_rebuild":
            return plan
        cursor = reference["cursor"]
        attempts[cursor] = attempts.get(cursor, 0) + 1
        code = "SOURCE_UNAVAILABLE" if cursor == 0 and attempts[cursor] < 2 else None
        return {
            "processed": 1,
            "changed": 1,
            "failed": int(code is not None),
            "rows": [{**plan["targets"][cursor], "code": code}],
            "next_cursor": 1 if cursor == 0 else None,
            "indexed_as_of": "2026-10-29T01:00:00+00:00",
        }

    async def sleep(_delay):
        pass

    monkeypatch.setattr(module.workflow, "execute_activity", activity)
    monkeypatch.setattr(module.workflow, "sleep", sleep)
    result = asyncio.run(EnterpriseRebuild().run(plan["context"]))
    assert result["status"] == "current" and result["ready"] == 2
    assert [ref["cursor"] for name, ref in calls if name == "rebuild_enterprise_batch"] == [0, 0, 1]
    assert sum(name == "plan_enterprise_rebuild" for name, _ref in calls) == 1
    assert all(ref["plan"] == plan for name, ref in calls if name == "rebuild_enterprise_batch")


def test_rebuild_sender_reuses_one_request_identity_without_source_body():
    class Client:
        async def start_workflow(self, target, reference, **options):
            self.call = target, reference, options

    ctx, _plan = manifest()
    client, request_id = Client(), uuid4()
    sender = ProjectionSender(client)
    first = asyncio.run(sender.rebuild(ctx, request_id))
    second = asyncio.run(sender.rebuild(replace(ctx), request_id))
    assert first == second and first.endswith(str(request_id))
    assert client.call[0] == EnterpriseRebuild.run
    assert set(client.call[1]) == {"tenant_id", "category_id", "actor_id", "requester_id"}
