"""Independent DCP/TR rounds, named policy authority and current-source readiness."""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import ApprovalRef, Key, ReviewRecord, ScopeRef, SourceRef, Text
from app.contracts.object_operations import (
    CommandPrecondition,
    ReviewFinalizedPayload,
    ReviewFinalizeRequest,
)
from app.db.schema import tables
from app.domain.case_requirements import _case
from app.domain.opportunity_requirements import requirement_snapshot
from app.domain.product_workspace import (
    Input,
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.review_materials import (
    MaterialChoice,
    authorize_materials,
    case_project,
    material_blockers,
    resolve_materials,
)
from app.domain.workflow_templates import NPD_WORKFLOW_TEMPLATE
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

Kind = Literal["dcp", "technical_review"]
Outcome = Literal["approved", "conditional", "hold", "rejected"]
STAGES = {"charter", *(stage.code for stage in NPD_WORKFLOW_TEMPLATE.stages)}


class ReviewPolicyDraft(Input):
    request_id: UUID
    review_kind: Kind
    stage_code: Key
    expected_version: int = Field(ge=0)
    chair_user_id: UUID
    reviewer_ids: tuple[UUID, ...] = Field(min_length=1, max_length=30)
    four_eyes: bool = True
    valid_days: int = Field(ge=1, le=3660)
    authority_basis: Text

    @model_validator(mode="after")
    def assignments(self) -> Self:
        if len(set(self.reviewer_ids)) != len(self.reviewer_ids) or self.stage_code not in STAGES:
            raise ValueError("评审人员不能重复，须选择立项或实际工作流阶段")
        return self


class ReviewBrief(Input):
    context: Text
    options: tuple[Text, ...] = Field(min_length=2, max_length=30)
    tradeoffs: Text
    consequences: Text
    recommendation: Text


class ReviewDraft(Input):
    request_id: UUID
    policy_id: UUID
    title: Text
    brief: ReviewBrief
    materials: tuple[MaterialChoice, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def unique_materials(self) -> Self:
        if len({(item.kind, item.id) for item in self.materials}) != len(self.materials):
            raise ValueError("同一技术材料不能重复选择")
        return self


class ReviewAction(CommandPrecondition):
    action: Literal["submit", "withdraw"]
    reason: Text


class ReviewSignoff(CommandPrecondition):
    outcome: Outcome
    rationale: Text
    conditions: tuple[Text, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def conditional(self) -> Self:
        if self.outcome == "conditional" and not self.conditions:
            raise ValueError("有条件结论必须写明条件")
        return self


def _user(connection: Connection, tenant_id: UUID, user_id: UUID) -> Any:
    row = (
        connection.execute(
            select(tables.users).where(
                tables.users.c.tenant_id == tenant_id,
                tables.users.c.id == user_id,
                tables.users.c.is_active.is_(True),
                tables.users.c.role.not_in(("supplier", "customer")),
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("评审授权人员须为本租户的有效内部用户")
    return row


def _policy(connection: Connection, tenant_id: UUID, case_id: UUID, policy_id: UUID) -> Any:
    row = (
        connection.execute(
            select(tables.case_review_policies).where(
                tables.case_review_policies.c.tenant_id == tenant_id,
                tables.case_review_policies.c.case_id == case_id,
                tables.case_review_policies.c.id == policy_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkAccessError("评审政策不存在或不可访问")
    return row


def _policies(connection: Connection, tenant_id: UUID, case_id: UUID) -> list[Any]:
    table = tables.case_review_policies
    ranked = (
        select(
            table,
            func.row_number()
            .over(
                partition_by=(table.c.review_kind, table.c.stage_code),
                order_by=table.c.version.desc(),
            )
            .label("position"),
        )
        .where(table.c.tenant_id == tenant_id, table.c.case_id == case_id)
        .subquery()
    )
    return list(
        connection.execute(
            select(ranked)
            .where(ranked.c.position == 1)
            .order_by(ranked.c.stage_code, ranked.c.review_kind)
        ).mappings()
    )


def review_basis(
    connection: Connection, tenant_id: UUID, case: Any, *, lock: bool = False
) -> dict[str, Any]:
    link = tables.case_requirement_links
    ranked = (
        select(
            link.c.requirement_id,
            link.c.action,
            func.row_number()
            .over(partition_by=link.c.requirement_id, order_by=link.c.sequence.desc())
            .label("position"),
        )
        .where(link.c.tenant_id == tenant_id, link.c.case_id == case["id"])
        .subquery()
    )
    ids = {case["requirement_id"]} | set(
        connection.execute(
            select(ranked.c.requirement_id).where(
                ranked.c.position == 1, ranked.c.action != "release"
            )
        ).scalars()
    )
    statement = (
        select(tables.requirements)
        .where(tables.requirements.c.tenant_id == tenant_id, tables.requirements.c.id.in_(ids))
        .order_by(tables.requirements.c.id)
    )
    requirements = [
        requirement_snapshot(row)
        for row in connection.execute(statement.with_for_update() if lock else statement).mappings()
    ]
    sequence = (
        connection.execute(
            select(func.max(link.c.sequence)).where(
                link.c.tenant_id == tenant_id, link.c.case_id == case["id"]
            )
        ).scalar_one()
        or 0
    )
    mapping, definition, release = (
        tables.definition_requirement_links,
        tables.product_definitions,
        tables.definition_releases,
    )
    record_rows = connection.execute(
        select(
            mapping.c.requirement_id,
            mapping.c.definition_id,
            definition.c.product_id,
            definition.c.revision_number,
        )
        .join(
            definition,
            (definition.c.tenant_id == mapping.c.tenant_id)
            & (definition.c.id == mapping.c.definition_id),
        )
        .where(mapping.c.tenant_id == tenant_id, mapping.c.requirement_id.in_(ids))
        .order_by(definition.c.revision_number.desc())
    ).mappings()
    records = list(record_rows)
    if lock:
        list(
            connection.execute(
                select(tables.product_nodes.c.id)
                .where(
                    tables.product_nodes.c.tenant_id == tenant_id,
                    tables.product_nodes.c.id.in_({row["product_id"] for row in records}),
                )
                .order_by(tables.product_nodes.c.id)
                .with_for_update()
            )
        )
    definitions = {}
    for row in records:
        key = f"{row['requirement_id']}:{row['product_id']}"
        if key in definitions:
            continue
        latest = (
            connection.execute(
                select(release)
                .where(release.c.tenant_id == tenant_id, release.c.product_id == row["product_id"])
                .order_by(release.c.sequence.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        definitions[key] = {
            **_plain(row),
            "release_id": str(latest["id"]) if latest else None,
            "is_current": latest is not None
            and latest["action"] == "publish"
            and latest["definition_id"] == row["definition_id"],
        }
    return {
        "case": {
            key: _plain(case)[key]
            for key in (
                "id",
                "tenant_id",
                "requirement_id",
                "code",
                "title",
                "summary",
                "business_case",
            )
        },
        "requirement_sequence": sequence,
        "requirements": requirements,
        "definitions": sorted(
            definitions.values(), key=lambda value: (value["requirement_id"], value["product_id"])
        ),
    }


def current_review_basis(
    connection: Connection, tenant_id: UUID, case: Any, stored: Any, *, lock: bool = False
) -> dict[str, Any]:
    result = review_basis(connection, tenant_id, case, lock=lock)
    if "materials" in stored:
        result["materials"] = resolve_materials(
            connection, tenant_id, case["id"], stored["materials"], lock=lock
        )
    return result


def review_sources_current(
    connection: Connection, tenant_id: UUID, case: Any, row: Any, *, lock: bool = False
) -> bool:
    try:
        return digest(
            current_review_basis(connection, tenant_id, case, row["basis"], lock=lock)
        ) == str(row["basis_digest"])
    except (ProductWorkError, ProductWorkAccessError):
        return False


def visible_review(connection: Connection, context: AuthContext, case_id: UUID, row: Any) -> bool:
    try:
        authorize_materials(
            connection,
            context.tenant.id,
            case_id,
            context.user.id,
            row["basis"].get("materials", []),
        )
        return True
    except ProductWorkAccessError:
        return False


def _basis_blockers(basis: dict[str, Any]) -> list[str]:
    result = [
        f"{row['code']}尚未批准"
        for row in basis["requirements"]
        if row["status"] not in {"approved", "converted"}
    ]
    result.extend(
        "定义来源已撤回或替代，须先将新定义关联到需求"
        for row in basis["definitions"]
        if not row["is_current"]
    )
    result.extend(material_blockers(basis.get("materials", [])))
    return list(dict.fromkeys(result))


def _row(connection: Connection, context: AuthContext, case_id: UUID, review_id: UUID) -> Any:
    row = (
        connection.execute(
            select(tables.case_reviews).where(
                tables.case_reviews.c.tenant_id == context.tenant.id,
                tables.case_reviews.c.case_id == case_id,
                tables.case_reviews.c.id == review_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkAccessError("评审轮次不存在或不可访问")
    return row


def _signoffs(connection: Connection, row: Any) -> list[Any]:
    return list(
        connection.execute(
            select(tables.case_review_signoffs).where(
                tables.case_review_signoffs.c.tenant_id == row["tenant_id"],
                tables.case_review_signoffs.c.review_id == row["id"],
            )
        ).mappings()
    )


def _emit(
    connection: Connection,
    context: AuthContext,
    case: Any,
    row: Any,
    action: str,
    *,
    command: Any = None,
    before: Any = None,
) -> None:
    event_key = digest(str(context.user.id) + command.idempotency_key) if command else uuid4()
    event_id = f"review:{row['id']}:{event_key}"
    EventAuditWriter(connection, tenant_id=context.tenant.id, actor_user_id=context.user.id).record(
        EventDraft(
            event_id=event_id,
            event_type="REVIEW_RECORD_CHANGED",
            source="review_service",
            entity_id=row["id"],
            payload={
                "case_id": str(case["id"]),
                "action": action,
                "object_version": row["version"],
            },
        ),
        AuditDraft(
            action=f"case_review.{action}",
            before_snapshot=_plain(before) if before else None,
            after_snapshot=_plain(row),
            context={
                "case_id": str(case["id"]),
                "request_key": command.idempotency_key if command else None,
                "command_digest": digest(command.model_dump(mode="json")) if command else None,
            },
        ),
    )


def _precondition(
    connection: Connection, context: AuthContext, row: Any, command: CommandPrecondition
) -> bool:
    log = tables.audit_log
    prior = connection.execute(
        select(log.c.context).where(
            log.c.tenant_id == context.tenant.id,
            log.c.entity_id == row["id"],
            log.c.actor_user_id == context.user.id,
            log.c.context["request_key"].as_string() == command.idempotency_key,
        )
    ).scalar_one_or_none()
    if prior:
        if prior["command_digest"] != digest(command.model_dump(mode="json")):
            raise ProductWorkError("同一请求不能用于不同评审操作")
        return False
    if row["version"] != command.expected_version or digest(_plain(row)) != command.payload_digest:
        raise ProductWorkError("评审内容或签核已变化，请刷新后再办理")
    return True


def _contract(row: Any) -> dict[str, Any]:
    source = SourceRef(
        tenant_id=row["tenant_id"],
        kind="review_basis",
        ref_id=row["id"],
        as_of=row["created_at"],
        digest=row["basis_digest"],
    )
    return ReviewRecord(
        id=row["id"],
        tenant_id=row["tenant_id"],
        scope=ScopeRef(kind="tenant", ref_id=row["tenant_id"]),
        version=row["version"],
        owner_user_id=row["created_by_user_id"],
        sources=(source,),
        review_kind=row["review_kind"],
        round_no=row["round_no"],
        policy_version=f"review-{row['policy_id']}",
        state=row["state"],
        outcome=row["outcome"],
        approval=ApprovalRef.model_validate(row["approval"]) if row["approval"] else None,
        conditions=tuple(row["conditions"]),
    ).model_dump(mode="json")


def case_review_blockers(
    connection: Connection, tenant_id: UUID, case: Any, stage_code: str, *, lock: bool = False
) -> list[dict[str, str]]:
    policies = [
        policy
        for policy in _policies(connection, tenant_id, case["id"])
        if policy["stage_code"] == stage_code
    ]
    basis = review_basis(connection, tenant_id, case, lock=lock)
    product_origin = bool(basis["definitions"]) or any(
        row["source"] == "product_definition" for row in basis["requirements"]
    )
    blockers = []
    if stage_code == "charter" and product_origin:
        for kind in {"dcp", "technical_review"} - {policy["review_kind"] for policy in policies}:
            blockers.append(
                {
                    "key": f"review_policy:{kind}:{stage_code}",
                    "kind": "review",
                    "label": f"立项尚未配置{kind}具名评审政策",
                }
            )
    for policy in policies:
        table = tables.case_reviews
        row = (
            connection.execute(
                select(table)
                .where(
                    table.c.tenant_id == tenant_id,
                    table.c.case_id == case["id"],
                    table.c.review_kind == policy["review_kind"],
                    table.c.stage_code == stage_code,
                )
                .order_by(table.c.round_no.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        reason = None
        if row is None or row["policy_id"] != policy["id"]:
            reason = "缺少当前政策下的评审"
        elif row["state"] != "finalized" or row["outcome"] != "approved":
            reason = "评审未完成或结论未通过；有条件结论须办理后重新评审"
        elif (
            policy["review_kind"] == "technical_review"
            and stage_code != "charter"
            and not row["basis"].get("materials")
        ):
            reason = "阶段技术评审缺少实际技术材料"
        elif row["expires_at"] <= datetime.now(UTC):
            reason = "结论已过期"
        elif not review_sources_current(connection, tenant_id, case, row, lock=lock):
            reason = "评审来源已变化"
        elif material_blockers(row["basis"].get("materials", [])):
            reason = "所引用技术材料当前未满足通过条件"
        else:
            try:
                for user_id in {
                    policy["chair_user_id"],
                    *(UUID(value) for value in policy["reviewer_ids"]),
                }:
                    _user(connection, tenant_id, user_id)
                    authorize_materials(
                        connection,
                        tenant_id,
                        case["id"],
                        user_id,
                        row["basis"].get("materials", []),
                    )
            except (ProductWorkError, ProductWorkAccessError):
                reason = "具名评审授权人员已失效"
        if reason:
            blockers.append(
                {
                    "key": f"review:{policy['id']}",
                    "kind": "review",
                    "label": f"{policy['review_kind']} / {stage_code}：{reason}",
                }
            )
    return blockers


class CaseReviewService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def list(
        self, context: AuthContext, case_id: UUID, *, review_id: UUID | None = None
    ) -> dict[str, Any]:
        _role(context, Action.DEVELOPMENT_CASE_VIEW)
        _role(context, Action.REQUIREMENT_VIEW)
        with self.engine.connect() as connection:
            case = _case(connection, context, case_id)
            table = tables.case_reviews
            rows = list(
                connection.execute(
                    select(table)
                    .where(table.c.tenant_id == context.tenant.id, table.c.case_id == case_id)
                    .order_by(table.c.round_no.desc(), table.c.created_at.desc())
                    .limit(201)
                ).mappings()
            )
            rows = [row for row in rows if visible_review(connection, context, case_id, row)]
            has_more = len(rows) > 200
            rows = rows[:200]
            if review_id is not None:
                target = _row(connection, context, case_id, review_id)
                if not visible_review(connection, context, case_id, target):
                    raise ProductWorkAccessError("评审轮次不存在或不可访问")
                rows = [target, *(row for row in rows if row["id"] != review_id)]
            latest_rounds = {
                (item.review_kind, item.stage_code): item.round_no
                for item in connection.execute(
                    select(
                        table.c.review_kind,
                        table.c.stage_code,
                        func.max(table.c.round_no).label("round_no"),
                    )
                    .where(table.c.tenant_id == context.tenant.id, table.c.case_id == case_id)
                    .group_by(table.c.review_kind, table.c.stage_code)
                )
            }
            people = connection.execute(
                select(tables.users.c.id, tables.users.c.display_name).where(
                    tables.users.c.tenant_id == context.tenant.id,
                    tables.users.c.is_active.is_(True),
                    tables.users.c.role.not_in(("supplier", "customer")),
                )
            ).mappings()
            return {
                "policies": [
                    _plain(row) for row in _policies(connection, context.tenant.id, case_id)
                ],
                "items": [
                    {
                        **_plain(row),
                        "payload_digest": digest(_plain(row)),
                        "is_latest": row["round_no"]
                        == latest_rounds[(row["review_kind"], row["stage_code"])],
                        "contract": _contract(row),
                        "source_is_current": review_sources_current(
                            connection, context.tenant.id, case, row
                        ),
                        "signoffs": [_plain(signoff) for signoff in _signoffs(connection, row)],
                    }
                    for row in rows
                ],
                "policy_versions": [
                    _plain(policy)
                    for policy in connection.execute(
                        select(tables.case_review_policies).where(
                            tables.case_review_policies.c.tenant_id == context.tenant.id,
                            tables.case_review_policies.c.case_id == case_id,
                            tables.case_review_policies.c.id.in_(
                                {row["policy_id"] for row in rows}
                            ),
                        )
                    ).mappings()
                ],
                "has_more": has_more,
                "members": [_plain(row) for row in people],
                "can_configure": is_allowed(context.user.role, Action.TENANT_MANAGE),
                "can_prepare": is_allowed(context.user.role, Action.DEVELOPMENT_CASE_EDIT),
                "current_user_id": str(context.user.id),
                "charter_blockers": case_review_blockers(
                    connection, context.tenant.id, case, "charter"
                ),
            }

    def policy(
        self, context: AuthContext, case_id: UUID, draft: ReviewPolicyDraft
    ) -> dict[str, Any]:
        _role(context, Action.TENANT_MANAGE)
        with self.engine.begin() as connection:
            case_project(connection, context.tenant.id, case_id, lock=True)
            case = _case(connection, context, case_id, lock=True)
            table = tables.case_review_policies
            previous = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.case_id == case_id,
                        table.c.created_by_user_id == context.user.id,
                        table.c.request_id == draft.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            fingerprint = digest(draft.model_dump(mode="json"))
            if previous:
                if previous["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号内容不一致")
                return _plain(previous)
            latest = next(
                (
                    row
                    for row in _policies(connection, context.tenant.id, case_id)
                    if row["review_kind"] == draft.review_kind
                    and row["stage_code"] == draft.stage_code
                ),
                None,
            )
            if draft.expected_version != (latest["version"] if latest else 0):
                raise ProductWorkError("评审政策已更新，请刷新")
            for user_id in {draft.chair_user_id, *draft.reviewer_ids}:
                _user(connection, context.tenant.id, user_id)
            values = draft.model_dump(exclude={"expected_version", "reviewer_ids"})
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        **values,
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        case_id=case_id,
                        version=draft.expected_version + 1,
                        reviewer_ids=[str(value) for value in draft.reviewer_ids],
                        created_by_user_id=context.user.id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            _emit(connection, context, case, row, "policy_published")
            return _plain(row)

    def create(self, context: AuthContext, case_id: UUID, draft: ReviewDraft) -> dict[str, Any]:
        _role(context, Action.DEVELOPMENT_CASE_EDIT)
        _role(context, Action.REQUIREMENT_VIEW)
        with self.engine.begin() as connection:
            case_project(connection, context.tenant.id, case_id, lock=True)
            case = _case(connection, context, case_id, lock=True)
            table = tables.case_reviews
            prior = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.case_id == case_id,
                        table.c.created_by_user_id == context.user.id,
                        table.c.request_id == draft.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            fingerprint = digest(draft.model_dump(mode="json"))
            if prior:
                if prior["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号内容不一致")
                authorize_materials(
                    connection,
                    context.tenant.id,
                    case_id,
                    context.user.id,
                    prior["basis"].get("materials", []),
                )
                return {**_plain(prior), "payload_digest": digest(_plain(prior))}
            policy = _policy(connection, context.tenant.id, case_id, draft.policy_id)
            if draft.policy_id not in {
                row["id"] for row in _policies(connection, context.tenant.id, case_id)
            }:
                raise ProductWorkError("只能使用当前政策发起新轮次")
            if policy["four_eyes"] and str(context.user.id) in policy["reviewer_ids"]:
                raise ProductWorkError("此政策要求准备人与必签人员分离，请由其他内部人员准备评审")
            round_no = (
                connection.execute(
                    select(func.max(table.c.round_no)).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.case_id == case_id,
                        table.c.review_kind == policy["review_kind"],
                        table.c.stage_code == policy["stage_code"],
                    )
                ).scalar_one()
                or 0
            )
            choices = [choice.model_dump(mode="json") for choice in draft.materials]
            if (
                policy["review_kind"] == "technical_review"
                and policy["stage_code"] != "charter"
                and not choices
            ):
                raise ProductWorkError("项目阶段TR须选择实际技术材料，不能仅用案例描述替代")
            for user_id in {
                context.user.id,
                policy["chair_user_id"],
                *(UUID(value) for value in policy["reviewer_ids"]),
            }:
                authorize_materials(connection, context.tenant.id, case_id, user_id, choices)
            basis = review_basis(connection, context.tenant.id, case, lock=True)
            basis["materials"] = resolve_materials(
                connection, context.tenant.id, case_id, choices, check_digest=True, lock=True
            )
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        case_id=case_id,
                        policy_id=policy["id"],
                        review_kind=policy["review_kind"],
                        stage_code=policy["stage_code"],
                        round_no=round_no + 1,
                        title=draft.title,
                        brief=draft.brief.model_dump(mode="json"),
                        basis=basis,
                        basis_digest=digest(basis),
                        created_by_user_id=context.user.id,
                        request_id=draft.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            _emit(connection, context, case, row, "created")
            return {**_plain(row), "payload_digest": digest(_plain(row))}

    def act(
        self,
        context: AuthContext,
        case_id: UUID,
        review_id: UUID,
        command: ReviewAction | ReviewSignoff | ReviewFinalizeRequest,
    ) -> dict[str, Any]:
        _role(context, Action.DEVELOPMENT_CASE_VIEW)
        _role(context, Action.REQUIREMENT_VIEW)
        with self.engine.begin() as connection:
            case_project(connection, context.tenant.id, case_id, lock=True)
            case = _case(connection, context, case_id, lock=True)
            row = _row(connection, context, case_id, review_id)
            policy = _policy(connection, context.tenant.id, case_id, row["policy_id"])
            authorize_materials(
                connection,
                context.tenant.id,
                case_id,
                context.user.id,
                row["basis"].get("materials", []),
            )
            if not _precondition(connection, context, row, command):
                return {**_plain(row), "payload_digest": digest(_plain(row))}
            if row["state"] in {"finalized", "withdrawn"}:
                raise ProductWorkError("历史结论不能改写，请发起新轮次")
            withdrawing = isinstance(command, ReviewAction) and command.action == "withdraw"
            if not withdrawing:
                if row["policy_id"] not in {
                    item["id"] for item in _policies(connection, context.tenant.id, case_id)
                }:
                    raise ProductWorkError("政策已更新，请按新政策发起评审")
                latest_round = connection.execute(
                    select(func.max(tables.case_reviews.c.round_no)).where(
                        tables.case_reviews.c.tenant_id == context.tenant.id,
                        tables.case_reviews.c.case_id == case_id,
                        tables.case_reviews.c.review_kind == row["review_kind"],
                        tables.case_reviews.c.stage_code == row["stage_code"],
                    )
                ).scalar_one()
                if latest_round != row["round_no"]:
                    raise ProductWorkError("已有新轮次，旧轮次仅可撤回或查看")
            action: str
            values: dict[str, Any]
            if isinstance(command, ReviewAction):
                if context.user.id not in {row["created_by_user_id"], policy["chair_user_id"]}:
                    raise ProductWorkAccessError("仅准备人或政策指定批准人可办理")
                if command.action == "submit" and row["state"] != "draft":
                    raise ProductWorkError("只能送审草稿")
                values = {
                    "state": "in_review" if command.action == "submit" else "withdrawn",
                    "rationale": command.reason,
                }
                action = command.action
            else:
                if row["state"] != "in_review":
                    raise ProductWorkError("当前轮次尚未送审")
                for user_id in {
                    policy["chair_user_id"],
                    *(UUID(value) for value in policy["reviewer_ids"]),
                }:
                    _user(connection, context.tenant.id, user_id)
                    authorize_materials(
                        connection,
                        context.tenant.id,
                        case_id,
                        user_id,
                        row["basis"].get("materials", []),
                    )
                if isinstance(command, ReviewSignoff):
                    if str(context.user.id) not in policy["reviewer_ids"] or (
                        policy["four_eyes"] and context.user.id == row["created_by_user_id"]
                    ):
                        raise ProductWorkAccessError("仅本轮政策中的独立必签人员可提交意见")
                    if any(
                        receipt["reviewer_user_id"] == context.user.id
                        for receipt in _signoffs(connection, row)
                    ):
                        raise ProductWorkError("你已提交本轮意见；需要修订时应发起新轮次")
                    connection.execute(
                        tables.case_review_signoffs.insert().values(
                            id=uuid4(),
                            tenant_id=context.tenant.id,
                            case_id=case_id,
                            review_id=review_id,
                            reviewer_user_id=context.user.id,
                            outcome=command.outcome,
                            rationale=command.rationale,
                            conditions=list(command.conditions),
                            basis_digest=row["basis_digest"],
                        )
                    )
                    values = {}
                    action = "signoff"
                else:
                    if command.review_id != review_id or context.user.id != policy["chair_user_id"]:
                        raise ProductWorkAccessError("结论只能由政策指定批准人确认")
                    receipts = _signoffs(connection, row)
                    if {str(item["reviewer_user_id"]) for item in receipts} != set(
                        policy["reviewer_ids"]
                    ):
                        raise ProductWorkError("必签意见尚未收齐")
                    outcomes = {item["outcome"] for item in receipts}
                    outcome = next(
                        value
                        for value in ("rejected", "hold", "conditional", "approved")
                        if value in outcomes
                    )
                    conditions = list(
                        dict.fromkeys(value for item in receipts for value in item["conditions"])
                    )
                    if command.outcome != outcome or set(command.conditions) != set(conditions):
                        raise ProductWorkError("最终结论与条件须完整保留必签意见")
                    if outcome == "approved":
                        blockers = _basis_blockers(row["basis"])
                        if blockers:
                            raise ProductWorkError("；".join(blockers))
                    now = datetime.now(UTC)
                    approval = ApprovalRef(
                        approval_id=uuid4(),
                        payload_digest=digest(
                            {
                                "basis": row["basis"],
                                "brief": row["brief"],
                                "signoffs": [_plain(item) for item in receipts],
                                "outcome": outcome,
                                "conditions": conditions,
                            }
                        ),
                        policy_version=f"review-{policy['id']}",
                        approved_by_user_id=context.user.id,
                        approved_at=now,
                    )
                    values = {
                        "state": "finalized",
                        "outcome": outcome,
                        "conditions": conditions,
                        "rationale": command.rationale,
                        "approval": approval.model_dump(mode="json"),
                        "expires_at": now + timedelta(days=policy["valid_days"]),
                    }
                    action = "finalized"
            if not (isinstance(command, ReviewAction) and command.action == "withdraw") and (
                digest(
                    current_review_basis(
                        connection, context.tenant.id, case, row["basis"], lock=True
                    )
                )
                != row["basis_digest"]
            ):
                raise ProductWorkError("需求、范围、定义或技术材料已变化，请使用当前资料发起新轮次")
            updated = (
                connection.execute(
                    tables.case_reviews.update()
                    .where(
                        tables.case_reviews.c.tenant_id == context.tenant.id,
                        tables.case_reviews.c.id == review_id,
                    )
                    .values(**values, version=row["version"] + 1, updated_at=datetime.now(UTC))
                    .returning(tables.case_reviews)
                )
                .mappings()
                .one()
            )
            _emit(connection, context, case, updated, action, command=command, before=row)
            if action == "finalized":
                payload = ReviewFinalizedPayload(
                    object_id=review_id,
                    object_version=updated["version"],
                    operation_id=uuid4(),
                    correlation_id=case_id,
                    causation_event_row_id=None,
                    review_kind=updated["review_kind"],
                    round_no=updated["round_no"],
                    outcome=updated["outcome"],
                    policy_version=f"review-{policy['id']}",
                )
                EventAuditWriter(
                    connection, tenant_id=context.tenant.id, actor_user_id=context.user.id
                ).record(
                    EventDraft(
                        event_id=f"review:{review_id}:finalized",
                        event_type="REVIEW_FINALIZED",
                        source="review_service",
                        entity_id=review_id,
                        payload=payload.model_dump(mode="json"),
                    ),
                    AuditDraft(
                        action="case_review.finalized_event", after_snapshot=_plain(updated)
                    ),
                )
            return {
                **_plain(updated),
                "payload_digest": digest(_plain(updated)),
                "contract": _contract(updated),
            }


class CaseReviewNotReadyError(ValueError):
    pass


def require_case_reviews_ready(connection: Connection, tenant_id: UUID, case: Any) -> None:
    blockers = case_review_blockers(connection, tenant_id, case, "charter", lock=True)
    if blockers:
        raise CaseReviewNotReadyError("；".join(item["label"] for item in blockers))


def scope_revalidated(connection: Connection, tenant_id: UUID, case: Any) -> bool:
    kinds = {
        policy["review_kind"]
        for policy in _policies(connection, tenant_id, case["id"])
        if policy["stage_code"] == "charter"
    }
    return kinds == {"dcp", "technical_review"} and not case_review_blockers(
        connection, tenant_id, case, "charter", lock=True
    )


def project_review_blockers(
    connection: Connection, tenant_id: UUID, project_id: UUID, stage_id: UUID, *, lock: bool = False
) -> list[dict[str, str]]:
    project = connection.execute(
        select(tables.projects.c.development_case_id).where(
            tables.projects.c.tenant_id == tenant_id, tables.projects.c.id == project_id
        )
    ).scalar_one()
    if project is None:
        return []
    query = select(tables.development_cases).where(
        tables.development_cases.c.tenant_id == tenant_id, tables.development_cases.c.id == project
    )
    case = connection.execute(query.with_for_update() if lock else query).mappings().one()
    stage = connection.execute(
        select(tables.stages.c.code).where(
            tables.stages.c.tenant_id == tenant_id,
            tables.stages.c.workflow_id
            == select(tables.projects.c.workflow_id)
            .where(tables.projects.c.tenant_id == tenant_id, tables.projects.c.id == project_id)
            .scalar_subquery(),
            tables.stages.c.id == stage_id,
        )
    ).scalar_one()
    return case_review_blockers(connection, tenant_id, case, stage, lock=lock)
