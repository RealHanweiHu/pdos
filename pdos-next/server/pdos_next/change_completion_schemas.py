"""Native development adoption and named verification inputs, without fact claims."""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from pdos_next.change_command_schemas import Target
from pdos_next.schemas.change_control.contracts import Ref
from pdos_next.schemas.verification.contracts import DTO, Key, SourceRef, Text


class FixedNativeRef(DTO):
    id: UUID
    revision: int = Field(strict=True, ge=1)


class RunScopeMapping(DTO):
    item_id: UUID
    run: Ref
    sample_id: UUID
    test_item_id: Key
    method: SourceRef
    requirement_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    rationale: Text

    @model_validator(mode="after")
    def exact_run(self):
        if self.run.kind != "test_run" or self.run.key is not None:
            raise ValueError("Select an exact actual Run")
        return self


class EffectivityPayload(Target):
    item_id: UUID
    lot: FixedNativeRef
    sample_refs: tuple[Ref, ...] = Field(min_length=1)
    confirmation_token: str | None = Field(default=None, min_length=16, max_length=512)

    @model_validator(mode="after")
    def exact_samples(self):
        if any(ref.kind != "sample" or ref.key is not None for ref in self.sample_refs):
            raise ValueError("Select actual sample references")
        if len(set(self.sample_refs)) != len(self.sample_refs):
            raise ValueError("Samples cannot repeat")
        return self


class VerificationPayload(Target):
    mappings: tuple[RunScopeMapping, ...] = Field(min_length=1)
    text: Text
    approval_token: str | None = Field(default=None, min_length=16, max_length=512)


class ClosePayload(Target):
    text: Text
    approval_token: str | None = Field(default=None, min_length=16, max_length=512)


class CompletionMaterial(DTO):
    operation: Literal["change.effectivity.record", "change.verification.record", "change.close"]
    payload: EffectivityPayload | VerificationPayload | ClosePayload

    @model_validator(mode="after")
    def exact_operation(self):
        expected = {
            "change.effectivity.record": EffectivityPayload,
            "change.verification.record": VerificationPayload,
            "change.close": ClosePayload,
        }[self.operation]
        if type(self.payload) is not expected:
            raise ValueError("The input must match the selected operation")
        if getattr(self.payload, "approval_token", None) or getattr(
            self.payload, "confirmation_token", None
        ):
            raise ValueError("Prepare material before requesting a named proof")
        return self
