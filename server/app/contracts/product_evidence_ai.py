"""Typed domain candidates; model output never controls scope, owner, IDs or state."""

from typing import Self

from pydantic import Field, model_validator

from app.contracts.product_work_ai import ProductWorkAssessment
from app.domain.competitors import CompetitorContent
from app.domain.market_analysis import MarketSegmentContent


class ProductEvidenceAssessment(ProductWorkAssessment):
    competitor_observations: tuple[CompetitorContent, ...] = Field(default=(), max_length=6)
    market_segments: tuple[MarketSegmentContent, ...] = Field(default=(), max_length=6)

    @model_validator(mode="after")
    def matching_domain(self) -> Self:
        if self.capability not in ("competitor_analysis", "market_analysis"):
            raise ValueError("证据候选只用于竞品和市场分析")
        if (self.capability == "competitor_analysis" and self.market_segments) or (
            self.capability == "market_analysis" and self.competitor_observations
        ):
            raise ValueError("候选类型须与本次分析能力一致")
        if (self.competitor_observations or self.market_segments) and not self.summary:
            raise ValueError("候选须有引用原字段的分析依据")
        return self
