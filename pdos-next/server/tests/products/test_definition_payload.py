from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.products.definitions import difference, semantic
from pdos_next.schemas.products.definitions import DefinitionDraftPayload, DefinitionSpec


def reference():
    return {"artifact_id": str(uuid4()), "expected_revision": 1, "line": 2, "quote": "150 PSI"}


def spec(**overrides):
    return {
        "key": "pressure",
        "parameter": "Declared pressure",
        "value_type": "number",
        "availability": "unknown",
        "reason": "Condition remains unknown",
        "sources": [reference()],
        **overrides,
    }


def definition(**overrides):
    ref = reference()
    return {
        "title": "Synthetic definition",
        "purpose": "Source-bound synthetic verification",
        "use_cases": ["Synthetic fixture only"],
        "change_reason": "Create a synthetic draft",
        "sources": [ref],
        "specs": [spec(sources=[ref])],
        **overrides,
    }


@pytest.mark.parametrize("availability", ["unknown", "conflicted", "not_applicable"])
def test_unavailable_values_never_become_zero(availability):
    with pytest.raises(ValidationError):
        DefinitionSpec.model_validate(spec(availability=availability, value="0"))
    value = DefinitionSpec.model_validate(spec(availability=availability))
    assert value.value is None and value.lower is None and value.upper is None


@pytest.mark.parametrize("extra", ["tenant_id", "writer_id", "published_by", "status", "approval"])
def test_client_cannot_supply_trusted_context_or_publication(extra):
    with pytest.raises(ValidationError):
        DefinitionDraftPayload.model_validate(definition(**{extra: str(uuid4())}))


@pytest.mark.parametrize(
    "invalid",
    [
        {"availability": "known", "value": "150"},
        {"availability": "known", "value": "NaN", "unit": "PSI"},
        {"availability": "known", "value": "1e27", "unit": "PSI"},
        {"availability": "known", "value": "0.0000000000001", "unit": "PSI"},
        {
            "availability": "known",
            "value_type": "range",
            "lower": "151",
            "upper": "150",
            "unit": "PSI",
        },
        {"availability": "known", "value_type": "text", "text": "required", "value": "0"},
        {"state": "confirmed"},
    ],
)
def test_invalid_spec_shapes_and_claimed_confirmation_rejected(invalid):
    with pytest.raises(ValidationError):
        DefinitionSpec.model_validate(spec(**invalid))


def test_zero_is_retained_only_as_explicit_known_value_with_unit():
    value = DefinitionSpec.model_validate(spec(availability="known", value="0", unit="PSI"))
    assert str(value.value) == "0"


def test_parent_and_source_binding_are_exact_and_unique():
    body = definition(parent_definition_id=str(uuid4()))
    with pytest.raises(ValidationError):
        DefinitionDraftPayload.model_validate(body)
    body = definition()
    body["specs"][0]["sources"] = [reference()]
    with pytest.raises(ValidationError):
        DefinitionDraftPayload.model_validate(body)
    body = definition()
    body["specs"].append(deepcopy(body["specs"][0]))
    with pytest.raises(ValidationError):
        DefinitionDraftPayload.model_validate(body)


def test_semantic_identity_ignores_reference_and_spec_display_order():
    body = definition()
    other = reference()
    body["sources"].append(other)
    body["specs"].append(spec(key="temperature", sources=[other]))
    shuffled = deepcopy(body)
    shuffled["sources"].reverse()
    shuffled["specs"].reverse()
    assert semantic(DefinitionDraftPayload.model_validate(body)) == semantic(
        DefinitionDraftPayload.model_validate(shuffled)
    )


def test_diff_uses_stable_spec_identity_and_retains_history():
    before = {"title": "Original", "specs": [{"key": "pressure", "value": "150"}]}
    snapshot = deepcopy(before)
    after = {"title": "Revised", "specs": [{"key": "pressure", "value": "160"}]}
    changes = difference(before, after)
    assert {change["path"] for change in changes} == {"title", "specs/pressure"}
    assert (
        next(change for change in changes if change["path"] == "specs/pressure")["before"]["value"]
        == "150"
    )
    changes[1]["before"]["value"] = "900"
    assert before == snapshot
