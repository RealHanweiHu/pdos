"""Evidence-bound comparisons between retained frozen costs and actual ERP calculations."""

from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.build_materials import BuildMaterialService
from app.domain.cost_freezes import row
from app.domain.cost_rollups import ALGORITHM as ROLLUP_ALGORITHM
from app.domain.cost_rollups import RollupDraft, basis, calculate
from app.domain.document_previews import document_row, metadata
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import ProductWorkError, _plain, digest

ALGORITHM = "cost-backtest.v1"


class CostPair(Contract):
    frozen_input_id: UUID
    actual_input_id: UUID
    correspondence_basis: Text


class BacktestDraft(Contract):
    freeze_id: UUID
    actual_rollup_id: UUID
    expected_calculation_digest: Digest
    title: str = Field(min_length=1, max_length=256)
    purpose: Literal["historical_snapshot", "production_actual"]
    period_from: date
    period_to: date
    evidence_id: UUID
    evidence_location: Text
    scope_basis: Text
    quantity_basis: Text
    limitations: Text
    pairs: list[CostPair] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def consistent(self) -> "BacktestDraft":
        if not self.period_from <= self.period_to <= datetime.now(UTC).date():
            raise ValueError("成本观察区间须按先后填写且不能晚于今天")
        for key in ("frozen_input_id", "actual_input_id"):
            values = [getattr(pair, key) for pair in self.pairs]
            if len(values) != len(set(values)):
                raise ValueError("同一费用条目只能参与一次对应，不能重复计入差额")
        return self


class BacktestSave(Contract):
    request_id: UUID
    expected_digest: Digest
    draft: BacktestDraft
    evidence_checked: bool
    scope_checked: bool
    quantity_checked: bool


def source_state(c: Connection, tenant: UUID, project: UUID, calculation: Any) -> dict[str, Any]:
    try:
        fixed = basis(c, tenant, project, RollupDraft.model_validate(calculation["command"]))
        return {
            "current": digest(fixed) == calculation["source_digest"]
            and all(v["current"] and v["source_current"] for v in fixed["inputs"]),
            "reason": "按当前BOM、成本依据及原件重新读取；历史计算值保留",
        }
    except (ValueError, LookupError, PermissionError):
        return {"current": False, "reason": "至少一项原来源当前无法核对，保留历史计算值"}


def compare(
    command: BacktestDraft, frozen: dict[str, Any], actual: dict[str, Any]
) -> dict[str, Any]:
    with localcontext() as ctx:
        ctx.prec = 38
        return _compare(command, frozen, actual)


def _compare(
    command: BacktestDraft, frozen: dict[str, Any], actual: dict[str, Any]
) -> dict[str, Any]:
    left, right = frozen["command"], actual["command"]
    a = {v["input_id"]: v for v in frozen["result"]["lines"]}
    b = {v["input_id"]: v for v in actual["result"]["lines"]}
    ai = {v["id"]: v["payload"] for v in frozen["snapshot"]["inputs"]}
    bi = {v["id"]: v["payload"] for v in actual["snapshot"]["inputs"]}
    abom = {v["id"]: v for v in frozen["snapshot"]["items"]}
    bbom = {v["id"]: v for v in actual["snapshot"]["items"]}
    common_gaps, notices = [], []
    for key, label in (
        ("currency", "统一币种"),
        ("tax_basis", "税费"),
        ("freight_basis", "运费"),
        ("product_unit", "成品单位"),
    ):
        if left[key] != right[key]:
            common_gaps.append(f"两边{label}口径不同，不能直接相减")
    for key, label in (
        ("product_quantity", "计算产品数量"),
        ("as_of", "计价时点"),
        ("rate_type", "汇率用途"),
        ("scope_basis", "费用范围说明"),
        ("quantity_basis", "数量依据"),
        ("bom_id", "Cost BOM版本"),
    ):
        if left[key] != right[key]:
            notices.append(f"两边{label}不同，须结合原值与具名对应依据解释差异")
    pairs, used_a, used_b = [], set(), set()
    for pair in command.pairs:
        aid, bid = str(pair.frozen_input_id), str(pair.actual_input_id)
        if aid not in a or bid not in b:
            raise ProductWorkError("对应条目必须来自选定冻结计算和实际计算的费用行")
        used_a.add(aid)
        used_b.add(bid)
        x, y, xp, yp = a[aid], b[bid], ai[aid], bi[bid]
        gaps = list(common_gaps)
        for key, label in (
            ("basis", "单位／NRE"),
            ("subsystem", "子系统"),
            ("unit", "原始单位"),
            ("category", "费用类型"),
        ):
            if xp[key] != yp[key]:
                gaps.append(f"{label}不同，尚不能按同一费用直接对比")
        if Decimal(x["quantity_per_product"]) != Decimal(y["quantity_per_product"]):
            gaps.append("每成品使用数量不同，不能作为同范围费用差额")
        xb, yb = abom.get(x["bom_item_id"]), bbom.get(y["bom_item_id"])
        if bool(xb) != bool(yb) or xb and yb and xb["part_number"] != yb["part_number"]:
            gaps.append("BOM对应项／料号不同，须在工程变更后的同范围计算另行比较")
        if xb and yb and (
            xb["unit"] != yb["unit"] or xp["unit"] != xb["unit"] or yp["unit"] != yb["unit"]
        ):
            gaps.append("BOM用量或计价单位不一致，未假定历史单位换算关系")
        if x["value"] is None or y["value"] is None:
            gaps.append("至少一边原计算金额不完整")
        delta = Decimal(y["value"]) - Decimal(x["value"]) if not gaps else None
        pct = (
            delta / Decimal(x["value"]) * 100
            if delta is not None and Decimal(x["value"]) != 0
            else None
        )
        pairs.append(
            {
                "frozen_input_id": aid,
                "actual_input_id": bid,
                "correspondence_basis": pair.correspondence_basis,
                "basis": x["basis"],
                "subsystem": x["subsystem"],
                "frozen": x,
                "actual": y,
                "frozen_bom_item": xb,
                "actual_bom_item": yb,
                "comparable": not gaps,
                "gaps": gaps,
                "delta": str(delta) if delta is not None else None,
                "percent": str(pct) if pct is not None else None,
            }
        )
    missing_a = [v for k, v in a.items() if k not in used_a]
    missing_b = [v for k, v in b.items() if k not in used_b]
    totals = {}
    for kind in ("unit", "nre"):
        relevant = [
            v for v in pairs if v["frozen"]["basis"] == kind or v["actual"]["basis"] == kind
        ]
        unmapped = any(v["basis"] == kind for v in missing_a + missing_b)
        complete = bool(relevant) and not unmapped and all(v["comparable"] for v in relevant)
        previous = sum(
            (Decimal(v["frozen"]["value"]) for v in relevant if v["comparable"]), Decimal(0)
        )
        observed = sum(
            (Decimal(v["actual"]["value"]) for v in relevant if v["comparable"]), Decimal(0)
        )
        delta = observed - previous
        totals[kind] = {
            "comparable": complete,
            "frozen": str(previous) if complete else None,
            "actual": str(observed) if complete else None,
            "delta": str(delta) if complete else None,
            "percent": str(delta / previous * 100) if complete and previous != 0 else None,
            "matched_frozen_subtotal": str(previous),
            "matched_actual_subtotal": str(observed),
            "unmapped": unmapped,
            "matched_count": sum(v["comparable"] for v in relevant),
        }
    allocated = None
    if (
        left["nre_policy"] == right["nre_policy"] == "amortize"
        and Decimal(left["nre_volume"]) == Decimal(right["nre_volume"])
        and totals["unit"]["comparable"]
        and totals["nre"]["comparable"]
    ):
        previous = Decimal(totals["unit"]["frozen"]) + Decimal(totals["nre"]["frozen"]) / Decimal(
            left["nre_volume"]
        )
        observed = Decimal(totals["unit"]["actual"]) + Decimal(totals["nre"]["actual"]) / Decimal(
            right["nre_volume"]
        )
        allocated = {
            "frozen": str(previous),
            "actual": str(observed),
            "delta": str(observed - previous),
            "volume": left["nre_volume"],
        }
    elif left["nre_policy"] == "amortize" or right["nre_policy"] == "amortize":
        notices.append("NRE分摊口径或覆盖不一致，不计算包含分摊的单位总差额")
    subsystems = []
    for subsystem in sorted(
        {v["subsystem"] for v in a.values()} | {v["subsystem"] for v in b.values()}
    ):
        for kind in ("unit", "nre"):
            relevant = [
                v
                for v in pairs
                if (v["frozen"]["subsystem"] == subsystem and v["frozen"]["basis"] == kind)
                or (v["actual"]["subsystem"] == subsystem and v["actual"]["basis"] == kind)
            ]
            if not relevant and not any(
                v["subsystem"] == subsystem and v["basis"] == kind for v in missing_a + missing_b
            ):
                continue
            complete = (
                bool(relevant)
                and all(v["comparable"] for v in relevant)
                and not any(
                    v["subsystem"] == subsystem and v["basis"] == kind
                    for v in missing_a + missing_b
                )
            )
            delta = sum(
                (Decimal(v["delta"]) for v in relevant if v["delta"] is not None), Decimal(0)
            )
            subsystems.append(
                {
                    "subsystem": subsystem,
                    "basis": kind,
                    "comparable": complete,
                    "delta": str(delta) if complete else None,
                }
            )
    top = sorted(
        (v for v in pairs if v["delta"] is not None),
        key=lambda v: abs(Decimal(v["delta"])),
        reverse=True,
    )
    return {
        "algorithm": ALGORITHM,
        "decimal_precision": 38,
        "currency": left["currency"],
        "totals": totals,
        "allocated": allocated,
        "pairs": pairs,
        "subsystems": subsystems,
        "unmatched_frozen": missing_a,
        "unmatched_actual": missing_b,
        "gaps": common_gaps,
        "notices": notices,
        "unit_drivers": [v for v in top if v["basis"] == "unit"][:10],
        "nre_drivers": [v for v in top if v["basis"] == "nre"][:10],
        "scope_notice": (
            "差额为实际减冻结，按各自已保存汇率折算后的费用对比，包含价格、税费转换和汇率变化；"
            "不自动解释为纯单价变化、节省成果或因果关系。未对应项不补零；回测不批准替代料或工程变更。"
        ),
    }


def preview(
    c: Connection, context: AuthContext, project: UUID, command: BacktestDraft
) -> dict[str, Any]:
    BuildMaterialService._authorize(c, context, project, write=True)
    frozen = row(c, context.tenant.id, project, tables.cost_freezes, command.freeze_id)
    actual = row(c, context.tenant.id, project, tables.cost_rollups, command.actual_rollup_id)
    fixed = frozen["snapshot"]["calculation"]
    if actual["calculation_digest"] != command.expected_calculation_digest:
        raise ProductWorkError("实际成本计算版本已改变，请重新选择")
    for source in (fixed, actual):
        if source["algorithm"] != ROLLUP_ALGORITHM or not source["result"]["complete"]:
            raise ProductWorkError("请分别保存本版算法下选定范围无计算缺口的冻结和实际计算")
        if (
            calculate(RollupDraft.model_validate(source["command"]), source["snapshot"])
            != source["result"]
        ):
            raise ProductWorkError("原计算与固定算法不一致，不能用于回测")
    if actual["command"]["stage"] != "actual":
        raise ProductWorkError("回测须明确选择ERP实际成本计算，不以估算或报价冒充实绩")
    current = source_state(c, context.tenant.id, project, actual)
    if command.purpose == "production_actual" and not current["current"]:
        raise ProductWorkError(
            "实际计算来源已修订／不可核对，请重算后登记当期量产回测；旧版可仅作历史快照对照"
        )
    value = {
        "algorithm": ALGORITHM,
        "command": command.model_dump(mode="json"),
        "freeze": {
            "id": str(frozen["id"]),
            "version": frozen["version"],
            "created_at": frozen["created_at"].isoformat(),
            "approved_by_user_id": str(frozen["approved_by_user_id"]),
            "freeze_request_id": str(frozen["freeze_request_id"]),
            "calculation_digest": frozen["calculation_digest"],
        },
        "frozen_calculation": fixed,
        "actual_calculation": _plain(dict(actual)),
        "actual_source_state": current,
        "evidence": metadata(document_row(c, context.tenant.id, project, command.evidence_id)),
        "reviewer": {"id": str(context.user.id), "name": context.user.display_name},
        "result": compare(command, fixed, _plain(dict(actual))),
    }
    return {**value, "digest": digest(value)}


class CostBacktestService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def preview(
        self, context: AuthContext, project: UUID, command: BacktestDraft
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return preview(c, context, project, command)

    def save(self, context: AuthContext, project: UUID, command: BacktestSave) -> dict[str, Any]:
        with self.engine.begin() as c:
            NpiExecutionService._project(
                c, tenant_id=context.tenant.id, project_id=project, lock=True
            )
            BuildMaterialService._authorize(c, context, project, write=True)
            t = tables.cost_backtests
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
                    raise ProductWorkError("此请求已用于另一份回测")
                return _plain(dict(prior))
            if not all((command.evidence_checked, command.scope_checked, command.quantity_checked)):
                raise ProductWorkError("请核对真实凭证、费用对应范围及原数量后保存")
            observed = preview(c, context, project, command.draft)
            if observed["digest"] != command.expected_digest:
                raise ProductWorkError("回测来源或核对口径已变化，请重新预览")
            saved = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project,
                        freeze_id=command.draft.freeze_id,
                        actual_rollup_id=command.draft.actual_rollup_id,
                        evidence_id=command.draft.evidence_id,
                        algorithm=ALGORITHM,
                        title=command.draft.title,
                        purpose=command.draft.purpose,
                        payload=command.model_dump(mode="json"),
                        snapshot=observed,
                        result=observed["result"],
                        comparison_digest=observed["digest"],
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
                record_type="cost_backtest",
                action="recorded",
                before=None,
                after=_plain(dict(saved)),
            )
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
            t = tables.cost_backtests
            columns = (
                list(t.c)
                if identity
                else [
                    t.c.id,
                    t.c.title,
                    t.c.purpose,
                    t.c.created_at,
                    t.c.freeze_id,
                    t.c.actual_rollup_id,
                    t.c.snapshot["freeze"]["version"].as_integer().label("freeze_version"),
                    t.c.comparison_digest,
                ]
            )
            q = select(*columns).where(
                t.c.tenant_id == context.tenant.id, t.c.project_id == project
            )
            if identity:
                q = q.where(t.c.id == identity)
            if before:
                cursor = row(c, context.tenant.id, project, t, before)
                q = q.where(
                    (t.c.created_at < cursor["created_at"])
                    | ((t.c.created_at == cursor["created_at"]) & (t.c.id < before))
                )
            records = list(
                c.execute(q.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21)).mappings()
            )
            values = []
            for record in records[:20]:
                value = _plain(dict(record))
                if identity:
                    value["current_actual_source"] = source_state(
                        c, context.tenant.id, project, record["snapshot"]["actual_calculation"]
                    )
                    try:
                        value["evidence_current"] = (
                            metadata(
                                document_row(c, context.tenant.id, project, record["evidence_id"])
                            )
                            == record["snapshot"]["evidence"]
                        )
                    except (ValueError, LookupError, PermissionError):
                        value["evidence_current"] = False
                values.append(value)
            return {
                "items": values,
                "next_cursor": str(records[19]["id"]) if len(records) > 20 else None,
            }
