"""Scope, incomplete evidence and deterministic result checks."""

import pytest

from pdos_next.domain.verification.rules import (
    accepted_coverage,
    check_coverage,
    compute_results,
    coverage_gaps,
    document_gaps,
)
from pdos_next.error_catalog import REASONS
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import Acceptance, Coverage

from .helpers import (
    coverage,
    document,
    execution,
    fact,
    item,
    measurement,
    request,
    run,
    sample,
    source,
    uid,
)


def test_missing_documents_block_only_applicable_items():
    current = request(
        items=(item(), item("pressure")),
        documents=(document("pressure-rule", items=("pressure",), present=False),),
    )
    assert document_gaps(current, {"dimension"}) == ()
    gaps = document_gaps(current)
    assert {(g.code, g.item_id) for g in gaps} == {("DOCUMENT_MISSING", "pressure")}


def test_optional_document_does_not_manufacture_missing_required_evidence():
    current = request(documents=(document(present=False, required=False),))
    assert document_gaps(current) == ()


@pytest.mark.parametrize(
    "field",
    [
        "drawing",
        "method",
        "criterion",
        "unit",
        "conditions",
        "material",
    ],
)
def test_required_method_data_gap_remains_explicit(field):
    current = request(items=(item(**{field: None}),))
    gaps = document_gaps(current)
    assert len(gaps) == 1 and gaps[0].item_id == "dimension"
    assert field in gaps[0].detail


def test_qualitative_criterion_is_ready_with_source_but_not_numeric_pass():
    planned_item = item(
        criterion=None,
        criterion_text="表面无可见裂纹",
        criterion_source=source("visual-rule"),
    )
    assert document_gaps(request(items=(planned_item,))) == ()
    computed, result = compute_results(
        run(items=(planned_item,), execution=execution()),
        tuple(measurement(f"m-{i}", pair=p) for i, p in enumerate(coverage())),
        final=True,
    )
    assert result == "indeterminate"
    assert all(c.result == "indeterminate" for c in computed)


def test_full_coverage_uses_sample_item_pairs_and_fixed_cavities():
    refs = (sample(), sample("sample-b", "B"))
    current = request(samples=refs)
    assert check_coverage(current, coverage(samples=refs)) is None
    assert coverage_gaps(current, coverage(samples=refs)) == ()


def test_partial_coverage_records_count_and_uncovered_cavity_separately():
    current = request(samples=(sample(),))
    selected = coverage(samples=(sample(),))
    assert check_coverage(current, selected) is None
    gaps = coverage_gaps(current, selected)
    assert {g.code for g in gaps} == {"PARTIAL_SAMPLE_COUNT", "UNCOVERED_CAVITY"}
    assert all(g.item_id == "dimension" for g in gaps)


@pytest.mark.parametrize("selected", [(), coverage()[:1] * 2])
def test_coverage_cannot_be_empty_or_repeat_exact_pair(selected):
    with pytest.raises(DomainError) as rejected:
        check_coverage(request(samples=(sample(), sample("sample-b", "B"))), selected)
    assert rejected.value.reason == "INVALID_COVERAGE"
    assert rejected.value.code == REASONS["INVALID_COVERAGE"]


def test_same_sample_may_cover_separate_nondestructive_items():
    ref = sample()
    selected = (
        Coverage(sample_id=ref.id, item_id="dimension"),
        Coverage(sample_id=ref.id, item_id="pressure"),
    )
    current = request(items=(item(), item("pressure")), samples=(ref,))
    assert check_coverage(current, selected) is None


@pytest.mark.parametrize(
    "selected",
    [
        (Coverage(sample_id=uid("foreign-sample"), item_id="dimension"),),
        (Coverage(sample_id=sample().id, item_id="foreign-item"),),
    ],
)
def test_coverage_cannot_escape_supplied_sample_or_item_scope(selected):
    with pytest.raises(DomainError) as rejected:
        check_coverage(request(samples=(sample(),)), selected)
    assert rejected.value.reason == "INVALID_COVERAGE"
    assert rejected.value.code == REASONS["INVALID_COVERAGE"]


def test_sample_from_other_build_cannot_be_accepted_as_this_build():
    foreign = sample(build_id=uid("different-build"))
    with pytest.raises(DomainError) as rejected:
        check_coverage(request(), coverage(samples=(foreign,)), samples=(foreign,))
    assert rejected.value.code == "FORBIDDEN_SCOPE"


def test_unrequested_cavity_cannot_silently_be_counted_as_applicable():
    wrong = sample(cavity="C")
    with pytest.raises(DomainError) as rejected:
        check_coverage(request(), coverage(samples=(wrong,)), samples=(wrong,))
    assert rejected.value.reason == "INAPPLICABLE_CONFIGURATION"
    assert rejected.value.code == REASONS["INAPPLICABLE_CONFIGURATION"]


def test_same_sample_cannot_have_two_actual_configuration_versions():
    with pytest.raises(DomainError) as rejected:
        check_coverage(request(), coverage()[:1], samples=(sample(), sample(revision=2)))
    assert rejected.value.reason == "INVALID_COVERAGE"
    assert rejected.value.code == REASONS["INVALID_COVERAGE"]


def test_accepted_coverage_is_union_of_actual_acceptance_pairs():
    selected = coverage()
    current = request(
        acceptances=(
            Acceptance(coverage=selected[:1], actor_id=uid("actor"), at=fact("accept-a")),
            Acceptance(coverage=selected, actor_id=uid("actor"), at=fact("accept-b")),
        )
    )
    assert set(accepted_coverage(current)) == set(selected)


@pytest.mark.parametrize("raw", ["9.5", "10.5", "010.000"])
def test_numeric_boundaries_are_inclusive_and_raw_text_is_preserved(raw):
    readings = tuple(measurement(f"m-{i}", pair=p, raw=raw) for i, p in enumerate(coverage()))
    computed, result = compute_results(run(execution=execution()), readings, final=True)
    assert result == "pass" and all(c.result == "pass" for c in computed)
    assert readings[0].raw_value == raw


@pytest.mark.parametrize("raw", ["9.49999", "10.50001"])
def test_out_of_range_reading_is_fail_and_not_execution_state(raw):
    current = run(status="running", execution=execution())
    computed, result = compute_results(current, (measurement(raw=raw),))
    assert computed[0].result == "fail" and result == "fail"
    assert current.status == "running"


def test_partial_passed_readings_cannot_be_aggregate_pass():
    computed, result = compute_results(run(execution=execution()), (measurement(),), final=False)
    assert {c.result for c in computed} == {"pass", "indeterminate"}
    assert result == "indeterminate"


def test_preliminary_complete_readings_do_not_become_final_pass():
    readings = tuple(measurement(f"m-{i}", pair=p) for i, p in enumerate(coverage()))
    computed, result = compute_results(run(execution=execution()), readings)
    assert all(c.result == "pass" for c in computed) and result == "indeterminate"


@pytest.mark.parametrize(
    "field",
    [
        "raw_value",
        "unit",
        "conditions",
        "equipment",
        "environment",
        "method",
        "source",
        "observed_at",
        "observed_timezone",
    ],
)
def test_missing_measurement_evidence_is_indeterminate_even_at_final(field):
    readings = tuple(
        measurement(f"m-{i}", pair=p, **{field: None}) for i, p in enumerate(coverage())
    )
    computed, result = compute_results(run(execution=execution()), readings, final=True)
    assert result == "indeterminate"
    assert all(c.result == "indeterminate" and c.reasons for c in computed)


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "garbled", ""])
def test_non_numeric_or_nonfinite_raw_value_is_preserved_without_passing(raw):
    readings = tuple(measurement(f"m-{i}", pair=p, raw=raw) for i, p in enumerate(coverage()))
    computed, result = compute_results(run(execution=execution()), readings, final=True)
    assert result == "indeterminate" and all(c.reasons for c in computed)
    assert readings[0].raw_value == raw


@pytest.mark.parametrize(
    "changes",
    [
        {"unit": "cm"},
        {"conditions": "80 °C, wet"},
        {"method": source("method-v2")},
        {"equipment": source("other-equipment")},
        {"environment": "uncontrolled"},
        {"missing": ("原件待补",)},
    ],
)
def test_unit_condition_method_execution_or_declared_gap_cannot_silently_pass(changes):
    readings = tuple(measurement(f"m-{i}", pair=p, **changes) for i, p in enumerate(coverage()))
    computed, result = compute_results(run(execution=execution()), readings, final=True)
    assert result == "indeterminate" and all(c.reasons for c in computed)


def test_measurements_without_real_execution_conditions_are_indeterminate():
    readings = tuple(measurement(f"m-{i}", pair=p) for i, p in enumerate(coverage()))
    _, result = compute_results(run(), readings, final=True)
    assert result == "indeterminate"


def test_measurement_matches_requirement_but_conflicts_with_actual_run_condition():
    readings = tuple(measurement(f"m-{i}", pair=p) for i, p in enumerate(coverage()))
    actual = execution().model_copy(update={"conditions": "80 °C, wet"})
    computed, result = compute_results(run(execution=actual), readings, final=True)
    assert result == "indeterminate" and all(c.reasons for c in computed)


@pytest.mark.parametrize(
    "readings",
    [
        (measurement(), measurement()),
        (measurement(), measurement(pair=coverage()[1])),
        (measurement(pair=Coverage(sample_id=uid("foreign-sample"), item_id="dimension")),),
    ],
)
def test_measurement_pair_identity_and_run_scope_cannot_duplicate_or_escape(readings):
    with pytest.raises(DomainError) as rejected:
        compute_results(run(execution=execution()), readings, final=True)
    assert rejected.value.reason == "INVALID_MEASUREMENT_SCOPE"
    assert rejected.value.code == REASONS["INVALID_MEASUREMENT_SCOPE"]
