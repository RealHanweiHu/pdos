"""Versioned nine-section strategy, budget comparisons and explicit publication."""

from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import ApprovalRef, Contract, Key, Quantity, SourceRef, Text
from app.contracts.object_operations import CommandPrecondition
from app.contracts.product_records import FactStatement, ProductStrategy, StrategyCanvas
from app.db.schema import tables
from app.domain.market_analysis import _fact
from app.domain.product_evidence import evidence_quality, resolve_evidence
from app.domain.product_workspace import (
    Input,
    ProductWorkAccessError,
    ProductWorkError,
    _emit,
    _line,
    _line_filter,
    _member,
    _plain,
    _precondition,
    _record,
    _role,
    _scope_ref,
    _space,
    digest,
)

COST_INTERPRETATION = (
    "模块每台目标成本之和；NRE为一次性预算，不计入单台目标。预算、售价目标及周期均不是实际结果。"
)


class BudgetValue(Contract):
    amount: Quantity | None = Field(ge=0)
    basis: FactStatement


class CostModule(Contract):
    key: Key
    name: Text
    target: BudgetValue


class RouteComparison(Contract):
    solution_id: UUID
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    price_target: BudgetValue
    nre_budget: BudgetValue
    id_cycle_days: BudgetValue
    modules: tuple[CostModule, ...] = Field(default=(), max_length=100)
    scope: FactStatement
    quality: FactStatement
    supply: FactStatement
    manufacturing: FactStatement
    resources: FactStatement
    trade_off: FactStatement

    @model_validator(mode="after")
    def unique_modules(self) -> Self:
        if len({module.key for module in self.modules}) != len(self.modules):
            raise ValueError("同一路线不能重复计算同一模块的目标成本")
        return self


class ConstraintDisposition(Contract):
    outcome: Literal["accepted", "deferred", "not_applicable"]
    reason: Text
    sources: tuple[SourceRef, ...] = Field(default=(), max_length=20)


class ProfessionalConstraint(Contract):
    id: UUID
    discipline: Key
    statement: FactStatement
    work_item_id: UUID | None = None
    disposition: ConstraintDisposition | None = None


class StrategyContent(Contract):
    title: Text
    owner_user_id: UUID
    canvas: StrategyCanvas
    route_comparisons: tuple[RouteComparison, ...] = Field(default=(), max_length=30)
    selected_solution_id: UUID | None = None
    professional_constraints: tuple[ProfessionalConstraint, ...] = Field(default=(), max_length=100)
    unknowns: tuple[Text, ...] = Field(default=(), max_length=100)
    decision_reason: Text

    @model_validator(mode="after")
    def identities(self) -> Self:
        ids = {route.solution_id for route in self.route_comparisons}
        if len(ids) != len(self.route_comparisons):
            raise ValueError("比较路线编号不能重复")
        if self.selected_solution_id is not None and self.selected_solution_id not in ids:
            raise ValueError("选定路线须属于已比较方案")
        if len({item.id for item in self.professional_constraints}) != len(
            self.professional_constraints
        ):
            raise ValueError("专业约束编号不能重复")
        facts = list(self.canvas.model_dump().values())
        for route in self.route_comparisons:
            facts += [
                getattr(route, key).model_dump()
                for key in ("scope", "quality", "supply", "manufacturing", "resources", "trade_off")
            ]
            facts += [
                value.basis.model_dump()
                for value in (
                    route.price_target,
                    route.nre_budget,
                    route.id_cycle_days,
                    *(module.target for module in route.modules),
                )
            ]
        facts += [item.statement.model_dump() for item in self.professional_constraints]
        if any(fact.get("approval") is not None for fact in facts):
            raise ValueError("策略内容不接受客户端提供的批准引用")
        return self


class StrategyDraft(Input):
    request_id: UUID
    opportunity_id: UUID
    supersedes_id: UUID | None = None
    content: StrategyContent


class StrategyEdit(CommandPrecondition):
    content: StrategyContent
    reason: Text


class StrategyAction(CommandPrecondition):
    action: Literal["submit", "return", "publish"]
    reason: Text


def budget_summary(routes: tuple[RouteComparison, ...]) -> list[dict[str, Any]]:
    result = []
    for route in routes:
        with localcontext() as context:
            context.prec = 64
            known = sum(
                (
                    module.target.amount
                    for module in route.modules
                    if module.target.amount is not None
                ),
                Decimal(0),
            )
        missing = [module.key for module in route.modules if module.target.amount is None]
        result.append(
            {
                "solution_id": str(route.solution_id),
                "currency": route.currency,
                "known_subtotal": str(known),
                "target_unit_cost": str(known) if route.modules and not missing else None,
                "unknown_modules": missing,
                "modules_missing": not route.modules,
                "policy_version": "module-target-sum-v1",
                "interpretation": COST_INTERPRETATION,
            }
        )
    return result


def _facts(
    connection: Connection,
    context: AuthContext,
    space_id: UUID,
    line_id: UUID | None,
    content: StrategyContent,
    opportunity: Any,
) -> dict[str, Any]:
    _member(connection, context, space_id, content.owner_user_id, line_id=line_id)
    solutions = {item["id"] for item in opportunity["solutions"]}
    if any(str(route.solution_id) not in solutions for route in content.route_comparisons):
        raise ProductWorkError("比较路线必须来自所引用机会版本的候选方案")
    value = content.model_dump(mode="json")
    for key in StrategyCanvas.model_fields:
        value["canvas"][key] = _fact(connection, context, getattr(content.canvas, key))
    for index, route in enumerate(content.route_comparisons):
        target = value["route_comparisons"][index]
        for key in ("scope", "quality", "supply", "manufacturing", "resources", "trade_off"):
            target[key] = _fact(connection, context, getattr(route, key))
        for key in ("price_target", "nre_budget", "id_cycle_days"):
            target[key]["basis"] = _fact(connection, context, getattr(route, key).basis)
        for module_index, module in enumerate(route.modules):
            target["modules"][module_index]["target"]["basis"] = _fact(
                connection, context, module.target.basis
            )
    for index, constraint in enumerate(content.professional_constraints):
        value["professional_constraints"][index]["statement"] = _fact(
            connection, context, constraint.statement
        )
        if constraint.disposition:
            value["professional_constraints"][index]["disposition"]["sources"] = resolve_evidence(
                connection, context, constraint.disposition.sources
            )
        if constraint.work_item_id:
            work = (
                connection.execute(
                    select(tables.scoped_work_items).where(
                        tables.scoped_work_items.c.tenant_id == context.tenant.id,
                        tables.scoped_work_items.c.market_space_id == space_id,
                        tables.scoped_work_items.c.id == constraint.work_item_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if (
                work is None
                or work["product_line_id"] != line_id
                or work["action_type"] not in {"discipline_review", "constraint_review"}
            ):
                raise ProductWorkError("专业约束须关联同一范围的专业或约束评审工作")
    value["owner_user_id"] = content.owner_user_id
    value["selected_solution_id"] = content.selected_solution_id
    value["cost_summary"] = budget_summary(content.route_comparisons)
    return value


def _content(row: Any) -> StrategyContent:
    return StrategyContent.model_validate({key: row[key] for key in StrategyContent.model_fields})


def publication_readiness(
    connection: Connection, context: AuthContext, row: Any, opportunity: Any
) -> list[str]:
    issues = []
    routes = row["route_comparisons"]
    if len(routes) < 3:
        issues.append("至少比较三个候选方案")
    ids = {route["solution_id"] for route in routes}
    paths = {solution["approach"] for solution in opportunity["solutions"] if solution["id"] in ids}
    for key, label in (
        ("new_development", "新开发"),
        ("platform_reuse", "平台复用"),
        ("upgrade", "升级"),
    ):
        if key not in paths:
            issues.append(f"缺少{label}路线比较")
    if row["selected_solution_id"] is None:
        issues.append("尚未选定开发路线；暂缓原因可保留在草稿")
    for route in routes:
        if not route["modules"]:
            issues.append("每条比较路线须分解子系统或模块目标成本，未知成本可明示")
    disciplines = {item["discipline"].lower() for item in row["professional_constraints"]}
    for discipline in ("dqe", "sqe", "ie"):
        if discipline not in disciplines:
            issues.append(f"尚未记录{discipline.upper()}约束或明确适用性处置")
    for constraint in row["professional_constraints"]:
        if not constraint["work_item_id"] and not constraint["disposition"]:
            issues.append(f"专业约束 {constraint['discipline']} 尚无评审任务或明确处置")
        elif constraint["work_item_id"] and not constraint["disposition"]:
            state = connection.execute(
                select(tables.scoped_work_items.c.state).where(
                    tables.scoped_work_items.c.tenant_id == context.tenant.id,
                    tables.scoped_work_items.c.id == UUID(constraint["work_item_id"]),
                )
            ).scalar_one()
            if state == "cancelled":
                issues.append(
                    f"专业约束 {constraint['discipline']} 关联工作已取消，须重新安排或明确处置"
                )
    return list(dict.fromkeys(issues))


def _manager(
    connection: Connection, context: AuthContext, space_id: UUID, line_id: UUID | None
) -> bool:
    try:
        _role(context, Action.PRODUCT_WORK_MANAGE)
        _space(connection, context, space_id, access="manager")
        _line(connection, context, space_id, line_id, access="manager")
        return True
    except ProductWorkAccessError:
        return False


def _strategy(
    connection: Connection, context: AuthContext, row: Any, opportunity: Any
) -> dict[str, Any]:
    constraints = [item["statement"] for item in row["professional_constraints"]]
    refs = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "sources":
                    refs.extend(child)
                else:
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect({key: row[key] for key in ("canvas", "route_comparisons", "professional_constraints")})
    contract = ProductStrategy(
        id=row["id"],
        tenant_id=row["tenant_id"],
        scope=_scope_ref(row),
        version=row["version"],
        owner_user_id=row["owner_user_id"],
        sources=tuple({ref["ref_id"]: ref for ref in refs}.values()),
        opportunity_id=row["opportunity_id"],
        selected_solution_id=row["selected_solution_id"],
        canvas=row["canvas"],
        compared_solution_ids=tuple(route["solution_id"] for route in row["route_comparisons"]),
        professional_constraints=tuple(constraints),
        state=row["state"],
        approval=row["approval"],
        unknowns=tuple(row["unknowns"]),
    )
    return {
        **_record(row),
        "contract": contract.model_dump(mode="json"),
        "opportunity_series_id": str(opportunity["series_id"]),
        "opportunity_title": opportunity["title"],
        "opportunity_version": opportunity["version"],
        "solutions": opportunity["solutions"],
        "publication_blockers": publication_readiness(connection, context, row, opportunity),
        "can_publish": _manager(
            connection, context, row["market_space_id"], row["product_line_id"]
        ),
        "source_warnings": evidence_quality(connection, context, refs),
    }


class ProductStrategyService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list(self, context: AuthContext, space_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _space(connection, context, space_id)
            table = tables.product_strategies
            rows = list(
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        _line_filter(table, context),
                    )
                    .order_by(table.c.updated_at.desc())
                    .limit(100)
                ).mappings()
            )
            items = []
            for row in rows:
                opportunity = self._opportunity(
                    connection, context, space_id, row["opportunity_id"]
                )
                item = _strategy(connection, context, row, opportunity)
                item["has_successor"] = (
                    connection.execute(
                        select(table.c.id).where(
                            table.c.tenant_id == context.tenant.id,
                            table.c.supersedes_id == row["id"],
                        )
                    ).first()
                    is not None
                )
                items.append(item)
            return {"items": items}

    def detail(self, context: AuthContext, space_id: UUID, strategy_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _space(connection, context, space_id)
            table = tables.product_strategies
            row = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        table.c.id == strategy_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProductWorkAccessError("策略不存在或不可访问")
            _line(connection, context, space_id, row["product_line_id"])
            opportunity = self._opportunity(connection, context, space_id, row["opportunity_id"])
            item = _strategy(connection, context, row, opportunity)
            item["has_successor"] = (
                connection.execute(
                    select(table.c.id).where(
                        table.c.tenant_id == context.tenant.id, table.c.supersedes_id == row["id"]
                    )
                ).first()
                is not None
            )
            return item

    def _opportunity(
        self, connection: Connection, context: AuthContext, space_id: UUID, opportunity_id: UUID
    ) -> Any:
        row = (
            connection.execute(
                select(tables.opportunities).where(
                    tables.opportunities.c.tenant_id == context.tenant.id,
                    tables.opportunities.c.market_space_id == space_id,
                    tables.opportunities.c.id == opportunity_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ProductWorkAccessError("机会不存在或不可访问")
        _line(connection, context, space_id, row["product_line_id"])
        return row

    def create(self, context: AuthContext, space_id: UUID, draft: StrategyDraft) -> dict[str, Any]:
        _role(context, Action.PRODUCT_WORK_CONTRIBUTE)
        with self.engine.begin() as connection:
            _space(connection, context, space_id, access="contributor", lock=True)
            opportunity = self._opportunity(connection, context, space_id, draft.opportunity_id)
            _line(
                connection,
                context,
                space_id,
                opportunity["product_line_id"],
                access="contributor",
                writable=True,
            )
            table = tables.product_strategies
            fingerprint = digest(draft.model_dump(mode="json"))
            existing = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        table.c.created_by_user_id == context.user.id,
                        table.c.request_id == draft.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing:
                if existing["request_digest"] != fingerprint:
                    raise ProductWorkError("同一请求编号不能用于不同策略")
                return _strategy(connection, context, existing, opportunity)
            if opportunity["state"] == "closed":
                raise ProductWorkError("已关闭机会不能新建开发策略")
            node_id = uuid4()
            series_id, revision = node_id, 1
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
                if previous is None or previous["state"] != "published":
                    raise ProductWorkError("新修订须基于已发布策略")
                prior_opportunity = self._opportunity(
                    connection, context, space_id, previous["opportunity_id"]
                )
                if prior_opportunity["series_id"] != opportunity["series_id"]:
                    raise ProductWorkError("策略修订须来自同一机会系列")
                if connection.execute(
                    select(table.c.id).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.supersedes_id == previous["id"],
                    )
                ).first():
                    raise ProductWorkError("已存在后续策略修订，请打开该修订")
                series_id, revision = previous["series_id"], previous["revision_number"] + 1
            values = _facts(
                connection,
                context,
                space_id,
                opportunity["product_line_id"],
                draft.content,
                opportunity,
            )
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        **values,
                        id=node_id,
                        tenant_id=context.tenant.id,
                        market_space_id=space_id,
                        product_line_id=opportunity["product_line_id"],
                        opportunity_id=opportunity["id"],
                        created_by_user_id=context.user.id,
                        series_id=series_id,
                        supersedes_id=draft.supersedes_id,
                        revision_number=revision,
                        request_id=draft.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            result = _strategy(connection, context, row, opportunity)
            _emit(connection, context, space_id, "product_strategy", "created", row)
            return result

    def change(
        self,
        context: AuthContext,
        space_id: UUID,
        strategy_id: UUID,
        command: StrategyEdit | StrategyAction,
    ) -> dict[str, Any]:
        _role(context, Action.PRODUCT_WORK_CONTRIBUTE)
        with self.engine.begin() as connection:
            _space(connection, context, space_id, access="contributor", lock=True)
            table = tables.product_strategies
            row = (
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        table.c.id == strategy_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProductWorkAccessError("策略不存在或不可访问")
            _line(
                connection,
                context,
                space_id,
                row["product_line_id"],
                access="contributor",
                writable=True,
            )
            manager = _manager(connection, context, space_id, row["product_line_id"])
            author = context.user.id in {row["owner_user_id"], row["created_by_user_id"]}
            if (
                isinstance(command, StrategyAction)
                and command.action in {"publish", "return"}
                and not manager
            ) or (not manager and not author):
                raise ProductWorkAccessError("当前用户不能办理此策略动作")
            opportunity = self._opportunity(connection, context, space_id, row["opportunity_id"])
            if not _precondition(connection, context, row, command):
                return _strategy(connection, context, row, opportunity)
            now = datetime.now(UTC)
            if isinstance(command, StrategyEdit):
                if row["state"] != "draft":
                    raise ProductWorkError("仅草稿可修改；审核中须先退回，发布后须创建新修订")
                values = _facts(
                    connection,
                    context,
                    space_id,
                    row["product_line_id"],
                    command.content,
                    opportunity,
                )
                action = "edited"
            else:
                action = command.action
                if row["state"] != ("draft" if action == "submit" else "in_review"):
                    raise ProductWorkError("策略当前状态不能执行此动作")
                if action == "return":
                    values = {"state": "draft"}
                else:
                    _facts(
                        connection,
                        context,
                        space_id,
                        row["product_line_id"],
                        _content(row),
                        opportunity,
                    )
                    blockers = publication_readiness(connection, context, row, opportunity)
                    if blockers:
                        raise ProductWorkError("；".join(blockers))
                    if action == "submit":
                        values = {"state": "in_review"}
                    else:
                        snapshot = _plain(
                            {
                                key: row[key]
                                for key in (
                                    "id",
                                    "tenant_id",
                                    "market_space_id",
                                    "product_line_id",
                                    "opportunity_id",
                                    "revision_number",
                                    "version",
                                    "cost_summary",
                                    *StrategyContent.model_fields,
                                )
                            }
                        )
                        approval = ApprovalRef(
                            approval_id=uuid4(),
                            payload_digest=digest(snapshot),
                            policy_version="human-strategy-publication-v1",
                            approved_by_user_id=context.user.id,
                            approved_at=now,
                        )
                        values = {
                            "state": "published",
                            "approval": approval.model_dump(mode="json"),
                            "published_snapshot": snapshot,
                        }
            updated = (
                connection.execute(
                    table.update()
                    .where(table.c.tenant_id == context.tenant.id, table.c.id == row["id"])
                    .values(**values, version=row["version"] + 1, updated_at=now)
                    .returning(table)
                )
                .mappings()
                .one()
            )
            result = _strategy(connection, context, updated, opportunity)
            _emit(
                connection,
                context,
                space_id,
                "product_strategy",
                action,
                updated,
                before=row,
                operation=command,
            )
            return result

    def history(self, context: AuthContext, space_id: UUID, strategy_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _space(connection, context, space_id)
            row = (
                connection.execute(
                    select(tables.product_strategies).where(
                        tables.product_strategies.c.tenant_id == context.tenant.id,
                        tables.product_strategies.c.market_space_id == space_id,
                        tables.product_strategies.c.id == strategy_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProductWorkAccessError("策略不存在或不可访问")
            _line(connection, context, space_id, row["product_line_id"])
            log = tables.audit_log
            records = connection.execute(
                select(
                    log.c.action,
                    log.c.actor_user_id,
                    log.c.timestamp,
                    log.c.context,
                    log.c.after_snapshot,
                )
                .where(
                    log.c.tenant_id == context.tenant.id,
                    log.c.entity_id == strategy_id,
                    log.c.action.like("product_strategy.%"),
                )
                .order_by(log.c.timestamp.desc(), log.c.id.desc())
                .limit(100)
            ).mappings()
            return {"items": [_plain(item) for item in records]}
