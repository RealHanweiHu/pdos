"""Explicit, versioned weighting of declaration coverage; never an economic forecast."""

from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from app.contracts.common_objects import Contract, Key, Quantity, Text
from app.domain.product_workspace import digest


class CriterionWeight(Contract):
    criterion_key: Key
    weight: Quantity = Field(gt=0, le=1)
    basis: Text


class CoverageScoringPolicy(Contract):
    formula_version: Literal["product-coverage-weighted.v1"]
    policy_key: Key
    policy_version: int = Field(strict=True, ge=1)
    title: Text
    basis: Text
    weights: tuple[CriterionWeight, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def complete_weights(self) -> Self:
        if len({item.criterion_key for item in self.weights}) != len(self.weights):
            raise ValueError("评分权重不能重复引用判据")
        if sum((item.weight for item in self.weights), Decimal(0)) != Decimal(1):
            raise ValueError("全部判据权重之和必须精确为1，不自动归一化")
        return self


def score_coverage(
    policy: CoverageScoringPolicy, rows: list[dict[str, Any]], product_ids: list[str]
) -> dict[str, Any]:
    weights = {item.criterion_key: item.weight for item in policy.weights}

    def score(statuses: list[tuple[str, str]]) -> dict[str, Any]:
        matched = sum((weights[key] for key, state in statuses if state == "match"), Decimal(0))
        unknown = sum((weights[key] for key, state in statuses if state == "unknown"), Decimal(0))
        return {
            "score": str(matched * 100) if unknown == 0 else None,
            "lower_bound": str(matched * 100),
            "upper_bound": str((matched + unknown) * 100),
            "unknown_weight": str(unknown),
            "contributions": [
                {
                    "criterion_key": key,
                    "status": state,
                    "weight": str(weights[key]),
                    "points": None
                    if state == "unknown"
                    else str(weights[key] * (100 if state == "match" else 0)),
                }
                for key, state in statuses
            ],
        }

    return {
        "policy": policy.model_dump(mode="json"),
        "policy_digest": digest(policy.model_dump(mode="json")),
        "products": [
            {
                "product_id": product_id,
                **score(
                    [
                        (
                            row["criterion"]["key"],
                            next(
                                cell["status"]
                                for cell in row["cells"]
                                if cell["product_id"] == product_id
                            ),
                        )
                        for row in rows
                    ]
                ),
            }
            for product_id in product_ids
        ],
        "selected_portfolio": score(
            [(row["criterion"]["key"], row["selected_portfolio_status"]) for row in rows]
        ),
        "formula": (
            "声明覆盖分=100×Σ(判据权重×匹配值)；匹配=1，明确缺口=0。"
            "未知不补值，仅给出全未知不匹配至全未知匹配的区间；分母始终为全部权重1，不因缺资料缩小。"
            "组合对每条需求只计一次，以任一产品匹配为覆盖。"
        ),
        "scope": (
            "用户指定权重下的所选需求覆盖分析，不代表实测达标、商业收益、市场份额、"
            "立项优先级或方案批准。不同政策、判据或来源的分数不能直接比较。"
        ),
    }
