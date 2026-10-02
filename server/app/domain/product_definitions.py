"""Structured definitions, scoped professional review and append-only releases."""

from datetime import UTC, datetime
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import ApprovalRef, Contract, Digest, Key, SourceRef, Text
from app.contracts.object_operations import (
    CommandPrecondition,
    DefinitionPublishedPayload,
    DefinitionPublishRequest,
)
from app.contracts.product_records import FactStatement, ProductDefinition, SpecificationItem
from app.db.schema import tables
from app.domain.definition_inheritance import expand_definition, sparse_content
from app.domain.market_analysis import _fact
from app.domain.product_evidence import evidence_quality, resolve_evidence
from app.domain.product_strategies import _manager
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
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

DISCIPLINES = ("id", "md", "ee", "fw", "dqe")


class DefinitionContent(Contract):
    title: Text
    owner_user_id: UUID
    target_users: tuple[Text, ...] = Field(min_length=1, max_length=100)
    scenarios: tuple[Text, ...] = Field(min_length=1, max_length=100)
    included_features: tuple[Key, ...] = Field(default=(), max_length=100)
    excluded_features: tuple[Key, ...] = Field(default=(), max_length=100)
    region_constraints: tuple[FactStatement, ...] = Field(default=(), max_length=100)
    target_cost: FactStatement
    price_position: FactStatement
    launch_window: FactStatement
    service_requirements: tuple[FactStatement, ...] = Field(default=(), max_length=100)
    success_criteria: tuple[FactStatement, ...] = Field(min_length=1, max_length=100)
    items: tuple[SpecificationItem, ...] = Field(min_length=1, max_length=300)
    reviewers: dict[Literal["id", "md", "ee", "fw", "dqe"], UUID] = Field(default_factory=dict)
    change_reason: Text

    @model_validator(mode="after")
    def content_consistency(self) -> Self:
        if set(self.included_features) & set(self.excluded_features):
            raise ValueError("包含和排除的功能不能重复")
        if any(
            len(set(values)) != len(values)
            for values in (self.included_features, self.excluded_features)
        ):
            raise ValueError("功能标识不能重复")
        if len({item.item_key for item in self.items}) != len(self.items):
            raise ValueError("规格条目标识不能重复")
        facts = (
            *self.region_constraints,
            self.target_cost,
            self.price_position,
            self.launch_window,
            *self.service_requirements,
            *self.success_criteria,
            *(item.rationale for item in self.items),
        )
        if any(fact.approval is not None for fact in facts):
            raise ValueError("定义内容不接受客户端提供的批准引用")
        return self


class DefinitionDraft(Input):
    request_id: UUID
    product_id: UUID
    strategy_id: UUID
    supersedes_id: UUID | None = None
    base_definition_id: UUID | None = None
    content: DefinitionContent


class DefinitionEdit(CommandPrecondition):
    content: DefinitionContent
    reason: Text


class DefinitionAction(CommandPrecondition):
    action: Literal["submit", "return", "publish", "withdraw"]
    reason: Text
    reviewed_source_digest: Digest | None = None
    expected_release_id: UUID | None = None


class DefinitionReview(CommandPrecondition):
    discipline: Literal["id", "md", "ee", "fw", "dqe"]
    review_round: int = Field(ge=1)
    reviewed_source_digest: Digest
    outcome: Literal["approved", "changes_requested"]
    reason: Text
    sources: tuple[SourceRef, ...] = Field(default=(), max_length=30)


def definition_digest(row: Any) -> str:
    value = {
        key: row[key]
        for key in (
            "id",
            "tenant_id",
            "product_id",
            "strategy_id",
            "strategy_ref",
            "revision_number",
            "content",
        )
    }
    if row.get("base_definition_id") is not None:
        value.update(
            base_definition_ref=row["base_definition_ref"], parent_updates=row["parent_updates"]
        )
    return digest(_plain(value))


def _release(connection: Connection, context: AuthContext, product_id: UUID) -> Any:
    table = tables.definition_releases
    return (
        connection.execute(
            select(table)
            .where(table.c.tenant_id == context.tenant.id, table.c.product_id == product_id)
            .order_by(table.c.sequence.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def _row(
    connection: Connection,
    context: AuthContext,
    space_id: UUID,
    definition_id: UUID,
    *,
    write: bool = False,
) -> Any:
    table = tables.product_definitions
    query = select(table).where(
        table.c.tenant_id == context.tenant.id,
        table.c.market_space_id == space_id,
        table.c.id == definition_id,
    )
    row = connection.execute(query.with_for_update() if write else query).mappings().one_or_none()
    if row is None:
        raise ProductWorkAccessError("产品定义不存在或不可访问")
    _line(
        connection,
        context,
        space_id,
        row["product_line_id"],
        access="contributor" if write else "viewer",
        writable=write,
    )
    return expand_definition(connection, row)


def _resolve_content(
    connection: Connection,
    context: AuthContext,
    space_id: UUID,
    line_id: UUID,
    content: DefinitionContent,
    previous: Any = None,
) -> dict[str, Any]:
    _member(connection, context, space_id, content.owner_user_id, line_id=line_id)
    if previous:
        old_keys = {item["item_key"] for item in previous["content"]["items"]}
        if not old_keys.issubset({item.item_key for item in content.items}):
            raise ProductWorkError(
                "已发布的条目标识必须保留；不再适用时记录处置原因，不能删除后重新编号"
            )
    for user_id in set(content.reviewers.values()):
        _member(connection, context, space_id, user_id, line_id=line_id)
    value = content.model_dump(mode="json")
    for key in ("target_cost", "price_position", "launch_window"):
        value[key] = _fact(connection, context, getattr(content, key))
    for key in ("region_constraints", "service_requirements", "success_criteria"):
        value[key] = [_fact(connection, context, fact) for fact in getattr(content, key)]
    for index, item in enumerate(content.items):
        if item.owner_user_id:
            _member(connection, context, space_id, item.owner_user_id, line_id=line_id)
        value["items"][index]["rationale"] = _fact(connection, context, item.rationale)
    return value


def _readiness(row: Any, reviews: list[Any], *, reviewed: bool) -> list[str]:
    blockers = []
    for item in row["content"]["items"]:
        if item["required_for_release"] and item["state"] != "confirmed":
            blockers.append(f"必需规格 {item['item_key']} 尚未确认")
    for discipline in DISCIPLINES:
        if discipline not in row["content"]["reviewers"]:
            blockers.append(f"尚未指定 {discipline.upper()} 协审人")
        if reviewed and not any(
            review["discipline"] == discipline
            and review["review_round"] == row["review_round"]
            and review["review_digest"] == row["review_digest"]
            and review["outcome"] == "approved"
            for review in reviews
        ):
            blockers.append(f"{discipline.upper()} 尚未通过当前轮次协审")
    return blockers


def definition_diff(before: Any, after: Any) -> dict[str, Any]:
    prior = before["content"] if before else {}
    current = after["content"]
    old_items = {item["item_key"]: item for item in prior.get("items", [])}
    new_items = {item["item_key"]: item for item in current["items"]}
    return {
        "base_definition_id": str(before["id"]) if before else None,
        "sections": [
            {"field": key, "before": prior.get(key), "after": value}
            for key, value in current.items()
            if key != "items" and prior.get(key) != value
        ],
        "items": [
            {
                "item_key": key,
                "change": "added"
                if key not in old_items
                else "removed"
                if key not in new_items
                else "changed",
                "before": old_items.get(key),
                "after": new_items.get(key),
            }
            for key in sorted(set(old_items) | set(new_items))
            if old_items.get(key) != new_items.get(key)
        ],
        "strategy_changed": before is not None and before["strategy_id"] != after["strategy_id"],
    }


def _definition(connection: Connection, context: AuthContext, row: Any) -> dict[str, Any]:
    row = expand_definition(connection, row)
    content = row["content"]
    refs = []
    for fact in (
        *content["region_constraints"],
        content["target_cost"],
        content["price_position"],
        content["launch_window"],
        *content["service_requirements"],
        *content["success_criteria"],
        *(item["rationale"] for item in content["items"]),
    ):
        refs.extend(fact["sources"])
    contract = ProductDefinition(
        id=row["id"],
        tenant_id=row["tenant_id"],
        scope=_scope_ref(row),
        version=row["version"],
        owner_user_id=row["owner_user_id"],
        sources=tuple({ref["ref_id"]: ref for ref in refs}.values()),
        product_id=row["product_id"],
        strategy_ref=row["strategy_ref"],
        state=row["state"],
        approval=row["approval"],
        published_at=row["published_at"],
        **{
            key: content[key]
            for key in (
                "title",
                "target_users",
                "scenarios",
                "included_features",
                "excluded_features",
                "region_constraints",
                "target_cost",
                "price_position",
                "launch_window",
                "service_requirements",
                "success_criteria",
                "items",
            )
        },
    )
    reviews = list(
        connection.execute(
            select(tables.definition_reviews)
            .where(
                tables.definition_reviews.c.tenant_id == context.tenant.id,
                tables.definition_reviews.c.definition_id == row["id"],
            )
            .order_by(tables.definition_reviews.c.created_at.desc())
        ).mappings()
    )
    latest = _release(connection, context, row["product_id"])
    previous = (
        _row(connection, context, row["market_space_id"], row["supersedes_id"])
        if row["supersedes_id"]
        else None
    )
    parent_definition = (
        _row(connection, context, row["market_space_id"], row["base_definition_id"])
        if row["base_definition_id"]
        else None
    )
    product = (
        connection.execute(
            select(tables.product_nodes.c.name, tables.product_nodes.c.code).where(
                tables.product_nodes.c.tenant_id == context.tenant.id,
                tables.product_nodes.c.id == row["product_id"],
            )
        )
        .mappings()
        .one()
    )
    strategy = (
        connection.execute(
            select(
                tables.product_strategies.c.title, tables.product_strategies.c.revision_number
            ).where(
                tables.product_strategies.c.tenant_id == context.tenant.id,
                tables.product_strategies.c.id == row["strategy_id"],
            )
        )
        .mappings()
        .one()
    )
    return {
        **_record(row),
        "contract": contract.model_dump(mode="json"),
        "product_name": product["name"],
        "product_code": product["code"],
        "strategy_title": strategy["title"],
        "strategy_revision": strategy["revision_number"],
        "reviews": [_plain(review) for review in reviews],
        "review_blockers": _readiness(row, reviews, reviewed=False),
        "publication_blockers": _readiness(row, reviews, reviewed=True),
        "current_release": _plain(latest) if latest else None,
        "is_current": latest is not None
        and latest["definition_id"] == row["id"]
        and latest["action"] == "publish",
        "has_successor": connection.execute(
            select(tables.product_definitions.c.id).where(
                tables.product_definitions.c.tenant_id == context.tenant.id,
                tables.product_definitions.c.supersedes_id == row["id"],
            )
        ).first()
        is not None,
        "can_publish": _manager(
            connection, context, row["market_space_id"], row["product_line_id"]
        ),
        "source_warnings": evidence_quality(connection, context, refs),
        "stable_item_keys": sorted(
            {
                item["item_key"]
                for source in (previous, parent_definition)
                if source
                for item in source["content"]["items"]
            }
        ),
        "diff": definition_diff(previous, row),
    }


def create_definition_in_connection(
    connection: Connection,
    context: AuthContext,
    space_id: UUID,
    draft: DefinitionDraft,
    *,
    source_finding_id: UUID | None = None,
    source_finding_position: int | None = None,
) -> dict[str, Any]:
    _role(context, Action.PRODUCT_WORK_CONTRIBUTE)
    _space(connection, context, space_id, access="contributor", lock=True)
    product = (
        connection.execute(
            select(tables.product_nodes).where(
                tables.product_nodes.c.tenant_id == context.tenant.id,
                tables.product_nodes.c.market_space_id == space_id,
                tables.product_nodes.c.id == draft.product_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if product is None:
        raise ProductWorkAccessError("产品不存在或不可访问")
    line_id = product["product_line_id"]
    _line(connection, context, space_id, line_id, access="contributor", writable=True)
    if product["lifecycle"] == "retired":
        raise ProductWorkError("已退役产品不能创建新定义")
    table = tables.product_definitions
    fingerprint = digest(
        draft.model_dump(
            mode="json",
            exclude={"base_definition_id"} if draft.base_definition_id is None else set(),
        )
    )
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
            raise ProductWorkError("同一请求编号不能用于不同定义")
        return _definition(connection, context, existing)
    strategy = (
        connection.execute(
            select(tables.product_strategies).where(
                tables.product_strategies.c.tenant_id == context.tenant.id,
                tables.product_strategies.c.market_space_id == space_id,
                tables.product_strategies.c.id == draft.strategy_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if (
        strategy is None
        or strategy["state"] != "published"
        or strategy["product_line_id"] not in {None, line_id}
    ):
        raise ProductWorkError("定义须引用同范围已发布策略")
    node_id = uuid4()
    series_id, revision, previous = node_id, 1, None
    if draft.supersedes_id:
        previous = _row(connection, context, space_id, draft.supersedes_id)
        if previous["state"] != "published" or previous["product_id"] != product["id"]:
            raise ProductWorkError("新修订须基于同一产品的已发布定义")
        if connection.execute(
            select(table.c.id).where(
                table.c.tenant_id == context.tenant.id,
                table.c.supersedes_id == previous["id"],
            )
        ).first():
            raise ProductWorkError("已存在后续定义修订，请打开该修订")
        series_id, revision = previous["series_id"], previous["revision_number"] + 1
    elif connection.execute(
        select(table.c.id).where(
            table.c.tenant_id == context.tenant.id, table.c.product_id == product["id"]
        )
    ).first():
        raise ProductWorkError("产品已有定义，请编辑草稿或从已发布版创建修订")
    base_id = draft.base_definition_id or (previous["base_definition_id"] if previous else None)
    base_ref = None
    if product["derived_from"] is not None:
        if base_id is None:
            raise ProductWorkError("派生产品须锁定父产品已发布定义")
        parent = _row(connection, context, space_id, base_id)
        if parent["state"] != "published" or parent["product_id"] != product["derived_from"]:
            raise ProductWorkError("父定义与派生产品来源不一致")
        base_ref = SourceRef(
            tenant_id=context.tenant.id,
            kind="product_definition",
            ref_id=parent["id"],
            version=parent["version"],
            digest=parent["review_digest"],
            as_of=parent["published_at"],
        ).model_dump(mode="json")
    elif base_id is not None:
        raise ProductWorkError("仅派生产品可引用父定义")
    value = _resolve_content(connection, context, space_id, line_id, draft.content, previous)
    value = sparse_content(connection, context.tenant.id, base_id, value)
    reference = SourceRef(
        tenant_id=context.tenant.id,
        kind="product_strategy",
        ref_id=strategy["id"],
        version=strategy["version"],
        as_of=strategy["approval"]["approved_at"],
        digest=strategy["approval"]["payload_digest"],
    )
    row = (
        connection.execute(
            table.insert()
            .values(
                id=node_id,
                tenant_id=context.tenant.id,
                market_space_id=space_id,
                product_line_id=line_id,
                product_id=product["id"],
                strategy_id=strategy["id"],
                base_definition_id=base_id,
                base_definition_ref=base_ref,
                parent_updates=previous["parent_updates"] if previous else [],
                strategy_ref=reference.model_dump(mode="json"),
                owner_user_id=draft.content.owner_user_id,
                created_by_user_id=context.user.id,
                series_id=series_id,
                supersedes_id=draft.supersedes_id,
                revision_number=revision,
                title=draft.content.title,
                content=value,
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
    row = expand_definition(connection, row)
    result = _definition(connection, context, row)
    _emit(connection, context, space_id, "product_definition", "created", row)
    return result


class ProductDefinitionService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list(self, context: AuthContext, space_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _space(connection, context, space_id)
            table = tables.product_definitions
            rows = connection.execute(
                select(table)
                .where(
                    table.c.tenant_id == context.tenant.id,
                    table.c.market_space_id == space_id,
                    _line_filter(table, context),
                )
                .order_by(table.c.updated_at.desc())
                .limit(100)
            ).mappings()
            return {"items": [_definition(connection, context, row) for row in rows]}

    def detail(self, context: AuthContext, space_id: UUID, definition_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _space(connection, context, space_id)
            return _definition(
                connection, context, _row(connection, context, space_id, definition_id)
            )

    def create(
        self, context: AuthContext, space_id: UUID, draft: DefinitionDraft
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            return create_definition_in_connection(connection, context, space_id, draft)

    def change(
        self,
        context: AuthContext,
        space_id: UUID,
        definition_id: UUID,
        command: DefinitionEdit | DefinitionAction | DefinitionReview,
    ) -> dict[str, Any]:
        _role(context, Action.PRODUCT_WORK_CONTRIBUTE)
        with self.engine.begin() as connection:
            _space(connection, context, space_id, access="contributor", lock=True)
            row = _row(connection, context, space_id, definition_id, write=True)
            manager = _manager(connection, context, space_id, row["product_line_id"])
            author = context.user.id in {row["owner_user_id"], row["created_by_user_id"]}
            if isinstance(command, DefinitionReview):
                allowed = row["content"]["reviewers"].get(command.discipline) == str(
                    context.user.id
                )
            elif isinstance(command, DefinitionAction) and command.action in {
                "publish",
                "return",
                "withdraw",
            }:
                allowed = manager
            else:
                allowed = manager or author
            if not allowed:
                raise ProductWorkAccessError("当前用户不是此定义动作的办理人")
            if not _precondition(connection, context, row, command):
                return _definition(connection, context, row)
            now = datetime.now(UTC)
            if isinstance(command, DefinitionEdit):
                if row["state"] != "draft":
                    raise ProductWorkError("仅草稿可编辑；审核中先退回，发布后创建新修订")
                previous = (
                    _row(connection, context, space_id, row["supersedes_id"])
                    if row["supersedes_id"]
                    else None
                )
                value = _resolve_content(
                    connection, context, space_id, row["product_line_id"], command.content, previous
                )
                values = {
                    "content": sparse_content(
                        connection, context.tenant.id, row["base_definition_id"], value
                    ),
                    "title": command.content.title,
                    "owner_user_id": command.content.owner_user_id,
                }
                action = "edited"
            elif isinstance(command, DefinitionReview):
                if (
                    row["state"] != "in_review"
                    or command.review_round != row["review_round"]
                    or command.reviewed_source_digest != row["review_digest"]
                ):
                    raise ProductWorkError("协审须针对当前轮次及固定内容")
                _member(
                    connection, context, space_id, context.user.id, line_id=row["product_line_id"]
                )
                if connection.execute(
                    select(tables.definition_reviews.c.id).where(
                        tables.definition_reviews.c.tenant_id == context.tenant.id,
                        tables.definition_reviews.c.definition_id == row["id"],
                        tables.definition_reviews.c.review_round == row["review_round"],
                        tables.definition_reviews.c.discipline == command.discipline,
                    )
                ).first():
                    raise ProductWorkError("本专业已提交该轮意见；修改内容后请重新发起协审")
                connection.execute(
                    tables.definition_reviews.insert().values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        market_space_id=space_id,
                        definition_id=row["id"],
                        review_round=row["review_round"],
                        review_digest=row["review_digest"],
                        discipline=command.discipline,
                        reviewer_user_id=context.user.id,
                        outcome=command.outcome,
                        reason=command.reason,
                        sources=resolve_evidence(connection, context, command.sources),
                    )
                )
                values, action = {}, "reviewed"
            else:
                action = command.action
                if action == "withdraw":
                    latest = _release(connection, context, row["product_id"])
                    if (
                        row["state"] != "published"
                        or latest is None
                        or latest["action"] != "publish"
                        or latest["definition_id"] != row["id"]
                        or latest["id"] != command.expected_release_id
                    ):
                        raise ProductWorkError("仅当前生效发布可撤回，请刷新后确认发布记录")
                    released = self._append_release(
                        connection, context, row, "withdraw", command.reason, latest
                    )
                    _emit(
                        connection,
                        context,
                        space_id,
                        "product_definition",
                        action,
                        {**row, "release_event": _plain(released)},
                        before=row,
                        operation=command,
                    )
                    return _definition(connection, context, row)
                if row["state"] != ("draft" if action == "submit" else "in_review"):
                    raise ProductWorkError("定义当前状态不能执行此动作")
                if action == "return":
                    values = {"state": "draft", "review_digest": None}
                else:
                    content = DefinitionContent.model_validate(row["content"])
                    _resolve_content(connection, context, space_id, row["product_line_id"], content)
                    reviews = list(
                        connection.execute(
                            select(tables.definition_reviews).where(
                                tables.definition_reviews.c.tenant_id == context.tenant.id,
                                tables.definition_reviews.c.definition_id == row["id"],
                            )
                        ).mappings()
                    )
                    blockers = _readiness(row, reviews, reviewed=action == "publish")
                    if blockers:
                        raise ProductWorkError("；".join(blockers))
                    if action == "submit":
                        values = {
                            "state": "in_review",
                            "review_round": row["review_round"] + 1,
                            "review_digest": definition_digest(row),
                        }
                    else:
                        if command.reviewed_source_digest is None:
                            raise ProductWorkError("发布须确认已协审内容摘要")
                        DefinitionPublishRequest(
                            definition_id=row["id"],
                            expected_version=command.expected_version,
                            payload_digest=command.payload_digest,
                            idempotency_key=command.idempotency_key,
                            reviewed_source_digest=command.reviewed_source_digest,
                        )
                        if (
                            command.reviewed_source_digest != row["review_digest"]
                            or definition_digest(row) != row["review_digest"]
                        ):
                            raise ProductWorkError("发布内容与协审版本不一致")
                        latest = _release(connection, context, row["product_id"])
                        if (latest["definition_id"] if latest else None) != row["supersedes_id"]:
                            raise ProductWorkError("产品发布链已变化，请从最新发布定义修订")
                        approval = ApprovalRef(
                            approval_id=uuid4(),
                            payload_digest=row["review_digest"],
                            policy_version="human-definition-publication-v1",
                            approved_by_user_id=context.user.id,
                            approved_at=now,
                        )
                        values = {
                            "state": "published",
                            "approval": approval.model_dump(mode="json"),
                            "published_at": now,
                        }
            table = tables.product_definitions
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
            updated = expand_definition(connection, updated)
            if action == "publish":
                self._append_release(
                    connection,
                    context,
                    updated,
                    "publish",
                    command.reason,
                    _release(connection, context, row["product_id"]),
                )
            if action == "publish":
                publication = DefinitionPublishedPayload(
                    object_id=updated["id"],
                    object_version=updated["version"],
                    operation_id=uuid4(),
                    correlation_id=updated["id"],
                    causation_event_row_id=None,
                    product_id=updated["product_id"],
                    definition_digest=updated["review_digest"],
                )
                EventAuditWriter(
                    connection,
                    tenant_id=context.tenant.id,
                    actor_user_id=context.user.id,
                    project_id=None,
                ).record(
                    EventDraft(
                        event_id=f"definition:{updated['id']}:published",
                        event_type="DEFINITION_PUBLISHED",
                        source="product_definition_service",
                        entity_id=updated["id"],
                        payload=publication.model_dump(mode="json"),
                    ),
                    AuditDraft(
                        action="product_definition.published_event",
                        after_snapshot={
                            "definition_id": str(updated["id"]),
                            "definition_digest": updated["review_digest"],
                            "product_id": str(updated["product_id"]),
                        },
                        context={"market_space_id": str(space_id), "reason": command.reason},
                    ),
                )
            result = _definition(connection, context, updated)
            _emit(
                connection,
                context,
                space_id,
                "product_definition",
                action,
                updated,
                before=row,
                operation=command,
            )
            return result

    def _append_release(
        self,
        connection: Connection,
        context: AuthContext,
        row: Any,
        action: str,
        reason: str,
        previous: Any,
    ) -> Any:
        table = tables.definition_releases
        return (
            connection.execute(
                table.insert()
                .values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    market_space_id=row["market_space_id"],
                    product_id=row["product_id"],
                    definition_id=row["id"],
                    previous_release_id=previous["id"] if previous else None,
                    sequence=previous["sequence"] + 1 if previous else 1,
                    action=action,
                    actor_user_id=context.user.id,
                    reason=reason,
                )
                .returning(table)
            )
            .mappings()
            .one()
        )

    def history(self, context: AuthContext, space_id: UUID, definition_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _space(connection, context, space_id)
            row = _row(connection, context, space_id, definition_id)
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
                    log.c.entity_id == definition_id,
                    log.c.action.like("product_definition.%"),
                    log.c.action != "product_definition.published_event",
                )
                .order_by(log.c.timestamp.desc(), log.c.id.desc())
                .limit(100)
            ).mappings()
            releases = connection.execute(
                select(tables.definition_releases)
                .where(
                    tables.definition_releases.c.tenant_id == context.tenant.id,
                    tables.definition_releases.c.product_id == row["product_id"],
                )
                .order_by(tables.definition_releases.c.sequence.desc())
                .limit(100)
            ).mappings()
            return {
                "items": [_plain(item) for item in records],
                "releases": [_plain(release) for release in releases],
            }
