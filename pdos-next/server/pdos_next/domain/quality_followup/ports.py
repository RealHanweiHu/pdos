"""Host-only transaction callbacks; none can commit, confirm twice or create a Run."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pdos_next.domain.quality_issues.ports import Mutation

from .schemas import CompletionAssessment


class AppendIssue(Protocol):
    def __call__(
        self,
        s,
        ctx,
        product,
        before_row,
        mutation: Mutation,
        *,
        operation: str,
        authority: dict,
        policy_snapshot: dict,
        required_source_read_set: list,
        source_basis: dict,
        input_snapshot: dict,
        intent_digest: str,
        expected_issue_revision: int,
    ) -> object:
        """Append the SAME Issue and CAS Current in this Session, without a Receipt/commit."""
        ...


class ConsumedProof(Protocol):
    def __call__(self, s, ctx, command, payload, *, tier: str) -> UUID:
        """Return actual common consumed proof ID, binding actor/tier/material/readset/expiry."""
        ...


class AssessActionCompletion(Protocol):
    def __call__(
        self,
        s,
        ctx,
        product_id,
        basis,
        action,
        completion,
        *,
        policy_snapshot: dict,
        observation,
        write: bool = False,
    ) -> CompletionAssessment:
        """Recheck controlled action classification and genuine owner implementation.

        Investigation needs host policy evidence. Formal changes need actual
        approved implementation proofs. Callback must not commit/confirm/write.
        """
        ...


@dataclass(frozen=True)
class Runtime:
    append_issue: AppendIssue
    consumed_proof: ConsumedProof
    assess_action_completion: AssessActionCompletion | None = None
