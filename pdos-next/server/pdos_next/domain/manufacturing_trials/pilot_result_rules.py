"""Pure counts; no original-value extraction, I/O, authorization or persistence."""

from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from pdos_next.domain.manufacturing_trials.rules import (
    calculate as existing_calculate,
)
from pdos_next.domain.manufacturing_trials.rules import (
    counts_from_units,
    validate_counts,
)
from pdos_next.errors import DomainError
from pdos_next.schemas.manufacturing_trials.contracts import Counts
from pdos_next.schemas.manufacturing_trials.pilot_results import (
    AggregateProjection,
    Metrics,
    PilotProjection,
    Rate,
    RecordedBatch,
)


def _require(condition, code, detail, status=422):
    if not condition:
        raise DomainError(code, detail, status)


def _fraction(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return None
    with localcontext() as context:
        context.prec = 28
        context.rounding = ROUND_HALF_EVEN
        return Decimal(numerator) / Decimal(denominator)


def _rate(numerator, denominator, complete):
    fraction = _fraction(numerator, denominator)
    return Rate(
        numerator=numerator,
        denominator=denominator,
        recorded_fraction=fraction,
        value=fraction if complete else None,
        partition_complete=complete,
        state=(
            "undefined_zero_denominator"
            if denominator == 0
            else "unknown"
            if fraction is None
            else "known"
            if complete
            else "partial"
        ),
    )


def _metrics(counts, denominator, minimum_sample):
    validate_counts(counts)
    if denominator is not None and counts.input_count is not None:
        _require(
            counts.input_count == denominator,
            "FIXED_DENOMINATOR_CHANGED",
            "投入不是固定母批/样本分母。",
        )
    if denominator is not None:
        # Internal validation only: missing report input remains None in the
        # returned original Counts, never repaired with a host number or zero.
        validate_counts(counts.model_copy(update={"input_count": denominator}))
    original = existing_calculate(counts, minimum_sample)
    warnings = list(original.warnings)
    if denominator is None:
        warnings.append("FIXED_DENOMINATOR_UNKNOWN")
    if counts.input_count is None:
        warnings.append("REPORTED_INPUT_UNKNOWN")
    input_known = denominator not in (None, 0) and counts.input_count == denominator
    first_complete = (
        input_known
        and all(
            getattr(counts, name) is not None
            for name in ("first_pass", "first_failed", "first_unknown", "unprocessed")
        )
        and counts.first_unknown == 0
        and counts.unprocessed == 0
    )
    final_complete = (
        input_known
        and all(
            getattr(counts, name) is not None
            for name in ("final_good", "scrap", "rework_pending", "undecided", "unprocessed")
        )
        and counts.rework_pending == counts.undecided == counts.unprocessed == 0
    )
    if not first_complete:
        warnings.append("FIRST_PASS_PARTITION_NOT_FINAL")
    if not final_complete:
        warnings.append("FINAL_GOOD_PARTITION_NOT_FINAL")
    return Metrics(
        first_pass_yield=_rate(counts.first_pass, denominator, first_complete),
        final_good_yield=_rate(counts.final_good, denominator, final_complete),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def check_time(batch, checked_at):
    _require(
        isinstance(checked_at, datetime) and checked_at.utcoffset() is not None,
        "FRESH_SERVER_CLOCK_REQUIRED",
        "须使用owner全部IO后的服务器实际aware时钟。",
        503,
    )
    _require(
        batch.record.observed.occurred_at <= checked_at
        and batch.fixed.yield_scope.window_end <= checked_at,
        "FUTURE_OBSERVATION",
        "原观察及固定统计窗口不得晚于实际核对时钟。",
    )


def project(batch: RecordedBatch, *, checked_at: datetime) -> PilotProjection:
    if type(batch) is not RecordedBatch:
        raise DomainError("ACTUAL_FIXED_DTO_REQUIRED", "须解析完整固定结果DTO。", 422)
    check_time(batch, checked_at)
    counts = (
        batch.record.counts if batch.record.counts is not None else counts_from_units(batch.record)
    )
    metrics = _metrics(
        counts, batch.fixed.cohort.fixed_input_count, batch.fixed.yield_scope.minimum_sample
    )
    if batch.fixed.cohort.unit_refs is None:
        metrics = metrics.model_copy(
            update={"warnings": metrics.warnings + ("COHORT_MEMBERSHIP_NOT_ENUMERATED",)}
        )
    return PilotProjection(
        fixed=batch.fixed,
        counts=counts,
        metrics=metrics,
        observation_id=batch.record.observation_id,
    )


def revision(
    previous: RecordedBatch, current: RecordedBatch, *, checked_at: datetime
) -> PilotProjection:
    # Explicit expected CAS and correction lineage, never replace old projection.
    _require(
        previous.fixed.pilot_id == current.fixed.pilot_id
        and current.fixed.pilot_revision == previous.fixed.pilot_revision + 1,
        "PILOT_REVISION_CONFLICT",
        "结果修订须为同一Pilot的真实下一固定版本。",
    )
    _require(
        current.record.previous_observation_id == previous.record.observation_id
        and current.record.observation_id != previous.record.observation_id
        and bool(current.record.correction_reason),
        "OBSERVATION_REVISION_CONFLICT",
        "须固定前一观察和实际修正原因。",
    )
    expected = previous.fixed.model_dump()
    actual = current.fixed.model_dump()
    expected.pop("pilot_revision")
    actual.pop("pilot_revision")
    _require(
        expected == actual, "FIXED_SCOPE_CHANGED", "修订不得改变固定配置、成员、分母或统计条件。"
    )
    old, new = project(previous, checked_at=checked_at), project(current, checked_at=checked_at)
    _require(
        old.counts.input_count == new.counts.input_count,
        "FIXED_DENOMINATOR_CHANGED",
        "修订不能改变原投入口径。",
    )
    _require(
        current.record.observed.occurred_at >= previous.record.observed.occurred_at,
        "OBSERVATION_TIME_REVERSED",
        "修订发生钟不能倒退。",
    )
    return new


def _compatibility(fixed):
    scope = fixed.yield_scope
    # Lot/cohort identity and Pilot id intentionally differ for disjoint batches.
    return (
        fixed.scope,
        fixed.purpose,
        fixed.site,
        fixed.original_timezone,
        scope.basis.build,
        scope.basis.actual_configuration,
        scope.basis.engineering_configuration,
        scope.basis.process_revision,
        scope.basis.unit,
        scope.manufacturing_baseline,
        scope.line,
        scope.window_start,
        scope.window_end,
        scope.criterion,
        scope.nature,
        scope.minimum_sample,
        fixed.cohort.mode,
        fixed.cohort.denominator_policy,
        fixed.cohort.statistics_basis_key,
    )


def aggregate(batches: tuple[RecordedBatch, ...], *, checked_at: datetime) -> AggregateProjection:
    _require(
        type(batches) is tuple and len(batches) >= 1,
        "INVALID_AGGREGATE",
        "须选择有界固定批次。",
    )
    _require(
        all(type(batch) is RecordedBatch for batch in batches),
        "ACTUAL_FIXED_DTO_REQUIRED",
        "批次必须全部是完整固定DTO。",
    )
    basis = _compatibility(batches[0].fixed)
    lots, pilots, members = set(), set(), set()
    projections = []
    for batch in batches:
        fixed = batch.fixed
        _require(
            _compatibility(fixed) == basis,
            "INCOMPATIBLE_SCOPE",
            "产品/Build/实际配置/工艺/线体/条件/政策不相容。",
        )
        _require(
            fixed.yield_scope.basis.lot.id not in lots and fixed.pilot_id not in pilots,
            "OVERLAPPING_SCOPE",
            "同批次/Pilot及历史修正不能重复汇总。",
        )
        _require(
            fixed.cohort.unit_refs is not None,
            "COHORT_MEMBERSHIP_UNKNOWN",
            "缺实际成员全集时不能证明批次不重叠。",
            503,
        )
        ids = {ref.id for ref in fixed.cohort.unit_refs}
        _require(not ids & members, "OVERLAPPING_UNITS", "实际单件不能跨批次重复计算。")
        lots.add(fixed.yield_scope.basis.lot.id)
        pilots.add(fixed.pilot_id)
        members.update(ids)
        projections.append(project(batch, checked_at=checked_at))
    counts = Counts(
        **{
            key: None
            if any(getattr(p.counts, key) is None for p in projections)
            else sum(getattr(p.counts, key) for p in projections)
            for key in Counts.model_fields
        }
    )
    denominators = [batch.fixed.cohort.fixed_input_count for batch in batches]
    denominator = None if any(v is None for v in denominators) else sum(denominators)
    return AggregateProjection(
        members=tuple(batch.fixed for batch in batches),
        counts=counts,
        metrics=_metrics(counts, denominator, batches[0].fixed.yield_scope.minimum_sample),
    )
