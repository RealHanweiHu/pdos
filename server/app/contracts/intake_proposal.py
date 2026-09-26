"""Cited intake suggestions; historical text is never a current approval or completion."""

from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROMPT_VERSION = "intake-organization-v1"
SOURCE_VERSION = "intake-source-v1"
Kind = Literal["issue", "decision", "project_observation"]
Text = Annotated[str, Field(min_length=1, max_length=2000)]
FIELDS: dict[str, set[str]] = {
    "issue": {
        "title",
        "description",
        "external_ref",
        "source_state",
        "root_cause",
        "resolution",
        "target_date",
    },
    "decision": {
        "title",
        "outcome",
        "context",
        "options",
        "trade_offs",
        "rationale",
        "consequence",
        "historical_date",
        "historical_approver",
        "historical_owner",
        "historical_kind",
        "historical_state",
        "external_ref",
        "issue_ref",
    },
    "project_observation": {
        "phase",
        "progress",
        "historical_date",
        "responsibility",
        "gap",
        "other",
    },
}


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceQuote(Input):
    reference_id: str = Field(min_length=1, max_length=100)
    start: int = Field(ge=0, lt=20000)
    end: int = Field(gt=0, le=20000)
    exact_quote: str = Field(min_length=1, max_length=20000)

    @model_validator(mode="after")
    def nonempty(self) -> Self:
        if self.end <= self.start or not self.exact_quote.strip():
            raise ValueError("引用必须是非空的原文连续范围")
        return self


class ExtractedField(Input):
    name: str = Field(min_length=1, max_length=64)
    citation: SourceQuote


class Proposal(Input):
    number: int = Field(ge=1, le=30)
    kind: Kind
    summary: Text
    anchor: SourceQuote
    fields: tuple[ExtractedField, ...] = Field(max_length=14)
    missing_information: tuple[Text, ...] = Field(max_length=15)

    @model_validator(mode="after")
    def field_names(self) -> Self:
        names = [item.name for item in self.fields]
        if len(set(names)) != len(names) or set(names) - FIELDS[self.kind]:
            raise ValueError("字段重复或不属于所选对象")
        return self


class PossibleDuplicate(Input):
    first: int = Field(ge=1, le=30)
    second: int = Field(ge=1, le=30)
    explanation: Text


class IntakeOrganization(Input):
    disposition: Literal["proposals", "insufficient_evidence"]
    proposals: tuple[Proposal, ...] = Field(max_length=30)
    possible_duplicates: tuple[PossibleDuplicate, ...] = Field(max_length=30)
    open_questions: tuple[Text, ...] = Field(max_length=30)

    @model_validator(mode="after")
    def complete(self) -> Self:
        numbers = {item.number for item in self.proposals}
        if len(numbers) != len(self.proposals):
            raise ValueError("建议编号重复")
        if (self.disposition == "proposals") != bool(self.proposals):
            raise ValueError("资料不足时不生成对象建议")
        pairs = set()
        for pair in self.possible_duplicates:
            key = tuple(sorted((pair.first, pair.second)))
            if pair.first == pair.second or not set(key) <= numbers or key in pairs:
                raise ValueError("相似项须指向不同的实际建议，且不得重复")
            pairs.add(key)
        return self


def materialize(source: dict[str, Any], output: IntakeOrganization) -> dict[str, Any]:
    references = {item["reference_id"]: item for item in source["fragments"]}
    kinds = set(source["kinds"])
    quoted_characters = 0

    def quote(value: SourceQuote) -> dict[str, Any]:
        nonlocal quoted_characters
        original = references.get(value.reference_id)
        if original is None or value.end > len(original["text"]):
            raise ValueError("建议引用不属于本次固定的原文范围")
        text = original["text"][value.start : value.end]
        if text != value.exact_quote:
            raise ValueError("建议引用与原文字符范围不一致")
        quoted_characters += len(text)
        if quoted_characters > 200000:
            raise ValueError("建议引用超过当前人工核对范围")
        return {
            "attachment_id": original["attachment_id"],
            "ordinal": original["ordinal"],
            "locator": original["locator"],
            "start": value.start,
            "end": value.end,
            "value": text,
            "reference_id": value.reference_id,
        }

    proposals = []
    for item in output.proposals:
        if item.kind not in kinds:
            raise ValueError("建议对象不属于本次请求的整理范围")
        anchor = quote(item.anchor)
        original = {field.name: quote(field.citation) for field in item.fields}
        proposals.append(
            {
                "number": item.number,
                "kind": item.kind,
                "model_summary": item.summary,
                "anchor": anchor,
                "original": original,
                "missing_information": list(item.missing_information),
            }
        )
    return {
        "disposition": output.disposition,
        "proposals": proposals,
        "possible_duplicates": [
            item.model_dump(mode="json") for item in output.possible_duplicates
        ],
        "open_questions": list(output.open_questions),
    }
