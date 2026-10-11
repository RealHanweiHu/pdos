"""Pure proposal adapter checks, with no database or model calls."""

from copy import deepcopy
from decimal import Decimal, localcontext
from types import SimpleNamespace as NS
from uuid import UUID

import pytest

from pdos_next.domain.preproject import derivation
from pdos_next.domain.preproject.schemas import Groups, ItemInput, ProposalCreate, SpecItem
from pdos_next.errors import DomainError

PRODUCT, DEFINITION, PROPOSAL, CATEGORY, AUTHOR, SOURCE, PARAMETER = (
    UUID(int=i) for i in range(1, 8)
)


def reference():
    return {"type": "claim", "id": str(SOURCE), "version": 2, "statement": "Actual claim"}


def spec(**changes):
    return {
        "key": "pressure",
        "parameter": "Pressure",
        "parameter_id": str(PARAMETER),
        "parameter_version": 3,
        "value_type": "number",
        "availability": "known",
        "value": "12345678901234567890.12345678901234567890",
        "tolerance": "0.00000000000000000001",
        "unit": "Pa",
        "text": None,
        "test_conditions": ["25 C", "nominal voltage"],
        "condition_note": "Calibrated",
        "method": "Gauge",
        "acceptance_criterion": "Within tolerance",
        "modality": "must",
        "exceptions": [{"market": "EU"}],
        "applicable_variants": [{"name": "A"}],
        "nature": "observed",
        "item_status": "confirmed",
        "owner_id": str(AUTHOR),
        "reason": "Parent fact",
        "source_refs": [reference()],
        "origin": "human",
        "writer_id": str(AUTHOR),
        "run_id": None,
        "confirmed_by": str(AUTHOR),
        "receipt_id": str(UUID(int=20)),
        **changes,
    }


def view(**changes):
    return {
        "id": str(DEFINITION),
        "revision": 4,
        "category_id": str(CATEGORY),
        "product_id": str(PRODUCT),
        "variant_id": None,
        "title": "Parent definition",
        "status": "published",
        "sealed": True,
        "purpose": "Parent purpose",
        "specs": [spec()],
        **changes,
    }


def payload(items=(), **changes):
    return ProposalCreate(
        **{
            "title": "Derivative",
            "entry_kind": "derivative",
            "baseline_product_id": PRODUCT,
            "baseline_definition_id": DEFINITION,
            "baseline_definition_revision": 4,
            "groups": Groups(items=list(items)),
            **changes,
        }
    )


def given_spec(**changes):
    return ItemInput(
        kind="spec",
        content={
            "key": "pressure",
            "parameter": "Pressure",
            "value_type": "number",
            "availability": "known",
            "value": "200",
            **changes,
        },
        source_refs=[reference()],
    )


def difference(**changes):
    return ItemInput(
        kind="difference",
        content={
            "area": "specification",
            "item_ref": "pressure",
            "change": "changed",
            "reason": "Explicit user decision",
            "impact": "Requires another test",
            "applicability": "Proposed product for EU",
            "sources": [reference()],
            **changes,
        },
    )


def document(items=(), **changes):
    return {
        "id": str(PROPOSAL),
        "revision": 2,
        "entry_kind": "derivative",
        "target_kind": "new_product",
        "baseline_product_id": str(PRODUCT),
        "baseline_definition_id": str(DEFINITION),
        "baseline_definition_revision": 4,
        "items": [item.model_dump(mode="json") for item in items],
        **changes,
    }


@pytest.fixture
def parent(monkeypatch):
    parent, calls = view(), []

    def read(*args, **kwargs):
        calls.append((args, kwargs))
        return deepcopy(parent)

    monkeypatch.setattr(derivation, "published_baseline", read)
    return NS(view=parent, calls=calls)


def test_plain_proposal_does_not_read_parent(parent):
    item = given_spec()
    p = payload(
        [item],
        entry_kind="new_product",
        baseline_product_id=None,
        baseline_definition_id=None,
        baseline_definition_revision=None,
    )
    baseline, items = derivation.prepare_create("s", "c", p)
    assert baseline is None and items == [item] and not parent.calls
    assert items[0] is not item


@pytest.mark.parametrize(
    "entry,target", [("derivative", "new_product"), ("new_product", "new_variant")]
)
def test_parent_is_read_with_exact_user_reference(parent, entry, target):
    baseline, _ = derivation.prepare_create("s", "c", payload(entry_kind=entry, target_kind=target))
    assert baseline == parent.view
    assert parent.calls == [
        (("s", "c", PRODUCT, 4), {"definition_id": DEFINITION, "extra_refs": []})
    ]


def test_unavailable_parent_is_not_replaced_by_payload(monkeypatch):
    def denied(*args, **kwargs):
        raise DomainError("SOURCE_UNAVAILABLE", "Unavailable")

    monkeypatch.setattr(derivation, "published_baseline", denied)
    with pytest.raises(DomainError, match="Unavailable"):
        derivation.prepare_create(None, None, payload([given_spec()]))


@pytest.mark.parametrize(
    "kind,values",
    [
        ("number", {"value": "12345678901234567890.12345678901234567890"}),
        (
            "range",
            {"value": None, "lower": "0.000000000000000001", "upper": "999.000000000000000001"},
        ),
        ("text", {"value": None, "text": "precise statement"}),
        ("boolean", {"value": None, "text": "false"}),
        ("enum", {"value": None, "text": "blue"}),
    ],
)
def test_inherits_full_semantics_without_borrowing_signature(parent, kind, values):
    parent.view["specs"] = [spec(value_type=kind, **values)]
    original = deepcopy(parent.view)
    with localcontext() as context:
        context.prec = 4
        _, items = derivation.prepare_create(None, None, payload())
    actual = items[0]
    content = SpecItem.model_validate(actual.content)
    assert content.value_type == kind
    for field in (
        "parameter_id",
        "parameter_version",
        "unit",
        "condition_note",
        "test_conditions",
        "modality",
        "exceptions",
        "applicable_variants",
        "nature",
        "availability",
        "acceptance_criterion",
        "reason",
    ):
        assert str(getattr(content, field)) == str(original["specs"][0][field])
    assert content.tolerance == Decimal(original["specs"][0]["tolerance"])
    assert content.verification_method == "Gauge"
    assert content.owner_id is None and content.item_status == "unknown"
    assert not derivation.PROVENANCE_FIELDS.intersection(actual.content)
    assert len(actual.source_refs) == 1
    ref = actual.source_refs[0]
    assert (ref.type, ref.id, ref.version, ref.statement) == (
        "definition",
        DEFINITION,
        4,
        "specs/pressure",
    )
    assert content.text_value == values.get("text")
    assert content.value == (Decimal(values["value"]) if values.get("value") is not None else None)
    assert content.lower == (Decimal(values["lower"]) if values.get("lower") is not None else None)
    assert parent.view == original


@pytest.mark.parametrize("availability", ["unknown", "conflicted", "not_applicable"])
def test_unknown_and_not_applicable_never_become_facts(parent, availability):
    parent.view["specs"] = [spec(availability=availability, value=None, item_status="unknown")]
    _, items = derivation.prepare_create(None, None, payload())
    assert items[0].content["availability"] == availability
    assert items[0].content["value"] is None and items[0].content["item_status"] == "unknown"


def test_ai_parent_does_not_launder_ai_signature(parent):
    parent.view["specs"] = [spec(origin="ai_draft", run_id=str(UUID(int=30)))]
    _, items = derivation.prepare_create(None, None, payload())
    assert items[0].content["item_status"] == "ai_draft"
    assert not derivation.PROVENANCE_FIELDS.intersection(items[0].content)


def test_explicit_spec_wins_with_own_sources_and_preserves_difference(parent):
    replacement, diff = given_spec(item_status="confirmed"), difference()
    _, items = derivation.prepare_create(None, None, payload([replacement, diff]))
    assert [item.kind for item in items] == ["spec", "difference"]
    assert items[0] == replacement and items[1].content == diff.content
    assert items[1].source_refs == replacement.source_refs and not diff.source_refs


@pytest.mark.parametrize(
    "item_ref",
    [
        "pressure",
        "specs/pressure",
        {"key": "pressure"},
        {"path": "specs/pressure"},
        {"parameter_id": str(PARAMETER), "version": 3},
        f"{PARAMETER}@3",
    ],
)
def test_explicit_removal_uses_exact_parent_reference(parent, item_ref):
    _, items = derivation.prepare_create(
        None, None, payload([difference(change="removed", item_ref=item_ref)])
    )
    assert [item.kind for item in items] == ["difference"]


def test_escaped_key_removal(parent):
    parent.view["specs"] = [spec(key="pressure/a~b")]
    _, items = derivation.prepare_create(
        None, None, payload([difference(change="removed", item_ref="specs/pressure~1a~0b")])
    )
    assert [item.kind for item in items] == ["difference"]


def test_other_area_does_not_remove_spec(parent):
    _, items = derivation.prepare_create(
        None, None, payload([difference(change="removed", area="bom")])
    )
    assert [item.kind for item in items] == ["spec", "difference"]


@pytest.mark.parametrize(
    "items,reason",
    [
        ([given_spec(), given_spec()], "duplicate_spec_key"),
        ([given_spec(), difference(change="removed")], "derivation_conflicting_override"),
        ([difference(change="removed", item_ref="absent")], "derivation_item_reference_invalid"),
        (
            [difference(change="removed", item_ref={"parameter_id": str(PARAMETER), "version": 2})],
            "derivation_item_reference_invalid",
        ),
        ([difference(origin="human")], "derivation_provenance_supplied"),
    ],
)
def test_ambiguous_or_forged_input_cannot_silently_change_meaning(parent, items, reason):
    with pytest.raises(DomainError) as error:
        derivation.prepare_create(None, None, payload(items))
    assert error.value.detail["reason"] == reason


def test_validate_reads_frozen_exact_reference(parent):
    assert derivation.validate_baseline("s", "c", NS(frozen_document=document())) == parent.view
    assert parent.calls == [
        (("s", "c", PRODUCT, 4), {"definition_id": DEFINITION, "extra_refs": []})
    ]


def test_validate_plain_skips_parent(parent):
    assert derivation.validate_baseline(None, None, {"entry_kind": "new_product"}) is None
    assert not parent.calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("baseline_product_id", None),
        ("baseline_definition_id", None),
        ("baseline_definition_revision", 0),
    ],
)
def test_validate_rejects_incomplete_reference(parent, field, value):
    with pytest.raises(DomainError) as error:
        derivation.validate_baseline(None, None, document(**{field: value}))
    assert error.value.detail["reason"] == "baseline_not_published" and not parent.calls


def test_validate_detects_row_document_mismatch(parent):
    with pytest.raises(DomainError) as error:
        derivation.validate_baseline(
            None, None, NS(**document()), document(baseline_definition_revision=3)
        )
    assert error.value.code == "VERSION_CONFLICT" and not parent.calls


def test_calculation_uses_real_fixed_parent_and_actual_child(monkeypatch):
    original, calls = derivation.variants.compare_snapshots, []

    def compare(request, **kwargs):
        calls.append((request, kwargs))
        return original(request, **kwargs)

    monkeypatch.setattr(derivation.variants, "compare_snapshots", compare)
    result = derivation.calculation(view(), document([given_spec(), difference()]))
    request, mode = calls[0]
    assert request.old_parent == request.new_parent
    assert (
        request.old_parent.ref.definition_id == DEFINITION and request.old_parent.ref.revision == 4
    )
    assert request.child.ref.definition_id == PROPOSAL and request.child.ref.revision == 2
    assert request.child.content.specs[0].value == Decimal("200")
    assert mode == {"allow_same_parent": True}
    assert result["proposal"] == {"id": str(PROPOSAL), "revision": 2, "kind": "proposal"}
    assert result["baseline"]["definition_id"] == str(DEFINITION)
    assert len(request.overrides) == 1
    assert (
        request.overrides[0].reason == "Explicit user decision"
        and request.overrides[0].sources[0].id == SOURCE
    )
    assert result["difference_traces"][0]["content"]["impact"] == "Requires another test"


def test_calculation_deletion_is_absence_not_unknown():
    result = derivation.calculation(view(), document([difference(change="removed")]))
    row = next(row for row in result["differences"] if row["path"] == "specs/pressure")
    assert row["child"]["state"] == "deleted"


@pytest.mark.parametrize(
    "change",
    [{"impact": "Another impact"}, {"reason": "Another reason"}, {"applicability": "US only"}],
)
def test_request_digest_binds_difference_trace(change):
    a = derivation.calculation(view(), document([given_spec(), difference()]))
    b = derivation.calculation(view(), document([given_spec(), difference(**change)]))
    assert a["request_digest"] != b["request_digest"]


def test_request_digest_binds_proposal_revision():
    doc = document([given_spec(), difference()])
    a = derivation.calculation(view(), doc)
    b = derivation.calculation(view(), doc, revision=3)
    assert a["request_digest"] != b["request_digest"] and doc["revision"] == 2


@pytest.mark.parametrize(
    "change,code",
    [
        ({"reason": None}, "difference_reason_missing"),
        ({"applicability": None}, "difference_applicability_missing"),
        ({"item_ref": "absent"}, "difference_reference_unknown"),
        ({"change": "removed"}, "difference_value_mismatch"),
    ],
)
def test_incomplete_difference_is_diagnostic(change, code):
    result = derivation.calculation(view(), document([given_spec(), difference(**change)]))
    assert code in {row["code"] for row in result["missing"]}
    assert result["difference_traces"][0]["content"] == difference(**change).content


def test_calculation_requires_real_identity_and_revision():
    with pytest.raises(DomainError) as error:
        derivation.calculation(view(), {"items": []})
    assert error.value.detail["reason"] == "proposal_revision_required"


@pytest.mark.parametrize("field", ["baseline_product_id", "baseline_definition_id"])
def test_validate_invalid_uuid_is_domain_error(parent, field):
    with pytest.raises(DomainError) as error:
        derivation.validate_baseline(None, None, document(**{field: "bad-id"}))
    assert error.value.detail["reason"] == "baseline_not_published" and not parent.calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("baseline_product_id", str(UUID(int=50))),
        ("baseline_definition_id", str(UUID(int=51))),
        ("baseline_definition_revision", 3),
    ],
)
def test_calculation_does_not_compare_another_parent(field, value):
    with pytest.raises(DomainError) as error:
        derivation.calculation(view(), document(**{field: value}))
    assert error.value.detail["reason"] == "baseline_version_changed"


def test_calculation_unknown_change_is_not_invented_as_set():
    result = derivation.calculation(view(), document([given_spec(), difference(change="maybe")]))
    assert "difference_change_unknown" in {row["code"] for row in result["missing"]}


def test_calculation_invalid_proposal_uuid_is_domain_error():
    with pytest.raises(DomainError) as error:
        derivation.calculation(view(), document(id="bad-id"))
    assert error.value.detail["reason"] == "proposal_revision_required"


def test_duplicate_traces_are_preserved_without_picking_one():
    result = derivation.calculation(
        view(), document([given_spec(), difference(), difference(reason="Another decision")])
    )
    assert len(result["difference_traces"]) == 2
    assert "duplicate_difference_trace" in {row["code"] for row in result["missing"]}


def test_unknown_child_retains_unknown_and_actual_source_and_author(monkeypatch):
    original, calls = derivation.variants.compare_snapshots, []

    def compare(request, **kwargs):
        calls.append(request)
        return original(request, **kwargs)

    monkeypatch.setattr(derivation.variants, "compare_snapshots", compare)
    doc = document([given_spec(availability="unknown", value=None)])
    doc["items"][0].update(origin="ai_draft", writer_id=str(AUTHOR), run_id=str(UUID(int=40)))
    derivation.calculation(view(), doc)
    child = calls[0].child.content.specs[0]
    assert child.availability == "unknown" and child.value is None
    assert child.origin == "ai_draft" and child.writer_id == AUTHOR and child.run_id == UUID(int=40)
    assert child.source_refs[0].id == SOURCE
