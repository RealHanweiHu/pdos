"""Measured admission floors (D248): data-backed, never below 15%, frozen per request."""

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

from pdos_next.agent.kernel import context_calibration
from pdos_next.agent.kernel.context_budget import fit_messages, measure
from pdos_next.agent.kernel.gateway import AgentGateway
from pdos_next.errors import DomainError
from tests.agent.kernel.test_bound_read_host import make_host
from tests.agent.kernel.test_gateway import configured_route

ROOT = Path(__file__).resolve().parents[4]
EVIDENCE = (
    ROOT / "docs/reports/evidence/pdos-next-real-eval-20261105/d248-estimate-calibration.json"
)


def minimax():
    return replace(configured_route(), model="MiniMax-M3", context_window_tokens=48_000 + 20_384,
                   max_output_tokens=16_384)


def message(text="充气泵参数" * 200):
    return [{"role": "user", "content": json.dumps({"goal": text, "context": {}},
                                                   ensure_ascii=False)}]


def test_shipped_floors_are_the_decided_ones_and_match_their_evidence():
    default, floors = context_calibration.load()
    assert default == context_calibration.LEGACY_FLOOR == 1.15
    assert floors == {
        ("openai-compatible", "MiniMax-M3", "main"): 1.22,
        ("openai-compatible", "MiniMax-M3", "isolated"): 1.15,
    }
    evidence = json.loads(EVIDENCE.read_text())["ratios"]
    entries = json.loads(context_calibration.CONFIGURATION.read_text())["routes"]
    for entry in entries:
        measured = evidence[f"all/{entry['isolation']}"]
        assert entry["evidence"] == str(EVIDENCE.relative_to(ROOT))
        assert {k: entry["measured"][k] for k in ("calls", "p50", "p95", "max")} == {
            k: measured[k] for k in ("calls", "p50", "p95", "max")
        }


@pytest.mark.parametrize(
    ("model", "isolation", "expected"),
    [
        ("MiniMax-M3", "main", 1.22),
        ("MiniMax-M3", "assistant_extract", 1.15),
        ("MiniMax-M3", "research_subtask", 1.15),
        ("synthetic-model", "main", 1.15),  # Unmeasured: the design's 15% floor.
    ],
)
def test_floor_is_chosen_by_protocol_model_and_isolation_class(model, isolation, expected):
    route = replace(configured_route(), model=model)
    assert context_calibration.floor_for(route, isolation) == expected
    anthropic = replace(route, protocol="anthropic-native")
    assert context_calibration.floor_for(anthropic, isolation) == 1.15


def base_configuration():
    return json.loads(context_calibration.CONFIGURATION.read_text())


@pytest.mark.parametrize(
    "change",
    [
        lambda v: v.update(default_floor=1.10),
        lambda v: v["routes"][0].update(floor=1.12),  # Below the default floor.
        lambda v: v["routes"][0].update(floor=1.20),  # Below its measured max 1.211.
        lambda v: v["routes"][0].update(evidence=""),
        lambda v: v["routes"].append(dict(v["routes"][0])),
        lambda v: v["routes"][0].update(isolation="assistant_extract"),
        lambda v: v.update(schema="other/v1"),
    ],
)
def test_configuration_that_would_shrink_or_lose_its_basis_is_rejected(tmp_path, change):
    value = base_configuration()
    change(value)
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        context_calibration.load(path)


def test_measured_floor_raises_admission_and_previous_actual_can_still_raise_it():
    route, messages = minimax(), message()
    old = measure(route, "fixed", [], messages)
    new = measure(route, "fixed", [], messages, floor=1.22)
    assert old["calibration_factor"] == 1.15 and new["calibration_factor"] == 1.22
    assert new["admission_tokens"] == math.ceil(new["estimated_total"] * 1.22)
    assert new["admission_tokens"] >= old["admission_tokens"]
    assert new["calibration_floor"] == 1.22 and new["estimation_margin"] == 0.22
    previous = {"estimated_total": 100, "actual_input_tokens": 130}
    assert measure(route, "fixed", [], messages, calibration=previous,
                   floor=1.22)["calibration_factor"] == 1.3
    small = {"estimated_total": 100, "actual_input_tokens": 110}
    assert measure(route, "fixed", [], messages, calibration=small,
                   floor=1.22)["calibration_factor"] == 1.22


def test_floor_reaches_every_measurement_of_the_reduction_loop():
    route = replace(minimax(), context_window_tokens=1_000 + 20_384)
    messages = message("参" * 840)  # estimate 848: 975 at 1.15, 1035 at 1.22
    _, admitted = fit_messages(route, "", [], messages)
    assert admitted["calibration_factor"] == 1.15 and not admitted["over_focus"]
    with pytest.raises(DomainError) as error:
        fit_messages(route, "", [], messages, floor=1.22)
    assert error.value.detail["context_budget"]["calibration_factor"] == 1.22


def test_gateway_freezes_the_floor_per_request_and_replays_old_admissions_with_1_15(
    monkeypatch,
):
    f = make_host()
    gateway = AgentGateway(f.store, route_for=lambda _: minimax(), cost_required=False,
                           client=object())
    assert gateway.context_admission(f.scope, minimax(), "first") == (None, 1.22)
    assert f.run.versions["context_admissions"]["first"] == {"calibration": None, "floor": 1.22}
    # A later calibration file cannot change a request that was already admitted.
    monkeypatch.setattr(context_calibration, "floor_for", lambda *_: 1.5)
    assert gateway.context_admission(f.scope, minimax(), "first") == (None, 1.22)
    assert gateway.context_admission(f.scope, minimax(), "second") == (None, 1.5)
    # Admitted before floors were recorded: replays under the floor then in force.
    f.run.versions = {**f.run.versions, "context_admissions": {
        **f.run.versions["context_admissions"], "legacy": {"calibration": None},
    }}
    assert gateway.context_admission(f.scope, minimax(), "legacy") == (None, 1.15)
    assert gateway.context_baseline(f.scope, minimax(), "legacy") is None
