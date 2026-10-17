"""Fixed original declarations; no DTO proves authority or completeness."""

from typing import Literal, get_args
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from pdos_next.change_controlled_schemas import Exact, UnitBinding
from pdos_next.schemas.change_control.contracts import Facet, Kind, Ref
from pdos_next.schemas.verification.contracts import Scope, SourceRef, Text

OPERATION = "change.coverage.import"
EVENT = "change.coverage_imported"
FAMILY = "change_coverage_fact"
FACETS = get_args(Facet)


class FacetClosure(Exact):
    facet: Facet
    # Explicit fixed enumeration from the approved whole original, never SELECT=0.
    nodes: tuple[Ref, ...] = Field(min_length=1)
    statement: Text


class FacetState(Exact):
    node: Ref
    facet: Facet
    status: Literal["complete", "unknown", "not_applicable"]
    reason: Text


class PathDeclaration(Exact):
    node: Ref
    targets: tuple[Kind, ...] = Field(min_length=1)
    status: Literal["applicable", "not_applicable", "unknown"]
    reason: Text


class CoverageMaterial(Exact):
    schema_version: Literal[
        "pdos-controlled-change-coverage-v1", "pdos-controlled-change-coverage-v2"
    ]
    scope: Scope
    purpose: Text
    change_id: UUID
    origin_version_id: UUID
    origin_revision: int = Field(strict=True, ge=1)
    owner_id: UUID
    visibility: Literal["private", "category", "audience"]
    publisher_id: UUID
    roots: tuple[Ref, ...] = Field(min_length=1)
    nodes: tuple[Ref, ...] = Field(min_length=1)
    units: tuple[UnitBinding, ...] = Field(min_length=1)
    facets: tuple[FacetClosure, ...] = Field(min_length=8, max_length=8)
    facet_states: tuple[FacetState, ...] = Field(default=(), exclude_if=lambda value: not value)
    paths: tuple[PathDeclaration, ...] = Field(default=(), exclude_if=lambda value: not value)
    closure_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    nature: Literal["real", "synthetic"]

    @model_validator(mode="before")
    @classmethod
    def legacy_shape(cls, value):
        if isinstance(value, dict) and value.get("schema_version") == (
            "pdos-controlled-change-coverage-v1"
        ):
            if "facet_states" in value or "paths" in value:
                raise ValueError("Version 1 originals cannot declare new applicability fields")
        return value

    @model_validator(mode="after")
    def closed(self):
        nodes = {r.identity for r in self.nodes}
        if len(nodes) != len(self.nodes):
            raise ValueError("Fixed nodes must be unique")
        roots = {r.identity for r in self.roots}
        if len(roots) != len(self.roots) or not roots <= nodes:
            raise ValueError("Fixed roots must belong to the declared closure")
        if {v.facet for v in self.facets} != set(FACETS):
            raise ValueError("All eight canonical facets need their own fixed original declaration")
        for facet in self.facets:
            values = [v.identity for v in facet.nodes]
            if len(values) != len(set(values)) or set(values) != nodes:
                raise ValueError("Every facet must explicitly enumerate the exact bounded nodes")
        states = {(v.node.identity, v.facet) for v in self.facet_states}
        if len(states) != len(self.facet_states) or any(
            v.node.identity not in nodes for v in self.facet_states
        ):
            raise ValueError("Facet states must bind unique fixed nodes and facets")
        from pdos_next.domain.change_control.rules import NEXT

        paths = {(v.node.identity, frozenset(v.targets)) for v in self.paths}
        if len(paths) != len(self.paths) or any(
            v.node.identity not in nodes
            or len(set(v.targets)) != len(v.targets)
            or set(v.targets) != NEXT.get(v.node.kind)
            for v in self.paths
        ):
            raise ValueError("Path declarations must name exact fixed continuation groups")
        units = [v.unit for v in self.units]
        if len(set(units)) != len(units) or any(
            v.object_identity not in nodes or v.unit != f"object:{v.object_identity}"
            for v in self.units
        ):
            raise ValueError(
                "Only exact object units are integrated; batch/serial need real owners"
            )
        if {v.object_identity for v in self.units} != nodes or len(self.units) != len(nodes):
            raise ValueError("Every declared node needs its own exact object unit")
        if self.valid_until <= self.valid_from:
            raise ValueError("Original validity must be an actual nonempty interval")
        return self


class OriginalApproval(Exact):
    """Startup-only host pin, not an import request field or model instruction."""

    source: SourceRef
    material_sha256: str = Field(pattern="^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def native(self):
        if self.source.kind != "artifact":
            raise ValueError("Coverage requires an actual fixed original artifact line")
        return self


class CoverageImport(Exact):
    project_id: UUID
    change_id: UUID
    purpose: Text
    source: SourceRef
    expected_previous_id: UUID | None = None
    expected_previous_revision: int | None = Field(default=None, strict=True, ge=1)
    reason: Text

    @model_validator(mode="after")
    def previous(self):
        if (self.expected_previous_id is None) != (self.expected_previous_revision is None):
            raise ValueError("Previous coverage needs exact identity and revision together")
        return self
