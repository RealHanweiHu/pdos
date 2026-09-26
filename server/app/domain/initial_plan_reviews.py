"""Named manual plan review binding candidate, schedule, capacity and responsibilities."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import model_validator
from sqlalchemy import Connection, Engine, func, or_, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.contracts.common_objects import ApprovalRef, Contract, Digest, Text
from app.db.schema import tables
from app.domain.initial_plan_candidates import _source, _source_selector, candidate_snapshot
from app.domain.plan_responsibilities import _candidate, responsibility_state
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _member,
    _plain,
    digest,
)
from app.domain.resource_capacity import CapacityCheckDraft, evaluate_capacity
from app.domain.review_materials import case_project
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

REVIEW_SCOPE_NOTICE = (
    "接受计划供后续执行申请使用；不替代Case/DCP/TR、Project执行批准、正式预约或独立应用。"
)

POLICY_VERSION = "manual_plan.review.v1"


class PlanReviewDraft(Contract):
    request_id: UUID
    scenario_id: UUID
    capacity_check_id: UUID
    reviewer_user_id: UUID
    reason: Text
    replaces_review_id: UUID | None = None
    expected_review_digest: Digest | None = None

    @model_validator(mode="after")
    def replacement_fields(self) -> "PlanReviewDraft":
        if (self.replaces_review_id is None) != (self.expected_review_digest is None):
            raise ValueError("更换审阅人须提供原审阅及其版本")
        return self


class PlanReviewAction(Contract):
    request_id: UUID
    expected_digest: Digest
    action: Literal["accept", "reject", "withdraw"]
    reason: Text


def _candidate_write(connection: Connection, context: AuthContext, candidate_id: UUID) -> Any:
    candidate = _candidate(connection, context, candidate_id)
    if candidate["case_id"]:
        case_project(connection, context.tenant.id, candidate["case_id"], lock=True)
    _source(
        connection, context, candidate["market_space_id"], _source_selector(candidate), write=True
    )
    return (
        connection.execute(
            select(tables.initial_plan_candidates)
            .where(
                tables.initial_plan_candidates.c.tenant_id == context.tenant.id,
                tables.initial_plan_candidates.c.id == candidate_id,
            )
            .with_for_update()
        )
        .mappings()
        .one()
    )


def _reviewer(connection: Connection, context: AuthContext, candidate: Any, user_id: UUID) -> Any:
    user = (
        connection.execute(
            select(tables.users.c.id, tables.users.c.display_name, tables.users.c.role).where(
                tables.users.c.tenant_id == context.tenant.id,
                tables.users.c.id == user_id,
                tables.users.c.is_active.is_(True),
            )
        )
        .mappings()
        .one_or_none()
    )
    action = (
        Action.DEVELOPMENT_CASE_EDIT if candidate["case_id"] else Action.PRODUCT_WORK_CONTRIBUTE
    )
    if user is None or not is_allowed(Role(user["role"]), action):
        raise ProductWorkAccessError("审阅人已不具备当前计划编辑权限")
    if candidate["market_space_id"] and user["role"] not in ("owner", "admin"):
        _member(
            connection, context, candidate["market_space_id"], user_id, candidate["product_line_id"]
        )
    return user


def _inputs(
    connection: Connection,
    context: AuthContext,
    candidate_id: UUID,
    scenario_id: UUID,
    check_id: UUID,
) -> tuple[Any, Any]:
    scenario = (
        connection.execute(
            select(tables.initial_plan_scenarios)
            .where(
                tables.initial_plan_scenarios.c.tenant_id == context.tenant.id,
                tables.initial_plan_scenarios.c.candidate_id == candidate_id,
                tables.initial_plan_scenarios.c.id == scenario_id,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    check = (
        connection.execute(
            select(tables.plan_capacity_checks).where(
                tables.plan_capacity_checks.c.tenant_id == context.tenant.id,
                tables.plan_capacity_checks.c.scenario_id == scenario_id,
                tables.plan_capacity_checks.c.id == check_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if scenario is None or check is None:
        raise ProductWorkError("所选排程、容量检查和候选不属于同一条计划链")
    return scenario, check


def build_review_snapshot(
    connection: Connection, context: AuthContext, candidate: Any, scenario: Any, check: Any
) -> tuple[dict[str, Any], str]:
    responsibilities = responsibility_state(connection, context, candidate)
    current_capacity = evaluate_capacity(
        connection, context, scenario, CapacityCheckDraft.model_validate(check["inputs"])
    )
    blockers = []
    if not responsibilities["is_latest"]:
        blockers.append("候选已有新修订")
    if not responsibilities["source_is_current"]:
        blockers.append("计划来源已有变化")
    if not responsibilities["template_is_current"]:
        blockers.append("模板版本已有变化")
    if not responsibilities["all_confirmed"]:
        blockers.append("负责人/接收人尚未全部确认或当前资格已失效")
    blockers.extend(
        f"{item['node_key']}：{item['reason']}" for item in responsibilities["current_missing"]
    )
    if not scenario["result"]["complete"]:
        blockers.append("排程仍有未知时间")
    if current_capacity["status"] != "capacity_clear" or current_capacity["warnings"]:
        blockers.append("容量仍有冲突、缺项或版本变化")
    if digest(current_capacity) != check["result_digest"]:
        blockers.append("容量检查依据已有变化，请重新检查后准备新的审阅")
    confirmations = [
        {
            "node_key": item["node_key"],
            "slot": item["slot"],
            "user_id": item["user_id"],
            "eligible": item["eligible"],
            "response_id": item["response"]["id"] if item["response"] else None,
            "outcome": item["response"]["outcome"] if item["response"] else None,
        }
        for item in responsibilities["assignments"]
    ]
    basis = {
        "candidate": candidate_snapshot(candidate),
        "scenario": _plain(scenario),
        "capacity_check_id": str(check["id"]),
        "capacity_inputs": check["inputs"],
        "capacity": current_capacity,
        "confirmations": confirmations,
    }
    snapshot = {
        **basis,
        "blockers": blockers,
        "responsibilities": responsibilities["assignments"],
        "scope_notice": REVIEW_SCOPE_NOTICE,
        "origin": "manual",
    }
    return snapshot, digest(basis)


def _record(row: Any, *, reviewer_name: str | None = None) -> dict[str, Any]:
    return {**_plain(row), "payload_digest": digest(_plain(row)), "reviewer_name": reviewer_name}


def _event(
    connection: Connection, context: AuthContext, row: Any, reason: str, receipt_id: UUID
) -> None:
    EventAuditWriter(connection, tenant_id=context.tenant.id, actor_user_id=context.user.id).record(
        EventDraft(
            event_id=f"initial-plan-review:{receipt_id}",
            event_type="INITIAL_PLAN_REVIEW_CHANGED",
            source="planning_service",
            entity_id=row["id"],
            payload={
                "candidate_id": str(row["candidate_id"]),
                "state": row["state"],
                "round_no": row["round_no"],
            },
        ),
        AuditDraft(
            action="initial_plan_review." + row["state"],
            after_snapshot=_plain(row),
            context={"reason": reason},
        ),
    )


class InitialPlanReviewService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def list(self, context: AuthContext, candidate_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as connection:
            candidate = _candidate(connection, context, candidate_id)
            users = tables.users
            action = (
                Action.DEVELOPMENT_CASE_EDIT
                if candidate["case_id"]
                else Action.PRODUCT_WORK_CONTRIBUTE
            )
            eligible = select(users.c.id, users.c.display_name, users.c.role).where(
                users.c.tenant_id == context.tenant.id,
                users.c.is_active.is_(True),
                users.c.role.in_([role.value for role in Role if is_allowed(role, action)]),
            )
            if candidate["market_space_id"]:
                members = tables.market_space_members
                grants = tables.product_line_members
                space_access = (
                    select(members.c.user_id)
                    .where(
                        members.c.tenant_id == context.tenant.id,
                        members.c.market_space_id == candidate["market_space_id"],
                        members.c.user_id == users.c.id,
                        members.c.access.in_(("contributor", "manager")),
                    )
                    .exists()
                )
                line_access = (
                    select(grants.c.user_id)
                    .where(
                        grants.c.tenant_id == context.tenant.id,
                        grants.c.product_line_id == candidate["product_line_id"],
                        grants.c.user_id == users.c.id,
                        grants.c.access.in_(("contributor", "manager")),
                    )
                    .exists()
                    if candidate["product_line_id"]
                    else True
                )
                eligible = eligible.where(
                    or_(users.c.role.in_(("owner", "admin")), space_access & line_access)
                )
            reviewers = [
                _plain(row)
                for row in connection.execute(
                    eligible.order_by(users.c.display_name, users.c.id).limit(1000)
                ).mappings()
            ]
            eligible_ids = {user["id"] for user in reviewers}
            table = tables.initial_plan_reviews
            rows = list(
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id, table.c.candidate_id == candidate_id
                    )
                    .order_by(table.c.round_no.desc())
                    .limit(51)
                ).mappings()
            )
            names = {
                str(row["id"]): row["display_name"]
                for row in connection.execute(
                    select(users.c.id, users.c.display_name).where(
                        users.c.tenant_id == context.tenant.id,
                        users.c.id.in_({row["reviewer_user_id"] for row in rows}),
                    )
                ).mappings()
            }
            applied_review_ids = set(
                connection.execute(
                    select(tables.project_execution_requests.c.plan_review_id)
                    .join(
                        tables.initial_plan_applications,
                        (
                            tables.initial_plan_applications.c.tenant_id
                            == tables.project_execution_requests.c.tenant_id
                        )
                        & (
                            tables.initial_plan_applications.c.execution_request_id
                            == tables.project_execution_requests.c.id
                        ),
                    )
                    .where(
                        tables.project_execution_requests.c.tenant_id == context.tenant.id,
                        tables.project_execution_requests.c.plan_review_id.in_(
                            [row["id"] for row in rows[:50]]
                        ),
                    )
                ).scalars()
            )
            receipts = tables.initial_plan_review_receipts
            history = list(
                connection.execute(
                    select(receipts)
                    .where(
                        receipts.c.tenant_id == context.tenant.id,
                        receipts.c.review_id.in_([row["id"] for row in rows[:50]]),
                    )
                    .order_by(receipts.c.created_at, receipts.c.id)
                ).mappings()
            )
            checks = list(
                connection.execute(
                    select(
                        tables.plan_capacity_checks.c.id,
                        tables.plan_capacity_checks.c.scenario_id,
                        tables.plan_capacity_checks.c.created_at,
                        tables.plan_capacity_checks.c.result,
                    )
                    .join(
                        tables.initial_plan_scenarios,
                        (
                            tables.initial_plan_scenarios.c.tenant_id
                            == tables.plan_capacity_checks.c.tenant_id
                        )
                        & (
                            tables.initial_plan_scenarios.c.id
                            == tables.plan_capacity_checks.c.scenario_id
                        ),
                    )
                    .where(
                        tables.plan_capacity_checks.c.tenant_id == context.tenant.id,
                        tables.initial_plan_scenarios.c.candidate_id == candidate_id,
                    )
                    .order_by(
                        tables.plan_capacity_checks.c.created_at.desc(),
                        tables.plan_capacity_checks.c.id,
                    )
                    .limit(101)
                ).mappings()
            )
            return {
                "capacity_checks": [
                    {
                        "id": str(row["id"]),
                        "scenario_id": str(row["scenario_id"]),
                        "created_at": row["created_at"].isoformat(),
                        "status": row["result"]["status"],
                    }
                    for row in checks[:100]
                ],
                "has_more_checks": len(checks) > 100,
                "items": [
                    {
                        **_record(row, reviewer_name=names.get(str(row["reviewer_user_id"]))),
                        "applied": row["id"] in applied_review_ids,
                    }
                    for row in rows[:50]
                ],
                "has_more": len(rows) > 50,
                "reviewers": reviewers,
                "current_user_id": str(context.user.id),
                "can_prepare": str(context.user.id) in eligible_ids,
                "history": [_plain(row) for row in history],
            }

    def prepare(
        self, context: AuthContext, candidate_id: UUID, draft: PlanReviewDraft
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            candidate = _candidate_write(connection, context, candidate_id)
            table = tables.initial_plan_reviews
            signing = draft.model_dump(mode="json")
            for key in ("replaces_review_id", "expected_review_digest"):
                if key not in draft.model_fields_set:
                    signing.pop(key)
            fingerprint = digest({"candidate_id": str(candidate_id), **signing})
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
                if prior["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号已用于另一份审阅")
                return _record(prior)
            _reviewer(connection, context, candidate, draft.reviewer_user_id)
            replaced = None
            if draft.replaces_review_id:
                replaced = (
                    connection.execute(
                        select(table)
                        .where(
                            table.c.tenant_id == context.tenant.id,
                            table.c.candidate_id == candidate_id,
                        )
                        .order_by(table.c.round_no.desc())
                        .limit(1)
                    )
                    .mappings()
                    .one_or_none()
                )
                if (
                    replaced is None
                    or replaced["id"] != draft.replaces_review_id
                    or replaced["state"] != "pending_review"
                    or digest(_plain(replaced)) != draft.expected_review_digest
                ):
                    raise ProductWorkError("只能更换最新待审阅轮次的审阅人，请刷新原记录")
                if replaced["reviewer_user_id"] == draft.reviewer_user_id:
                    raise ProductWorkError("请选择与原审阅人不同的成员")
                if (
                    replaced["scenario_id"] != draft.scenario_id
                    or replaced["capacity_check_id"] != draft.capacity_check_id
                ):
                    raise ProductWorkError(
                        "更换审阅人须沿用原排程和容量检查；调整内容请准备完整新审阅"
                    )
            scenario, check = _inputs(
                connection, context, candidate_id, draft.scenario_id, draft.capacity_check_id
            )
            snapshot, basis_digest = build_review_snapshot(
                connection, context, candidate, scenario, check
            )
            if replaced is not None:
                if basis_digest != replaced["basis_digest"]:
                    raise ProductWorkError(
                        "原计划、责任或容量依据已变化，请重新检查并准备完整新审阅"
                    )
                original_name = connection.execute(
                    select(tables.users.c.display_name).where(
                        tables.users.c.tenant_id == context.tenant.id,
                        tables.users.c.id == replaced["reviewer_user_id"],
                    )
                ).scalar_one_or_none()
                snapshot["reviewer_change"] = {
                    "previous_review_id": str(replaced["id"]),
                    "previous_round_no": replaced["round_no"],
                    "previous_reviewer_user_id": str(replaced["reviewer_user_id"]),
                    "previous_reviewer_name": original_name,
                    "reason": draft.reason,
                    "changed_by_user_id": str(context.user.id),
                    "changed_by_name": context.user.display_name,
                }
            round_no = (
                connection.execute(
                    select(func.max(table.c.round_no)).where(
                        table.c.tenant_id == context.tenant.id, table.c.candidate_id == candidate_id
                    )
                ).scalar_one()
                or 0
            ) + 1
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        candidate_id=candidate_id,
                        scenario_id=scenario["id"],
                        capacity_check_id=check["id"],
                        round_no=round_no,
                        version=1,
                        state="pending_review",
                        reviewer_user_id=draft.reviewer_user_id,
                        snapshot=snapshot,
                        basis_digest=basis_digest,
                        preparation_reason=draft.reason,
                        created_by_user_id=context.user.id,
                        request_id=draft.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            _event(connection, context, row, draft.reason, uuid4())
            return _record(row)

    def act(
        self, context: AuthContext, candidate_id: UUID, review_id: UUID, command: PlanReviewAction
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            candidate = _candidate_write(connection, context, candidate_id)
            table = tables.initial_plan_reviews
            row = (
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.candidate_id == candidate_id,
                        table.c.id == review_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProductWorkAccessError("审阅不存在或不属于当前候选")
            if command.action == "withdraw":
                if context.user.id not in {row["created_by_user_id"], row["reviewer_user_id"]}:
                    raise ProductWorkAccessError("由准备人或审阅人撤回计划审阅")
            elif context.user.id != row["reviewer_user_id"]:
                raise ProductWorkAccessError("由指定审阅人接受或退回计划")
            _reviewer(connection, context, candidate, context.user.id)
            receipts = tables.initial_plan_review_receipts
            fingerprint = digest({"review_id": str(review_id), **command.model_dump(mode="json")})
            prior = (
                connection.execute(
                    select(receipts).where(
                        receipts.c.tenant_id == context.tenant.id,
                        receipts.c.actor_user_id == context.user.id,
                        receipts.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号已用于不同审阅动作")
                return _record(prior["snapshot"])
            if command.expected_digest != digest(_plain(row)):
                raise ProductWorkError("审阅已有新版本，请刷新后办理")
            if connection.execute(
                select(tables.initial_plan_applications.c.id)
                .join(
                    tables.project_execution_requests,
                    (
                        tables.project_execution_requests.c.tenant_id
                        == tables.initial_plan_applications.c.tenant_id
                    )
                    & (
                        tables.project_execution_requests.c.id
                        == tables.initial_plan_applications.c.execution_request_id
                    ),
                )
                .where(
                    tables.initial_plan_applications.c.tenant_id == context.tenant.id,
                    tables.project_execution_requests.c.plan_review_id == row["id"],
                )
            ).first():
                raise ProductWorkError("计划已独立应用，原接受记录保留；请通过项目变更办理调整")
            if row["state"] != "pending_review" and not (
                row["state"] == "accepted" and command.action == "withdraw"
            ):
                raise ProductWorkError("当前审阅状态不支持此操作")
            if (
                command.action != "withdraw"
                and connection.execute(
                    select(table.c.id)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.candidate_id == candidate_id,
                        table.c.round_no > row["round_no"],
                    )
                    .limit(1)
                ).first()
            ):
                raise ProductWorkError("已有新一轮审阅，请办理最新一轮")
            receipt_id = uuid4()
            now = datetime.now(UTC)
            approval = row["approval"]
            if command.action == "accept":
                scenario, check = _inputs(
                    connection, context, candidate_id, row["scenario_id"], row["capacity_check_id"]
                )
                snapshot, basis_digest = build_review_snapshot(
                    connection, context, candidate, scenario, check
                )
                if basis_digest != row["basis_digest"]:
                    raise ProductWorkError("来源、责任确认或相关容量已变化，请准备新一轮审阅")
                if snapshot["blockers"]:
                    raise ProductWorkError("计划尚不能接受：" + "；".join(snapshot["blockers"][:8]))
                approval = ApprovalRef(
                    approval_id=receipt_id,
                    payload_digest=basis_digest,
                    policy_version=POLICY_VERSION,
                    approved_by_user_id=context.user.id,
                    approved_at=now,
                ).model_dump(mode="json")
            state = {"accept": "accepted", "reject": "rejected", "withdraw": "withdrawn"}[
                command.action
            ]
            updated = (
                connection.execute(
                    table.update()
                    .where(table.c.tenant_id == context.tenant.id, table.c.id == review_id)
                    .values(
                        state=state,
                        version=row["version"] + 1,
                        approval=approval,
                        outcome_reason=command.reason,
                        updated_at=now,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            connection.execute(
                receipts.insert().values(
                    id=receipt_id,
                    tenant_id=context.tenant.id,
                    review_id=review_id,
                    actor_user_id=context.user.id,
                    request_id=command.request_id,
                    request_digest=fingerprint,
                    snapshot=_plain(updated),
                    reason=command.reason,
                )
            )
            _event(connection, context, updated, command.reason, receipt_id)
            return _record(updated)


def ensure_plan_reviews_resolved(
    connection: Connection,
    context: AuthContext,
    space_id: UUID,
    *,
    line_id: UUID | None = None,
    product_id: UUID | None = None,
) -> None:
    review = tables.initial_plan_reviews
    candidate = tables.initial_plan_candidates
    statement = (
        select(review.c.id)
        .join(
            candidate,
            (candidate.c.tenant_id == review.c.tenant_id)
            & (candidate.c.id == review.c.candidate_id),
        )
        .where(
            review.c.tenant_id == context.tenant.id,
            candidate.c.market_space_id == space_id,
            review.c.state.in_(("pending_review", "accepted")),
        )
    )
    applied_reviews = (
        select(tables.project_execution_requests.c.plan_review_id)
        .join(
            tables.initial_plan_applications,
            (
                tables.initial_plan_applications.c.tenant_id
                == tables.project_execution_requests.c.tenant_id
            )
            & (
                tables.initial_plan_applications.c.execution_request_id
                == tables.project_execution_requests.c.id
            ),
        )
        .where(tables.project_execution_requests.c.tenant_id == context.tenant.id)
    )
    statement = statement.where(~review.c.id.in_(applied_reviews))
    if line_id:
        statement = statement.where(candidate.c.product_line_id == line_id)
    if product_id:
        statement = statement.where(
            candidate.c.definition_id.in_(
                select(tables.product_definitions.c.id).where(
                    tables.product_definitions.c.tenant_id == context.tenant.id,
                    tables.product_definitions.c.product_id == product_id,
                )
            )
        )
    if connection.execute(statement.limit(1)).first():
        raise ProductWorkError("仍有待审阅或已接受待应用的计划，请先办理或明确撤回")
