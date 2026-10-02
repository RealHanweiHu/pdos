"""Saved resource dates cannot be reused after source or policy drift."""

from copy import deepcopy
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import Connection

from app.domain import resource_schedule_preparations as module
from app.domain.product_workspace import ProductWorkError
from tests.test_resource_reallocations import context


def evidence() -> dict[str, Any]:
    return {
        "ledger_identity_digest": "a" * 64,
        "policies": [{"policy_id": "policy", "version": 1}],
        "profiles": [{"id": "capacity", "parallel_units": "1"}],
        "reserved_intervals": [
            {
                "resource_id": "bench",
                "start": "2026-10-01T09:00:00Z",
                "end": "2026-10-01T17:00:00Z",
                "units": "1",
            }
        ],
        "priority_intervals": [],
        "legacy_missing": [],
    }


@pytest.mark.parametrize(
    "drift",
    ["policy", "capacity", "occupancy", "identity", "invalid_priority", "baseline_actual", None],
)
def test_current_solver_rejects_input_drift_instead_of_replacing_approved_content(
    monkeypatch: pytest.MonkeyPatch,
    drift: str | None,
) -> None:
    original, current = evidence(), evidence()
    if drift == "policy":
        current["policies"][0]["version"] = 2
    elif drift == "capacity":
        current["profiles"][0]["parallel_units"] = "2"
    elif drift == "occupancy":
        current["reserved_intervals"][0]["units"] = "0.5"
    elif drift == "identity":
        current["ledger_identity_digest"] = "b" * 64
    target = MagicMock()
    target.policy_errors = {uuid4(): "expired"} if drift == "invalid_priority" else {}
    target.evidence.return_value = current
    constructor = MagicMock(return_value=target)
    monkeypatch.setattr(module, "ResourceSolver", constructor)
    monkeypatch.setattr(module, "get_scenario", lambda *args: {"id": uuid4()})
    monkeypatch.setattr(
        module,
        "scenario_basis",
        lambda *args: {
            "basis_digest": "b" * 64 if drift == "baseline_actual" else "a" * 64,
        },
    )
    saved = {
        "scenario_id": uuid4(),
        "scenario_basis_digest": "a" * 64,
        "inputs": {"request_id": str(uuid4()), "demands": {}, "horizon_days": 90},
        "result": {"resource_solver": original},
    }
    frozen = deepcopy(saved)
    if drift is None:
        assert (
            module.current_solver(MagicMock(spec=Connection), context(), uuid4(), saved) is target
        )
    else:
        with pytest.raises(ProductWorkError, match="已变化"):
            module.current_solver(MagicMock(spec=Connection), context(), uuid4(), saved)
    if drift == "baseline_actual":
        constructor.assert_not_called()
    assert saved == frozen


def test_source_digest_is_order_independent_but_historical_missing_identity_is_rejected() -> None:
    original = evidence()
    original["policies"].append({"policy_id": "another", "version": 3})
    reversed_sources = deepcopy(original)
    reversed_sources["policies"].reverse()
    assert module.source_digest(original) == module.source_digest(reversed_sources)
    del reversed_sources["ledger_identity_digest"]
    with pytest.raises(ProductWorkError, match="原占用记录身份"):
        module.source_digest(reversed_sources)
