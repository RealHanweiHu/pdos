"""Human-authored, immutable pre-project plan candidates; no implicit task application."""

from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import (
    Contract,
    PlanCandidate,
    PlanDependency,
    PlanNode,
    Quantity,
    ScopeRef,
    SourceRef,
    Text,
)
from app.db.schema import tables
from app.domain.case_requirements import _case
from app.domain.case_reviews import review_basis
from app.domain.process_template_routing import ProfessionalRole
from app.domain.process_template_routing import resolve as resolve_routes
from app.domain.product_definitions import _row as definition_row
from app.domain.product_workspace import (
    Input,
    ProductWorkAccessError,
    ProductWorkError,
    _line,
    _member,
    _plain,
    _role,
    _space,
    digest,
)
from app.domain.project_templates import ProjectTemplateSelection, catalog, compile_selection

DISCIPLINES = {
    "product_management",
    "industrial_design",
    "mechanical",
    "hardware",
    "firmware",
    "design_quality",
    "supplier_quality",
    "industrial_engineering",
}


class PlanSource(Contract):
    kind: Literal["opportunity", "product_definition", "development_case"]
    id: UUID


class IndustrialDesignPlan(Contract):
    design_source: Text | None = None
    scope: Text | None = None
    investment_hours: Quantity | None = Field(default=None, ge=0)
    budget: Quantity | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    review_rounds: int | None = Field(default=None, ge=1, le=100)
    customer_wait_days: int | None = Field(default=None, ge=0, le=3650)
    buffer_days: int | None = Field(default=None, ge=0, le=3650)
    freeze_node_key: str | None = None
    estimate_basis: Text | None = None

    @model_validator(mode="after")
    def evidence(self) -> Self:
        if self.budget is not None and not self.currency:
            raise ValueError("预算须标明币种")
        if (
            any(
                value is not None
                for value in (
                    self.budget,
                    self.investment_hours,
                    self.review_rounds,
                    self.customer_wait_days,
                    self.buffer_days,
                )
            )
            and not self.estimate_basis
        ):
            raise ValueError("ID投入、轮次及等待估算须说明依据")
        return self


class PlanPreparation(Input):
    request_id: UUID
    source: PlanSource
    supersedes_id: UUID | None = None
    title: Text
    template: ProjectTemplateSelection
    nodes: tuple[PlanNode, ...] = Field(min_length=1, max_length=1000)
    dependencies: tuple[PlanDependency, ...] = Field(default=(), max_length=10000)
    routing_bindings: dict[ProfessionalRole, UUID] = Field(default_factory=dict, max_length=8)
    stage_assignments: dict[str, str]
    id_plan: IndustrialDesignPlan = Field(default_factory=IndustrialDesignPlan)
    revision_reason: Text


def _source(
    connection: Connection,
    context: AuthContext,
    space_id: UUID | None,
    source: PlanSource,
    *,
    write: bool = False,
) -> tuple[Any, dict[str, Any], ScopeRef]:
    if source.kind == "development_case":
        if space_id is not None:
            raise ProductWorkError("案例计划须从案例入口编制")
        _role(context, Action.DEVELOPMENT_CASE_EDIT if write else Action.DEVELOPMENT_CASE_VIEW)
        _role(context, Action.REQUIREMENT_VIEW)
        case = _case(connection, context, source.id, lock=write)
        return (
            case,
            review_basis(connection, context.tenant.id, case, lock=write),
            ScopeRef(kind="tenant", ref_id=context.tenant.id),
        )
    if space_id is None:
        raise ProductWorkAccessError("机会或定义计划须在所属市场空间编制")
    if write:
        _role(context, Action.PRODUCT_WORK_CONTRIBUTE)
    _space(connection, context, space_id, access="contributor" if write else "viewer", lock=write)
    if source.kind == "product_definition":
        row = definition_row(connection, context, space_id, source.id, write=write)
    else:
        table = tables.opportunities
        statement = select(table).where(
            table.c.tenant_id == context.tenant.id,
            table.c.market_space_id == space_id,
            table.c.id == source.id,
        )
        row = (
            connection.execute(statement.with_for_update() if write else statement)
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ProductWorkAccessError("机会不存在或不可访问")
        _line(
            connection,
            context,
            space_id,
            row["product_line_id"],
            access="contributor" if write else "viewer",
            writable=write,
        )
    return row, _plain(row), ScopeRef(kind=source.kind, ref_id=source.id)


def _source_selector(row: Any) -> PlanSource:
    if row["case_id"]:
        return PlanSource(kind="development_case", id=row["case_id"])
    if row["definition_id"]:
        return PlanSource(kind="product_definition", id=row["definition_id"])
    return PlanSource(kind="opportunity", id=row["opportunity_id"])


def _missing(plan: PlanCandidate, id_plan: IndustrialDesignPlan) -> list[dict[str, str]]:
    output = []
    for node in plan.nodes:
        pending = list(node.current_missing)
        if node.owner_user_id is None:
            pending.append("待指定负责人")
        if node.receiver_user_id is None:
            pending.append("待指定交付接收人")
        if node.effort_hours is None:
            pending.append("待估算工时")
        for reason in dict.fromkeys(pending):
            output.append({"node_key": node.node_key, "reason": reason})
    if any(node.discipline == "industrial_design" for node in plan.nodes):
        for key, label in (
            ("design_source", "ID设计来源"),
            ("scope", "ID工作范围"),
            ("investment_hours", "ID投入"),
            ("review_rounds", "ID评审轮次"),
            ("customer_wait_days", "客户等待"),
            ("buffer_days", "ID缓冲"),
            ("freeze_node_key", "ID冻结里程碑"),
        ):
            if getattr(id_plan, key) is None:
                output.append({"node_key": "ID", "reason": f"待明确{label}"})
    return output


def _record(connection: Connection, context: AuthContext, row: Any) -> dict[str, Any]:
    _, current, _ = _source(connection, context, row["market_space_id"], _source_selector(row))
    plan = PlanCandidate.model_validate(row["plan"])
    try:
        current_template = compile_selection(
            ProjectTemplateSelection.model_validate(row["template_selection"]),
            templates=catalog(connection=connection, tenant_id=context.tenant.id),
        )
        template_current = current_template["digest"] == row["template_snapshot"]["digest"]
    except ValueError:
        template_current = False
    missing = _missing(plan, IndustrialDesignPlan.model_validate(row["id_plan"]))
    template_tasks = {task["code"]: task for task in row["template_snapshot"]["tasks"]}
    for task in template_tasks.values():
        for predecessor in task["depends_on"]:
            if template_tasks[predecessor].get("hard_milestone") and not any(
                edge.predecessor == predecessor
                and edge.successor == task["code"]
                and edge.relation == "fs"
                and edge.lag >= 0
                for edge in plan.dependencies
            ):
                missing.append(
                    {
                        "node_key": task["code"],
                        "reason": f"模板硬前置{predecessor}尚未保留为完成后开始关系",
                    }
                )
    return {
        **candidate_snapshot(row),
        "payload_digest": digest(candidate_snapshot(row)),
        "source_is_current": digest(current) == row["source_digest"],
        "template_is_current": template_current,
        "missing": missing,
        "scheduling_status": "scenario_available"
        if connection.execute(
            select(tables.initial_plan_scenarios.c.id)
            .where(
                tables.initial_plan_scenarios.c.tenant_id == context.tenant.id,
                tables.initial_plan_scenarios.c.candidate_id == row["id"],
            )
            .limit(1)
        ).first()
        else "not_calculated",
        "application_status": "candidate_only",
    }


def candidate_snapshot(row: Any) -> dict[str, Any]:
    # Empty new metadata must not change digests of existing reviewed candidates.
    result: dict[str, Any] = _plain(row)
    if not result.get("routing_snapshot"):
        result.pop("routing_snapshot", None)
    return result


class InitialPlanCandidateService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def detail(self, context: AuthContext, candidate_id: UUID) -> dict[str, Any]:
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            t = tables.initial_plan_candidates
            candidate = (
                connection.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.id == candidate_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if candidate is None:
                raise ProductWorkAccessError("计划候选不存在或不可访问")
            # _record rechecks the original case / space / product-line permissions.
            record = _record(connection, context, candidate)
            source = _source_selector(candidate)
            successor = connection.execute(
                select(t.c.id).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.supersedes_id == candidate_id,
                )
            ).scalar_one_or_none()
            a = tables.initial_plan_applications
            application = (
                connection.execute(
                    select(a.c.project_id, a.c.baseline_id).where(
                        a.c.tenant_id == context.tenant.id,
                        a.c.candidate_id == candidate_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            result = {
                "candidate": record,
                "source": source.model_dump(mode="json"),
                "space_id": str(candidate["market_space_id"])
                if candidate["market_space_id"]
                else None,
                "successor_id": str(successor) if successor else None,
                "application": _plain(application) if application else None,
            }
        result["options"] = self.options(context, candidate["market_space_id"], source)
        return result

    def options(
        self, context: AuthContext, space_id: UUID | None, source: PlanSource
    ) -> dict[str, Any]:
        with self.engine.connect() as connection:
            row, _, _ = _source(connection, context, space_id, source)
            if space_id:
                query = (
                    select(tables.users.c.id, tables.users.c.display_name)
                    .join(
                        tables.market_space_members,
                        (tables.market_space_members.c.tenant_id == tables.users.c.tenant_id)
                        & (tables.market_space_members.c.user_id == tables.users.c.id),
                    )
                    .where(
                        tables.market_space_members.c.market_space_id == space_id,
                        tables.market_space_members.c.access.in_(("contributor", "manager")),
                        tables.users.c.tenant_id == context.tenant.id,
                        tables.users.c.is_active.is_(True),
                        tables.users.c.role.not_in(("supplier", "customer")),
                    )
                )
                if row["product_line_id"]:
                    query = query.where(
                        tables.users.c.id.in_(
                            select(tables.product_line_members.c.user_id).where(
                                tables.product_line_members.c.tenant_id == context.tenant.id,
                                tables.product_line_members.c.product_line_id
                                == row["product_line_id"],
                                tables.product_line_members.c.access.in_(
                                    ("contributor", "manager")
                                ),
                            )
                        )
                    )
            else:
                query = select(tables.users.c.id, tables.users.c.display_name).where(
                    tables.users.c.tenant_id == context.tenant.id,
                    tables.users.c.is_active.is_(True),
                    tables.users.c.role.not_in(("supplier", "customer")),
                )
            can_prepare = is_allowed(
                context.user.role,
                Action.DEVELOPMENT_CASE_EDIT
                if space_id is None
                else Action.PRODUCT_WORK_CONTRIBUTE,
            )
            if space_id and can_prepare:
                try:
                    _space(connection, context, space_id, access="contributor")
                    _line(
                        connection, context, space_id, row["product_line_id"], access="contributor"
                    )
                except ProductWorkAccessError:
                    can_prepare = False
            return {
                "can_prepare": can_prepare,
                "templates": catalog(connection=connection, tenant_id=context.tenant.id),
                "members": [_plain(member) for member in connection.execute(query).mappings()],
                "source_title": row["title"],
            }

    def list(
        self, context: AuthContext, space_id: UUID | None, source: PlanSource
    ) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _source(connection, context, space_id, source)
            table = tables.initial_plan_candidates
            column = {
                "opportunity": table.c.opportunity_id,
                "product_definition": table.c.definition_id,
                "development_case": table.c.case_id,
            }[source.kind]
            rows = list(
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        column == source.id,
                    )
                    .order_by(table.c.created_at.desc(), table.c.id)
                    .limit(101)
                ).mappings()
            )
            return {
                "items": [_record(connection, context, row) for row in rows[:100]],
                "has_more": len(rows) > 100,
            }

    def create(
        self, context: AuthContext, space_id: UUID | None, draft: PlanPreparation
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            source_row, snapshot, scope = _source(
                connection, context, space_id, draft.source, write=True
            )
            table = tables.initial_plan_candidates
            fingerprint = digest(
                draft.model_dump(
                    mode="json",
                    exclude={"routing_bindings"} if not draft.routing_bindings else set(),
                )
            )
            prior = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.created_by_user_id == context.user.id,
                        table.c.request_id == draft.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != fingerprint or prior["market_space_id"] != space_id:
                    raise ProductWorkError("同一请求不能用于不同计划内容或范围")
                return _record(connection, context, prior)
            previous = None
            if draft.supersedes_id:
                previous = (
                    connection.execute(
                        select(table)
                        .where(
                            table.c.tenant_id == context.tenant.id,
                            table.c.id == draft.supersedes_id,
                            table.c.market_space_id == space_id,
                        )
                        .with_for_update()
                    )
                    .mappings()
                    .one_or_none()
                )
                if previous is None or _source_selector(previous) != draft.source:
                    raise ProductWorkError("修订必须延续同一来源的计划")
                if connection.execute(
                    select(table.c.id).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.supersedes_id == previous["id"],
                    )
                ).first():
                    raise ProductWorkError("此计划已有新修订，请以最新版继续")
            template = compile_selection(
                draft.template,
                templates=catalog(connection=connection, tenant_id=context.tenant.id),
            )
            if draft.template.source_version_id is not None:
                raise ProductWorkError(
                    "此入口保存组织模板候选；项目模板采用记录在正式应用时另行核对"
                )
            keys = {node.node_key for node in draft.nodes}
            required = {task["code"] for task in template["tasks"]}
            if not required <= keys:
                raise ProductWorkError("计划须保留所选模板的全部任务；功能适用性通过模板配置处理")
            if set(draft.stage_assignments) != keys or set(draft.stage_assignments.values()) - {
                "concept",
                "planning",
                "design",
                "evt",
                "dvt",
                "pvt",
                "mp",
            }:
                raise ProductWorkError("每项任务须指定有效阶段")
            for task in template["tasks"]:
                if draft.stage_assignments[task["code"]] != task["stage"]:
                    raise ProductWorkError("模板任务阶段不可悄悄更改，请先修订组织模板")
            if any(node.discipline not in DISCIPLINES for node in draft.nodes):
                raise ProductWorkError("专业职责须使用明确的职责标识")
            routing = resolve_routes(template, draft.routing_bindings, draft.nodes)
            assigned = {
                person
                for node in draft.nodes
                for person in (node.owner_user_id, node.receiver_user_id)
                if person
            } | set(draft.routing_bindings.values())
            for user_id in assigned:
                if space_id:
                    _member(connection, context, space_id, user_id, source_row["product_line_id"])
                elif (
                    connection.execute(
                        select(tables.users.c.id).where(
                            tables.users.c.tenant_id == context.tenant.id,
                            tables.users.c.id == user_id,
                            tables.users.c.is_active.is_(True),
                            tables.users.c.role.not_in(("supplier", "customer")),
                        )
                    ).first()
                    is None
                ):
                    raise ProductWorkError("责任人与接收人须为有效内部用户")
            if (
                draft.id_plan.freeze_node_key is not None
                and draft.id_plan.freeze_node_key not in keys
            ):
                raise ProductWorkError("ID冻结目标须引用实际计划节点")
            candidate_id = uuid4()
            source_ref = SourceRef(
                tenant_id=context.tenant.id,
                kind=draft.source.kind,
                ref_id=draft.source.id,
                as_of=source_row["updated_at"]
                if "updated_at" in source_row
                else source_row["created_at"],
                digest=digest(snapshot),
            )
            try:
                plan = PlanCandidate(
                    id=candidate_id,
                    tenant_id=context.tenant.id,
                    scope=scope,
                    version=previous["version"] + 1 if previous else 1,
                    owner_user_id=context.user.id,
                    sources=(source_ref,),
                    template_version=f"{draft.template.template_id}.v{draft.template.version}",
                    nodes=draft.nodes,
                    dependencies=draft.dependencies,
                )
            except ValueError as error:
                raise ProductWorkError(
                    "计划节点编号重复、依赖引用缺失或存在循环，请修正后保存"
                ) from error
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=candidate_id,
                        tenant_id=context.tenant.id,
                        market_space_id=space_id,
                        product_line_id=source_row["product_line_id"] if space_id else None,
                        opportunity_id=draft.source.id
                        if draft.source.kind == "opportunity"
                        else None,
                        definition_id=draft.source.id
                        if draft.source.kind == "product_definition"
                        else None,
                        case_id=draft.source.id
                        if draft.source.kind == "development_case"
                        else None,
                        series_id=previous["series_id"] if previous else candidate_id,
                        supersedes_id=draft.supersedes_id,
                        version=plan.version,
                        title=draft.title,
                        template_selection=draft.template.model_dump(mode="json"),
                        template_snapshot=template,
                        source_snapshot=snapshot,
                        source_digest=digest(snapshot),
                        plan=plan.model_dump(mode="json"),
                        stage_assignments=draft.stage_assignments,
                        routing_snapshot=routing,
                        id_plan=draft.id_plan.model_dump(mode="json"),
                        revision_reason=draft.revision_reason,
                        created_by_user_id=context.user.id,
                        request_id=draft.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

            EventAuditWriter(
                connection, tenant_id=context.tenant.id, actor_user_id=context.user.id
            ).record(
                EventDraft(
                    event_id=f"initial-plan:{candidate_id}:prepared",
                    event_type="INITIAL_PLAN_PREPARED",
                    source="initial_plan_service",
                    entity_id=candidate_id,
                    payload={
                        "source_kind": draft.source.kind,
                        "source_id": str(draft.source.id),
                        "version": row["version"],
                        "candidate_digest": digest(plan.model_dump(mode="json")),
                    },
                ),
                AuditDraft(
                    action="initial_plan.prepared",
                    after_snapshot=_plain(row),
                    context={"reason": draft.revision_reason},
                ),
            )
            return _record(connection, context, row)
