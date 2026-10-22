"""The three tier sets partition PAYLOADS, and every registered command is catalogued."""

import json
from pathlib import Path

import pytest

from pdos_next.command_handlers import (
    T0_OPERATIONS,
    T1_OPERATIONS,
    T2_OPERATIONS,
    tier_of,
)
from pdos_next.contracts import PAYLOADS
from pdos_next.errors import DomainError
from pdos_next.service import EVENTS

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"


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
