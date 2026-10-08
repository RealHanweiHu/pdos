"""Private research candidates, adopted once through existing human domain services."""

from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from pydantic import Field
from sqlalchemy import func, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import SourceRef
from app.contracts.preproject_dialogue import Assessment
from app.db.schema import tables
from app.domain.product_workspace import (
    Input,
    MarketSpaceDraft,
    ProductWorkAccessError,
    ProductWorkError,
    ProductWorkspaceService,
    _role,
    _space,
    category_line_id,
)


class Confirm(Input):
    candidate_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: bool
    confirmed_shared: bool = False


def authorize_goal(c, ctx: AuthContext, conversation: Any, goal: str) -> None:
    if conversation["visibility"] != "private" or conversation["created_by_user_id"] != ctx.user.id:
        raise ProductWorkAccessError("品类和提案只能从本人私人会话发起")
    if goal == "category" and conversation["scope_kind"] == "personal":
        _role(ctx, Action.PRODUCT_WORK_MANAGE)
    elif goal == "proposal" and conversation["scope_kind"] in {"market_space", "product_line"}:
        _role(ctx, Action.PRODUCT_WORK_CONTRIBUTE)
        _space(c, ctx, conversation["market_space_id"], access="contributor")
    else:
        raise ProductWorkError("新建品类从品类目录开始，立项提案从当前品类开始")


def dialogue_context(engine, ctx, conversation, message) -> dict:
    with engine.connect() as c:
        authorize_goal(c, ctx, conversation, message["preproject_goal"])
        category = None
        if message["preproject_goal"] == "proposal":
            from app.domain.product_categories import category_bundle

            line = category_line_id(c, ctx.tenant.id, conversation["market_space_id"])
            category = category_bundle(
                c, ctx, conversation["market_space_id"], line, include_proposals=False
            )
        previous = (
            c.execute(
                select(tables.conversation_messages.c.id, tables.conversation_messages.c.body)
                .where(
                    tables.conversation_messages.c.tenant_id == ctx.tenant.id,
                    tables.conversation_messages.c.conversation_id == conversation["id"],
                    tables.conversation_messages.c.sequence <= message["sequence"],
                    tables.conversation_messages.c.preproject_goal == message["preproject_goal"],
                )
                .order_by(tables.conversation_messages.c.sequence.desc())
                .limit(8)
            )
            .mappings()
            .all()
        )
        # Carry the last typed questions forward so short answers remain intelligible.
        from app.ai.conversation_reply import identity

        prior = c.execute(
            select(tables.agent_runs.c.run_context)
            .where(
                tables.agent_runs.c.tenant_id == ctx.tenant.id,
                tables.agent_runs.c.id.in_(
                    [identity(p["id"]) for p in previous if p["id"] != message["id"]]
                ),
                tables.agent_runs.c.status == "succeeded",
            )
            .order_by(tables.agent_runs.c.completed_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    return {
        "goal": message["preproject_goal"],
        "category": category,
        "user_brief": "\n\n".join(p["body"] for p in reversed(previous))[:16000],
        "previous_assessment": prior.get("reply_result", {}).get("preproject") if prior else None,
    }


def validate_assessment(assessment: Assessment | None, snapshot: dict) -> Assessment:
    if assessment is None or assessment.goal != snapshot["preproject"]["goal"]:
        raise ProductWorkError("模型候选未匹配本次品类或提案入口")
    if assessment.stage == "clarify":
        return assessment
    refs = {r["reference_id"] for r in snapshot.get("research_receipt", {}).get("references", [])}
    if assessment.category:
        if not snapshot.get("research_receipt"):
            raise ProductWorkError("品类候选需有本轮自动研究回执，失败或未知也须如实记录")
        if any(set(n.citation_ids) - refs for n in assessment.category.notes):
            raise ProductWorkError("共用研究只能引用本轮已读取的公开原文")
    if assessment.proposal:
        doc = assessment.proposal.document
        category = snapshot["preproject"]["category"]
        allowed = (
            refs
            | {"brief", f"category:{category['category_line_id']}"}
            | {f"parameter:{p['parameter_id']}:{p['version']}" for p in category["parameters"]}
        )
        for item in [
            *doc.specifications,
            *doc.options,
            *doc.differences,
            *doc.competitors,
            *doc.user_voices,
        ]:
            if set(item.source_ids) - allowed:
                raise ProductWorkError("提案候选包含本轮不可读的来源")
        if any(s.state == "confirmed" for s in doc.specifications):
            raise ProductWorkError("AI不能替用户确认规格")
        evidence = {
            r["reference_id"]: r["excerpt"]
            for r in snapshot.get("research_receipt", {}).get("references", [])
        }
        evidence["brief"] = snapshot["preproject"]["user_brief"]
        if any(
            not any(v.quote in evidence.get(cid, "") for cid in v.source_ids)
            for v in doc.user_voices
        ):
            raise ProductWorkError("用户声音必须来自引用原文")
    return assessment


class ConnectionEngine:
    """Keep existing domain operations inside the caller's one transaction."""

    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def begin(self):
        yield self.connection

    @contextmanager
    def connect(self):
        yield self.connection


def applied(row) -> dict:
    params = f"category={row['category_id']}"
    if row["proposal_id"]:
        params += f"&tab=proposals&proposal={row['proposal_id']}"
    return {
        "category_id": str(row["category_id"]),
        "proposal_id": str(row["proposal_id"]) if row["proposal_id"] else None,
        "href": "/product-work?" + params,
    }


def confirm(
    engine, ctx: AuthContext, conversation_id: UUID, message_id: UUID, request: Confirm
) -> dict:
    from app.ai.conversation_reply import authorize, current, identity
    from app.contracts.product_proposals import ProposalCreate
    from app.domain.conversations import ConversationService
    from app.domain.product_categories import KnowledgeSave, ParameterSave, ProductCategoryService
    from app.domain.product_proposals import ProductProposalService

    if not request.confirmed:
        raise ProductWorkError("请确认当前候选后再保存")
    conversation, message = authorize(engine, ctx, conversation_id, message_id)
    with engine.begin() as c:
        conversation = ConversationService(engine)._conversation(c, ctx, conversation_id, lock=True)
        authorize_goal(c, ctx, conversation, message["preproject_goal"])
        t = tables.preproject_confirmations
        old = (
            c.execute(select(t).where(t.c.tenant_id == ctx.tenant.id, t.c.message_id == message_id))
            .mappings()
            .one_or_none()
        )
        if old:
            if (
                old["candidate_digest"] != request.candidate_digest
                or old["actor_user_id"] != ctx.user.id
            ):
                raise ProductWorkError("同一确认不能改用另一个候选")
            return applied(old)
        if (
            c.execute(
                select(func.max(tables.conversation_messages.c.sequence)).where(
                    tables.conversation_messages.c.tenant_id == ctx.tenant.id,
                    tables.conversation_messages.c.conversation_id == conversation_id,
                )
            ).scalar_one()
            != message["sequence"]
        ):
            raise ProductWorkError("已有新的对话，请采用最新候选")
        run = (
            c.execute(
                select(tables.agent_runs).where(
                    tables.agent_runs.c.tenant_id == ctx.tenant.id,
                    tables.agent_runs.c.id == identity(message_id),
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            run is None
            or run["status"] != "succeeded"
            or run["requested_by_user_id"] != ctx.user.id
            or run["completed_at"] is None
        ):
            raise ProductWorkError("研究候选未完成或不可用，请查询原请求或继续对话")
        result = run["run_context"].get("reply_result", {}).get("preproject", {})
        if result.get("candidate_digest") != request.candidate_digest:
            raise ProductWorkError("当前确认与原候选不一致")
        candidate = Assessment.model_validate(
            {k: v for k, v in result.items() if k != "candidate_digest"}
        )
        if candidate.stage != "ready":
            raise ProductWorkError("请先回答本轮关键问题")
        snapshot = {
            **run["run_context"]["reply_source"],
            **(
                {"research_receipt": run["run_context"]["reply_research"]}
                if run["run_context"].get("reply_research")
                else {}
            ),
        }
        if conversation["market_space_id"]:
            _space(c, ctx, conversation["market_space_id"], access="contributor", lock=True)
        refs = snapshot.get("research_receipt", {}).get("references", [])
        pins = snapshot.get("research_receipt", {}).get("pins", [])
        if pins:
            c.execute(
                select(tables.evidence_snapshots)
                .where(
                    tables.evidence_snapshots.c.tenant_id == ctx.tenant.id,
                    tables.evidence_snapshots.c.id.in_([UUID(p["id"]) for p in pins]),
                )
                .with_for_update()
            ).all()
            c.execute(
                select(tables.research_sources)
                .where(
                    tables.research_sources.c.tenant_id == ctx.tenant.id,
                    tables.research_sources.c.id.in_(
                        [UUID(p["source_id"]) for p in pins if p["source_id"]]
                    ),
                )
                .with_for_update()
            ).all()
        if not current(engine, ctx, snapshot):
            raise ProductWorkError("资料或权限已变化，请继续对话重新核对")
        validate_assessment(candidate, snapshot)
        bound = ConnectionEngine(c)
        source_refs = {
            f"snapshot:{p['id']}": SourceRef(
                tenant_id=ctx.tenant.id,
                kind="evidence_snapshot",
                ref_id=UUID(p["id"]),
                as_of=datetime.fromisoformat(p["captured_at"]),
                digest=p["content_digest"],
                locator=p["url"],
            )
            for p in pins
        }
        public_data = {}
        proposal_id = None
        if candidate.category:
            if not request.confirmed_shared:
                raise ProductWorkError("请具名确认品类候选可共享且不含客户专属资料")
            draft = candidate.category
            category = ProductWorkspaceService(bound).create_space(
                ctx,
                MarketSpaceDraft(
                    request_id=uuid5(run["id"], "category"),
                    **draft.model_dump(exclude={"parameters", "notes"}),
                ),
            )
            category_id = UUID(category["id"])
            line_id = category_line_id(c, ctx.tenant.id, category_id)
            service = ProductCategoryService(bound)
            for param in draft.parameters:
                service.parameter(
                    ctx,
                    category_id,
                    line_id,
                    ParameterSave(
                        request_id=uuid5(run["id"], "parameter:" + param.key),
                        reason="小Pai研究候选，经具名采用；专业条件与判据待专家复核",
                        **param.model_dump(),
                    ),
                )
            for index, note in enumerate(draft.notes):
                if note.kind == "competitor":
                    continue
                service.knowledge(
                    ctx,
                    category_id,
                    line_id,
                    KnowledgeSave(
                        request_id=uuid5(run["id"], "knowledge:" + str(index)),
                        kind=note.kind,
                        title=note.title,
                        body=(
                            "AI研究候选 · 待复核\n"
                            if note.state == "ai_draft"
                            else "未知 · 待补充依据\n"
                        )
                        + note.body,
                        source_refs=[source_refs[i] for i in note.citation_ids],
                        confirmed_anonymized=True,
                        regions=draft.regions if note.kind == "regulation" else [],
                    ),
                )
            public_data = {
                "notes": [n.model_dump(mode="json") for n in draft.notes if n.kind == "competitor"],
                "citations": [{k: r[k] for k in ("reference_id", "label", "href")} for r in refs],
                "source_refs": [r.model_dump(mode="json") for r in source_refs.values()],
                "remaining_questions": draft.research_questions,
                "coverage": "有界公开搜索；研究候选不代表专业确认",
            }
        else:
            draft = candidate.proposal
            assert draft is not None
            category_id = conversation["market_space_id"]
            doc = draft.document.model_dump(mode="json")
            for key in ("specifications", "options", "differences", "competitors", "user_voices"):
                for item in doc[key]:
                    item["source_ids"] = [
                        i.replace("snapshot:", "evidence:", 1) if i.startswith("snapshot:") else i
                        for i in item["source_ids"]
                    ]
            from app.contracts.product_proposals import ProposalDocument

            proposal = ProductProposalService(bound).create(
                ctx,
                category_id,
                ProposalCreate(
                    request_id=uuid5(run["id"], "proposal"),
                    title=draft.title,
                    entry_kind=draft.entry_kind,
                    brief=snapshot["preproject"]["user_brief"],
                    evidence_ids=[UUID(p["id"]) for p in pins],
                ),
                prepared_document=ProposalDocument.model_validate(doc),
                ai_run_id=run["id"],
            )
            proposal_id = UUID(proposal["id"])
        row = (
            c.execute(
                t.insert()
                .values(
                    id=uuid5(run["id"], "confirmed"),
                    tenant_id=ctx.tenant.id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    run_id=run["id"],
                    actor_user_id=ctx.user.id,
                    goal=candidate.goal,
                    candidate_digest=request.candidate_digest,
                    category_id=category_id,
                    proposal_id=proposal_id,
                    public_data=public_data,
                )
                .returning(t)
            )
            .mappings()
            .one()
        )
        return applied(row)
