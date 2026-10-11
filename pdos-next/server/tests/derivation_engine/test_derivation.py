"""Pure derivation checks, intentionally isolated from all database fixtures."""

from decimal import Decimal, localcontext
from uuid import UUID

import pytest

from pdos_next.domain.products.variants import accept_changes, merge_paths, snapshot_from_definition
from pdos_next.domain.products.variants import compare_snapshots as three_way
from pdos_next.schemas.products.derivation import (
    AdoptionSelection,
    ApplicabilityScope,
    DefinitionContent,
    DefinitionSnapshot,
    DerivationRequest,
    Override,
    ReuseAssessment,
    SnapshotRef,
    SourceReference,
    SpecSnapshot,
)

PARENT_PRODUCT = UUID(int=101)
CHILD_PRODUCT = UUID(int=102)
LOCAL_OWNER = UUID(int=201)
PARENT_OWNER = UUID(int=202)


def reference(index=1):
    return SourceReference(
        artifact_id=UUID(int=300 + index),
        expected_revision=1,
        line=index,
        quote=f"Source statement {index}",
    )


def specification(key="power", value="10", **changes):
    values = {
        "key": key,
        "parameter": key,
        "value_type": "number",
        "availability": "known",
        "value": Decimal(value) if value is not None else None,
        "unit": "W",
        "test_conditions": ("25 C", "nominal voltage"),
        "reason": "Source states this target",
        "sources": (reference(),),
    }
    values.update(changes)
    return SpecSnapshot(**values)


def content(specs=(), **changes):
    values = {
        "purpose": "Portable speaker definition",
        "use_cases": ("Portable listening",),
        "requirements": (),
        "constraints": (),
        "unknowns": (),
        "exclusions": (),
        "sources": (reference(),),
        "specs": tuple(specs),
    }
    values.update(changes)
    return DefinitionContent(**values)


def snapshot(number, product, revision, payload, **changes):
    values = {
        "ref": SnapshotRef(
            category_id=UUID(int=100),
            definition_id=UUID(int=number),
            product_id=product,
            revision=revision,
        ),
        "content": payload,
        "title": f"Definition {number}",
        "status": "draft",
    }
    values.update(changes)
    return DefinitionSnapshot(**values)


def request(old_specs=(), new_specs=(), child_specs=(), **changes):
    old = snapshot(1, PARENT_PRODUCT, 1, content(old_specs))
    values = {
        "old_parent": old,
        "new_parent": snapshot(2, PARENT_PRODUCT, 2, content(new_specs)),
        "child": snapshot(3, CHILD_PRODUCT, 1, content(child_specs)),
        "pinned_parent": old.ref,
    }
    values.update(changes)
    return DerivationRequest(**values)


def scope(product=CHILD_PRODUCT):
    return ApplicabilityScope(
        category_id=UUID(int=100), product_id=product, description="Speaker child variant"
    )


def selection(req, selected_paths, **changes):
    values = {
        "request_digest": three_way(req).request_digest,
        "paths": tuple(selected_paths),
        "reason": "Adopt selected parent change",
        "sources": (reference(),),
        "scope": scope(),
    }
    values.update(changes)
    return AdoptionSelection(**values)


def differences(req):
    return {item.path: item for item in three_way(req).differences}


class ValidationPort:
    def __init__(self, **changes):
        self.values = {
            "audience": "allowed",
            "cross_customer": "not_required",
            "applicability": "applicable",
            "basis": ("Authority checked source and child scope",),
        }
        self.values.update(changes)
        self.checks = []

    def assess(self, check):
        self.checks.append(check)
        return ReuseAssessment(**self.values)


def test_all_five_three_way_classes_include_child_only_and_sorted_paths():
    values = {
        "unchanged": ("10", "10", "10"),
        "parent_only": ("10", "20", "10"),
        "child_only": ("10", "10", "30"),
        "same_change": ("10", "20", "20"),
        "conflict": ("10", "20", "30"),
    }
    req = request(
        tuple(specification(key, items[0]) for key, items in values.items()),
        tuple(specification(key, items[1]) for key, items in values.items()),
        tuple(specification(key, items[2]) for key, items in values.items()),
    )
    result = three_way(req)
    by_path = {item.path: item for item in result.differences}
    for key in values:
        assert by_path[f"specs/{key}"].classification == key
    assert [item.path for item in result.differences] == sorted(by_path)


def test_deletion_conflict_and_additions_have_distinct_missing_states():
    req = request(
        (specification("removed"), specification("conflicted")),
        (specification("new_parent"),),
        (specification("removed"), specification("conflicted", "11"), specification("new_child")),
    )
    result = differences(req)
    assert result["specs/removed"].classification == "parent_only"
    assert result["specs/removed"].new_parent.state == "deleted"
    assert result["specs/conflicted"].classification == "conflict"
    assert result["specs/new_parent"].old_parent.state == "missing"
    assert result["specs/new_parent"].child.state == "missing"
    assert result["specs/new_parent"].classification == "parent_only"
    assert result["specs/new_child"].classification == "child_only"


@pytest.mark.parametrize(
    ("new_specs", "child_specs", "classification"),
    [
        ((), (specification(),), "parent_only"),
        ((specification(),), (), "child_only"),
        ((), (), "same_change"),
    ],
)
def test_deletion_classification(new_specs, child_specs, classification):
    item = differences(request((specification(),), new_specs, child_specs))["specs/power"]
    assert item.classification == classification


def test_absent_null_and_explicitly_deleted_sections_are_not_equal():
    old = snapshot(1, PARENT_PRODUCT, 1, DefinitionContent(purpose=None, specs=()))
    new = snapshot(2, PARENT_PRODUCT, 2, DefinitionContent(specs=()))
    child = snapshot(3, CHILD_PRODUCT, 1, DefinitionContent(specs=(), deleted_fields=("purpose",)))
    item = differences(request(old_parent=old, new_parent=new, child=child, pinned_parent=old.ref))[
        "field/purpose"
    ]
    assert item.old_parent.state == "null"
    assert item.new_parent.state == "missing"
    assert item.child.state == "deleted"
    assert item.classification == "conflict"


def test_unknown_spec_is_present_and_requires_confirmation_without_zero():
    known = specification()
    unknown = specification(value=None, availability="unknown")
    req = request((known,), (unknown,), (known,))
    item = differences(req)["specs/power"]
    assert item.new_parent.state == "unknown"
    assert item.new_parent.value.value is None
    assert item.reconfirmation
    candidate = accept_changes(req, selection(req, ("specs/power",)))
    adopted = candidate.content.specs[0]
    assert adopted.availability == "unknown"
    assert adopted.value is None
    assert adopted.state == "needs_confirmation"


def test_decimal_and_collection_order_do_not_create_changes():
    first = specification("a", "1.0", sources=(reference(1), reference(2)))
    second = specification("b", "2")
    reordered = specification(
        "a",
        "1.000000000000",
        sources=(reference(2), reference(1)),
        test_conditions=("nominal voltage", "25 C"),
        owner_id=PARENT_OWNER,
        state="proposed",
    )
    req = request((first, second), (second, reordered), (second, first))
    result = differences(req)
    assert result["specs/a"].classification == "unchanged"
    assert result["specs/b"].classification == "unchanged"
    assert result["specs/a"].changed_fields == ()


def test_definition_source_order_is_not_an_effective_content_change():
    req = request()
    req = req.model_copy(
        update={
            "old_parent": req.old_parent.model_copy(
                update={
                    "content": content(sources=(reference(1), reference(2))),
                }
            ),
            "new_parent": req.new_parent.model_copy(
                update={
                    "content": content(sources=(reference(2), reference(1))),
                }
            ),
            "child": req.child.model_copy(
                update={
                    "content": content(sources=(reference(1), reference(2))),
                }
            ),
        }
    )
    assert differences(req)["field/sources"].classification == "unchanged"


def test_small_decimal_delta_survives_a_low_precision_context():
    original = "1234567890123456789012345.123456789012"
    incoming = "1234567890123456789012345.123456789013"
    old = specification(value=original)
    req = request((old,), (specification(value=incoming),), (old,))
    with localcontext() as context:
        context.prec = 6
        item = differences(req)["specs/power"]
        candidate = accept_changes(req, selection(req, ("specs/power",)))
    assert item.classification == "parent_only"
    assert candidate.content.specs[0].value == Decimal(incoming)


@pytest.mark.parametrize("changes", [{"unit": "mW"}, {"test_conditions": ("40 C",)}])
def test_units_and_test_conditions_remain_semantic_and_need_reconfirmation(changes):
    old = specification()
    req = request((old,), (specification(**changes),), (old,))
    item = differences(req)["specs/power"]
    assert item.classification == "parent_only"
    assert set(changes) <= set(item.changed_fields)
    assert item.reconfirmation


def test_same_value_explicit_override_conflicts_when_parent_changes():
    old = specification()
    req = request(
        (old,),
        (specification(value="20"),),
        (old,),
        overrides=(
            Override(
                path="specs/power",
                operation="set",
                reason="Retain child power target",
                sources=(reference(),),
                scope=scope(),
            ),
        ),
    )
    assert differences(req)["specs/power"].classification == "conflict"
    with pytest.raises(ValueError):
        accept_changes(req, selection(req, ("specs/power",)))
    accepted = accept_changes(
        req, selection(req, ("specs/power",), resolve_conflicts=("specs/power",))
    )
    assert accepted.content.specs[0].value == Decimal("20")


def test_adoption_never_inherits_parent_identity_approval_or_decisions():
    old = specification(owner_id=LOCAL_OWNER)
    parent = specification(value="20", owner_id=PARENT_OWNER, state="proposed", nature="decided")
    req = request((old,), (parent,), (old,))
    req = req.model_copy(
        update={
            "new_parent": req.new_parent.model_copy(
                update={
                    "status": "published",
                    "owner_id": PARENT_OWNER,
                    "published_by": PARENT_OWNER,
                    "approval_ids": (UUID(int=500),),
                }
            ),
        }
    )
    candidate = accept_changes(req, selection(req, ("specs/power",)), ValidationPort())
    assert candidate.kind == "calculation_candidate"
    adopted = candidate.content.specs[0]
    assert adopted.value == Decimal("20")
    assert adopted.owner_id == LOCAL_OWNER
    assert adopted.state == "needs_confirmation"
    assert adopted.nature == "extracted"
    assert candidate.traces[0].origin_nature == "decided"
    assert {"title", "status", "owner_id", "published_by", "approval_ids"}.isdisjoint(
        candidate.content.model_dump()
    )
    assert candidate.required_authority_checks
    assert candidate.pinned_parent == req.old_parent.ref
    assert candidate.offered_parent == req.new_parent.ref


def test_new_parent_spec_cannot_inherit_parent_owner():
    req = request(new_specs=(specification(owner_id=PARENT_OWNER),))
    candidate = accept_changes(req, selection(req, ("specs/power",)), ValidationPort())
    assert candidate.content.specs[0].owner_id is None
    assert candidate.content.specs[0].state == "needs_confirmation"


def test_selective_parent_deletion_is_a_candidate_and_preserves_other_specs():
    removed, retained = specification("remove"), specification("retain")
    req = request((removed, retained), (retained,), (removed, retained))
    candidate = accept_changes(req, selection(req, ("specs/remove",)), ValidationPort())
    assert [item.key for item in candidate.content.specs] == ["retain"]
    assert [item.path for item in candidate.traces] == ["specs/remove"]


def test_selective_section_deletion_remains_explicit_in_candidate():
    req = request()
    incoming = DefinitionContent(
        use_cases=("Portable listening",),
        requirements=(),
        constraints=(),
        unknowns=(),
        exclusions=(),
        sources=(reference(),),
        specs=(),
        deleted_fields=("purpose",),
    )
    req = req.model_copy(
        update={
            "new_parent": req.new_parent.model_copy(update={"content": incoming}),
        }
    )
    candidate = accept_changes(req, selection(req, ("field/purpose",)), ValidationPort())
    assert "purpose" in candidate.content.deleted_fields
    assert "purpose" not in candidate.content.model_fields_set
    assert candidate.content.use_cases == req.child.content.use_cases


def test_source_section_deletion_keeps_trace_evidence_and_reports_missing_source():
    req = request()
    incoming = DefinitionContent(
        purpose="Portable speaker definition",
        use_cases=("Portable listening",),
        requirements=(),
        constraints=(),
        unknowns=(),
        exclusions=(),
        specs=(),
        deleted_fields=("sources",),
    )
    req = req.model_copy(
        update={
            "new_parent": req.new_parent.model_copy(update={"content": incoming}),
        }
    )
    candidate = accept_changes(req, selection(req, ("field/sources",)), ValidationPort())
    assert "sources" in candidate.content.deleted_fields
    assert "sources" not in candidate.content.model_fields_set
    assert candidate.content.sources is None
    assert candidate.traces[0].sources == (reference(),)
    assert "missing_definition_source" in {item.code for item in candidate.missing}


def test_parent_deletion_conflict_requires_explicit_resolution_before_removing_child():
    old = specification()
    req = request((old,), (), (specification(value="11"),))
    assert differences(req)["specs/power"].classification == "conflict"
    with pytest.raises(ValueError):
        accept_changes(req, selection(req, ("specs/power",)), ValidationPort())
    candidate = accept_changes(
        req, selection(req, ("specs/power",), resolve_conflicts=("specs/power",)), ValidationPort()
    )
    assert candidate.content.specs == ()
    assert [item.path for item in candidate.traces] == ["specs/power"]


def test_selective_adoption_preserves_unselected_set_and_delete_overrides():
    retained_override = Override(
        path="specs/retain",
        operation="set",
        reason="Keep child target above parent",
        sources=(reference(),),
        scope=scope(),
    )
    deleted_override = Override(
        path="specs/remove",
        operation="delete",
        reason="Target is excluded from this child",
        sources=(reference(),),
        scope=scope(),
    )
    req = request(
        (specification(), specification("retain"), specification("remove")),
        (specification(value="20"), specification("retain"), specification("remove")),
        (specification(), specification("retain", "11")),
        overrides=(retained_override, deleted_override),
    )
    candidate = accept_changes(req, selection(req, ("specs/power",)), ValidationPort())
    retained = {item.path: item for item in candidate.overrides}
    assert retained["specs/retain"] == retained_override
    assert retained["specs/remove"] == deleted_override
    specs = {item.key: item for item in candidate.content.specs}
    assert specs["retain"].value == Decimal("11")
    assert "remove" not in specs


def test_no_validation_port_returns_preview_with_pending_authority():
    old = specification()
    req = request((old,), (specification(value="20"),), (old,))
    candidate = accept_changes(req, selection(req, ("specs/power",)))
    assert candidate.kind == "calculation_candidate"
    assert candidate.content.specs[0].value == Decimal("20")
    assert "authority_pending" in {item.code for item in candidate.missing}
    assert candidate.traces[0].assessment is None


@pytest.mark.parametrize(
    "assessment",
    [
        {"audience": "denied"},
        {"audience": "unknown"},
        {"cross_customer": "denied"},
        {"cross_customer": "unknown"},
        {"applicability": "not_applicable"},
        {"applicability": "unknown"},
    ],
)
def test_denied_or_unknown_port_cannot_adopt(assessment):
    old = specification()
    req = request((old,), (specification(value="20"),), (old,))
    port = ValidationPort(**assessment)
    candidate = accept_changes(req, selection(req, ("specs/power",)), port)
    assert candidate.content.specs[0].value == Decimal("10")
    assert "specs/power" not in {item.path for item in candidate.traces}
    assert any(item.path == "specs/power" for item in candidate.missing)
    assert port.checks[0].child == req.child.ref
    assert port.checks[0].scope == scope()


@pytest.mark.parametrize(
    "mutation",
    [
        {
            "pinned_parent": SnapshotRef(
                category_id=UUID(int=100),
                definition_id=UUID(int=1),
                product_id=PARENT_PRODUCT,
                revision=9,
            )
        },
        {"new_parent": snapshot(2, PARENT_PRODUCT, 1, content())},
        {"new_parent": snapshot(1, PARENT_PRODUCT, 2, content())},
        {"new_parent": snapshot(2, UUID(int=999), 2, content())},
        {"child": snapshot(1, CHILD_PRODUCT, 1, content())},
    ],
)
def test_fixed_parent_and_snapshot_version_mismatches_are_rejected(mutation):
    with pytest.raises(ValueError):
        three_way(request(**mutation))


@pytest.mark.parametrize(
    "bad_path", ["field/title", "specs/../power", "specs/power/value", "specs/", "other/power"]
)
def test_invalid_override_paths_are_rejected(bad_path):
    override = Override(
        path=bad_path,
        operation="set",
        reason="Explicit child exception",
        sources=(reference(),),
        scope=scope(),
    )
    with pytest.raises(ValueError):
        three_way(request(overrides=(override,)))


def test_duplicate_keys_and_inconsistent_unknown_numbers_are_rejected():
    with pytest.raises(ValueError):
        content((specification(), specification()))
    with pytest.raises(ValueError):
        specification(availability="unknown")
    with pytest.raises(ValueError):
        specification(value="NaN")
    with pytest.raises(ValueError):
        DefinitionContent(specs=(), purpose=None, deleted_fields=("purpose",))


@pytest.mark.parametrize("field", ["value", "lower", "upper", "tolerance"])
@pytest.mark.parametrize("inexact", [1.25, True])
def test_specification_does_not_accept_float_or_bool_as_exact_decimal(field, inexact):
    payload = specification().model_dump()
    if field in {"lower", "upper"}:
        payload.update(value_type="range", value=None, lower=Decimal("1"), upper=Decimal("2"))
    payload[field] = inexact
    with pytest.raises(ValueError, match="never a float"):
        SpecSnapshot.model_validate(payload)


def test_stale_digest_duplicate_selection_and_scope_mismatch_are_rejected():
    old = specification()
    req = request((old,), (specification(value="20"),), (old,))
    for changes in (
        {"request_digest": "0" * 64},
        {"paths": ("specs/power", "specs/power")},
        {"paths": ("specs/missing",)},
        {"scope": scope(PARENT_PRODUCT)},
    ):
        with pytest.raises(ValueError):
            accept_changes(req, selection(req, ("specs/power",), **changes))


def test_algorithms_leave_inputs_unchanged_and_bind_content_in_digest():
    old = specification()
    req = request((old,), (specification(value="20"),), (old,))
    before = req.model_dump()
    merge_paths(req.old_parent)
    first = three_way(req)
    accept_changes(req, selection(req, ("specs/power",)), ValidationPort())
    assert req.model_dump() == before
    assert three_way(req).request_digest == first.request_digest
    changed = request((old,), (specification(value="21"),), (old,))
    assert three_way(changed).request_digest != first.request_digest


def test_current_definition_view_adapter_retains_exact_decimals_and_fixed_identity():
    spec = specification().model_dump(mode="json")
    spec["value"] = "12.000000000000"
    view = {
        "id": str(UUID(int=1)),
        "category_id": str(UUID(int=100)),
        "product_id": str(PARENT_PRODUCT),
        "revision": 1,
        "title": "Parent source",
        "status": "draft",
        "owner_id": str(PARENT_OWNER),
        "parent_definition_id": None,
        "purpose": "Portable speaker definition",
        "use_cases": ["Portable listening"],
        "requirements": [],
        "constraints": [],
        "unknowns": [],
        "exclusions": [],
        "visibility": "private",
        "change_reason": "First draft",
        "sources": [
            {
                **reference().model_dump(mode="json"),
                "title": "Source title",
                "status": "active",
                "spec_keys": ["power"],
            }
        ],
        "specs": [spec],
        "created_at": "2026-10-02T10:00:00Z",
        "source_status": "current",
        "differences": [],
    }
    variant_id = UUID(int=700)
    adapted = snapshot_from_definition(view, variant_id=variant_id)
    assert adapted.ref.definition_id == UUID(int=1)
    assert adapted.ref.revision == 1
    assert adapted.ref.variant_id == variant_id
    assert adapted.owner_id == PARENT_OWNER
    assert adapted.content.specs[0].value == Decimal("12")
    assert adapted.content.specs[0].sources == (reference(),)
    assert adapted.content.sources == (reference(),)
    assert "visibility" not in adapted.content.model_dump()


def test_source_null_selection_stays_null_and_reports_missing_sources():
    old = snapshot(1, PARENT_PRODUCT, 1, content())
    new = snapshot(2, PARENT_PRODUCT, 2, content(sources=None))
    req = request(old_parent=old, new_parent=new, pinned_parent=old.ref)
    candidate = accept_changes(req, selection(req, ("field/sources",)), ValidationPort())
    assert candidate.content.sources is None
    assert "sources" in candidate.content.model_fields_set
    assert "sources" not in candidate.content.deleted_fields
    assert any(item.code == "missing_definition_source" for item in candidate.missing)


def test_unchanged_unknown_spec_still_exposes_confirmation_requirement():
    unknown = specification(value=None, availability="unknown", state="proposed")
    item = differences(request((unknown,), (unknown,), (unknown,)))["specs/power"]
    assert item.classification == "unchanged"
    assert "unknown_requires_confirmation" in item.reconfirmation
    assert item.child.value.value is None


def test_adoption_repairs_only_the_selected_missing_override():
    old = specification()
    other = specification("unselected")
    req = request(
        (old, other),
        (specification(value="20"), other),
        (specification(value="20"), specification("unselected", "30")),
    )
    candidate = accept_changes(req, selection(req, ("specs/power",)), ValidationPort())
    remaining = {item.path for item in candidate.missing if item.code == "missing_override"}
    assert remaining == {"specs/unselected"}
