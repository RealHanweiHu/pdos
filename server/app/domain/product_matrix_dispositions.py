"""Named matrix dispositions and real follow-up work, without changing product releases."""

from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, Key, Text
from app.db.schema import tables
from app.domain.product_catalog import _node_row
from app.domain.product_definitions import _release
from app.domain.product_matrix_records import read_view, record_row
from app.domain.product_workspace import (
    ProductWorkError,
    WorkDraft,
    _emit,
    _line,
    _line_filter,
    _member,
    _plain,
    _role,
    _space,
    create_work_in_connection,
    digest,
)


class DispositionRead(Contract):
    record_id: UUID
    series_id: UUID | None = None
    before_id: UUID | None = None


class DispositionWrite(Contract):
    record_id: UUID
    request_id: UUID
    supersedes_id: UUID | None = None
    expected_source_digest: Digest
    topic: Literal["coverage_gap", "positioning_overlap", "platform_reuse"]
    product_ids: tuple[UUID, ...] = Field(min_length=1, max_length=8)
    criterion_keys: tuple[Key, ...] = Field(min_length=1, max_length=20)
    title: Text
    outcome: Literal[
        "investigate",
        "retain",
        "revise_definition",
        "revise_roadmap",
        "not_applicable",
        "withdrawn",
    ]
    reason: Text
    work_item_id: UUID | None = None
    followup: WorkDraft | None = None

    @model_validator(mode="after")
    def shape(self) -> Self:
        if len(set(self.product_ids)) != len(self.product_ids) or len(
            set(self.criterion_keys)
        ) != len(self.criterion_keys):
            raise ValueError("产品与判据不能重复")
        if self.topic != "coverage_gap" and len(self.product_ids) < 2:
            raise ValueError("重叠/复用处置须明确至少两个原选产品")
        if self.followup is not None and self.work_item_id is not None:
            raise ValueError("请选择关联原工作或新建工作")
        if (
            self.outcome in {"investigate", "revise_definition", "revise_roadmap"}
            and self.work_item_id is None
            and self.followup is None
        ):
            raise ValueError("待补证或修订须落实到实际跟进工作")
        if self.outcome == "withdrawn" and (
            self.supersedes_id is None or self.followup is not None
        ):
            raise ValueError("撤回保留原工作，不新建工作")
        if self.followup is not None and (
            self.followup.owner_user_id is None
            or self.followup.due_at is None
            or (
                self.followup.action_type != "evidence_collection"
                and self.followup.receiver_user_id is None
            )
        ):
            raise ValueError("跟进工作须明确负责人、期限及所需接收人")
        return self


def scope(
    c: Connection, context: AuthContext, space: UUID, record: UUID, *, write: bool = False
) -> Any:
    _space(c, context, space, access="manager" if write else "viewer", lock=write)
    saved = record_row(c, context, space, record)
    if write:
        _role(context, Action.PRODUCT_WORK_MANAGE)
        _line(c, context, space, saved["product_line_id"], access="manager", writable=True)
    return saved


def source(c: Connection, context: AuthContext, space: UUID, saved: Any) -> dict[str, Any]:
    view = read_view(c, context, space, saved)
    nodes = [
        _node_row(c, context, space, UUID(p["id"])) for p in saved["result"]["snapshot"]["products"]
    ]
    segment = tables.market_segments
    original = (
        c.execute(
            select(segment).where(
                segment.c.tenant_id == context.tenant.id, segment.c.id == saved["segment_id"]
            )
        )
        .mappings()
        .one()
    )
    latest = (
        c.execute(
            select(segment)
            .where(
                segment.c.tenant_id == context.tenant.id,
                segment.c.series_id == original["series_id"],
            )
            .order_by(segment.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one()
    )
    body = _plain(
        {
            "record_id": saved["id"],
            "record_version": saved["version"],
            "result_digest": saved["result_digest"],
            "current_products": [
                {"node": dict(n), "release": _plain(_release(c, context, n["id"]))} for n in nodes
            ],
            "current_market_id": latest["id"],
            "current_market_version": latest["version"],
            "source_changes": view["source_changes"],
            "source_warnings": view["current_source_warnings"],
        }
    )
    return {**body, "digest": digest(body)}


def work(c: Connection, context: AuthContext, space: UUID, identity: UUID) -> Any:
    t = tables.scoped_work_items
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == context.tenant.id,
                t.c.market_space_id == space,
                t.c.id == identity,
                _line_filter(t, context),
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("跟进工作不存在或不在当前可读范围")
    return row


def view(
    c: Connection, context: AuthContext, space: UUID, row: Any, current: dict[str, Any]
) -> dict[str, Any]:
    actor = c.execute(
        select(tables.users.c.display_name).where(
            tables.users.c.tenant_id == context.tenant.id, tables.users.c.id == row["actor_user_id"]
        )
    ).scalar_one()
    current_work = work(c, context, space, row["work_item_id"]) if row["work_item_id"] else None
    return {
        **_plain(row),
        "actor_name": actor,
        "sources_current": row["source_digest"] == current["digest"],
        "current_work": _plain(current_work) if current_work is not None else None,
        "work_changed": current_work is not None
        and digest(_plain(current_work)) != digest(row["work_snapshot"]),
    }


class ProductMatrixDispositionService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def read(self, context: AuthContext, space: UUID, query: DispositionRead) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            saved = scope(c, context, space, query.record_id)
            current = source(c, context, space, saved)
            can_manage = True
            try:
                _role(context, Action.PRODUCT_WORK_MANAGE)
                selected_space = _space(c, context, space, access="manager")
                if selected_space["lifecycle"] == "archived":
                    can_manage = False
                for line in {
                    saved["product_line_id"],
                    *(n["node"]["product_line_id"] for n in current["current_products"]),
                }:
                    _line(
                        c,
                        context,
                        space,
                        UUID(str(line)) if line else None,
                        access="manager",
                        writable=True,
                    )
            except (ValueError, PermissionError):
                can_manage = False
            t = tables.product_matrix_dispositions
            q = select(t).where(
                t.c.tenant_id == context.tenant.id,
                t.c.market_space_id == space,
                t.c.record_id == query.record_id,
            )
            if query.series_id:
                q = q.where(t.c.series_id == query.series_id)
            if query.before_id:
                before = c.execute(q.where(t.c.id == query.before_id)).mappings().one_or_none()
                if before is None:
                    raise ProductWorkError("请从原处置记录继续翻页")
                q = q.where(
                    (t.c.created_at < before["created_at"])
                    | ((t.c.created_at == before["created_at"]) & (t.c.id < before["id"]))
                )
            values = (
                c.execute(q.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21))
                .mappings()
                .all()
            )
            items = []
            for row in values[:20]:
                newer = c.execute(
                    select(t.c.id).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.series_id == row["series_id"],
                        t.c.version > row["version"],
                    )
                ).first()
                items.append({**view(c, context, space, row, current), "is_latest": newer is None})
            return {
                "source": current,
                "can_manage": can_manage,
                "items": items,
                "next_before_id": str(values[19]["id"]) if len(values) > 20 else None,
                "products": [
                    {k: p[k] for k in ("id", "code", "name", "product_line_id")}
                    for p in saved["result"]["snapshot"]["products"]
                ],
                "criteria": [item["criterion"] for item in saved["result"]["criteria"]],
            }

    def save(self, context: AuthContext, space: UUID, command: DispositionWrite) -> dict[str, Any]:
        with self.engine.begin() as c:
            saved = scope(c, context, space, command.record_id, write=True)
            t = tables.product_matrix_dispositions
            fingerprint = digest({"space": str(space), "body": command.model_dump(mode="json")})
            existing = (
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
            current = source(c, context, space, saved)
            if existing is not None:
                if existing["request_digest"] != fingerprint:
                    raise ProductWorkError("同一请求不能用于其他处置")
                return view(c, context, space, existing, current)
            if current["digest"] != command.expected_source_digest:
                raise ProductWorkError("原对照当前依据已有变化，请刷新核对后保存")
            products = {UUID(n["node"]["id"]): n["node"] for n in current["current_products"]}
            if not set(command.product_ids).issubset(products) or not set(
                command.criterion_keys
            ).issubset({i["criterion"]["key"] for i in saved["result"]["criteria"]}):
                raise ProductWorkError("处置仅可引用原对照中实际选择的产品和判据")
            for node in products.values():
                _line(
                    c,
                    context,
                    space,
                    UUID(node["product_line_id"]),
                    access="manager",
                    writable=True,
                )
            prior = None
            if command.supersedes_id:
                prior = (
                    c.execute(
                        select(t).where(
                            t.c.tenant_id == context.tenant.id,
                            t.c.market_space_id == space,
                            t.c.record_id == saved["id"],
                            t.c.id == command.supersedes_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if (
                    prior is None
                    or c.execute(
                        select(t.c.id).where(
                            t.c.tenant_id == context.tenant.id,
                            t.c.series_id == prior["series_id"],
                            t.c.version > prior["version"],
                        )
                    ).first()
                ):
                    raise ProductWorkError("处置已更新，请读取最新版后再修订")
                if (
                    prior["topic"] != command.topic
                    or set(prior["product_ids"]) != {str(v) for v in command.product_ids}
                    or set(prior["criterion_keys"]) != set(command.criterion_keys)
                ):
                    raise ProductWorkError("同一处置主题保留原产品与判据；其他范围请新建主题")
            linked = command.work_item_id
            if command.followup:
                if command.followup.product_line_id not in {
                    UUID(products[v]["product_line_id"]) for v in command.product_ids
                }:
                    raise ProductWorkError("跟进工作须明确属于所选产品的一条产品线")
                linked = UUID(create_work_in_connection(c, context, space, command.followup)["id"])
            if command.outcome == "withdrawn":
                linked = prior["work_item_id"] if prior else None
            actual_work = work(c, context, space, linked) if linked else None
            if actual_work is not None and command.outcome != "withdrawn":
                if actual_work["product_line_id"] not in {
                    UUID(products[v]["product_line_id"]) for v in command.product_ids
                }:
                    raise ProductWorkError("关联工作须属于所选产品的产品线")
                if command.outcome in {"investigate", "revise_definition", "revise_roadmap"} and (
                    actual_work["state"] in {"cancelled", "completed"}
                    or actual_work["owner_user_id"] is None
                    or actual_work["due_at"] is None
                    or (
                        actual_work["acceptance_required"]
                        and actual_work["receiver_user_id"] is None
                    )
                ):
                    raise ProductWorkError("请选择未结束且责任与期限明确的实际工作")
                if command.outcome in {"investigate", "revise_definition", "revise_roadmap"}:
                    _member(
                        c,
                        context,
                        space,
                        actual_work["owner_user_id"],
                        actual_work["product_line_id"],
                    )
                    _member(
                        c,
                        context,
                        space,
                        actual_work["receiver_user_id"],
                        actual_work["product_line_id"],
                    )
            identity = uuid4()
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        tenant_id=context.tenant.id,
                        market_space_id=space,
                        record_id=saved["id"],
                        series_id=prior["series_id"] if prior else identity,
                        supersedes_id=prior["id"] if prior else None,
                        version=prior["version"] + 1 if prior else 1,
                        topic=command.topic,
                        product_ids=[str(v) for v in command.product_ids],
                        criterion_keys=list(command.criterion_keys),
                        title=command.title,
                        outcome=command.outcome,
                        reason=command.reason,
                        source_snapshot=current,
                        source_digest=current["digest"],
                        work_item_id=linked,
                        work_snapshot=_plain(actual_work) if actual_work is not None else None,
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
            _emit(c, context, space, "product_matrix_disposition", "recorded", row, before=prior)
            return view(c, context, space, row, current)
