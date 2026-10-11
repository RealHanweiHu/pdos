"""Pure seed conversion tests; no database fixtures or runtime credentials."""

import json
from pathlib import Path

import pytest

from pdos_next.domain.preproject.category_seed import convert_seed

SEEDS = Path(__file__).resolve().parents[4] / "docs/design/category-seeds"


def seed(name):
    return json.loads((SEEDS / f"{name}.json").read_text())


def preview(name):
    return convert_seed(seed(name), (SEEDS / "sources.md").read_text())


def test_complete_seed_material_and_state_preserved():
    parameter_count = test_count = regulation_count = 0
    for name in ("auto-tire-inflator", "bicycle-pump"):
        original = seed(name)
        result = preview(name)
        assert result.origin == "imported"
        assert result.raw_document == original
        assert result.raw_document["origin"] == "ai_draft"
        assert result.sources_markdown == (SEEDS / "sources.md").read_text()
        category = result.categories[0]
        assert category.raw == original["categories"][0]
        assert category.key == name
        parameter_count += len(category.parameters)
        tests = category.raw["test_template"]
        test_count += len(tests["items"])
        assert tests["specifications_frozen"] is False
        assert {item["state"] for item in tests["items"]} == {"expert_pending"}
        regulations = category.raw["regulations"]["items"]
        regulation_count += len(regulations)
        assert {item["applicability_state"] for item in regulations} == {"expert_pending"}
        assert {item["compliance_state"] for item in regulations} == {"not_assessed"}
        assert {item["classification_state"] for item in regulations} == {"ai_draft"}
        for mapped, raw in zip(category.parameters, category.raw["parameters"], strict=True):
            assert mapped.raw == raw
            assert mapped.key == raw["key"] == mapped.seed_parameter_id
            assert mapped.version == 1
            assert mapped.name == raw["label"]
            assert mapped.value_type == raw["value_type"]
            assert mapped.unit == raw["unit"]
            assert mapped.standard_condition == raw["conditions"]
            assert mapped.method == raw["verification_method"]
            assert mapped.acceptance_criterion == raw["acceptance_criterion"]
            assert mapped.source_origin == "ai_draft"
            assert mapped.source_status == raw["status"]
            assert mapped.source_ids == tuple(raw["source_ids"])
    assert (parameter_count, test_count, regulation_count) == (61, 61, 87)


def test_category_local_keys_and_pending_states():
    auto = preview("auto-tire-inflator").categories[0]
    bike = preview("bicycle-pump").categories[0]
    assert sum(p.source_status == "expert_pending" for p in bike.parameters) == 14
    assert sum(p.source_status == "expert_pending" for p in auto.parameters) == 18
    auto_pressure = next(p for p in auto.parameters if p.key == "max_pressure")
    bike_pressure = next(p for p in bike.parameters if p.key == "max_pressure")
    assert auto_pressure.standard_condition != bike_pressure.standard_condition
    assert bike.raw["dictionary_conventions"]["coverage_gaps"]
    assert "CO₂" in bike.raw["dictionary_conventions"]["form_groups"]


def test_unknown_fields_stay_null_and_input_is_not_mutated():
    document = seed("bicycle-pump")
    parameter = document["categories"][0]["parameters"][0]
    parameter.pop("conditions")
    parameter["verification_method"] = None
    parameter["acceptance_criterion"] = None
    parameter["unit"] = None
    result = convert_seed(document, "Original source catalogue")
    converted = result.categories[0].parameters[0]
    assert converted.standard_condition is None
    assert converted.method is None
    assert converted.acceptance_criterion is None
    assert converted.unit is None
    assert converted.enum_values is None
    assert "conditions" not in parameter
    parameter["expert_open_points"].append("Later edit")
    assert "Later edit" not in converted.raw["expert_open_points"]
    assert "Later edit" not in result.raw_document["categories"][0]["parameters"][0][
        "expert_open_points"
    ]


def test_missing_source_catalogue_and_duplicate_keys_are_rejected():
    document = seed("bicycle-pump")
    with pytest.raises(ValueError, match="catalogue"):
        convert_seed(document, " ")
    parameters = document["categories"][0]["parameters"]
    parameters.append(parameters[0])
    with pytest.raises(ValueError, match="Duplicate parameter"):
        convert_seed(document, "Original sources")
