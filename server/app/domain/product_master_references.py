"""Internal, human-owned ERP/PLM reference receipts; never external confirmation."""

from datetime import UTC, datetime
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, Key, SourceRef, Text
from app.db.schema import tables
from app.domain.product_catalog import _node_row
from app.domain.product_definitions import _release, _row, definition_digest
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _emit,
    _line,
    _plain,
    _result_sources,
    _role,
    _space,
    digest,
)


class MasterReferenceSave(Contract):
    request_id: UUID
    expected_context_digest: Digest
    action: Literal["register", "correct", "withdraw"]
    previous_id: UUID | None = None
    system_kind: Literal["erp", "plm"]
    source_system: Key
    master_kind: Literal["material", "product", "cad_revision"]
    external_id: Text
    external_revision: Text
    external_as_of: AwareDatetime
    sources: tuple[SourceRef, ...] = Field(min_length=1, max_length=100)
    reason: Text

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if (self.action == "register") != (self.previous_id is None):
            raise ValueError("登记不能指定上一引用；纠正和撤回必须指定上一引用")
        if (self.master_kind == "material" and self.system_kind != "erp") or (
            self.master_kind == "cad_revision" and self.system_kind != "plm"
        ):
            raise ValueError("物料仅引用ERP，CAD版本仅引用PLM")
        if self.external_as_of > datetime.now(UTC):
            raise ValueError("外部版本时间不能晚于当前时间")
        return self


FROZEN_FIELDS = (
    "system_kind",
    "source_system",
    "master_kind",
    "external_id",
    "external_revision",
    "external_as_of",
    "sources",
)


def _context(
    c: Connection, context: AuthContext, space: UUID, product: UUID, *, write: bool = False
) -> dict[str, Any]:
    _role(context, Action.PRODUCT_WORK_MANAGE if write else Action.PRODUCT_WORK_VIEW)
    access = "manager" if write else "viewer"
    _space(c, context, space, access=access, lock=write)
    node = _node_row(c, context, space, product)
    _line(c, context, space, node["product_line_id"], access=access)
    if node["level"] not in {"model", "variant"}:
        raise ProductWorkError("仅型号或变体可登记外部主数据引用")
    snapshot = _plain(
        {key: node[key] for key in ("id", "version", "code", "name", "level", "lifecycle")}
    )
    release = _release(c, context, product)
    definition = None
    if release is not None and release["action"] == "publish":
        row = _row(c, context, space, release["definition_id"])
        if row["product_id"] != product or row["state"] != "published":
            raise ProductWorkError("发布定义与产品不一致")
        definition = {
            "id": str(row["id"]),
            "version": row["version"],
            "revision": row["revision_number"],
            "digest": definition_digest(row),
            "release_id": str(release["id"]),
        }
    value = {"product": snapshot, "current_definition": definition}
    return {
        **value,
        "context_digest": digest(
            {**value, "latest_release": _plain(release) if release is not None else None}
        ),
    }


def _items(
    c: Connection, context: AuthContext, space: UUID, product: UUID, current: dict[str, Any]
) -> list[dict[str, Any]]:
    table = tables.product_master_references
    rows = (
        c.execute(
            select(table)
            .where(
                table.c.tenant_id == context.tenant.id,
                table.c.market_space_id == space,
                table.c.product_id == product,
            )
            .order_by(table.c.created_at, table.c.id)
        )
        .mappings()
        .all()
    )
    result = []
    for row in rows:
        _result_sources(c, context, tuple(SourceRef.model_validate(ref) for ref in row["sources"]))
        item = _plain(dict(row))
        item.pop("request_digest", None)
        item.pop("tenant_id", None)
        item.pop("market_space_id", None)
        item.pop("product_id", None)
        item["is_head"] = not any(other["previous_id"] == row["id"] for other in rows)
        item["context_status"] = (
            "no_current_release"
            if current["current_definition"] is None
            else "current"
            if row["context_digest"] == current["context_digest"]
            else "stale"
        )
        result.append(item)
    return result


class ProductMasterReferenceService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def read(self, context: AuthContext, space_id: UUID, product_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as c:
            current = _context(c, context, space_id, product_id)
            return {**current, "items": _items(c, context, space_id, product_id, current)}

    def save(
        self, context: AuthContext, space_id: UUID, product_id: UUID, command: MasterReferenceSave
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            current = _context(c, context, space_id, product_id, write=True)
            table = tables.product_master_references
            rows = (
                c.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        table.c.product_id == product_id,
                    )
                )
                .mappings()
                .all()
            )
            request_digest = digest(command.model_dump(mode="json"))
            prior = next((row for row in rows if row["request_id"] == command.request_id), None)
            if prior is not None:
                if prior["created_by_user_id"] != context.user.id:
                    raise ProductWorkAccessError("原请求不属于当前操作者")
                if prior["request_digest"] != request_digest:
                    raise ProductWorkError("请求标识已用于不同内容")
                return {**current, "items": _items(c, context, space_id, product_id, current)}
            if command.expected_context_digest != current["context_digest"]:
                raise ProductWorkError("产品或发布定义已变化，请刷新后重新登记")
            previous = next((row for row in rows if row["id"] == command.previous_id), None)
            if command.previous_id is not None and (
                previous is None
                or previous["action"] == "withdraw"
                or any(row["previous_id"] == command.previous_id for row in rows)
            ):
                raise ProductWorkError("上一引用不存在、已被替代或已撤回")
            data = command.model_dump(mode="json")
            if command.action != "withdraw":
                replaced = {row["previous_id"] for row in rows if row["previous_id"] is not None}
                for row in rows:
                    if (
                        row["id"] in replaced
                        or row["action"] == "withdraw"
                        or row["id"] == command.previous_id
                    ):
                        continue
                    if all(
                        row[key] == getattr(command, key)
                        for key in ("system_kind", "source_system", "master_kind", "external_id")
                    ):
                        raise ProductWorkError("该外部定位已有活动引用，请纠正或撤回原引用")
            if command.action == "withdraw":
                assert previous is not None
                if previous["external_as_of"] != command.external_as_of or any(
                    _plain(previous)[key] != data[key]
                    for key in FROZEN_FIELDS
                    if key != "external_as_of"
                ):
                    raise ProductWorkError("撤回必须保留上一引用的全部身份与来源")
                definition_ref = previous["definition_ref"]
                product_snapshot = previous["product_snapshot"]
                frozen_context = previous["context_digest"]
            else:
                if (
                    current["current_definition"] is None
                    or current["product"]["lifecycle"] == "retired"
                ):
                    raise ProductWorkError("登记或纠正需要未退役产品的当前已发布定义")
                _line(
                    c,
                    context,
                    space_id,
                    _node_row(c, context, space_id, product_id)["product_line_id"],
                    access="manager",
                    writable=True,
                )
                definition_ref = current["current_definition"]
                product_snapshot = current["product"]
                frozen_context = current["context_digest"]
            _result_sources(c, context, command.sources)
            # Reauthorize all history before a write whose response includes that history.
            _items(c, context, space_id, product_id, current)
            values = {
                "id": uuid4(),
                "tenant_id": context.tenant.id,
                "market_space_id": space_id,
                "product_id": product_id,
                "created_by_user_id": context.user.id,
                "request_id": command.request_id,
                "request_digest": request_digest,
                "context_digest": frozen_context,
                "previous_id": command.previous_id,
                "definition_ref": definition_ref,
                "product_snapshot": product_snapshot,
                "version": 1,
                **{key: getattr(command, key) for key in FROZEN_FIELDS if key != "sources"},
                "sources": data["sources"],
                "action": command.action,
                "reason": command.reason,
            }
            row = c.execute(table.insert().values(**values).returning(table)).mappings().one()
            _emit(c, context, space_id, "product_master_reference", command.action, row)
            return {**current, "items": _items(c, context, space_id, product_id, current)}
