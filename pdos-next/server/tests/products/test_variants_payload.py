from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.products.variants import (
    effective_definition,
    merge_content,
    semantic,
    three_way,
)
from pdos_next.errors import DomainError
from pdos_next.schemas.products.variants import (
    RebaseChoice,
    VariantDerivePayload,
    VariantOverrides,
    VariantRebasePayload,
)


def source():
    return {
        "artifact_id": str(uuid4()),
        "expected_revision": 1,
        "line": 1,
        "quote": "Synthetic only",
    }


def definition():
    return {
        "id": str(uuid4()),
        "revision": 1,
        "title": "Parent definition",
        "purpose": "Synthetic verification",
        "use_cases": ["Synthetic scenario"],
        "requirements": [],
        "constraints": [],
        "unknowns": [],
        "exclusions": [],
        "specs": [],
        "sources": [source()],
    }


def derive(**changes):
    return {
        "name": "Regional synthetic",
        "kind": "region",
        "applicability": ["Synthetic region only"],
        "parent_definition_id": str(uuid4()),
        "expected_parent_revision": 1,
        "sources": [source()],
        "reason": "Scoped synthetic derivation",
        **changes,
    }


@pytest.mark.parametrize("field", ["owner_id", "status", "id", "approval", "__proto__", "sources"])
def test_override_rejects_trusted_fields_and_arbitrary_path(field):
    with pytest.raises(ValidationError):
        VariantDerivePayload.model_validate(derive(overrides={field: "forged"}))


@pytest.mark.parametrize(
    "path", ["owner_id", "status", "specs/x/owner_id", "../../status", "__class__"]
)
def test_rebase_choice_paths_are_closed(path):
    with pytest.raises(ValidationError):
        RebaseChoice.model_validate(
            {"path": path, "selection": "parent", "reason": "Synthetic selection"}
        )


def test_semantic_identity_removes_expiring_confirmation_token():
    body = derive()
    one = VariantDerivePayload.model_validate({**body, "confirmation_token": "a" * 32})
    two = VariantDerivePayload.model_validate({**body, "confirmation_token": "b" * 32})
    assert semantic(one) == semantic(two) and "confirmation_token" not in semantic(one)


@pytest.mark.parametrize(
    "category,old,parent,child",
    [
        ("parent_only", "old", "new", "old"),
        ("child_only", "old", "old", "child"),
        ("same_change", "old", "same", "same"),
        ("conflict", "old", "parent", "child"),
    ],
)
def test_three_way_classifies_independent_changes(category, old, parent, child):
    before = {"title": old, "specs": []}
    new, current = {"title": parent, "specs": []}, {"title": child, "specs": []}
    snapshot = deepcopy(before)
    result = three_way(before, new, current)
    assert result == [
        {
            "path": "title",
            "old_parent": old,
            "new_parent": parent,
            "current_child": child,
            "category": category,
        }
    ]
    result[0]["old_parent"] = "changed local copy"
    assert before == snapshot


def test_conflict_requires_explicit_choice_and_unknown_choice_cannot_be_applied():
    old, parent, child = ({"title": title, "specs": []} for title in ("old", "parent", "child"))
    with pytest.raises(DomainError) as missing:
        merge_content(old, parent, child, [])
    assert missing.value.code == "CONFIRMATION_REQUIRED"
    picked = RebaseChoice(path="title", selection="child", reason="Keep local purpose")
    assert merge_content(old, parent, child, [picked])["title"] == "child"
    picked = RebaseChoice(path="title", selection="parent", reason="Adopt parent title")
    assert merge_content(old, parent, child, [picked])["title"] == "parent"
    extra = RebaseChoice(path="purpose", selection="parent", reason="Not a real change")
    with pytest.raises(DomainError) as conflict:
        merge_content(old, parent, child, [picked, extra])
    assert conflict.value.code == "VERSION_CONFLICT"


def test_derive_keeps_parent_unchanged_and_drops_inherited_appointment():
    parent = definition()
    ref = parent["sources"][0]
    parent["specs"] = [
        {
            "key": "temperature",
            "parameter": "Temperature",
            "value_type": "number",
            "availability": "unknown",
            "reason": "Unknown condition",
            "sources": [ref],
            "owner_id": str(uuid4()),
            "state": "proposed",
        }
    ]
    snapshot = deepcopy(parent)
    effective = effective_definition(
        parent, {"title": "Variant title"}, [ref], "private", "Derive explicit scope"
    )
    assert effective.title == "Variant title"
    assert effective.specs[0].owner_id is None and effective.specs[0].state == "needs_confirmation"
    assert parent == snapshot


def test_spec_overrides_cannot_claim_appointment_or_fill_unknown_zero():
    ref = source()
    spec = {
        "key": "pressure",
        "parameter": "Pressure",
        "value_type": "number",
        "availability": "unknown",
        "reason": "No known condition",
        "sources": [ref],
    }
    for extra in ({"owner_id": str(uuid4())}, {"state": "proposed"}, {"value": "0"}):
        with pytest.raises(ValidationError):
            VariantOverrides.model_validate({"specs": [{**spec, **extra}]})


def test_exact_decimal_comparison_preserves_38_digits_and_ignores_scale():
    value = "12345678901234567890123456.123456789012"

    def view(number):
        return {"specs": [{"key": "precision", "value": number, "sources": []}]}

    assert three_way(view(value), view(value), view(value)) == []
    assert three_way(view("150"), view("150.000000000000"), view("1.5E+2")) == []


def test_spec_add_remove_are_visible_and_deletion_conflict_requires_choice():
    old = {"specs": [{"key": "pressure", "value": "150", "sources": []}]}
    new = {"specs": []}
    child = {"specs": [{"key": "pressure", "value": "160", "sources": []}]}
    changes = three_way(old, new, child)
    assert changes[0]["category"] == "conflict" and changes[0]["new_parent"] is None
    picked = RebaseChoice(
        path="specs/pressure", selection="parent", reason="Explicit removal scope"
    )
    assert merge_content(old, new, child, [picked])["specs"] == []


def test_rebase_duplicate_choices_and_null_overrides_rejected():
    choice = {"path": "title", "selection": "child", "reason": "Keep local version"}
    with pytest.raises(ValidationError):
        VariantRebasePayload.model_validate(
            {
                "variant_id": str(uuid4()),
                "expected_variant_revision": 1,
                "parent_definition_id": str(uuid4()),
                "expected_parent_revision": 2,
                "choices": [choice, choice],
                "sources": [source()],
                "reason": "Compare parent update",
            }
        )
    with pytest.raises(ValidationError):
        VariantOverrides.model_validate({"title": None})
