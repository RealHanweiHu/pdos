"""Deeper lookup uses the real continuation owner, not a new task authority."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.enterprise_search.assistant_depth import (
    DeepenInput,
    admit_read,
    mode_for,
    prepare_deep,
)
from pdos_next.errors import DomainError
from pdos_next.models import Principal
from pdos_next.service import Context


def case(*, existing_child=None, other_owner=False):
    tenant, human, category, product, session_id = [uuid4() for _ in range(5)]
    parent = SimpleNamespace(
        id=uuid4(), tenant_id=tenant, category_id=category, product_id=product,
        project_id=None, proposal_id=None, requester_id=uuid4() if other_owner else human,
        state="completed", reverted_at=None, session_id=session_id,
        read_sources=[{"artifact_id": str(uuid4()), "expected_revision": 3}],
    )
    conversation = SimpleNamespace(id=session_id, owner_id=human, tenant_id=tenant,
                                   proposal_id=None)
    rows = iter([parent, existing_child, conversation, None])
    writes = []

    def get(model, identity):
        assert model is Principal and identity == human
        return SimpleNamespace(kind="human", active=True)

    session = SimpleNamespace(scalar=lambda *_args: next(rows), get=get,
                              add=lambda *_args: writes.append(True))
    requested = DeepenInput(continue_from_run_id=parent.id, goal="比较尚未核对的测试条件",
                            idempotency_key="deeper-lookup-request")
    return session, Context(tenant, human, human, category_id=category), parent, requested, writes


def test_prepare_deep_calls_real_continuation_with_server_inherited_scope_and_fixed_sources():
    session, ctx, parent, requested, writes = case()
    effective, actual, profile = prepare_deep(session, ctx, requested)
    assert actual is parent and not writes
    assert effective.session_id == parent.session_id and effective.product_id == parent.product_id
    assert str(effective.sources[0].artifact_id) == parent.read_sources[0]["artifact_id"]
    assert effective.sources[0].expected_revision == 3 and effective.goal == requested.goal
    assert profile == {"version": 1, "mode": "deep", "parent_run_id": str(parent.id)}
    assert "model" not in profile and "writer_id" not in profile


@pytest.mark.parametrize("failure", ["other_owner", "existing_child"])
def test_prepare_deep_preserves_actual_owner_and_single_continuation_checks(failure):
    session, ctx, _parent, requested, writes = case(
        other_owner=failure == "other_owner",
        existing_child=uuid4() if failure == "existing_child" else None,
    )
    with pytest.raises(DomainError):
        prepare_deep(session, ctx, requested)
    assert not writes


@pytest.mark.parametrize("extra", [
    {"product_id": str(uuid4())}, {"session_id": str(uuid4())},
    {"model": "other-main-model"}, {"token_limit": 999999},
])
def test_deep_request_cannot_replace_scope_model_or_budget(extra):
    _session, _ctx, _parent, requested, _writes = case()
    with pytest.raises(ValidationError):
        DeepenInput.model_validate({**requested.model_dump(mode="json"), **extra})


def test_legacy_depth_is_unprofiled_and_deep_is_bound_to_actual_parent():
    run = SimpleNamespace(versions={}, continued_from_id=uuid4())
    assert mode_for(run) is None
    run.versions["assistant_depth"] = {
        "version": 1, "mode": "deep", "parent_run_id": str(run.continued_from_id),
    }
    assert mode_for(run) == "deep"
    run.continued_from_id = uuid4()
    with pytest.raises(DomainError):
        mode_for(run)


def test_quick_allows_one_search_and_three_extract_sources_deep_allows_more():
    admit_read("quick", "assistant.search", {}, other_search_calls=0)
    with pytest.raises(DomainError):
        admit_read("quick", "assistant.search", {}, other_search_calls=1)
    admit_read("quick", "assistant.extract", {"citation_ids": [str(uuid4()) for _ in range(3)]})
    with pytest.raises(DomainError):
        admit_read("quick", "assistant.extract", {"citation_ids": [str(uuid4()) for _ in range(4)]})
    admit_read("deep", "assistant.search", {}, other_search_calls=3)
    admit_read("deep", "assistant.extract", {"citation_ids": [str(uuid4()) for _ in range(8)]})
    with pytest.raises(DomainError):
        admit_read("deep", "assistant.search", {}, other_search_calls=4)


def test_quota_uses_other_call_count_so_same_durable_call_replay_does_not_charge_again():
    admit_read("quick", "assistant.search", {}, other_search_calls=0)
    admit_read("quick", "assistant.search", {}, other_search_calls=0)
    with pytest.raises(DomainError):
        admit_read("quick", "assistant.search", {}, other_search_calls=True)
