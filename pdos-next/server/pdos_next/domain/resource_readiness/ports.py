"""All operations run on the caller's Session/UOW. No connection or commit here."""

from typing import Literal, Protocol
from uuid import UUID

from pdos_next.schemas.resource_readiness.contracts import (
    Occupancy,
    ReadinessReport,
    Reservation,
    ReservationPreview,
    ReservationRequest,
    ResourceContext,
    ResourceSnapshot,
    StagedReservation,
)
from pdos_next.schemas.verification.contracts import SourceRef


class ResourceFactsPort(Protocol):
    def context(self, owner_run_id: UUID, purpose: str, operation_id: str) -> ResourceContext:
        """Bind scope/executor/current ACL, qualification and policy from locked host run.

        Reauthorize every replay; policy_registered is false for unregistered actions.
        No capability, tenant/project or condition allowance from model fields.
        """
        ...

    def resources(
        self, context: ResourceContext, resource_ids: tuple[UUID, ...]
    ) -> tuple[ResourceSnapshot, ...]:
        """Current fixed resource identity, applicability and named qualification facts.

        Host verifies physical-resource global identity, current revision, tenant/product/
        project applicability (shared resource mappings may span projects), and facts.
        Current facts must apply to EXACT resource revision AND both fixed actual
        configurations of this run; required_resources/units/purpose must come from
        its approved method, not arbitrary request fields. No future planned Build.
        Snapshot.scope is the current authorized applicability projection, not the
        physical resource's owner: occupancy identity remains tenant-global.
        May return fewer resources for absent records; no substitute version.
        """
        ...

    def source_status(
        self, context: ResourceContext, source: SourceRef
    ) -> Literal["current", "missing", "withdrawn", "drifted"]:
        """Current ACL and original validity; raise on denied access. Never LLM/network."""
        ...


class ReservationStorePort(Protocol):
    def lock(self, context: ResourceContext, request: ReservationRequest) -> None:
        """In caller UOW: lock semantic run-intent, then resource occupancy sentinel rows.

        Acquire resource IDs by UUID.bytes, including empty occupancy resources: no
        phantom double-booking. Resource revision, acceptance/calibration/qualification,
        maintenance and calendar updates MUST use these same sentinel locks; protect
        authority/source revocation epochs with the host's existing locks or CAS.
        Host takes parent Request/Run before these locks, then
        SampleUnit IDs by UUID.bytes using ONE ordering across all reservation users.
        If samples must lock first in existing adapters, change host universal ordering;
        never nest this protocol with an inverse lock order. No independent transaction.
        """
        ...

    def find(self, context: ResourceContext, request: ReservationRequest) -> Reservation | None:
        """Scoped stable run intent, key and ID uniqueness; mismatched aliases conflict.

        One resource bundle per owner run in v1. Different command/key/ID must not bypass
        that identity. Raise if key or ID is attached to a different owner/scope.
        Historical released/cancelled records remain and cannot silently reactivate.
        """
        ...

    def occupancies(
        self, context: ResourceContext, resource_ids: tuple[UUID, ...]
    ) -> tuple[Occupancy, ...]:
        """All formal occupants, including other projects AND staged writes in this UOW.

        No tentative/cancelled/released occupancy. Return sanitized capacity only;
        never omit other-project occupancy due to the caller's record-view ACL.
        """
        ...

    def confirm(self, context: ResourceContext, preview: ReservationPreview) -> None:
        """Consume host's common T1 proof/current named T2 evidence exactly once.

        Host binds operation, stable intent, actor, scope, payload, complete fixed
        readset, expected version, digest/expiry and current authorization. This is
        not a new confirmation mechanism. Internal verification.reserve may reuse
        its enclosing RunStart proof, never require a second user confirmation.
        When the enclosing handler already consumed the proof in this same UOW,
        assert that binding (including this resource readset), do not consume again.
        This protocol itself does not mint tokens or establish another command ledger.
        Reject AI T2. Must rollback together with reservation/sample/receipt/outbox.
        """
        ...

    def stage(
        self,
        context: ResourceContext,
        reservation: Reservation,
        expected_revision: int,
        expected_occupancy_revisions: tuple[tuple[UUID, int], ...],
    ) -> None:
        """Insert-only at 0 / CAS otherwise; CAS+bump resource occupancy versions.

        Revalidate/lock all fixed resource, calendar, qualification, source and
        context.facts_revision epochs at persistence; occupancy CAS alone is insufficient.
        Compare expected revisions for every physical resource even when its evidence
        is missing. Referenced resource identities/sentinels are never physically deleted.
        Append immutable history/fixed facts with host receipt/audit/outbox in the
        caller Session; flush is allowed, commit/rollback is caller-owned. Preserve
        semantic-intent+ID uniqueness. Raise on CAS conflict, no partial success.
        The caller must abort the whole UOW on ANY subprotocol/sample/Mutation failure.
        """
        ...


class ResourceReservationPort(Protocol):
    """Subprotocol consumed by host SampleAvailabilityPort.reserve; zero sample ownership."""

    def stage_formal(
        self, request: ReservationRequest, preview: ReservationPreview, expected_revision: int = 0
    ) -> StagedReservation: ...

    def recheck_execution(self, request: ReservationRequest) -> ReadinessReport: ...
