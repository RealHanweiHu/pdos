"""Pure payload checks; no persistence, authority, model or network fixtures."""

from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.preproject.schemas import PreparedContent, Reference, SpecItem
from pdos_next.schemas.products.definition_items import DefinitionItemOp, DefinitionItemPatch


def spec(**changes):
    return {"key": "pressure", "parameter": "Pressure", "value_type": "number", **changes}


def ref(**changes):
    return {
        "type": "human",
        "id": str(uuid4()),
        "version": 1,
        "statement": "Synthetic named decision",
        **changes,
    }


def upsert(**changes):
    return {"op": "upsert", "content": spec(), **changes}


def patch(*ops, **changes):
    return {"definition_id": str(uuid4()), "ops": list(ops) or [upsert()], **changes}


def test_complete_shared_model_keeps_conditions_sources_and_all_m3_fields():
    content = spec(
        parameter_id=str(uuid4()),
        parameter_version=3,
        availability="known",
        value="0",
        tolerance="0",
        unit="PSI",
        condition_note="Nonstandard source condition",
        test_conditions=["25 °C", "12 V"],
        verification_method="Source-defined measurement",
        acceptance_criterion="Source-defined threshold",
        modality="should",
        exceptions=[{"text": "except during startup", "applies_to": "startup"}],
        applicable_variants=[{"variant_id": str(uuid4())}],
        nature="decided",
        item_status="confirmed",
        owner_id=str(uuid4()),
        reason="Synthetic named decision",
    )
    source = ref(type="snapshot", line=5, quote="Source-defined threshold")
    body = patch(upsert(content=content, source_refs=[source]))
    before = deepcopy(body)
    op = DefinitionItemPatch.model_validate(body).ops[0]
    assert isinstance(op.content, SpecItem) and isinstance(op.source_refs[0], Reference)
    assert op.content.model_dump(mode="json") == SpecItem.model_validate(content).model_dump(
        mode="json"
    )
    assert op.source_refs[0].model_dump(mode="json") == Reference.model_validate(source).model_dump(
        mode="json"
    )
    assert op.content.value == Decimal(0) and op.content.tolerance == Decimal(0)
    assert body == before


@pytest.mark.parametrize("availability", ["unknown", "conflicted", "not_applicable"])
def test_unavailable_values_remain_null_and_never_acquire_a_zero(availability):
    content = spec(availability=availability, reason="Not applicable to this variant")
    actual = DefinitionItemPatch.model_validate(patch(upsert(content=content))).ops[0].content
    assert (actual.value, actual.lower, actual.upper, actual.text_value) == (None,) * 4
    for field, value in (("value", "0"), ("lower", "0"), ("upper", "0"), ("text_value", "false")):
        with pytest.raises(ValidationError, match="Unknown values must remain null"):
            DefinitionItemPatch.model_validate(patch(upsert(content={**content, field: value})))


@pytest.mark.parametrize(
    "content",
    [
        spec(availability="known", value="0"),
        spec(value_type="range", availability="known", lower="0", upper="0"),
        spec(value_type="boolean", availability="known", text_value="false"),
        spec(value_type="enum", availability="known", text_value="off"),
    ],
)
def test_known_zero_false_and_enum_keep_shared_shape(content):
    actual = DefinitionItemPatch.model_validate(patch(upsert(content=content))).ops[0].content
    assert actual.model_dump(mode="json") == SpecItem.model_validate(content).model_dump(
        mode="json"
    )


@pytest.mark.parametrize(
    "content",
    [
        spec(availability="known"),
        spec(value_type="range", availability="known", lower="2", upper="1"),
        spec(availability="known", value="0", text_value="false"),
        spec(value_type="boolean", availability="known", value=False),
        spec(value_type="boolean", availability="known", text_value="False"),
        spec(tolerance="-0.1"),
        spec(parameter_id=str(uuid4())),
        spec(parameter_version=2),
        spec(parameter_id=str(uuid4()), parameter_version=0),
    ],
)
def test_invalid_values_and_parameter_version_ambiguity_are_rejected(content):
    with pytest.raises(ValidationError):
        DefinitionItemPatch.model_validate(patch(upsert(content=content)))


def test_confirmed_requires_a_value_or_reason_and_source_without_granting_ai_authority():
    known = spec(availability="known", value="0", item_status="confirmed")
    with pytest.raises(ValidationError, match="Confirmed specifications need a source"):
        DefinitionItemPatch.model_validate(patch(upsert(content=known)))
    with pytest.raises(ValidationError, match="Confirmed items need a value"):
        DefinitionItemPatch.model_validate(
            patch(upsert(content=spec(item_status="confirmed"), source_refs=[ref()]))
        )
    # Shape cannot decide writer/run policy; that remains the actual domain owner's check.
    candidate = DefinitionItemPatch.model_validate(
        patch(
            upsert(content=known, source_refs=[ref()]),
            prepared_by_run_id=str(uuid4()),
            candidate_digest="a" * 64,
        )
    )
    assert candidate.ops[0].content.item_status == "confirmed"
    content = spec(availability="not_applicable", item_status="confirmed", reason="Not used")
    assert (
        DefinitionItemPatch.model_validate(patch(upsert(content=content, source_refs=[ref()])))
        .ops[0]
        .content.value
        is None
    )
    with pytest.raises(ValidationError):
        DefinitionItemPatch.model_validate(
            patch(upsert(content={**content, "reason": "  "}, source_refs=[ref()]))
        )


@pytest.mark.parametrize("nature", ["observed", "extracted", "computed", "inferred", "decided"])
@pytest.mark.parametrize("status", ["ai_draft", "expert_pending", "unknown"])
def test_owner_nature_and_status_keep_shared_semantics(nature, status):
    owner = uuid4()
    actual = (
        DefinitionItemPatch.model_validate(
            patch(upsert(content=spec(owner_id=str(owner), nature=nature, item_status=status)))
        )
        .ops[0]
        .content
    )
    assert (actual.owner_id, actual.nature, actual.item_status) == (owner, nature, status)


@pytest.mark.parametrize(
    "operation",
    [
        upsert(base_version=1),
        upsert(item_id=str(uuid4())),
        {"op": "remove"},
        {"op": "remove", "item_id": str(uuid4())},
        {"op": "remove", "base_version": 1},
        {"op": "upsert"},
        upsert(content=None),
    ],
)
def test_new_update_remove_and_content_are_unambiguous(operation):
    with pytest.raises(ValidationError):
        DefinitionItemPatch.model_validate(patch(operation))


@pytest.mark.parametrize("version", [0, -1, True, False, 1.0, "1"])
def test_base_version_requires_positive_integer_without_coercion(version):
    with pytest.raises(ValidationError):
        DefinitionItemPatch.model_validate(
            patch(upsert(item_id=str(uuid4()), base_version=version))
        )


@pytest.mark.parametrize("extra", [{"content": None}, {"content": {}}, {"source_refs": []}])
def test_remove_rejects_even_empty_content_or_sources(extra):
    with pytest.raises(ValidationError):
        DefinitionItemPatch.model_validate(
            patch({"op": "remove", "item_id": str(uuid4()), "base_version": 3, **extra})
        )


def test_valid_new_update_and_remove_preserve_exact_versions():
    existing, removed = uuid4(), uuid4()
    value = DefinitionItemPatch.model_validate(
        patch(
            upsert(item_id=None, base_version=None),
            upsert(item_id=str(existing), base_version=7, content=spec(key="temperature")),
            {"op": "remove", "item_id": str(removed), "base_version": 4},
        )
    )
    assert value.ops[0].item_id is None and value.ops[0].base_version is None
    assert (value.ops[1].item_id, value.ops[1].base_version) == (existing, 7)
    assert (value.ops[2].item_id, value.ops[2].base_version) == (removed, 4)
    assert value.ops[2].content is None and value.ops[2].source_refs == []
    assert DefinitionItemPatch.model_validate(value.model_dump(exclude_unset=True)) == value


def test_batch_rejects_duplicate_existing_item_including_remove_collision():
    identity = str(uuid4())
    with pytest.raises(ValidationError, match="same item twice"):
        DefinitionItemPatch.model_validate(
            patch(
                upsert(item_id=identity, base_version=1),
                {"op": "remove", "item_id": identity, "base_version": 1},
            )
        )


def test_batch_rejects_duplicate_normalized_key_and_empty_batch():
    with pytest.raises(ValidationError, match="keys cannot repeat"):
        DefinitionItemPatch.model_validate(
            patch(
                upsert(item_id=str(uuid4()), base_version=1),
                upsert(content=spec(key=" pressure ")),
            )
        )
    with pytest.raises(ValidationError):
        DefinitionItemPatch.model_validate(patch(ops=[]))


@pytest.mark.parametrize(
    "kind",
    ["human", "artifact", "original", "snapshot", "knowledge", "parameter", "definition", "claim"],
)
def test_all_existing_source_kinds_reuse_shared_reference(kind):
    actual = DefinitionItemOp.model_validate(upsert(source_refs=[ref(type=kind)]))
    assert actual.source_refs[0].type == kind and actual.source_refs[0].version == 1


@pytest.mark.parametrize("change", [{"version": 0}, {"line": 0}, {"type": "invented"}])
def test_invalid_source_shape_is_rejected(change):
    with pytest.raises(ValidationError):
        DefinitionItemOp.model_validate(upsert(source_refs=[ref(**change)]))


@pytest.mark.parametrize(
    "field",
    [
        "tenant_id",
        "category_id",
        "product_id",
        "writer_id",
        "run_id",
        "actor_id",
        "requester_id",
        "origin",
        "confirmed_by",
        "receipt_id",
        "visibility",
        "private_context",
        "qualification_id",
        "write_tier",
        "policy",
        "sealed",
    ],
)
@pytest.mark.parametrize("location", ["payload", "op", "content", "reference"])
def test_scope_policy_and_provenance_are_rejected_at_each_typed_boundary(field, location):
    body = patch()
    if location == "payload":
        target = body
    elif location == "op":
        target = body["ops"][0]
    elif location == "content":
        target = body["ops"][0]["content"]
    else:
        body["ops"][0]["source_refs"] = [ref()]
        target = body["ops"][0]["source_refs"][0]
    target[field] = str(uuid4())
    with pytest.raises(ValidationError):
        DefinitionItemPatch.model_validate(body)


def test_t1_fields_reuse_actual_prepared_content_shape_only():
    assert issubclass(DefinitionItemPatch, PreparedContent)
    run = uuid4()
    actual = DefinitionItemPatch.model_validate(
        patch(prepared_by_run_id=str(run), candidate_digest="b" * 64, confirmation_token="opaque")
    )
    assert actual.prepared_by_run_id == run and actual.candidate_digest == "b" * 64
    assert actual.confirmation_token == "opaque"
    for fields in (
        {"prepared_by_run_id": str(run)},
        {"candidate_digest": "b" * 64},
        {"prepared_by_run_id": str(run), "candidate_digest": "not-a-digest"},
    ):
        with pytest.raises(ValidationError):
            DefinitionItemPatch.model_validate(patch(**fields))


def test_legacy_fields_and_nested_prepared_authority_are_not_alternate_inputs():
    for field in ("text", "method", "state", "sources", "confirmed_by", "prepared_by_run_id"):
        with pytest.raises(ValidationError):
            DefinitionItemPatch.model_validate(
                patch(upsert(content=spec(**{field: "not-an-alias"})))
            )
