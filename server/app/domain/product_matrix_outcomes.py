"""Scoped implementation observations tied to real published versions and work receipts."""

from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Digest, SourceRef, Text
from app.contracts.product_records import FactStatement
from app.db.schema import tables
from app.domain.market_analysis import _fact
from app.domain.product_definitions import _definition, _release, _row
from app.domain.product_evidence import evidence_quality
from app.domain.product_matrix_dispositions import scope, source, work
from app.domain.product_roadmap import latest_rows
from app.domain.product_roadmap import source as roadmap_source
from app.domain.product_roadmap import view as roadmap_view
from app.domain.product_workspace import ProductWorkError, _emit, _line, _plain, _sources, digest


class OutcomeRead(Contract):
    disposition_id: UUID
    before_version: int | None = Field(default=None, ge=1)


class PublishedVersion(Contract):
    product_id: UUID
    kind: Literal["definition", "roadmap"]
    ref_id: UUID


class OutcomeWrite(Contract):
    disposition_id: UUID
    request_id: UUID
    expected_version: int = Field(ge=0)
    expected_source_digest: Digest
    state: Literal["progress", "verified", "not_implemented", "withdrawn"]
    checked_product_ids: tuple[UUID, ...] = Field(min_length=1, max_length=8)
    versions: tuple[PublishedVersion, ...] = Field(default=(), max_length=16)
    reason: Text
    verification: FactStatement

    @model_validator(mode="after")
    def shape(self) -> Self:
        if len(set(self.checked_product_ids)) != len(self.checked_product_ids) or len(
            {(v.product_id, v.kind) for v in self.versions}
        ) != len(self.versions):
            raise ValueError("核对产品和对应版本不能重复")
        if any(v.product_id not in self.checked_product_ids for v in self.versions):
            raise ValueError("发布版本须属于本次明确核对的产品")
        if self.verification.approval is not None:
            raise ValueError("验证说明不能伪造正式批准引用")
        if self.state == "verified" and self.verification.fact_kind == "hypothesis":
            raise ValueError("落实核对须提供实际依据，不能仅凭假设")
        if self.state == "withdrawn" and self.expected_version == 0:
            raise ValueError("尚无结果可撤回")
        return self


def context_source(
    c: Connection, context: AuthContext, space: UUID, identity: UUID, *, write: bool = False
) -> tuple[Any, dict[str, Any]]:
    d = tables.product_matrix_dispositions
    disposition = (
        c.execute(
            select(d).where(
                d.c.tenant_id == context.tenant.id, d.c.market_space_id == space, d.c.id == identity
            )
        )
        .mappings()
        .one_or_none()
    )
    if disposition is None:
        raise ProductWorkError("原处置不存在")
    saved = scope(c, context, space, disposition["record_id"], write=write)
    current = source(c, context, space, saved)
    latest_disposition = c.execute(
        select(d.c.id)
        .where(d.c.tenant_id == context.tenant.id, d.c.series_id == disposition["series_id"])
        .order_by(d.c.version.desc())
        .limit(1)
    ).scalar_one()
    if write and (latest_disposition != identity or disposition["outcome"] == "withdrawn"):
        raise ProductWorkError("请从未撤回的最新处置登记结果；原结果历史保留")
    for node in current["current_products"]:
        _line(
            c,
            context,
            space,
            UUID(node["node"]["product_line_id"]),
            access="manager" if write else "viewer",
            writable=write,
        )
    options = []
    roadmaps = latest_rows(c, context.tenant.id, [UUID(v) for v in disposition["product_ids"]])
    original_products = {v["id"]: v for v in saved["result"]["snapshot"]["products"]}
    for identity_text in disposition["product_ids"]:
        identity_product = UUID(identity_text)
        released = _release(c, context, identity_product)
        if released is not None and released["action"] == "publish":
            definition_row = _row(c, context, space, released["definition_id"])
            definition = _definition(c, context, definition_row)
            options.append(
                {
                    "product_id": identity_text,
                    "kind": "definition",
                    "ref_id": str(released["id"]),
                    "label": (
                        f"{original_products[identity_text]['name']} · "
                        f"定义 v{definition['revision_number']}"
                    ),
                    "snapshot": {"release": _plain(released), "definition": _plain(definition_row)},
                    "later_than_disposition": released["created_at"] >= disposition["created_at"]
                    and str(released["id"]) != original_products[identity_text]["release_id"]
                    and str(released["definition_id"])
                    != original_products[identity_text]["definition_id"],
                    "warnings": definition["source_warnings"],
                    "href": (
                        f"/product-work?space={space}&tab=definitions"
                        f"#definition-{released['definition_id']}"
                    ),
                }
            )
        roadmap = roadmaps.get(identity_text)
        if roadmap is not None and roadmap["state"] == "published":
            _, current_definition = roadmap_source(c, context, space, identity_product)
            mapped = roadmap_view(c, context, roadmap, current_definition)
            options.append(
                {
                    "product_id": identity_text,
                    "kind": "roadmap",
                    "ref_id": str(roadmap["id"]),
                    "label": (
                        f"{original_products[identity_text]['name']} · 路线图 v{roadmap['version']}"
                    ),
                    "snapshot": _plain(roadmap),
                    "later_than_disposition": roadmap["created_at"] >= disposition["created_at"],
                    "warnings": mapped["source_warnings"]
                    + ([] if mapped["source_current"] else ["路线图所依定义或产品范围已变化"]),
                    "href": (
                        f"/product-work?space={space}&tab=matrix&roadmap_product={identity_text}"
                    ),
                }
            )
    actual_work = (
        work(c, context, space, disposition["work_item_id"])
        if disposition["work_item_id"]
        else None
    )
    work_warnings = evidence_quality(c, context, actual_work["evidence"]) if actual_work else []
    value = {
        "disposition": _plain(disposition),
        "latest_disposition_id": str(latest_disposition),
        "market_product_line_id": str(saved["product_line_id"])
        if saved["product_line_id"]
        else None,
        "matrix_source": current,
        "work": _plain(actual_work) if actual_work is not None else None,
        "work_warnings": work_warnings,
        "options": options,
        "products": [
            {k: original_products[v][k] for k in ("id", "name", "code")}
            for v in disposition["product_ids"]
        ],
    }
    return disposition, {**value, "digest": digest(value)}


def result_view(
    c: Connection, context: AuthContext, row: Any, current: dict[str, Any]
) -> dict[str, Any]:
    actor = c.execute(
        select(tables.users.c.display_name).where(
            tables.users.c.tenant_id == context.tenant.id, tables.users.c.id == row["actor_user_id"]
        )
    ).scalar_one()
    t = tables.product_matrix_outcome_versions
    versions = (
        c.execute(select(t).where(t.c.tenant_id == context.tenant.id, t.c.outcome_id == row["id"]))
        .mappings()
        .all()
    )
    return {
        **_plain(row),
        "actor_name": actor,
        "versions": [_plain(v) for v in versions],
        "sources_current": row["source_digest"] == current["digest"],
        "evidence_warnings": evidence_quality(c, context, row["verification"]["sources"]),
        "unchecked_product_ids": [
            v for v in current["disposition"]["product_ids"] if v not in row["checked_product_ids"]
        ],
    }


class ProductMatrixOutcomeService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def read(self, context: AuthContext, space: UUID, query: OutcomeRead) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            _, current = context_source(c, context, space, query.disposition_id)
            can_record = True
            try:
                # Evaluate permissions without acquiring a write lock in a history read.
                from app.auth.roles import Action
                from app.domain.product_workspace import _role, _space

                _role(context, Action.PRODUCT_WORK_MANAGE)
                s = _space(c, context, space, access="manager")
                can_record = (
                    s["lifecycle"] != "archived"
                    and current["latest_disposition_id"] == str(query.disposition_id)
                    and current["disposition"]["outcome"] != "withdrawn"
                )
                for line in {
                    n["node"]["product_line_id"]
                    for n in current["matrix_source"]["current_products"]
                } | {current["market_product_line_id"]}:
                    _line(
                        c,
                        context,
                        space,
                        UUID(line) if line else None,
                        access="manager",
                        writable=True,
                    )
            except (ValueError, PermissionError):
                can_record = False
            t = tables.product_matrix_outcomes
            q = select(t).where(
                t.c.tenant_id == context.tenant.id, t.c.disposition_id == query.disposition_id
            )
            version = c.execute(
                select(func.coalesce(func.max(t.c.version), 0)).where(
                    t.c.tenant_id == context.tenant.id, t.c.disposition_id == query.disposition_id
                )
            ).scalar_one()
            if query.before_version:
                q = q.where(t.c.version < query.before_version)
            values = c.execute(q.order_by(t.c.version.desc()).limit(21)).mappings().all()
            return {
                "source": current,
                "can_record": can_record,
                "version": version,
                "items": [result_view(c, context, row, current) for row in values[:20]],
                "next_before_version": values[19]["version"] if len(values) > 20 else None,
            }

    def save(self, context: AuthContext, space: UUID, command: OutcomeWrite) -> dict[str, Any]:
        with self.engine.begin() as c:
            disposition, current = context_source(
                c, context, space, command.disposition_id, write=True
            )
            t = tables.product_matrix_outcomes
            signature = digest({"space": str(space), "body": command.model_dump(mode="json")})
            previous = (
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
            if previous is not None:
                if previous["request_digest"] != signature:
                    raise ProductWorkError("同一请求不能改写结果内容")
                return result_view(c, context, previous, current)
            version = c.execute(
                select(func.coalesce(func.max(t.c.version), 0)).where(
                    t.c.tenant_id == context.tenant.id, t.c.disposition_id == command.disposition_id
                )
            ).scalar_one()
            if (
                version != command.expected_version
                or command.expected_source_digest != current["digest"]
            ):
                raise ProductWorkError("原处置、来源或结果已有变化，请刷新核对")
            if not {str(v) for v in command.checked_product_ids}.issubset(
                disposition["product_ids"]
            ):
                raise ProductWorkError("核对范围必须属于原处置产品")
            selected = []
            for ref in command.versions:
                option = next(
                    (
                        v
                        for v in current["options"]
                        if v["ref_id"] == str(ref.ref_id)
                        and v["product_id"] == str(ref.product_id)
                        and v["kind"] == ref.kind
                    ),
                    None,
                )
                if option is None:
                    raise ProductWorkError("请选择当前可读的实际发布版本")
                selected.append(option)
            verification = _fact(c, context, command.verification)
            if command.state == "verified":
                w = current["work"]
                if w is not None:
                    if w["state"] != "completed" or (
                        w["acceptance_required"] and w["accepted_at"] is None
                    ):
                        raise ProductWorkError("跟进工作尚未完成原接收流程，不能确认落实")
                    if not w["evidence"]:
                        raise ProductWorkError("原工作缺少实际输出证据，不能确认落实")
                    _sources(c, context, tuple(SourceRef.model_validate(v) for v in w["evidence"]))
                if current["work_warnings"] or evidence_quality(
                    c, context, verification["sources"]
                ):
                    raise ProductWorkError("实际证据存在失效/变化提示，请先回原记录核对")
                if any(v["warnings"] for v in selected):
                    raise ProductWorkError("选中发布版本的依据待重核，请先回原业务处理")
                required = {"revise_definition": "definition", "revise_roadmap": "roadmap"}.get(
                    disposition["outcome"]
                )
                if required and any(
                    not any(
                        v["product_id"] == str(identity)
                        and v["kind"] == required
                        and v["later_than_disposition"]
                        and not v["warnings"]
                        for v in selected
                    )
                    for identity in command.checked_product_ids
                ):
                    raise ProductWorkError("每个核对产品须关联处置后发布且依据有效的对应修订版本")
            identity = uuid4()
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        tenant_id=context.tenant.id,
                        market_space_id=space,
                        disposition_id=command.disposition_id,
                        version=version + 1,
                        state=command.state,
                        checked_product_ids=[str(v) for v in command.checked_product_ids],
                        reason=command.reason,
                        verification=verification,
                        source_snapshot={**current, "selected_versions": selected},
                        source_digest=current["digest"],
                        actor_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=signature,
                        created_at=c.execute(select(func.clock_timestamp())).scalar_one(),
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            for chosen in selected:
                c.execute(
                    tables.product_matrix_outcome_versions.insert().values(
                        tenant_id=context.tenant.id,
                        market_space_id=space,
                        outcome_id=identity,
                        product_id=UUID(chosen["product_id"]),
                        kind=chosen["kind"],
                        definition_release_id=UUID(chosen["ref_id"])
                        if chosen["kind"] == "definition"
                        else None,
                        roadmap_revision_id=UUID(chosen["ref_id"])
                        if chosen["kind"] == "roadmap"
                        else None,
                        snapshot=chosen,
                    )
                )
            _emit(c, context, space, "product_matrix_outcome", "recorded", row)
            return result_view(c, context, row, current)
