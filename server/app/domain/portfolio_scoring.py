"""Versioned explicit weights and deterministic portfolio comparison arithmetic."""

from datetime import datetime
from decimal import Decimal, localcontext
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.contracts.common_objects import Contract, Key, Quantity, Text
from app.domain.cost_inputs import Currency
from app.domain.working_time import CalendarDefinition, WorkingTime

FORMULA = "portfolio.relative_utility.v1"
DIMENSIONS = ("time", "cost", "quality", "capacity")


class Weights(Contract):
    time: Quantity = Field(ge=0, le=1)
    cost: Quantity = Field(ge=0, le=1)
    quality: Quantity = Field(ge=0, le=1)
    capacity: Quantity = Field(ge=0, le=1)

    @model_validator(mode="after")
    def complete(self) -> Self:
        if sum((getattr(self, key) for key in DIMENSIONS), Decimal(0)) != 1:
            raise ValueError("四项权重合计须明确为 1")
        return self


class RiskLevel(Contract):
    key: Key
    label: str = Field(min_length=1, max_length=80)
    penalty: Quantity = Field(ge=0, le=1)
    basis: Text


class PortfolioPolicy(Contract):
    request_id: UUID
    expected_version: int = Field(ge=0)
    title: Text
    status: Literal["active", "suspended"]
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    currency: Currency
    weights: Weights
    time_scale_hours: Quantity = Field(gt=0, le=1000000)
    cost_scale_amount: Quantity = Field(gt=0)
    quality_scale: Quantity = Field(gt=0, le=1)
    capacity_scale: Quantity = Field(gt=0, le=1)
    max_source_age_hours: Quantity = Field(gt=0, le=8760)
    max_asof_spread_minutes: int = Field(ge=0, le=10080)
    risk_levels: list[RiskLevel] = Field(min_length=2, max_length=10)
    reason: Text

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.valid_until <= self.valid_from:
            raise ValueError("政策有效期须为正")
        if len({v.key for v in self.risk_levels}) != len(self.risk_levels):
            raise ValueError("质量风险等级编号不可重复")
        return self


class PortfolioProject(Contract):
    project_id: UUID
    calendar_version_id: UUID
    weight: Quantity = Field(gt=0, le=1)
    basis: Text


class PortfolioChoice(Contract):
    project_id: UUID
    schedule_id: UUID
    cost_rollup_id: UUID | None = None
    quality_level: Key | None = None
    evidence_id: UUID | None = None
    evidence_location: Text | None = None
    quality_basis: Text | None = None
    scope_basis: Text

    @model_validator(mode="after")
    def evidence(self) -> Self:
        fields = (self.quality_level, self.evidence_id, self.evidence_location, self.quality_basis)
        if any(v is not None for v in fields) and any(v is None for v in fields):
            raise ValueError("质量风险假设须同时说明等级、实际资料、位置和具名判断依据；未知则留空")
        return self


class PortfolioAlternative(Contract):
    key: Key
    title: Text
    strategy: Literal[
        "reference",
        "overtime",
        "alternative_equipment",
        "outsourcing",
        "scope_tradeoff",
        "delay",
        "combined",
    ]
    assumptions: Text
    choices: list[PortfolioChoice] = Field(min_length=1, max_length=10)


class PortfolioComparison(Contract):
    request_id: UUID
    comparison_at: AwareDatetime
    title: Text
    reason: Text
    policy_id: UUID
    reference_key: Key
    projects: list[PortfolioProject] = Field(min_length=1, max_length=10)
    alternatives: list[PortfolioAlternative] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def same_scope(self) -> Self:
        projects = {p.project_id for p in self.projects}
        if (
            len(projects) != len(self.projects)
            or sum((p.weight for p in self.projects), Decimal(0)) != 1
        ):
            raise ValueError("项目不可重复，项目权重合计须明确为 1")
        keys = {option.key for option in self.alternatives}
        if len(keys) != len(self.alternatives) or self.reference_key not in keys:
            raise ValueError("方案编号不可重复，须明确选择其中一项作为比较参照")
        for option in self.alternatives:
            if (
                len(option.choices) != len(projects)
                or {c.project_id for c in option.choices} != projects
            ):
                raise ValueError("每个方案都须覆盖同一组项目；范围取舍在对应依据中明确说明")
        return self


class PortfolioComparisonSave(PortfolioComparison):
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def arithmetic(
    command: PortfolioComparison,
    policy: PortfolioPolicy,
    alternatives: list[dict[str, Any]],
    calendars: dict[str, Any],
) -> dict[str, Any]:
    """Only fixed source values enter arithmetic; no database/model/clock reads."""
    with localcontext() as context:
        context.prec = 48
        return _arithmetic(command, policy, alternatives, calendars)


def _arithmetic(
    command: PortfolioComparison,
    policy: PortfolioPolicy,
    alternatives: list[dict[str, Any]],
    calendars: dict[str, Any],
) -> dict[str, Any]:
    reference = next(v for v in alternatives if v["key"] == command.reference_key)
    baseline = {v["project_id"]: v for v in reference["projects"]}
    levels = {v.key: v.penalty for v in policy.risk_levels}
    results = []
    for option in alternatives:
        current = {v["project_id"]: v for v in option["projects"]}
        gaps: dict[str, list[str]] = {key: [] for key in DIMENSIONS}
        time_delta, cost_delta, quality_delta = Decimal(0), Decimal(0), Decimal(0)
        details = []
        for project in command.projects:
            pid = str(project.project_id)
            a, b = baseline[pid], current[pid]
            named = b["project_name"]
            hours = amount = risk = None
            if a["finish"] is None or b["finish"] is None:
                gaps["time"].append(f"{named}：至少一方结束时间未知")
            else:
                left, right = (
                    datetime.fromisoformat(a["finish"]),
                    datetime.fromisoformat(b["finish"]),
                )
                engine = WorkingTime(
                    CalendarDefinition.model_validate(calendars[pid]["definition"])
                )
                minutes = engine.working_minutes(min(left, right), max(left, right))
                hours = Decimal(minutes) / 60 * (1 if right >= left else -1)
                time_delta += hours * project.weight
            ac, bc = a["cost"], b["cost"]
            if ac is None or bc is None:
                gaps["cost"].append(f"{named}：未选择两边完整的成本计算")
            else:
                same = all(
                    ac["command"][key] == bc["command"][key]
                    for key in (
                        "currency",
                        "tax_basis",
                        "freight_basis",
                        "product_unit",
                        "as_of",
                        "rate_type",
                        "nre_policy",
                    )
                )
                same = same and Decimal(ac["command"]["product_quantity"]) == Decimal(
                    bc["command"]["product_quantity"]
                )
                av, bv = ac["command"].get("nre_volume"), bc["command"].get("nre_volume")
                same = same and (
                    (av is None and bv is None)
                    or (av is not None and bv is not None and Decimal(av) == Decimal(bv))
                )
                if not same or ac["command"]["currency"] != policy.currency:
                    gaps["cost"].append(f"{named}：币种、数量、税费、运费、时点或NRE口径不同")
                elif any(
                    v["command"]["stage"] == "actual"
                    or not v["current"]
                    or not v["result"]["complete"]
                    or v["result"]["unit_total"] is None
                    or v["result"]["nre_total"] is None
                    for v in (ac, bc)
                ):
                    gaps["cost"].append(
                        f"{named}：须采用当前完整估算/报价，单位费用或NRE缺项不按零"
                    )
                else:
                    quantity = Decimal(ac["command"]["product_quantity"])
                    amount = (
                        (Decimal(bc["result"]["unit_total"]) - Decimal(ac["result"]["unit_total"]))
                        * quantity
                        + Decimal(bc["result"]["nre_total"])
                        - Decimal(ac["result"]["nre_total"])
                    )
                    cost_delta += amount
            if a["quality_level"] not in levels or b["quality_level"] not in levels:
                gaps["quality"].append(f"{named}：缺少按本政策登记的质量风险假设")
            else:
                risk = levels[b["quality_level"]] - levels[a["quality_level"]]
                quality_delta += risk * project.weight
            details.append(
                {
                    "project_id": pid,
                    "project_name": named,
                    "weight": str(project.weight),
                    "working_hours_delta": str(hours) if hours is not None else None,
                    "cost_delta": str(amount) if amount is not None else None,
                    "quality_risk_delta": str(risk) if risk is not None else None,
                }
            )
        capacity_delta = None
        if reference["capacity_pressure"] is None or option["capacity_pressure"] is None:
            gaps["capacity"].append("至少一方缺少完整组合容量计算")
        else:
            capacity_delta = Decimal(option["capacity_pressure"]) - Decimal(
                reference["capacity_pressure"]
            )
        deltas = {
            "time": time_delta,
            "cost": cost_delta,
            "quality": quality_delta,
            "capacity": capacity_delta,
        }
        scales = {
            "time": policy.time_scale_hours,
            "cost": policy.cost_scale_amount,
            "quality": policy.quality_scale,
            "capacity": policy.capacity_scale,
        }
        dimensions, total = {}, Decimal(0)
        scored = not option["blockers"] and not reference["source_blockers"]
        for key in DIMENSIONS:
            weight = getattr(policy.weights, key)
            delta = deltas[key] if not gaps[key] else None
            score = (
                min(Decimal(100), max(Decimal(0), 50 - 50 * delta / scales[key]))
                if delta is not None
                else None
            )
            if weight and score is None:
                scored = False
            if score is not None:
                total += score * weight
            dimensions[key] = {
                "weight": str(weight),
                "delta": str(delta) if delta is not None else None,
                "scale": str(scales[key]),
                "score": str(score) if score is not None else None,
                "gaps": gaps[key],
            }
        results.append(
            {
                **option,
                "dimensions": dimensions,
                "project_differences": details,
                "score": str(total) if scored else None,
                "rank": None,
            }
        )
    ordered = sorted(
        (v for v in results if v["score"] is not None),
        key=lambda v: (-Decimal(v["score"]), v["key"]),
    )
    previous, place = None, 0
    for index, option in enumerate(ordered, 1):
        if previous is None or Decimal(option["score"]) != previous:
            place = index
        option["rank"] = place
        previous = Decimal(option["score"])
    return {
        "formula_version": FORMULA,
        "formula": (
            "dimension=clamp(50-50*(candidate-reference)/scale,0,100); total=sum(weight*dimension)"
        ),
        "reference_key": command.reference_key,
        "currency": policy.currency,
        "alternatives": results,
        "project_weight_use": (
            "time_and_human_quality_risk; cost_is_sum_of_declared_quantities; "
            "capacity_is_peak_utilization"
        ),
        "missing_policy": "unknown_weighted_dimension_or_infeasible_source_excludes_ranking",
        "applied": False,
        "ready_for_application": False,
    }
