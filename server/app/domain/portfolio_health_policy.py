"""Explicit, versioned health thresholds; missing dimensions never become green."""

from decimal import Decimal, localcontext
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import Connection, Engine, func, select, text

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Text
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain, _role, digest

CATALOG = {
    "schedule": {
        "label": "排程",
        "metric": "forecast_finish_delay_days",
        "unit": "自然日",
        "scope": "当前完整且来源一致的预测完工与当前获批基线完工之差；提前按0延误。",
    },
    "engineering": {
        "label": "工程",
        "metric": "open_severe_engineering_issues",
        "unit": "项",
        "scope": (
            "全部已登记工程Issue中尚未关闭的high/critical项；无工程Issue时不可评估，不代表无风险。"
        ),
    },
    "quality": {
        "label": "质量",
        "metric": "open_severe_quality_issues",
        "unit": "项",
        "scope": (
            "全部已登记quality/test_failure Issue中尚未关闭的high/critical项；"
            "不代表完整测试覆盖或验证通过。"
        ),
    },
    "cost": {
        "label": "成本",
        "metric": "exceeded_cost_gap_scopes",
        "unit": "项",
        "scope": (
            "全部已建Cost Gap范围的最新观察中超目标的范围数；"
            "来源失效或待重核时不可评估，不合并不同币种金额。"
        ),
    },
    "supplier": {
        "label": "供应",
        "metric": "late_sample_delivery_percent",
        "unit": "%",
        "scope": (
            "当前有效样品事项中，实际收样晚于首次承诺的比例；"
            "缺承诺或未收样保持缺口，不推定供方责任。"
        ),
    },
    "certification": {
        "label": "认证",
        "metric": "required_certificates_not_current",
        "unit": "项",
        "scope": (
            "当前必需认证中尚未有效、已失效或撤销的项数；"
            "无必需认证或日期/证据缺项不可评估，不代表市场合规矩阵完整。"
        ),
    },
}
FORMULA = (
    "health.v1: lower_is_better; <=clear=100; >=alert=0; "
    "otherwise=100*(alert-value)/(alert-clear); total=sum(weight*score); "
    "any_unknown=unknown"
)


class DimensionPolicy(Contract):
    dimension: Literal["schedule", "engineering", "quality", "cost", "supplier", "certification"]
    weight: Decimal = Field(gt=0, le=1, max_digits=12, decimal_places=8)
    clear_at_or_below: Decimal = Field(ge=0, max_digits=18, decimal_places=6)
    alert_at_or_above: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    basis: Text

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.alert_at_or_above <= self.clear_at_or_below:
            raise ValueError("异常阈值须高于正常阈值")
        if self.dimension == "supplier" and self.alert_at_or_above > 100:
            raise ValueError("延迟比例阈值不得超过100%")
        return self


class HealthPolicy(Contract):
    request_id: UUID
    expected_version: int = Field(ge=0)
    title: Text
    status: Literal["active", "suspended"]
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    max_forecast_age_hours: int = Field(ge=1, le=8760)
    max_cost_age_days: int = Field(ge=0, le=3650)
    dimensions: list[DimensionPolicy] = Field(min_length=6, max_length=6)
    reason: Text

    @model_validator(mode="after")
    def complete(self) -> Self:
        if {d.dimension for d in self.dimensions} != set(CATALOG):
            raise ValueError("须明确六个维度，不能重复或删除缺数据维度")
        if sum((d.weight for d in self.dimensions), Decimal(0)) != 1:
            raise ValueError("六维权重之和须为1，缺失项不重新分配权重")
        if self.valid_until <= self.valid_from:
            raise ValueError("政策有效期须为正")
        return self


def latest(c: Connection, tenant: UUID) -> Any:
    t = tables.portfolio_health_policies
    return (
        c.execute(select(t).where(t.c.tenant_id == tenant).order_by(t.c.version.desc()).limit(1))
        .mappings()
        .one_or_none()
    )


def evaluate(metrics: dict[str, dict[str, Any]], policy: HealthPolicy | None) -> dict[str, Any]:
    dimensions = []
    configured: dict[str, DimensionPolicy] = (
        {d.dimension: d for d in policy.dimensions} if policy else {}
    )
    with localcontext() as ctx:
        ctx.prec = 48
        total = Decimal(0)
        for key, definition in CATALOG.items():
            source = metrics[key]
            rule = configured.get(key)
            value = source.get("value")
            score = None
            status = "unknown"
            if rule is not None and value is not None and not source["missing"]:
                number = Decimal(str(value))
                score = max(
                    Decimal(0),
                    min(
                        Decimal(100),
                        100
                        * (rule.alert_at_or_above - number)
                        / (rule.alert_at_or_above - rule.clear_at_or_below),
                    ),
                )
                status = (
                    "alert"
                    if number >= rule.alert_at_or_above
                    else "clear"
                    if number <= rule.clear_at_or_below
                    else "attention"
                )
                total += rule.weight * score
            dimensions.append(
                {
                    "dimension": key,
                    **definition,
                    **source,
                    "score": str(score) if score is not None else None,
                    "status": status,
                    "rule": rule.model_dump(mode="json") if rule else None,
                }
            )
        unknown = sum(v["status"] == "unknown" for v in dimensions)
        return {
            "dimensions": dimensions,
            "score": None if unknown else str(total),
            "unknown_dimensions": unknown,
            "alert_dimensions": sum(v["status"] == "alert" for v in dimensions),
            "formula": FORMULA,
        }


class HealthPolicyService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, context: AuthContext, before: int | None = None) -> dict[str, Any]:
        _role(context, Action.PROJECT_VIEW)
        with self.engine.connect() as c:
            t = tables.portfolio_health_policies
            query = select(t).where(t.c.tenant_id == context.tenant.id)
            if before is not None:
                query = query.where(t.c.version < before)
            records = list(c.execute(query.order_by(t.c.version.desc()).limit(21)).mappings())
            current = latest(c, context.tenant.id)
            return {
                "current": _plain(current) if current else None,
                "items": [_plain(v) for v in records[:20]],
                "next": records[19]["version"] if len(records) > 20 else None,
                "can_manage": is_allowed(context.user.role, Action.TENANT_MANAGE),
                "catalog": CATALOG,
                "formula": FORMULA,
            }

    def publish(self, context: AuthContext, command: HealthPolicy) -> dict[str, Any]:
        _role(context, Action.TENANT_MANAGE)
        with self.engine.begin() as c:
            c.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"portfolio-health:{context.tenant.id}"},
            )
            t = tables.portfolio_health_policies
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
                if prior["request_digest"] != signature:
                    raise ProductWorkError("请求编号已用于另一健康政策")
                return _plain(prior)
            previous = latest(c, context.tenant.id)
            version = previous["version"] if previous else 0
            if version != command.expected_version:
                raise ProductWorkError("健康政策已变化，请核对最新版本")
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            value = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        version=version + 1,
                        body=command.model_dump(mode="json"),
                        formula_version="health.v1",
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=signature,
                        created_at=now,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            return _plain(value)
