"""The three tier sets partition PAYLOADS, and every registered command is catalogued."""

import json
from pathlib import Path

import pytest

from pdos_next.core.command_handlers import (
    T0_OPERATIONS,
    T1_OPERATIONS,
    T2_OPERATIONS,
    tier_of,
)
from pdos_next.core.contracts import PAYLOADS
from pdos_next.core.service import EVENTS
from pdos_next.errors import DomainError

CONTRACTS = Path(__file__).resolve().parents[4] / "contracts"


def _catalog():
    entries = {}
    for name in ("operations.json", "auxiliary-operations.json"):
        for entry in json.loads((CONTRACTS / name).read_text())["items"]:
            assert entry["operation"] not in entries, entry["operation"]
            entries[entry["operation"]] = (name, entry)
    return entries


def test_tiers_partition_registered_payloads():
    assert T0_OPERATIONS | T1_OPERATIONS | T2_OPERATIONS == set(PAYLOADS)
    assert not T0_OPERATIONS & T1_OPERATIONS
    assert not T0_OPERATIONS & T2_OPERATIONS
    assert not T1_OPERATIONS & T2_OPERATIONS


def test_unregistered_operation_is_refused_not_defaulted():
    with pytest.raises(DomainError) as failure:
        tier_of("evidence.artifact.register.unregistered")
    assert failure.value.reason == "WRITE_TIER_UNREGISTERED"
    assert failure.value.code == "FORBIDDEN_SCOPE"


def test_every_registered_command_is_catalogued_with_its_actual_tier():
    catalog = _catalog()
    for operation in sorted(PAYLOADS):
        assert operation in catalog, operation
        _, entry = catalog[operation]
        assert entry["write_tier"] == tier_of(operation), operation
        assert entry["event"] == EVENTS[operation], operation


def test_catalogued_slices_are_actually_registered():
    for operation, (_, entry) in _catalog().items():
        if entry.get("implementation") == "implemented_local_slice":
            assert operation in PAYLOADS, operation


def test_source_catalog_validator_runs_clean():
    """The derived catalogs still match the frozen v1.1 source they record."""
    import subprocess
    import sys

    root = CONTRACTS.parent
    result = subprocess.run(
        [sys.executable, str(root / "tools/validate_contracts.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def _validate_copy(tmp_path, change):
    """Run the validator on a copy of the contracts after one deliberate change."""
    import shutil
    import subprocess
    import sys

    root = CONTRACTS.parent
    source = "docs/design/2026-10-08-pdos-complete-target-architecture-v1.1.md"
    shutil.copytree(CONTRACTS, tmp_path / "contracts")
    (tmp_path / "tools").mkdir()
    shutil.copy(root / "tools/validate_contracts.py", tmp_path / "tools")
    (tmp_path / source).parent.mkdir(parents=True)
    shutil.copy(root / source, tmp_path / source)
    change(tmp_path / "contracts")
    return subprocess.run(
        [sys.executable, str(tmp_path / "tools/validate_contracts.py")],
        capture_output=True,
        text=True,
    )


def _edit(path, update):
    data = json.loads(path.read_text())
    update(data)
    path.write_text(json.dumps(data, ensure_ascii=False))


def test_validator_rejects_acceptance_text_that_differs_from_appendix_b(tmp_path):
    def change(contracts):
        def update(data):
            item = next(i for i in data["items"] if i["id"] == "AT-57")
            item["expected"] += "（改动）"

        _edit(contracts / "acceptance.json", update)

    assert _validate_copy(tmp_path, lambda contracts: None).returncode == 0
    result = _validate_copy(tmp_path / "changed", change)
    assert result.returncode != 0 and "AT-57 differs from appendix B" in result.stderr


def test_validator_rejects_an_unregistered_dingtalk_write_endpoint(tmp_path):
    def change(contracts):
        def update(data):
            data["paths"]["/v1/personal/dingtalk/unregistered"] = {"post": {}}

        _edit(contracts / "openapi.json", update)

    result = _validate_copy(tmp_path, change)
    assert result.returncode != 0
    assert "Unregistered write endpoint: POST /v1/personal/dingtalk/unregistered" in result.stderr
