"""Deterministic unique-unit counting; percentages never serve as authority."""

from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from pdos_next.errors import DomainError
from pdos_next.schemas.manufacturing_trials.contracts import (
    Counts,
    Gap,
    Readiness,
    ResultRecord,
    YieldResult,
    YieldScope,
)


def readiness(gaps: tuple[Gap, ...]) -> Readiness:
    state = "BLOCKED" if any(g.state == "blocked" for g in gaps) else "UNKNOWN" if gaps else "READY"
    return Readiness(state=state, gaps=gaps)


def counts_from_units(record: ResultRecord) -> Counts:
    units = record.units
    return Counts(
        input_count=len(units),
        output_count=sum(u.final_state != "unprocessed" for u in units),
        first_pass=sum(u.first_result == "pass" for u in units),
        first_failed=sum(u.first_result == "fail" for u in units),
        first_unknown=sum(u.first_result == "unknown" for u in units),
        final_good=sum(u.final_state == "good" for u in units),
        reworked_good=sum(u.final_state == "good" and u.rework_cycles > 0 for u in units),
        scrap=sum(u.final_state == "scrap" for u in units),
        rework_pending=sum(u.final_state == "rework_pending" for u in units),
        undecided=sum(u.final_state == "undecided" for u in units),
        unprocessed=sum(u.final_state == "unprocessed" for u in units),
        rework_cycles=sum(u.rework_cycles for u in units),
    )


def _error():
    raise DomainError("COUNT_CONFLICT", "投入、首遍、互斥终态或返工数量矛盾。", 422)


def validate_counts(counts: Counts) -> None:
    total = counts.input_count
    for fields in (
        ("first_pass", "first_failed", "first_unknown", "unprocessed"),
        ("final_good", "scrap", "rework_pending", "undecided", "unprocessed"),
    ):
        values = [getattr(counts, name) for name in fields]
        if total is not None:
            if sum(v for v in values if v is not None) > total:
                _error()
            if all(v is not None for v in values) and sum(values) != total:
                _error()
    if total is not None:
        for name in Counts.model_fields:
            value = getattr(counts, name)
            if name != "rework_cycles" and value is not None and value > total:
                _error()
    output, unprocessed = counts.output_count, counts.unprocessed
    if total is not None and output is not None and unprocessed is not None:
        if output + unprocessed != total:
            _error()
    for fields in (
        ("first_pass", "first_failed", "first_unknown"),
        ("final_good", "scrap", "rework_pending", "undecided"),
    ):
        values = [getattr(counts, name) for name in fields]
        if output is not None:
            if sum(v for v in values if v is not None) > output:
                _error()
            if all(v is not None for v in values) and sum(values) != output:
                _error()
    first, final, reworked, failed = (
        counts.first_pass,
        counts.final_good,
        counts.reworked_good,
        counts.first_failed,
    )
    if final is not None and sum(v for v in (first, reworked) if v is not None) > final:
        _error()
    if (
        all(value is not None for value in (first, final, reworked, counts.first_unknown))
        and final > first + reworked + counts.first_unknown
    ):
        _error()
    if (
        failed is not None
        and counts.first_unknown is not None
        and reworked is not None
        and reworked > failed + counts.first_unknown
    ):
        _error()
    if counts.rework_cycles is not None and reworked is not None:
        if counts.rework_cycles < reworked:
            _error()


def calculate(counts: Counts, minimum_sample: int) -> YieldResult:
    if type(minimum_sample) is not int or minimum_sample < 1:
        raise DomainError("INVALID_SAMPLE_POLICY", "样本阈值须为服务器固定正整数。", 422)
    validate_counts(counts)
    warnings = []
    denominator = counts.input_count
    if denominator is None:
        warnings.append("UNKNOWN_DENOMINATOR")
    elif denominator == 0:
        warnings.append("ZERO_DENOMINATOR")
    elif denominator < minimum_sample:
        warnings.append("INSUFFICIENT_SAMPLE")
    if any(getattr(counts, name) is None for name in Counts.model_fields):
        warnings.append("MISSING_COUNTS")
    if counts.first_unknown is None or counts.first_unknown > 0:
        warnings.append("FIRST_RESULT_UNKNOWN")
    if any(
        getattr(counts, name) is None or getattr(counts, name) > 0
        for name in ("rework_pending", "undecided", "unprocessed")
    ):
        warnings.append("INCOMPLETE_FINAL_RESULTS")
    first_rate = None
    final_rate = None
    if denominator:
        if counts.first_pass is not None and counts.first_unknown == 0:
            with localcontext() as context:
                context.prec = 28
                context.rounding = ROUND_HALF_EVEN
                first_rate = Decimal(counts.first_pass) / Decimal(denominator)
        if counts.final_good is not None:
            with localcontext() as context:
                context.prec = 28
                context.rounding = ROUND_HALF_EVEN
                final_rate = Decimal(counts.final_good) / Decimal(denominator)
    return YieldResult(
        counts=counts,
        first_pass_yield=first_rate,
        final_good_yield=final_rate,
        warnings=tuple(warnings),
    )


def aggregate(observations: tuple[tuple[YieldScope, Counts], ...]) -> YieldResult:
    if not observations:
        raise DomainError("EMPTY_SCOPE", "没有可汇总的固定批次。", 422)
    basis = observations[0][0]
    seen = set()
    for scope, counts in observations:
        validate_counts(counts)
        # No overlap assumptions: repeated lots require an owner-proven partition first.
        if scope.basis.lot.id in seen:
            raise DomainError("OVERLAPPING_SCOPE", "同批次/修正续版不能重复汇总。", 422)
        seen.add(scope.basis.lot.id)
        fields = (
            "manufacturing_baseline",
            "line",
            "window_start",
            "window_end",
            "criterion",
            "nature",
            "minimum_sample",
        )
        if any(getattr(scope, f) != getattr(basis, f) for f in fields) or any(
            getattr(scope.basis, f) != getattr(basis.basis, f)
            for f in (
                "actual_configuration",
                "engineering_configuration",
                "process_revision",
                "unit",
            )
        ):
            raise DomainError("INCOMPATIBLE_SCOPE", "配置、工艺、单位或统计条件不相容。", 422)
    combined = {}
    for name in Counts.model_fields:
        values = [getattr(counts, name) for _, counts in observations]
        combined[name] = None if any(v is None for v in values) else sum(values)
    return calculate(Counts(**combined), basis.minimum_sample)
