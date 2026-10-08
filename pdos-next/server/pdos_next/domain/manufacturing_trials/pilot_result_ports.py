"""Future real host seams. No connection, imported material or default positive owner."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pdos_next.contracts import SourceRead
from pdos_next.errors import DomainError
from pdos_next.schemas.manufacturing_trials.contracts import PilotCreate, ResultRecord
from pdos_next.schemas.manufacturing_trials.pilot_results import FixedPilotScope, RecordedBatch


class PilotScopeOwner(Protocol):
    def fixed(self, session, ctx, pilot, *, at: datetime, write: bool) -> FixedPilotScope:
        """Actual Current/Build/Lot/Actual/Eng/Process/released Baseline/line/cohort.

        Must bind full caller scope/ACL, named professional decision, retained
        source bytes, issuer epochs, all resource/material membership and expiry.
        This DTO parse alone does not attest any of those live requirements.
        """
        ...

    def verified_result(
        self,
        session,
        ctx,
        fixed: FixedPilotScope,
        original: ResultRecord,
        *,
        at: datetime,
        write: bool,
    ) -> RecordedBatch:
        """Read exact original values/units/unique members/physical disposition.

        Count categories are actual state facts, not inferred text classifications;
        check occurrence <= fresh now, execution/window and original nature.
        """
        ...

    def sources(self, session, ctx, material) -> tuple[SourceRead, ...]:
        """Full <=20 closure, not caller-provided subset; all IO then fresh recheck."""
        ...

    def refresh(self, session, ctx, read, *, at: datetime, write: bool):
        """SameSession/UOW, current refs/caller/runtime/negative facts/expiry again."""
        ...


class PilotCommonCommandOwner(Protocol):
    def prepare(self, session, ctx, command, payload: PilotCreate | ResultRecord):
        """Actual common validation/locks/current input+semantic/readset material."""
        ...

    def consume_once(self, session, ctx, original_prepared_command, *, owner_material):
        """Real common T1 False->True + fresh first clock; never a private token engine."""
        ...

    def record_same_uow(self, session, ctx, original_command, mutation, *, consumption):
        """Actual immutable Pilot+result+CAS+Receipt/Audit/Outbox/RequestKey atom.

        No commit; final owner IO then fresh saved_at/TTL. Root registers real SQL
        reverse proof and full targets. No AI DML; role/qualification not from DTO.
        """
        ...


@dataclass(frozen=True)
class Ports:
    facts: PilotScopeOwner | None = None
    commands: PilotCommonCommandOwner | None = None

    def require(self):
        if self.facts is None or self.commands is None:
            raise DomainError("INTEGRATION_REQUIRED", "真实试产范围/共同T1端口尚未接通。", 503)
        return self
