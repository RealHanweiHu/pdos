"""New staged selection only; all records synthetic fixtures, no live gate."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy.engine import Connection, Engine

from pdos_next.domain.manufacturing_trials.pilot_result_ports import Ports
from pdos_next.domain.manufacturing_trials.pilot_result_rules import aggregate, project, revision
from pdos_next.errors import DomainError
from pdos_next.schemas.manufacturing_trials.contracts import Counts, Ref, UnitOutcome
from pdos_next.schemas.manufacturing_trials.pilot_results import FixedPilotScope, RecordedBatch

AT = datetime(2026, 10, 3, 12, 0, 0, 160086, UTC)


@pytest.fixture(autouse=True)
def no_io(monkeypatch):
    def deny(*a, **kw):
        raise AssertionError("No database/network in isolated pilot rules")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)
    monkeypatch.setattr(Connection, "execute", deny)
    monkeypatch.setattr(httpx.Client, "request", deny)


def ref(kind):
    return Ref(kind=kind, id=uuid4(), revision=1)


def counts(n=10, good=6, **changes):
    values = dict(
        input_count=n,
        output_count=n,
        first_pass=good,
        first_failed=n - good,
        first_unknown=0,
        final_good=good,
        reworked_good=0,
        scrap=n - good,
        rework_pending=0,
        undecided=0,
        unprocessed=0,
        rework_cycles=0,
    )
    values.update(changes)
    return Counts(**values)


def batch(n=10, good=6, *, compatible=None, count_changes=None):
    src = {
        "id": str(uuid4()),
        "revision": 1,
        "kind": "artifact",
        "position": "line:1;quote_sha256:" + "a" * 64,
    }
    if compatible:
        fixed = compatible.fixed.model_dump(mode="json")
        fixed["pilot_id"] = str(uuid4())
        fixed["yield_scope"]["basis"]["lot"] = ref("build_lot").model_dump(mode="json")
        fixed["yield_scope"]["cohort_key"] = "new-lot-members"
        fixed["cohort"].update(
            population_count=n,
            fixed_input_count=n,
            unit_refs=[ref("sample").model_dump(mode="json") for _ in range(n)],
        )
    else:
        fixed = dict(
            scope=dict(tenant_id=uuid4(), product_id=uuid4(), project_id=uuid4()),
            pilot_id=uuid4(),
            pilot_revision=1,
            purpose="内部合成试产口径",
            site="测试线",
            original_timezone="UTC",
            yield_scope=dict(
                basis={
                    key: ref(kind)
                    for key, kind in (
                        ("build", "build"),
                        ("lot", "build_lot"),
                        ("actual_configuration", "actual_configuration"),
                        ("engineering_configuration", "engineering_configuration"),
                        ("process_revision", "process_revision"),
                    )
                }
                | {"unit": "ea"},
                manufacturing_baseline=ref("manufacturing_baseline"),
                line=ref("line"),
                cohort_key="first-lot-members",
                window_start=AT - timedelta(hours=1),
                window_end=AT,
                criterion=ref("criterion"),
                nature="synthetic",
                minimum_sample=30,
            ),
            cohort=dict(
                population_count=n,
                fixed_input_count=n,
                mode="entire_lot",
                statistics_basis_key="all-fixed-input-per-unit-v1",
                unit_refs=[ref("sample") for _ in range(n)],
                source=src,
            ),
        )
    fixed = FixedPilotScope.model_validate(fixed)
    return RecordedBatch(
        fixed=fixed,
        record=dict(
            observation_id=uuid4(),
            expected_pilot_revision=fixed.pilot_revision,
            scope=fixed.yield_scope,
            counts=counts(n, good, **(count_changes or {})),
            observed=dict(occurred_at=AT, original_timezone="UTC", source=src),
            source=src,
        ),
    )


def replace(b, path, value):
    data = b.model_dump(mode="json")
    obj = data
    keys = path.split(".")
    for key in keys[:-1]:
        obj = obj[key]
    obj[keys[-1]] = value
    # Rebind canonical record.scope only for changes of the fixed statistical scope.
    if path.startswith("fixed.yield_scope."):
        data["record"]["scope"] = deepcopy(data["fixed"]["yield_scope"])
    return RecordedBatch.model_validate(data)


def test_first_and_final_keep_fixed_input_rework_not_events():
    b = batch(count_changes=dict(final_good=8, reworked_good=2, scrap=2, rework_cycles=100))
    p = project(b, checked_at=AT)
    assert p.counts.input_count == 10 and p.counts.output_count == 10
    assert p.metrics.first_pass_yield.value == Decimal("0.6")
    assert p.metrics.final_good_yield.value == Decimal("0.8")
    assert p.metrics.process_capability == p.metrics.factory_qualification == "NOT_ASSESSED"
    assert p.metrics.start_authorized is False and p.metrics.manufacturing_release is None
    assert p.received_at is None


def test_pending_rework_is_not_good_or_scrap_and_final_rate_stays_partial():
    b = batch(
        count_changes=dict(
            final_good=8, reworked_good=2, scrap=1, rework_pending=1, rework_cycles=2
        )
    )
    p = project(b, checked_at=AT)
    assert p.metrics.first_pass_yield.value == Decimal("0.6")
    assert p.metrics.final_good_yield.value is None
    assert p.metrics.final_good_yield.recorded_fraction == Decimal("0.8")
    assert p.metrics.final_good_yield.state == "partial"


def test_missing_final_category_not_silently_zero():
    b = batch(count_changes=dict(scrap=None))
    p = project(b, checked_at=AT)
    assert p.counts.scrap is None
    assert p.metrics.final_good_yield.value is None
    assert p.metrics.final_good_yield.recorded_fraction == Decimal("0.6")


def test_unknown_first_outcome_final_good_known_independent():
    b = batch(count_changes=dict(first_failed=3, first_unknown=1))
    p = project(b, checked_at=AT)
    assert p.metrics.first_pass_yield.value is None
    assert p.metrics.final_good_yield.value == Decimal("0.6")


def test_unprocessed_input_keeps_denominator_not_output():
    b = batch(
        count_changes=dict(output_count=7, first_pass=6, first_failed=1, unprocessed=3, scrap=1)
    )
    p = project(b, checked_at=AT)
    assert p.metrics.first_pass_yield.denominator == p.metrics.final_good_yield.denominator == 10
    assert p.metrics.first_pass_yield.value is None
    assert p.metrics.final_good_yield.value is None
    assert p.metrics.final_good_yield.recorded_fraction == Decimal("0.6")


def test_zero_and_unknown_fixed_denominator_no_percentages():
    zero = batch(0, 0)
    assert (
        project(zero, checked_at=AT).metrics.final_good_yield.state == "undefined_zero_denominator"
    )
    b = batch(count_changes=dict(input_count=None))
    b = replace(b, "fixed.cohort.fixed_input_count", None)
    p = project(b, checked_at=AT)
    assert p.counts.input_count is None
    assert (
        p.metrics.first_pass_yield.denominator is None and p.metrics.first_pass_yield.value is None
    )


def test_missing_report_input_not_filled_from_fixed_owner():
    b = batch(count_changes=dict(input_count=None))
    p = project(b, checked_at=AT)
    assert p.counts.input_count is None
    assert p.metrics.final_good_yield.denominator == 10
    assert p.metrics.final_good_yield.value is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("input_count", True),
        ("input_count", -1),
        ("first_pass", "6"),
        ("final_good", 6.0),
    ],
)
def test_count_scalar_strictness(field, value):
    with pytest.raises(ValidationError):
        counts(**{field: value})


@pytest.mark.parametrize(
    "changes",
    [
        {"scrap": 5},
        {"first_pass": 11},
        {"output_count": 9},
        {"reworked_good": 5},
        {"final_good": 5},
        {"rework_cycles": 0, "reworked_good": 2, "final_good": 8, "scrap": 2},
    ],
)
def test_overlap_and_count_conflict_are_rejected(changes):
    with pytest.raises(DomainError) as error:
        project(batch(count_changes=changes), checked_at=AT)
    assert error.value.reason == "COUNT_CONFLICT"


def test_fixed_denominator_change_rejected():
    b = batch()
    data = b.model_dump()
    data["fixed"]["cohort"].update(population_count=11, fixed_input_count=11, unit_refs=None)
    with pytest.raises(DomainError) as error:
        project(RecordedBatch.model_validate(data), checked_at=AT)
    assert error.value.reason == "FIXED_DENOMINATOR_CHANGED"


def test_weighted_aggregation_not_percent_average():
    a = batch(10, 10)
    b = batch(30, 0, compatible=a)
    result = aggregate((a, b), checked_at=AT)
    assert result.counts.input_count == 40
    assert (
        result.metrics.first_pass_yield.value
        == result.metrics.final_good_yield.value
        == Decimal("0.25")
    )
    assert result.percentage_averaging_used is False


@pytest.mark.parametrize(
    "path,value",
    [
        ("fixed.scope.tenant_id", str(uuid4())),
        ("fixed.scope.product_id", str(uuid4())),
        ("fixed.scope.project_id", str(uuid4())),
        ("fixed.purpose", "另一用途"),
        ("fixed.site", "另一地点"),
        ("fixed.original_timezone", "America/Los_Angeles"),
        ("fixed.yield_scope.basis.build", ref("build").model_dump(mode="json")),
        (
            "fixed.yield_scope.basis.actual_configuration",
            ref("actual_configuration").model_dump(mode="json"),
        ),
        (
            "fixed.yield_scope.basis.engineering_configuration",
            ref("engineering_configuration").model_dump(mode="json"),
        ),
        (
            "fixed.yield_scope.basis.process_revision",
            ref("process_revision").model_dump(mode="json"),
        ),
        ("fixed.yield_scope.basis.unit", "kg"),
        (
            "fixed.yield_scope.manufacturing_baseline",
            ref("manufacturing_baseline").model_dump(mode="json"),
        ),
        ("fixed.yield_scope.line", ref("line").model_dump(mode="json")),
        ("fixed.yield_scope.criterion", ref("criterion").model_dump(mode="json")),
        ("fixed.yield_scope.nature", "real"),
        ("fixed.yield_scope.minimum_sample", 31),
        ("fixed.cohort.statistics_basis_key", "另一分母政策"),
    ],
)
def test_full_scope_incompatibility_cannot_aggregate(path, value):
    a = batch()
    b = batch(10, 6, compatible=a)
    b = replace(b, path, value)
    with pytest.raises(DomainError) as error:
        aggregate((a, b), checked_at=AT)
    assert error.value.reason == "INCOMPATIBLE_SCOPE"


def test_repeated_lot_pilot_or_sample_ref_rejected():
    a = batch()
    b = batch(10, 6, compatible=a)
    with pytest.raises(DomainError) as error:
        aggregate((a, a), checked_at=AT)
    assert error.value.reason == "OVERLAPPING_SCOPE"
    b = replace(
        b, "fixed.yield_scope.basis.lot", a.fixed.yield_scope.basis.lot.model_dump(mode="json")
    )
    with pytest.raises(DomainError) as error:
        aggregate((a, b), checked_at=AT)
    assert error.value.reason == "OVERLAPPING_SCOPE"
    b = batch(10, 6, compatible=a)
    refs = list(b.fixed.cohort.unit_refs)
    refs[0] = a.fixed.cohort.unit_refs[0]
    b = replace(b, "fixed.cohort.unit_refs", [r.model_dump(mode="json") for r in refs])
    with pytest.raises(DomainError) as error:
        aggregate((a, b), checked_at=AT)
    assert error.value.reason == "OVERLAPPING_UNITS"


def test_missing_member_owner_is_unknown_not_disjoint_positive():
    a = replace(batch(), "fixed.cohort.unit_refs", None)
    p = project(a, checked_at=AT)
    assert "COHORT_MEMBERSHIP_NOT_ENUMERATED" in p.metrics.warnings
    with pytest.raises(DomainError) as error:
        aggregate((a,), checked_at=AT)
    assert error.value.reason == "COHORT_MEMBERSHIP_UNKNOWN" and error.value.status == 503


def test_no_draft_or_missing_baseline_line_scope():
    for path in ("fixed.yield_scope.manufacturing_baseline", "fixed.yield_scope.line"):
        with pytest.raises(ValidationError):
            replace(batch(), path, None)
    # Ref alone does not prove released; actual owner must reject the existing draft.
    with pytest.raises(ValidationError):
        replace(batch(), "fixed.qualified", True)


def corrected(b):
    data = b.model_dump()
    data["fixed"]["pilot_revision"] += 1
    data["record"].update(
        expected_pilot_revision=data["fixed"]["pilot_revision"],
        observation_id=uuid4(),
        previous_observation_id=b.record.observation_id,
        correction_reason="真实修正",
    )
    return RecordedBatch.model_validate(data)


def test_append_correction_keeps_exact_scope_and_members():
    a = batch()
    b = corrected(a)
    p = revision(a, b, checked_at=AT)
    assert p.counts == a.record.counts
    assert a.fixed.pilot_revision == 1 and b.fixed.pilot_revision == 2
    with pytest.raises(DomainError) as error:
        revision(
            a,
            replace(b, "fixed.yield_scope.line", ref("line").model_dump(mode="json")),
            checked_at=AT,
        )
    assert error.value.reason == "FIXED_SCOPE_CHANGED"


def test_correction_cannot_reuse_original_observation_identity():
    a = batch()
    b = replace(corrected(a), "record.observation_id", str(a.record.observation_id))
    with pytest.raises(DomainError) as error:
        revision(a, b, checked_at=AT)
    assert error.value.reason == "OBSERVATION_REVISION_CONFLICT"


def test_unknown_batch_input_never_invents_aggregate_input():
    a = batch()
    b = batch(10, 6, compatible=a, count_changes=dict(input_count=None))
    result = aggregate((a, b), checked_at=AT)
    assert result.counts.input_count is None
    assert result.metrics.final_good_yield.denominator == 20
    assert result.metrics.final_good_yield.value is None
    assert result.metrics.final_good_yield.recorded_fraction == Decimal("0.6")


def test_unit_counts_preserve_subset_rework_and_reject_overlapping_states():
    a = batch(4, 1)
    scenarios = (
        ("pass", "good", 0),
        ("fail", "good", 3),
        ("fail", "rework_pending", 2),
        ("unknown", "undecided", 0),
    )
    units = [
        UnitOutcome(
            sample=r, first_result=f, final_state=last, rework_cycles=cycles, source=a.record.source
        )
        for r, (f, last, cycles) in zip(a.fixed.cohort.unit_refs, scenarios, strict=True)
    ]
    data = a.model_dump()
    data["record"].update(counts=None, units=units)
    p = project(RecordedBatch.model_validate(data), checked_at=AT)
    assert p.counts.input_count == 4 and p.counts.rework_cycles == 5 and p.counts.reworked_good == 1
    assert p.counts.final_good == 2 and p.counts.rework_pending == p.counts.undecided == 1
    assert p.metrics.first_pass_yield.value is None and p.metrics.final_good_yield.value is None
    with pytest.raises(ValidationError):
        UnitOutcome(
            sample=a.fixed.cohort.unit_refs[0],
            first_result="pass",
            final_state="scrap",
            rework_cycles=0,
            source=a.record.source,
        )
    data["record"]["units"] = units[:-1]
    with pytest.raises(ValidationError):
        RecordedBatch.model_validate(data)


def test_native_clock_micros_offset_and_freshness():
    a = batch()
    original = a.record.observed.occurred_at
    project(a, checked_at=AT.astimezone(timezone(timedelta(hours=-7))))
    assert original.microsecond == 160086 and a.record.observed.occurred_at == original
    with pytest.raises(DomainError) as error:
        project(a, checked_at=AT - timedelta(microseconds=1))
    assert error.value.reason == "FUTURE_OBSERVATION"
    with pytest.raises(DomainError) as error:
        project(a, checked_at=AT.replace(tzinfo=None))
    assert error.value.reason == "FRESH_SERVER_CLOCK_REQUIRED"


def test_decimal_precision_does_not_use_global_float_context():
    a = batch(3, 1)
    with localcontext() as context:
        context.prec = 3
        p = project(a, checked_at=AT)
    assert p.metrics.first_pass_yield.value == Decimal("0.3333333333333333333333333333")


def test_sampling_subset_is_fixed_not_silent_full_lot():
    a = batch()
    data = a.model_dump()
    data["fixed"]["cohort"].update(mode="fixed_sampled_subset", population_count=100)
    p = project(RecordedBatch.model_validate(data), checked_at=AT)
    assert p.metrics.first_pass_yield.denominator == 10
    data["fixed"]["cohort"]["mode"] = "entire_lot"
    with pytest.raises(ValidationError):
        RecordedBatch.model_validate(data)


def test_missing_host_fails_closed_no_writes():
    with pytest.raises(DomainError) as error:
        Ports().require()
    assert error.value.reason == "INTEGRATION_REQUIRED" and error.value.status == 503
