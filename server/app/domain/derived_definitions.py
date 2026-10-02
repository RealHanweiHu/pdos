"""Human product derivation and explicit, source-bound three-way parent updates."""

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

from pydantic import Field, model_validator
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Digest, Key, SourceRef, Text
from app.contracts.object_operations import CommandPrecondition
from app.db.schema import tables
from app.domain.definition_inheritance import (
    accept_changes,
    expand_definition,
    sparse_content,
    three_way,
)
from app.domain.product_catalog import ProductDraft, _node_row, create_product_in_connection
from app.domain.product_definitions import (
    DefinitionContent,
    DefinitionDraft,
    _definition,
    _release,
    _resolve_content,
    _row,
    create_definition_in_connection,
)
from app.domain.product_strategies import _manager
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _emit,
    _line,
    _plain,
    _precondition,
    _role,
    _space,
    digest,
)


class DeriveDefinition(CommandPrecondition):
    code: Key
    name: Text
    reason: Text


class MergeParent(CommandPrecondition):
    target_definition_id: UUID
    target_release_id: UUID
    comparison_digest: Digest
    accept_paths: tuple[str, ...] = Field(min_length=1, max_length=320)
    reason: Text

    @model_validator(mode="after")
    def unique_paths(self) -> "MergeParent":
        if len(set(self.accept_paths)) != len(self.accept_paths):
            raise ValueError("接受的变更项不能重复")
        return self


def _comparison(c: Any, context: AuthContext, space: UUID, row: Any) -> dict[str, Any]:
    if row["base_definition_id"] is None:
        raise ProductWorkError("此定义没有父产品引用")
    original = _row(c, context, space, row["base_definition_id"])
    latest = _release(c, context, original["product_id"])
    if latest is None or latest["action"] != "publish":
        raise ProductWorkError("父产品当前发布已撤回；锁定引用保留，暂不能接受新版")
    incoming = _row(c, context, space, latest["definition_id"])
    changes = three_way(original["content"], row["content"], incoming["content"])
    snapshot = {
        "local": _plain(row),
        "base": _plain(original),
        "incoming": _plain(incoming),
        "release": _plain(latest),
    }
    return {
        "base_definition_id": str(original["id"]),
        "target_definition_id": str(incoming["id"]),
        "target_release_id": str(latest["id"]),
        "target_revision": incoming["revision_number"],
        "comparison_digest": digest(snapshot),
        "changes": changes,
    }


class DerivedDefinitionService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def derive(
        self, context: AuthContext, space: UUID, definition: UUID, command: DeriveDefinition
    ) -> dict[str, Any]:
        _role(context, Action.PRODUCT_WORK_MANAGE)
        try:
            with self.engine.begin() as c:
                _space(c, context, space, access="manager", lock=True)
                source = _row(c, context, space, definition)
                _line(c, context, space, source["product_line_id"], access="manager", writable=True)
                request = uuid5(definition, command.idempotency_key)
                if not _precondition(c, context, source, command):
                    existing = c.execute(
                        select(tables.product_definitions.c.id).where(
                            tables.product_definitions.c.tenant_id == context.tenant.id,
                            tables.product_definitions.c.market_space_id == space,
                            tables.product_definitions.c.created_by_user_id == context.user.id,
                            tables.product_definitions.c.request_id == request,
                        )
                    ).scalar_one()
                    return _definition(c, context, _row(c, context, space, existing))
                released = _release(c, context, source["product_id"])
                if (
                    source["state"] != "published"
                    or released is None
                    or released["action"] != "publish"
                    or released["definition_id"] != definition
                ):
                    raise ProductWorkError("派生须从当前生效的父产品定义开始，请刷新发布版")
                node = _node_row(c, context, space, source["product_id"])
                if node["level"] == "line":
                    raise ProductWorkError("请从具体产品派生，不能派生整条产品线")
                product = create_product_in_connection(
                    c,
                    context,
                    space,
                    ProductDraft(
                        request_id=request,
                        code=command.code,
                        name=command.name,
                        level=node["level"],
                        parent_id=node["parent_id"],
                        derived_from=node["id"],
                        owner_user_id=context.user.id,
                        regions=node["regions"],
                        channels=node["channels"],
                    ),
                )
                content = deepcopy(source["content"])
                content.update(
                    title=command.name,
                    owner_user_id=str(context.user.id),
                    reviewers={},
                    change_reason=command.reason,
                )
                for item in content["items"]:
                    item.update(
                        owner_user_id=None, state="needs_confirmation", disposition_reason=None
                    )
                result = create_definition_in_connection(
                    c,
                    context,
                    space,
                    DefinitionDraft(
                        request_id=request,
                        product_id=product["id"],
                        strategy_id=source["strategy_id"],
                        base_definition_id=definition,
                        content=DefinitionContent.model_validate(content),
                    ),
                )
                _emit(
                    c,
                    context,
                    space,
                    "product_definition",
                    "derived_created",
                    source,
                    before=source,
                    operation=command,
                )
                return result
        except IntegrityError as error:
            raise ProductWorkError("产品编号已存在，或父产品关系已变化，请刷新后重试") from error

    def compare(self, context: AuthContext, space: UUID, definition: UUID) -> dict[str, Any]:
        _role(context, Action.PRODUCT_WORK_VIEW)
        with self.engine.connect() as c:
            _space(c, context, space)
            return _comparison(c, context, space, _row(c, context, space, definition))

    def merge(
        self, context: AuthContext, space: UUID, definition: UUID, command: MergeParent
    ) -> dict[str, Any]:
        _role(context, Action.PRODUCT_WORK_CONTRIBUTE)
        with self.engine.begin() as c:
            _space(c, context, space, access="contributor", lock=True)
            row = _row(c, context, space, definition, write=True)
            if context.user.id not in {
                row["owner_user_id"],
                row["created_by_user_id"],
            } and not _manager(c, context, space, row["product_line_id"]):
                raise ProductWorkAccessError("仅负责人或范围管理人可接受父版变更")
            if not _precondition(c, context, row, command):
                return _definition(c, context, row)
            if row["state"] != "draft":
                raise ProductWorkError("请先退回草稿或从已发布版创建修订，再比较父版更新")
            comparison = _comparison(c, context, space, row)
            if (
                comparison["comparison_digest"] != command.comparison_digest
                or comparison["target_definition_id"] != str(command.target_definition_id)
                or comparison["target_release_id"] != str(command.target_release_id)
            ):
                raise ProductWorkError("父版或本地内容已变化，请重新进行三方对比")
            available = {entry["path"] for entry in comparison["changes"]}
            if not set(command.accept_paths) <= available:
                raise ProductWorkError("只能接受本次三方对比列出的变更")
            parent = _row(c, context, space, command.target_definition_id)
            content = accept_changes(row["content"], parent["content"], command.accept_paths)
            content["change_reason"] = command.reason
            value = _resolve_content(
                c,
                context,
                space,
                row["product_line_id"],
                DefinitionContent.model_validate(content),
                row,
            )
            reference = SourceRef(
                tenant_id=context.tenant.id,
                kind="product_definition",
                ref_id=parent["id"],
                version=parent["version"],
                digest=parent["review_digest"],
                as_of=parent["published_at"],
            )
            table = tables.product_definitions
            updated = (
                c.execute(
                    table.update()
                    .where(table.c.tenant_id == context.tenant.id, table.c.id == definition)
                    .values(
                        parent_updates=[
                            *row["parent_updates"],
                            {
                                "source": reference.model_dump(mode="json"),
                                "accepted_paths": list(command.accept_paths),
                                "actor_user_id": str(context.user.id),
                                "comparison_digest": command.comparison_digest,
                                "reason": command.reason,
                            },
                        ],
                        content=sparse_content(
                            c, context.tenant.id, row["base_definition_id"], value
                        ),
                        version=row["version"] + 1,
                        review_digest=None,
                        updated_at=datetime.now(UTC),
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            updated = expand_definition(c, updated)
            result = _definition(c, context, updated)
            _emit(
                c,
                context,
                space,
                "product_definition",
                "parent_merged",
                updated,
                before=row,
                operation=command,
            )
            return result
