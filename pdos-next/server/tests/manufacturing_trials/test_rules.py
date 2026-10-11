from decimal import Decimal

import pytest
from pydantic import ValidationError

from pdos_next.domain.manufacturing_trials.rules import aggregate, calculate, counts_from_units
from pdos_next.errors import DomainError
from pdos_next.schemas.manufacturing_trials.contracts import Counts, UnitOutcome

from .helpers import counts, create_pilot, record, ref


def test_first_final_rework_unique_input():
    result = calculate(counts(rework_cycles=100), 30)
    assert result.counts.input_count == 10
    assert result.first_pass_yield == Decimal("0.6")
    assert result.final_good_yield == Decimal("0.8")
    assert "INSUFFICIENT_SAMPLE" in result.warnings
    assert "INCOMPLETE_FINAL_RESULTS" in result.warnings
    assert result.process_capability == result.factory_qualification == "NOT_ASSESSED"


@pytest.mark.parametrize(
    "changes",
    [
        {"first_pass": 11},
        {"scrap": 2},
        {"first_failed": 3},
        {"output_count": 9},
        {"final_good": 5},
        {"reworked_good": 5},
        {"rework_cycles": 1},
        {"input_count": 0},
        {"unprocessed": 1},
        {"final_good": None, "scrap": 11},
    ],
)
def test_contradictory_counts(changes):
    with pytest.raises(DomainError):
        calculate(counts(**changes), 10)


@pytest.mark.parametrize("denominator", [None, 0])
def test_unknown_zero_denominator(denominator):
    result = calculate(Counts(**{k: denominator for k in Counts.model_fields}), 30)
    assert result.first_pass_yield is None and result.final_good_yield is None
    assert ("UNKNOWN_DENOMINATOR" if denominator is None else "ZERO_DENOMINATOR") in result.warnings


def test_partial_unknown_no_full_claim():
    result = calculate(counts(first_failed=3, first_unknown=1, final_good=None), 1)
    assert result.first_pass_yield is None and result.final_good_yield is None
    assert "MISSING_COUNTS" in result.warnings
    result = calculate(counts(scrap=None, rework_pending=None), 1)
    assert result.final_good_yield == Decimal("0.8")
    assert "INCOMPLETE_FINAL_RESULTS" in result.warnings


@pytest.mark.parametrize("value", [True, -1, 1.2, "3"])
def test_strict_counts(value):
    with pytest.raises(ValidationError):
        counts(input_count=value)


def test_unit_rework_and_duplicate_detection():
    _, _, _, pilot = create_pilot()
    original = record(pilot)
    units = tuple(
        UnitOutcome(
            sample=ref("sample", i + 100),
            first_result=first,
            final_state=final,
            rework_cycles=cycles,
            source=original.source,
        )
        for i, (first, final, cycles) in enumerate(
            (
                ("pass", "good", 0),
                ("fail", "good", 4),
                ("fail", "rework_pending", 2),
                ("unknown", "undecided", 0),
            )
        )
    )
    value = type(original).model_validate({**original.model_dump(), "counts": None, "units": units})
    result = calculate(counts_from_units(value), 20)
    assert result.counts.input_count == 4 and result.counts.rework_cycles == 6
    assert result.counts.first_pass == 1 and result.counts.final_good == 2
    assert result.first_pass_yield is None and result.final_good_yield == Decimal("0.5")
    with pytest.raises(ValidationError):
        type(value).model_validate({**value.model_dump(), "units": units + (units[0],)})


@pytest.mark.parametrize(
    "first,final,cycles",
    [
        ("pass", "scrap", 0),
        ("pass", "good", 1),
        ("unprocessed", "good", 0),
        ("fail", "good", 0),
        ("unprocessed", "unprocessed", 1),
    ],
)
def test_mutually_exclusive_unit_states(first, final, cycles):
    _, _, _, pilot = create_pilot()
    with pytest.raises(ValidationError):
        UnitOutcome(
            sample=ref("sample"),
            first_result=first,
            final_state=final,
            rework_cycles=cycles,
            source=record(pilot).source,
        )


def scopes():
    _, _, _, pilot = create_pilot()
    scope = record(pilot).scope
    other = type(scope).model_validate(
        {
            **scope.model_dump(),
            "basis": {
                **scope.basis.model_dump(),
                "lot": ref("build_lot", 99),
            },
        }
    )
    return scope, other


def test_aggregate_counts_not_average_percentages():
    scope, other = scopes()
    ten = counts(
        final_good=10,
        first_pass=10,
        first_failed=0,
        reworked_good=0,
        scrap=0,
        rework_pending=0,
        rework_cycles=0,
    )
    thirty = counts(
        input_count=30,
        output_count=30,
        first_pass=0,
        first_failed=30,
        final_good=0,
        reworked_good=0,
        scrap=30,
        rework_pending=0,
        rework_cycles=0,
    )
    result = aggregate(((scope, ten), (other, thirty)))
    assert result.counts.input_count == 40
    assert result.first_pass_yield == result.final_good_yield == Decimal("0.25")


@pytest.mark.parametrize(
    "field,value",
    [
        ("nature", "real"),
        ("minimum_sample", 31),
        ("criterion", ref("criterion", 555)),
        ("line", ref("line", 333)),
        ("manufacturing_baseline", ref("manufacturing_baseline", 444)),
    ],
)
def test_incompatible_aggregate(field, value):
    scope, other = scopes()
    other = type(other).model_validate({**other.model_dump(), field: value})
    with pytest.raises(DomainError) as error:
        aggregate(((scope, counts()), (other, counts())))
    assert error.value.reason == "INCOMPATIBLE_SCOPE"


@pytest.mark.parametrize(
    "field,value",
    [
        ("unit", "piece"),
        ("actual_configuration", ref("actual_configuration", 999)),
        ("process_revision", ref("process_revision", 777)),
        ("engineering_configuration", ref("engineering_configuration", 888)),
    ],
)
def test_incompatible_basis_aggregate(field, value):
    scope, other = scopes()
    other = type(other).model_validate(
        {**other.model_dump(), "basis": {**other.basis.model_dump(), field: value}}
    )
    with pytest.raises(DomainError) as error:
        aggregate(((scope, counts()), (other, counts())))
    assert error.value.reason == "INCOMPATIBLE_SCOPE"


def test_same_lot_and_missing_counts_aggregate():
    scope, other = scopes()
    with pytest.raises(DomainError) as error:
        aggregate(((scope, counts()), (scope, counts())))
    assert error.value.reason == "OVERLAPPING_SCOPE"
    result = aggregate(((scope, counts()), (other, counts(final_good=None))))
    assert result.counts.final_good is None and result.final_good_yield is None


@pytest.mark.parametrize("threshold", [0, -1, True, "30"])
def test_invalid_direct_sample_policy(threshold):
    with pytest.raises(DomainError) as error:
        calculate(counts(), threshold)
    assert error.value.reason == "INVALID_SAMPLE_POLICY"


def test_yield_precision_independent_of_callers_decimal_context():
    from decimal import localcontext

    value = counts(
        input_count=3,
        output_count=3,
        first_pass=1,
        first_failed=2,
        final_good=2,
        reworked_good=1,
        scrap=1,
        rework_pending=0,
        rework_cycles=4,
    )
    with localcontext() as context:
        context.prec = 2
        low_precision = calculate(value, 1)
    with localcontext() as context:
        context.prec = 50
        high_precision = calculate(value, 1)
    assert low_precision == high_precision
    assert str(low_precision.first_pass_yield) == "0.3333333333333333333333333333"
