from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.agent_kernel.m3_extracted_match import map_spec
from pdos_next.agent_kernel.m3_spec_compare import AgentSpecCompareInput
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.errors import DomainError


def parameter(**changes):
    return SimpleNamespace(
        parameter_id=uuid4(),
        version=2,
        key="noise",
        name="噪声",
        value_type="number",
        unit="dB(A)",
        **changes,
    )


def spec(**changes):
    return {
        "key": "noise",
        "parameter": "噪声",
        "value_type": "number",
        "upper": "75",
        "unit": None,
        "condition_note": None,
        "availability": "known",
        **changes,
    }


def test_exact_mapping_preserves_missing_customer_fields_and_one_sided_bounds():
    p = parameter()
    raw = spec()
    before = deepcopy(raw)
    required, mapped = map_spec(raw, [p], lambda *_: pytest.fail("No explicit selector"))
    assert mapped["status"] == "mapped" and mapped["basis"] == "exact_dictionary_label"
    assert required.parameter_id == p.parameter_id and required.parameter_version == 2
    assert required.unit is required.condition_note is required.lower is required.value is None
    assert str(required.upper) == "75" and required.item_status == "ai_draft"
    assert required.nature == "extracted" and required.owner_id is None and raw == before


def test_conflicting_exact_labels_stay_ambiguous_and_unrecognized_names_stay_unmapped():
    first = parameter()
    other = SimpleNamespace(parameter_id=uuid4(), version=1, key="sound", name="噪声")
    required, result = map_spec(spec(), [first, other], lambda *_: None)
    assert result["status"] == "ambiguous" and len(result["candidates"]) == 2
    assert required.parameter_id is required.parameter_version is None
    required, result = map_spec(
        spec(key="unfamiliar", parameter="陌生参数"), [first], lambda *_: None
    )
    assert result["status"] == "unmapped" and required.parameter_id is None


def test_explicit_historical_reference_is_not_silently_upgraded():
    old = parameter()
    old.version = 1
    new = deepcopy(old)
    new.version = 2
    required, mapped = map_spec(
        spec(parameter_id=str(old.parameter_id), parameter_version=1),
        [new],
        lambda identity, version: old,
    )
    assert required.parameter_version == 1 and mapped["basis"] == "extracted_reference"


def test_invalid_explicit_parameter_is_unmapped_without_fallback_or_value_rewrite():
    def missing(*_):
        raise DomainError("SOURCE_UNAVAILABLE", "not in this category")

    required, mapped = map_spec(
        spec(parameter_id=str(uuid4()), parameter_version=1), [parameter()], missing
    )
    assert mapped["status"] == "unmapped" and required.parameter_id is None
    assert str(required.upper) == "75" and required.unit is None


@pytest.mark.parametrize("indices", [[True], ["0"], [-1], [0, 0], []])
def test_row_selection_is_typed_and_cannot_smuggle_replacement_requirements(indices):
    with pytest.raises(ValidationError):
        AgentSpecCompareInput.model_validate(
            {
                "subjects": [{"type": "product", "id": uuid4()}],
                "extraction_ref": {"call_id": uuid4(), "row_indices": indices},
            }
        )


def test_registered_mode_accepts_only_actual_row_selectors_and_products():
    good = {
        "subjects": [{"type": "product", "id": uuid4()}],
        "extraction_ref": {"call_id": uuid4(), "row_indices": [0]},
    }
    assert AgentSpecCompareInput.model_validate(good).extraction_ref.row_indices == [0]
    for changes in (
        {"requirements": [spec()]},
        {"parameter_ids": [uuid4()]},
        {"subjects": [{"type": "proposal", "id": uuid4()}]},
        {"private_context": False},
    ):
        with pytest.raises(ValidationError):
            AgentSpecCompareInput.model_validate({**good, **changes})
    assert default_registry().get("calc.spec_compare").version == "5"
