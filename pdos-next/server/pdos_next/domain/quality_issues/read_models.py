"""Permission-aware read mapping; values are fetched from fixed authoritative Run."""

from typing import Literal
from uuid import UUID

from pdos_next.errors import DomainError
from pdos_next.schemas.quality_issues.contracts import FailureRef, Issue, Ref
from pdos_next.schemas.verification.contracts import DTO, Measurement

from .ports import Ports
from .rules import failure_ref, issue_sources


class FailureReading(DTO):
    failure: FailureRef
    measurement: Measurement | None = None
    available: bool
    reasons: tuple[str, ...] = ()


class FollowupNeed(DTO):
    kind: Literal["engineering_change_assessment", "new_verification_run"]
    source_issue: Ref
    failure_ids: tuple[str, ...]
    reason: str
    # A requirement is not a ChangeRequest/Order or a created Build/Run.


class IssueReading(DTO):
    issue: Issue
    failures: tuple[FailureReading, ...]
    originals: tuple[Issue, ...] = ()
    current: bool
    recheck_reasons: tuple[str, ...] = ()
    followup_needs: tuple[FollowupNeed, ...] = ()


class QualityIssueReader:
    def __init__(self, ports: Ports):
        self.ports = ports

    def get(self, issue_id: UUID) -> IssueReading:
        if self.ports.commands is None or self.ports.runs is None:
            raise DomainError("INTEGRATION_REQUIRED", "问题/固定Run读取接口待接入。", 503)
        if any(not callable(getattr(self.ports.commands, m, None)) for m in ("context", "issue")):
            raise DomainError("INTEGRATION_REQUIRED", "问题读取接口待接入。", 503)
        if any(
            not callable(getattr(self.ports.runs, m, None)) for m in ("currentness", "original")
        ):
            raise DomainError("INTEGRATION_REQUIRED", "归档Run读取接口待接入。", 503)
        authority = self.ports.commands.context("quality.issue.read", issue_id)
        if not authority.authorized or authority.cancelled:
            raise DomainError("FORBIDDEN_OPERATION", "当前范围不可读取。", 403)
        issue = self.ports.commands.issue(authority.scope, issue_id)
        if issue.scope != authority.scope or not set(issue.audience) <= set(authority.audience):
            raise DomainError("FORBIDDEN_SCOPE", "问题范围/受众不可读取。", 403)
        originals = tuple(
            self.ports.commands.issue(authority.scope, alias) for alias in issue.aliases
        )
        if any(
            o.scope != authority.scope or not set(o.audience) <= set(authority.audience)
            for o in originals
        ):
            raise DomainError("FORBIDDEN_SCOPE", "原问题范围/受众不可读取。", 403)
        readings = []
        for failure in issue.failures:
            current = self.ports.runs.currentness(authority.scope, failure)
            if not current.current:
                readings.append(
                    FailureReading(
                        failure=failure,
                        available=False,
                        reasons=current.reasons or ("固定来源待重核。",),
                    )
                )
                continue
            # original must resolve archived exact Run revision, not substitute latest.
            verified = self.ports.runs.original(authority.scope, failure.run)
            actual = failure_ref(verified, failure.measurement_id)
            if actual != failure or verified.run.scope != authority.scope:
                raise DomainError("FIXED_REFERENCE_MISMATCH", "原Run固定引用不一致。")
            measurement = next(
                m for m in verified.run.measurements if m.id == failure.measurement_id
            )
            readings.append(
                FailureReading(failure=failure, measurement=measurement, available=True)
            )
        sources = issue_sources(issue)
        if sources and not callable(getattr(self.ports.evidence, "currentness", None)):
            raise DomainError("INTEGRATION_REQUIRED", "当前判断来源读取接口待接入。", 503)
        judgments = tuple(
            self.ports.evidence.currentness(authority.scope, s, "quality.issue") for s in sources
        )
        reasons = issue.recheck_reasons + tuple(r for row in readings for r in row.reasons)
        reasons += tuple(
            r
            for judgment in judgments
            if not judgment.current
            for r in (judgment.reasons or ("判断来源已失效，待重核。",))
        )
        needs = []
        ref = Ref(id=issue.id, revision=issue.revision)
        ids = tuple(f.identity for f in issue.failures)
        if issue.root_cause:
            needs.append(
                FollowupNeed(
                    kind="engineering_change_assessment",
                    source_issue=ref,
                    failure_ids=ids,
                    reason="工程评估是否需要双线变更；本模块不创建或批准ChangeOrder。",
                )
            )
        if issue.capa:
            needs.append(
                FollowupNeed(
                    kind="new_verification_run",
                    source_issue=ref,
                    failure_ids=ids,
                    reason="按固定有效性要求形成新Run/观察依据，不复用原失败Run。",
                )
            )
        return IssueReading(
            issue=issue,
            originals=originals,
            failures=tuple(readings),
            current=not issue.needs_recheck
            and all(r.available for r in readings)
            and all(j.current for j in judgments),
            recheck_reasons=reasons,
            followup_needs=tuple(needs),
        )
