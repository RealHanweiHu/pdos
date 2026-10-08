"""A product line is a category. Shared facts never ingest private customer originals."""

from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, func, or_, select, text

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import SourceRef
from app.db.schema import tables
from app.domain.product_workspace import (
    Input,
    ProductWorkError,
    _line,
    _plain,
    _role,
    _space,
    category_line_id,
    digest,
)


class ParameterSave(Input):
    request_id: UUID
    parameter_id: UUID | None = None
    expected_version: int = Field(default=0, ge=0)
    key: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]{0,63}$")
    label: str = Field(min_length=1, max_length=128)
    unit: str = Field(min_length=1, max_length=64)
    conditions: str = Field(min_length=1, max_length=1024)
    direction: Literal["higher", "lower", "target", "neutral"]
    verification_method: str = Field(default="", max_length=2048)
    acceptance_criterion: str = Field(default="", max_length=2048)
    reason: str = Field(min_length=1, max_length=2048)


class KnowledgeSave(Input):
    request_id: UUID
    kind: Literal["scene", "voice", "regulation", "general_requirement"]
    title: str = Field(min_length=1, max_length=256)
    body: str = Field(min_length=1, max_length=8000)
    regions: list[str] = Field(default_factory=list, max_length=30)
    source_refs: list[SourceRef] = Field(default_factory=list, max_length=20)
    proposal_id: UUID | None = None
    expected_proposal_version: int | None = Field(default=None, ge=1)
    confirmed_anonymized: bool = False


class PlatformCreate(Input):
    request_id: UUID
    code: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{1,128}$")
    name: str = Field(min_length=1, max_length=256)
    description: str = Field(min_length=1, max_length=4096)


class PlatformLink(Input):
    request_id: UUID
    product_id: UUID
    platform_id: UUID
    expected_version: int = Field(default=0, ge=0)
    action: Literal["attach", "detach"]
    reason: str = Field(min_length=1, max_length=2048)


def category_access(
    c: Connection, ctx: AuthContext, space: UUID, line: UUID | None, *, write: bool = False
) -> None:
    _space(c, ctx, space, access="manager" if write else "viewer", lock=write)
    _line(c, ctx, space, line, access="manager" if write else "viewer", writable=write)
    if line is None:
        raise ProductWorkError("请先进入品类，汽车与自行车须分开建类")
    if write:
        _role(ctx, Action.PRODUCT_WORK_MANAGE)
        # Serialize revision allocation and one category's command replay.
        c.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"category:{ctx.tenant.id}:{line}"},
        )


def replay(c: Connection, table: Any, ctx: AuthContext, request: Any) -> Any:
    old = (
        c.execute(
            select(table).where(
                table.c.tenant_id == ctx.tenant.id, table.c.request_id == request.request_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if old and old["request_digest"] != digest(request.model_dump(mode="json")):
        raise ProductWorkError("同一请求编号不能用于不同内容")
    return old


def identity_values(ctx: AuthContext, request: Any) -> dict[str, Any]:
    return dict(
        id=uuid4(),
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        request_id=request.request_id,
        request_digest=digest(request.model_dump(mode="json")),
    )


def category_parameters(
    c: Connection, ctx: AuthContext, space: UUID, line: UUID
) -> list[dict[str, Any]]:
    t = tables.category_parameters
    rows = c.execute(
        select(t)
        .where(
            t.c.tenant_id == ctx.tenant.id,
            t.c.market_space_id == space,
            t.c.product_line_id == line,
        )
        .order_by(t.c.version.desc(), t.c.key)
    ).mappings()
    current: dict[UUID, Any] = {}
    for row in rows:
        current.setdefault(row["parameter_id"], row)
    return [_plain(row) for row in sorted(current.values(), key=lambda r: r["key"])]


def parameter_reference(
    c: Connection,
    ctx: AuthContext,
    space: UUID,
    line: UUID | None,
    parameter_id: UUID,
    version: int | None,
) -> Any:
    if line is None:
        _space(c, ctx, space)
        line = category_line_id(c, ctx.tenant.id, space)
    t = tables.category_parameters
    p = (
        c.execute(
            select(t).where(
                t.c.tenant_id == ctx.tenant.id,
                t.c.market_space_id == space,
                t.c.product_line_id == line,
                t.c.parameter_id == parameter_id,
                t.c.version == version,
            )
        )
        .mappings()
        .one_or_none()
    )
    if p is None:
        raise ProductWorkError("参数不属于当前品类，或字典版本不存在")
    return p


def validate_parameter(
    c: Connection,
    ctx: AuthContext,
    space: UUID,
    line: UUID | None,
    item: dict[str, Any],
    *,
    spec: bool = False,
) -> None:
    pid, version = item.get("parameter_id"), item.get("parameter_version")
    if not pid:
        if version is not None:
            raise ProductWorkError("参数版本必须带共用参数编号")
        return
    p = parameter_reference(c, ctx, space, line, UUID(str(pid)), version)
    key = item.get("item_key", item.get("key", item.get("id")))
    conditions = item.get("conditions")
    if isinstance(conditions, (list, tuple)):
        conditions = "\n".join(conditions)
    if key != p["key"] or item.get("unit") != p["unit"] or conditions != p["conditions"]:
        raise ProductWorkError("共用参数的键、单位与标准测试条件须引用同一字典版本；差异另列待决项")
    if spec and item.get("label", item.get("title")) != p["label"]:
        raise ProductWorkError("共用参数名称须保持字典定义")


def category_test_template(parameters: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "items": [
            dict(
                key=p["key"],
                title=p["label"],
                parameter_id=p["parameter_id"],
                parameter_version=p["version"],
                unit=p["unit"],
                conditions=p["conditions"],
                direction=p["direction"],
                method=p["verification_method"],
                acceptance_criteria=p["acceptance_criterion"],
                state="ready"
                if p["verification_method"] and p["acceptance_criterion"]
                else "expert_pending",
            )
            for p in parameters
        ],
        "specifications_frozen": False,
    }


def category_bundle(
    c: Connection,
    ctx: AuthContext,
    space: UUID,
    line: UUID,
    regions: list[str] | None = None,
    *,
    include_proposals: bool = True,
) -> dict[str, Any]:
    category_access(c, ctx, space, line)
    category = _space(c, ctx, space)
    selected_regions = regions or category["regions"]
    p = category_parameters(c, ctx, space, line)
    k = tables.category_knowledge
    knowledge = [
        _plain(r)
        for r in c.execute(
            select(k)
            .where(
                k.c.tenant_id == ctx.tenant.id,
                k.c.market_space_id == space,
                k.c.product_line_id == line,
            )
            .order_by(k.c.created_at, k.c.id)
        ).mappings()
    ]
    knowledge = [
        r
        for r in knowledge
        if r["kind"] != "regulation"
        or not r["regions"]
        or bool(set(r["regions"]) & set(selected_regions))
    ]
    from app.domain.product_evidence import evidence_quality

    knowledge = [r for r in knowledge if not evidence_quality(c, ctx, r["source_refs"])]
    # Old unbound shared records belong to the same category; customer originals stay private.
    from app.domain.competitors import _all_refs
    from app.domain.product_evidence import evidence_quality

    competitors = []
    t = tables.competitor_observations
    rows = (
        c.execute(
            select(t).where(
                t.c.tenant_id == ctx.tenant.id,
                t.c.market_space_id == space,
                or_(t.c.product_line_id == line, t.c.product_line_id.is_(None)),
            )
        )
        .mappings()
        .all()
    )
    superseded = {r["supersedes_id"] for r in rows}
    for r in rows:
        if r["id"] not in superseded and not evidence_quality(c, ctx, _all_refs(r)):
            competitors.append(_plain(r))
    segments = []
    t = tables.market_segments
    rows = (
        c.execute(
            select(t).where(
                t.c.tenant_id == ctx.tenant.id,
                t.c.market_space_id == space,
                or_(t.c.product_line_id == line, t.c.product_line_id.is_(None)),
            )
        )
        .mappings()
        .all()
    )
    superseded = {r["supersedes_id"] for r in rows}
    for r in rows:
        if r["id"] not in superseded:
            # FactStatement sources must remain current before model reuse.
            refs = [
                ref
                for key in (
                    "target_users",
                    "job_to_be_done",
                    "customer_problems",
                    "use_environments",
                    "buying_criteria",
                    "unmet_needs",
                )
                for ref in r[key].get("sources", [])
            ]
            if not evidence_quality(c, ctx, refs):
                segments.append(
                    {
                        key: _plain(r)[key]
                        for key in (
                            "id",
                            "version",
                            "title",
                            "target_users",
                            "job_to_be_done",
                            "customer_problems",
                            "use_environments",
                            "buying_criteria",
                            "unmet_needs",
                        )
                    }
                )
    # Public proposal definitions and released models share the same parameter identities.
    # Customer proposals/variants never participate in the category comparison.
    products = []
    t = tables.product_proposals
    for r in c.execute(
        select(t)
        .where(
            t.c.tenant_id == ctx.tenant.id,
            t.c.market_space_id == space,
            or_(t.c.product_line_id == line, t.c.product_line_id.is_(None)),
            t.c.entry_kind == "new_product",
            func.jsonb_array_length(t.c.source_file_ids) == 0,
            t.c.state != "declined",
        )
        .order_by(t.c.updated_at.desc())
        .limit(100)
    ).mappings():
        if not include_proposals:
            continue
        products.append(
            dict(
                id=str(r["id"]),
                name=r["title"],
                kind="proposal",
                specifications=r["document"].get("specifications", []),
            )
        )
    from app.domain.product_definitions import _release

    t = tables.product_nodes
    for node in c.execute(
        select(t).where(
            t.c.tenant_id == ctx.tenant.id,
            t.c.market_space_id == space,
            t.c.product_line_id == line,
            t.c.level == "model",
            t.c.lifecycle != "retired",
        )
    ).mappings():
        release = _release(c, ctx, node["id"])
        if release and release["action"] == "publish":
            d = (
                c.execute(
                    select(tables.product_definitions).where(
                        tables.product_definitions.c.tenant_id == ctx.tenant.id,
                        tables.product_definitions.c.id == release["definition_id"],
                    )
                )
                .mappings()
                .one()
            )
            products.append(
                dict(
                    id=str(node["id"]),
                    name=node["name"],
                    kind="model",
                    specifications=[
                        {
                            **item,
                            "value": item.get("target_value") or item.get("target_text") or "",
                            "conditions": "\n".join(item["conditions"]),
                        }
                        for item in d["content"]["items"]
                    ],
                )
            )
    result = dict(
        category_id=str(space),
        category_line_id=str(line),
        category_name=category["title"],
        user_groups=category["user_groups"],
        use_scenarios=category["use_scenarios"],
        research_questions=category["research_questions"],
        regions=selected_regions,
        parameters=p,
        knowledge=knowledge,
        competitors=competitors,
        products=products,
        segments=segments,
        test_template=category_test_template(p),
    )
    confirmations = tables.preproject_confirmations
    result["research_drafts"] = [
        _plain(r)
        for r in c.execute(
            select(
                confirmations.c.public_data,
                confirmations.c.actor_user_id,
                confirmations.c.run_id,
                confirmations.c.created_at,
            ).where(
                confirmations.c.tenant_id == ctx.tenant.id,
                confirmations.c.category_id == space,
                confirmations.c.goal == "category",
            )
        ).mappings()
        if not evidence_quality(c, ctx, r["public_data"].get("source_refs", []))
    ]
    result["digest"] = digest(result)
    return result


class ProductCategoryService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def read(self, ctx: AuthContext, space: UUID, line: UUID) -> dict[str, Any]:
        with self.engine.connect() as c:
            return category_bundle(c, ctx, space, line)

    def parameter(
        self, ctx: AuthContext, space: UUID, line: UUID, request: ParameterSave
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            category_access(c, ctx, space, line, write=True)
            t = tables.category_parameters
            old = replay(c, t, ctx, request)
            if old:
                if old["product_line_id"] != line:
                    raise ProductWorkError("请求属于另一个品类")
                return _plain(old)
            latest = next(
                (p for p in category_parameters(c, ctx, space, line) if p["key"] == request.key),
                None,
            )
            if latest:
                if (
                    str(request.parameter_id) != latest["parameter_id"]
                    or request.expected_version != latest["version"]
                ):
                    raise ProductWorkError("参数已有版本，请基于当前字典修订")
                parameter_id, version = UUID(latest["parameter_id"]), latest["version"] + 1
            else:
                if request.parameter_id or request.expected_version:
                    raise ProductWorkError("新参数从版本1开始，不能换键后冒用旧参数")
                if len(category_parameters(c, ctx, space, line)) >= 60:
                    raise ProductWorkError("单个品类最多60个共用参数")
                parameter_id, version = uuid4(), 1
            row = (
                c.execute(
                    t.insert()
                    .values(
                        **identity_values(ctx, request),
                        market_space_id=space,
                        product_line_id=line,
                        parameter_id=parameter_id,
                        version=version,
                        **request.model_dump(
                            exclude={"request_id", "parameter_id", "expected_version"}
                        ),
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            return _plain(row)

    def knowledge(
        self, ctx: AuthContext, space: UUID, line: UUID, request: KnowledgeSave
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            category_access(c, ctx, space, line, write=True)
            t = tables.category_knowledge
            proposal = None
            if request.proposal_id:
                from app.domain.product_proposals import proposal_row

                proposal = proposal_row(c, ctx, space, request.proposal_id, write=True)
                if (
                    proposal["product_line_id"] not in (None, line)
                    or proposal["owner_user_id"] != ctx.user.id
                ):
                    raise ProductWorkError("只能由客户提案负责人将本人材料去标识后确认沉淀到同品类")
                if (
                    proposal["version"] != request.expected_proposal_version
                    or not request.confirmed_anonymized
                ):
                    raise ProductWorkError("需核对当前提案版本并明确确认已经去掉客户身份和专属要求")
                if request.source_refs:
                    raise ProductWorkError("客户沉淀不能携带客户原件或原件链接")
            elif request.expected_proposal_version is not None:
                raise ProductWorkError("客户版本必须带提案编号")
            # Human confirmation is explicit; model routes cannot call this operation.
            if not request.confirmed_anonymized:
                raise ProductWorkError("发布到品类前需具名确认这是可共享、已去标识的资料")
            old = replay(c, t, ctx, request)
            if old:
                if old["product_line_id"] != line:
                    raise ProductWorkError("请求属于另一个品类")
                return _plain(old)
            from app.domain.product_evidence import resolve_evidence

            refs = (
                resolve_evidence(c, ctx, tuple(request.source_refs)) if request.source_refs else []
            )
            row = (
                c.execute(
                    t.insert()
                    .values(
                        **identity_values(ctx, request),
                        market_space_id=space,
                        product_line_id=line,
                        kind=request.kind,
                        title=request.title,
                        body=request.body,
                        regions=request.regions,
                        source_refs=refs,
                        origin="human_anonymized" if proposal else "human_shared",
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            if proposal:
                c.execute(
                    tables.category_promotion_proofs.insert().values(
                        id=uuid4(),
                        tenant_id=ctx.tenant.id,
                        knowledge_id=row["id"],
                        proposal_id=proposal["id"],
                        proposal_version=proposal["version"],
                        source_digest=digest(_plain(proposal)),
                        actor_user_id=ctx.user.id,
                    )
                )
            return _plain(row)

    def platforms(self, ctx: AuthContext, space: UUID) -> dict[str, Any]:
        from app.domain.product_catalog import ProductCatalogService

        catalog = ProductCatalogService(self.engine).catalog(ctx, space)
        visible = [UUID(p["id"]) for p in catalog["nodes"] if p["level"] == "model"]
        with self.engine.connect() as c:
            _space(c, ctx, space)
            items = [
                _plain(r)
                for r in c.execute(
                    select(tables.technical_platforms)
                    .where(tables.technical_platforms.c.tenant_id == ctx.tenant.id)
                    .order_by(tables.technical_platforms.c.code)
                ).mappings()
            ]
            t = tables.product_platform_links
            rows = c.execute(
                select(t)
                .where(t.c.tenant_id == ctx.tenant.id, t.c.product_id.in_(visible))
                .order_by(t.c.version.desc())
            ).mappings()
            links: dict[tuple[UUID, UUID], dict[str, Any]] = {}
            for r in rows:
                links.setdefault((r["product_id"], r["platform_id"]), _plain(r))
            return dict(items=items, links=list(links.values()))

    def platform(self, ctx: AuthContext, space: UUID, request: PlatformCreate) -> dict[str, Any]:
        with self.engine.begin() as c:
            _space(c, ctx, space, access="manager", lock=True)
            _role(ctx, Action.PRODUCT_WORK_MANAGE)
            t = tables.technical_platforms
            old = replay(c, t, ctx, request)
            if old:
                return _plain(old)
            if c.execute(
                select(t.c.id).where(t.c.tenant_id == ctx.tenant.id, t.c.code == request.code)
            ).first():
                raise ProductWorkError("技术平台编号已存在")
            return _plain(
                c.execute(
                    t.insert()
                    .values(
                        **identity_values(ctx, request),
                        **request.model_dump(exclude={"request_id"}),
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )

    def link(self, ctx: AuthContext, space: UUID, request: PlatformLink) -> dict[str, Any]:
        from app.domain.product_catalog import _node_row

        with self.engine.begin() as c:
            node = _node_row(c, ctx, space, request.product_id)
            category_access(c, ctx, space, node["product_line_id"], write=True)
            if node["level"] != "model" or node["lifecycle"] == "retired":
                raise ProductWorkError("技术平台关联到当前型号；客户变体沿型号复用，不公开客户资料")
            if not c.execute(
                select(tables.technical_platforms.c.id).where(
                    tables.technical_platforms.c.tenant_id == ctx.tenant.id,
                    tables.technical_platforms.c.id == request.platform_id,
                )
            ).first():
                raise ProductWorkError("平台不存在或不属于当前租户")
            t = tables.product_platform_links
            old = replay(c, t, ctx, request)
            if old:
                if old["market_space_id"] != space:
                    raise ProductWorkError("平台请求属于另一个空间")
                return _plain(old)
            latest = (
                c.execute(
                    select(t)
                    .where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.product_id == request.product_id,
                        t.c.platform_id == request.platform_id,
                    )
                    .order_by(t.c.version.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            version = latest["version"] if latest else 0
            if version != request.expected_version or (not latest and request.action == "detach"):
                raise ProductWorkError("平台关联已更新，请刷新后办理")
            return _plain(
                c.execute(
                    t.insert()
                    .values(
                        **identity_values(ctx, request),
                        market_space_id=space,
                        product_line_id=node["product_line_id"],
                        version=version + 1,
                        **request.model_dump(exclude={"request_id", "expected_version"}),
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
