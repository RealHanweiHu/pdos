"""Deterministic, evidence-bound Cost BOM calculations and subsystem comparisons."""

from datetime import date
from decimal import Decimal, localcontext
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.build_materials import BuildMaterialService
from app.domain.cost_inputs import (
    Currency,
    InputPreview,
    Positive,
    PriceDraft,
    RateDraft,
    current_query,
    sources,
)
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import ProductWorkError, _plain, digest

ALGORITHM = "cost-rollup.v1"


class PriceSelection(Contract):
    input_id: UUID
    quantity_per_product: Positive | None = None


class RollupDraft(Contract):
    bom_id: UUID
    title: str = Field(min_length=1, max_length=256)
    stage: Literal["estimate", "quote", "actual"]
    currency: Currency
    as_of: date
    product_quantity: Positive
    product_unit: str = Field(min_length=1, max_length=64)
    tax_basis: Literal["exclusive", "inclusive"]
    freight_basis: Literal["included", "excluded"]
    rate_type: Literal["spot", "budget", "erp_actual"]
    max_rate_age_days: int = Field(ge=0, le=3650)
    nre_policy: Literal["separate", "amortize"]
    nre_volume: Positive | None = None
    quantity_basis: Text
    scope_basis: Text
    prices: list[PriceSelection] = Field(min_length=1, max_length=500)
    target_ids: list[UUID] = Field(default_factory=list, max_length=100)
    rate_ids: list[UUID] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def consistent(self) -> "RollupDraft":
        ids = [v.input_id for v in self.prices] + self.target_ids + self.rate_ids
        if len(ids) != len(set(ids)):
            raise ValueError("同一依据版本只能选择一次")
        if (self.nre_policy == "amortize") != (self.nre_volume is not None):
            raise ValueError("NRE分摊须明确分摊产品数量；单列时不填写分摊数量")
        return self


class RollupSave(Contract):
    request_id: UUID
    expected_digest: Digest
    draft: RollupDraft


def basis(c: Connection, tenant: UUID, project: UUID, command: RollupDraft) -> dict[str, Any]:
    b, i, t = tables.development_boms, tables.development_bom_items, tables.cost_inputs
    bom = (
        c.execute(
            select(b).where(
                b.c.tenant_id == tenant,
                b.c.project_id == project,
                b.c.id == command.bom_id,
                b.c.bom_type == "cost",
            )
        )
        .mappings()
        .one_or_none()
    )
    if bom is None:
        raise ProductWorkError("请选择本项目Cost BOM")
    items = list(
        c.execute(
            select(i)
            .where(i.c.tenant_id == tenant, i.c.project_id == project, i.c.bom_id == command.bom_id)
            .order_by(i.c.line_number, i.c.id)
            .limit(2001)
        ).mappings()
    )
    if len(items) > 2000:
        raise ProductWorkError("当前计算上限2000个BOM项，未截断计算，请先按实际子装配拆分核对")
    ids = [v.input_id for v in command.prices] + command.target_ids + command.rate_ids
    inputs = list(
        c.execute(
            select(t)
            .where(t.c.tenant_id == tenant, t.c.project_id == project, t.c.id.in_(ids))
            .order_by(t.c.id)
        ).mappings()
    )
    if len(inputs) != len(ids):
        raise ProductWorkError("所选成本依据不属于此项目或已不可用")
    receipts = []
    for row in inputs:
        value = _plain(dict(row))
        latest = (
            c.execute(current_query(tenant, project).where(t.c.record_id == row["record_id"]))
            .mappings()
            .one()
        )
        value["current"] = latest["id"] == row["id"] and row["status"] == "active"
        try:
            value["source_current"] = (
                digest(sources(c, tenant, project, InputPreview(draft=row["payload"]).draft))
                == row["snapshot"]["source_digest"]
            )
        except (ValueError, LookupError, PermissionError):
            value["source_current"] = False
        receipts.append(value)
    return {
        "algorithm": ALGORITHM,
        "bom": _plain(dict(bom)),
        "items": [_plain(dict(v)) for v in items],
        "inputs": receipts,
    }


def calculate(command: RollupDraft, fixed: dict[str, Any]) -> dict[str, Any]:
    with localcontext() as ctx:
        ctx.prec = 38
        return _calculate(command, fixed)


def _calculate(command: RollupDraft, fixed: dict[str, Any]) -> dict[str, Any]:
    gaps: list[str] = []
    warnings: list[str] = []
    items = {v["id"]: v for v in fixed["items"]}
    inputs = {v["id"]: v for v in fixed["inputs"]}
    rates: dict[str, tuple[RateDraft, str]] = {}
    for rid in command.rate_ids:
        row = inputs[str(rid)]
        rate = InputPreview(draft=row["payload"]).draft
        if not isinstance(rate, RateDraft):
            raise ProductWorkError("汇率选择须对应汇率依据版本")
        if rate.to_currency != command.currency or rate.rate_type != command.rate_type:
            raise ProductWorkError("汇率方向和用途须与本次计算口径一致")
        if rate.from_currency in rates:
            raise ProductWorkError("同一原币种只选择一个明确时点汇率")
        age = (command.as_of - rate.as_of).days
        if (
            not row["current"]
            or not row["source_current"]
            or not 0 <= age <= command.max_rate_age_days
        ):
            gaps.append(f"{rate.from_currency}汇率来源/版本或时点不满足本次口径")
        else:
            rates[rate.from_currency] = (rate, str(rid))

    def convert(
        price: PriceDraft, amount: Decimal
    ) -> tuple[Decimal | None, str | None, str | None]:
        if price.tax_basis == "unknown" or price.freight_basis != command.freight_basis:
            return None, None, "税费未知或运费口径不一致，未假定费用为零"
        if price.tax_basis != command.tax_basis:
            if price.tax_rate is None:
                return None, None, "缺少税率，无法换为本次税费口径"
            amount = (
                amount / (1 + price.tax_rate)
                if command.tax_basis == "exclusive"
                else amount * (1 + price.tax_rate)
            )
        rate_id = None
        if price.currency != command.currency:
            if price.currency not in rates:
                return None, None, f"缺少{price.currency}到{command.currency}的有效指定汇率"
            rate, rate_id = rates[price.currency]
            amount *= rate.rate
        return amount, rate_id, None

    def original(rid: UUID) -> tuple[PriceDraft, dict[str, Any], list[str]]:
        row = inputs[str(rid)]
        price = InputPreview(draft=row["payload"]).draft
        if not isinstance(price, PriceDraft):
            raise ProductWorkError("价格与目标必须选择实际成本依据")
        missing = []
        if not row["current"] or not row["source_current"]:
            missing.append("原依据已修订、撤回或来源变化")
        if price.as_of > command.as_of:
            missing.append("原依据晚于本次计算时点")
        return price, row, missing

    selected_items: set[str] = set()
    quantities: dict[str, Decimal] = {}
    ancestors: dict[str, set[str]] = {}
    for identity, item in items.items():
        quantity = Decimal(item["quantity"])
        seen = {identity}
        parent = item["parent_item_id"]
        chain = set()
        while parent:
            if parent not in items or parent in seen:
                raise ProductWorkError("Cost BOM存在缺失父项或循环，无法滚算数量")
            seen.add(parent)
            chain.add(parent)
            quantity *= Decimal(items[parent]["quantity"])
            parent = items[parent]["parent_item_id"]
        quantities[identity] = quantity
        ancestors[identity] = chain
    lines = []
    groups: dict[str, dict[str, Any]] = {}

    def group(name: str) -> dict[str, Any]:
        return groups.setdefault(
            name,
            {
                "subsystem": name,
                "unit": Decimal(0),
                "nre": Decimal(0),
                "unit_complete": True,
                "nre_complete": True,
                "target_unit": None,
                "target_nre": None,
                "unit_count": 0,
                "nre_count": 0,
            },
        )

    for selection in command.prices:
        price, row, missing = original(selection.input_id)
        if (
            price.stage == "target"
            or (command.stage != "estimate" and price.stage != command.stage)
            or (command.stage == "estimate" and price.stage not in {"estimate", "quote"})
        ):
            raise ProductWorkError("估算只选择估算/报价依据；报价与实际计算必须分别使用对应阶段")
        identity = str(price.bom_item_id) if price.bom_item_id else None
        if identity and identity not in items:
            raise ProductWorkError("所选费用关联的Cost BOM项不属于本次范围")
        if price.basis == "nre":
            if selection.quantity_per_product is not None:
                raise ProductWorkError("NRE整项不填写每产品用量")
            quantity = Decimal(1)
            order_quantity = Decimal(1)
        elif identity:
            if identity not in items:
                raise ProductWorkError("所选物料价格不属于本次Cost BOM")
            if price.category == "material" and identity in selected_items:
                raise ProductWorkError("同一Cost BOM项不能重复选择价格")
            if selection.quantity_per_product is not None:
                raise ProductWorkError("BOM物料用量从原父子层级滚算，不能在成本计算中改写")
            if price.category == "material":
                selected_items.add(identity)
            quantity = quantities[identity]
            order_quantity = quantity * command.product_quantity
        else:
            if price.category == "material":
                raise ProductWorkError("物料计价须对应实际Cost BOM项")
            if selection.quantity_per_product is None:
                raise ProductWorkError("非BOM单位费用须明确每产品使用数量")
            quantity = selection.quantity_per_product
            order_quantity = quantity * command.product_quantity
        if price.stage == "quote":
            if (
                not price.valid_from
                or not price.valid_until
                or not price.valid_from <= command.as_of <= price.valid_until
            ):
                missing.append("报价不在本次计价日有效期内")
            if (
                price.minimum_order_quantity is None
                or order_quantity < price.minimum_order_quantity
                or price.maximum_order_quantity is not None
                and order_quantity > price.maximum_order_quantity
            ):
                missing.append("本次原单位需求量不在所选报价档位内")
        if price.stage == "actual" and price.actual_quantity != order_quantity:
            missing.append("ERP行实际数量与本次产品数量/用量不一致，需先按凭证范围对账")
        unit = price.amount / price.price_quantity
        value, rate_id, conversion_error = convert(price, unit * quantity)
        if conversion_error:
            missing.append(conversion_error)
        if missing:
            value = None
        g = group(price.subsystem)
        bucket = "nre" if price.basis == "nre" else "unit"
        g[bucket + "_count"] += 1
        if value is None:
            g[bucket + "_complete"] = False
        else:
            g[bucket] += value
        gaps.extend(f"{price.title}：{m}" for m in missing)
        lines.append(
            {
                "input_id": str(selection.input_id),
                "record_id": row["record_id"],
                "version": row["version"],
                "title": price.title,
                "stage": price.stage,
                "subsystem": price.subsystem,
                "basis": price.basis,
                "bom_item_id": identity,
                "quantity_per_product": str(quantity),
                "order_quantity": str(order_quantity),
                "original_amount": str(price.amount),
                "price_quantity": str(price.price_quantity),
                "original_currency": price.currency,
                "unit": price.unit,
                "rate_input_id": rate_id,
                "value": str(value) if value is not None else None,
                "missing": missing,
            }
        )
    for identity in selected_items:
        if ancestors[identity] & selected_items:
            raise ProductWorkError(
                "父组件与其子项同时计价会重复计入，请明确采用父组件整包或子项拆分"
            )
    parents = {v["parent_item_id"] for v in items.values() if v["parent_item_id"]}
    uncovered = [
        i
        for i in items
        if i not in parents and i not in selected_items and not ancestors[i] & selected_items
    ]
    if not items:
        gaps.append("Cost BOM没有物料项，无法声明完整产品成本")
    for identity in uncovered:
        gaps.append(f"BOM {items[identity]['part_number']} 未选择有效价格，未按零计价")
    target_keys = set()
    for rid in command.target_ids:
        price, row, missing = original(rid)
        if price.stage != "target" or price.bom_item_id is not None:
            raise ProductWorkError(
                "子系统比较须选择独立子系统目标或NRE预算，不使用单个物料目标冒充总目标"
            )
        key = (price.subsystem, price.basis)
        if key in target_keys:
            raise ProductWorkError("同一子系统和计价范围只能选择一个目标版本")
        target_keys.add(key)
        if price.basis == "unit" and price.unit != command.product_unit:
            missing.append("目标单位与成品单位不一致")
        value, rate_id, error = convert(price, price.amount / price.price_quantity)
        if error:
            missing.append(error)
        g = group(price.subsystem)
        bucket = "nre" if price.basis == "nre" else "unit"
        g["target_" + bucket] = {
            "input_id": str(rid),
            "value": str(value) if value is not None and not missing else None,
            "rate_input_id": rate_id,
            "missing": missing,
        }
        warnings.extend(f"目标 {price.subsystem}：{m}" for m in missing)
    comparison = []
    material_complete = bool(items) and not uncovered
    for g in groups.values():
        comparison_item = {"subsystem": g["subsystem"]}
        for bucket in ("unit", "nre"):
            target = g["target_" + bucket]
            complete = (
                g[bucket + "_complete"]
                and g[bucket + "_count"] > 0
                and (material_complete if bucket == "unit" else True)
            )
            actual = g[bucket] if complete else None
            comparison_item[bucket] = {
                "known_subtotal": str(g[bucket]),
                "total": str(actual) if actual is not None else None,
                "target": target,
                "gap": str(actual - Decimal(target["value"]))
                if actual is not None and target and target["value"] is not None
                else None,
            }
            if target and not g[bucket + "_count"]:
                warnings.append(f"{g['subsystem']}目标没有对应的所选成本条目，不按零计算差额")
            if not target and g[bucket]:
                warnings.append(
                    f"{g['subsystem']}缺少"
                    f"{'NRE预算' if bucket == 'nre' else '单位成本目标'}，未计算该差额"
                )
        comparison.append(comparison_item)
    has_nre = any(g["nre_count"] for g in groups.values())
    if command.nre_policy == "amortize" and not has_nre:
        gaps.append("分摊NRE但未选择一次性费用依据，不能按零分摊")
    complete = not gaps
    unit = sum((g["unit"] for g in groups.values()), Decimal(0))
    nre = sum((g["nre"] for g in groups.values()), Decimal(0))
    combined = unit + nre / command.nre_volume if command.nre_volume else None
    top = sorted(
        (line for line in lines if line["basis"] == "unit" and line["value"] is not None),
        key=lambda line: Decimal(line["value"]),
        reverse=True,
    )[:10]
    return {
        "algorithm": ALGORITHM,
        "decimal_precision": 38,
        "rounding": "only_display_no_currency_rounding",
        "complete": complete,
        "currency": command.currency,
        "unit_total": str(unit) if complete else None,
        "known_unit_subtotal": str(unit),
        "nre_total": str(nre) if complete and has_nre else None,
        "known_nre_subtotal": str(nre),
        "including_allocated_nre": str(combined) if complete and combined is not None else None,
        "lines": lines,
        "comparisons": comparison,
        "top_drivers": top,
        "gaps": gaps,
        "warnings": warnings,
        "scope_notice": (
            "按选定BOM及明确费用范围核算；估算/报价/ERP实际分列，未知不按零；"
            "未选费用不推定已覆盖，结果不等于批准冻结或量产验证。"
        ),
    }


def preview(c: Connection, tenant: UUID, project: UUID, command: RollupDraft) -> dict[str, Any]:
    fixed = basis(c, tenant, project, command)
    result = calculate(command, fixed)
    value = {"command": command.model_dump(mode="json"), "basis": fixed, "result": result}
    return {**value, "digest": digest(value)}


class CostRollupService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def options(
        self,
        context: AuthContext,
        project: UUID,
        bom: UUID | None = None,
        after: UUID | None = None,
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            BuildMaterialService._authorize(c, context, project)
            b, i, t = tables.development_boms, tables.development_bom_items, tables.cost_inputs
            boms = list(
                c.execute(
                    select(b)
                    .where(
                        b.c.tenant_id == context.tenant.id,
                        b.c.project_id == project,
                        b.c.bom_type == "cost",
                    )
                    .order_by(b.c.code, b.c.version)
                ).mappings()
            )
            q = current_query(context.tenant.id, project).where(t.c.status == "active")
            if bom:
                if not any(row["id"] == bom for row in boms):
                    raise ProductWorkError("Cost BOM不属于此项目")
                q = q.where(
                    t.c.bom_item_id.is_(None)
                    | t.c.bom_item_id.in_(
                        select(i.c.id).where(
                            i.c.tenant_id == context.tenant.id,
                            i.c.project_id == project,
                            i.c.bom_id == bom,
                        )
                    )
                )
            if after:
                q = q.where(t.c.record_id > after)
            inputs = list(c.execute(q.order_by(t.c.record_id).limit(51)).mappings())
            return {
                "boms": [_plain(dict(v)) for v in boms],
                "inputs": [_plain(dict(v)) for v in inputs[:50]],
                "next_cursor": str(inputs[49]["record_id"]) if len(inputs) > 50 else None,
            }

    def prepare(self, context: AuthContext, project: UUID, command: RollupDraft) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            BuildMaterialService._authorize(c, context, project, write=True)
            return preview(c, context.tenant.id, project, command)

    def save(self, context: AuthContext, project: UUID, command: RollupSave) -> dict[str, Any]:
        with self.engine.begin() as c:
            NpiExecutionService._project(
                c, tenant_id=context.tenant.id, project_id=project, lock=True
            )
            BuildMaterialService._authorize(c, context, project, write=True)
            t = tables.cost_rollups
            signature = digest(command.model_dump(mode="json"))
            prior = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.created_by_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["project_id"] != project or prior["request_digest"] != signature:
                    raise ProductWorkError("此请求已用于不同成本计算")
                return _plain(dict(prior))
            value = preview(c, context.tenant.id, project, command.draft)
            if value["digest"] != command.expected_digest:
                raise ProductWorkError("价格、目标、汇率或BOM已变化，请重新计算核对")
            saved = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project,
                        bom_id=command.draft.bom_id,
                        title=command.draft.title,
                        algorithm=ALGORITHM,
                        command=value["command"],
                        snapshot=value["basis"],
                        result=value["result"],
                        source_digest=digest(value["basis"]),
                        calculation_digest=value["digest"],
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=signature,
                        created_at=func.clock_timestamp(),
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            NpiExecutionService._record_change(
                c,
                tenant_id=context.tenant.id,
                project_id=project,
                actor_user_id=context.user.id,
                record_id=saved["id"],
                record_type="cost_rollup",
                action="calculated",
                before=None,
                after=_plain(dict(saved)),
            )
            from app.domain.cost_gaps import record_for_rollup

            record_for_rollup(c, context, saved)
            return _plain(dict(saved))

    def get(
        self,
        context: AuthContext,
        project: UUID,
        identity: UUID | None = None,
        before: UUID | None = None,
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            BuildMaterialService._authorize(c, context, project)
            t = tables.cost_rollups
            q = select(t).where(t.c.tenant_id == context.tenant.id, t.c.project_id == project)
            if identity:
                q = q.where(t.c.id == identity)
            if before:
                cursor = c.execute(q.where(t.c.id == before)).mappings().one_or_none()
                if cursor is None:
                    raise ProductWorkError("请从当前项目计算历史继续翻页")
                q = q.where(
                    (t.c.created_at < cursor["created_at"])
                    | ((t.c.created_at == cursor["created_at"]) & (t.c.id < before))
                )
            records = list(
                c.execute(q.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21)).mappings()
            )
            items = []
            for row in records[:20]:
                value = _plain(dict(row))
                if identity:
                    try:
                        latest_basis = basis(
                            c,
                            context.tenant.id,
                            project,
                            RollupDraft.model_validate(row["command"]),
                        )
                        value["source_current"] = digest(latest_basis) == row[
                            "source_digest"
                        ] and all(
                            v["current"] and v["source_current"] for v in latest_basis["inputs"]
                        )
                    except (ValueError, LookupError, PermissionError):
                        value["source_current"] = False
                else:
                    value = {
                        k: value[k]
                        for k in (
                            "id",
                            "title",
                            "created_at",
                            "created_by_user_id",
                            "algorithm",
                            "command",
                            "calculation_digest",
                        )
                    } | {"complete": row["result"]["complete"]}
                items.append(value)
            return {
                "items": items,
                "next_cursor": str(records[19]["id"]) if len(records) > 20 else None,
            }
