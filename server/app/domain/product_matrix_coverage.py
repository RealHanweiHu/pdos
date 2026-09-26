"""Explicit market-to-definition criteria; deterministic declaration coverage."""

from decimal import Decimal
from itertools import combinations
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import Engine, exists, select

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Digest, Key, Quantity, Text, Unit
from app.db.schema import tables
from app.domain.market_analysis import FACT_GROUPS
from app.domain.product_evidence import evidence_quality
from app.domain.product_matrix import MatrixComparison, ProductMatrixService
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _line,
    _line_filter,
    _plain,
    _space,
    digest,
)

VERSION = "market-definition-coverage.v1"


class CoverageOptions(Contract):
    search: str = Field(default="", max_length=256)
    offset: int = Field(default=0, ge=0)
    revision: Digest | None = None


class CoveragePreparation(MatrixComparison):
    segment_id: UUID


class CriterionMapping(Contract):
    product_id: UUID
    item_key: Key


class CoverageCriterion(Contract):
    key: Key
    source_locator: str = Field(
        max_length=128,
        pattern=r"^(job_to_be_done|outcome|(?:target_users|customer_problems|use_environments|buying_criteria|unmet_needs)\.[0-9]+)$",
    )
    interpretation: Text
    mode: Literal["feature", "numeric_spec"]
    mappings: tuple[CriterionMapping, ...] = Field(default=(), max_length=8)
    lower: Quantity | None = None
    upper: Quantity | None = None
    unit: Unit | None = None
    conditions: tuple[Text, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def comparable_input(self) -> Self:
        if len({item.product_id for item in self.mappings}) != len(self.mappings):
            raise ValueError("每条需求对每个产品只能指定一个对应条目")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError("下界不能大于上界")
        if self.mode == "feature" and (
            self.lower is not None
            or self.upper is not None
            or self.unit is not None
            or self.conditions
        ):
            raise ValueError("功能声明判据不接收数值、单位或测试条件")
        return self


class CoverageCalculation(CoveragePreparation):
    expected_source_digest: Digest
    criteria: tuple[CoverageCriterion, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def criteria_scope(self) -> Self:
        if len({item.key for item in self.criteria}) != len(self.criteria):
            raise ValueError("判据编号不能重复")
        selected = {item.product_id for item in self.choices}
        if any(
            mapping.product_id not in selected
            for item in self.criteria
            for mapping in item.mappings
        ):
            raise ValueError("判据对应项必须属于本次所选产品")
        return self


def segment_options_query(context: AuthContext, space_id: UUID, search: str) -> Any:
    t = tables.market_segments
    newer = t.alias("newer_segment")
    return (
        select(t.c.id, t.c.title, t.c.product_line_id, t.c.version, t.c.created_at)
        .where(
            t.c.tenant_id == context.tenant.id,
            t.c.market_space_id == space_id,
            _line_filter(t, context),
            ~exists(
                select(newer.c.id).where(
                    newer.c.tenant_id == t.c.tenant_id,
                    newer.c.series_id == t.c.series_id,
                    newer.c.version > t.c.version,
                )
            ),
            t.c.title.contains(search, autoescape=True),
        )
        .order_by(t.c.title, t.c.id)
    )


def evaluate(criterion: CoverageCriterion, product: dict[str, Any]) -> dict[str, Any]:
    mapping = next(
        (item for item in criterion.mappings if str(item.product_id) == product["id"]), None
    )
    value: dict[str, Any] = {
        "product_id": product["id"],
        "status": "unknown",
        "item_key": mapping.item_key if mapping else None,
        "actual": None,
        "source_path": None,
    }
    if mapping is None:
        return {**value, "reason": "尚未明确对应条目"}
    content = product["content"]
    if criterion.mode == "feature":
        if mapping.item_key in content["included_features"]:
            return {
                **value,
                "status": "match",
                "actual": "included",
                "source_path": "content.included_features",
                "reason": "当前发布定义明确包含所对应功能",
            }
        if mapping.item_key in content["excluded_features"]:
            return {
                **value,
                "status": "gap",
                "actual": "excluded",
                "source_path": "content.excluded_features",
                "reason": "当前发布定义明确排除所对应功能",
            }
        raise ProductWorkError("所选功能标识不在当前发布定义中，请重新核对")
    item = next((item for item in content["items"] if item["item_key"] == mapping.item_key), None)
    if item is None:
        raise ProductWorkError("所选规格条目不在当前发布定义中，请重新核对")
    value.update(actual=item, source_path=f"content.items[{mapping.item_key}]")
    missing = []
    if criterion.lower is None and criterion.upper is None:
        missing.append("目标范围未明确")
    if criterion.unit is None:
        missing.append("判据单位未明确")
    if item["state"] != "confirmed":
        missing.append("规格未确认或已标不适用")
    if item["target_value"] is None:
        missing.append("规格没有标称数值")
    if criterion.unit != item["unit"]:
        missing.append("单位不同，未作换算")
    if set(criterion.conditions) != set(item["conditions"]):
        missing.append("测试条件不同，不能直接比较")
    if missing:
        return {**value, "reason": "；".join(missing)}
    nominal = Decimal(str(item["target_value"]))
    matched = (criterion.lower is None or nominal >= criterion.lower) and (
        criterion.upper is None or nominal <= criterion.upper
    )
    return {
        **value,
        "status": "match" if matched else "gap",
        "reason": "已确认规格的标称目标在所选闭区间内"
        if matched
        else "已确认规格的标称目标在所选闭区间外",
    }


class ProductMatrixCoverageService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def options(
        self, context: AuthContext, space_id: UUID, query: CoverageOptions
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            _space(c, context, space_id)
            rows = [
                _plain(row)
                for row in c.execute(
                    segment_options_query(context, space_id, query.search).limit(10001)
                ).mappings()
            ]
            if len(rows) > 10000:
                raise ProductWorkError("市场细分超过10000项，请输入名称缩小范围")
            revision = digest(rows)
            if query.offset and query.revision != revision:
                raise ProductWorkError("市场细分已变化，请从第一页刷新")
            return {
                "items": rows[query.offset : query.offset + 20],
                "total": len(rows),
                "revision": revision,
                "next_offset": query.offset + 20 if query.offset + 20 < len(rows) else None,
            }

    def prepare(
        self, context: AuthContext, space_id: UUID, query: CoveragePreparation
    ) -> dict[str, Any]:
        comparison = ProductMatrixService(self.engine).compare(
            context, space_id, MatrixComparison(choices=query.choices)
        )
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            _space(c, context, space_id)
            t = tables.market_segments
            row = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.market_space_id == space_id,
                        t.c.id == query.segment_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProductWorkAccessError("市场细分不存在或不可访问")
            _line(c, context, space_id, row["product_line_id"])
            if c.execute(
                select(t.c.id).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.series_id == row["series_id"],
                    t.c.version > row["version"],
                )
            ).first():
                raise ProductWorkError("所选市场细分已有新版本，请重新选择")
            outcome = (
                c.execute(
                    select(tables.desired_outcomes).where(
                        tables.desired_outcomes.c.tenant_id == context.tenant.id,
                        tables.desired_outcomes.c.id == row["desired_outcome_id"],
                    )
                )
                .mappings()
                .one()
            )
            facts = [{"locator": "job_to_be_done", "fact": row["job_to_be_done"]}]
            for group in FACT_GROUPS:
                facts.extend(
                    {"locator": f"{group}.{index}", "fact": fact}
                    for index, fact in enumerate(row[group])
                )
            facts.append(
                {
                    "locator": "outcome",
                    "fact": {
                        "text": outcome["statement"],
                        "sources": outcome["sources"],
                        "fact_kind": "desired_outcome",
                        "metric_key": outcome["metric_key"],
                        "unit": outcome["unit"],
                        "baseline_value": str(outcome["baseline_value"])
                        if outcome["baseline_value"] is not None
                        else None,
                        "target_value": str(outcome["target_value"])
                        if outcome["target_value"] is not None
                        else None,
                        "measurement_method": outcome["measurement_method"],
                        "window": outcome["window"],
                    },
                }
            )
            snapshot = _plain(
                {
                    "segment": {
                        key: row[key]
                        for key in ("id", "title", "version", "product_line_id", "created_at")
                    },
                    "facts": facts,
                    "products": comparison["products"],
                    "version": VERSION,
                }
            )
            refs = [ref for entry in facts for ref in entry["fact"]["sources"]]
            return {
                **snapshot,
                "source_digest": digest(snapshot),
                "source_warnings": evidence_quality(c, context, refs),
                "limits": comparison["limits"],
            }

    def calculate(
        self, context: AuthContext, space_id: UUID, query: CoverageCalculation
    ) -> dict[str, Any]:
        prepared = self.prepare(
            context,
            space_id,
            CoveragePreparation(choices=query.choices, segment_id=query.segment_id),
        )
        if prepared["source_digest"] != query.expected_source_digest:
            raise ProductWorkError("市场或产品依据已变化，请重新读取后对应")
        return calculate_snapshot(query, prepared)


def calculate_snapshot(query: CoverageCalculation, prepared: dict[str, Any]) -> dict[str, Any]:
    if prepared["version"] != VERSION:
        raise ProductWorkError("此对照规则版本尚不支持重算")
    facts = {item["locator"]: item["fact"] for item in prepared["facts"]}
    results = []
    for criterion in query.criteria:
        if criterion.source_locator not in facts:
            raise ProductWorkError("判据引用的原市场需求不存在")
        cells = [evaluate(criterion, product) for product in prepared["products"]]
        counts = {
            key: sum(cell["status"] == key for cell in cells) for key in ("match", "gap", "unknown")
        }
        status = "match" if counts["match"] else "unknown" if counts["unknown"] else "gap"
        results.append(
            {
                "criterion": criterion.model_dump(mode="json"),
                "market_fact": facts[criterion.source_locator],
                "cells": cells,
                "counts": counts,
                "selected_portfolio_status": status,
            }
        )
    product_summary = []
    for product in prepared["products"]:
        counts = {
            key: sum(
                cell["status"] == key
                for row in results
                for cell in row["cells"]
                if cell["product_id"] == product["id"]
            )
            for key in ("match", "gap", "unknown")
        }
        product_summary.append({"product_id": product["id"], **counts})
    overlap = []
    for left, right in combinations(prepared["products"], 2):
        shared = [
            row["criterion"]["key"]
            for row in results
            if all(
                any(
                    cell["product_id"] == product["id"] and cell["status"] == "match"
                    for cell in row["cells"]
                )
                for product in (left, right)
            )
        ]
        overlap.append(
            {
                "left_id": left["id"],
                "right_id": right["id"],
                "shared_criteria": shared,
                "ancestor_related": left["id"] in [node["id"] for node in right["path"]]
                or right["id"] in [node["id"] for node in left["path"]],
            }
        )
    result = {
        "snapshot": prepared,
        "criteria": results,
        "product_summary": product_summary,
        "overlap": overlap,
        "formula_version": VERSION,
        "input_digest": digest(query.model_dump(mode="json")),
        "scope": (
            "本次人工对应的市场需求及所选发布定义；功能声明和规格标称目标对照，"
            "不代表实测覆盖、市场份额或蚕食。"
        ),
        "formula": (
            "逐项精确功能声明或同单位/同条件已确认标称值与闭区间比较；"
            "有一个产品匹配即为所选组合声明有对应；无匹配且有未知则保持未知，"
            "否则为已知声明缺口。未知不补分、不做销量/收益计算。"
        ),
    }
    return {**result, "result_digest": digest(result)}
