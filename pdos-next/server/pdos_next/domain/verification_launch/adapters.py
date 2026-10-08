"""One common command transaction; confirmation and resource effects stay caller-owned."""

from dataclasses import dataclass

from pdos_next.domain.verification.handlers import VerificationHandler
from pdos_next.domain.verification.ports import Ports
from pdos_next.domain.verification_front.adapters import (
    BoundEvidence,
    FixedBuilds,
    TransactionCommands,
)
from pdos_next.domain.verification_handoff.adapters import InspectedSamples
from pdos_next.errors import DomainError


@dataclass
class LaunchCommands(TransactionCommands):
    fixed_run: object = None

    def confirm(self, invocation, preview, authority):
        if not self.accepted_confirmation or invocation.operation not in {
            "test.run.plan",
            "verification.schedule.promise",
            "test.run.start",
        }:
            raise DomainError("CONFIRMATION_REQUIRED", "必须先消费共同开测实质确认。", 403)

    def run(self, scope, run_id):
        if self.fixed_run is None or self.fixed_run.scope != scope or self.fixed_run.id != run_id:
            raise DomainError("FORBIDDEN_SCOPE", "Run不在本次固定事务范围。", 403)
        return self.fixed_run

    def runs(self, scope, request_id):
        if scope != self.authority.scope or request_id != self.fixed_request.id:
            raise DomainError("FORBIDDEN_SCOPE", "Run集合不在当前固定请求。", 403)
        return (self.fixed_run,) if self.fixed_run else ()


@dataclass
class LaunchSamples(InspectedSamples):
    reserve_one: object = None
    recheck_one: object = None

    def reserve(self, scope, run_id, samples, coverage, destructive, execution):
        if self.reserve_one is None:
            raise DomainError("INTEGRATION_REQUIRED", "测试资源及样件占用未接通。", 503)
        return self.reserve_one(scope, run_id, samples, coverage, destructive, execution)

    def recheck_running(self, scope, run):
        if self.recheck_one is None:
            raise DomainError("INTEGRATION_REQUIRED", "原测试占用重核未接通。", 503)
        return self.recheck_one(scope, run)


def kernel(commands, build, check_source, samples):
    return VerificationHandler(
        Ports(
            commands=commands,
            builds=FixedBuilds(build, "executing"),
            evidence=BoundEvidence(check_source),
            samples=samples,
        )
    )
