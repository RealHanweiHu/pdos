"""Actual material reader uses only frozen Human pins and repeats its ordinary recheck."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from pdos_next.agent_kernel import context_corrections as corrections
from pdos_next.enterprise_search import assistant_materials as materials
from pdos_next.enterprise_search.assistant_schemas import MaterialsInput
from pdos_next.errors import DomainError
from pdos_next.service import digest
from tests.agent_kernel.test_context_corrections import case, selection


def fixture(monkeypatch):
    run, ctx, ref = case()
    run.category_id = None
    ref.update(source_type="artifact", object_id=ref["source_id"])
    condition = selection(ref, focus=None, sources=[ref])
    state = {"context_selection": condition}
    run.versions = {"work_state": state, "work_state_digest": digest(state)}
    scope = SimpleNamespace(
        run_id=run.id, tenant_id=run.tenant_id, requester_id=run.requester_id, category_id=None
    )
    row = {
        **ref,
        "source_id": UUID(ref["source_id"]),
        "object_id": UUID(ref["object_id"]),
        "category_id": UUID(ref["category_id"]),
        "tenant_id": run.tenant_id,
        "as_of": datetime.now(UTC),
        "body_chars": 24,
        "is_current": True,
    }
    executed, checked = [], []
    session = SimpleNamespace(
        get=lambda *_: run,
        execute=lambda query: (
            executed.append(query)
            or SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: [row]))
        ),
    )
    monkeypatch.setattr(corrections, "_rows", lambda *_: [row])

    def current(_session, candidates):
        checked.append(candidates)
        return {key: row for key in candidates}, {}

    monkeypatch.setattr("pdos_next.enterprise_search.assistant_sources.current", current)
    monkeypatch.setattr(materials, "current", current)
    return SimpleNamespace(
        run=run,
        ctx=ctx,
        ref=ref,
        scope=scope,
        row=row,
        session=session,
        executed=executed,
        checked=checked,
    )


def test_personal_fixed_source_is_readable_without_forging_a_business_read_set(monkeypatch):
    f = fixture(monkeypatch)
    result = materials.read(
        f.session, f.scope, MaterialsInput(artifact_ids=[f.ref["source_id"]]), uuid4()
    )
    assert result["returned"] == 1 and result["items"][0]["source_revision"] == 2
    assert result["items"][0]["content_hash"] == f.ref["content_hash"]
    assert f.run.read_sources == [] and f.run.category_id is None
    assert len(f.checked) == 2  # selection recheck and material source/dependency recheck


@pytest.mark.parametrize(
    "reason", ["source_changed", "source_unavailable", "source_dependency_unavailable"]
)
def test_changed_revoked_or_scan_invalid_pin_stops_before_material_body_query(monkeypatch, reason):
    f = fixture(monkeypatch)
    monkeypatch.setattr(
        "pdos_next.enterprise_search.assistant_sources.current", lambda *_: ({}, {"0": reason})
    )
    with pytest.raises(DomainError):
        materials.read(
            f.session, f.scope, MaterialsInput(artifact_ids=[f.ref["source_id"]]), uuid4()
        )
    assert f.executed == []


def test_nonselected_source_cannot_be_added_by_model_material_parameters(monkeypatch):
    f = fixture(monkeypatch)
    with pytest.raises(DomainError):
        materials.read(f.session, f.scope, MaterialsInput(artifact_ids=[uuid4()]), uuid4())
    assert f.executed == []


def test_frozen_classification_cannot_silently_understate_new_source_taint(monkeypatch):
    f = fixture(monkeypatch)
    f.run.versions["work_state"]["context_selection"]["sources"][0]["customer_original"] = False
    f.run.versions["work_state_digest"] = digest(f.run.versions["work_state"])
    monkeypatch.setattr(
        "pdos_next.enterprise_search.assistant_sources.current",
        lambda _session, candidates: (
            {key: {**f.row, "customer_original": True} for key in candidates},
            {},
        ),
    )
    with pytest.raises(DomainError) as changed:
        materials.read(
            f.session, f.scope, MaterialsInput(artifact_ids=[f.ref["source_id"]]), uuid4()
        )
    assert changed.value.code == "SOURCE_STALE" and f.executed == []
