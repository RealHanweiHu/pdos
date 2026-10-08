"""One living proposal before investment; source-bound, reversible draft editing."""

import json
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4, uuid5

from sqlalchemy import Connection, Engine, and_, func, or_, select

from app.auth.repository import AuthContext, AuthRepository
from app.auth.roles import Action, is_allowed
from app.contracts.product_proposals import (
    ProposalCompetitor,
    ProposalCreate,
    ProposalDecide,
    ProposalDifference,
    ProposalDocument,
    ProposalEdit,
    ProposalOption,
    ProposalSpec,
    ProposalSubmit,
    ProposalVoice,
)
from app.db.schema import tables
from app.domain.product_source_files import file_row
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    ProductWorkspaceService,
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


def active_actor(context: AuthContext, engine: Engine) -> AuthContext:
    current = AuthRepository(engine).find_user_context(context.user.id)
    if (
        current is None
        or current.tenant.id != context.tenant.id
        or (current.user.auth_version, current.user.role)
        != (context.user.auth_version, context.user.role)
    ):
        raise ProductWorkAccessError("当前身份已变化，请重新登录")
    return current


def proposal_row(
    c: Connection, ctx: AuthContext, space: UUID, identity: UUID, *, write: bool = False
) -> Any:
    _space(c, ctx, space, access="contributor" if write else "viewer", lock=write)
    t = tables.product_proposals
    query = select(t).where(
        t.c.tenant_id == ctx.tenant.id, t.c.market_space_id == space, t.c.id == identity
    )
    row = c.execute(query.with_for_update() if write else query).mappings().one_or_none()
    if row is None:
        raise ProductWorkAccessError("提案不存在或当前无权读取")
    if (row["entry_kind"] == "odm" or row["source_file_ids"]) and ctx.user.id not in {
        row["owner_user_id"],
        row["reviewer_user_id"],
    }:
        raise ProductWorkAccessError("客户提案仅负责人和本次具名评审人可读取")
    _line(
        c,
        ctx,
        space,
        row["product_line_id"],
        access="contributor" if write else "viewer",
        writable=write,
    )
    if write:
        _role(ctx, Action.PRODUCT_WORK_CONTRIBUTE)
    return row


def source_catalog(
    c: Connection, ctx: AuthContext, row: Any, *, model: bool = False
) -> list[dict[str, Any]]:
    """Models receive authorized original excerpts; shared views receive locators only."""
    sources: list[dict[str, Any]] = []
    if row["brief"]:
        sources.append(
            dict(
                id="brief",
                label="客户需求片段" if row["entry_kind"] == "odm" else "发起人说明",
                digest=digest(row["brief"]),
                locator="brief",
                text=row["brief"] if model else None,
            )
        )
    for identity in row["source_file_ids"]:
        if model:
            file = file_row(c, ctx, row["market_space_id"], UUID(identity))
        else:
            t = tables.product_source_files
            file = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.id == UUID(identity),
                        t.c.market_space_id == row["market_space_id"],
                        t.c.uploaded_by_user_id == row["owner_user_id"],
                    )
                )
                .mappings()
                .one_or_none()
            )
        if file is None or file["revoked_at"] or file["status"] != "extracted":
            raise ProductWorkError("提案原件已撤回或未解析，请核对原文件")
        if model and file["classification"] == "restricted":
            raise ProductWorkError("受限原件不能提供给模型，请先人工摘录允许使用的内容")
        if file["product_line_id"] not in (None, row["product_line_id"]):
            raise ProductWorkAccessError("原件与提案产品线不一致")
        for fragment in file["fragments"]:
            sources.append(
                dict(
                    id=f"file:{identity}:{fragment['ordinal']}",
                    label=file["filename"],
                    digest=file["sha256"],
                    locator=fragment["locator"],
                    version=file["version"],
                    text=fragment["text"] if model else None,
                )
            )
    if row["evidence_ids"]:
        found = ProductWorkspaceService(c.engine).evidence_options(
            ctx, row["market_space_id"], [UUID(i) for i in row["evidence_ids"]]
        )
        if {i["id"] for i in found} != set(row["evidence_ids"]):
            raise ProductWorkError("部分证据已停用或不能读取")
        for item in found:
            if item["is_stale"] or item["superseded"] or item["has_conflict"]:
                raise ProductWorkError("部分证据过期、已更新或存在冲突，请核对后引用")
            body = c.execute(
                select(tables.evidence_contents.c.body).where(
                    tables.evidence_contents.c.tenant_id == ctx.tenant.id,
                    tables.evidence_contents.c.content_digest == item["reference"]["digest"],
                )
            ).scalar_one_or_none()
            if not body:
                raise ProductWorkError("证据尚无可读原文")
            sources.append(
                dict(
                    id=f"evidence:{item['id']}",
                    label=item["name"],
                    digest=item["reference"]["digest"],
                    locator=item["url"],
                    text=body if model else None,
                )
            )
    if row["baseline_product_id"]:
        from app.domain.product_catalog import _node_row
        from app.domain.product_definitions import _release

        node = _node_row(c, ctx, row["market_space_id"], row["baseline_product_id"])
        _line(c, ctx, row["market_space_id"], node["product_line_id"])
        release = _release(c, ctx, node["id"])
        if release is None or release["action"] != "publish":
            raise ProductWorkError("派生参考产品尚无生效定义；请先提供可核对的基线资料")
        definition = (
            c.execute(
                select(tables.product_definitions).where(
                    tables.product_definitions.c.tenant_id == ctx.tenant.id,
                    tables.product_definitions.c.id == release["definition_id"],
                )
            )
            .mappings()
            .one()
        )
        sources.append(
            dict(
                id="baseline",
                label=node["name"],
                digest=digest(_plain(definition)),
                locator=str(release["id"]),
                text=str(_plain(definition)) if model else None,
            )
        )
    if row["product_line_id"]:
        from app.domain.product_categories import category_bundle

        bundle = category_bundle(
            c,
            ctx,
            row["market_space_id"],
            row["product_line_id"],
            row.get("target_regions") or [],
            include_proposals=False,
        )
        sources.append(
            dict(
                id=f"category:{row['product_line_id']}",
                label=f"品类共用研究 · {bundle['category_name']}",
                digest=bundle["digest"],
                locator=f"category/{row['product_line_id']}",
                text=json.dumps(bundle, ensure_ascii=False) if model else None,
            )
        )
        for p in row.get("category_context", {}).get("parameters", []):
            sources.append(
                dict(
                    id=f"parameter:{p['parameter_id']}:{p['version']}",
                    label=f"规格字典 · {p['label']}",
                    digest=digest(p),
                    locator=f"parameter/{p['parameter_id']}/v{p['version']}",
                    version=p["version"],
                    text=json.dumps(p, ensure_ascii=False) if model else None,
                )
            )
    if len(sources) > 150:
        raise ProductWorkError("资料超过本轮150段原文范围，请减少文件或证据")
    if model and sum(len(i.get("text") or "") for i in sources) > 120000:
        raise ProductWorkError("本轮原文超过12万字符，请提供更聚焦的需求文件")
    return sources


def validate_document(document: ProposalDocument, sources: list[dict[str, Any]]) -> None:
    ids = {s["id"] for s in sources}
    records: list[
        ProposalSpec | ProposalOption | ProposalDifference | ProposalCompetitor | ProposalVoice
    ] = [
        *document.specifications,
        *document.options,
        *document.differences,
        *document.competitors,
        *document.user_voices,
    ]
    for item in records:
        if set(item.source_ids) - ids:
            raise ProductWorkError("提案引用包含未授权或不存在的来源")
    for voice in document.user_voices:
        # Shared catalogs have no body; actual text is checked at model output time.
        if any(s.get("text") is not None for s in sources) and not any(
            voice.quote in (s.get("text") or "") for s in sources if s["id"] in voice.source_ids
        ):
            raise ProductWorkError("用户声音引文与所选原文不一致")
    for spec in document.specifications:
        if spec.state == "confirmed" and (not spec.value.strip() or not spec.source_ids):
            raise ProductWorkError("已确认规格需填写目标值并保留来源")


def serial(row: Any) -> dict[str, Any]:
    return {**_plain(row), "payload_digest": digest(_plain(row))}


def validate_proposal_parameters(
    c: Connection, ctx: AuthContext, row: Any, document: ProposalDocument
) -> None:
    from app.domain.product_categories import validate_parameter

    pins = {p["key"]: p for p in row.get("category_context", {}).get("parameters", [])}
    items = {p.id: p for p in document.specifications}
    for key, p in pins.items():
        item = items.get(key)
        if (
            item is None
            or str(item.parameter_id) != p["parameter_id"]
            or item.parameter_version != p["version"]
            or item.direction != p["direction"]
        ):
            raise ProductWorkError("品类规格骨架与字典版本须保留；不适用项请在取舍或待决问题中说明")
    for item in document.specifications:
        validate_parameter(
            c,
            ctx,
            row["market_space_id"],
            row["product_line_id"],
            item.model_dump(mode="json"),
            spec=True,
        )


def revision_sources(c: Connection, ctx: AuthContext, row: Any) -> list[dict[str, Any]]:
    r = tables.product_proposal_revisions
    value = c.execute(
        select(r.c.source_catalog)
        .where(r.c.tenant_id == ctx.tenant.id, r.c.proposal_id == row["id"])
        .order_by(r.c.version.desc())
        .limit(1)
    ).scalar_one()
    return cast(list[dict[str, Any]], value)


def sources_match(before: list[dict[str, Any]], current: list[dict[str, Any]]) -> bool:
    def normalized(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            [{k: v for k, v in item.items() if k != "text"} for item in items],
            key=lambda item: item["id"],
        )

    return normalized(before) == normalized(current)


def append_revision(
    c: Connection,
    ctx: AuthContext,
    row: Any,
    sources: list[dict[str, Any]],
    *,
    ai_run_id: UUID | None = None,
) -> None:
    c.execute(
        tables.product_proposal_revisions.insert().values(
            id=uuid4(),
            tenant_id=ctx.tenant.id,
            proposal_id=row["id"],
            version=row["version"],
            actor_user_id=ctx.user.id,
            ai_run_id=ai_run_id,
            origin="ai_assisted" if ai_run_id else "human",
            document=row["document"],
            source_catalog=[{k: v for k, v in item.items() if k != "text"} for item in sources],
            document_digest=digest(row["document"]),
        )
    )


class ProductProposalService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def list(self, ctx: AuthContext, space: UUID) -> dict[str, Any]:
        ctx = active_actor(ctx, self.engine)
        with self.engine.connect() as c:
            _space(c, ctx, space)
            t = tables.product_proposals
            rows = (
                c.execute(
                    select(t)
                    .where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.market_space_id == space,
                        _line_filter(t, ctx),
                        or_(
                            and_(
                                t.c.entry_kind != "odm",
                                func.jsonb_array_length(t.c.source_file_ids) == 0,
                            ),
                            t.c.owner_user_id == ctx.user.id,
                            t.c.reviewer_user_id == ctx.user.id,
                        ),
                    )
                    .order_by(t.c.updated_at.desc())
                    .limit(101)
                )
                .mappings()
                .all()
            )
        return {"items": [serial(row) for row in rows[:100]], "truncated": len(rows) > 100}

    def detail(self, ctx: AuthContext, space: UUID, identity: UUID) -> dict[str, Any]:
        ctx = active_actor(ctx, self.engine)
        with self.engine.connect() as c:
            row = proposal_row(c, ctx, space, identity)
            r, d = tables.product_proposal_revisions, tables.product_proposal_decisions
            revisions = c.execute(
                select(r)
                .where(r.c.tenant_id == ctx.tenant.id, r.c.proposal_id == identity)
                .order_by(r.c.version.desc())
                .limit(30)
            ).mappings()
            history = [_plain(i) for i in revisions]
            decisions = c.execute(
                select(d)
                .where(d.c.tenant_id == ctx.tenant.id, d.c.proposal_id == identity)
                .order_by(d.c.created_at.desc())
            ).mappings()
            try:
                catalog = source_catalog(c, ctx, row)
                source_error = None
                sources_changed = not sources_match(revision_sources(c, ctx, row), catalog)
            except (ProductWorkError, ProductWorkAccessError) as error:
                catalog = history[0]["source_catalog"] if history else []
                source_error = str(error)
                sources_changed = False
            value = serial(row)
            value.update(
                source_catalog=catalog,
                source_error=source_error,
                sources_changed=sources_changed,
                history=history,
                decisions=[_plain(i) for i in decisions],
                can_edit=row["owner_user_id"] == ctx.user.id
                and row["state"] in {"draft", "returned"}
                and is_allowed(ctx.user.role, Action.PRODUCT_WORK_CONTRIBUTE),
                can_decide=row["reviewer_user_id"] == ctx.user.id
                and row["state"] == "in_review"
                and is_allowed(ctx.user.role, Action.PRODUCT_WORK_MANAGE),
            )
            a = tables.agent_runs
            value["ai_history"] = [
                {
                    "run_id": str(i["id"]),
                    "status": i["status"],
                    "instruction": i["run_context"]["proposal_source"]["instruction"],
                    "source_version": i["run_context"]["proposal_source"]["proposal"]["version"],
                    "result": i["run_context"].get("proposal_result"),
                    "created_at": str(i["created_at"]),
                }
                for i in c.execute(
                    select(a)
                    .where(
                        a.c.tenant_id == ctx.tenant.id,
                        a.c.requested_by_user_id == ctx.user.id,
                        a.c.context_version == "product-proposal-v1",
                        a.c.run_context["proposal_source"]["proposal"]["id"].as_string()
                        == str(identity),
                    )
                    .order_by(a.c.created_at.desc())
                    .limit(5)
                ).mappings()
            ]
            return value

    def create(
        self,
        ctx: AuthContext,
        space: UUID,
        request: ProposalCreate,
        *,
        prepared_document: ProposalDocument | None = None,
        ai_run_id: UUID | None = None,
    ) -> dict[str, Any]:
        ctx = active_actor(ctx, self.engine)
        _role(ctx, Action.PRODUCT_WORK_CONTRIBUTE)
        with self.engine.begin() as c:
            _space(c, ctx, space, access="contributor", lock=True)
            request = request.model_copy(
                update={
                    "product_line_id": request.product_line_id
                    or category_line_id(c, ctx.tenant.id, space)
                }
            )
            _line(c, ctx, space, request.product_line_id, access="contributor", writable=True)
            t = tables.product_proposals
            identity = uuid5(ctx.user.id, f"proposal:{request.request_id}")
            old = (
                c.execute(select(t).where(t.c.tenant_id == ctx.tenant.id, t.c.id == identity))
                .mappings()
                .one_or_none()
            )
            fingerprint = digest(request.model_dump(mode="json"))
            if old:
                if old["request_digest"] != fingerprint or old["market_space_id"] != space:
                    raise ProductWorkError("此请求编号已用于不同提案")
                return serial(old)
            for identity_file in request.source_file_ids:
                file_row(c, ctx, space, identity_file)
            assert request.product_line_id is not None
            from app.domain.product_categories import category_bundle

            bundle = category_bundle(
                c,
                ctx,
                space,
                request.product_line_id,
                request.target_regions,
                include_proposals=False,
            )
            dictionary_specs = [
                ProposalSpec(
                    id=p["key"],
                    label=p["label"],
                    unit=p["unit"],
                    conditions=p["conditions"],
                    parameter_id=UUID(p["parameter_id"]),
                    parameter_version=p["version"],
                    direction=p["direction"],
                    source_ids=[f"parameter:{p['parameter_id']}:{p['version']}"],
                )
                for p in bundle["parameters"]
            ]
            document = ProposalDocument(
                narrative=request.brief,
                specifications=dictionary_specs
                or [
                    ProposalSpec(id=key, label=label)
                    for key, label in (
                        ("audience", "适用人群"),
                        ("use_path", "完整使用路径"),
                        ("selling_point", "主要卖点"),
                        ("performance", "关键性能"),
                        ("price", "目标价格带"),
                        ("market", "销售地区 / 认证"),
                    )
                ],
                questions=["哪些规格是立项依据，哪些留到项目规格冻结时确认？"],
            )
            if prepared_document:
                from app.ai.product_proposal import protect_confirmed

                document = protect_confirmed(document, prepared_document)
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        tenant_id=ctx.tenant.id,
                        market_space_id=space,
                        owner_user_id=ctx.user.id,
                        request_digest=fingerprint,
                        **request.model_dump(mode="json", exclude={"request_id"}),
                        request_id=request.request_id,
                        category_context=bundle,
                        document=document.model_dump(mode="json"),
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            sources = source_catalog(c, ctx, row)
            validate_document(document, sources)
            validate_proposal_parameters(c, ctx, row, document)
            append_revision(c, ctx, row, sources, ai_run_id=ai_run_id)
            _emit(c, ctx, space, "product_proposal", "created", row)
            return serial(row)

    def edit(
        self, ctx: AuthContext, space: UUID, identity: UUID, request: ProposalEdit
    ) -> dict[str, Any]:
        ctx = active_actor(ctx, self.engine)
        with self.engine.begin() as c:
            row = proposal_row(c, ctx, space, identity, write=True)
            if not _precondition(c, ctx, row, request):
                return serial(row)
            if row["owner_user_id"] != ctx.user.id or row["state"] not in {"draft", "returned"}:
                raise ProductWorkAccessError("仅提案负责人可编辑未提交的草稿")
            sources = source_catalog(c, ctx, row)
            validate_document(request.document, sources)
            validate_proposal_parameters(c, ctx, row, request.document)
            if request.ai_run_id:
                from app.ai.product_proposal import validate_application

                validate_application(c, ctx, row, request.ai_run_id)
            t = tables.product_proposals
            changed = (
                c.execute(
                    t.update()
                    .where(t.c.id == identity)
                    .values(
                        document=request.document.model_dump(mode="json"),
                        state="draft",
                        reviewer_user_id=None,
                        submitted_version=None,
                        version=row["version"] + 1,
                        updated_at=datetime.now(UTC),
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            append_revision(c, ctx, changed, sources, ai_run_id=request.ai_run_id)
            _emit(
                c, ctx, space, "product_proposal", "edited", changed, before=row, operation=request
            )
            return serial(changed)

    def submit(
        self, ctx: AuthContext, space: UUID, identity: UUID, request: ProposalSubmit
    ) -> dict[str, Any]:
        ctx = active_actor(ctx, self.engine)
        with self.engine.begin() as c:
            row = proposal_row(c, ctx, space, identity, write=True)
            if not _precondition(c, ctx, row, request):
                return serial(row)
            if row["owner_user_id"] != ctx.user.id or row["state"] not in {"draft", "returned"}:
                raise ProductWorkAccessError("仅提案负责人可提交草稿立项评审")
            _member(c, ctx, space, request.reviewer_user_id, row["product_line_id"])
            reviewer = AuthRepository(self.engine).find_user_context(request.reviewer_user_id)
            if reviewer is None or not is_allowed(reviewer.user.role, Action.PRODUCT_WORK_MANAGE):
                raise ProductWorkError("请选择有产品管理权限的具名评审人")
            sources = source_catalog(c, ctx, row)
            document = ProposalDocument.model_validate(row["document"])
            if not sources_match(revision_sources(c, ctx, row), sources):
                raise ProductWorkError("资料版本已变化，请核对后保存草稿，再提交评审")
            validate_document(document, sources)
            validate_proposal_parameters(c, ctx, row, document)
            if not document.narrative.strip():
                raise ProductWorkError("请先填写提案叙述")
            changed = (
                c.execute(
                    tables.product_proposals.update()
                    .where(tables.product_proposals.c.id == identity)
                    .values(
                        state="in_review",
                        reviewer_user_id=request.reviewer_user_id,
                        submitted_version=row["version"],
                        version=row["version"] + 1,
                        updated_at=datetime.now(UTC),
                    )
                    .returning(tables.product_proposals)
                )
                .mappings()
                .one()
            )
            _emit(
                c,
                ctx,
                space,
                "product_proposal",
                "submitted",
                changed,
                before=row,
                operation=request,
            )
            return serial(changed)

    def decide(
        self, ctx: AuthContext, space: UUID, identity: UUID, request: ProposalDecide
    ) -> dict[str, Any]:
        ctx = active_actor(ctx, self.engine)
        _role(ctx, Action.PRODUCT_WORK_MANAGE)
        with self.engine.begin() as c:
            row = proposal_row(c, ctx, space, identity, write=True)
            if not _precondition(c, ctx, row, request):
                return serial(row)
            if row["state"] != "in_review" or row["reviewer_user_id"] != ctx.user.id:
                raise ProductWorkAccessError("仅本次具名评审人可办理立项决定")
            catalog = revision_sources(c, ctx, row)
            if request.outcome == "approved":
                current_catalog = source_catalog(c, ctx, row)
                if not sources_match(catalog, current_catalog):
                    raise ProductWorkError("评审中的原件或基线已变化，请退回核对后重新提交")
            document = ProposalDocument.model_validate(row["document"])
            if request.selected_option and request.selected_option not in {
                i.key for i in document.options
            }:
                raise ProductWorkError("所选方案不属于本次提案")
            if request.outcome == "approved" and document.options and not request.selected_option:
                raise ProductWorkError("请明确本次批准的定位方案")
            unknown = bool(
                document.questions
                or document.risks
                or any(s.state != "confirmed" for s in document.specifications)
            )
            if request.outcome == "approved" and unknown and not request.accepted_unknowns.strip():
                raise ProductWorkError("请具名记录未决问题和风险如何带入项目处理")
            snapshot = {
                "proposal": serial(row),
                "source_catalog": catalog,
                "specifications_frozen": False,
            }
            c.execute(
                tables.product_proposal_decisions.insert().values(
                    id=uuid4(),
                    tenant_id=ctx.tenant.id,
                    proposal_id=identity,
                    proposal_version=row["submitted_version"],
                    actor_user_id=ctx.user.id,
                    outcome=request.outcome,
                    selected_option=request.selected_option,
                    rationale=request.rationale,
                    accepted_unknowns=request.accepted_unknowns,
                    snapshot=snapshot,
                    snapshot_digest=digest(snapshot),
                )
            )
            changed = (
                c.execute(
                    tables.product_proposals.update()
                    .where(tables.product_proposals.c.id == identity)
                    .values(
                        state=request.outcome,
                        version=row["version"] + 1,
                        updated_at=datetime.now(UTC),
                    )
                    .returning(tables.product_proposals)
                )
                .mappings()
                .one()
            )
            _emit(
                c, ctx, space, "product_proposal", "decided", changed, before=row, operation=request
            )
            return serial(changed)
