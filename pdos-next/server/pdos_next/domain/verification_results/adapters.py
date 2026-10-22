"""Results ports stay within the caller's common T1/T2 transaction; no resource effects."""

from dataclasses import dataclass

from pdos_next.domain.verification.handlers import VerificationHandler
from pdos_next.domain.verification.ports import Ports
from pdos_next.domain.verification_front.adapters import FixedBuilds, TransactionCommands
from pdos_next.errors import DomainError


@dataclass
class ResultsCommands(TransactionCommands):
    fixed_run: object = None
    fixed_runs: tuple = ()

    def confirm(self, invocation, preview, authority):
        if not self.accepted_confirmation or invocation.operation not in {
            "test.results.import",
            "test.run.review",
            "test.disposition.decide",
        }:
            raise DomainError("CONFIRMATION_REQUIRED", "须先消费共同结果确认/具名批准。", 403)

    def run(self, scope, run_id):
        if self.fixed_run is None or self.fixed_run.scope != scope or self.fixed_run.id != run_id:
            raise DomainError("FORBIDDEN_SCOPE", "结果Run不在固定事务范围。", 403)
        return self.fixed_run

    def runs(self, scope, request_id):
        if scope != self.authority.scope or request_id != self.fixed_request.id:
            raise DomainError("FORBIDDEN_SCOPE", "结果Run集合不在固定请求范围。", 403)
        if any(run.scope != scope or run.request_id != request_id for run in self.fixed_runs):
            raise DomainError("INTEGRITY_MISMATCH", "聚合Run集合跨越固定请求。")
        return self.fixed_runs


@dataclass
class ResultsEvidence:
    check_source: object
    verify_original: object

    def check(self, scope, source, purpose):
        return self.check_source(scope, source, purpose)

    def verify_measurement(self, scope, measurement, run):
        return self.verify_original(scope, measurement, run)


@dataclass
class RetainedSamples:
    recheck_original: object

    def inspect(self, *args):
        raise DomainError("INVALID_OPERATION", "结果路径不办理新的样件可用性或开测。")

    def reserve(self, *args):
        raise DomainError("INVALID_OPERATION", "结果路径不得再预约或消费样件。")

    def recheck_running(self, scope, run):
        return self.recheck_original(scope, run)


def kernel(commands, build, check_source, verify_original, recheck_original):
    return VerificationHandler(
        Ports(
            commands=commands,
            builds=FixedBuilds(build, "executing"),
            evidence=ResultsEvidence(check_source, verify_original),
            samples=RetainedSamples(recheck_original),
        )
    )
