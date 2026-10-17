"""Pure native declarations/JSON, never an owner or professional qualification."""

import json
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from psycopg.types.json import Jsonb, JsonbDumper
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg
from sqlalchemy.engine import Engine

from pdos_next.domain.manufacturing_trials.native_models import NativePilotRun
from pdos_next.domain.manufacturing_trials.native_schemas import (
    CREATE_EVENT,
    RESULT_EVENT,
    PilotCreatePayload,
    PilotResultPayload,
    StatisticsBasis,
    json_snapshot,
    semantic,
)

from .helpers import NOW, SCOPE, SOURCE, creation, ref
from .test_pilot_results import batch


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Native schema checks must never connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


def statistics(**changes):
    values = dict(
        site="合成试产线",
        original_timezone="Asia/Shanghai",
        window_start=NOW - timedelta(hours=2),
        window_end=NOW,
        cohort_mode="entire_lot",
        samples=(ref("sample", 41), ref("sample", 42)),
        statistics_basis_key="本Pilot原文口径",
        criterion_id=UUID(int=50),
        criterion_text="  首遍合格判据  保留原始间隔  ",
        minimum_sample=2,
        operation_key="assemble",
        source=SOURCE,
    )
    return StatisticsBasis(**{**values, **changes})


def test_minimal_creation_keeps_unknown_statistics_and_typed_defaults_without_mutation():
    raw = {"project_id": SCOPE.project_id, "details": creation().model_dump()}
    before = deepcopy(raw)
    payload = PilotCreatePayload.model_validate(raw)
    saved = semantic(payload)
    assert payload.statistics is None and payload.visibility == "private"
    assert saved["statistics"] is None and saved["details"]["line"] is None
    assert saved["details"]["people"] == [] and saved["details"]["parameters"] == []
    assert "confirmation_token" not in saved
    assert saved["details"]["pilot_id"] == str(creation().pilot_id)
    assert raw == before
    assert CREATE_EVENT == "pilot.created" and RESULT_EVENT == "pilot.results_recorded"


@pytest.mark.parametrize("field", ["qualified", "start_authorized", "actor_id", "nature"])
def test_client_cannot_add_authority_or_nature_to_creation(field):
    with pytest.raises(ValidationError):
        PilotCreatePayload.model_validate(
            {"project_id": SCOPE.project_id, "details": creation(), field: True}
        )


def test_statistical_wording_is_retained_without_inventing_a_fixed_scope_or_policy():
    declared = statistics()
    assert declared.criterion_text == "  首遍合格判据  保留原始间隔  "
    assert declared.criterion_revision == 1 and declared.operational_scope is None
    assert not {"fixed_scope", "nature", "qualified", "start_authorized"} & set(
        declared.model_dump()
    )
    assert statistics(samples=()).samples == ()  # No fake enumerated membership.
    assert statistics(cohort_mode="fixed_sampled_subset").cohort_mode == "fixed_sampled_subset"
    with pytest.raises(ValidationError):
        StatisticsBasis.model_validate({**declared.model_dump(), "qualified": True})


@pytest.mark.parametrize(
    "changes",
    [
        {"original_timezone": "Made/Up"},
        {"window_start": NOW.replace(tzinfo=None)},
        {"window_end": NOW - timedelta(hours=2)},
        {"window_end": NOW - timedelta(hours=3)},
        {"minimum_sample": 0},
        {"minimum_sample": True},
        {"criterion_revision": 2},
        {"criterion_revision": True},
        {"samples": (ref("line", 41),)},
        {"samples": (ref("sample", 41), ref("sample", 41).model_copy(update={"revision": 2}))},
    ],
)
def test_statistics_rejects_impossible_windows_wrong_refs_and_nonfixed_criterion(changes):
    with pytest.raises(ValidationError):
        statistics(**changes)


def test_operational_scope_is_only_a_declared_json_value_and_keeps_its_original_timezone():
    declared = statistics(
        operational_scope={
            "purpose": "合成试产",
            "quantity": "2.00",
            "unit": "ea",
            "site": "合成试产线",
            "window": {
                "start": NOW - timedelta(hours=2),
                "finish": NOW,
                "original_timezone": "Asia/Shanghai",
            },
        }
    )
    saved = declared.model_dump(mode="json")
    assert saved["operational_scope"]["quantity"] == "2"
    assert saved["operational_scope"]["window"]["original_timezone"] == "Asia/Shanghai"
    assert "authorized" not in saved["operational_scope"]


def test_result_keeps_actual_record_and_expected_revision_for_first_and_correction():
    original = batch()
    for expected in (1, 2):
        record = original.record.model_dump()
        record["expected_pilot_revision"] = expected
        if expected == 2:
            record.update(previous_observation_id=UUID(int=60), correction_reason="修正原观察")
        payload = PilotResultPayload(
            pilot_id=original.fixed.pilot_id,
            expected_pilot_revision=expected,
            record=record,
        )
        assert semantic(payload)["record"]["expected_pilot_revision"] == expected
        assert payload.record.counts == original.record.counts
        with pytest.raises(ValidationError):
            PilotResultPayload.model_validate(
                {**payload.model_dump(), "expected_pilot_revision": expected + 1}
            )


def test_confirmation_projection_keeps_original_request_and_private_key_untouched():
    payload = PilotCreatePayload(
        project_id=SCOPE.project_id,
        details=creation(),
        statistics=statistics(),
        confirmation_token="synthetic-confirmation-token-unchanged",
    )
    command = {
        "command_id": UUID(int=70),
        "idempotency_key": "original-private-key",
        "payload": payload.model_dump(),
    }
    before = deepcopy(command)
    canonical = semantic(payload)
    assert "confirmation_token" not in canonical
    assert canonical["details"]["manufacturing_baseline"] is None
    assert (
        command == before and payload.confirmation_token == before["payload"]["confirmation_token"]
    )
    with pytest.raises(TypeError):
        semantic(command["payload"])


def test_actual_jsonb_driver_accepts_recursively_normalized_nested_owner_material():
    native = {
        "owners": {"project": {"id": SCOPE.project_id, "read_at": NOW}},
        "declaration": PilotCreatePayload(project_id=SCOPE.project_id, details=creation()),
        "exact_quantity": Decimal("2.500"),
        "samples": (ref("sample", 41),),
    }
    value = json_snapshot(native)
    process = NativePilotRun.__table__.c.material_snapshot.type.dialect_impl(
        PGDialect_psycopg()
    ).bind_processor(PGDialect_psycopg())
    encoded = JsonbDumper(Jsonb).dump(process(value))
    assert json.loads(encoded) == json.loads(json.dumps(value, allow_nan=False))
    assert native["owners"]["project"]["id"] is SCOPE.project_id
    assert isinstance(native["exact_quantity"], Decimal)
