"""Deterministic failure identity; no model-proposed fact or title deduplication."""

import hashlib
import json
from uuid import UUID

from pdos_next.domain.verification.rules import compute_results
from pdos_next.errors import DomainError
from pdos_next.schemas.quality_issues.contracts import FailureRef, Ref

from .ports import VerifiedRun


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def semantic_digest(payload) -> str:
    return digest(payload.model_dump(mode="json"))


def replace(record, **changes):
    return type(record).model_validate({**record.model_dump(), **changes})


def capa_draft_text_revisable(issue) -> bool:
    """Structural pending-draft eligibility; the host separately excludes saved Links."""
    return bool(
        issue.status in {"triaged", "actioning"}
        and issue.capa is not None
        and issue.root_cause is None
        and all(action.completion is None for action in issue.capa.actions)
        and issue.capa.effectiveness is None
        and not issue.capa.effectiveness_history
        and issue.closure is None
        and not issue.needs_recheck
        and issue.merged_into is None
    )


def failure_ref(verified: VerifiedRun, measurement_id: UUID) -> FailureRef:
    run = verified.run
    if (
        len({i.id for i in run.items}) != len(run.items)
        or len({s.id for s in run.samples}) != len(run.samples)
        or len({(c.sample_id, c.item_id) for c in run.coverage}) != len(run.coverage)
    ):
        raise DomainError("FAILURE_CONTEXT_MISSING", "固定测试范围身份重复。", 422)
    if run.status not in {"running", "results_pending", "reviewed", "disposed"}:
        raise DomainError("NOT_ACTUAL_FAILURE", "计划或未执行Run不能建失败问题。", 422)
    if run.actual_start is None or run.execution is None or run.result != "fail":
        raise DomainError("NOT_ACTUAL_FAILURE", "必须是已有实测的确定失败结果。", 422)
    measurements = [m for m in run.measurements if m.id == measurement_id]
    if len(measurements) != 1:
        raise DomainError("NOT_ACTUAL_FAILURE", "需要唯一固定测量。", 422)
    m = measurements[0]
    try:
        results, _ = compute_results(run, run.measurements, final=run.final_result is not None)
    except (KeyError, StopIteration) as exc:
        raise DomainError("FAILURE_CONTEXT_MISSING", "固定测试项/范围不完整。", 422) from exc
    result = next((r for r in results if r.measurement_id == m.id), None)
    stored = next((r for r in run.computed_results if r.measurement_id == m.id), None)
    if result is None or result.result != "fail" or stored != result:
        raise DomainError("NOT_ACTUAL_FAILURE", "未知/无测量或权威判定不一致不能建失败问题。", 422)
    if m.observed_at is None or m.observed_at < run.actual_start.occurred_at:
        raise DomainError("FAILURE_CONTEXT_MISSING", "测量须有真实开始后的观察时间。", 422)
    if run.status != "running" and (run.actual_end is None or run.final_result is None):
        raise DomainError("FAILURE_CONTEXT_MISSING", "最终结果须保留真实结束和返回事实。", 422)
    if run.actual_end and (
        m.observed_at > run.actual_end.occurred_at
        or run.actual_end.occurred_at < run.actual_start.occurred_at
    ):
        raise DomainError("FAILURE_CONTEXT_MISSING", "测量/开始/结束时间不一致。", 422)
    if (
        run.actual_end
        and run.final_result
        and (run.actual_end.occurred_at > run.final_result.occurred_at)
    ):
        raise DomainError("FAILURE_CONTEXT_MISSING", "结果返回不能早于真实结束。", 422)
    item = next(i for i in run.items if i.id == m.coverage.item_id)
    sample = next((s for s in run.samples if s.id == m.coverage.sample_id), None)
    if not sample or sample.build_id != run.build.id or not item.criterion or not m.source:
        raise DomainError("FAILURE_CONTEXT_MISSING", "精确配置/样件/判据/来源缺失。", 422)
    if m.method is None or m.method != item.method:
        raise DomainError("FAILURE_CONTEXT_MISSING", "测量方法与固定方法不一致。", 422)
    identity = digest(
        {
            "scope": run.scope.model_dump(mode="json"),
            "run": str(run.id),
            "measurement": str(m.id),
            "sample": str(sample.id),
            "item": item.id,
            "criterion": item.criterion.source.model_dump(mode="json"),
        }
    )
    return FailureRef(
        identity=identity,
        run=Ref(id=run.id, revision=run.revision),
        measurement_id=m.id,
        executor_id=run.execution.executor_id,
        coverage=m.coverage,
        build=run.build,
        sample=sample,
        criterion=item.criterion.source,
        method=m.method,
        source=m.source,
        nature=verified.nature,
    )


def issue_sources(issue, *, distinct=False):
    """Current judgments, optionally one occurrence per exact direct reference."""
    sources = tuple(s for c in issue.containment for s in (*c.evidence, c.at.source))
    if issue.root_cause:
        sources += issue.root_cause.sources
    if issue.capa:
        sources += tuple(s for h in issue.capa.hypotheses for s in h.sources)
        sources += tuple(
            s
            for a in issue.capa.actions
            if a.completion
            for s in (*a.completion.evidence, a.completion.at.source)
        )
        if issue.capa.effectiveness:
            sources += issue.capa.effectiveness.sources
    if issue.closure:
        sources += issue.closure.sources
    if not distinct:
        # Readers and recheck preserve the raw sequence and diagnostic counts.
        return sources
    selected = {}
    for source in sources:
        key = (source.kind, source.id, source.revision, source.position)
        selected.setdefault(key, source)
    return tuple(selected.values())
