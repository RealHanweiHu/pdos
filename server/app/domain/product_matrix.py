"""Read current released definitions through the existing product hierarchy."""

from itertools import combinations
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Digest
from app.db.schema import tables
from app.domain.product_catalog import PARENT_LEVEL
from app.domain.product_definitions import _definition, _row
from app.domain.product_roadmap import latest_rows
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _line,
    _line_filter,
    _plain,
    _space,
    digest,
)


class MatrixQuery(Contract):
    product_line_id: UUID | None = None
    root_id: UUID | None = None
    lifecycle: Literal["proposed", "developing", "available", "retired"] | None = None
    region: str = Field(default="", max_length=128)
    channel: str = Field(default="", max_length=128)
    scenario: str = Field(default="", max_length=2048)
    search: str = Field(default="", max_length=256)
    publication: Literal["all", "current", "missing", "withdrawn"] = "current"
    offset: int = Field(default=0, ge=0)
    revision: Digest | None = None


class MatrixChoice(Contract):
    product_id: UUID
    release_id: UUID


class MatrixComparison(Contract):
    choices: tuple[MatrixChoice, ...] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def unique_products(self) -> Self:
        if len({item.product_id for item in self.choices}) != len(self.choices):
            raise ValueError("比较产品不能重复")
        return self


def matrix_query(context: AuthContext, space_id: UUID, line_id: UUID | None) -> Any:
    nodes = tables.product_nodes
    releases = tables.definition_releases
    definitions = tables.product_definitions
    ranked = (
        select(
            releases,
            func.row_number()
            .over(partition_by=releases.c.product_id, order_by=releases.c.sequence.desc())
            .label("rank"),
        )
        .where(releases.c.tenant_id == context.tenant.id, releases.c.market_space_id == space_id)
        .subquery()
    )
    statement = (
        select(
            nodes,
            ranked.c.id.label("release_id"),
            ranked.c.action.label("release_action"),
            ranked.c.created_at.label("released_at"),
            definitions.c.id.label("definition_id"),
            definitions.c.revision_number.label("definition_revision"),
            *(
                definitions.c.content[key].label(key)
                for key in (
                    "target_users",
                    "scenarios",
                    "price_position",
                    "launch_window",
                )
            ),
        )
        .select_from(nodes)
        .outerjoin(ranked, (ranked.c.product_id == nodes.c.id) & (ranked.c.rank == 1))
        .outerjoin(
            definitions,
            (definitions.c.id == ranked.c.definition_id)
            & (definitions.c.tenant_id == nodes.c.tenant_id)
            & (definitions.c.market_space_id == nodes.c.market_space_id),
        )
        .where(
            nodes.c.tenant_id == context.tenant.id,
            nodes.c.market_space_id == space_id,
            _line_filter(nodes, context),
        )
        .order_by(nodes.c.code, nodes.c.id)
    )
    if line_id is not None:
        statement = statement.where(nodes.c.product_line_id == line_id)
    return statement


def capture(
    connection: Connection, context: AuthContext, space_id: UUID, line_id: UUID | None = None
) -> list[dict[str, Any]]:
    _space(connection, context, space_id)
    if line_id is not None:
        _line(connection, context, space_id, line_id)
    rows = list(
        connection.execute(matrix_query(context, space_id, line_id).limit(10001)).mappings()
    )
    if len(rows) > 10000:
        raise ProductWorkError("产品范围超过10000项，请按产品线缩小范围")
    nodes = {row["id"]: row for row in rows}
    result = []
    for row in rows:
        chain: list[dict[str, Any]] = []
        seen = set()
        current = row
        problem = None
        while current is not None:
            if current["id"] in seen:
                problem = "层级存在循环，请核对原产品归属"
                break
            seen.add(current["id"])
            chain.insert(
                0, {key: current[key] for key in ("id", "code", "name", "level", "version")}
            )
            if current["parent_id"] is None:
                if current["level"] != "line" or current["id"] != row["product_line_id"]:
                    problem = "产品线根节点不一致"
                break
            parent = nodes.get(current["parent_id"])
            if parent is None or parent["level"] != PARENT_LEVEL.get(current["level"]):
                problem = "父级缺失或层级不匹配"
                break
            current = parent
        publication = (
            "missing"
            if row["release_id"] is None
            else "current"
            if row["release_action"] == "publish"
            else "withdrawn"
        )
        value = {
            key: row[key]
            for key in (
                "id",
                "product_line_id",
                "parent_id",
                "level",
                "code",
                "name",
                "version",
                "lifecycle",
                "regions",
                "channels",
                "release_id",
                "released_at",
                "definition_id",
                "definition_revision",
            )
        }
        value.update(path=chain, hierarchy_warning=problem, publication=publication)
        # A withdrawn release must never revive an earlier publication in the matrix.
        for key in ("target_users", "scenarios", "price_position", "launch_window"):
            value[key] = row[key] if publication == "current" else None
        value["href"] = (
            f"/product-work?space={space_id}&tab=definitions#definition-{row['definition_id']}"
            if row["definition_id"]
            else None
        )
        result.append(_plain(value))
    return result


class ProductMatrixService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def overview(self, context: AuthContext, space_id: UUID, query: MatrixQuery) -> dict[str, Any]:
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            rows = capture(connection, context, space_id, query.product_line_id)
            if query.root_id and not any(row["id"] == str(query.root_id) for row in rows):
                raise ProductWorkAccessError("产品层级不存在或不可访问")
            facets = {
                key: sorted({item for row in rows for item in (row[key] or [])})
                for key in ("regions", "channels", "scenarios")
            }
            scope = rows
            if query.root_id:
                scope = [
                    row
                    for row in scope
                    if str(query.root_id) in [node["id"] for node in row["path"]]
                ]
            counts = {
                key: sum(row["publication"] == key for row in scope)
                for key in ("current", "missing", "withdrawn")
            }
            filtered = [
                row
                for row in scope
                if (
                    (query.publication == "all" or row["publication"] == query.publication)
                    and (query.lifecycle is None or row["lifecycle"] == query.lifecycle)
                    and (not query.region or query.region in row["regions"])
                    and (not query.channel or query.channel in row["channels"])
                    and (not query.scenario or query.scenario in (row["scenarios"] or []))
                    and (
                        not query.search
                        or query.search.casefold()
                        in " ".join(
                            [
                                row["code"],
                                row["name"],
                                *(row["target_users"] or []),
                                *(row["scenarios"] or []),
                                (row["price_position"] or {}).get("text", ""),
                                (row["launch_window"] or {}).get("text", ""),
                            ]
                        ).casefold()
                    )
                )
            ]
            roadmap_versions = latest_rows(
                connection,
                context.tenant.id,
                [UUID(row["id"]) for row in filtered],
                summary_only=True,
            )
            revision = digest(
                {
                    "filters": query.model_dump(mode="json", exclude={"offset", "revision"}),
                    "rows": filtered,
                    "roadmaps": {key: _plain(value) for key, value in roadmap_versions.items()},
                    "counts": counts,
                    "facets": facets,
                }
            )
            if query.offset and query.revision != revision:
                raise ProductWorkError("产品或发布版本已变化，请从第一页刷新")
            page = filtered[query.offset : query.offset + 20]
            roadmap_rows = latest_rows(
                connection, context.tenant.id, [UUID(row["id"]) for row in page]
            )
            for row in page:
                roadmap = roadmap_rows.get(row["id"])
                row["roadmap"] = _plain(roadmap) if roadmap else None
                row["roadmap_source_current"] = bool(
                    roadmap
                    and row["publication"] == "current"
                    and str(roadmap["release_id"]) == row["release_id"]
                    and roadmap["source_snapshot"]["product"]["version"] == row["version"]
                )
                row["roadmap_href"] = (
                    f"/product-work?space={space_id}&tab=matrix&roadmap_product={row['id']}#product-roadmap"
                )
            return {
                "items": page,
                "total": len(filtered),
                "scope_counts": counts,
                "facets": facets,
                "revision": revision,
                "next_offset": query.offset + 20 if len(filtered) > query.offset + 20 else None,
            }

    def compare(
        self, context: AuthContext, space_id: UUID, query: MatrixComparison
    ) -> dict[str, Any]:
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            rows = {row["id"]: row for row in capture(connection, context, space_id)}
            products: list[dict[str, Any]] = []
            for choice in query.choices:
                row = rows.get(str(choice.product_id))
                if row is None:
                    raise ProductWorkAccessError("所选产品不存在或不可访问")
                if row["publication"] != "current" or row["release_id"] != str(choice.release_id):
                    raise ProductWorkError("所选定义已撤回或发布新版本，请重新选择")
                definition = _definition(
                    connection,
                    context,
                    _row(connection, context, space_id, UUID(row["definition_id"])),
                )
                products.append(
                    {
                        **row,
                        "content": definition["content"],
                        "source_warnings": definition["source_warnings"],
                        "sources": definition["contract"]["sources"],
                        "definition_digest": definition["payload_digest"],
                    }
                )
            pairs = []
            for left, right in combinations(products, 2):
                shared = {
                    key: sorted(set(left[key] or []) & set(right[key] or []))
                    for key in ("target_users", "scenarios", "regions", "channels")
                }
                shared["included_features"] = sorted(
                    set(left["content"]["included_features"])
                    & set(right["content"]["included_features"])
                )
                platforms = [
                    {node["id"] for node in item["path"] if node["level"] == "platform"}
                    for item in (left, right)
                ]
                related = left["id"] in [node["id"] for node in right["path"]] or right["id"] in [
                    node["id"] for node in left["path"]
                ]
                pairs.append(
                    {
                        "left_id": left["id"],
                        "right_id": right["id"],
                        "shared": shared,
                        "same_platform": bool(platforms[0] & platforms[1]),
                        "ancestor_related": related,
                    }
                )
            return {
                "products": products,
                "pairs": pairs,
                "revision": digest(products),
                "comparison_version": "published-product-matrix.v1",
                "limits": [
                    "仅比较所选当前发布定义，空白表示未声明；不代表整个市场空白。",
                    "相同文字或功能标识仅提示核对重叠；父子层级可能有意继承，不判定蚕食。",
                    "同平台归属不代表已经完成工程复用；地区与渠道不自动继承父级。",
                    "价格与上市窗口保留原文及事实类型，不推算价格带、销售预测或确定上市日期。",
                    "规格条目标识只在各自定义中稳定，需核对单位、条件与判据后再比较。",
                ],
            }
