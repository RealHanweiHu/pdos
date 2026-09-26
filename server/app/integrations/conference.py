"""Conference provider boundary for auto-created meetings (vNext V2-2, D35).

Creating the conference is the one part of scheduling that depends on a third
party, so it is isolated behind this protocol. Two consequences follow:

* **A provider failure never loses the meeting.** The meeting is created in
  PDOS first and the conference is attached afterwards; if the provider is
  down, the meeting still exists with no link and someone can create one by
  hand. Booking a room is not worth losing the agenda over.
* **Real providers need credentials that are granted separately.** The DingTalk
  and Tencent adapters are declared here but refuse to act until a tenant
  binding exists, so nothing can silently call out with half a configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


class ConferenceProviderError(RuntimeError):
    """Raised when the provider could not service the request."""


class ConferenceNotConfiguredError(ConferenceProviderError):
    """Raised when a provider is asked to act without tenant credentials."""


@dataclass(frozen=True)
class ConferenceBooking:
    provider: str
    external_meeting_id: str
    join_url: str


class ConferenceProvider(Protocol):
    name: str

    def create(
        self,
        *,
        tenant_id: UUID,
        subject: str,
        start_at: datetime,
        end_at: datetime,
        idempotency_key: str,
    ) -> ConferenceBooking: ...

    def reschedule(
        self,
        *,
        tenant_id: UUID,
        external_meeting_id: str,
        start_at: datetime,
        end_at: datetime,
    ) -> ConferenceBooking: ...

    def cancel(self, *, tenant_id: UUID, external_meeting_id: str) -> None: ...


class UnconfiguredConferenceProvider:
    """Stands in for a real provider until its tenant credentials are granted.

    It fails loudly rather than returning a fake link: a meeting invitation
    pointing nowhere is worse than an obviously missing one.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    def create(
        self,
        *,
        tenant_id: UUID,
        subject: str,
        start_at: datetime,
        end_at: datetime,
        idempotency_key: str,
    ) -> ConferenceBooking:
        raise ConferenceNotConfiguredError(
            f"{self.name} conference credentials are not configured for this tenant"
        )

    def reschedule(
        self,
        *,
        tenant_id: UUID,
        external_meeting_id: str,
        start_at: datetime,
        end_at: datetime,
    ) -> ConferenceBooking:
        raise ConferenceNotConfiguredError(
            f"{self.name} conference credentials are not configured for this tenant"
        )

    def cancel(self, *, tenant_id: UUID, external_meeting_id: str) -> None:
        raise ConferenceNotConfiguredError(
            f"{self.name} conference credentials are not configured for this tenant"
        )


class InMemoryConferenceProvider:
    """Deterministic provider for tests and local development.

    Keyed by idempotency key so a repeated create returns the same booking,
    which is what a real provider's idempotent create must also do.
    """

    def __init__(self, *, name: str = "dingtalk") -> None:
        self.name = name
        self.bookings: dict[str, ConferenceBooking] = {}
        self.cancelled: list[str] = []
        self.fail_next: Exception | None = None

    def _maybe_fail(self) -> None:
        if self.fail_next is not None:
            error, self.fail_next = self.fail_next, None
            raise error

    def create(
        self,
        *,
        tenant_id: UUID,
        subject: str,
        start_at: datetime,
        end_at: datetime,
        idempotency_key: str,
    ) -> ConferenceBooking:
        self._maybe_fail()
        existing = self.bookings.get(idempotency_key)
        if existing is not None:
            return existing
        conference_id = f"conf-{len(self.bookings) + 1}"
        booking = ConferenceBooking(
            provider=self.name,
            external_meeting_id=conference_id,
            join_url=f"https://meeting.example.com/j/{conference_id}",
        )
        self.bookings[idempotency_key] = booking
        return booking

    def reschedule(
        self,
        *,
        tenant_id: UUID,
        external_meeting_id: str,
        start_at: datetime,
        end_at: datetime,
    ) -> ConferenceBooking:
        self._maybe_fail()
        for booking in self.bookings.values():
            if booking.external_meeting_id == external_meeting_id:
                return booking
        raise ConferenceProviderError(f"unknown conference {external_meeting_id}")

    def cancel(self, *, tenant_id: UUID, external_meeting_id: str) -> None:
        self._maybe_fail()
        self.cancelled.append(external_meeting_id)
