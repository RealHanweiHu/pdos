"""One kernel invocation, one host append, one REAL shared proof consumption."""

from dataclasses import dataclass
from uuid import UUID

from pdos_next.domain.quality_execution.adapters import BoundEvidence, BoundPolicy, FixedRuns
from pdos_next.domain.quality_issues.handlers import QualityIssueHandler
from pdos_next.domain.quality_issues.ports import Outcome, Ports
from pdos_next.errors import DomainError


@dataclass
class TransactionCommands:
    authority: object
    invocation: object
    issue_value: object
    record_mutation: object
    consumed_proof_id: UUID | None = None

    def context(self, operation, subject_id):
        if (operation, subject_id) != (self.invocation.operation, self.issue_value.id):
            raise DomainError("FORBIDDEN_SCOPE", "后续动作不在固定问题范围。", 403)
        return self.authority

    def begin(self, invocation):
        if invocation != self.invocation:
            raise DomainError("INTEGRITY_MISMATCH", "共同命令未绑定本次领域意图。")
        return self.context(invocation.operation, invocation.subject_id)

    def replay(self, invocation, authority):
        # Shared execute already deduplicates keys/semantic Receipts. This adapter
        # never invents an unchecked replay outcome or consumes a second proof.
        return None

    def issue(self, scope, issue_id):
        if scope != self.issue_value.scope or issue_id != self.issue_value.id:
            raise DomainError("FORBIDDEN_SCOPE", "问题不在固定服务器范围。", 403)
        return self.issue_value

    def by_failure(self, scope, identity):
        return None

    def confirm(self, invocation, preview, authority):
        if invocation != self.invocation or not isinstance(self.consumed_proof_id, UUID):
            raise DomainError("CONFIRMATION_REQUIRED", "共同已消费证明未接入。")
        if invocation.operation == "quality.issue.root_cause.decide":
            if invocation.decision_id != self.consumed_proof_id:
                raise DomainError("NAMED_APPROVAL_REQUIRED", "根因决定须绑定实际具名证明。")
        elif invocation.operation != "quality.capa.actions.complete":
            raise DomainError("FORBIDDEN_OPERATION", "未开放此后续动作。", 403)

    def record(self, invocation, mutation):
        row = self.record_mutation(mutation)
        return Outcome(subject_id=row.issue_id, revision=row.revision, status=row.status)


def kernel(commands, results, check_source, policy):
    return QualityIssueHandler(
        Ports(
            commands=commands,
            runs=FixedRuns(tuple(results)),
            policies=BoundPolicy(policy),
            evidence=BoundEvidence(check_source),
        )
    )
