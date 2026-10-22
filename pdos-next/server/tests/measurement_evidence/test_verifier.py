"""Original bytes, exact values and fixed sample scope, without database substitutes."""

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.domain.measurement_evidence.schemas import (
    FORMAT_VERSION,
    ObservationSelection,
    OriginalRef,
    ReportBinding,
    SampleItemBinding,
)
from pdos_next.domain.measurement_evidence.verifier import (
    VerifierLimits,
    extract_observations,
    fixed_run_sha256,
    verify_measurement,
)
from pdos_next.domain.verification.rules import compute_results
from pdos_next.domain.verification_launch.schemas import ExecutionPlan
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import (
    BuildRef,
    ConfigurationRef,
    Coverage,
    ExecutionConditions,
    NumericCriterion,
    SampleRef,
    Scope,
    SourceRef,
    TimeFact,
)
from pdos_next.schemas.verification.contracts import (
    TestItem as VerificationItem,
)
from pdos_next.schemas.verification.contracts import (
    TestRun as VerificationRun,
)


def reference(artifact_id, line=1, quote="synthetic reference"):
    return {
        "artifact_id": str(artifact_id),
        "expected_revision": 1,
        "line": line,
        "quote": quote,
    }


def source(ref):
    return SourceRef(
        id=ref["artifact_id"],
        revision=ref["expected_revision"],
        kind="artifact",
        position=f"line:{ref['line']};quote_sha256:{hashlib.sha256(ref['quote'].encode()).hexdigest()}",
    )


@pytest.fixture
def work():
    scope = Scope(tenant_id=uuid4(), product_id=uuid4(), project_id=uuid4())
    config = ConfigurationRef(id=uuid4(), revision=1)
    build = BuildRef(
        id=uuid4(),
        revision=1,
        product_id=scope.product_id,
        project_id=scope.project_id,
        engineering_configuration=config,
        manufacturing_configuration=ConfigurationRef(id=uuid4(), revision=1),
    )
    samples = tuple(
        SampleRef(
            id=uuid4(),
            revision=1,
            build_id=build.id,
            actual_configuration=ConfigurationRef(id=uuid4(), revision=2),
            cavity=cavity,
        )
        for cavity in ("A", "B")
    )
    at = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
    ref = reference(uuid4())
    plan = ExecutionPlan.model_validate(
        {
            "window": {
                "start": at.isoformat(),
                "finish": (at + timedelta(hours=2)).isoformat(),
                "original_timezone": "UTC",
            },
            "executor_id": str(uuid4()),
            "equipment": ref,
            "calibration": reference(uuid4(), quote="synthetic calibration"),
            "environment": "23 ℃",
            "conditions": "Load 2 N",
            "resource_fact_id": str(uuid4()),
            "expected_resource_fact_revision": 1,
        }
    )
    equipment = source(ref)
    calibration = source(plan.calibration.model_dump(mode="json"))
    method = SourceRef(id=uuid4(), revision=3, kind="artifact", position="method:dimension:v3")
    run = VerificationRun(
        id=uuid4(),
        revision=2,
        scope=scope,
        request_id=uuid4(),
        request_revision=7,
        build=build,
        samples=samples,
        items=(
            VerificationItem(
                id="dimension",
                feature="Synthetic measurement",
                method=method,
                criterion=NumericCriterion(lower="1", upper="2", source=equipment),
                unit="mm",
                conditions=plan.conditions,
                sample_count=2,
            ),
        ),
        coverage=tuple(Coverage(sample_id=s.id, item_id="dimension") for s in samples),
        execution=ExecutionConditions(
            equipment=equipment,
            calibration=calibration,
            executor_id=plan.executor_id,
            environment=plan.environment,
            conditions=plan.conditions,
        ),
        status="running",
        actual_start=TimeFact(
            occurred_at=at,
            original_timezone="UTC",
            source=equipment,
            received_at=at,
            actor_id=plan.executor_id,
        ),
    )
    row = {
        "format": FORMAT_VERSION,
        "run_id": str(run.id),
        "sample_id": str(samples[0].id),
        "sample_revision": 1,
        "actual_configuration": samples[0].actual_configuration.model_dump(mode="json"),
        "cavity": "A",
        "item_id": "dimension",
        "raw_value": "  +001.2300 ",
        "unit": "mm",
        "conditions": plan.conditions,
        "equipment": equipment.model_dump(mode="json"),
        "equipment_label": "机台 甲",
        "calibration": calibration.model_dump(mode="json"),
        "environment": plan.environment,
        "method": method.model_dump(mode="json"),
        "executor_id": str(plan.executor_id),
        "observed_at": (at + timedelta(minutes=1)).isoformat(),
        "observed_timezone": "UTC",
        "note": "原值不可裁剪",
    }
    return SimpleNamespace(run=run, plan=plan, row=row, report_id=uuid4(), original_id=uuid4())


def content(work, rows=None, newline="\n"):
    rows = (work.row,) if rows is None else rows
    return (newline.join(json.dumps(row, ensure_ascii=False) for row in rows) + newline).encode()


def binding(work, raw, *, plan=True):
    execution_plan = work.plan if plan else None
    return ReportBinding(
        scope=work.run.scope,
        run_id=work.run.id,
        run_revision=work.run.revision,
        request_id=work.run.request_id,
        request_revision=work.run.request_revision,
        run_basis_sha256=fixed_run_sha256(work.run, execution_plan),
        report=SourceRef(
            id=work.report_id, revision=1, kind="artifact", position="original-report"
        ),
        original=OriginalRef(
            id=work.original_id,
            revision=1,
            sha256=hashlib.sha256(raw).hexdigest(),
            size=len(raw),
            media_type="text/plain",
        ),
        security_epoch=4,
        pairs=tuple(
            SampleItemBinding(sample=sample, item_id="dimension") for sample in work.run.samples
        ),
        execution_plan=execution_plan,
    )


def candidate(work, raw=None, **kwargs):
    raw = content(work) if raw is None else raw
    fixed = binding(work, raw, **kwargs)
    result = extract_observations(raw, fixed)
    return raw, fixed, result.observations[0]


def assert_failure(code, fn):
    with pytest.raises(DomainError) as failed:
        fn()
    assert failed.value.reason == code
    from pdos_next.error_catalog import CATEGORIES

    assert failed.value.code in CATEGORIES
    # Failure messages are bounded and do not include the actual report values.
    assert len(str(failed.value)) <= 150


def test_exact_raw_string_lexical_tokens_and_known_decimal_use_existing_rule(work):
    raw, fixed, observed = candidate(work)
    assert observed.raw_value == "  +001.2300 "
    assert observed.value_state == "known" and observed.missing == ()
    assert observed.metadata_mismatches == ()
    measured = observed.to_measurement(uuid4())
    assert measured.raw_value == observed.raw_value
    verified = verify_measurement(raw, fixed, measured, work.run)
    assert verified.verification == "exact_source_values"
    assert verified.report_sha256 == hashlib.sha256(raw).hexdigest()
    assert len(verified.proof_sha256) == 64
    assert verify_measurement(raw, fixed, measured, work.run) == verified
    results, total = compute_results(work.run, (measured,), final=True)
    assert results[0].result == "pass" and results[1].result == "indeterminate"
    assert total == "indeterminate"  # A missing pair never becomes Cartesian null/pass coverage.
    loc = next(location for location in observed.field_locations if location.field == "raw_value")
    assert json.loads(loc.raw_token) == measured.raw_value
    assert raw[loc.byte_start : loc.byte_end].decode() == loc.raw_token


def test_every_nested_field_and_crlf_utf8_offsets_remain_exact(work):
    second = deepcopy(work.row)
    second.update(
        sample_id=str(work.run.samples[1].id),
        actual_configuration=work.run.samples[1].actual_configuration.model_dump(mode="json"),
        cavity="B",
        raw_value="1.40",
    )
    raw = content(work, (work.row, second), newline="\r\n")
    fixed = binding(work, raw)
    observations = extract_observations(raw, fixed).observations
    assert len(observations) == 2
    for observation in observations:
        line = raw.decode().splitlines()[observation.line - 1]
        for loc in observation.field_locations:
            assert loc.line == observation.line
            if loc.presence != "missing":
                assert line[loc.character_start : loc.character_end] == loc.raw_token
                assert raw[loc.byte_start : loc.byte_end].decode() == loc.raw_token
        assert any(loc.field == "actual_configuration.id" for loc in observation.field_locations)
        assert any(loc.field == "equipment.position" for loc in observation.field_locations)


def test_escaped_unicode_and_quotes_preserve_decoded_raw_and_original_json_token(work):
    work.row["raw_value"] = '  读数\\n"𝄞"\u2028 '
    raw = (json.dumps(work.row, ensure_ascii=True) + "\n").encode()
    raw, fixed, observed = candidate(work, raw)
    loc = next(location for location in observed.field_locations if location.field == "raw_value")
    assert observed.raw_value == work.row["raw_value"]
    assert "\\u2028" in loc.raw_token and "\\ud834\\udd1e" in loc.raw_token
    assert observed.value_state == "non_numeric"
    verify_measurement(raw, fixed, observed.to_measurement(uuid4()), work.run)


@pytest.mark.parametrize("raw_value", [None, "", "   ", "NaN", "Infinity", "-Infinity", "文字"])
def test_unknown_and_nonfinite_strings_remain_original_and_indeterminate(work, raw_value):
    work.row["raw_value"] = raw_value
    raw, fixed, observed = candidate(work)
    measured = observed.to_measurement(uuid4())
    assert measured.raw_value == raw_value
    assert observed.value_state != "known" and measured.missing
    verify_measurement(raw, fixed, measured, work.run)
    results, _ = compute_results(work.run, (measured,), final=True)
    assert results[0].result == "indeterminate"


def test_missing_vs_null_are_different_provenance_and_never_filled_from_run(work):
    work.row.pop("equipment")
    work.row["method"] = None
    work.row.pop("observed_at")
    raw, fixed, observed = candidate(work)
    assert observed.equipment is None and observed.method is None and observed.observed_at is None
    assert observed.observed_timezone == "UTC"
    locations = {loc.field: loc for loc in observed.field_locations}
    assert locations["equipment"].presence == "missing"
    assert locations["equipment"].raw_token is None
    assert locations["method"].presence == "null"
    assert locations["method"].raw_token == "null"
    assert "SOURCE_FIELD_MISSING:equipment" in observed.missing
    assert "SOURCE_FIELD_NULL:method" in observed.missing
    verify_measurement(raw, fixed, observed.to_measurement(uuid4()), work.run)


def test_empty_selection_and_absent_report_rows_do_not_invent_null_measurements(work):
    raw = content(work)
    fixed = binding(work, raw)
    result = extract_observations(raw, fixed, ())
    assert result.observations == () and result.missing_pairs == work.run.coverage
    result = extract_observations(b"", binding(work, b""))
    assert result.observations == () and result.missing_pairs == work.run.coverage
    phantom = ObservationSelection(line=2, sample_id=work.run.samples[1].id, item_id="dimension")
    assert_failure(
        "REPORT_SELECTION_MISMATCH", lambda: extract_observations(raw, fixed, (phantom,))
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("raw_value", "1.2300"),
        ("unit", "cm"),
        ("conditions", "Load 0 N"),
        ("equipment_label", "机台 乙"),
        ("environment", "23 C"),
        ("method", SourceRef(id=uuid4(), revision=1, kind="artifact", position="unrelated")),
        ("equipment", SourceRef(id=uuid4(), revision=1, kind="artifact", position="unrelated")),
        ("note", "changed"),
        ("observed_at", datetime(2026, 10, 2, 12, 2, tzinfo=UTC)),
        ("observed_timezone", "Etc/UTC"),
        ("missing", ("invented gap",)),
    ],
)
def test_each_measurement_field_must_match_original_not_expectation(work, field, replacement):
    raw, fixed, observed = candidate(work)
    measured = observed.to_measurement(uuid4()).model_copy(update={field: replacement})
    assert_failure(
        "MEASUREMENT_SOURCE_MISMATCH", lambda: verify_measurement(raw, fixed, measured, work.run)
    )


@pytest.mark.parametrize(
    "source_change", ["wrong_id", "wrong_revision", "wrong_line", "wrong_hash", "domain"]
)
def test_hash_alone_wrong_locator_or_source_identity_cannot_verify(work, source_change):
    raw, fixed, observed = candidate(work)
    measured = observed.to_measurement(uuid4())
    changes = {
        "wrong_id": {"id": uuid4()},
        "wrong_revision": {"revision": 2},
        "wrong_line": {"position": f"line:2;quote_sha256:{observed.row_sha256}"},
        "wrong_hash": {"position": "line:1;quote_sha256:" + "0" * 64},
        "domain": {"kind": "domain"},
    }
    measured = measured.model_copy(
        update={"source": measured.source.model_copy(update=changes[source_change])}
    )
    code = (
        "REPORT_SELECTION_MISMATCH"
        if source_change == "wrong_line"
        else "MEASUREMENT_SOURCE_MISMATCH"
    )
    assert_failure(code, lambda: verify_measurement(raw, fixed, measured, work.run))


@pytest.mark.parametrize(
    "field", ["unit", "conditions", "environment", "executor_id", "calibration", "equipment"]
)
def test_original_mismatched_metadata_is_preserved_as_unknown_not_changed(work, field):
    if field in {"calibration", "equipment"}:
        work.row[field] = SourceRef(
            id=uuid4(), revision=1, kind="artifact", position="other"
        ).model_dump(mode="json")
    elif field == "executor_id":
        work.row[field] = str(uuid4())
    else:
        work.row[field] = "actual different value"
    raw, fixed, observed = candidate(work)
    measured = observed.to_measurement(uuid4())
    verified = verify_measurement(raw, fixed, measured, work.run)
    assert verified.observation == observed
    results, _ = compute_results(work.run, (measured,), final=True)
    assert results[0].result == "indeterminate"


def test_lacking_plan_is_explicit_unknown_and_never_supplies_missing_executed_metadata(work):
    raw, fixed, observed = candidate(work, plan=False)
    assert "EXECUTION_PLAN_UNBOUND" in observed.missing
    measured = observed.to_measurement(uuid4())
    verify_measurement(raw, fixed, measured, work.run)
    assert compute_results(work.run, (measured,), True)[0][0].result == "indeterminate"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("run_id", str(uuid4()), "INVALID_MEASUREMENT_SCOPE"),
        ("sample_id", str(uuid4()), "INVALID_MEASUREMENT_SCOPE"),
        ("item_id", "unaccepted", "INVALID_MEASUREMENT_SCOPE"),
        ("sample_revision", 2, "REPORT_SAMPLE_MISMATCH"),
        ("sample_revision", True, "INVALID_REPORT_FIELD"),
        ("sample_revision", 1.0, "INVALID_REPORT_FIELD"),
        ("sample_revision", "1", "INVALID_REPORT_FIELD"),
        ("actual_configuration", {"id": str(uuid4()), "revision": 2}, "REPORT_SAMPLE_MISMATCH"),
        ("actual_configuration", {"id": str(uuid4()), "revision": True}, "INVALID_REPORT_FIELD"),
        ("cavity", "B", "REPORT_SAMPLE_MISMATCH"),
        ("format", "other", "INVALID_REPORT_FIELD"),
        ("raw_value", 1.23, "INVALID_REPORT_FIELD"),
        ("raw_value", True, "INVALID_REPORT_FIELD"),
        ("approved", True, "INVALID_REPORT_FIELD"),
        ("measurement_id", str(uuid4()), "INVALID_REPORT_FIELD"),
    ],
)
def test_closed_schema_identity_and_no_numeric_coercion(work, field, value, code):
    work.row[field] = value
    raw = content(work)
    assert_failure(code, lambda: extract_observations(raw, binding(work, raw)))


@pytest.mark.parametrize("field", ["equipment", "method", "calibration"])
def test_incomplete_or_trimmed_reference_cannot_be_filled_or_normalized(work, field):
    work.row[field]["position"] = "  " + work.row[field]["position"]
    raw = content(work)
    assert_failure("INVALID_REPORT_FIELD", lambda: extract_observations(raw, binding(work, raw)))
    work.row[field]["position"] = work.row[field]["position"].strip()
    work.row[field].pop("kind")
    raw = content(work)
    assert_failure("INVALID_REPORT_FIELD", lambda: extract_observations(raw, binding(work, raw)))


@pytest.mark.parametrize("nested", [False, True])
def test_duplicate_keys_even_equivalent_escape_names_are_ambiguous(work, nested):
    raw = content(work).decode()
    if nested:
        raw = raw.replace('"revision": 2', '"revision": 2, "revi\\u0073ion": 2', 1)
    else:
        raw = raw.replace('"raw_value":', '"raw_value": null, "raw_\\u0076alue":', 1)
    raw = raw.encode()
    assert_failure("DUPLICATE_REPORT_KEY", lambda: extract_observations(raw, binding(work, raw)))


def test_multiple_rows_for_one_pair_rejected_even_when_user_selects_one(work):
    raw = content(work, (work.row, work.row))
    fixed = binding(work, raw)
    selection = ObservationSelection(line=1, sample_id=work.run.samples[0].id, item_id="dimension")
    assert_failure("AMBIGUOUS_REPORT_ROW", lambda: extract_observations(raw, fixed, (selection,)))


def test_duplicate_selection_and_false_pair_mapping_are_rejected(work):
    raw = content(work)
    fixed = binding(work, raw)
    selected = ObservationSelection(line=1, sample_id=work.run.samples[0].id, item_id="dimension")
    assert_failure(
        "AMBIGUOUS_REPORT_SELECTION", lambda: extract_observations(raw, fixed, (selected, selected))
    )
    wrong = selected.model_copy(update={"sample_id": work.run.samples[1].id})
    assert_failure("REPORT_SELECTION_MISMATCH", lambda: extract_observations(raw, fixed, (wrong,)))


@pytest.mark.parametrize(
    ("iso", "zone", "valid"),
    [
        ("2026-10-02T12:01:00+00:00", "UTC", True),
        ("2026-11-01T01:30:00-04:00", "America/New_York", True),
        ("2026-11-01T01:30:00-05:00", "America/New_York", True),
        ("2026-03-08T03:30:00-04:00", "America/New_York", True),
        ("2026-03-08T02:30:00-05:00", "America/New_York", False),
        ("2026-07-02T12:01:00-05:00", "America/New_York", False),
        ("2026-10-02T12:01:00", "UTC", False),
        ("2026-02-29T12:01:00+00:00", "UTC", False),
        ("2026-10-02T12:01:60+00:00", "UTC", False),
        ("2026-10-02T12:01:00+00:00", "Mars/Olympus", False),
        (1790000000, "UTC", False),
    ],
)
def test_strict_aware_iana_date_offset_and_dst_without_invented_time(work, iso, zone, valid):
    work.row.update(observed_at=iso, observed_timezone=zone)
    raw = content(work)
    fixed = binding(work, raw)
    if not valid:
        assert_failure("INVALID_REPORT_TIME", lambda: extract_observations(raw, fixed))
    else:
        candidate = extract_observations(raw, fixed).observations[0]
        assert candidate.observed_at.tzinfo == UTC
        assert candidate.observed_timezone == zone
        loc = next(
            location for location in candidate.field_locations if location.field == "observed_at"
        )
        assert json.loads(loc.raw_token) == iso


def test_raw_observation_clock_cannot_precede_actual_start_or_exceed_actual_end(work):
    work.row["observed_at"] = (work.run.actual_start.occurred_at - timedelta(seconds=1)).isoformat()
    raw, fixed, observed = candidate(work)
    assert_failure(
        "INVALID_REPORT_TIME",
        lambda: verify_measurement(raw, fixed, observed.to_measurement(uuid4()), work.run),
    )
    work.row["observed_at"] = (work.run.actual_start.occurred_at + timedelta(minutes=2)).isoformat()
    raw, fixed, observed = candidate(work)
    ended = work.run.model_copy(
        update={
            "actual_end": work.run.actual_start.model_copy(
                update={"occurred_at": work.run.actual_start.occurred_at + timedelta(minutes=1)}
            )
        }
    )
    assert_failure(
        "INVALID_REPORT_TIME",
        lambda: verify_measurement(raw, fixed, observed.to_measurement(uuid4()), ended),
    )


def test_result_append_keeps_fixed_run_basis_but_configuration_or_method_change_does_not(work):
    raw, fixed, observed = candidate(work)
    measured = observed.to_measurement(uuid4())
    revised = work.run.model_copy(
        update={"revision": 3, "status": "results_pending", "measurements": (measured,)}
    )
    assert fixed_run_sha256(revised, work.plan) == fixed.run_basis_sha256
    verify_measurement(raw, fixed, measured, revised)
    changed = revised.model_copy(
        update={
            "items": (
                revised.items[0].model_copy(
                    update={
                        "method": SourceRef(
                            id=uuid4(), revision=1, kind="artifact", position="new-method"
                        )
                    }
                ),
            )
        }
    )
    assert_failure(
        "REPORT_BINDING_MISMATCH", lambda: verify_measurement(raw, fixed, measured, changed)
    )
    downgraded = work.run.model_copy(update={"revision": 1})
    assert_failure(
        "REPORT_BINDING_MISMATCH", lambda: verify_measurement(raw, fixed, measured, downgraded)
    )


def test_relabelled_config_or_trimmed_raw_or_fake_null_cannot_reuse_source_proof(work):
    raw, fixed, observed = candidate(work)
    measured = observed.to_measurement(uuid4())
    assert_failure(
        "MEASUREMENT_SOURCE_MISMATCH",
        lambda: verify_measurement(
            raw, fixed, measured.model_copy(update={"raw_value": None}), work.run
        ),
    )
    false_pairs = (
        fixed.pairs[0].model_copy(
            update={
                "sample": fixed.pairs[0].sample.model_copy(
                    update={"actual_configuration": ConfigurationRef(id=uuid4(), revision=1)}
                )
            }
        ),
        fixed.pairs[1],
    )
    renamed = fixed.model_copy(update={"pairs": false_pairs})
    assert_failure(
        "REPORT_BINDING_MISMATCH", lambda: verify_measurement(raw, renamed, measured, work.run)
    )


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_json_tokens_are_rejected_separately_from_original_strings(work, token):
    raw = (
        content(work)
        .decode()
        .replace('"raw_value": "  +001.2300 "', f'"raw_value": {token}')
        .encode()
    )
    assert_failure("INVALID_REPORT_FORMAT", lambda: extract_observations(raw, binding(work, raw)))


@pytest.mark.parametrize(
    "payload",
    [
        b"\xff",
        b"\xef\xbb\xbf{}\n",
        b"{}\r",
        b"\n",
        b"[]\n",
        b'{"x":1}\nignored',
        b'{"x":1,"raw_value":"\\ud800"}\n',
    ],
)
def test_encoding_bom_blank_nonobject_partial_json_or_surrogate_are_not_observations(work, payload):
    with pytest.raises(DomainError) as failed:
        extract_observations(payload, binding(work, payload))
    assert failed.value.reason in {
        "INVALID_REPORT_ENCODING",
        "UNSUPPORTED_REPORT_LINE_BREAK",
        "INVALID_REPORT_FORMAT",
        "INVALID_REPORT_FIELD",
    }


def test_literal_unicode_line_separator_is_rejected_but_escaped_separator_is_supported(work):
    work.row["note"] = "literal\u2028break"
    raw = content(work)
    assert_failure(
        "UNSUPPORTED_REPORT_LINE_BREAK", lambda: extract_observations(raw, binding(work, raw))
    )
    raw = (json.dumps(work.row, ensure_ascii=True) + "\n").encode()
    assert extract_observations(raw, binding(work, raw)).observations[0].note == work.row["note"]


def test_full_bytes_hash_size_and_limits_precede_report_interpretation(work):
    raw = content(work)
    fixed = binding(work, raw)
    assert_failure("REPORT_HASH_MISMATCH", lambda: extract_observations(raw + b" ", fixed))
    assert_failure(
        "REPORT_HASH_MISMATCH", lambda: extract_observations(raw.replace(b"001", b"002"), fixed)
    )
    assert_failure(
        "REPORT_SIZE_LIMIT",
        lambda: extract_observations(raw, fixed, limits=VerifierLimits(max_input_bytes=10)),
    )
    assert_failure(
        "REPORT_LINE_LIMIT",
        lambda: extract_observations(raw, fixed, limits=VerifierLimits(max_line_bytes=10)),
    )
    two = content(work, (work.row, work.row))
    assert_failure(
        "AMBIGUOUS_REPORT_ROW",
        lambda: extract_observations(two, binding(work, two)),
    )
    deep = b'{"x": [[[[[[[[[1]]]]]]]]]}\n'
    assert_failure(
        "REPORT_STRUCTURE_LIMIT", lambda: extract_observations(deep, binding(work, deep))
    )


@pytest.mark.parametrize(
    "limit",
    [
        {"max_input_bytes": 0},
        {"max_input_bytes": 10000001},
        {"max_depth": True},
        {"max_line_bytes": 131073},
    ],
)
def test_limits_cannot_be_unbounded_or_boolean(limit):
    with pytest.raises(ValueError):
        VerifierLimits(**limit)
