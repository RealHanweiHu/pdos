"""RFQ extraction preserves source statements and unknowns; only draft requirements result."""

from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from app.contracts.change_work_package import Statement
from app.contracts.common_objects import Contract, Text
from app.contracts.product_work_ai import ProductWorkAssessment


def private_fragment(reference: str) -> bool:
    parts = reference.split(":")
    if len(parts) != 4 or parts[0] != "attachment" or parts[2] != "fragment":
        return False
    try:
        return (
            str(UUID(parts[1])) == parts[1].lower()
            and parts[3].isascii()
            and parts[3].isdecimal()
            and int(parts[3]) > 0
            and str(int(parts[3])) == parts[3]
        )
    except ValueError:
        return False


class RfqRequirement(Contract):
    title: str = Field(min_length=1, max_length=512)
    description: str = Field(min_length=1, max_length=12000)
    priority: Literal["low", "medium", "high", "critical"]
    acceptance_criteria: tuple[Text, ...] = Field(max_length=30)
    basis: Statement
    missing: tuple[Text, ...] = Field(max_length=20)
    category_label: None = None

    @model_validator(mode="after")
    def cited_and_honest(self) -> Self:
        if not self.acceptance_criteria and not self.missing:
            raise ValueError("未给出验收判据时须明确待澄清项")
        if not self.basis.citations or any(
            not (
                citation.reference_id.startswith("file:") or private_fragment(citation.reference_id)
            )
            or tuple(citation.field_path) != ("text",)
            for citation in self.basis.citations
        ):
            raise ValueError("RFQ需求必须引用本次原文件片段")
        return self


class ProductRfqAssessment(ProductWorkAssessment):
    requirements: tuple[RfqRequirement, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def rfq_only(self) -> Self:
        if self.capability != "rfq_requirements":
            raise ValueError("RFQ合同仅用于需求抽取")
        if self.requirements and (self.disposition != "analysis" or not self.summary):
            raise ValueError("需求抽取须保留有依据的摘要")
        return self
