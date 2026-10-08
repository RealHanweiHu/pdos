from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from pdos_next.schemas.manufacturing_trials.contracts import Parameter, ResultRecord

from .helpers import NOW, SOURCE, create_pilot, creation, record, ref


@pytest.mark.parametrize(
    "field,kind",
    [
        ("manufacturing_baseline", "process_revision"),
        ("line", "equipment"),
        ("first_article", "sample"),
        ("control_plan", "risk"),
    ],
)
def test_typed_authority_references_not_arbitrary_strings(field, kind):
    with pytest.raises(ValidationError):
        type(creation()).model_validate({**creation().model_dump(), field: ref(kind)})


@pytest.mark.parametrize(
    "value,unit,source",
    [
        (Decimal("1"), None, SOURCE),
        (Decimal("1"), "mm", None),
        (Decimal("NaN"), "mm", SOURCE),
        (Decimal("Infinity"), "mm", SOURCE),
    ],
)
def test_parameter_values_require_exact_source_unit_finite(value, unit, source):
    with pytest.raises(ValidationError):
        Parameter(key="pressure", value=value, unit=unit, source=source)


def test_unknown_parameter_remains_null():
    value = Parameter(key="pressure", value=None, unit=None, source=None)
    assert value.value is None and value.unit is None


@pytest.mark.parametrize("change", ["naive", "bad_zone", "outside_window", "inverted_window"])
def test_time_source_and_window_contracts(change):
    _, _, _, pilot = create_pilot()
    payload = record(pilot).model_dump()
    if change == "naive":
        payload["observed"]["occurred_at"] = NOW.replace(tzinfo=None)
    elif change == "bad_zone":
        payload["observed"]["original_timezone"] = "Made/Up"
    elif change == "outside_window":
        payload["observed"]["occurred_at"] = NOW - timedelta(days=1)
    else:
        payload["scope"]["window_start"] = NOW + timedelta(days=1)
    with pytest.raises(ValidationError):
        ResultRecord.model_validate(payload)


def test_correction_requires_reason_and_unknown_fields_closed():
    _, _, _, pilot = create_pilot()
    for changes in (
        {"previous_observation_id": ref("sample").id},
        {"correction_reason": "孤立原因"},
        {"approved": True},
    ):
        with pytest.raises(ValidationError):
            ResultRecord.model_validate({**record(pilot).model_dump(), **changes})


def test_frozen_payload_cannot_be_mutated():
    with pytest.raises(ValidationError):
        creation().purpose = "静默修改"
