"""T2 ``evidence.source.withdraw`` payload (P100 第 1–2 项, D310); no service imports."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from pdos_next.core.schema_base import StrictModel

OPERATION = "evidence.source.withdraw"
EVENT = "source.withdrawn"


class SourceWithdrawPayload(StrictModel):
    source_id: UUID
    kind: Literal["original", "artifact"]
    expected_revision: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=3, max_length=2000)
    approval_token: str | None = Field(default=None, min_length=20, max_length=128)


PAYLOADS = {OPERATION: SourceWithdrawPayload}
