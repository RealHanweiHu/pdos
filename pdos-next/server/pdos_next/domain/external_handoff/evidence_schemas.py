"""Registered handoff contract material, not an issuer or connector grant."""

from typing import Literal
from uuid import UUID

from pydantic import model_validator

from pdos_next.domain.release.schemas import (
    DTO,
    ReleaseScope,
    SubjectConfiguration,
    Text,
    VersionRef,
)
from pdos_next.schemas.verification.contracts import Scope

from .schemas import Destination, ManifestFile, MappingRef, NumberMapping


class HandoffContract(DTO):
    schema_version: Literal["pdos-external-handoff-contract-v1"]
    scope: Scope
    category_id: UUID
    subject_config: SubjectConfiguration
    purpose: Text
    destination: Destination
    release_scope: ReleaseScope
    required_mapping_refs: tuple[MappingRef, ...]
    required_manifest_refs: tuple[VersionRef, ...]
    mappings: tuple[NumberMapping, ...]
    files: tuple[ManifestFile, ...]

    @model_validator(mode="after")
    def fixed(self):
        if self.schema_version != "pdos-external-handoff-contract-v1":
            raise ValueError("Unsupported handoff contract schema")
        if self.purpose != self.purpose.strip():
            raise ValueError("Handoff contract purpose must remain explicit")
        groups = (
            self.required_mapping_refs,
            self.required_manifest_refs,
            tuple(value.ref for value in self.mappings),
            tuple(value.artifact for value in self.files),
            tuple(value.logical_name for value in self.files),
        )
        if any(len(set(group)) != len(group) for group in groups):
            raise ValueError("Contract requirements and fixed objects cannot repeat")
        return self
