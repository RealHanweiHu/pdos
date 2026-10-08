"""Product identity, line grants and market-space maintenance before project creation."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, select
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.contracts.common_objects import Key, ScopeRef, Text
from app.contracts.object_operations import CommandPrecondition
from app.contracts.product_records import ProductNode
from app.db.schema import tables
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
    _role,
    _space,
    category_line_id,
    digest,
)

Level = Literal["line", "family", "platform", "series", "model", "variant"]
Lifecycle = Literal["proposed", "developing", "available", "retired"]
PARENT_LEVEL = {
    "family": "line",
    "platform": "family",
    "series": "platform",
    "model": "series",
    "variant": "model",
}


class ProductDraft(Input):
    request_id: UUID
    code: Key
    name: str = Field(min_length=1, max_length=2048)
    level: Level
    parent_id: UUID | None = None
    derived_from: UUID | None = None
    owner_user_id: UUID
    regions: list[Text] = Field(default_factory=list, max_length=30)
    channels: list[Key] = Field(default_factory=list, max_length=30)
    tags: list[str] = Field(default_factory=list, max_length=30)


class ProductChange(CommandPrecondition):
    name: str = Field(min_length=1, max_length=2048)
    owner_user_id: UUID
    lifecycle: Lifecycle
    regions: tuple[Text, ...] = Field(max_length=30)
    channels: tuple[Key, ...] = Field(max_length=30)
    tags: tuple[str, ...] | None = Field(default=None, max_length=30)
    reason: str = Field(min_length=1, max_length=2048)


class LineMemberChange(CommandPrecondition):
    user_id: UUID
    access: Literal["viewer", "contributor", "manager"] | None


class SpaceChange(CommandPrecondition):
    title: str = Field(min_length=1, max_length=512)
    user_groups: tuple[str, ...] = Field(min_length=1, max_length=30)
    regions: tuple[str, ...] = Field(min_length=1, max_length=30)
    use_scenarios: tuple[str, ...] = Field(min_length=1, max_length=50)
    research_questions: tuple[str, ...] = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1, max_length=2048)


class SpaceLifecycle(CommandPrecondition):
    lifecycle: Literal["active", "archived"]
    reason: str = Field(min_length=1, max_length=2048)


def _node(row: Any) -> dict[str, Any]:
    value = ProductNode(
        id=row["id"],
        tenant_id=row["tenant_id"],
        scope=ScopeRef(kind="product_line", ref_id=row["product_line_id"]),
        version=row["version"],
        owner_user_id=row["owner_user_id"],
        code=row["code"],
        name=row["name"],
        level=row["level"],
        parent_id=row["parent_id"],
        lifecycle=row["lifecycle"],
        regions=tuple(row["regions"]),
        channels=tuple(row["channels"]),
    )
    return {**_plain(row), **value.model_dump(mode="json"), "payload_digest": digest(_plain(row))}


def _node_row(connection: Any, context: AuthContext, space_id: UUID, node_id: UUID) -> Any:
    table = tables.product_nodes
    row = (
        connection.execute(
            select(table).where(
                table.c.tenant_id == context.tenant.id,
                table.c.market_space_id == space_id,
                table.c.id == node_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkAccessError("产品节点不存在或无权访问")
    return row


def create_product_in_connection(
    connection: Connection, context: AuthContext, space_id: UUID, draft: ProductDraft
) -> dict[str, Any]:
    _role(context, Action.PRODUCT_WORK_MANAGE)
    _space(connection, context, space_id, access="manager", lock=True)
    if draft.level in {"family", "platform", "series"}:
        raise ProductWorkError(
            "新产品按品类→型号→变体创建；族/系列用可选标签，平台在独立平台目录维护"
        )
    if draft.level == "line":
        raise ProductWorkError("请在品类目录创建新的品类，不能在品类内另建产品线")
    table = tables.product_nodes
    fingerprint = digest(
        draft.model_dump(
            mode="json", exclude={"derived_from"} if draft.derived_from is None else set()
        )
    )
    source = None
    if draft.derived_from:
        source = _node_row(connection, context, space_id, draft.derived_from)
        _line(connection, context, space_id, source["product_line_id"])
        from app.domain.product_definitions import _release

        released = _release(connection, context, source["id"])
        if (
            source["level"] != draft.level
            or source["level"] == "line"
            or source["lifecycle"] == "retired"
            or released is None
            or released["action"] != "publish"
        ):
            raise ProductWorkError("派生须选择同层级、未退役且有生效定义的父产品")
    existing = (
        connection.execute(
            select(table).where(
                table.c.tenant_id == context.tenant.id,
                table.c.market_space_id == space_id,
                table.c.request_id == draft.request_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing:
        _line(connection, context, space_id, existing["product_line_id"])
        if existing["request_digest"] != fingerprint:
            raise ProductWorkError("同一请求编号不能用于不同产品内容")
        return _node(existing)
    node_id = uuid4()
    if draft.level == "line":
        if draft.parent_id is not None:
            raise ProductWorkError("产品线没有上级产品节点")
        line_id = node_id
        _member(connection, context, space_id, draft.owner_user_id)
    else:
        if draft.parent_id is None:
            raise ProductWorkError("请选择所属品类或型号")
        parent = _node_row(connection, context, space_id, draft.parent_id)
        line_id = parent["product_line_id"]
        _line(connection, context, space_id, line_id, access="manager", writable=True)
        if (
            parent["level"]
            not in ({"line", "series"} if draft.level == "model" else {PARENT_LEVEL[draft.level]})
            or parent["lifecycle"] == "retired"
        ):
            raise ProductWorkError("上级须为相邻产品层级，且未退役")
        _member(connection, context, space_id, draft.owner_user_id, line_id)
    if source is not None and source["product_line_id"] != line_id:
        raise ProductWorkError("派生来源须属于同一产品线；请在父产品所属产品线创建派生产品")
    row = (
        connection.execute(
            table.insert()
            .values(
                **draft.model_dump(),
                id=node_id,
                tenant_id=context.tenant.id,
                market_space_id=space_id,
                product_line_id=line_id,
                request_digest=fingerprint,
            )
            .returning(table)
        )
        .mappings()
        .one()
    )
    if draft.level == "line":
        for user_id in {context.user.id, draft.owner_user_id}:
            connection.execute(
                tables.product_line_members.insert().values(
                    tenant_id=context.tenant.id,
                    market_space_id=space_id,
                    product_line_id=node_id,
                    user_id=user_id,
                    access="manager",
                    added_by_user_id=context.user.id,
                )
            )
    _emit(connection, context, space_id, "product_node", "created", row)
    return _node(row)


class ProductCatalogService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def catalog(self, context: AuthContext, space_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as connection:
            space = _space(connection, context, space_id)
            table = tables.product_nodes
            nodes = list(
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        _line_filter(table, context),
                    )
                    .order_by(table.c.created_at, table.c.code)
                ).mappings()
            )
            visible_lines = [row["id"] for row in nodes if row["level"] == "line"]
            grants = tables.product_line_members
            memberships = list(
                connection.execute(
                    select(
                        grants.c.product_line_id,
                        grants.c.user_id,
                        grants.c.access,
                        tables.users.c.display_name,
                    )
                    .join(
                        tables.users,
                        (tables.users.c.tenant_id == grants.c.tenant_id)
                        & (tables.users.c.id == grants.c.user_id),
                    )
                    .where(
                        grants.c.tenant_id == context.tenant.id,
                        grants.c.product_line_id.in_(visible_lines),
                    )
                ).mappings()
            )
            space_access = connection.execute(
                select(tables.market_space_members.c.access).where(
                    tables.market_space_members.c.tenant_id == context.tenant.id,
                    tables.market_space_members.c.market_space_id == space_id,
                    tables.market_space_members.c.user_id == context.user.id,
                )
            ).scalar_one_or_none()
            elevated = context.user.role in {Role.OWNER, Role.ADMIN}
            space_manager = elevated or space_access == "manager"
            can_manage = (
                space_manager
                and is_allowed(context.user.role, Action.PRODUCT_WORK_MANAGE)
                and space["lifecycle"] != "archived"
            )
            mine = {
                row["product_line_id"]: row["access"]
                for row in memberships
                if row["user_id"] == context.user.id
            }
            return {
                "category_id": str(space_id),
                "category_line_id": str(category_line_id(connection, context.tenant.id, space_id)),
                "nodes": [_node(row) for row in nodes],
                "members": [_plain(row) for row in memberships],
                "can_create_line": False,
                "line_access": {
                    str(line_id): {
                        "can_manage": can_manage and (elevated or mine.get(line_id) == "manager"),
                        "can_contribute": (elevated or space_access in {"contributor", "manager"})
                        and (elevated or mine.get(line_id) in {"contributor", "manager"})
                        and is_allowed(context.user.role, Action.PRODUCT_WORK_CONTRIBUTE)
                        and space["lifecycle"] != "archived"
                        and next(row for row in nodes if row["id"] == line_id)["lifecycle"]
                        != "retired",
                    }
                    for line_id in visible_lines
                },
            }

    def create(self, context: AuthContext, space_id: UUID, draft: ProductDraft) -> dict[str, Any]:
        _role(context, Action.PRODUCT_WORK_MANAGE)
        try:
            with self.engine.begin() as connection:
                return create_product_in_connection(connection, context, space_id, draft)
        except IntegrityError as error:
            raise ProductWorkError("产品编号已存在，或上级产品关系已变化，请刷新") from error

    def change(
        self, context: AuthContext, space_id: UUID, node_id: UUID, command: ProductChange
    ) -> dict[str, Any]:
        _role(context, Action.PRODUCT_WORK_MANAGE)
        with self.engine.begin() as connection:
            _space(connection, context, space_id, access="manager", lock=True)
            row = _node_row(connection, context, space_id, node_id)
            if row["level"] == "line":
                raise ProductWorkError("品类资料、负责人和状态统一在品类设置办理")
            _line(
                connection,
                context,
                space_id,
                row["product_line_id"],
                access="manager",
                writable=row["level"] != "line",
            )
            if not _precondition(connection, context, row, command):
                return _node(row)
            _member(connection, context, space_id, command.owner_user_id, row["product_line_id"])
            if row["level"] == "line":
                owner_access = connection.execute(
                    select(tables.product_line_members.c.access).where(
                        tables.product_line_members.c.tenant_id == context.tenant.id,
                        tables.product_line_members.c.product_line_id == node_id,
                        tables.product_line_members.c.user_id == command.owner_user_id,
                    )
                ).scalar_one_or_none()
                if owner_access != "manager":
                    raise ProductWorkError("产品线负责人须为产品线管理成员")
            table = tables.product_nodes
            if command.lifecycle == "retired":
                from app.domain.initial_plan_reviews import ensure_plan_reviews_resolved

                ensure_plan_reviews_resolved(
                    connection,
                    context,
                    space_id,
                    line_id=node_id if row["level"] == "line" else None,
                    product_id=node_id if row["level"] != "line" else None,
                )
                child = connection.execute(
                    select(table.c.id)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.parent_id == node_id,
                        table.c.lifecycle != "retired",
                    )
                    .limit(1)
                ).first()
                if child:
                    raise ProductWorkError("请先处置未退役的下级产品")
                if connection.execute(
                    select(tables.product_definitions.c.id)
                    .where(
                        tables.product_definitions.c.tenant_id == context.tenant.id,
                        tables.product_definitions.c.product_line_id == node_id
                        if row["level"] == "line"
                        else tables.product_definitions.c.product_id == node_id,
                        tables.product_definitions.c.state == "in_review",
                    )
                    .limit(1)
                ).first():
                    raise ProductWorkError("产品仍有待协审定义，请先办理或退回草稿")
                if row["level"] == "line":
                    if connection.execute(
                        select(tables.product_strategies.c.id)
                        .where(
                            tables.product_strategies.c.tenant_id == context.tenant.id,
                            tables.product_strategies.c.product_line_id == node_id,
                            tables.product_strategies.c.state == "in_review",
                        )
                        .limit(1)
                    ).first():
                        raise ProductWorkError("产品线仍有待审核策略，请先办理或退回草稿")
                    for task_table in (
                        tables.research_tasks,
                        tables.scoped_work_items,
                        tables.experiments,
                    ):
                        open_task = connection.execute(
                            select(task_table.c.id)
                            .where(
                                task_table.c.tenant_id == context.tenant.id,
                                task_table.c.product_line_id == node_id,
                                task_table.c.state.not_in(("completed", "concluded", "cancelled")),
                            )
                            .limit(1)
                        ).first()
                        if open_task:
                            raise ProductWorkError(
                                "产品线仍有未结束的研究、专业工作或实验，请先处置"
                            )
            elif row["parent_id"] is not None:
                parent = _node_row(connection, context, space_id, row["parent_id"])
                if parent["lifecycle"] == "retired":
                    raise ProductWorkError("请先恢复上级产品")
            values = command.model_dump(
                mode="json",
                exclude={
                    "expected_version",
                    "payload_digest",
                    "idempotency_key",
                    "schema_version",
                    "reason",
                },
            )
            if command.tags is None:
                values.pop("tags", None)
            values["owner_user_id"] = command.owner_user_id
            after = (
                connection.execute(
                    table.update()
                    .where(table.c.id == node_id)
                    .values(**values, version=row["version"] + 1, updated_at=datetime.now(UTC))
                    .returning(table)
                )
                .mappings()
                .one()
            )
            _emit(
                connection,
                context,
                space_id,
                "product_node",
                "updated",
                after,
                before=row,
                operation=command,
            )
            return _node(after)

    def set_member(
        self, context: AuthContext, space_id: UUID, line_id: UUID, command: LineMemberChange
    ) -> dict[str, Any]:
        _role(context, Action.PRODUCT_WORK_MANAGE)
        with self.engine.connect() as connection:
            _line(connection, context, space_id, line_id, access="manager")
        raise ProductWorkError("成员权限统一在品类设置维护，不再单独维护产品线成员")

    def change_space(
        self, context: AuthContext, space_id: UUID, command: SpaceChange | SpaceLifecycle
    ) -> dict[str, Any]:
        _role(context, Action.PRODUCT_WORK_MANAGE)
        with self.engine.begin() as connection:
            row = _space(
                connection,
                context,
                space_id,
                access="manager",
                lock=True,
                allow_archived=isinstance(command, SpaceLifecycle),
            )
            if not _precondition(connection, context, row, command):
                return {**_plain(row), "payload_digest": digest(_plain(row))}
            if isinstance(command, SpaceLifecycle):
                if row["lifecycle"] == command.lifecycle:
                    raise ProductWorkError("品类已经处于目标状态")
                if command.lifecycle == "archived":
                    from app.domain.initial_plan_reviews import ensure_plan_reviews_resolved

                    ensure_plan_reviews_resolved(connection, context, space_id)
                    if connection.execute(
                        select(tables.product_definitions.c.id)
                        .where(
                            tables.product_definitions.c.tenant_id == context.tenant.id,
                            tables.product_definitions.c.market_space_id == space_id,
                            tables.product_definitions.c.state == "in_review",
                        )
                        .limit(1)
                    ).first():
                        raise ProductWorkError("品类仍有待协审定义，请先办理或退回草稿")
                    if connection.execute(
                        select(tables.product_strategies.c.id)
                        .where(
                            tables.product_strategies.c.tenant_id == context.tenant.id,
                            tables.product_strategies.c.market_space_id == space_id,
                            tables.product_strategies.c.state == "in_review",
                        )
                        .limit(1)
                    ).first():
                        raise ProductWorkError("品类仍有待审核策略，请先办理或退回草稿")
                    for task_table in (
                        tables.research_tasks,
                        tables.scoped_work_items,
                        tables.experiments,
                    ):
                        if connection.execute(
                            select(task_table.c.id)
                            .where(
                                task_table.c.tenant_id == context.tenant.id,
                                task_table.c.market_space_id == space_id,
                                task_table.c.state.not_in(("completed", "concluded", "cancelled")),
                            )
                            .limit(1)
                        ).first():
                            raise ProductWorkError("品类仍有未结束工作，请先完成或明确取消")
                values: dict[str, Any] = {"lifecycle": command.lifecycle}
            else:
                values = command.model_dump(
                    mode="json",
                    exclude={
                        "expected_version",
                        "payload_digest",
                        "idempotency_key",
                        "schema_version",
                        "reason",
                    },
                )
                for key in ("user_groups", "regions", "use_scenarios", "research_questions"):
                    if any(not item.strip() or len(item) > 2048 for item in values[key]):
                        raise ProductWorkError("空间描述每项须为1至2048字符")
                    values[key] = [item.strip() for item in values[key]]
            after = (
                connection.execute(
                    tables.market_spaces.update()
                    .where(tables.market_spaces.c.id == space_id)
                    .values(**values, version=row["version"] + 1, updated_at=datetime.now(UTC))
                    .returning(tables.market_spaces)
                )
                .mappings()
                .one()
            )
            _emit(
                connection,
                context,
                space_id,
                "market_space",
                "lifecycle_changed" if isinstance(command, SpaceLifecycle) else "updated",
                after,
                before=row,
                operation=command,
            )
            return {**_plain(after), "payload_digest": digest(_plain(after))}
