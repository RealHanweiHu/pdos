"""Versioned cost evidence; recorded prices never imply approved or frozen costs."""

from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.build_materials import BuildMaterialService
from app.domain.document_previews import document_row, metadata
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.supplier_engineering import supplier_row

Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Money = Annotated[Decimal, Field(ge=0, max_digits=24, decimal_places=8)]
Positive = Annotated[Decimal, Field(gt=0, max_digits=24, decimal_places=8)]


class EvidenceDraft(Contract):
    source_reference: str = Field(min_length=1, max_length=256)
    source_line: str = Field(min_length=1, max_length=256)
    evidence_id: UUID
    location: Text
    as_of: date
    status: Literal["active", "withdrawn"] = "active"
    reason: Text

    @model_validator(mode="after")
    def actual_date(self) -> "EvidenceDraft":
        if self.as_of > datetime.now(UTC).date():
            raise ValueError("原资料日期不能填写未来时间；未来报价生效日请填在有效期")
        return self


class PriceDraft(EvidenceDraft):
    kind: Literal["price"] = "price"
    stage: Literal["target", "estimate", "quote", "actual"]
    title: str = Field(min_length=1, max_length=256)
    subsystem: str = Field(min_length=1, max_length=128)
    category: Literal[
        "material",
        "labor",
        "tooling",
        "certification",
        "prototype",
        "testing",
        "logistics",
        "other",
    ]
    basis: Literal["unit", "nre"]
    currency: Currency
    amount: Money
    price_quantity: Positive = Decimal("1")
    unit: str = Field(min_length=1, max_length=64)
    tax_basis: Literal["exclusive", "inclusive", "unknown"]
    tax_rate: Annotated[Decimal, Field(ge=0, le=1, max_digits=9, decimal_places=8)] | None = None
    freight_basis: Literal["included", "excluded", "unknown"]
    scope_basis: Text
    bom_item_id: UUID | None = None
    supplier_id: UUID | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    minimum_order_quantity: Positive | None = None
    maximum_order_quantity: Positive | None = None
    actual_quantity: Positive | None = None
    actual_source: Literal["erp_snapshot"] | None = None

    @model_validator(mode="after")
    def complete(self) -> "PriceDraft":
        if self.basis == "nre" and (self.price_quantity != 1 or self.unit != "项"):
            raise ValueError("一次性费用按整项总额登记，计价数量为1、单位为项；分摊另行核对")
        if (
            self.category == "material"
            and self.basis == "unit"
            and self.stage != "target"
            and not self.bom_item_id
        ):
            raise ValueError("物料估算、报价及实际须对应本项目Cost BOM物料项")
        if self.stage == "quote":
            if (
                not self.supplier_id
                or not self.valid_from
                or not self.valid_until
                or not self.minimum_order_quantity
            ):
                raise ValueError("报价须有实际供方、明确有效期及最小适用订购量")
            if self.valid_until < self.valid_from:
                raise ValueError("报价有效期结束不能早于开始")
            if (
                self.maximum_order_quantity
                and self.maximum_order_quantity < self.minimum_order_quantity
            ):
                raise ValueError("报价最大数量不能小于最小数量")
        elif any(
            (
                self.valid_from,
                self.valid_until,
                self.minimum_order_quantity,
                self.maximum_order_quantity,
            )
        ):
            raise ValueError("仅供应报价填写有效期及适用订购量")
        if self.stage == "actual":
            if self.actual_source != "erp_snapshot" or self.actual_quantity is None:
                raise ValueError("实际成本须登记ERP快照来源及其实际数量，不能以报价替代")
            if self.basis == "unit" and self.actual_quantity != self.price_quantity:
                raise ValueError("实际总额须按同一凭证的实际数量计价，计价数量须与实际数量相同")
            if self.basis == "nre" and self.actual_quantity != 1:
                raise ValueError("一次性费用实际数量为1项")
        elif self.actual_source is not None or self.actual_quantity is not None:
            raise ValueError("目标、估算与报价不登记为ERP实际")
        if self.tax_basis == "unknown" and self.tax_rate is not None:
            raise ValueError("税费口径未知时不能填写确定税率")
        return self


class RateDraft(EvidenceDraft):
    kind: Literal["exchange_rate"] = "exchange_rate"
    from_currency: Currency
    to_currency: Currency
    rate: Positive
    rate_type: Literal["spot", "budget", "erp_actual"]
    scope_basis: Text

    @model_validator(mode="after")
    def different_currencies(self) -> "RateDraft":
        if self.from_currency == self.to_currency:
            raise ValueError("同币种不需要汇率；汇率方向为1原币折合多少目标币")
        return self


Draft = Annotated[PriceDraft | RateDraft, Field(discriminator="kind")]


class InputPreview(Contract):
    draft: Draft


class InputApply(InputPreview):
    request_id: UUID
    expected_version: int = Field(ge=0)
    expected_digest: Digest


def current_query(tenant: UUID, project: UUID) -> Any:
    t = tables.cost_inputs
    newer = t.alias("newer_cost_input")
    return select(t).where(
        t.c.tenant_id == tenant,
        t.c.project_id == project,
        ~select(newer.c.id)
        .where(
            newer.c.tenant_id == t.c.tenant_id,
            newer.c.project_id == t.c.project_id,
            newer.c.record_id == t.c.record_id,
            newer.c.version > t.c.version,
        )
        .correlate(t)
        .exists(),
    )


def source_key(draft: PriceDraft | RateDraft) -> str:
    return digest(
        {
            "kind": draft.kind,
            "stage": draft.stage if isinstance(draft, PriceDraft) else None,
            "reference": draft.source_reference,
            "line": draft.source_line,
        }
    )


def sources(
    c: Connection, tenant: UUID, project: UUID, draft: PriceDraft | RateDraft
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "document": metadata(document_row(c, tenant, project, draft.evidence_id))
    }
    if isinstance(draft, PriceDraft):
        if draft.supplier_id:
            result["supplier"] = supplier_row(c, tenant, draft.supplier_id)
        if draft.bom_item_id:
            t, b = tables.development_bom_items, tables.development_boms
            item = (
                c.execute(
                    select(t)
                    .join(b, (b.c.tenant_id == t.c.tenant_id) & (b.c.id == t.c.bom_id))
                    .where(
                        t.c.tenant_id == tenant,
                        t.c.project_id == project,
                        t.c.id == draft.bom_item_id,
                        b.c.project_id == project,
                        b.c.bom_type == "cost",
                    )
                )
                .mappings()
                .one_or_none()
            )
            if item is None:
                raise ProductWorkError("请选择本项目实际Cost BOM物料项；不向EBOM写入成本真值")
            if draft.basis == "unit" and item["unit"] != draft.unit:
                raise ProductWorkError("计价单位与Cost BOM单位不同，须先明确换算后登记原件依据")
            result["bom_item"] = _plain(dict(item))
            bom = (
                c.execute(select(b).where(b.c.tenant_id == tenant, b.c.id == item["bom_id"]))
                .mappings()
                .one()
            )
            result["bom"] = _plain(dict(bom))
    return result


def normalized(draft: PriceDraft | RateDraft) -> dict[str, Any]:
    if isinstance(draft, RateDraft):
        return {
            "direction": f"1 {draft.from_currency} = {draft.rate} {draft.to_currency}",
            "rate": str(draft.rate),
            "as_of": draft.as_of.isoformat(),
            "rate_type": draft.rate_type,
        }
    with localcontext() as context:
        context.prec = 38
        unit_amount = draft.amount / draft.price_quantity
    return {
        "algorithm": "cost-price-normalization.v1",
        "decimal_precision": 38,
        "stage": draft.stage,
        "basis": draft.basis,
        "currency": draft.currency,
        "source_amount": str(draft.amount),
        "source_quantity": str(draft.price_quantity),
        "unit_amount": str(unit_amount),
        "unit": draft.unit,
        "tax_basis": draft.tax_basis,
        "tax_rate": str(draft.tax_rate) if draft.tax_rate is not None else None,
        "freight_basis": draft.freight_basis,
        "notice": "保留原税费/运费口径，未兑换币种、分摊NRE或计入滚算；未知口径不视为0。",
    }


def preview(
    c: Connection, context: AuthContext, project: UUID, record: UUID, draft: PriceDraft | RateDraft
) -> dict[str, Any]:
    BuildMaterialService._authorize(c, context, project, write=True)
    t = tables.cost_inputs
    current = (
        c.execute(current_query(context.tenant.id, project).where(t.c.record_id == record))
        .mappings()
        .one_or_none()
    )
    key = source_key(draft)
    if current and (current["source_key"] != key or current["kind"] != draft.kind):
        raise ProductWorkError("沿原来源/行及成本阶段修订；新的实际或报价请独立登记")
    if c.execute(
        select(t.c.id)
        .where(
            t.c.tenant_id == context.tenant.id,
            t.c.project_id == project,
            t.c.source_key == key,
            t.c.record_id != record,
        )
        .limit(1)
    ).first():
        raise ProductWorkError("同一来源行已有记录，请修订原记录，避免重复计价")
    payload = draft.model_dump(mode="json")
    if draft.status == "withdrawn":
        if current is None:
            raise ProductWorkError("新记录不能直接撤回")
        if {k: v for k, v in payload.items() if k not in {"status", "reason"}} != {
            k: v for k, v in current["payload"].items() if k not in {"status", "reason"}
        }:
            raise ProductWorkError("撤回只填写理由；需修改原值请另保存修订")
        actual_sources = current["snapshot"]["sources"]
    else:
        actual_sources = sources(c, context.tenant.id, project, draft)
    basis = {
        "author": {"id": str(context.user.id), "name": context.user.display_name},
        "sources": actual_sources,
        "source_digest": digest(actual_sources),
        "command": payload,
        "previous_version": current["version"] if current else 0,
        "normalized": normalized(draft),
    }
    return {"basis": basis, "digest": digest(basis)}


class CostInputService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(
        self,
        context: AuthContext,
        project: UUID,
        *,
        after: UUID | None = None,
        record: UUID | None = None,
        before_version: int | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            BuildMaterialService._authorize(c, context, project)
            t = tables.cost_inputs
            query = current_query(context.tenant.id, project)
            if record:
                query = query.where(t.c.record_id == record)
            elif after:
                query = query.where(t.c.record_id > after)
            values = list(c.execute(query.order_by(t.c.record_id).limit(21)).mappings())
            items = []
            for row in values[:20]:
                view = _plain(dict(row))
                try:
                    draft = InputPreview(draft=row["payload"]).draft
                    view["source_current"] = (
                        digest(sources(c, context.tenant.id, project, draft))
                        == row["snapshot"]["source_digest"]
                    )
                except (ValueError, LookupError, PermissionError):
                    view["source_current"] = False
                view["quote_expired"] = (
                    row["stage"] == "quote"
                    and date.fromisoformat(row["payload"]["valid_until"]) < datetime.now(UTC).date()
                )
                items.append(view)
            history = []
            if record:
                q = select(t).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.project_id == project,
                    t.c.record_id == record,
                )
                if before_version is not None:
                    q = q.where(t.c.version < before_version)
                history = list(c.execute(q.order_by(t.c.version.desc()).limit(21)).mappings())
            d, b, bi, supplier = (
                tables.documents,
                tables.development_boms,
                tables.development_bom_items,
                tables.suppliers,
            )
            options: dict[str, Any] = {}
            for name, q in (
                (
                    "documents",
                    select(d.c.id, d.c.filename.label("label"))
                    .where(d.c.tenant_id == context.tenant.id, d.c.project_id == project)
                    .order_by(d.c.created_at.desc()),
                ),
                (
                    "suppliers",
                    select(supplier.c.id, supplier.c.name.label("label"))
                    .where(supplier.c.tenant_id == context.tenant.id)
                    .order_by(supplier.c.code),
                ),
                (
                    "bom_items",
                    select(
                        bi.c.id,
                        bi.c.part_number.label("label"),
                        bi.c.unit,
                        b.c.code.label("bom_code"),
                        b.c.version.label("bom_version"),
                    )
                    .join(b, (b.c.tenant_id == bi.c.tenant_id) & (b.c.id == bi.c.bom_id))
                    .where(
                        bi.c.tenant_id == context.tenant.id,
                        bi.c.project_id == project,
                        b.c.bom_type == "cost",
                    )
                    .order_by(b.c.code, bi.c.part_number),
                ),
            ):
                if search:
                    needle = (
                        "%"
                        + search.strip()
                        .replace("\\", "\\\\")
                        .replace("%", "\\%")
                        .replace("_", "\\_")
                        + "%"
                    )
                    if name == "documents":
                        q = q.where(d.c.filename.ilike(needle, escape="\\"))
                    elif name == "suppliers":
                        q = q.where(
                            supplier.c.name.ilike(needle, escape="\\")
                            | supplier.c.code.ilike(needle, escape="\\")
                        )
                    else:
                        q = q.where(
                            bi.c.part_number.ilike(needle, escape="\\")
                            | bi.c.description.ilike(needle, escape="\\")
                            | b.c.code.ilike(needle, escape="\\")
                        )
                all_rows = list(c.execute(q.limit(201)).mappings())
                options[name] = [_plain(dict(row)) for row in all_rows[:200]]
                options[name + "_more"] = len(all_rows) > 200
            return {
                "items": items,
                "history": [_plain(dict(r)) for r in history[:20]],
                "next_cursor": str(values[19]["record_id"]) if len(values) > 20 else None,
                "next_history_version": history[19]["version"] if len(history) > 20 else None,
                "options": options,
            }

    def preview(
        self, context: AuthContext, project: UUID, record: UUID, body: InputPreview
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return preview(c, context, project, record, body.draft)

    def apply(
        self, context: AuthContext, project: UUID, record: UUID, body: InputApply
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            return self.apply_in_connection(c, context, project, record, body)

    def apply_in_connection(
        self, c: Connection, context: AuthContext, project: UUID, record: UUID, body: InputApply
    ) -> dict[str, Any]:
        signature = digest(
            {
                "project": str(project),
                "record": str(record),
                "command": body.model_dump(mode="json"),
            }
        )
        NpiExecutionService._project(c, tenant_id=context.tenant.id, project_id=project, lock=True)
        BuildMaterialService._authorize(c, context, project, write=True)
        t = tables.cost_inputs
        old = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.created_by_user_id == context.user.id,
                    t.c.request_id == body.request_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if old:
            if old["request_digest"] != signature:
                raise ProductWorkError("此请求号已用于不同成本依据")
            return _plain(dict(old))
        observed = preview(c, context, project, record, body.draft)
        if (
            observed["digest"] != body.expected_digest
            or observed["basis"]["previous_version"] != body.expected_version
        ):
            raise ProductWorkError("原来源或版本已变化，请重新预览")
        draft = body.draft
        saved = (
            c.execute(
                t.insert()
                .values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    project_id=project,
                    record_id=record,
                    version=body.expected_version + 1,
                    kind=draft.kind,
                    stage=draft.stage if isinstance(draft, PriceDraft) else None,
                    source_key=source_key(draft),
                    status=draft.status,
                    payload=draft.model_dump(mode="json"),
                    snapshot=observed["basis"],
                    evidence_id=draft.evidence_id,
                    bom_item_id=draft.bom_item_id if isinstance(draft, PriceDraft) else None,
                    supplier_id=draft.supplier_id if isinstance(draft, PriceDraft) else None,
                    reason=draft.reason,
                    created_by_user_id=context.user.id,
                    request_id=body.request_id,
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
            record_id=record,
            record_type="cost_input",
            action=draft.status,
            before=None,
            after=_plain(dict(saved)),
        )
        return _plain(dict(saved))
