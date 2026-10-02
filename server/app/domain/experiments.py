"""Pinned VUVF experiment plans, human approval and evidence-backed outcomes."""

from datetime import UTC, datetime
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import ApprovalRef, Contract, SourceRef, Text
from app.contracts.object_operations import CommandPrecondition
from app.contracts.product_records import Experiment
from app.db.schema import tables
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

PLAN_FIELDS = (
    "owner_user_id",
    "dimension",
    "hypothesis",
    "method",
    "sample_basis",
    "success_criterion",
    "falsification_criterion",
    "due_at",
    "sources",
)


class ExperimentPlan(Contract):
    owner_user_id: UUID
    dimension: Literal["value", "usability", "viability", "feasibility"]
    hypothesis: Text
    method: Text
    sample_basis: Text
    success_criterion: Text
    falsification_criterion: Text
    due_at: AwareDatetime | None = None
    sources: tuple[SourceRef, ...] = Field(default=(), max_length=30)


class ExperimentDraft(Input):
    request_id: UUID
    opportunity_id: UUID
    solution_id: UUID
    plan: ExperimentPlan


class ExperimentEdit(CommandPrecondition):
    plan: ExperimentPlan
    reason: Text


class ExperimentAction(CommandPrecondition):
    action: Literal["approve", "start", "conclude", "cancel"]
    reason: Text
    result: Literal["supported", "refuted", "inconclusive"] | None = None
    result_evidence: tuple[SourceRef, ...] = Field(default=(), max_length=30)

    @model_validator(mode="after")
    def result_is_conclusion(self) -> Self:
        if self.action == "conclude":
            if self.result is None:
                raise ValueError("实验结论须选择支持、证伪或不确定")
            if self.result in {"supported", "refuted"} and not self.result_evidence:
                raise ValueError("支持或证伪结论须引用实际结果证据")
        elif self.result is not None or self.result_evidence:
            raise ValueError("尚未结束的实验不能写入结果")
        return self


def plan_snapshot(row: Any) -> dict[str, Any]:
    return _plain(
        {
            key: row[key]
            for key in (
                "id",
                "tenant_id",
                "market_space_id",
                "product_line_id",
                "opportunity_id",
                "solution_id",
                *PLAN_FIELDS,
            )
        }
    )


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


def _experiment(connection: Connection, context: AuthContext, row: Any) -> dict[str, Any]:
    approval = None
    if row["approval_id"] is not None:
        record = (
            connection.execute(
                select(tables.experiment_approvals).where(
                    tables.experiment_approvals.c.tenant_id == context.tenant.id,
                    tables.experiment_approvals.c.experiment_id == row["id"],
                    tables.experiment_approvals.c.id == row["approval_id"],
                )
            )
            .mappings()
            .one()
        )
        approval = ApprovalRef(
            approval_id=record["id"],
            **{
                key: record[key]
                for key in (
                    "payload_digest",
                    "policy_version",
                    "approved_by_user_id",
                    "approved_at",
                )
            },
        )
    contract = Experiment(
        id=row["id"],
        tenant_id=row["tenant_id"],
        scope=_scope_ref(row),
        version=row["version"],
        owner_user_id=row["owner_user_id"],
        sources=tuple(row["sources"]),
        approval=approval,
        **{
            key: row[key]
            for key in (
                "opportunity_id",
                "solution_id",
                "dimension",
                "hypothesis",
                "method",
                "sample_basis",
                "success_criterion",
                "falsification_criterion",
                "due_at",
                "state",
                "result",
                "result_evidence",
                "result_explanation",
                "concluded_at",
                "cancellation_reason",
            )
        },
    )
    from app.domain.requirement_package_succession import links

    return {
        **_record(row),
        **contract.model_dump(mode="json"),
        "succession": links(
            connection, context.tenant.id, row["market_space_id"], row["id"], "experiment"
        ),
    }


def _plan_values(
    connection: Connection,
    context: AuthContext,
    space_id: UUID,
    line_id: UUID | None,
    plan: ExperimentPlan,
) -> dict[str, Any]:
    _member(connection, context, space_id, plan.owner_user_id, line_id=line_id)
    return {
        **plan.model_dump(exclude={"sources"}),
        "sources": resolve_evidence(connection, context, plan.sources),
    }


def create_experiment_in_connection(
    connection: Connection,
    context: AuthContext,
    space_id: UUID,
    draft: ExperimentDraft,
    *,
    source_finding_id: UUID | None = None,
    source_finding_position: int | None = None,
) -> dict[str, Any]:
    _role(context, Action.PRODUCT_WORK_CONTRIBUTE)
    _space(connection, context, space_id, access="contributor", lock=True)
    opportunity = (
        connection.execute(
            select(tables.opportunities).where(
                tables.opportunities.c.tenant_id == context.tenant.id,
                tables.opportunities.c.market_space_id == space_id,
                tables.opportunities.c.id == draft.opportunity_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if opportunity is None:
        raise ProductWorkAccessError("机会不存在或不可访问")
    _line(
        connection,
        context,
        space_id,
        opportunity["product_line_id"],
        access="contributor",
        writable=True,
    )
    table = tables.experiments
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
            raise ProductWorkError("同一请求编号不能用于不同实验")
        return _experiment(connection, context, existing)
    if (
        opportunity["state"] == "closed"
        or connection.execute(
            select(tables.opportunities.c.id).where(
                tables.opportunities.c.tenant_id == context.tenant.id,
                tables.opportunities.c.supersedes_id == opportunity["id"],
            )
        ).first()
    ):
        raise ProductWorkError("新实验须从未关闭机会的最新版本建立")
    if str(draft.solution_id) not in {item["id"] for item in opportunity["solutions"]}:
        raise ProductWorkError("所选方案不属于此机会版本")
    values = _plan_values(connection, context, space_id, opportunity["product_line_id"], draft.plan)
    row = (
        connection.execute(
            table.insert()
            .values(
                **values,
                id=uuid4(),
                tenant_id=context.tenant.id,
                market_space_id=space_id,
                product_line_id=opportunity["product_line_id"],
                opportunity_id=opportunity["id"],
                solution_id=draft.solution_id,
                created_by_user_id=context.user.id,
                request_id=draft.request_id,
                request_digest=fingerprint,
                source_finding_id=source_finding_id,
                source_finding_position=source_finding_position,
            )
            .returning(table)
        )
        .mappings()
        .one()
    )
    result = _experiment(connection, context, row)
    _emit(connection, context, space_id, "experiment", "created", row)
    return result


class ExperimentService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list(self, context: AuthContext, space_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _space(connection, context, space_id)
            table = tables.experiments
            rows = connection.execute(
                select(table)
                .where(
                    table.c.tenant_id == context.tenant.id,
                    table.c.market_space_id == space_id,
                    _line_filter(table, context),
                )
                .order_by(table.c.created_at.desc())
                .limit(200)
            ).mappings()
            items = []
            for row in rows:
                opportunity = (
                    connection.execute(
                        select(tables.opportunities).where(
                            tables.opportunities.c.tenant_id == context.tenant.id,
                            tables.opportunities.c.id == row["opportunity_id"],
                        )
                    )
                    .mappings()
                    .one()
                )
                item = _experiment(connection, context, row)
                item.update(
                    opportunity_title=opportunity["title"],
                    opportunity_version=opportunity["version"],
                    solution_title=next(
                        solution["title"]
                        for solution in opportunity["solutions"]
                        if solution["id"] == str(row["solution_id"])
                    ),
                    can_approve=_manager(connection, context, space_id, row["product_line_id"]),
                    source_warnings=evidence_quality(
                        connection, context, [*row["sources"], *row["result_evidence"]]
                    ),
                )
                items.append(item)
            return {"items": items}

    def detail(self, context: AuthContext, space_id: UUID, experiment_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _space(connection, context, space_id)
            row = (
                connection.execute(
                    select(tables.experiments).where(
                        tables.experiments.c.tenant_id == context.tenant.id,
                        tables.experiments.c.market_space_id == space_id,
                        tables.experiments.c.id == experiment_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProductWorkAccessError("实验不存在或不可访问")
            _line(connection, context, space_id, row["product_line_id"])
            opportunity = (
                connection.execute(
                    select(tables.opportunities).where(
                        tables.opportunities.c.tenant_id == context.tenant.id,
                        tables.opportunities.c.id == row["opportunity_id"],
                    )
                )
                .mappings()
                .one()
            )
            item = _experiment(connection, context, row)
            item.update(
                opportunity_title=opportunity["title"],
                opportunity_version=opportunity["version"],
                solution_title=next(
                    solution["title"]
                    for solution in opportunity["solutions"]
                    if solution["id"] == str(row["solution_id"])
                ),
                can_approve=_manager(connection, context, space_id, row["product_line_id"]),
                source_warnings=evidence_quality(
                    connection, context, [*row["sources"], *row["result_evidence"]]
                ),
            )
            return item

    def create(
        self, context: AuthContext, space_id: UUID, draft: ExperimentDraft
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            return create_experiment_in_connection(connection, context, space_id, draft)

    def change(
        self,
        context: AuthContext,
        space_id: UUID,
        experiment_id: UUID,
        command: ExperimentEdit | ExperimentAction,
    ) -> dict[str, Any]:
        _role(context, Action.PRODUCT_WORK_CONTRIBUTE)
        with self.engine.begin() as connection:
            _space(connection, context, space_id, access="contributor", lock=True)
            table = tables.experiments
            row = (
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        table.c.id == experiment_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProductWorkAccessError("实验不存在或不可访问")
            _line(
                connection,
                context,
                space_id,
                row["product_line_id"],
                access="contributor",
                writable=True,
            )
            manager = _manager(connection, context, space_id, row["product_line_id"])
            owner = row["owner_user_id"] == context.user.id
            if isinstance(command, ExperimentEdit):
                allowed = manager or owner or row["created_by_user_id"] == context.user.id
            else:
                allowed = (
                    manager
                    if command.action == "approve"
                    else owner
                    if command.action in {"start", "conclude"}
                    else owner or manager
                )
            if not allowed:
                raise ProductWorkAccessError("此动作须由实验负责人或有权限的管理者办理")
            if not _precondition(connection, context, row, command):
                return _experiment(connection, context, row)
            now = datetime.now(UTC)
            if isinstance(command, ExperimentEdit):
                if row["state"] != "draft":
                    raise ProductWorkError(
                        "批准后的实验计划已固定；需改变方法或阈值时取消并另建实验"
                    )
                values = _plan_values(
                    connection, context, space_id, row["product_line_id"], command.plan
                )
                action = "edited"
            else:
                action = command.action
                required = {"approve": "draft", "start": "approved", "conclude": "running"}
                if row["state"] in {"concluded", "cancelled"} or (
                    action in required and row["state"] != required[action]
                ):
                    raise ProductWorkError("实验当前状态不能执行此动作")
                values = {}
                if action == "approve":
                    _member(
                        connection,
                        context,
                        space_id,
                        row["owner_user_id"],
                        line_id=row["product_line_id"],
                    )
                    resolve_evidence(
                        connection,
                        context,
                        tuple(SourceRef.model_validate(ref) for ref in row["sources"]),
                    )
                    snapshot = plan_snapshot(row)
                    approval_id = uuid4()
                    connection.execute(
                        tables.experiment_approvals.insert().values(
                            id=approval_id,
                            tenant_id=context.tenant.id,
                            experiment_id=row["id"],
                            experiment_version=row["version"],
                            payload_digest=digest(snapshot),
                            plan_snapshot=snapshot,
                            policy_version="human-experiment-approval-v1",
                            approved_by_user_id=context.user.id,
                            approved_at=now,
                            reason=command.reason,
                        )
                    )
                    values.update(state="approved", approval_id=approval_id)
                elif action == "start":
                    _member(
                        connection,
                        context,
                        space_id,
                        row["owner_user_id"],
                        line_id=row["product_line_id"],
                    )
                    values.update(state="running", started_at=now)
                elif action == "conclude":
                    _member(
                        connection,
                        context,
                        space_id,
                        row["owner_user_id"],
                        line_id=row["product_line_id"],
                    )
                    values.update(
                        state="concluded",
                        result=command.result,
                        result_evidence=resolve_evidence(
                            connection, context, command.result_evidence
                        ),
                        result_explanation=command.reason,
                        concluded_at=now,
                    )
                else:
                    values.update(state="cancelled", cancellation_reason=command.reason)
            updated = (
                connection.execute(
                    table.update()
                    .where(table.c.id == row["id"], table.c.tenant_id == context.tenant.id)
                    .values(**values, version=row["version"] + 1, updated_at=now)
                    .returning(table)
                )
                .mappings()
                .one()
            )
            result = _experiment(connection, context, updated)
            _emit(
                connection,
                context,
                space_id,
                "experiment",
                action,
                updated,
                before=row,
                operation=command,
            )
            return result

    def history(self, context: AuthContext, space_id: UUID, experiment_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _space(connection, context, space_id)
            row = (
                connection.execute(
                    select(tables.experiments).where(
                        tables.experiments.c.tenant_id == context.tenant.id,
                        tables.experiments.c.market_space_id == space_id,
                        tables.experiments.c.id == experiment_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProductWorkAccessError("实验不存在或不可访问")
            _line(connection, context, space_id, row["product_line_id"])
            log = tables.audit_log
            records = connection.execute(
                select(
                    log.c.action,
                    log.c.actor_user_id,
                    log.c.timestamp,
                    log.c.before_snapshot,
                    log.c.after_snapshot,
                    log.c.context,
                )
                .where(
                    log.c.tenant_id == context.tenant.id,
                    log.c.entity_id == experiment_id,
                    log.c.action.like("experiment.%"),
                )
                .order_by(log.c.timestamp.desc())
                .limit(100)
            ).mappings()
            return {"items": [_plain(record) for record in records]}
