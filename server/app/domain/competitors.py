"""Cited competitor observations and deterministic comparison of stated conditions."""

from datetime import UTC, date, datetime
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Key, Quantity, SourceRef, Text, Unit
from app.db.schema import tables
from app.domain.product_evidence import evidence_quality as _quality
from app.domain.product_evidence import resolve_evidence as _resolve
from app.domain.product_workspace import (
    Input,
    ProductWorkAccessError,
    ProductWorkError,
    _emit,
    _line,
    _line_filter,
    _record,
    _role,
    _space,
    digest,
)


class CompetitorMetric(Contract):
    key: Key
    label: Text
    number: Quantity | None = None
    text: Text | None = None
    unit: Unit | None = None
    nature: Literal["claimed", "measured", "inferred", "unknown"]
    conditions: Text | None = None
    method: Text | None = None
    source_refs: tuple[SourceRef, ...] = Field(default=(), max_length=20)
    missing_reason: Text | None = None

    @model_validator(mode="after")
    def supported_value(self) -> Self:
        if self.nature == "unknown":
            if self.number is not None or self.text is not None or self.missing_reason is None:
                raise ValueError("未知指标须保留缺失原因，不能补入数值")
        elif not self.source_refs or (self.number is None) == (self.text is None):
            raise ValueError("已知指标须有来源，且填写数值或文字值之一")
        if self.number is not None and self.unit is None:
            raise ValueError("数值指标须注明单位")
        if self.nature == "inferred" and self.method is None:
            raise ValueError("推断指标须保留计算或推断方法")
        return self


class PriceQuote(Contract):
    amount: Quantity = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    as_of: date
    quantity: int = Field(ge=1, le=1000000)
    basis: Literal["retail", "list", "promotion", "wholesale"]
    tax_included: bool | None
    shipping_included: bool | None
    conditions: Text
    source_refs: tuple[SourceRef, ...] = Field(min_length=1, max_length=20)


class CertificationObservation(Contract):
    name: Text
    status: Literal["reported", "documented", "unknown"]
    scope: Text | None = None
    document_number: Text | None = None
    valid_until: date | None = None
    source_refs: tuple[SourceRef, ...] = Field(default=(), max_length=20)
    missing_reason: Text | None = None

    @model_validator(mode="after")
    def document_proof(self) -> Self:
        if self.status == "unknown" and self.missing_reason is None:
            raise ValueError("未知认证须注明缺失信息")
        if self.status != "unknown" and not self.source_refs:
            raise ValueError("认证声明须引用来源")
        if self.status == "documented" and (self.document_number is None or self.scope is None):
            raise ValueError("证书记录须保存编号及覆盖范围")
        return self


class CompetitorDraft(Input):
    request_id: UUID
    product_line_id: UUID | None = None
    supersedes_id: UUID | None = None
    brand: str = Field(min_length=1, max_length=256)
    model: str = Field(min_length=1, max_length=256)
    variant: str = Field(min_length=1, max_length=256)
    competitor_kind: Literal["direct", "indirect", "emerging", "substitute"]
    region: str = Field(min_length=1, max_length=128)
    channel: str = Field(min_length=1, max_length=128)
    configuration: Text
    lifecycle: Literal["unknown", "announced", "available", "discontinued"]
    observed_on: date
    identity_sources: tuple[SourceRef, ...] = Field(min_length=1, max_length=20)
    metrics: tuple[CompetitorMetric, ...] = Field(min_length=1, max_length=50)
    price_quote: PriceQuote | None = None
    certifications: tuple[CertificationObservation, ...] = Field(default=(), max_length=30)
    notes: str = Field(default="", max_length=4096)
    revision_reason: Text

    @model_validator(mode="after")
    def observation_dates(self) -> Self:
        if len({metric.key for metric in self.metrics}) != len(self.metrics):
            raise ValueError("同一观察内指标编号不能重复")
        if self.observed_on > datetime.now(UTC).date():
            raise ValueError("观察日期不能晚于今天")
        if self.price_quote and self.price_quote.as_of > self.observed_on:
            raise ValueError("价格日期不能晚于本次观察日期")
        return self


class ComparisonRequest(Contract):
    observation_ids: tuple[UUID, ...] = Field(min_length=2, max_length=6)

    @model_validator(mode="after")
    def different_observations(self) -> Self:
        if len(set(self.observation_ids)) != len(self.observation_ids):
            raise ValueError("请选择不同的观察记录")
        return self


def _all_refs(row: Any) -> list[dict[str, Any]]:
    refs = list(row["identity_sources"])
    for metric in row["metrics"]:
        refs.extend(metric["source_refs"])
    if row["price_quote"]:
        refs.extend(row["price_quote"]["source_refs"])
    for certification in row["certifications"]:
        refs.extend(certification["source_refs"])
    return refs


class CompetitorService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list(self, context: AuthContext, space_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _space(connection, context, space_id)
            table = tables.competitor_observations
            rows = list(
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        _line_filter(table, context),
                    )
                    .order_by(table.c.created_at.desc())
                    .limit(200)
                ).mappings()
            )
            superseded = {row["supersedes_id"] for row in rows if row["supersedes_id"]}
            return {
                "items": [
                    {
                        **_record(row),
                        "is_latest": row["id"] not in superseded,
                        "source_warnings": _quality(connection, context, _all_refs(row)),
                    }
                    for row in rows
                ]
            }

    def create(
        self, context: AuthContext, space_id: UUID, draft: CompetitorDraft
    ) -> dict[str, Any]:
        _role(context, Action.PRODUCT_WORK_CONTRIBUTE)
        with self.engine.begin() as connection:
            _space(connection, context, space_id, access="contributor", lock=True)
            _line(
                connection,
                context,
                space_id,
                draft.product_line_id,
                access="contributor",
                writable=True,
            )
            table = tables.competitor_observations
            fingerprint = digest(draft.model_dump(mode="json"))
            existing = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        table.c.owner_user_id == context.user.id,
                        table.c.request_id == draft.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing:
                if existing["request_digest"] != fingerprint:
                    raise ProductWorkError("同一请求编号不能用于不同竞品观察")
                return _record(existing)
            node_id = uuid4()
            series_id, version = node_id, 1
            if draft.supersedes_id:
                previous = (
                    connection.execute(
                        select(table).where(
                            table.c.tenant_id == context.tenant.id,
                            table.c.market_space_id == space_id,
                            table.c.id == draft.supersedes_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if previous is None:
                    raise ProductWorkAccessError("前一观察记录不存在或不可访问")
                _line(
                    connection,
                    context,
                    space_id,
                    previous["product_line_id"],
                    access="contributor",
                    writable=True,
                )
                if (
                    previous["product_line_id"],
                    previous["brand"],
                    previous["model"],
                    previous["variant"],
                ) != (draft.product_line_id, draft.brand, draft.model, draft.variant):
                    raise ProductWorkError("修订须保持同一范围、品牌、型号和变体")
                if connection.execute(
                    select(table.c.id).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.supersedes_id == previous["id"],
                    )
                ).first():
                    raise ProductWorkError("此记录已有新版，请以最新观察创建修订")
                series_id, version = previous["series_id"], previous["version"] + 1
            payload = draft.model_dump(
                mode="json",
                exclude={"request_id", "product_line_id", "supersedes_id", "observed_on"},
            )
            payload["identity_sources"] = _resolve(connection, context, draft.identity_sources)
            for metric, value in zip(draft.metrics, payload["metrics"], strict=True):
                value["source_refs"] = _resolve(connection, context, metric.source_refs)
            if draft.price_quote:
                payload["price_quote"]["source_refs"] = _resolve(
                    connection, context, draft.price_quote.source_refs
                )
            for certification, value in zip(
                draft.certifications, payload["certifications"], strict=True
            ):
                value["source_refs"] = _resolve(connection, context, certification.source_refs)
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        **payload,
                        id=node_id,
                        tenant_id=context.tenant.id,
                        market_space_id=space_id,
                        product_line_id=draft.product_line_id,
                        series_id=series_id,
                        supersedes_id=draft.supersedes_id,
                        version=version,
                        owner_user_id=context.user.id,
                        observed_on=draft.observed_on,
                        request_id=draft.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            _emit(connection, context, space_id, "competitor_observation", "recorded", row)
            return _record(row)

    def compare(
        self, context: AuthContext, space_id: UUID, request: ComparisonRequest
    ) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _space(connection, context, space_id)
            table = tables.competitor_observations
            selected = {
                row["id"]: row
                for row in connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        table.c.id.in_(request.observation_ids),
                    )
                ).mappings()
            }
            rows = []
            for row_id in request.observation_ids:
                row = selected.get(row_id)
                if row is None:
                    raise ProductWorkAccessError("部分观察记录不存在或不可访问")
                _line(connection, context, space_id, row["product_line_id"])
                rows.append(row)
            metrics = [{metric["key"]: metric for metric in row["metrics"]} for row in rows]
            keys = sorted({key for item in metrics for key in item})
            result = []
            context_warnings = _quality(
                connection, context, [ref for row in rows for ref in row["identity_sources"]]
            )
            for field, message in (
                ("configuration", "配置不同，请结合比较用途判断"),
                ("channel", "销售渠道不同"),
                ("observed_on", "观察日期不同"),
            ):
                if len({row[field] for row in rows}) > 1:
                    context_warnings.append(message)
            for key in keys:
                cells = [item.get(key) for item in metrics]
                reasons: list[str] = []
                if any(cell is None or cell["nature"] == "unknown" for cell in cells):
                    reasons.append("部分型号缺少该指标")
                known = [cell for cell in cells if cell is not None and cell["nature"] != "unknown"]
                for field, reason in (
                    ("label", "指标定义不同"),
                    ("unit", "单位不同，尚未做有据换算"),
                    ("nature", "宣传、实测或推断口径不同"),
                    ("conditions", "测试或使用条件不同"),
                    ("method", "测量方法不同"),
                ):
                    if len({cell[field] for cell in known}) > 1:
                        reasons.append(reason)
                if any(cell["conditions"] is None or cell["method"] is None for cell in known):
                    reasons.append("工况或测量方法未明确")
                if any(cell["nature"] == "inferred" for cell in known):
                    reasons.append("推断值需要验证")
                if len({row["region"] for row in rows}) > 1:
                    reasons.append("销售地区不同")
                if len({cell["number"] is None for cell in known}) > 1:
                    reasons.append("数值和文字表达不一致")
                warnings = list(
                    dict.fromkeys(
                        context_warnings
                        + _quality(
                            connection,
                            context,
                            [ref for cell in known for ref in cell["source_refs"]],
                        )
                    )
                )
                result.append(
                    {
                        "key": key,
                        "label": next((cell["label"] for cell in cells if cell), key),
                        "kind": "metric",
                        "status": "not_comparable"
                        if reasons
                        else "review_needed"
                        if warnings
                        else "comparable",
                        "reasons": reasons + warnings,
                        "cells": cells,
                    }
                )
            prices = [row["price_quote"] for row in rows]
            price_reasons = []
            if any(price is None for price in prices):
                price_reasons.append("部分型号价格未知")
            known_prices = [price for price in prices if price is not None]
            for key, label in (
                ("currency", "币种"),
                ("as_of", "报价日期"),
                ("quantity", "数量"),
                ("basis", "促销或报价类型"),
                ("tax_included", "税费"),
                ("shipping_included", "运费"),
                ("conditions", "报价条件"),
            ):
                if len({price[key] for price in known_prices}) > 1:
                    price_reasons.append(f"{label}口径不同")
            if any(
                price["tax_included"] is None or price["shipping_included"] is None
                for price in known_prices
            ):
                price_reasons.append("税费或运费范围未知")
            for key, label in (("region", "地区"), ("channel", "渠道"), ("configuration", "配置")):
                if len({row[key] for row in rows}) > 1:
                    price_reasons.append(f"{label}不同")
            warnings = list(
                dict.fromkeys(
                    context_warnings
                    + _quality(
                        connection,
                        context,
                        [ref for price in known_prices for ref in price["source_refs"]],
                    )
                )
            )
            result.append(
                {
                    "key": "price",
                    "label": "价格",
                    "kind": "price",
                    "status": "not_comparable"
                    if price_reasons
                    else "review_needed"
                    if warnings
                    else "comparable",
                    "reasons": price_reasons + warnings,
                    "cells": prices,
                }
            )
            return {
                "observations": [_record(row) for row in rows],
                "rows": result,
                "comparison_policy_version": "declared-conditions-v1",
                "as_of": datetime.now(UTC).isoformat(),
                "note": "同口径标记仅说明录入条件一致，不代表证据已独立验证；本表不自动排名。",
            }
