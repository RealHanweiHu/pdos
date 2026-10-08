"""Future trusted bridges. Missing bridges cannot silently certify candidates."""

from typing import Protocol

from .schemas import CandidateBinding, CandidateInspect, FollowupBasis, OutputRef, ResolvedOutputs


class FollowupOwnerPort(Protocol):
    def __call__(
        self,
        s,
        ctx,
        product_id,
        basis: FollowupBasis,
        action_id,
        output_refs: tuple[OutputRef, ...],
        *,
        at=None,
        write=False,
    ) -> ResolvedOutputs: ...


class CandidateOwnerPort(Protocol):
    def __call__(
        self,
        s,
        ctx,
        product_id,
        binding: CandidateBinding,
        *,
        at,
        write=False,
    ) -> CandidateInspect: ...


def require_effectiveness_bridge():
    """No implemented bridge may be mistaken for policy, qualification or observation."""
    from pdos_next.errors import DomainError

    raise DomainError(
        "INTEGRATION_REQUIRED", "CAPA专业适用、独立复核与实际观察期权威接口尚未接通。", 503
    )
