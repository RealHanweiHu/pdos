"""Immutable, scoped market coverage records and replay of their frozen inputs."""

from typing import Any
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, and_, exists, func, or_, select
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.product_catalog import _node_row
from app.domain.product_definitions import _release
from app.domain.product_evidence import evidence_quality
from app.domain.product_matrix import MatrixChoice
from app.domain.product_matrix_coverage import (
    CoverageCalculation,
    CoveragePreparation,
    ProductMatrixCoverageService,
    calculate_snapshot,
)
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _emit,
    _line,
    _line_filter,
    _plain,
    _role,
    _space,
    digest,
)


class MatrixRecordSave(Contract):
    request_id: UUID
    supersedes_id: UUID | None = None
    title: Text
    reason: Text
    calculation: CoverageCalculation
    expected_result_digest: Digest


class MatrixRecordHistory(Contract):
    before_id: UUID | None = None
    series_id: UUID | None = None
    search: str = Field(default="", max_length=256)


class MatrixRecordRead(Contract):
    record_id: UUID


def visible(context: AuthContext) -> Any:
    t, refs, nodes = (
        tables.product_matrix_records,
        tables.product_matrix_record_products,
        tables.product_nodes,
    )
    inaccessible = exists(
        select(refs.c.product_id)
        .join(nodes, (nodes.c.tenant_id == refs.c.tenant_id) & (nodes.c.id == refs.c.product_id))
        .where(
            refs.c.tenant_id == t.c.tenant_id,
            refs.c.record_id == t.c.id,
            ~_line_filter(nodes, context),
        )
    )
    return and_(_line_filter(t, context), ~inaccessible)


def record_row(c: Connection, context: AuthContext, space_id: UUID, record_id: UUID) -> Any:
    t = tables.product_matrix_records
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == context.tenant.id,
                t.c.market_space_id == space_id,
                t.c.id == record_id,
                visible(context),
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkAccessError("对照记录不存在或当前无权读取全部原资料")
    return row


def read_view(c: Connection, context: AuthContext, space_id: UUID, row: Any) -> dict[str, Any]:
    result = row["result"]
    snapshot = result["snapshot"]
    changes = []
    segment = tables.market_segments
    original = (
        c.execute(
            select(segment).where(
                segment.c.tenant_id == context.tenant.id, segment.c.id == row["segment_id"]
            )
        )
        .mappings()
        .one()
    )
    if c.execute(
        select(segment.c.id).where(
            segment.c.tenant_id == context.tenant.id,
            segment.c.series_id == original["series_id"],
            segment.c.version > original["version"],
        )
    ).first():
        changes.append("市场细分已有新版本，保存的原需求未改写")
    refs = [ref for entry in snapshot["facts"] for ref in entry["fact"]["sources"]]
    for product in snapshot["products"]:
        node = _node_row(c, context, space_id, UUID(product["id"]))
        _line(c, context, space_id, node["product_line_id"])
        release = _release(c, context, UUID(product["id"]))
        if (
            release is None
            or release["action"] != "publish"
            or str(release["id"]) != product["release_id"]
        ):
            changes.append(f"{product['code']} 的当前发布定义已变化或撤回")
        if node["version"] != product["version"]:
            changes.append(f"{product['code']} 的产品范围或登记信息已变化")
        refs.extend(product["sources"])
    actor = c.execute(
        select(tables.users.c.display_name).where(
            tables.users.c.tenant_id == context.tenant.id, tables.users.c.id == row["actor_user_id"]
        )
    ).scalar_one()
    return {
        **_plain(row),
        "actor_name": actor,
        "source_changes": changes,
        "current_source_warnings": evidence_quality(c, context, refs),
    }


class ProductMatrixRecordService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def save(
        self, context: AuthContext, space_id: UUID, command: MatrixRecordSave
    ) -> dict[str, Any]:
        _role(context, Action.PRODUCT_WORK_CONTRIBUTE)
        try:
            with self.engine.begin() as c:
                _space(c, context, space_id, access="contributor", lock=True)
                t = tables.product_matrix_records
                fingerprint = digest(
                    {"space_id": str(space_id), "command": command.model_dump(mode="json")}
                )
                prior = (
                    c.execute(
                        select(t.c.id, t.c.request_digest).where(
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
                        raise ProductWorkError("请求编号已用于另一份对照记录")
                    return read_view(
                        c, context, space_id, record_row(c, context, space_id, prior["id"])
                    )
                result = ProductMatrixCoverageService(self.engine).calculate(
                    context, space_id, command.calculation
                )
                if result["result_digest"] != command.expected_result_digest:
                    raise ProductWorkError("对照结果或依据已变化，请重新计算后保存")
                segment = tables.market_segments
                market = (
                    c.execute(
                        select(segment).where(
                            segment.c.tenant_id == context.tenant.id,
                            segment.c.market_space_id == space_id,
                            segment.c.id == command.calculation.segment_id,
                        )
                    )
                    .mappings()
                    .one()
                )
                _line(
                    c,
                    context,
                    space_id,
                    market["product_line_id"],
                    access="contributor",
                    writable=True,
                )
                previous = (
                    record_row(c, context, space_id, command.supersedes_id)
                    if command.supersedes_id
                    else None
                )
                if previous:
                    old_policy = previous["inputs"].get("scoring_policy")
                    new_policy = command.calculation.scoring_policy
                    if (
                        old_policy is not None
                        and new_policy is not None
                        and old_policy["policy_key"] == new_policy.policy_key
                        and old_policy != new_policy.model_dump(mode="json")
                        and new_policy.policy_version <= old_policy["policy_version"]
                    ):
                        raise ProductWorkError("本对照评分政策已修改，请增加政策版本后重新计算保存")
                    if c.execute(
                        select(t.c.id).where(
                            t.c.tenant_id == context.tenant.id, t.c.supersedes_id == previous["id"]
                        )
                    ).first():
                        raise ProductWorkError("原记录已有后续版本，请读取最新版本或另存独立对照")
                    old_market = c.execute(
                        select(segment.c.series_id).where(
                            segment.c.tenant_id == context.tenant.id,
                            segment.c.id == previous["segment_id"],
                        )
                    ).scalar_one()
                    if old_market != market["series_id"]:
                        raise ProductWorkError("修订须属于同一市场细分；不同细分请另存对照")
                identifier = uuid4()
                row = (
                    c.execute(
                        t.insert()
                        .values(
                            id=identifier,
                            tenant_id=context.tenant.id,
                            market_space_id=space_id,
                            product_line_id=market["product_line_id"],
                            segment_id=market["id"],
                            series_id=previous["series_id"] if previous else identifier,
                            supersedes_id=previous["id"] if previous else None,
                            version=previous["version"] + 1 if previous else 1,
                            title=command.title,
                            reason=command.reason,
                            inputs=command.calculation.model_dump(mode="json"),
                            result=result,
                            result_digest=result["result_digest"],
                            formula_version=result["formula_version"],
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
                for product in result["snapshot"]["products"]:
                    c.execute(
                        tables.product_matrix_record_products.insert().values(
                            tenant_id=context.tenant.id,
                            market_space_id=space_id,
                            record_id=identifier,
                            product_id=UUID(product["id"]),
                            definition_id=UUID(product["definition_id"]),
                            release_id=UUID(product["release_id"]),
                        )
                    )
                _emit(c, context, space_id, "product_matrix_record", "saved", row, before=previous)
                return read_view(c, context, space_id, row)
        except IntegrityError as error:
            raise ProductWorkError("对照记录未保存，请刷新来源或原记录后重试") from error

    def read(self, context: AuthContext, space_id: UUID, query: MatrixRecordRead) -> dict[str, Any]:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            _space(c, context, space_id)
            return read_view(
                c, context, space_id, record_row(c, context, space_id, query.record_id)
            )

    def history(
        self, context: AuthContext, space_id: UUID, query: MatrixRecordHistory
    ) -> dict[str, Any]:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            _space(c, context, space_id)
            t, users = tables.product_matrix_records, tables.users
            statement = (
                select(
                    *(
                        t.c[key]
                        for key in (
                            "id",
                            "series_id",
                            "version",
                            "title",
                            "reason",
                            "created_at",
                            "supersedes_id",
                        )
                    ),
                    users.c.display_name.label("actor_name"),
                )
                .join(
                    users, (users.c.tenant_id == t.c.tenant_id) & (users.c.id == t.c.actor_user_id)
                )
                .where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.market_space_id == space_id,
                    visible(context),
                    t.c.title.contains(query.search, autoescape=True),
                )
            )
            if query.series_id:
                statement = statement.where(t.c.series_id == query.series_id)
            if query.before_id:
                before = record_row(c, context, space_id, query.before_id)
                statement = statement.where(
                    or_(
                        t.c.created_at < before["created_at"],
                        and_(t.c.created_at == before["created_at"], t.c.id < before["id"]),
                    )
                )
            rows = list(
                c.execute(
                    statement.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21)
                ).mappings()
            )
            return {
                "items": [_plain(row) for row in rows[:20]],
                "next_before_id": str(rows[19]["id"]) if len(rows) > 20 else None,
            }

    def replay(
        self, context: AuthContext, space_id: UUID, query: MatrixRecordRead
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            _space(c, context, space_id)
            row = record_row(c, context, space_id, query.record_id)
            result = calculate_snapshot(
                CoverageCalculation.model_validate(row["inputs"]), row["result"]["snapshot"]
            )
            return {
                "record_id": str(row["id"]),
                "formula_version": row["formula_version"],
                "matches_saved": result == row["result"]
                and result["result_digest"] == row["result_digest"],
                "saved_digest": row["result_digest"],
                "replayed_digest": result["result_digest"],
                "scope": "按原输入、原资料及原规则重算，不表示当前产品或市场仍相同",
            }

    def refresh_inputs(
        self, context: AuthContext, space_id: UUID, query: MatrixRecordRead
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            _space(c, context, space_id)
            row = record_row(c, context, space_id, query.record_id)
            t = tables.market_segments
            series = c.execute(
                select(t.c.series_id).where(
                    t.c.tenant_id == context.tenant.id, t.c.id == row["segment_id"]
                )
            ).scalar_one()
            market = (
                c.execute(
                    select(t)
                    .where(t.c.tenant_id == context.tenant.id, t.c.series_id == series)
                    .order_by(t.c.version.desc())
                    .limit(1)
                )
                .mappings()
                .one()
            )
            _line(c, context, space_id, market["product_line_id"])
            choices = []
            for product in row["result"]["snapshot"]["products"]:
                release = _release(c, context, UUID(product["id"]))
                if release is None or release["action"] != "publish":
                    raise ProductWorkError("原选产品存在定义撤回；请先选定有效产品另建对照")
                choices.append(
                    MatrixChoice(product_id=UUID(product["id"]), release_id=release["id"])
                )
        prepared = ProductMatrixCoverageService(self.engine).prepare(
            context, space_id, CoveragePreparation(choices=tuple(choices), segment_id=market["id"])
        )
        return {
            "record_id": str(row["id"]),
            "title": row["title"],
            "prepared": prepared,
            "choices": [item.model_dump(mode="json") for item in choices],
            "criteria": row["inputs"]["criteria"],
            "scoring_policy": row["inputs"].get("scoring_policy"),
            "notice": (
                "已读取当前市场与发布定义；旧判据与条目对应只作为草稿，请逐项重核后重新计算保存"
            ),
        }
