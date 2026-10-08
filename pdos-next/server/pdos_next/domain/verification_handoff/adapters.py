"""One transaction, the delivered kernel, and server-inspected physical facts."""

from dataclasses import dataclass

from pdos_next.domain.verification.handlers import VerificationHandler
from pdos_next.domain.verification.ports import Ports, SampleAvailability
from pdos_next.domain.verification_front.adapters import (
    BoundEvidence,
    FixedBuilds,
    TransactionCommands,
)
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import EventTime, SourceRef


@dataclass
class HandoffCommands(TransactionCommands):
    def confirm(self, invocation, preview, authority):
        if not self.accepted_confirmation or invocation.operation not in {
            "verification.handoff.offer",
            "verification.handoff.accept",
            "verification.handoff.return",
        }:
            raise DomainError("CONFIRMATION_REQUIRED", "必须先消费共同交接实质确认。", 403)


@dataclass
class InspectedSamples:
    inspect_one: object
    actual_applicable: object

    def inspect(self, scope, sample, purpose):
        value = self.inspect_one(sample)
        readiness = value.get("current_readiness")
        ready_at = None
        if value["availability"] == "ready" and readiness:
            clocks = readiness.get("clocks") or value.get("clocks")
            reference = readiness.get("source_ref")
            if clocks and reference:
                ready_at = EventTime(
                    occurred_at=clocks["occurred_at"],
                    original_timezone=clocks["original_timezone"],
                    source=SourceRef.model_validate(reference),
                )
        source = SourceRef(
            id=sample.id, revision=sample.revision, kind="domain", position="actual-sample"
        )
        return SampleAvailability(
            sample=sample,
            available=value["availability"] == "ready",
            applicable=self.actual_applicable(sample),
            source=source,
            ready_at=ready_at,
            reason="实物就绪、实际配置适用或其当前权威依据尚未满足。",
        )

    def reserve(self, *args):
        raise DomainError("INTEGRATION_REQUIRED", "交接不预约或消耗样件。", 503)


def kernel(commands, build_ref, build_status, check_source, samples):
    return VerificationHandler(
        Ports(
            commands=commands,
            builds=FixedBuilds(build_ref, build_status),
            evidence=BoundEvidence(check_source),
            samples=samples,
        )
    )
