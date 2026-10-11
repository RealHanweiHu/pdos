"""Real legacy assembly boundary; no database or model calls."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest

from pdos_next.domain.products import variants
from pdos_next.errors import DomainError
from pdos_next.schemas.products.variants import RebaseChoice
from tests.derivation_engine.test_m3_adapter import m3_spec, view


def legacy_parent():
    source = {
        "artifact_id": str(UUID(int=80)),
        "expected_revision": 1,
        "line": 1,
        "quote": "Fixed original",
    }
    spec = m3_spec(
        parameter_id=None,
        parameter_version=None,
        item_status="unknown",
        condition_note=None,
        modality=None,
        exceptions=[],
        applicable_variants=[],
        source_refs=[],
        origin="human",
        writer_id=None,
        run_id=None,
        confirmed_by=None,
        receipt_id=None,
        sources=[source],
    )
    return view(specs=[spec], sources=[source], source_refs=[], use_cases=["Inflation"])


def assemble(parent):
    return variants.effective_definition(parent, {}, [], "private", "Fixed legacy scope")


def test_real_legacy_number_assembly_removes_only_migration_defaults():
    parent = legacy_parent()
    before = deepcopy(parent)
    result = assemble(parent)
    assert str(result.specs[0].value) == "150.000000000001"
    assert result.specs[0].sources[0].quote == "Fixed original"
    assert result.specs[0].state == "needs_confirmation"
    assert "parameter_id" not in result.specs[0].model_dump()
    assert parent == before


def test_legacy_migration_defaults_do_not_create_a_spec_override():
    parent = legacy_parent()
    effective = assemble(parent).model_dump(mode="json")
    assert variants._sparse(parent, effective) == {}


def test_legacy_migration_defaults_do_not_create_a_three_way_spec_change():
    parent = legacy_parent()
    effective = assemble(parent).model_dump(mode="json")
    new_parent = {**deepcopy(parent), "revision": 2, "id": str(UUID(int=2))}
    assert variants.three_way(parent, new_parent, effective) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"parameter_id": str(UUID(int=40)), "parameter_version": 3},
        {"source_refs": [{"type": "claim", "id": str(UUID(int=90)), "version": 1}]},
        {"writer_id": str(UUID(int=21))},
        {"confirmed_by": str(UUID(int=23)), "receipt_id": str(UUID(int=24))},
        {"item_status": "expert_pending"},
        {"condition_note": "Fixed M3 condition"},
        {"value_type": "boolean", "value": None, "text": "true"},
        {"value_type": "enum", "value": None, "text": "CO2"},
    ],
)
def test_actual_m3_facts_require_proposal_without_silent_projection(changes):
    parent = legacy_parent()
    parent["specs"][0].update(changes)
    before = deepcopy(parent)
    with pytest.raises(DomainError) as caught:
        assemble(parent)
    assert caught.value.detail["reason"] == "m3_definition_requires_proposal"
    assert caught.value.status == 422
    assert parent == before


def test_definition_level_m3_source_requires_proposal():
    parent = legacy_parent()
    parent["source_refs"] = [{"type": "snapshot", "id": str(UUID(int=91)), "version": 1}]
    with pytest.raises(DomainError) as caught:
        assemble(parent)
    assert caught.value.detail["reason"] == "m3_definition_requires_proposal"


def test_explicit_legacy_title_override_requires_choice_and_keeps_local():
    old = legacy_parent()
    new = {**deepcopy(old), "id": str(UUID(int=2)), "revision": 2, "title": "New parent"}
    child = {**deepcopy(old), "id": str(UUID(int=3))}
    current = SimpleNamespace(
        id=UUID(int=3),
        revision=1,
        variant_id=UUID(int=50),
        applicability=["Local identity"],
        reason="Keep local title",
        overrides={"title": child["title"]},
    )
    changes = variants.three_way(old, new, child, current=current)
    assert changes[0]["path"] == "title" and changes[0]["category"] == "conflict"
    with pytest.raises(DomainError):
        variants.merge_content(old, new, child, [], current=current)
    selection = RebaseChoice(path="title", selection="child", reason="Keep local title")
    result = variants.merge_content(old, new, child, [selection], current=current)
    assert result["title"] == child["title"]


def test_explicit_title_override_is_bound_in_comparison_digest():
    old = legacy_parent()
    new = {**deepcopy(old), "id": str(UUID(int=2)), "revision": 2, "title": "New parent"}
    child = {**deepcopy(old), "id": str(UUID(int=3))}
    request = variants._comparison_request(old, new, child)
    ordinary = variants.compare_snapshots(request, include_legacy_title=True)
    explicit = variants.compare_snapshots(
        request, include_legacy_title=True, legacy_title_override=True
    )
    assert ordinary.request_digest != explicit.request_digest
