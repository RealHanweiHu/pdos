"""A named human's internal followup over one immutable native G0 risk."""

from typing import Literal

from pydantic import Field

from pdos_next.domain.projects.work.schemas import (
    ConfirmedPayload,
    G0OpenItemRef,
    SourceRef,
    Text,
    VersionRef,
)

from .models import OPERATION


class RiskFollowupPayload(ConfirmedPayload):
    risk: G0OpenItemRef
    current: VersionRef | None
    action: Literal["close", "reopen"]
    summary: Text
    sources: tuple[SourceRef, ...] = Field(min_length=1)


PAYLOADS = {OPERATION: RiskFollowupPayload}
