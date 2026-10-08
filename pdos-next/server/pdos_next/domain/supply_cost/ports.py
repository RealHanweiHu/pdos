"""Host-owned ports. Every method participates in the passed common unit of work.

No port may commit, grant rights from a payload, query a different tenant, or
declare an import fresh without verifying its original evidence. These are
integration contracts, not implementations of mainline authentication/SQL.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pdos_next.engines.supply_cost.dto import AlternateQualification
from pdos_next.schemas.supply_cost.dto import (
    BoundDemand,
    CommandBinding,
    CommandReceipt,
    Confirmation,
    CostInputs,
    Intent,
    PreparedPlan,
    Preview,
    Scope,
    SupplySnapshot,
)


class BuildDemandPort(Protocol):
    def load(
        self, uow: object, scope: Scope, build_id: str, expected_revision: int, as_of: datetime
    ) -> BoundDemand:
        """Return Build's SAME fixed basis and full authoritative expansion.

        Verify project/audience, both configurations, source read set and Build
        revision. Transport complete original evidence refs and exact fixed
        manufacturing operation keys for same-transaction rechecks. Do not
        reconstruct a basis from a different configuration view.
        Missing/unfrozen interface raises PORT_UNCONNECTED, not an empty demand.
        """
        ...


class SupplySnapshotPort(Protocol):
    def capture(
        self, uow: object, scope: Scope, capture_id: str, binding: BoundDemand, as_of: datetime
    ) -> SupplySnapshot:
        """Resolve a server-authorized draft/import; return immutable proposed snapshot.

        Bind original source, real audience and canonical current pool balances.
        Stage no write here. Commitments, transit and incremental receipts stay
        evidence, not additive stock. Quality partitioning must be authoritative.
        """
        ...

    def current(self, uow: object, scope: Scope, build_id: str) -> SupplySnapshot | None: ...

    def get(
        self, uow: object, scope: Scope, snapshot_id: str, expected_revision: int
    ) -> SupplySnapshot: ...

    def verified_alternates(
        self, uow: object, scope: Scope, binding: BoundDemand, as_of: datetime
    ) -> tuple[AlternateQualification, ...]:
        """Authenticate issuer/evidence, exact applicability and current qualification.

        No qualification objects or externally_verified flags are accepted from
        the command/model. Empty means no verified alternatives, not approval.
        """
        ...

    def history(self, uow: object, scope: Scope, build_id: str) -> tuple[SupplySnapshot, ...]:
        """Authorize every immutable historical record; no current-only replacement."""
        ...


class CostInputPort(Protocol):
    def get(
        self, uow: object, scope: Scope, input_id: str, expected_revision: int, binding: BoundDemand
    ) -> CostInputs:
        """Verify fixed quote objects/tiers, manufacturing op mapping, currencies/rates.

        Process quantities per good product, units/losses/prices require evidence;
        cycle time or a missing cost is never converted to an invented fact/zero.
        """
        ...


class CommandPort(Protocol):
    def bind(
        self, uow: object, context: object, intent: Intent, confirmation: Confirmation | None
    ) -> CommandBinding:
        """Bind authenticated session/Run tenant/project/audience and fixed server time.

        On apply, recover as_of from the stored preview, while current_time is
        real server time. Never deserialize authority from intent.payload.
        """
        ...

    def authorize(
        self, uow: object, context: object, binding: CommandBinding, intent: Intent, *, apply: bool
    ) -> None:
        """Enforce current user/Run rights, qualification, cancellation and real confirmer.

        This package exposes only T1 candidates. It never offers T2 release,
        supplier-approved qualification, ERP stock transactions or finance approval.
        """
        ...

    def replay(
        self, uow: object, binding: CommandBinding, intent: Intent, confirmation: Confirmation
    ) -> CommandReceipt | None:
        """Lock/check both command idempotency and semantic intent before fresh reads.

        Reject key reuse with different payload; authorize historical receipt
        scope and token/plan binding. A completed original may be returned despite
        later source changes. No new effect, confirmation consumption or event.
        """
        ...

    def preview(
        self, uow: object, binding: CommandBinding, intent: Intent, plan: PreparedPlan
    ) -> Preview:
        """Persist real substantive review, canonical plan hash and expiry."""
        ...

    def stage_once(
        self,
        uow: object,
        context: object,
        binding: CommandBinding,
        intent: Intent,
        confirmation: Confirmation,
        plan: PreparedPlan,
    ) -> CommandReceipt:
        """Under common transaction/locks, recheck source revisions+state, permissions,
        cancel epoch, current snapshot pointer and preview expiry/hash/one-use;
        then atomically consume confirmation and stage immutable fact/projection,
        ActionReceipt, Audit and Outbox. Both duplicate layers return one effect.
        Rollback restores everything. This method MUST NOT commit or start its
        own transaction; the host owns commit and any SQL/model registration.
        """
        ...


@dataclass(frozen=True)
class Ports:
    command: CommandPort
    demand: BuildDemandPort | None = None
    supply: SupplySnapshotPort | None = None
    cost: CostInputPort | None = None
