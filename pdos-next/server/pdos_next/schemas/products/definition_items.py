"""Definition specification patch shapes; authority remains with the domain owner."""

from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from pdos_next.domain.preproject.schemas import PreparedContent, Reference, SpecItem
from pdos_next.schema_base import StrictModel


class DefinitionItemOp(StrictModel):
    op: Literal["upsert", "remove"] = "upsert"
    item_id: UUID | None = None
    base_version: int | None = Field(default=None, gt=0, strict=True)
    content: SpecItem | None = None
    source_refs: list[Reference] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_operation(self) -> Self:
        if (self.item_id is None) != (self.base_version is None):
            raise ValueError("Existing item identity and base version must be supplied together")
        if self.op == "remove":
            if self.item_id is None:
                raise ValueError("Removal requires an existing item and its base version")
            if self.model_fields_set & {"content", "source_refs"}:
                raise ValueError("Removal must not contain content or source references")
        else:
            if self.content is None:
                raise ValueError("Upsert requires a complete specification")
            if self.content.item_status == "confirmed" and not self.source_refs:
                raise ValueError("Confirmed specifications need a source")
        return self


class DefinitionItemPatch(PreparedContent):
    definition_id: UUID
    ops: list[DefinitionItemOp] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_items_and_keys(self) -> Self:
        identities = [op.item_id for op in self.ops if op.item_id is not None]
        if len(set(identities)) != len(identities):
            raise ValueError("A patch cannot modify the same item twice")
        keys = [op.content.key for op in self.ops if op.content is not None]
        if len(set(keys)) != len(keys):
            raise ValueError("Specification keys cannot repeat within a patch")
        return self
