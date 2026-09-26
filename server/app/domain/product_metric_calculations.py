"""Versioned, reproducible deltas between actual measurements and declared targets."""

from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, TypeAdapter, ValidationError, model_validator
from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Digest, Key, Quantity, Text
from app.db.schema import tables
from app.domain.product_result_feedback import ResultRead, prepared, project_access, target
from app.domain.product_workspace import ProductWorkError, _emit, _plain, digest
from app.domain.project_write_lock import lock_project_write_scope

VERSION = "actual-definition-delta.v1"
NUMBER = TypeAdapter(Quantity)


class MetricScope(Contract):
    definition_id: UUID
    project_id: UUID
    test_run_id: UUID


class MetricContext(MetricScope):
    before_version: int | None = Field(default=None, ge=1)


class MetricMapping(Contract):
    item_key: Key
    metric_index: int = Field(ge=0, le=99)
    metric_name: str = Field(min_length=1, max_length=128)
    comparability: Literal["same_conditions", "not_comparable", "unknown"]
    basis: Text


class MetricPreview(MetricScope):
    expected_source_digest: Digest
    mappings: tuple[MetricMapping, ...] = Field(min_length=1, max_length=20)
    reason: Text

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len({v.item_key for v in self.mappings}) != len(self.mappings):
            raise ValueError("每个规格条目在同一口径中只对应一个实际指标")
        return self


class MetricSave(MetricPreview):
    request_id: UUID
    expected_version: int = Field(ge=0)
    expected_preview_digest: Digest


class MetricReplay(Contract):
    calculation_id: UUID


def source(
    c: Connection, context: AuthContext, space: UUID, scope: MetricScope, *, write: bool = False
) -> dict[str, Any]:
    return prepared(
        c,
        context,
        space,
        ResultRead(
            definition_id=scope.definition_id,
            project_id=scope.project_id,
            source_kind="test_run",
            source_id=scope.test_run_id,
        ),
        write=write,
    )


def number(value: Any) -> Decimal | None:
    if (
        value is None
        or isinstance(value, bool)
        or not isinstance(value, (str, int, float, Decimal))
    ):
        return None
    try:
        return NUMBER.validate_python(str(value).strip())
    except ValidationError:
        return None


def calculate(
    version: str, original: dict[str, Any], mappings: tuple[MetricMapping, ...]
) -> dict[str, Any]:
    if version != VERSION:
        raise ProductWorkError("原计算版本当前不可执行，保留原结果，不静默改用其他公式")
    actual = original["source"]
    run = actual["record"]
    specs = {v["item_key"]: v for v in original["definition"]["content"]["items"]}
    inherited = {v["item_key"] for v in actual["inherited_specifications"]}
    results = []
    for mapping in mappings:
        specification = specs.get(mapping.item_key)
        metric = (
            run["metrics"][mapping.metric_index]
            if mapping.metric_index < len(run["metrics"])
            else None
        )
        reasons = []
        measured = number(metric.get("value")) if isinstance(metric, dict) else None
        expected = number(specification.get("target_value")) if specification else None
        if specification is None or metric is None:
            reasons.append("原规格或实际指标已缺失")
        if metric is not None and metric.get("name") != mapping.metric_name:
            reasons.append("该位置的指标名称已变化，须重新对应")
        if mapping.item_key not in inherited:
            reasons.append("测试规格/需求未直接继承本定义条目，暂不作数值比较")
        if mapping.comparability != "same_conditions":
            reasons.append("测试条件、方法或适用范围尚未确认为可比")
        if (
            not specification
            or not metric
            or not specification.get("unit")
            or metric.get("unit") != specification["unit"]
        ):
            reasons.append("原单位缺失或不完全一致，未自动换算")
        if measured is None or expected is None:
            reasons.append("原实测值或目标不是可确定的十进制数值，未解析范围/文字或补零")
        if run["status"] == "aborted":
            reasons.append("测试已中止，不能作为完成测量比较")
        if not actual.get("sample_configuration"):
            reasons.append("未固定实际样机配置，产品适用范围待核对")
        if not actual["evidence"] or actual["missing_evidence"]:
            reasons.append("实际报告依据缺失或不可读取")
        if not original["inheritance_current"]:
            reasons.append("当前项目已不再继承此定义")
        delta = relative = None
        if not reasons and measured is not None and expected is not None:
            with localcontext() as ctx:
                ctx.prec = 64
                delta = format(measured - expected, "f")
                if expected != 0:
                    relative = format(
                        ((measured - expected) / abs(expected) * 100).quantize(
                            Decimal("0.000001"), rounding=ROUND_HALF_UP
                        ),
                        "f",
                    )
        results.append(
            {
                "item_key": mapping.item_key,
                "specification": specification,
                "metric_index": mapping.metric_index,
                "metric": metric,
                "mapping": mapping.model_dump(mode="json"),
                "state": "unknown" if reasons else "calculated",
                "reasons": reasons,
                "actual_value": format(measured, "f") if measured is not None else None,
                "target_value": format(expected, "f") if expected is not None else None,
                "delta": delta,
                "relative_delta_percent": relative,
                "relative_unknown_reason": "目标为零，变化率未定义"
                if expected == 0 and not reasons
                else None,
            }
        )
    return {
        "formula_version": VERSION,
        "items": results,
        "calculated_count": sum(v["state"] == "calculated" for v in results),
        "unknown_count": sum(v["state"] == "unknown" for v in results),
        "formula": "差额=实测值−原定义目标；变化率=差额÷|原目标|×100%，目标为零时变化率未知。",
        "rounding": (
            "实测与目标使用固定十进制（最多24位、8位小数）；"
            "差额不额外取整，变化率四舍五入至6位小数。"
        ),
        "interpretation": (
            "仅比较明确对应的一次测量与声明目标，差额不判定通过/失败，"
            "不改写原测试结论，不推定因果或整机表现。"
        ),
    }


def preview(
    c: Connection, context: AuthContext, space: UUID, command: MetricPreview, *, write: bool = False
) -> dict[str, Any]:
    original = source(c, context, space, command, write=write)
    if original["digest"] != command.expected_source_digest:
        raise ProductWorkError("原测试、定义或依据已变化，请读取当前资料后重新核对")
    config = {
        "formula_version": VERSION,
        "mappings": [v.model_dump(mode="json") for v in command.mappings],
    }
    body = {
        "source": original,
        "configuration": config,
        "reason": command.reason,
        "result": calculate(VERSION, original, command.mappings),
    }
    return {**body, "digest": digest(body)}


def conditions(context: AuthContext, scope: MetricScope) -> tuple[Any, ...]:
    t = tables.product_metric_calculations
    return (
        t.c.tenant_id == context.tenant.id,
        t.c.definition_id == scope.definition_id,
        t.c.project_id == scope.project_id,
        t.c.test_run_id == scope.test_run_id,
    )


class ProductMetricCalculationService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def context(self, context: AuthContext, space: UUID, query: MetricContext) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            original = source(c, context, space, query)
            writable = True
            try:
                target(c, context, space, query.definition_id, write=True)
            except (ValueError, PermissionError):
                writable = False
            t = tables.product_metric_calculations
            version = c.execute(
                select(func.coalesce(func.max(t.c.version), 0)).where(*conditions(context, query))
            ).scalar_one()
            q = select(t).where(*conditions(context, query))
            if query.before_version:
                q = q.where(t.c.version < query.before_version)
            values = c.execute(q.order_by(t.c.version.desc()).limit(21)).mappings().all()
            return {
                "source": original,
                "version": version,
                "can_save": writable and original["inheritance_current"],
                "items": [
                    {**_plain(v), "sources_current": v["source_digest"] == original["digest"]}
                    for v in values[:20]
                ],
                "next_before_version": values[19]["version"] if len(values) > 20 else None,
            }

    def preview(self, context: AuthContext, space: UUID, command: MetricPreview) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return preview(c, context, space, command)

    def save(self, context: AuthContext, space: UUID, command: MetricSave) -> dict[str, Any]:
        with self.engine.begin() as c:
            project_access(c, context, command.project_id)
            if not lock_project_write_scope(
                c, tenant_id=context.tenant.id, project_id=command.project_id
            ):
                raise ProductWorkError("原项目不可用")
            target(c, context, space, command.definition_id, write=True)
            t = tables.product_metric_calculations
            signature = digest({"space": str(space), "command": command.model_dump(mode="json")})
            old = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.actor_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old:
                if old["request_digest"] != signature:
                    raise ProductWorkError("同一请求不能改写计算")
                return _plain(old)
            current = preview(c, context, space, command, write=True)
            previous = (
                c.execute(
                    select(t)
                    .where(*conditions(context, command))
                    .order_by(t.c.version.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if (previous["version"] if previous else 0) != command.expected_version or current[
                "digest"
            ] != command.expected_preview_digest:
                raise ProductWorkError("计算版本或预览已变化，请重新核对")
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        market_space_id=space,
                        project_id=command.project_id,
                        definition_id=command.definition_id,
                        test_run_id=command.test_run_id,
                        version=command.expected_version + 1,
                        previous_id=previous["id"] if previous else None,
                        formula_version=VERSION,
                        configuration=current["configuration"],
                        source_snapshot=current["source"],
                        source_digest=current["source"]["digest"],
                        result=current["result"],
                        preview_digest=current["digest"],
                        reason=command.reason,
                        actor_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=signature,
                        created_at=c.execute(select(func.clock_timestamp())).scalar_one(),
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            _emit(
                c,
                context,
                space,
                "product_metric_calculation",
                "recorded",
                {"id": row["id"], "version": row["version"], "definition_id": row["definition_id"]},
            )
            return _plain(row)

    def replay(self, context: AuthContext, space: UUID, query: MetricReplay) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            t = tables.product_metric_calculations
            row = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.market_space_id == space,
                        t.c.id == query.calculation_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProductWorkError("原计算不存在或不可读取")
            target(c, context, space, row["definition_id"])
            project_access(c, context, row["project_id"])
            mappings = tuple(
                MetricMapping.model_validate(v) for v in row["configuration"]["mappings"]
            )
            result = calculate(row["formula_version"], row["source_snapshot"], mappings)
            try:
                current = source(
                    c,
                    context,
                    space,
                    MetricScope(
                        definition_id=row["definition_id"],
                        project_id=row["project_id"],
                        test_run_id=row["test_run_id"],
                    ),
                )
                unchanged = current["digest"] == row["source_digest"]
            except (ValueError, LookupError):
                unchanged = False
            return {
                "record": _plain(row),
                "replayed_result": result,
                "matches_saved": result == row["result"],
                "sources_current": unchanged,
            }
