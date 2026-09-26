"""Named product roadmap publication with frozen definition sources and history."""

from datetime import date
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, func, select
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, Key, Text
from app.contracts.product_records import FactStatement
from app.db.schema import tables
from app.domain.market_analysis import _fact
from app.domain.product_catalog import _node_row
from app.domain.product_definitions import _release, _row, definition_digest
from app.domain.product_evidence import evidence_quality
from app.domain.product_strategies import _manager
from app.domain.product_workspace import (
    ProductWorkError,
    _emit,
    _line,
    _member,
    _plain,
    _role,
    _space,
    digest,
)


class RoadmapCheckpoint(Contract):
    key: Key
    title: Text
    kind: Literal["definition", "development", "validation", "launch", "retirement", "other"]
    owner_user_id: UUID
    window_start: date | None
    window_end: date | None
    unknown_reason: Text | None = None
    basis: FactStatement
    disposition: Literal["planned", "cancelled"] = "planned"
    cancellation_reason: Text | None = None

    @model_validator(mode="after")
    def honest_window(self) -> Self:
        if (self.window_start is None) != (self.window_end is None):
            raise ValueError("日期窗口须同时填写开始和结束，或同时留空")
        if self.window_start is not None and self.window_end is not None:
            if self.window_end < self.window_start:
                raise ValueError("窗口结束日期不能早于开始日期")
            if self.unknown_reason is not None:
                raise ValueError("已明确窗口不同时填写日期未定原因")
        elif self.unknown_reason is None:
            raise ValueError("日期未定须保留原因")
        if (self.disposition == "cancelled") != (self.cancellation_reason is not None):
            raise ValueError("取消节点须填写原因；仍计划的节点不能同时标取消")
        if self.basis.approval is not None:
            raise ValueError("日期依据不能由客户端提供批准引用")
        return self


class RoadmapContent(Contract):
    scope_note: Text
    checkpoints: tuple[RoadmapCheckpoint, ...] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def keys(self) -> Self:
        if len({item.key for item in self.checkpoints}) != len(self.checkpoints):
            raise ValueError("路线图节点标识不能重复")
        return self


class RoadmapRead(Contract):
    product_id: UUID
    before_version: int | None = Field(default=None, ge=1)


class RoadmapWrite(Contract):
    product_id: UUID
    request_id: UUID
    expected_version: int = Field(ge=0)
    expected_source_digest: Digest | None = None
    action: Literal["publish", "withdraw"]
    body: RoadmapContent | None = None
    reason: Text

    @model_validator(mode="after")
    def shape(self) -> Self:
        if self.action == "publish" and (self.body is None or self.expected_source_digest is None):
            raise ValueError("发布路线图须固定当前定义依据和节点内容")
        if self.action == "withdraw" and self.body is not None:
            raise ValueError("撤回保留原内容，不接受替换内容")
        return self


def latest_rows(
    c: Connection, tenant_id: UUID, product_ids: list[UUID], *, summary_only: bool = False
) -> dict[str, Any]:
    t = tables.product_roadmap_revisions
    columns = [t.c.id, t.c.product_id, t.c.version] if summary_only else [t]
    q = (
        select(
            *columns,
            func.row_number()
            .over(partition_by=t.c.product_id, order_by=t.c.version.desc())
            .label("position"),
        )
        .where(t.c.tenant_id == tenant_id, t.c.product_id.in_(product_ids))
        .subquery()
    )
    return {
        str(row["product_id"]): row
        for row in c.execute(select(q).where(q.c.position == 1)).mappings()
    }


def source(
    c: Connection, context: AuthContext, space_id: UUID, product_id: UUID
) -> tuple[Any, dict[str, Any] | None]:
    node = _node_row(c, context, space_id, product_id)
    _line(c, context, space_id, node["product_line_id"])
    release = _release(c, context, product_id)
    if release is None or release["action"] != "publish":
        return node, None
    definition = _row(c, context, space_id, release["definition_id"])
    snapshot = _plain(
        {
            "product": {
                key: node[key]
                for key in (
                    "id",
                    "code",
                    "name",
                    "version",
                    "parent_id",
                    "level",
                    "product_line_id",
                    "lifecycle",
                    "regions",
                    "channels",
                )
            },
            "release_id": release["id"],
            "definition_id": definition["id"],
            "definition_revision": definition["revision_number"],
            "definition_digest": definition_digest(definition),
            "released_at": release["created_at"],
            "launch_window": definition["content"]["launch_window"],
            "target_users": definition["content"]["target_users"],
            "scenarios": definition["content"]["scenarios"],
        }
    )
    return node, snapshot


def view(
    c: Connection, context: AuthContext, row: Any, current: dict[str, Any] | None
) -> dict[str, Any]:
    refs = [ref for item in row["body"]["checkpoints"] for ref in item["basis"]["sources"]]
    refs.extend(row["source_snapshot"]["launch_window"]["sources"])
    actor_name = c.execute(
        select(tables.users.c.display_name).where(
            tables.users.c.tenant_id == context.tenant.id, tables.users.c.id == row["actor_user_id"]
        )
    ).scalar_one()
    return {
        **_plain(row),
        "actor_name": actor_name,
        "source_current": current is not None and row["source_digest"] == digest(current),
        "source_warnings": evidence_quality(c, context, refs),
    }


class ProductRoadmapService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def read(self, context: AuthContext, space_id: UUID, query: RoadmapRead) -> dict[str, Any]:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            space = _space(c, context, space_id)
            node, snapshot = source(c, context, space_id, query.product_id)
            line = _line(c, context, space_id, node["product_line_id"])
            can_manage = (
                _manager(c, context, space_id, node["product_line_id"])
                and space["lifecycle"] != "archived"
                and line["lifecycle"] != "retired"
            )
            current = latest_rows(c, context.tenant.id, [query.product_id]).get(
                str(query.product_id)
            )
            return {
                "source": snapshot,
                "source_digest": digest(snapshot) if snapshot else None,
                "product": _plain(node),
                "latest": view(c, context, current, snapshot) if current else None,
                "can_manage": can_manage,
                "can_publish": can_manage
                and snapshot is not None
                and node["lifecycle"] != "retired",
                "source_warnings": evidence_quality(
                    c, context, snapshot["launch_window"]["sources"]
                )
                if snapshot
                else [],
            }

    def history(self, context: AuthContext, space_id: UUID, query: RoadmapRead) -> dict[str, Any]:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            _space(c, context, space_id)
            _, snapshot = source(c, context, space_id, query.product_id)
            t = tables.product_roadmap_revisions
            statement = select(t).where(
                t.c.tenant_id == context.tenant.id,
                t.c.market_space_id == space_id,
                t.c.product_id == query.product_id,
            )
            if query.before_version is not None:
                statement = statement.where(t.c.version < query.before_version)
            rows = list(c.execute(statement.order_by(t.c.version.desc()).limit(21)).mappings())
            return {
                "items": [view(c, context, row, snapshot) for row in rows[:20]],
                "next_before_version": rows[19]["version"] if len(rows) > 20 else None,
            }

    def save(self, context: AuthContext, space_id: UUID, command: RoadmapWrite) -> dict[str, Any]:
        _role(context, Action.PRODUCT_WORK_MANAGE)
        try:
            with self.engine.begin() as c:
                _space(c, context, space_id, access="manager", lock=True)
                node, snapshot = source(c, context, space_id, command.product_id)
                _line(
                    c, context, space_id, node["product_line_id"], access="manager", writable=True
                )
                t = tables.product_roadmap_revisions
                fingerprint = digest(
                    {"space_id": str(space_id), "command": command.model_dump(mode="json")}
                )
                prior = (
                    c.execute(
                        select(t).where(
                            t.c.tenant_id == context.tenant.id,
                            t.c.actor_user_id == context.user.id,
                            t.c.request_id == command.request_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if prior:
                    if prior["request_digest"] != fingerprint:
                        raise ProductWorkError("请求编号已用于另一项路线图操作")
                    return view(c, context, prior, snapshot)
                previous = latest_rows(c, context.tenant.id, [command.product_id]).get(
                    str(command.product_id)
                )
                version = previous["version"] if previous else 0
                if command.expected_version != version:
                    raise ProductWorkError("路线图已有新版本，请读取后再办理")
                if command.action == "withdraw":
                    if previous is None or previous["state"] != "published":
                        raise ProductWorkError("当前没有可撤回的路线图")
                    body, frozen = previous["body"], previous["source_snapshot"]
                else:
                    if node["lifecycle"] == "retired":
                        raise ProductWorkError("已退市产品只读；恢复产品后再发布路线图")
                    if snapshot is None or command.expected_source_digest != digest(snapshot):
                        raise ProductWorkError("产品或发布定义已变化，请重新核对依据")
                    assert command.body is not None
                    old = {}
                    if previous:
                        old = {item["key"]: item for item in previous["body"]["checkpoints"]}
                        new = {item.key: item for item in command.body.checkpoints}
                        if not old.keys() <= new.keys():
                            raise ProductWorkError("已有节点标识须保留；不再计划的节点请明确取消")
                        if any(new[key].kind != value["kind"] for key, value in old.items()):
                            raise ProductWorkError("原节点类型不能更换；请取消原节点并另建")
                    body = command.body.model_dump(mode="json")
                    for index, checkpoint in enumerate(command.body.checkpoints):
                        if checkpoint.disposition == "planned" or old.get(checkpoint.key, {}).get(
                            "owner_user_id"
                        ) != str(checkpoint.owner_user_id):
                            _member(
                                c,
                                context,
                                space_id,
                                checkpoint.owner_user_id,
                                line_id=node["product_line_id"],
                            )
                        old_basis = old.get(checkpoint.key, {}).get("basis")
                        if (
                            checkpoint.disposition == "cancelled"
                            and old_basis == checkpoint.basis.model_dump(mode="json")
                        ):
                            body["checkpoints"][index]["basis"] = old_basis
                        else:
                            body["checkpoints"][index]["basis"] = _fact(
                                c, context, checkpoint.basis
                            )
                    frozen = snapshot
                row = (
                    c.execute(
                        t.insert()
                        .values(
                            id=uuid4(),
                            tenant_id=context.tenant.id,
                            market_space_id=space_id,
                            product_line_id=node["product_line_id"],
                            product_id=command.product_id,
                            definition_id=UUID(frozen["definition_id"]),
                            release_id=UUID(frozen["release_id"]),
                            version=version + 1,
                            state="published" if command.action == "publish" else "withdrawn",
                            body=body,
                            source_snapshot=frozen,
                            source_digest=digest(frozen),
                            reason=command.reason,
                            actor_user_id=context.user.id,
                            request_id=command.request_id,
                            request_digest=fingerprint,
                            created_at=c.execute(select(func.clock_timestamp())).scalar_one(),
                        )
                        .returning(t)
                    )
                    .mappings()
                    .one()
                )
                _emit(c, context, space_id, "product_roadmap", command.action, row, before=previous)
                return view(c, context, row, snapshot)
        except IntegrityError as error:
            raise ProductWorkError("路线图未保存，请刷新当前版本后重试") from error
