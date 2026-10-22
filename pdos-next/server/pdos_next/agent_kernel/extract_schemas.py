"""Closed extraction data shapes; selectors and citations grant no authority."""

from copy import deepcopy
from typing import Annotated, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, create_model, field_validator, model_validator

from pdos_next.domain.preproject.schemas import Reference, SpecItem
from pdos_next.schema_base import StrictModel

NonBlank = Annotated[str, Field(min_length=1)]


class RowSchemaDeclaration(StrictModel):
    """An installed skill's registered data contract, never a tool definition."""

    kind: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    version: str = Field(min_length=1)


class ParameterFocus(StrictModel):
    parameter: Reference

    @model_validator(mode="after")
    def parameter_only(self):
        ref = self.parameter
        if ref.type != "parameter" or any(
            value is not None for value in (ref.line, ref.quote, ref.statement)
        ):
            raise ValueError("Parameter focus requires only an actual parameter identity/version")
        return self


class ExtractInput(StrictModel):
    proposal_id: UUID | None = None
    # None means the actual mounted set of an actual bound Proposal; [] never
    # silently becomes 'all'. Neither form grants source access on its own.
    artifact_version_ids: list[UUID] | None = Field(default=None, min_length=1)
    row_schema: RowSchemaDeclaration
    focus: NonBlank | ParameterFocus | None = None

    @model_validator(mode="after")
    def explicit_category_sources(self):
        if self.proposal_id is None and not self.artifact_version_ids:
            raise ValueError("Category extraction requires an explicit artifact version list")
        ids = self.artifact_version_ids
        if ids is not None and len(ids) != len(set(ids)):
            raise ValueError("Artifact version selectors must be unique")
        return self


class ArtifactReadInput(StrictModel):
    artifact_version_id: UUID
    locator: NonBlank | None = None
    cursor: int = Field(default=0, ge=0, strict=True)
    page_size: int = Field(default=100, ge=1, le=200, strict=True)


# Reuse every actual RFQ content field and its Pydantic field constraints. The
# projection omits authority, rather than hiding accepted authority on export.
_CODE_OWNED_SPEC_FIELDS = frozenset({"nature", "item_status", "owner_id"})


def _valid_spec_content(self):
    content = self.model_dump()
    SpecItem.model_validate(
        {**content, "nature": "extracted", "item_status": "ai_draft", "owner_id": None}
    )
    return self


RFQSpecDraft = create_model(
    "RFQSpecDraft",
    __base__=StrictModel,
    __validators__={"consistent_spec": model_validator(mode="after")(_valid_spec_content)},
    **{
        name: (field.annotation, deepcopy(field))
        for name, field in SpecItem.model_fields.items()
        if name not in _CODE_OWNED_SPEC_FIELDS
    },
)


class CitationDraft(StrictModel):
    # Whitespace in a literal quotation is evidence, not formatting to normalize.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    artifact_version_id: UUID
    locator: NonBlank
    quote: NonBlank

    @field_validator("locator", "quote")
    @classmethod
    def nonblank_literal(cls, value):
        if not value.strip():
            raise ValueError("A citation needs a nonblank actual locator and literal quotation")
        return value


class RFQDraftRow(CitationDraft):
    kind: Literal["spec", "functional", "compliance", "packaging_labeling", "commercial", "other"]
    statement: NonBlank
    spec: RFQSpecDraft | None = None
    missing: list[NonBlank] = Field(default_factory=list)

    @model_validator(mode="after")
    def correct_row_kind(self):
        if (self.kind == "spec") != (self.spec is not None):
            raise ValueError("Exactly specification requirements carry structured SpecItem content")
        return self


class VoiceDraftRow(CitationDraft):
    """A second registered example; category imports are not limited to this kind."""

    item_label: str | None = None
    model: str | None = None
    channel: str | None = None
    region: str | None = None
    date: str | None = None
    rating: str | None = None
    language: str | None = None


class RowSchemaRegistry:
    """Host-installed data DTOs only; requests cannot register tools or schemas.

    Further imported-material kinds are installed here by server code after a
    real skill declaration is available. Registration itself grants no scope,
    tool, write tier or provider permission. The host must also compare this
    resolved schema with its actually loaded skill and frozen manifest.
    """

    def __init__(self):
        self._rows = {}

    def register(self, declaration: RowSchemaDeclaration, row_model: type[CitationDraft]):
        if not isinstance(row_model, type) or not issubclass(row_model, CitationDraft):
            raise ValueError("A registered extraction row must preserve the citation contract")
        if row_model.model_config.get("extra") != "forbid" or any(
            row_model.model_fields[name].annotation != field.annotation
            for name, field in CitationDraft.model_fields.items()
        ):
            raise ValueError("Registered rows must keep closed fields and typed citations")
        forbidden = {
            "status",
            "error",
            "coverage",
            "coverage_scope",
            "counts",
            "count",
            "sample_size",
            "row_id",
            "job_id",
            "source_refs",
            "content_hash",
            "next_cursor",
            "actor_id",
            "tenant_id",
            "category_id",
            "product_id",
            "owner_id",
            "run_id",
        }
        if forbidden.intersection(row_model.model_fields):
            raise ValueError("Extraction authority fields belong to host verification")
        key = (declaration.kind, declaration.version)
        if key in self._rows:
            raise ValueError("A registered row contract cannot be replaced in place")
        self._rows[key] = row_model

    def row_model(self, declaration: RowSchemaDeclaration):
        row = self._rows.get((declaration.kind, declaration.version))
        if row is None:
            raise ValueError("The requested data contract is not registered")
        return row

    def rows_model(self, declaration: RowSchemaDeclaration):
        row = self._rows.get((declaration.kind, declaration.version))
        if row is None:
            raise ValueError("The requested data contract is not registered")
        return create_model(
            f"{row.__name__}Rows",
            __base__=StrictModel,
            rows=(list[row], Field(default_factory=list)),
        )


def draft_registry():
    registry = RowSchemaRegistry()
    registry.register(RowSchemaDeclaration(kind="rfq_requirement", version="1"), RFQDraftRow)
    registry.register(RowSchemaDeclaration(kind="user_voice", version="1"), VoiceDraftRow)
    return registry


SCHEMAS = {"evidence.extract": ExtractInput, "evidence.artifact.read": ArtifactReadInput}
