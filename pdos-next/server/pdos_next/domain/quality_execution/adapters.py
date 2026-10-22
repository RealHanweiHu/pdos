"""Adapters for the delivered quality kernel, within one caller-owned Session."""

from dataclasses import dataclass

from pdos_next.domain.quality_issues.handlers import QualityIssueHandler
from pdos_next.domain.quality_issues.ports import Currentness, Outcome, Ports, QualityPolicy
from pdos_next.domain.quality_issues.rules import failure_ref
from pdos_next.errors import DomainError
from pdos_next.schemas.quality_issues.contracts import Ref


@dataclass
class TransactionCommands:
    authority: object
    invocation: object
    issues: dict
    failure_issues: dict
    record_mutation: object
    accepted_confirmation: bool = False

    def context(self, operation, subject_id):
        if operation != self.invocation.operation or subject_id != self.invocation.subject_id:
            raise DomainError("FORBIDDEN_SCOPE", "品质操作不在固定事务上下文。", 403)
        return self.authority

    def begin(self, invocation):
        if invocation != self.invocation:
            raise DomainError("INTEGRITY_MISMATCH", "品质领域载荷与共同命令绑定不一致。")
        return self.authority

    def replay(self, invocation, authority):
        # Common execute already resolved exact key and semantic Receipt replays.
        return None

    def issue(self, scope, issue_id):
        issue = self.issues.get(issue_id)
        if issue is None or issue.scope != scope:
            raise DomainError("FORBIDDEN_SCOPE", "问题不在当前固定范围。", 403)
        return issue

    def by_failure(self, scope, identity):
        issue = self.failure_issues.get(identity)
        if issue is not None and issue.scope != scope:
            raise DomainError("FORBIDDEN_SCOPE", "稳定失败映射跨越品质范围。", 403)
        return issue

    def confirm(self, invocation, preview, authority):
        if (
            not self.accepted_confirmation
            or invocation != self.invocation
            or (
                invocation.operation
                not in {
                    "quality.issue.merge",
                    "quality.issue.triage",
                    "quality.issue.containment.record",
                }
            )
        ):
            raise DomainError("CONFIRMATION_REQUIRED", "必须先消费共同实质确认。")

    def record(self, invocation, mutation):
        row = self.record_mutation(mutation)
        return Outcome(subject_id=row.issue_id, revision=row.revision, status=row.status)


@dataclass
class FixedRuns:
    values: tuple
    create_result: object = None

    def fixed(self, scope, run_id):
        value = self.create_result
        if value is None or value.scope != scope or value.verified.run.id != run_id:
            raise DomainError("FORBIDDEN_SCOPE", "失败Run没有精确服务器事件绑定。", 403)
        return value.verified

    def original(self, scope, run):
        value = next(
            (
                v
                for v in self.values
                if v.scope == scope
                and v.verified.run.id == run.id
                and v.run_revision == run.revision
            ),
            None,
        )
        if value is None:
            raise DomainError("INTEGRATION_REQUIRED", "归档失败Run读取接口尚未绑定。", 503)
        return value.verified

    def delivery(self, scope, event_id, failure):
        value = self.create_result
        if (
            value is None
            or value.scope != scope
            or value.event_id != event_id
            or (
                value.measurement_id != failure.measurement_id
                or failure_ref(value.verified, value.measurement_id) != failure
            )
        ):
            raise DomainError("INTEGRITY_MISMATCH", "源事件不属于精确失败与判据。")

    def currentness(self, scope, failure):
        direct = next(
            (v for v in self.values if getattr(v, "failure", None) == failure and v.scope == scope),
            None,
        )
        if direct is not None:
            return Currentness(current=direct.current, reasons=direct.reasons)
        value = next(
            (
                v
                for v in self.values
                if v.scope == scope
                and v.verified.run.id == failure.run.id
                and v.run_revision == failure.run.revision
                and v.measurement_id == failure.measurement_id
            ),
            None,
        )
        if value is None:
            raise DomainError("INTEGRATION_REQUIRED", "失败原件/执行证明接口未接入。", 503)
        return Currentness(
            current=value.current
            and failure_ref(value.verified, failure.measurement_id) == failure,
            reasons=value.reasons,
        )


@dataclass
class BoundEvidence:
    check_source: object

    def check(self, scope, source, purpose):
        self.check_source(scope, source)

    def currentness(self, scope, source, purpose):
        self.check_source(scope, source)
        return Currentness(current=True)


@dataclass
class BoundPolicy:
    value: object

    def assess(self, authority, failures):
        if self.value is None:
            raise DomainError("INTEGRATION_REQUIRED", "当前风险政策发布接口未接入。", 503)
        return QualityPolicy(
            ref=Ref(id=self.value["id"], revision=self.value["revision"]),
            risk=self.value["risk"],
            independent_verification=self.value["independent_verification"],
        )

    def verification(self, *args):
        raise DomainError("INTEGRATION_REQUIRED", "本切片未接独立有效性复验。", 503)


def kernel(commands, results, create_result, check_source, policy):
    return QualityIssueHandler(
        Ports(
            commands=commands,
            runs=FixedRuns(tuple(results), create_result),
            evidence=BoundEvidence(check_source),
            policies=BoundPolicy(policy),
        )
    )
