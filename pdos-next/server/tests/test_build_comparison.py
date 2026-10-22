from copy import deepcopy

import pytest

from pdos_next.domain.build_execution.comparison import compare_configurations


def basis():
    engineering = {
        "id": "engineering-1", "revision": 1, "definition_id": "definition-1",
        "definition_revision": 1, "bom_id": "bom-1", "bom_revision": 1,
        "design_versions": {"mechanical": None, "electronic": None, "firmware": None},
        "bom": {"lines": [{"key": "motor", "part_id": "part-1",
                           "expected_part_revision": 1, "quantity": "2.00", "unit": "ea",
                           "loss_rate": None, "critical": True, "notes": None}]},
    }
    manufacturing = {
        "id": "process-1", "revision": 1, "site": None, "line": None,
        "operations": [{"key": "assembly", "kind": "assembly", "depends_on": [],
                        "name": "Assemble", "bom_line_keys": ["motor"],
                        "cycle_time_minutes": None, "resource_requirements": []}],
    }
    return engineering, manufacturing


def test_unknown_to_explicit_zero_and_new_firmware_are_independent_differences():
    planned, process = basis()
    actual = deepcopy(planned)
    actual["bom"]["lines"][0]["loss_rate"] = "0"
    actual["design_versions"]["firmware"] = {"system": "synthetic", "revision": "r2"}
    result = compare_configurations(planned, process, actual, process)
    assert {row["path"] for row in result} == {
        "engineering.bom.lines.motor", "engineering.design_versions.firmware",
    }
    assert next(r for r in result if r["path"].endswith("motor"))["before"]["loss_rate"] is None
    assert planned["bom"]["lines"][0]["loss_rate"] is None


def test_decimal_scale_and_source_metadata_do_not_create_fictitious_changes():
    planned, process = basis()
    actual, manufactured = deepcopy(planned), deepcopy(process)
    actual["bom"]["lines"][0]["quantity"] = "2"
    actual.update(created_at="later", source_status="needs_recheck", owner_id="another")
    manufactured["operations"][0]["source_status"] = "needs_recheck"
    assert compare_configurations(planned, process, actual, manufactured) == []


def test_distinct_fixed_identity_remains_a_difference_even_with_same_content():
    planned, process = basis()
    actual = deepcopy(planned)
    actual["id"] = "engineering-2"
    assert compare_configurations(planned, process, actual, process) == [{
        "path": "engineering.configuration",
        "before": {"id": "engineering-1", "revision": 1},
        "after": {"id": "engineering-2", "revision": 1}, "label": "工程配置版本",
    }]


def test_added_removed_material_and_reordered_process_remain_explicit():
    planned, process = basis()
    process["operations"].append({"key": "inspect", "name": "Inspect", "kind": "inspection"})
    actual, manufactured = deepcopy(planned), deepcopy(process)
    actual["bom"]["lines"][0]["key"] = "new-motor"
    manufactured["operations"].reverse()
    result = {row["path"]: row for row in compare_configurations(
        planned, process, actual, manufactured,
    )}
    assert result["engineering.bom.lines.motor"]["after"] is None
    assert result["engineering.bom.lines.new-motor"]["before"] is None
    assert result["manufacturing.operation_order"]["after"] == ["inspect", "assembly"]


def test_duplicate_keys_cannot_hide_a_configuration_difference():
    planned, process = basis()
    actual = deepcopy(planned)
    actual["bom"]["lines"].append(deepcopy(actual["bom"]["lines"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        compare_configurations(planned, process, actual, process)
