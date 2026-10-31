"""Model selectors and finite evidence rows; authority is supplied by the host."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from pdos_next.schema_base import StrictModel

from .schemas import SearchInput


class AssistantSearchInput(SearchInput):
    limit: int = Field(default=8, ge=1, le=20, strict=True)


class ExtractInput(StrictModel):
    citation_ids: list[UUID] = Field(min_length=1, max_length=8)
    question: str = Field(default="提取与当前问题有关的依据", max_length=1000)


class PassageInput(StrictModel):
    citation_id: UUID
    cursor: int = Field(default=0, ge=0, strict=True)
    page_chars: int = Field(default=1600, ge=1, le=2000, strict=True)


class CitationsInput(StrictModel):
    reference_id: UUID | None = None
    cursor: UUID | None = None
    page_size: int = Field(default=3, ge=1, le=8, strict=True)

    @model_validator(mode="after")
    def one_selector(self):
        if self.reference_id is not None and self.cursor is not None:
            raise ValueError("引用定位与分页游标不能同时提供。")
        return self


class EvidenceDraft(StrictModel):
    citation_id: UUID
    statement: str = Field(min_length=1, max_length=1000)
    quote: str = Field(min_length=1, max_length=1000)


class MaterialsInput(StrictModel):
    artifact_ids: list[UUID] = Field(min_length=1, max_length=8)


class CompareInput(StrictModel):
    left_citation_id: UUID
    right_citation_id: UUID
    cursor: int = Field(default=0, ge=0, strict=True)
    batch_size: int = Field(default=2, ge=1, le=4, strict=True)

    @model_validator(mode="after")
    def distinct_sources(self):
        if self.left_citation_id == self.right_citation_id:
            raise ValueError("请选择两个不同的固定引用。")
        return self


class ComparisonReadInput(StrictModel):
    comparison_id: str = Field(pattern=r"^[a-f0-9]{64}$")


class DifferenceDraft(StrictModel):
    change_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    label: str = Field(min_length=1, max_length=120)
    impact_citation_id: UUID | None = None
    impact_quote: str | None = Field(default=None, min_length=1, max_length=500)
    questions: list[str] = Field(default_factory=list, max_length=4)


class TaskCellDraft(StrictModel):
    """Bounded analysis and evidence selectors; source authority is supplied by the host."""

    status: Literal["recorded", "not_recorded", "to_confirm", "unspecified"] = "to_confirm"
    citation_id: UUID | None = None
    quote: str | None = Field(default=None, min_length=1, max_length=1000)
    text: str | None = Field(default=None, min_length=1, max_length=1000)
    field_path: (
        list[
            Annotated[str, Field(min_length=1, max_length=120, strict=True)]
            | Annotated[int, Field(ge=0, le=1000, strict=True)]
        ]
        | None
    ) = Field(default=None, min_length=2, max_length=10)

    @model_validator(mode="after")
    def evidence_or_unknown(self):
        if self.status == "recorded":
            if self.citation_id is None or (self.quote is None) == (self.field_path is None):
                raise ValueError("已记录单元格须选择一个实际引用片段或结构化字段。")
        elif any(
            value is not None
            for value in (self.citation_id, self.quote, self.field_path, self.text)
        ):
            raise ValueError("未知单元格不能携带未核对的内容。")
        return self


class TaskRowDraft(StrictModel):
    # Keys are checked against the selected, registered structure by the server.
    cells: dict[str, TaskCellDraft] = Field(default_factory=dict, max_length=5)


class TaskResultDraft(StrictModel):
    format: Literal["blockers", "cases", "review", "commitments"]
    rows: list[TaskRowDraft] = Field(default_factory=list, max_length=40)

    @model_validator(mode="after")
    def bounded_sources(self):
        identities = {
            cell.citation_id
            for row in self.rows
            for cell in row.cells.values()
            if cell.citation_id is not None
        }
        if len(identities) > 20:
            raise ValueError("任务结果最多引用 20 个已核对来源。")
        return self


SCHEMAS = {
    "assistant.search": AssistantSearchInput,
    "assistant.extract": ExtractInput,
    "assistant.citations.read": CitationsInput,
    "assistant.materials.read": MaterialsInput,
    "assistant.compare": CompareInput,
    "assistant.comparison.read": ComparisonReadInput,
    "assistant.passage.read": PassageInput,
}
