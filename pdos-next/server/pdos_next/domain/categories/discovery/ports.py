"""Bind ports to the host transaction; never deserialize Authority from a payload."""

from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field

from pdos_next.schemas.discovery.contracts import (
    DTO,
    Citation,
    DefinitionCandidate,
    Observation,
    Research,
    Verification,
)


class Authority(DTO):
    tenant_id: UUID
    actor_id: UUID
    actor_kind: Literal["human", "ai"]
    scope_id: UUID | None
    product_id: UUID | None = None
    product_revision: int | None = Field(default=None, ge=1)
    purpose: str
    audience: Literal["private", "category", "audience"]
    authorized: bool
    # OEM completeness criteria are server policy, not model-supplied proof.
    required_categories: tuple[str, ...] = ()
    cancelled: bool = False


class SourcePort(Protocol):
    def check(self, authority: Authority, source: Citation) -> None:
        """Lock/recheck tenant/scope/ACL/audience/active version/hash and exact quote.

        For originals also verify immutable storage version/hash, safe parse state,
        and derived-line -> exact page/cell/line mapping. Hash alone is insufficient.
        Product binding must permit every research citation in the target Product.
        Raise SOURCE_UNAVAILABLE/SOURCE_STALE/FORBIDDEN_SCOPE/INTEGRITY_MISMATCH.
        """
        ...

    def verify(self, authority: Authority, observation: Observation) -> Verification:
        """Compare ALL proposed fields with the exact raw values at pinned locations.

        Cover parameter/value/type/unit/tolerance/method/conditions/applicability,
        statement and raw_text; translations and inference may remain pending.
        No assertion of verified from ID/hash/quote existence or substring numeric
        matching. No network/LLM wait in transaction. If unknown return pending.
        accepted_requirement=True requires a locked currently accepted requirement
        with matching scope/content/sources, never just a submitted UUID.
        """
        ...


class Mutation(DTO):
    research: Research
    before_revision: int
    intent_digest: str
    event: str
    replayed_content: bool = False


class ResearchPort(Protocol):
    def locked(self, authority: Authority, research_id: UUID) -> Research: ...

    def record(self, authority: Authority, mutation: Mutation) -> Research:
        """CAS/insert-only in caller Session; research+receipt+audit+outbox atomically.

        Host owns command key & stable-intent locking, replay ACL, cancellation,
        source locks and same-key/different-payload rejection. No commit. The content
        digest is supplemental dedupe, not a second receipt or confirmation store.
        """
        ...


class DefinitionPort(Protocol):
    def draft(self, authority: Authority, candidate: DefinitionCandidate) -> object:
        """Only products owns DefinitionRevision/Spec writes in SAME transaction.

        Called only by host after its existing preview/confirmation is consumed.
        Reuse canonical policy; do not consume a second confirmation in this port.
        Persist complete provenance sidecar with definition reference. All actions,
        receipt/audit/outbox and preview consumption rollback on failure.
        """
        ...


class Ports:
    def __init__(
        self,
        *,
        sources: SourcePort | None = None,
        research: ResearchPort | None = None,
        definitions: DefinitionPort | None = None,
    ):
        self.sources = sources
        self.research = research
        self.definitions = definitions
