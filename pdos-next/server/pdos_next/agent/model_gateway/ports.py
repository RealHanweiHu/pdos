import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pdos_next.providers.types import ProtocolKind, ProviderUsage


class ExtractionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    goal: str = Field(min_length=3, max_length=2000)
    source: str = Field(min_length=1, max_length=200_000)
    artifact_id: UUID

    @field_validator("source", "goal")
    @classmethod
    def valid_text(cls, value):
        if "\x00" in value or not value.strip() or len(value.encode("utf-8")) > 200_000:
            raise ValueError("Nonempty bounded UTF-8 text required")
        return value

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()


@dataclass(frozen=True)
class CallPermit:
    """Issued only by a server callback; never accepted from model or request payload."""

    call_id: UUID
    request_digest: str
    route_digest: str
    writer_id: UUID
    provider_version: str
    expires_at: datetime
    purpose: Literal["source_claim"] = "source_claim"
    egress_allowed: bool = False
    protocol: ProtocolKind | None = None


@dataclass(frozen=True)
class Reservation:
    call_id: UUID
    token: str


class BudgetPort(Protocol):
    """reserve must durably reject spent/unknown call_ids across processes and restarts.

    Settle or unknown must persist before this call can be considered finished. A
    caller must reconcile an unknown attempt rather than creating another call_id
    for the same intended model step. No in-memory implementation grants eligibility.
    """

    def reserve(
        self, permit: CallPermit, *, input_bytes: int, max_output_tokens: int
    ) -> Reservation: ...

    def settle(
        self,
        reservation: Reservation,
        *,
        usage: ProviderUsage,
        outcome: Literal["completed", "rejected"],
        error_code: str | None = None,
        request_id: str | None = None,
    ) -> None: ...

    def unknown(
        self, reservation: Reservation, *, error_code: str, request_id: str | None = None
    ) -> None: ...
