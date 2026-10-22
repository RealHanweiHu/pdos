"""Native integration boundaries; no database or external services."""

import subprocess
import sys
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.engine import Engine

from pdos_next.command_handlers import PHASED_MATERIAL_OPERATIONS, T1_OPERATIONS, handler
from pdos_next.domain.build_operational_facts.execution_scope import OperationalScope
from pdos_next.domain.build_operational_facts.schemas import OperationalScope as ReexportedScope
from pdos_next.domain.manufacturing_trials import native_service as native
from pdos_next.errors import DomainError
from pdos_next.schemas.manufacturing_trials.pilot_results import RecordedBatch

from .test_pilot_results import AT, batch


@pytest.fixture(autouse=True)
def no_io(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Native pure integration must not connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


@pytest.mark.parametrize("operation", ["npi.pilot.create", "npi.pilot.result.record"])
def test_actual_common_registry_uses_one_phased_t1_handler(operation):
    assert operation in T1_OPERATIONS
    assert operation in PHASED_MATERIAL_OPERATIONS
    assert handler(operation) is native
    assert native.EVENTS[operation] in {"pilot.created", "pilot.results_recorded"}


@pytest.mark.parametrize(
    "entry",
    [
        "pdos_next.domain.build_operational_facts.schemas",
        "pdos_next.domain.manufacturing_trials.native_schemas",
        "pdos_next.domain.manufacturing_trials.native_models",
        "pdos_next.contracts",
    ],
)
def test_public_schema_entry_points_finish_the_same_registry(entry):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import {entry}; from pdos_next.contracts import PAYLOADS; "
            "assert 'npi.pilot.create' in PAYLOADS; "
            "assert 'npi.pilot.result.record' in PAYLOADS",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert OperationalScope is ReexportedScope


def correction(*, window_open=False):
    original = batch()
    raw = original.model_dump(mode="json")
    if window_open:
        end = (AT + timedelta(hours=1)).isoformat()
        raw["fixed"]["yield_scope"]["window_end"] = end
        raw["record"]["scope"]["window_end"] = end
        original = RecordedBatch.model_validate(raw)
    raw["fixed"]["pilot_revision"] = 2
    raw["record"].update(
        expected_pilot_revision=2,
        observation_id=str(uuid4()),
        previous_observation_id=str(original.record.observation_id),
        correction_reason="原始观察补正，保留前件",
    )
    return original, RecordedBatch.model_validate(raw)


@pytest.mark.parametrize("window_open", [False, True])
def test_correction_retains_fixed_basis_even_before_window_is_final(window_open):
    original, current = correction(window_open=window_open)
    result = native._correction(original, current, checked_at=AT)
    assert result is None if window_open else result.observation_id == current.record.observation_id


def test_correction_retains_verified_history_without_promoting_unknown_current_resource():
    original, current = correction()
    assert native._correction(original, current, checked_at=AT, project_allowed=False) is None
    changed = current.model_copy(
        update={"fixed": current.fixed.model_copy(update={"site": "另一场地"})}
    )
    with pytest.raises(DomainError):
        native._correction(original, changed, checked_at=AT, project_allowed=False)


@pytest.mark.parametrize("window_open", [False, True])
@pytest.mark.parametrize("change", ["site", "time", "reason", "input"])
def test_correction_rejects_changed_scope_lineage_clock_or_denominator(window_open, change):
    original, current = correction(window_open=window_open)
    raw = current.model_dump(mode="json")
    if change == "site":
        raw["fixed"]["site"] = "另一实际场地"
    elif change == "time":
        raw["record"]["observed"]["occurred_at"] = (AT - timedelta(seconds=1)).isoformat()
    elif change == "reason":
        raw["record"]["previous_observation_id"] = str(uuid4())
    else:
        raw["record"]["counts"]["input_count"] = 11
    current = RecordedBatch.model_validate(raw)
    with pytest.raises(DomainError):
        native._correction(original, current, checked_at=AT)
