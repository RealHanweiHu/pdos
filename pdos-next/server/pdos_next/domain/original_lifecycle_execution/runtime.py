"""Explicit server injection. No default inventory, reference coverage or policy."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pdos_next.object_storage.types import ObjectRef
from pdos_next.original_lifecycle.ports import ClockPort, ReferenceGuardPort
from pdos_next.original_lifecycle.types import (
    CurrentAuthorization,
    LifecycleAction,
    LifecycleIntent,
    OriginalState,
    RetentionPolicy,
)


@dataclass(frozen=True, slots=True)
class BoundFacts:
    owner_id: UUID
    original: OriginalState

    def __post_init__(self):
        if not isinstance(self.owner_id, UUID) or not isinstance(self.original, OriginalState):
            raise ValueError("Authoritative facts require typed owner and original")


@dataclass(frozen=True, slots=True)
class LifecycleRuntime:
    policy: RetentionPolicy
    resolve_reference: Callable[[object, object, UUID, UUID], ObjectRef]
    read_facts: Callable[[object, object, UUID, ObjectRef, OriginalState | None], BoundFacts]
    references_factory: Callable[[object, object, UUID], ReferenceGuardPort]
    clock: ClockPort | None = None
    transition_hook: (
        Callable[[object, object, LifecycleIntent, LifecycleIntent, OriginalState], None] | None
    ) = None
    service_authorize: (
        Callable[
            [object, object, UUID, ObjectRef, LifecycleAction, datetime, LifecycleIntent],
            CurrentAuthorization,
        ]
        | None
    ) = None

    def __post_init__(self):
        if not isinstance(self.policy, RetentionPolicy):
            raise ValueError("An explicit typed server retention policy is required")
        for callback in (self.resolve_reference, self.read_facts, self.references_factory):
            if not callable(callback):
                raise ValueError("Authoritative lifecycle ports must be explicitly configured")
        for callback in (self.transition_hook, self.service_authorize):
            if callback is not None and not callable(callback):
                raise ValueError("Invalid lifecycle callback")
