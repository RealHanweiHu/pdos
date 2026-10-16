"""Platform metadata is tenant-shared; applicability belongs to a scoped link."""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from pdos_next.schema_base import StrictModel


class NewPlatform(StrictModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""


class PlatformLinkInput(StrictModel):
    product_id: UUID
    variant_id: UUID | None = None
    platform_id: UUID | None = None
    new_platform: NewPlatform | None = None
    action: Literal["attach", "detach"]
    compatibility: str | None = None
    platform_version: str | None = None
    reason: str = Field(min_length=1)
    expected_link_version: int = Field(ge=0)
    confirmation_token: str | None = None
    prepared_by_run_id: UUID | None = None
    candidate_digest: str | None = None

    @model_validator(mode="after")
    def target(self):
        if (self.platform_id is None) == (self.new_platform is None):
            raise ValueError("Select an existing platform or provide a new platform")
        if self.new_platform and (self.action != "attach" or self.expected_link_version != 0):
            raise ValueError("A new platform must start with an attachment at version zero")
        if (self.prepared_by_run_id is None) != (self.candidate_digest is None):
            raise ValueError("Prepared candidate identity and digest belong together")
        return self


class PlatformReadInput(StrictModel):
    platform_id: UUID | None = None
    product_id: UUID | None = None
    variant_id: UUID | None = None
    category_id: UUID | None = None
    code: str | None = None
    name_query: str | None = None
    include_history: bool = Field(default=False, strict=True)
    cursor: UUID | None = None
    page_size: int = Field(default=50, ge=1, le=200)

    @model_validator(mode="after")
    def variant_scope(self):
        if self.variant_id and self.product_id is None:
            raise ValueError("Select a product for the variant")
        return self
