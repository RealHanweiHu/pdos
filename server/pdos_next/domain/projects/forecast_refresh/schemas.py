"""Closed T0 forecast-refresh declaration (v1.1 §03.5, I08; P82 D181, P58, P66).

A refresh is a deterministic engine run over the current applied plan and the
actual task facts. The client names the input digest it read; the server
recomputes it, so the same input on the same calendar day is the same intent.
"""

from uuid import UUID

from pydantic import Field

from pdos_next.domain.projects.work.schemas import DTO, VersionRef

OPERATION = "work.forecast.refresh"
EVENT = "forecast.refreshed"
SUBJECT = "forecast_refresh"


class Payload(DTO):
    project_id: UUID
    plan: VersionRef
    expected_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


PAYLOADS = {OPERATION: Payload}
