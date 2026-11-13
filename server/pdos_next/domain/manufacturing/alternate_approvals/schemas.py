"""Closed T2 alternate-material approval declarations (P96 第 5–7 项, D308).

An engineering-role named person approves one alternate for one BOM line of one
fixed Build (its BOM and configuration digests), citing a current test run with
a named review. Validity and revocation are versions; the BOM never changes.
"""

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from pdos_next.domain.projects.work.schemas import DTO, Text, VersionRef

OPERATION = "supply.alternate.approve"
EVENT = "alternate.approved"
SUBJECT = "alternate_approval"
ACTIONS = ("approve", "revoke")
STATES = ("approved", "revoked")
Key = Annotated[str, Field(min_length=1, max_length=200)]


class Scope(DTO):
    build_id: UUID
    expected_build_revision: int = Field(ge=1, strict=True)
    item_id: Key
    alternate_material_id: Key
    alternate_unit: Key
    alternate_quantity_per_target: Decimal = Field(gt=0, max_digits=24, decimal_places=12)


class Payload(DTO):
    approval: VersionRef | None = None
    action: Literal["approve", "revoke"]
    scope: Scope | None = None
    evidence_run: VersionRef | None = None
    valid_until: AwareDatetime | None = None
    reason: Text
    approval_token: str | None = Field(default=None, min_length=20, max_length=128)

    @model_validator(mode="after")
    def shape(self):
        if (self.approval is None) != (self.scope is not None):
            raise ValueError("首次批准给出 Build、BOM 行与替代料；之后固定原批准版本")
        if self.action == "approve" and self.evidence_run is None:
            raise ValueError("批准须引用替代料的测试运行（带当前具名复核）")
        if self.action == "revoke" and (
            self.approval is None or self.evidence_run or self.valid_until
        ):
            raise ValueError("撤销只针对已有批准，不带新证据或有效期")
        return self


PAYLOADS = {OPERATION: Payload}
