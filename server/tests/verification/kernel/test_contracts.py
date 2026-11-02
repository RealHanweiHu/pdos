"""Consumer-visible data boundaries, with synthetic references only."""

from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from pdos_next.schemas.verification.contracts import (
    EventTime,
    NumericCriterion,
    RequestCreate,
)

from .helpers import NOW, build, document, event, item, measurement, request, run, source, uid


@pytest.mark.parametrize("bounds", [({},), ({"lower": "NaN"},), ({"upper": "Infinity"},)])
def test_criterion_rejects_missing_or_nonfinite_bound(bounds):
    with pytest.raises(ValidationError):
        NumericCriterion(**bounds[0], source=source())


def test_criterion_rejects_reversed_bounds():
    with pytest.raises(ValidationError):
        NumericCriterion(lower=Decimal("11"), upper=Decimal("9"), source=source())


@pytest.mark.parametrize("field", ["occurred_at", "effective_at"])
def test_event_rejects_unzoned_times(field):
    data = event().model_dump()
    data[field] = datetime(2026, 10, 2, 18)
    with pytest.raises(ValidationError):
        EventTime(**data)


def test_event_retains_original_zone_while_normalizing_utc():
    original = event().model_dump()
    original["occurred_at"] = "2026-10-02T11:00:00-07:00"
    current = EventTime(**original)
    assert current.occurred_at == NOW
    assert current.original_timezone == "America/Los_Angeles"


def test_event_rejects_unknown_original_zone():
    data = event().model_dump()
    data["original_timezone"] = "Imaginary/Factory"
    with pytest.raises(ValidationError):
        EventTime(**data)


def test_document_applicability_cannot_escape_requested_items():
    with pytest.raises(ValidationError):
        request(documents=(document(items=("not-requested",)),))


def test_test_item_identity_and_cavity_are_unique():
    with pytest.raises(ValidationError):
        request(items=(item(), item()))
    with pytest.raises(ValidationError):
        item(cavities=("A", "A"))


def test_payload_cannot_claim_server_scope_or_actor():
    data = dict(
        request_id=uid("new-request"), build_id=build().id, expected_build_revision=1,
        title="合成请求", purpose="合成尺寸", items=(item(),), return_form="原始读数",
        actor_id=uid("pretend-actor"), authorized=True,
    )
    with pytest.raises(ValidationError):
        RequestCreate(**data)


def test_reading_is_preserved_as_raw_text_and_missing_fields_are_not_defaults():
    current = measurement(raw="010.000", equipment=None, method=None, missing=("设备未知",))
    assert current.raw_value == "010.000"
    assert current.equipment is None and current.method is None
    assert current.missing == ("设备未知",)


def test_measurement_retains_original_zone_while_observed_instant_normalizes_utc():
    current = measurement(observed_at="2026-10-02T11:00:00-07:00",
                          observed_timezone="America/Los_Angeles")
    assert current.observed_at == NOW
    assert current.observed_timezone == "America/Los_Angeles"


def test_measurement_rejects_invalid_original_observation_zone():
    with pytest.raises(ValidationError):
        measurement(observed_timezone="Imaginary/Factory")


def expected_time_dto(kind, **changes):
    if kind == "aggregate":
        return request(**changes)
    return RequestCreate(
        request_id=uid("new-request"), build_id=build().id, expected_build_revision=1,
        title="合成验证请求", purpose="尺寸", items=(item(),), return_form="原始读数", **changes,
    )


@pytest.mark.parametrize("kind", ["command", "aggregate"])
def test_expected_at_requires_original_forecast_timezone(kind):
    with pytest.raises(ValidationError):
        expected_time_dto(kind, expected_at="2026-10-02T11:00:00-07:00")


@pytest.mark.parametrize("kind", ["command", "aggregate"])
def test_expected_at_normalizes_utc_and_preserves_original_forecast_timezone(kind):
    current = expected_time_dto(
        kind, expected_at="2026-10-02T11:00:00-07:00", expected_timezone="America/Los_Angeles",
    )
    assert current.expected_at == NOW
    assert current.expected_timezone == "America/Los_Angeles"


def test_execution_status_and_result_are_separate_dimensions():
    current = run(status="results_pending", result="fail")
    assert current.status == "results_pending" and current.result == "fail"
    with pytest.raises(ValidationError):
        run(status="pass")


def test_planned_build_dual_configuration_is_not_sample_actual_configuration():
    current = run()
    actual_ids = {s.actual_configuration.id for s in current.samples}
    assert current.build.engineering_configuration.id not in actual_ids
    assert current.build.manufacturing_configuration.id not in actual_ids
