"""Regression candidates using normal actual imports; no owner/qualification positive."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.engine import Connection, Engine

from pdos_next.domain.manufacturing_trials.pilot_result_rules import aggregate, project
from pdos_next.domain.manufacturing_trials.rules import (
    calculate,
    counts_from_units,
    validate_counts,
)
from pdos_next.errors import DomainError
from pdos_next.schemas.manufacturing_trials.contracts import Counts, Ref, UnitOutcome
from pdos_next.schemas.manufacturing_trials.pilot_results import FixedPilotScope, RecordedBatch

AT = datetime(2026, 10, 3, 12, 0, 0, 160086, UTC)


@pytest.fixture(autouse=True)
def no_io(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("No database/network in staged count regression")

    monkeypatch.setattr(Engine, "connect", reject)
    monkeypatch.setattr(Engine, "raw_connection", reject)
    monkeypatch.setattr(Connection, "execute", reject)
    monkeypatch.setattr(httpx.Client, "request", reject)


def quantities(**changes):
    material = dict(
        input_count=10,
        output_count=10,
        first_pass=6,
        first_failed=4,
        first_unknown=0,
        final_good=8,
        reworked_good=2,
        scrap=2,
        rework_pending=0,
        undecided=0,
        unprocessed=0,
        rework_cycles=2,
    )
    material.update(changes)
    return Counts(**material)


def reference(kind):
    return Ref(id=uuid4(), revision=1, kind=kind)


def record(values):
    # Structure-only synthetic data. No actual Current/bytes/qualification claim.
    source = dict(
        id=uuid4(),
        revision=1,
        kind="artifact",
        position="line:1;quote_sha256:" + sha256(b"synthetic regression material").hexdigest(),
    )
    n = values.input_count if values.input_count is not None else 10
    fixed = FixedPilotScope(
        scope=dict(tenant_id=uuid4(), product_id=uuid4(), project_id=uuid4()),
        pilot_id=uuid4(),
        pilot_revision=1,
        purpose="本地合成口径核对",
        site="合成线",
        original_timezone="UTC",
        yield_scope=dict(
            basis=dict(
                build=reference("build"),
                lot=reference("build_lot"),
                actual_configuration=reference("actual_configuration"),
                engineering_configuration=reference("engineering_configuration"),
                process_revision=reference("process_revision"),
                unit="ea",
            ),
            manufacturing_baseline=reference("manufacturing_baseline"),
            line=reference("line"),
            cohort_key="fixed-units",
            window_start=AT - timedelta(hours=1),
            window_end=AT,
            criterion=reference("criterion"),
            nature="synthetic",
            minimum_sample=1,
        ),
        cohort=dict(
            population_count=n,
            fixed_input_count=n,
            mode="entire_lot",
            statistics_basis_key="all-fixed-input-per-unit-v1",
            unit_refs=tuple(reference("sample") for _ in range(n)),
            source=source,
        ),
    )
    return RecordedBatch(
        fixed=fixed,
        record=dict(
            observation_id=uuid4(),
            expected_pilot_revision=1,
            scope=fixed.yield_scope,
            counts=values,
            observed=dict(occurred_at=AT, original_timezone="UTC", source=source),
            source=source,
        ),
    )


@pytest.mark.parametrize(
    "changes",
    [
        # Every partition totals 10, but two purported good units have no pass/rework path.
        dict(reworked_good=0, rework_cycles=0),
        # One formerly unknown unit can become good without rework; two cannot.
        dict(first_failed=3, first_unknown=1, reworked_good=0, rework_cycles=0),
    ],
)
def test_unexplained_good_is_count_conflict_even_with_complete_partition(changes):
    values = quantities(**changes)
    before = values.model_dump()
    for operation in (validate_counts, lambda value: calculate(value, 1)):
        with pytest.raises(DomainError) as error:
            operation(values)
        assert error.value.reason == "COUNT_CONFLICT"
        assert error.value.status == 422
    assert values.model_dump() == before
    with pytest.raises(DomainError) as error:
        project(record(values), checked_at=AT)
    assert error.value.reason == "COUNT_CONFLICT" and error.value.status == 422


def test_real_rework_path_keeps_first_and_final_rates_separate():
    values = quantities(rework_cycles=100)
    validate_counts(values)
    result = project(record(values), checked_at=AT)
    assert result.counts.input_count == result.counts.output_count == 10
    assert result.counts.reworked_good == 2 and result.counts.rework_cycles == 100
    assert result.metrics.first_pass_yield.value == Decimal("0.6")
    assert result.metrics.final_good_yield.value == Decimal("0.8")
    assert result.metrics.start_authorized is False
    assert result.metrics.manufacturing_release is None
    assert result.metrics.external_delivery_authorized is False


def test_existing_pass_to_scrap_contradiction_still_rejected():
    values = quantities(first_pass=10, first_failed=0, reworked_good=0, rework_cycles=0)
    with pytest.raises(DomainError) as error:
        validate_counts(values)
    assert error.value.reason == "COUNT_CONFLICT" and error.value.status == 422


def test_previously_unknown_unit_can_become_good_without_invented_rework():
    values = quantities(
        first_failed=3, first_unknown=1, final_good=7, scrap=3, reworked_good=0, rework_cycles=0
    )
    validate_counts(values)
    result = project(record(values), checked_at=AT)
    assert result.counts.first_unknown == 1
    assert result.metrics.first_pass_yield.value is None
    assert result.metrics.final_good_yield.value == Decimal("0.7")
    assert result.metrics.manufacturing_release is None


@pytest.mark.parametrize("field", ["first_pass", "final_good", "reworked_good", "first_unknown"])
def test_missing_cross_partition_quantity_is_preserved_not_assumed_zero(field):
    # Cross-partition inference is unavailable if ANY quantity is absent.
    values = quantities(**{field: None})
    before = values.model_dump()
    validate_counts(values)
    result = project(record(values), checked_at=AT)
    assert result.counts.model_dump() == before
    assert getattr(result.counts, field) is None
    assert "MISSING_COUNTS" in result.metrics.warnings
    if field == "first_pass":
        assert result.metrics.first_pass_yield.numerator is None
        assert result.metrics.first_pass_yield.value is None
    if field == "final_good":
        assert result.metrics.final_good_yield.numerator is None
        assert result.metrics.final_good_yield.value is None
    if field == "first_unknown":
        assert result.metrics.first_pass_yield.partition_complete is False
    # Numeric final proportion, when independently established, is NEVER a release.
    assert result.metrics.start_authorized is False
    assert result.metrics.manufacturing_release is None
    assert result.metrics.external_delivery_authorized is False


def test_unreported_input_does_not_become_fixed_owner_input():
    values = quantities(input_count=None)
    result = project(record(values), checked_at=AT)
    assert result.counts.input_count is None
    assert result.metrics.final_good_yield.denominator == 10
    assert result.metrics.final_good_yield.value is None
    assert result.metrics.final_good_yield.recorded_fraction == Decimal("0.8")


def test_zero_denominator_remains_undefined_not_zero_percent():
    values = Counts(**{name: 0 for name in Counts.model_fields})
    result = project(record(values), checked_at=AT)
    assert result.metrics.first_pass_yield.value is None
    assert result.metrics.final_good_yield.value is None
    assert result.metrics.final_good_yield.state == "undefined_zero_denominator"


def test_unit_and_batch_representations_agree_for_unknown_to_good_and_failed_rework():
    base = record(
        quantities(
            input_count=3,
            output_count=3,
            first_pass=1,
            first_failed=1,
            first_unknown=1,
            final_good=3,
            reworked_good=1,
            scrap=0,
            rework_cycles=2,
        )
    )
    states = (("pass", "good", 0), ("fail", "good", 2), ("unknown", "good", 0))
    units = tuple(
        UnitOutcome(
            sample=sample,
            first_result=first,
            final_state=last,
            rework_cycles=cycles,
            source=base.record.source,
        )
        for sample, (first, last, cycles) in zip(base.fixed.cohort.unit_refs, states, strict=True)
    )
    material = base.model_dump()
    material["record"].update(counts=None, units=units)
    per_unit = RecordedBatch.model_validate(material)
    derived = counts_from_units(per_unit.record)
    validate_counts(derived)
    assert derived == base.record.counts
    assert project(per_unit, checked_at=AT).counts == project(base, checked_at=AT).counts


def test_same_physical_sample_id_with_new_revision_cannot_aggregate_twice():
    first = record(quantities())
    material = first.model_dump()
    material["fixed"]["pilot_id"] = uuid4()
    material["fixed"]["yield_scope"]["basis"]["lot"] = reference("build_lot")
    material["fixed"]["yield_scope"]["cohort_key"] = "different-lot"
    members = [reference("sample") for _ in range(10)]
    members[0] = Ref(id=first.fixed.cohort.unit_refs[0].id, revision=2, kind="sample")
    material["fixed"]["cohort"]["unit_refs"] = members
    material["record"]["scope"] = material["fixed"]["yield_scope"]
    material["record"]["observation_id"] = uuid4()
    second = RecordedBatch.model_validate(material)
    with pytest.raises(DomainError) as error:
        aggregate((first, second), checked_at=AT)
    assert error.value.reason == "OVERLAPPING_UNITS" and error.value.status == 422
