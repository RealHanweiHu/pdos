"""Synthetic, in-memory Build preparation checks; no database fixtures are needed."""

from copy import deepcopy
from decimal import Decimal, getcontext, localcontext
from socket import socket

import pytest
from pydantic import ValidationError

from pdos_next.domain.builds.readiness import compute_readiness


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Pure readiness checks cannot use network")

    monkeypatch.setattr(socket, "connect", forbidden)


def snapshot():
    version = {"revision": 1, "created_at": "2026-10-01T00:00:00Z", "source_state": "current"}
    return {
        "as_of": "2026-10-02T00:00:00Z",
        "build": {**version, "id": "synthetic-build", "quantity": "10", "unit": "ea"},
        "engineering_configuration": {
            **version,
            "id": "synthetic-engineering",
            "definition_id": "synthetic-definition",
            "bom": {
                **version,
                "id": "synthetic-bom",
                "lines": [
                    {
                        "key": "component-1",
                        "part_id": "synthetic-part",
                        "quantity": "2",
                        "unit": "ea",
                        "loss_rate": "0.05",
                        "critical": True,
                    }
                ],
            },
        },
        "manufacturing_configuration": {
            **version,
            "id": "synthetic-manufacturing",
            "operations": [{"key": "assembly", "title": "Synthetic assembly"}],
        },
    }


def check(result, key):
    return next(row for row in result["checks"] if row["key"] == key)


def test_known_decimal_demand_reuses_bom_loss_without_promising_stock_or_start():
    result = compute_readiness(snapshot())
    demand = result["demands"][0]
    assert Decimal(demand["required_quantity"]) == Decimal("21")
    assert Decimal(demand["quantity_per_product"]) == Decimal("2.1")
    assert demand["material_id"] == "synthetic-part" and demand["unit"] == "ea"
    assert check(result, "material_demand")["status"] == "known"
    assert check(result, "material_demand")["blocking"] is False
    assert result["ready"] is None and result["hard_blocking"] is True
    assert result["status"] == "unknown" and "score" not in result
    assert check(result, "supply_coverage")["blocking"] is True


def test_supply_snapshot_is_explicitly_unconnected_and_has_complete_engine_basis():
    result = compute_readiness(snapshot())
    coverage = result["coverage"]
    fixed = coverage["input_snapshot"]
    assert fixed["supply_scope_complete"] is False
    assert fixed["pools"] == fixed["reservations"] == fixed["alternates"] == []
    assert fixed["supply_snapshot"]["state"] == "unknown"
    assert fixed["as_of"] == result["as_of"]
    assert len(coverage["input_sha256"]) == len(result["input_sha256"]) == 64
    assert coverage["secured_ready"] is None and coverage["potential_ready"] is None
    assert coverage["critical_secured_ready"] is None
    assert coverage["lines"][0]["secured_gap"] is None
    assert coverage["lines"][0]["uses"] == []


def test_operation_claims_do_not_prove_resources_methods_or_release():
    data = snapshot()
    data["manufacturing_configuration"]["operations"][0].update(
        {
            "equipment_accepted": True,
            "quality_method_approved": True,
            "manufacturing_released": True,
            "capacity": "9999999",
        }
    )
    result = compute_readiness(data)
    for key in ("resources", "quality_method", "engineering_release", "manufacturing_release"):
        gate = check(result, key)
        assert gate["status"] == "unknown" and gate["blocking"] is True
        assert gate["message"] and gate["recovery_action"] and gate["reason_code"]
    assert (
        result["input_snapshot"]["manufacturing_configuration"]["operations"][0][
            "equipment_accepted"
        ]
        is True
    )
    assert result["ready"] is None


@pytest.mark.parametrize("field", ["quantity", "unit", "loss_rate"])
def test_missing_bom_requirement_stays_unknown(field):
    data = snapshot()
    data["engineering_configuration"]["bom"]["lines"][0][field] = None
    result = compute_readiness(data)
    assert result["demands"][0]["required_quantity"] is None
    assert check(result, "material_demand")["status"] == "unknown"
    assert result["coverage"]["secured_ready"] is None


@pytest.mark.parametrize("field", ["quantity", "unit"])
def test_missing_build_scope_cannot_form_known_demand(field):
    data = snapshot()
    data["build"][field] = None
    result = compute_readiness(data)
    assert result["demands"][0]["required_quantity"] is None
    assert check(result, "material_demand")["blocking"] is True


def test_known_number_with_unknown_part_mapping_does_not_become_complete_demand():
    data = snapshot()
    data["engineering_configuration"]["bom"]["lines"][0]["part_id"] = None
    result = compute_readiness(data)
    assert Decimal(result["demands"][0]["required_quantity"]) == Decimal("21")
    demand_check = check(result, "material_demand")
    assert demand_check["status"] == "unknown"
    assert "material_mapping_unknown" in {row["code"] for row in demand_check["issues"]}


@pytest.mark.parametrize("missing", ["engineering", "bom", "lines"])
def test_absent_or_empty_bom_is_not_vacuously_complete(missing):
    data = snapshot()
    if missing == "engineering":
        data["engineering_configuration"] = None
    elif missing == "bom":
        data["engineering_configuration"]["bom"] = None
    else:
        data["engineering_configuration"]["bom"]["lines"] = []
    result = compute_readiness(data)
    assert result["demands"] == []
    assert check(result, "material_demand")["status"] == "unknown"
    assert result["ready"] is None
    if missing == "lines":
        assert result["coverage"]["secured_ready"] is None
    else:
        assert result["coverage"] is None


@pytest.mark.parametrize("state", ["stale", "withdrawn", "unknown"])
@pytest.mark.parametrize("kind", ["build", "engineering_configuration", "bom"])
def test_noncurrent_quantity_source_cannot_produce_known_demand(kind, state):
    data = snapshot()
    record = data["engineering_configuration"]["bom"] if kind == "bom" else data[kind]
    record["source_state"] = state
    result = compute_readiness(data)
    assert result["demands"][0]["required_quantity"] is None
    assert result["status"] == ("unknown" if state == "unknown" else "blocked")
    assert check(result, "fixed_sources")["blocking"] is True


@pytest.mark.parametrize("invalidity", ["future", "expired"])
def test_source_time_is_checked_against_fixed_as_of(invalidity):
    data = snapshot()
    if invalidity == "future":
        data["build"]["created_at"] = "2026-10-03T00:00:00Z"
    else:
        data["build"]["valid_until"] = data["as_of"]
    result = compute_readiness(data)
    assert result["status"] == "blocked"
    assert result["demands"][0]["required_quantity"] is None


def test_missing_source_validity_is_unknown_without_assuming_current():
    data = snapshot()
    del data["engineering_configuration"]["source_state"]
    result = compute_readiness(data)
    assert result["input_snapshot"]["engineering_configuration"]["source_state"] == "unknown"
    assert result["demands"][0]["required_quantity"] is None


def test_stale_manufacturing_source_blocks_without_erasing_known_engineering_demand():
    data = snapshot()
    data["manufacturing_configuration"]["source_state"] = "withdrawn"
    result = compute_readiness(data)
    assert result["status"] == "blocked"
    assert Decimal(result["demands"][0]["required_quantity"]) == Decimal("21")
    assert check(result, "manufacturing_release")["status"] == "unknown"


def test_loss_above_supported_ratio_preserves_original_and_does_not_clip_demand():
    data = snapshot()
    data["engineering_configuration"]["bom"]["lines"][0]["loss_rate"] = "2"
    result = compute_readiness(data)
    assert (
        result["input_snapshot"]["engineering_configuration"]["bom"]["lines"][0]["loss_rate"] == "2"
    )
    assert result["demands"][0]["required_quantity"] is None
    assert "loss_rate_unsupported" in {
        row["code"] for row in check(result, "material_demand")["issues"]
    }


def test_duplicate_bom_keys_are_a_conflict_not_double_counted_demand():
    data = snapshot()
    lines = data["engineering_configuration"]["bom"]["lines"]
    lines.append(deepcopy(lines[0]))
    result = compute_readiness(data)
    assert result["status"] == "blocked" and len(result["demands"]) == 1
    assert result["demands"][0]["required_quantity"] is None
    assert check(result, "material_demand")["status"] == "blocked"


@pytest.mark.parametrize("quantity", [0, "-1", True, 0.5, "NaN", "1e1000000"])
def test_invalid_numbers_fail_before_calculation(quantity):
    data = snapshot()
    data["build"]["quantity"] = quantity
    with pytest.raises(ValidationError):
        compute_readiness(data)


@pytest.mark.parametrize("extra", [{"pools": []}, {"supply_scope_complete": True}, {"ready": True}])
def test_callers_cannot_smuggle_supplies_or_readiness_into_snapshot(extra):
    with pytest.raises(ValidationError):
        compute_readiness({**snapshot(), **extra})


def test_naive_as_of_is_rejected_instead_of_using_machine_timezone():
    data = snapshot()
    data["as_of"] = "2026-10-02T00:00:00"
    with pytest.raises(ValidationError):
        compute_readiness(data)


def test_fixed_input_is_deterministic_and_does_not_mutate_original_or_decimal_context():
    data = snapshot()
    before = deepcopy(data)
    baseline = compute_readiness(data)
    with localcontext() as context:
        context.prec = 3
        context.rounding = "ROUND_DOWN"
        assert compute_readiness(data) == baseline
        assert getcontext().prec == 3 and getcontext().rounding == "ROUND_DOWN"
    assert data == before and compute_readiness(data) == baseline
    assert baseline["as_of"] == "2026-10-02T00:00:00Z"


def test_hash_binds_manufacturing_operations_and_part_mapping_metadata():
    original = snapshot()
    baseline = compute_readiness(original)
    changed = deepcopy(original)
    changed["manufacturing_configuration"]["operations"][0]["title"] = "Changed fixed operation"
    assert compute_readiness(changed)["input_sha256"] != baseline["input_sha256"]
    changed = deepcopy(original)
    changed["engineering_configuration"]["bom"]["lines"][0]["metadata"] = {
        "part": {"mapping_version": "v2", "erp_number": "synthetic-reference"},
        "notes": None,
    }
    mapped = compute_readiness(changed)
    assert mapped["input_sha256"] != baseline["input_sha256"]
    assert mapped["coverage"]["input_sha256"] != baseline["coverage"]["input_sha256"]


def test_count_build_units_and_component_unit_range_are_not_guessed():
    data = snapshot()
    data["build"]["unit"] = "kg"
    assert compute_readiness(data)["demands"][0]["required_quantity"] is None
    data = snapshot()
    data["engineering_configuration"]["bom"]["lines"][0]["unit"] = "box"
    result = compute_readiness(data)
    assert result["demands"][0]["required_quantity"] is None
    assert "unit_unsupported" in {row["code"] for row in check(result, "material_demand")["issues"]}


def test_fixed_context_metadata_changes_basis_hash_without_granting_qualification():
    data = snapshot()
    baseline = compute_readiness(data)
    data["build"]["metadata"] = {
        "purpose": "Synthetic customer sample verification",
        "verification_objectives": "Synthetic surface inspection",
        "required_source_read_set": [{"artifact_id": "synthetic-source", "expected_revision": 1}],
        "claimed_authorized": True,
    }
    data["engineering_configuration"]["metadata"] = {
        "definition_revision": 1,
        "design_versions": {"firmware": {"revision": "synthetic-v2"}},
        "claimed_engineering_release": True,
    }
    data["manufacturing_configuration"]["metadata"] = {
        "site": "Synthetic site",
        "line": "Synthetic line",
        "claimed_manufacturing_release": True,
    }
    result = compute_readiness(data)
    assert result["input_sha256"] != baseline["input_sha256"]
    assert result["coverage"]["input_sha256"] != baseline["coverage"]["input_sha256"]
    assert result["input_snapshot"]["build"]["metadata"] == data["build"]["metadata"]
    assert result["demands"] == baseline["demands"]
    for key in ("resources", "quality_method", "engineering_release", "manufacturing_release"):
        assert check(result, key)["status"] == "unknown"
    assert result["ready"] is None and result["hard_blocking"] is True
