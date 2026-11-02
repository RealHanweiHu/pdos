"""Deterministic scope/readiness/results. Unknown measurements never become pass."""

from decimal import Decimal, InvalidOperation

from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import (
    ComputedResult,
    Coverage,
    Gap,
    Measurement,
    SampleRef,
    TestRun,
    VerificationRequest,
)


def pairs(coverage: tuple[Coverage, ...]) -> set[tuple]:
    return {(c.sample_id, c.item_id) for c in coverage}


def accepted_coverage(request: VerificationRequest) -> tuple[Coverage, ...]:
    result = {}
    for acceptance in request.acceptances:
        for c in acceptance.coverage:
            result[(c.sample_id, c.item_id)] = c
    return tuple(result[key] for key in sorted(result, key=lambda k: (str(k[0]), k[1])))


def check_coverage(
    request: VerificationRequest,
    coverage: tuple[Coverage, ...],
    samples: tuple[SampleRef, ...] | None = None,
) -> None:
    if not coverage or len(pairs(coverage)) != len(coverage):
        raise DomainError("INVALID_COVERAGE", "覆盖范围须非空，样件/测试项不能重复。", 422)
    sample_refs = request.samples if samples is None else samples
    indexed_samples = {s.id: s for s in sample_refs}
    if len(indexed_samples) != len(sample_refs):
        raise DomainError("INVALID_COVERAGE", "一个样件只能有一个固定实际配置版本。", 422)
    items = {i.id: i for i in request.items}
    for c in coverage:
        sample, item = indexed_samples.get(c.sample_id), items.get(c.item_id)
        if sample is None or item is None:
            raise DomainError("INVALID_COVERAGE", "覆盖引用不在本次样件和测试项范围内。", 422)
        if sample.build_id != request.build.id:
            raise DomainError("FORBIDDEN_SCOPE", "样件不属于固定 Build。", 403)
        if item.cavities and sample.cavity not in item.cavities:
            raise DomainError("INAPPLICABLE_CONFIGURATION", "样件模穴不适用于所选测试项。")


def document_gaps(
    request: VerificationRequest,
    item_ids: set[str] | None = None,
) -> tuple[Gap, ...]:
    selected = {i.id for i in request.items} if item_ids is None else item_ids
    gaps = []
    for item in request.items:
        if item.id not in selected:
            continue
        missing = [
            name
            for name in ("drawing", "method", "unit", "conditions", "material")
            if getattr(item, name) is None
        ]
        if item.criterion is None and not (item.criterion_text and item.criterion_source):
            missing.append("criterion")
        gaps.extend(
            Gap(code="DOCUMENT_MISSING", item_id=item.id, detail=f"缺少 {name}") for name in missing
        )
    for doc in request.documents:
        if doc.required and doc.source is None:
            gaps.extend(
                Gap(code="DOCUMENT_MISSING", item_id=key, detail=f"缺少 {doc.title}")
                for key in doc.item_ids
                if key in selected
            )
    return tuple(gaps)


def coverage_gaps(request: VerificationRequest, coverage: tuple[Coverage, ...]) -> tuple[Gap, ...]:
    """Planning coverage compared to requested counts/cavities; partial remains explicit."""
    samples = {s.id: s for s in request.samples}
    gaps = []
    for item in request.items:
        ids = {c.sample_id for c in coverage if c.item_id == item.id}
        if len(ids) < item.sample_count:
            gaps.append(
                Gap(
                    code="PARTIAL_SAMPLE_COUNT",
                    item_id=item.id,
                    detail=f"已覆盖 {len(ids)}/{item.sample_count} 件",
                )
            )
        cavities = {samples[k].cavity for k in ids if k in samples}
        for cavity in sorted(set(item.cavities) - cavities):
            gaps.append(
                Gap(code="UNCOVERED_CAVITY", item_id=item.id, detail=f"未覆盖模穴 {cavity}")
            )
    return tuple(gaps)


def compute_results(
    run: TestRun,
    measurements: tuple[Measurement, ...],
    final: bool = False,
) -> tuple[tuple[ComputedResult, ...], str]:
    known = pairs(run.coverage)
    by_pair = {}
    ids = set()
    for m in measurements:
        key = (m.coverage.sample_id, m.coverage.item_id)
        if key not in known or key in by_pair or m.id in ids:
            raise DomainError("INVALID_MEASUREMENT_SCOPE", "测量范围越界或重复。", 422)
        by_pair[key] = m
        ids.add(m.id)
    items = {i.id: i for i in run.items}
    output = []
    for coverage in run.coverage:
        m = by_pair.get((coverage.sample_id, coverage.item_id))
        item = items[coverage.item_id]
        if m is None:
            output.append(
                ComputedResult(coverage=coverage, result="indeterminate", reasons=("尚未返回测量",))
            )
            continue
        missing = list(m.missing)
        missing.extend(
            f"缺少 {name}"
            for name in (
                "raw_value",
                "unit",
                "conditions",
                "equipment",
                "environment",
                "method",
                "source",
                "observed_at",
                "observed_timezone",
            )
            if getattr(m, name) is None or getattr(m, name) == ""
        )
        if m.unit != item.unit:
            missing.append("单位与判据不一致，未执行单位换算")
        if m.conditions != item.conditions:
            missing.append("工况与要求不一致，需专业适用性判断")
        if m.method != item.method:
            missing.append("测试方法版本与固定方法不一致")
        if run.execution is None:
            missing.append("缺少真实执行条件")
        elif m.equipment != run.execution.equipment or m.environment != run.execution.environment:
            missing.append("设备或环境与本次执行不一致")
        if run.execution is not None and m.conditions != run.execution.conditions:
            missing.append("工况与真实执行记录不一致")
        if item.criterion is None:
            missing.append("缺少可确定性计算的数值判据，需专业判断")
        numeric = None
        if m.raw_value is not None:
            try:
                numeric = Decimal(m.raw_value)
                if not numeric.is_finite():
                    missing.append("读数不是有限数值")
            except InvalidOperation:
                missing.append("原值不能按本次数值判据解析")
        result = "indeterminate"
        if not missing and numeric is not None:
            criterion = item.criterion
            outside = (criterion.lower is not None and numeric < criterion.lower) or (
                criterion.upper is not None and numeric > criterion.upper
            )
            result = "fail" if outside else "pass"
        output.append(
            ComputedResult(
                coverage=coverage, result=result, measurement_id=m.id, reasons=tuple(missing)
            )
        )
    outcomes = {o.result for o in output}
    # Early failures are meaningful for their explicit coverage, never overall success.
    if "fail" in outcomes:
        aggregate = "fail"
    elif "indeterminate" in outcomes or not final:
        aggregate = "indeterminate"
    else:
        aggregate = "pass"
    return tuple(output), aggregate
