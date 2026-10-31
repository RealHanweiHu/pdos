"""Pure target selection and exact-request recovery; no engine or model port."""
# ruff: noqa: F811 -- existing pure source fixture

from copy import deepcopy
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from pdos_next.domain.knowledge import assistant_gaps as gaps
from pdos_next.domain.knowledge import assistant_sources as sources
from pdos_next.domain.knowledge.assistant_schemas import GapInput
from pdos_next.errors import DomainError
from pdos_next.service import digest
from tests.knowledge.test_assistant_knowledge import source  # noqa: F401


def test_explicit_target_keeps_personal_run_and_actual_fixed_source_unchanged(source):
    ctx, session, run, ref, _actual = source
    run.category_id = None
    original = deepcopy(ref)
    result = sources.capture(session, ctx, run.id)
    assert result["run"] is run and run.category_id is None
    assert result["source_proof"] == [original] and ref == original
    assert result["artifacts"][0]["id"] == original["source_id"]


def test_personal_target_never_silently_filters_a_different_actual_source_category(source):
    ctx, session, run, _ref, actual = source
    run.category_id = None
    actual["category_id"] = str(uuid4())
    with pytest.raises(DomainError, match="重新查询") as failure:
        sources.capture(session, ctx, run.id)
    assert failure.value.code == "FORBIDDEN_SCOPE" and run.category_id is None


def test_personal_bound_material_uses_its_actual_category_and_fixed_revision(source, monkeypatch):
    ctx, session, run, ref, actual = source
    from uuid import UUID

    run.category_id = None
    run.read_sources = [{"artifact_id": ref["source_id"], "expected_revision": 1}]
    row = {**ref, "source_id": UUID(ref["source_id"]), "category_id": ctx.category_id}
    session.execute = lambda _: NS(mappings=lambda: NS(all=lambda: [row]))
    monkeypatch.setattr(sources, "recheck", lambda _s, _proof: {"0": actual})
    assert sources.bound_proof(session, run, category_id=ctx.category_id)[0] == [ref]
    with pytest.raises(DomainError):
        sources.bound_proof(session, run, category_id=uuid4())


def test_recovery_only_reads_the_exact_request_or_reports_conflict_and_miss(monkeypatch):
    tenant, category, person, run, key, identity = (uuid4() for _ in range(6))
    ctx = NS(tenant_id=tenant, category_id=category, requester_id=person, actor_id=person)
    data = GapInput(
        run_id=run,
        kind="missing_material",
        feedback_id=None,
        request_key=key,
        preview_digest="a" * 64,
    )
    row = NS(
        id=identity,
        request_key=key,
        recipient_id=person,
        run_id=run,
        kind="missing_material",
        feedback_id=None,
        request_sha256=digest(data.model_dump(mode="json", exclude={"request_key"})),
    )
    session = NS(scalar=lambda _statement: row)  # Deliberately no append/execute port.
    monkeypatch.setattr(gaps, "human", lambda *_: None)
    monkeypatch.setattr(gaps, "category_scope", lambda *_: None)
    assert gaps.recover(session, ctx, data) == gaps.submission_receipt(row)
    changed = data.model_copy(update={"preview_digest": "b" * 64})
    with pytest.raises(DomainError) as conflict:
        gaps.recover(session, ctx, changed)
    assert conflict.value.code == "DUPLICATE_INTENT_CONFLICT"
    session.scalar = lambda _: None
    with pytest.raises(DomainError) as missing:
        gaps.recover(session, ctx, data)
    assert missing.value.code == "NOT_FOUND" and missing.value.status == 404


def test_personal_capture_keeps_actual_product_scope_as_guidance_without_rebinding_run(source):
    ctx, session, run, _ref, actual = source
    source_product = uuid4()
    actual["product_id"] = source_product
    run.category_id = None
    run.product_id = None
    result = sources.capture(session, ctx, run.id)
    assert result["source_product_ids"] == [str(source_product)]
    assert run.product_id is None and run.category_id is None
