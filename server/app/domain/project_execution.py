"""Versioned execution authority and source-bound approval of accepted initial plans."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, func, or_, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import ApprovalRef, Contract, Digest, SourceRef, Text
from app.contracts.planning_records import CaseProjectConversion
from app.db.schema import tables
from app.domain.case_requirements import _case, _relations, require_case_requirements_ready
from app.domain.case_reviews import case_review_blockers, review_basis
from app.domain.definition_inheritance import expand_definition
from app.domain.initial_plan_reviews import _inputs, _reviewer, build_review_snapshot
from app.domain.plan_responsibilities import _candidate
from app.domain.product_definitions import _row as definition_row
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _line,
    _plain,
    _role,
    _space,
    digest,
)
from app.domain.resource_reservations import _project
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class ProjectExecutionNotReadyError(ValueError):
    pass


class ExecutionPolicyDraft(Contract):
    request_id: UUID
    expected_version: int = Field(ge=0)
    approver_user_id: UUID
    four_eyes: bool
    authority_basis: Text


class ExecutionRenewal(Contract):
    previous_execution_id: UUID
    expected_execution_digest: Digest
    policy_id: UUID


class ExecutionRequestDraft(Contract):
    request_id: UUID
    plan_review_id: UUID
    reason: Text
    policy_renewal: ExecutionRenewal | None = None


class ExecutionAction(Contract):
    request_id: UUID
    expected_digest: Digest
    action: Literal["approve", "reject", "withdraw"]
    reason: Text


def ensure_conversion(connection: Connection, tenant_id: UUID, project_id: UUID) -> Any:
    project = (
        connection.execute(
            select(tables.projects).where(
                tables.projects.c.tenant_id == tenant_id, tables.projects.c.id == project_id
            )
        )
        .mappings()
        .one()
    )
    table = tables.case_project_conversions
    prior = (
        connection.execute(
            select(table).where(table.c.tenant_id == tenant_id, table.c.project_id == project_id)
        )
        .mappings()
        .one_or_none()
    )
    if prior:
        if prior["case_id"] != project["development_case_id"]:
            raise ProductWorkError("转换记录与实际项目来源不一致")
        return prior
    case_id = project["development_case_id"]
    if case_id is None:
        raise ProductWorkError("项目缺少实际Case来源，不能绑定初始计划")
    event = tables.events
    audit = tables.audit_log
    records = list(
        connection.execute(
            select(
                event.c.id.label("event_row_id"),
                event.c.timestamp,
                audit.c.id.label("audit_row_id"),
                audit.c.actor_user_id,
                audit.c.before_snapshot,
                audit.c.after_snapshot,
            )
            .join(
                audit,
                (audit.c.tenant_id == event.c.tenant_id)
                & (audit.c.event_id == event.c.event_id)
                & (audit.c.project_id == event.c.project_id)
                & (audit.c.entity_id == event.c.entity_id),
            )
            .where(
                event.c.tenant_id == tenant_id,
                event.c.project_id == project_id,
                event.c.entity_id == case_id,
                event.c.source == "development_case_service",
                event.c.event_type == "DEVELOPMENT_CASE_STATUS_CHANGED",
                event.c.payload["from_status"].as_string() == "approved",
                event.c.payload["to_status"].as_string() == "converted",
                audit.c.action == "development_case.transition",
            )
            .limit(2)
        ).mappings()
    )
    if (
        len(records) != 1
        or records[0]["actor_user_id"] is None
        or not records[0]["before_snapshot"]
        or records[0]["before_snapshot"].get("status") != "approved"
        or records[0]["after_snapshot"].get("status") != "converted"
    ):
        raise ProductWorkError("缺少唯一有效的Case批准转项目事件和审计，请先补齐真实转换证据")
    record = records[0]
    row_id = uuid4()
    contract = CaseProjectConversion(
        id=row_id,
        tenant_id=tenant_id,
        case_ref=SourceRef(
            tenant_id=tenant_id,
            kind="development_case",
            ref_id=case_id,
            as_of=record["timestamp"],
            digest=digest(record["before_snapshot"]),
        ),
        project_id=project_id,
        converted_by_user_id=record["actor_user_id"],
        converted_at=record["timestamp"],
        event_row_id=record["event_row_id"],
        audit_row_id=record["audit_row_id"],
    )
    return (
        connection.execute(
            table.insert()
            .values(
                id=row_id,
                tenant_id=tenant_id,
                case_id=case_id,
                project_id=project_id,
                event_row_id=record["event_row_id"],
                audit_row_id=record["audit_row_id"],
                contract=contract.model_dump(mode="json"),
            )
            .returning(table)
        )
        .mappings()
        .one()
    )


def _policy(connection: Connection, tenant_id: UUID, project_id: UUID) -> Any:
    table = tables.project_execution_policies
    return (
        connection.execute(
            select(table)
            .where(table.c.tenant_id == tenant_id, table.c.project_id == project_id)
            .order_by(table.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def _person(connection: Connection, context: AuthContext, project_id: UUID, user_id: UUID) -> Any:
    user = (
        connection.execute(
            select(tables.users.c.id, tables.users.c.display_name, tables.users.c.role).where(
                tables.users.c.tenant_id == context.tenant.id,
                tables.users.c.id == user_id,
                tables.users.c.is_active.is_(True),
                tables.users.c.role.in_(
                    ("owner", "admin", "project_manager", "engineer", "quality")
                ),
            )
        )
        .mappings()
        .one_or_none()
    )
    if user is None:
        raise ProductWorkError("参与人已不是有效内部用户")
    if (
        user["role"] not in ("owner", "admin")
        and connection.execute(
            select(tables.project_members.c.id).where(
                tables.project_members.c.tenant_id == context.tenant.id,
                tables.project_members.c.project_id == project_id,
                tables.project_members.c.user_id == user_id,
            )
        ).first()
        is None
    ):
        raise ProductWorkError(f"{user['display_name']}尚未加入实际项目")
    return user


def _origin(
    connection: Connection, context: AuthContext, candidate: Any, case: Any
) -> dict[str, Any]:
    relations = _relations(connection, context, case)
    requirements = {UUID(item["requirement_id"]) for item in relations}
    if candidate["case_id"]:
        if candidate["case_id"] != case["id"]:
            raise ProductWorkError("案例计划只能应用到该Case实际转换的项目")
        return {
            "kind": "development_case",
            "case_id": str(case["id"]),
            "requirements": [item["current"] for item in relations],
        }
    definition = tables.product_definitions
    strategy = tables.product_strategies
    statement = select(definition).where(
        definition.c.tenant_id == context.tenant.id,
        definition.c.market_space_id == candidate["market_space_id"],
        definition.c.state == "published",
    )
    if candidate["definition_id"]:
        statement = statement.where(definition.c.id == candidate["definition_id"])
    else:
        statement = statement.join(
            strategy,
            (strategy.c.tenant_id == definition.c.tenant_id)
            & (strategy.c.id == definition.c.strategy_id),
        ).where(strategy.c.opportunity_id == candidate["opportunity_id"])
    matches = []
    for row in connection.execute(statement).mappings():
        try:
            definition_row(connection, context, row["market_space_id"], row["id"])
        except ProductWorkAccessError:
            continue
        release = (
            connection.execute(
                select(tables.definition_releases)
                .where(
                    tables.definition_releases.c.tenant_id == context.tenant.id,
                    tables.definition_releases.c.product_id == row["product_id"],
                )
                .order_by(tables.definition_releases.c.sequence.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        if not release or release["action"] != "publish" or release["definition_id"] != row["id"]:
            continue
        links = list(
            connection.execute(
                select(tables.definition_requirement_links).where(
                    tables.definition_requirement_links.c.tenant_id == context.tenant.id,
                    tables.definition_requirement_links.c.definition_id == row["id"],
                )
            ).mappings()
        )
        row = expand_definition(connection, row)
        confirmed = {
            item["item_key"] for item in row["content"]["items"] if item["state"] == "confirmed"
        }
        covered = {item["item_key"] for item in links if item["requirement_id"] in requirements}
        if not confirmed or not confirmed <= covered:
            continue
        matches.append(
            {
                "definition_id": str(row["id"]),
                "release_id": str(release["id"]),
                "revision_number": row["revision_number"],
                "requirement_ids": sorted(
                    {str(item["requirement_id"]) for item in links if item["item_key"] in confirmed}
                ),
                "item_keys": sorted(confirmed),
            }
        )
    if not matches:
        raise ProductWorkError("未找到完整覆盖该Case需求的当前发布定义及实际转化链")
    return {
        "kind": "product_definition" if candidate["definition_id"] else "opportunity",
        "definitions": sorted(matches, key=lambda item: item["definition_id"]),
        "requirements": [item["current"] for item in relations],
    }


def _lock_candidate_source(connection: Connection, context: AuthContext, candidate_id: UUID) -> Any:
    candidate = _candidate(connection, context, candidate_id)
    if candidate["market_space_id"]:
        _space(connection, context, candidate["market_space_id"], lock=True)
        _line(
            connection,
            context,
            candidate["market_space_id"],
            candidate["product_line_id"],
            writable=True,
        )
    source_table = (
        tables.development_cases
        if candidate["case_id"]
        else tables.product_definitions
        if candidate["definition_id"]
        else tables.opportunities
    )
    source_id = candidate["case_id"] or candidate["definition_id"] or candidate["opportunity_id"]
    connection.execute(
        select(source_table.c.id)
        .where(source_table.c.tenant_id == context.tenant.id, source_table.c.id == source_id)
        .with_for_update()
    ).scalar_one()
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


def execution_snapshot(
    connection: Connection,
    context: AuthContext,
    project: Any,
    review: Any,
    policy: Any,
    conversion: Any,
) -> tuple[dict[str, Any], str]:
    case = _case(connection, context, project["development_case_id"], lock=True)
    candidate = _lock_candidate_source(connection, context, review["candidate_id"])
    review = (
        connection.execute(
            select(tables.initial_plan_reviews)
            .where(
                tables.initial_plan_reviews.c.tenant_id == context.tenant.id,
                tables.initial_plan_reviews.c.id == review["id"],
            )
            .with_for_update()
        )
        .mappings()
        .one()
    )
    scenario, check = _inputs(
        connection, context, candidate["id"], review["scenario_id"], review["capacity_check_id"]
    )
    origin = _origin(connection, context, candidate, case)
    # Capture requirements and current definition releases before the shared resource locks.
    case_basis = review_basis(connection, context.tenant.id, case, lock=True)
    blockers = []
    try:
        require_case_requirements_ready(connection, context.tenant.id, case)
    except ValueError as error:
        blockers.append(str(error))
    blockers.extend(
        item["label"]
        for item in case_review_blockers(connection, context.tenant.id, case, "charter", lock=True)
    )
    if case["status"] not in ("approved", "converted"):
        blockers.append("Case当前尚未获准执行来源")
    if any(item["status"] not in ("approved", "converted") for item in origin["requirements"]):
        blockers.append("存在尚未批准的实际需求")
    if any(not item["is_current"] for item in case_basis["definitions"]):
        blockers.append("Case中的定义引用已被替代或撤回")
    if review["state"] != "accepted":
        blockers.append("计划尚未接受或已撤回")
    if connection.execute(
        select(tables.initial_plan_reviews.c.id)
        .where(
            tables.initial_plan_reviews.c.tenant_id == context.tenant.id,
            tables.initial_plan_reviews.c.candidate_id == candidate["id"],
            tables.initial_plan_reviews.c.round_no > review["round_no"],
        )
        .limit(1)
    ).first():
        blockers.append("已有新一轮计划审阅")
    try:
        _reviewer(connection, context, candidate, review["reviewer_user_id"])
    except (ProductWorkError, ProductWorkAccessError) as error:
        blockers.append(str(error))
    for user_id in {
        UUID(node[field])
        for node in candidate["plan"]["nodes"]
        for field in ("owner_user_id", "receiver_user_id")
        if node[field]
    }:
        try:
            _person(connection, context, project["id"], user_id)
        except ProductWorkError as error:
            blockers.append(str(error))
    _person(connection, context, project["id"], policy["approver_user_id"])
    stage_codes = set(
        connection.execute(
            select(tables.stages.c.code).where(
                tables.stages.c.tenant_id == context.tenant.id,
                tables.stages.c.workflow_id == project["workflow_id"],
            )
        ).scalars()
    )
    if set(candidate["stage_assignments"].values()) - stage_codes:
        blockers.append("计划阶段与实际项目工作流不匹配")
    plan_snapshot, plan_digest = build_review_snapshot(
        connection, context, candidate, scenario, check
    )
    blockers.extend(plan_snapshot["blockers"])
    if plan_digest != review["basis_digest"]:
        blockers.append("已接受计划的关键依据已变化，须重新审阅")
    if project["status"] in ("completed", "archived"):
        blockers.append("项目已结束")
    from app.domain.case_reviews import _policies

    case_policies = [
        _plain(item)
        for item in _policies(connection, context.tenant.id, case["id"])
        if item["stage_code"] == "charter"
    ]
    review_table = tables.case_reviews
    ranked = (
        select(
            review_table.c.id,
            review_table.c.policy_id,
            review_table.c.state,
            review_table.c.approval,
            review_table.c.expires_at,
            review_table.c.review_kind,
            func.row_number()
            .over(partition_by=review_table.c.review_kind, order_by=review_table.c.round_no.desc())
            .label("position"),
        )
        .where(
            review_table.c.tenant_id == context.tenant.id,
            review_table.c.case_id == case["id"],
            review_table.c.stage_code == "charter",
        )
        .subquery()
    )
    reviews = list(
        connection.execute(
            select(ranked).where(ranked.c.position == 1).order_by(ranked.c.review_kind)
        ).mappings()
    )
    basis = {
        "project": {
            key: _plain(project)[key]
            for key in ("id", "development_case_id", "workflow_id", "start_date", "target_date")
        },
        "conversion": _plain(conversion),
        "case_basis": case_basis,
        "case_reviews": [_plain(row) for row in reviews],
        "case_policies": case_policies,
        "origin": origin,
        "plan_review_id": str(review["id"]),
        "plan_digest": plan_digest,
        "policy": _plain(policy),
    }
    return {
        **basis,
        "project_name": project["name"],
        "plan_snapshot": plan_snapshot,
        "blockers": list(dict.fromkeys(blockers)),
    }, digest(basis)


def _record(row: Any) -> dict[str, Any]:
    return {**_plain(row), "payload_digest": digest(_plain(row))}


def _event(
    connection: Connection,
    context: AuthContext,
    project_id: UUID,
    row: Any,
    kind: str,
    reason: str,
    receipt_id: UUID,
) -> None:
    EventAuditWriter(
        connection,
        tenant_id=context.tenant.id,
        actor_user_id=context.user.id,
        project_id=project_id,
    ).record(
        EventDraft(
            event_id=f"project-execution:{receipt_id}",
            event_type="PROJECT_EXECUTION_CHANGED",
            source="planning_service",
            entity_id=row["id"],
            payload={"record_id": str(row["id"]), "action": kind},
        ),
        AuditDraft(
            action="project_execution." + kind,
            after_snapshot=_plain(row),
            context={"reason": reason},
        ),
    )


class ProjectExecutionService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def list(
        self, context: AuthContext, project_id: UUID, target_id: UUID | None = None
    ) -> dict[str, Any]:
        with self.engine.connect() as connection:
            project = _project(connection, context, project_id)
            policies = list(
                connection.execute(
                    select(tables.project_execution_policies)
                    .where(
                        tables.project_execution_policies.c.tenant_id == context.tenant.id,
                        tables.project_execution_policies.c.project_id == project_id,
                    )
                    .order_by(tables.project_execution_policies.c.version.desc())
                ).mappings()
            )
            table = tables.project_execution_requests
            rows = list(
                connection.execute(
                    select(table)
                    .where(table.c.tenant_id == context.tenant.id, table.c.project_id == project_id)
                    .order_by(table.c.round_no.desc())
                    .limit(51)
                ).mappings()
            )
            has_more = len(rows) > 50
            visible = rows[:50]
            if target_id is not None and not any(row["id"] == target_id for row in visible):
                target = (
                    connection.execute(
                        select(table).where(
                            table.c.tenant_id == context.tenant.id,
                            table.c.project_id == project_id,
                            table.c.id == target_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if target is None:
                    raise ProductWorkAccessError("指定申请不存在或不属于当前项目")
                visible.append(target)
            users = tables.users
            members = select(tables.project_members.c.user_id).where(
                tables.project_members.c.tenant_id == context.tenant.id,
                tables.project_members.c.project_id == project_id,
            )
            people = [
                _plain(row)
                for row in connection.execute(
                    select(users.c.id, users.c.display_name, users.c.role)
                    .where(
                        users.c.tenant_id == context.tenant.id,
                        users.c.is_active.is_(True),
                        users.c.role.in_(
                            ("owner", "admin", "project_manager", "engineer", "quality")
                        ),
                        or_(users.c.role.in_(("owner", "admin")), users.c.id.in_(members)),
                    )
                    .order_by(users.c.display_name, users.c.id)
                    .limit(1000)
                ).mappings()
            ]
            applied_ids = {
                str(value)
                for value in connection.execute(
                    select(tables.initial_plan_applications.c.execution_request_id).where(
                        tables.initial_plan_applications.c.tenant_id == context.tenant.id,
                        tables.initial_plan_applications.c.project_id == project_id,
                    )
                ).scalars()
            }
            choices = []
            case = (
                _case(connection, context, project["development_case_id"])
                if project["development_case_id"]
                else None
            )
            if case:
                review_table = tables.initial_plan_reviews
                for row in connection.execute(
                    select(review_table)
                    .where(
                        review_table.c.tenant_id == context.tenant.id,
                        review_table.c.state == "accepted",
                    )
                    .order_by(review_table.c.created_at.desc())
                    .limit(500)
                ).mappings():
                    try:
                        candidate = _candidate(connection, context, row["candidate_id"])
                        _origin(connection, context, candidate, case)
                    except (ProductWorkError, ProductWorkAccessError):
                        continue
                    choices.append(
                        {
                            "id": str(row["id"]),
                            "candidate_id": str(candidate["id"]),
                            "title": candidate["title"],
                            "candidate_version": candidate["version"],
                            "round_no": row["round_no"],
                        }
                    )
            receipts = tables.project_execution_receipts
            history = list(
                connection.execute(
                    select(receipts)
                    .where(
                        receipts.c.tenant_id == context.tenant.id,
                        receipts.c.execution_request_id.in_([row["id"] for row in visible]),
                    )
                    .order_by(receipts.c.created_at, receipts.c.id)
                ).mappings()
            )
            return {
                "project_status": project["status"],
                "latest_execution_id": str(rows[0]["id"]) if rows else None,
                "policy": _plain(policies[0]) if policies else None,
                "policy_history": [_plain(row) for row in policies],
                "people": people,
                "plan_reviews": choices,
                "items": [
                    {**_record(row), "applied": str(row["id"]) in applied_ids} for row in visible
                ],
                "has_more": has_more,
                "history": [_plain(row) for row in history],
                "current_user_id": str(context.user.id),
                "can_configure": is_allowed(context.user.role, Action.TENANT_MANAGE),
                "can_request": is_allowed(context.user.role, Action.PROJECT_EDIT),
                "application_available": True,
            }

    def publish_policy(
        self, context: AuthContext, project_id: UUID, draft: ExecutionPolicyDraft
    ) -> dict[str, Any]:
        _role(context, Action.TENANT_MANAGE)
        with self.engine.begin() as connection:
            _project(connection, context, project_id, write=True)
            _person(connection, context, project_id, draft.approver_user_id)
            table = tables.project_execution_policies
            fingerprint = digest({"project_id": str(project_id), **draft.model_dump(mode="json")})
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
                    raise ProductWorkError("请求编号已用于另一项执行政策")
                return _plain(prior)
            latest = _policy(connection, context.tenant.id, project_id)
            if draft.expected_version != (latest["version"] if latest else 0):
                raise ProductWorkError("执行政策已有新版本，请刷新")
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        version=draft.expected_version + 1,
                        approver_user_id=draft.approver_user_id,
                        four_eyes=draft.four_eyes,
                        authority_basis=draft.authority_basis,
                        created_by_user_id=context.user.id,
                        request_id=draft.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            _event(
                connection,
                context,
                project_id,
                row,
                "policy_published",
                draft.authority_basis,
                uuid4(),
            )
            return _plain(row)

    def prepare(
        self, context: AuthContext, project_id: UUID, draft: ExecutionRequestDraft
    ) -> dict[str, Any]:
        _role(context, Action.PROJECT_EDIT)
        with self.engine.begin() as connection:
            project = _project(connection, context, project_id, write=True)
            table = tables.project_execution_requests
            signing = draft.model_dump(mode="json")
            if "policy_renewal" not in draft.model_fields_set:
                signing.pop("policy_renewal")
            fingerprint = digest({"project_id": str(project_id), **signing})
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
                    raise ProductWorkError("请求编号已用于另一项执行申请")
                return _record(prior)
            policy = _policy(connection, context.tenant.id, project_id)
            if policy is None:
                raise ProductWorkError("请先配置本项目的具名执行批准政策")
            previous = None
            if draft.policy_renewal:
                previous = (
                    connection.execute(
                        select(table)
                        .where(
                            table.c.tenant_id == context.tenant.id, table.c.project_id == project_id
                        )
                        .order_by(table.c.round_no.desc())
                        .limit(1)
                    )
                    .mappings()
                    .one_or_none()
                )
                renewal = draft.policy_renewal
                if (
                    previous is None
                    or previous["id"] != renewal.previous_execution_id
                    or previous["state"] != "pending_approval"
                    or digest(_plain(previous)) != renewal.expected_execution_digest
                ):
                    raise ProductWorkError("仅可续提最新待批准申请，请刷新原申请")
                if (
                    policy["id"] != renewal.policy_id
                    or policy["id"] == previous["policy_id"]
                    or previous["plan_review_id"] != draft.plan_review_id
                ):
                    raise ProductWorkError("续提须固定当前新政策并沿用原计划审阅")
            conversion = ensure_conversion(connection, context.tenant.id, project_id)
            review = (
                connection.execute(
                    select(tables.initial_plan_reviews).where(
                        tables.initial_plan_reviews.c.tenant_id == context.tenant.id,
                        tables.initial_plan_reviews.c.id == draft.plan_review_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if review is None:
                raise ProductWorkError("计划审阅不存在")
            snapshot, basis_digest = execution_snapshot(
                connection, context, project, review, policy, conversion
            )
            if previous is not None:
                fields = (
                    "project",
                    "conversion",
                    "case_basis",
                    "case_reviews",
                    "case_policies",
                    "origin",
                    "plan_review_id",
                    "plan_digest",
                )
                if digest({k: snapshot[k] for k in fields}) != digest(
                    {k: previous["snapshot"][k] for k in fields}
                ):
                    raise ProductWorkError("原计划或执行依据已变化，请核对后准备完整新申请")
                old_renewal = previous["snapshot"].get("policy_renewal") or {}
                requesters = sorted(
                    {
                        str(previous["created_by_user_id"]),
                        str(context.user.id),
                        *old_renewal.get("original_requester_ids", []),
                    }
                )
                if policy["four_eyes"] and str(policy["approver_user_id"]) in requesters:
                    raise ProductWorkError("新政策要求独立批准人，不能由本申请历次提交人批准")
                snapshot["policy_renewal"] = {
                    "previous_execution_id": str(previous["id"]),
                    "previous_round_no": previous["round_no"],
                    "previous_policy": previous["snapshot"]["policy"],
                    "original_requester_ids": requesters,
                    "reason": draft.reason,
                    "actor_user_id": str(context.user.id),
                    "actor_name": context.user.display_name,
                }
            round_no = (
                connection.execute(
                    select(func.max(table.c.round_no)).where(
                        table.c.tenant_id == context.tenant.id, table.c.project_id == project_id
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
                        project_id=project_id,
                        conversion_id=conversion["id"],
                        plan_review_id=review["id"],
                        policy_id=policy["id"],
                        round_no=round_no,
                        version=1,
                        state="pending_approval",
                        snapshot=snapshot,
                        basis_digest=basis_digest,
                        plan_digest=review["basis_digest"],
                        request_reason=draft.reason,
                        created_by_user_id=context.user.id,
                        request_id=draft.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            _event(connection, context, project_id, row, "requested", draft.reason, uuid4())
            return _record(row)

    def act(
        self, context: AuthContext, project_id: UUID, execution_id: UUID, command: ExecutionAction
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            project = _project(connection, context, project_id, write=True)
            table = tables.project_execution_requests
            row = (
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.project_id == project_id,
                        table.c.id == execution_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProductWorkAccessError("执行申请不存在或不属于当前项目")
            policy = (
                connection.execute(
                    select(tables.project_execution_policies).where(
                        tables.project_execution_policies.c.tenant_id == context.tenant.id,
                        tables.project_execution_policies.c.id == row["policy_id"],
                    )
                )
                .mappings()
                .one()
            )
            if command.action == "withdraw":
                if context.user.id not in {row["created_by_user_id"], policy["approver_user_id"]}:
                    raise ProductWorkAccessError("由申请人或批准人撤回执行申请")
            elif context.user.id != policy["approver_user_id"]:
                raise ProductWorkAccessError("仅政策指定的实际批准人可办理")
            receipts = tables.project_execution_receipts
            fingerprint = digest(
                {"execution_id": str(execution_id), **command.model_dump(mode="json")}
            )
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
                    raise ProductWorkError("请求编号已用于不同批准动作")
                return _record(prior["snapshot"])
            if digest(_plain(row)) != command.expected_digest:
                raise ProductWorkError("执行申请已变化，请刷新")
            if connection.execute(
                select(tables.initial_plan_applications.c.id).where(
                    tables.initial_plan_applications.c.tenant_id == context.tenant.id,
                    tables.initial_plan_applications.c.execution_request_id == row["id"],
                )
            ).first():
                raise ProductWorkError(
                    "计划已独立应用，原批准作为历史保留；后续调整通过项目变更办理"
                )
            if row["state"] != "pending_approval" and not (
                row["state"] == "approved" and command.action == "withdraw"
            ):
                raise ProductWorkError("当前状态不能办理此动作")
            latest = _policy(connection, context.tenant.id, project_id)
            if command.action != "withdraw" and (
                latest["id"] != policy["id"]
                or connection.execute(
                    select(table.c.id)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.project_id == project_id,
                        table.c.round_no > row["round_no"],
                    )
                    .limit(1)
                ).first()
            ):
                raise ProductWorkError("政策或申请已有新版本，请办理最新一轮")
            receipt_id = uuid4()
            now = datetime.now(UTC)
            approval = row["approval"]
            if command.action == "approve":
                original_requesters = (row["snapshot"].get("policy_renewal") or {}).get(
                    "original_requester_ids", []
                )
                if policy["four_eyes"] and str(context.user.id) in {
                    str(row["created_by_user_id"]),
                    *original_requesters,
                }:
                    raise ProductWorkError("本项目政策要求批准人与本申请历次提交人分离")
                if project["status"] not in ("proposed", "approved", "active", "on_hold"):
                    raise ProductWorkError("项目须先提交为待批准状态，且尚未结束，才能办理执行批准")
                conversion = ensure_conversion(connection, context.tenant.id, project_id)
                review = (
                    connection.execute(
                        select(tables.initial_plan_reviews).where(
                            tables.initial_plan_reviews.c.tenant_id == context.tenant.id,
                            tables.initial_plan_reviews.c.id == row["plan_review_id"],
                        )
                    )
                    .mappings()
                    .one()
                )
                snapshot, basis_digest = execution_snapshot(
                    connection, context, project, review, policy, conversion
                )
                if basis_digest != row["basis_digest"]:
                    raise ProductWorkError("计划、需求、评审或执行依据已变化，请重新申请")
                if snapshot["blockers"]:
                    raise ProductWorkError("执行条件未就绪：" + "；".join(snapshot["blockers"][:8]))
                approval = ApprovalRef(
                    approval_id=receipt_id,
                    payload_digest=row["plan_digest"],
                    policy_version=f"project_execution.v{policy['version']}",
                    approved_by_user_id=context.user.id,
                    approved_at=now,
                ).model_dump(mode="json")
            state = {"approve": "approved", "reject": "rejected", "withdraw": "withdrawn"}[
                command.action
            ]
            updated = (
                connection.execute(
                    table.update()
                    .where(table.c.tenant_id == context.tenant.id, table.c.id == execution_id)
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
                    execution_request_id=execution_id,
                    actor_user_id=context.user.id,
                    request_id=command.request_id,
                    request_digest=fingerprint,
                    snapshot=_plain(updated),
                    reason=command.reason,
                )
            )
            _event(connection, context, project_id, updated, state, command.reason, receipt_id)
            if command.action == "approve" and project["status"] == "proposed":
                after = (
                    connection.execute(
                        tables.projects.update()
                        .where(
                            tables.projects.c.tenant_id == context.tenant.id,
                            tables.projects.c.id == project_id,
                        )
                        .values(status="approved", updated_at=now)
                        .returning(tables.projects)
                    )
                    .mappings()
                    .one()
                )
                EventAuditWriter(
                    connection,
                    tenant_id=context.tenant.id,
                    actor_user_id=context.user.id,
                    project_id=project_id,
                ).record(
                    EventDraft(
                        event_id=f"project-execution-approved:{receipt_id}",
                        event_type="PROJECT_STATUS_CHANGED",
                        source="project_service",
                        entity_id=project_id,
                        payload={"from_status": "proposed", "to_status": "approved"},
                    ),
                    AuditDraft(
                        action="project.transition",
                        before_snapshot=_plain(project),
                        after_snapshot=_plain(after),
                        context={"execution_request_id": str(execution_id)},
                    ),
                )
            return _record(updated)


def guard_execution_transition(
    connection: Connection, tenant_id: UUID, project_id: UUID, to_status: str, current_status: str
) -> None:
    managed = connection.execute(
        select(tables.case_project_conversions.c.id).where(
            tables.case_project_conversions.c.tenant_id == tenant_id,
            tables.case_project_conversions.c.project_id == project_id,
        )
    ).first() or _policy(connection, tenant_id, project_id)
    if not managed:
        return
    if to_status == "approved":
        raise ProjectExecutionNotReadyError("请从执行申请办理具名批准，不能仅切换项目状态")
    if (
        current_status == "approved"
        and to_status == "active"
        and connection.execute(
            select(tables.initial_plan_applications.c.id).where(
                tables.initial_plan_applications.c.tenant_id == tenant_id,
                tables.initial_plan_applications.c.project_id == project_id,
            )
        ).first()
        is None
    ):
        raise ProjectExecutionNotReadyError("请先独立应用已批准计划的任务和基线，再激活项目")
