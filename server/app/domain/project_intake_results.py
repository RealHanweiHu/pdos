"""Versioned execution evidence for actual initialization and historical repair Tasks."""

from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.conversations import ConversationError
from app.domain.decision_intake_references import DecisionReferenceReview, freeze, key, resolve
from app.domain.issue_intake_compensation_results import ResultEvidence, current_evidence
from app.domain.issue_intake_compensations import task_view
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.product_workspace import _plain, digest
from app.domain.project_intake import Observation, authorize, record_event, source_read
from app.domain.project_intake_work import business_snapshot
from app.domain.project_write_lock import lock_project_write_scope


class InitializationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_revision: int = Field(ge=0)
    expected_context_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: Literal["progress", "addressed", "no_change_needed", "follow_up"]
    summary: str = Field(min_length=1, max_length=10000)
    criteria_response: str = Field(min_length=1, max_length=10000)
    remaining: str = Field(min_length=1, max_length=10000)
    evidence: list[ResultEvidence] = Field(default_factory=list, max_length=10)
    business_reviews: list[DecisionReferenceReview] = Field(default_factory=list, max_length=50)
    reviewed: Literal[True]

    @model_validator(mode="after")
    def evidence_complete(self) -> Self:
        if len({item.document_id for item in self.evidence}) != len(self.evidence):
            raise ValueError("同一证据文件请合并说明")
        if self.outcome in {"addressed", "no_change_needed"} and not self.evidence:
            raise ValueError("完成或无需修改的结论需要实际文件及对应依据")
        identities = [(item.kind, item.id, item.path_id) for item in self.business_reviews]
        if len(set(identities)) != len(identities):
            raise ValueError("同一业务引用路径请合并说明")
        if self.outcome in {"addressed", "no_change_needed"} and any(
            item.result == "follow_up" for item in self.business_reviews
        ):
            raise ValueError("所选业务仍有后续要求，请选择仍需后续处理")
        return self


def basis(
    c: Connection, ctx: AuthContext, project: UUID, identity: UUID, *, lock: bool = False
) -> dict[str, Any]:
    authorize(c, ctx, project, write=lock)
    b, p, t = tables.project_intake_work, tables.project_intake_proposals, tables.tasks
    query = select(b).where(
        b.c.tenant_id == ctx.tenant.id, b.c.project_id == project, b.c.id == identity
    )
    binding = c.execute(query.with_for_update() if lock else query).mappings().one_or_none()
    if binding is None:
        raise ConversationError("本项目没有此初始化任务安排")
    proposal = (
        c.execute(select(p).where(p.c.tenant_id == ctx.tenant.id, p.c.id == binding["proposal_id"]))
        .mappings()
        .one()
    )
    task_query = select(t).where(
        t.c.tenant_id == ctx.tenant.id, t.c.project_id == project, t.c.id == binding["task_id"]
    )
    task = c.execute(task_query.with_for_update() if lock else task_query).mappings().one()
    original_source = (
        proposal["draft"].get("work_context", {}).get(str(binding["work_key"]), {}).get("source")
    )
    ref = binding["work_snapshot"].get("source")
    live_source = None
    available = True
    if ref:
        table = {"issue": tables.issues, "risk": tables.risks, "decision": tables.decisions}[
            ref["kind"]
        ]
        query = select(table).where(
            table.c.tenant_id == ctx.tenant.id,
            table.c.project_id == project,
            table.c.id == UUID(ref["id"]),
        )
        row = c.execute(query.with_for_update() if lock else query).mappings().one_or_none()
        if row is None:
            available = False
        else:
            live_source = business_snapshot(row, ref["kind"], c)
    originals = []
    wanted = set(binding["work_snapshot"]["observation_keys"])
    for source in proposal["draft"]["observations"]:
        if source["key"] not in wanted:
            continue
        try:
            actual = source_read(c, ctx, project, Observation.model_validate(source))
            frozen = next(
                item for item in binding["source_snapshot"] if item["key"] == source["key"]
            )
            originals.append(
                {"key": source["key"], "current": actual == frozen, "snapshot": actual}
            )
        except ConversationError:
            originals.append({"key": source["key"], "current": False, "snapshot": None})
    context = {
        "binding_id": str(identity),
        "task": task_view(task),
        "business_source": live_source,
        "source_available": available,
        "original_sources": originals,
    }
    r = tables.project_intake_work_results
    revision = c.execute(
        select(func.coalesce(func.max(r.c.revision), 0)).where(
            r.c.tenant_id == ctx.tenant.id, r.c.binding_id == identity
        )
    ).scalar_one()
    return {
        "binding": _plain(binding),
        "original_business_source": original_source,
        "business_source_changed": original_source != live_source,
        "context": context,
        "context_digest": digest(context),
        "result_revision": revision,
    }


def view_result(
    c: Connection, ctx: AuthContext, project: UUID, row: Any, current: dict[str, Any]
) -> dict[str, Any]:
    evidence = current_evidence(c, ctx.tenant.id, project, row["evidence_snapshot"])
    reasons = []
    if row["context_snapshot"] != current["context"]:
        reasons.append("任务、业务来源或原文核对状态已有变化")
    if any(item["changed"] for item in evidence):
        reasons.append("办理证据已变化或不可用")
    if not current["context"]["source_available"] or any(
        not item["current"] for item in current["context"]["original_sources"]
    ):
        reasons.append("原业务或选段依据当前不可完整核对")
    saved_reviews = row["business_reviews"]
    ref = current["binding"]["work_snapshot"].get("source")
    actual = (
        resolve(c, ctx, project, UUID(ref["id"]), saved_reviews)
        if saved_reviews and ref and ref["kind"] == "decision"
        else {}
    )
    visible = []
    for item in saved_reviews:
        if key(item) not in actual:
            continue
        value = actual[key(item)]
        visible.append(
            item
            | {
                "current": value,
                "changed": value is None or value["digest"] != item["expected_digest"],
            }
        )
    if len(visible) != len(saved_reviews):
        reasons.append("当前权限不足以核对全部已选业务引用")
    if any(item["changed"] for item in visible):
        reasons.append("所选下游业务或引用关系已变化")
    return _plain(row) | {
        "business_reviews": visible,
        "evidence": evidence,
        "current": not reasons,
        "recheck_reasons": reasons,
    }


class ProjectIntakeResults:
    def __init__(self, engine: Engine):
        self.engine = engine

    def read(
        self, ctx: AuthContext, project: UUID, identity: UUID, before_revision: int | None = None
    ) -> dict[str, Any]:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            current = basis(c, ctx, project, identity)
            KnowledgeCorrectionService._authorize(
                c, ctx.tenant.id, ctx.user.id, project, Action.DOCUMENT_ANALYZE
            )
            r, u = tables.project_intake_work_results, tables.users
            query = (
                select(r, u.c.display_name.label("actor_name"))
                .join(u, (u.c.tenant_id == r.c.tenant_id) & (u.c.id == r.c.created_by_user_id))
                .where(r.c.tenant_id == ctx.tenant.id, r.c.binding_id == identity)
            )
            if before_revision is not None:
                query = query.where(r.c.revision < before_revision)
            rows = list(c.execute(query.order_by(r.c.revision.desc()).limit(21)).mappings())
            return current | {
                "items": [view_result(c, ctx, project, row, current) for row in rows[:20]],
                "next_revision": rows[19]["revision"] if len(rows) > 20 else None,
            }

    def save(
        self, ctx: AuthContext, project: UUID, identity: UUID, body: InitializationResult
    ) -> dict[str, Any]:
        signature = digest(body.model_dump(mode="json", exclude={"request_id"}))
        with self.engine.begin() as c:
            authorize(c, ctx, project, write=True)
            KnowledgeCorrectionService._authorize(
                c, ctx.tenant.id, ctx.user.id, project, Action.DOCUMENT_ANALYZE
            )
            if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
                raise ConversationError("项目暂不可办理")
            r = tables.project_intake_work_results
            previous = (
                c.execute(
                    select(r).where(
                        r.c.tenant_id == ctx.tenant.id,
                        r.c.project_id == project,
                        r.c.binding_id == identity,
                        r.c.request_id == body.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if previous is not None:
                if previous["request_digest"] != signature:
                    raise ConversationError("此请求已登记其他结果，请读取原回执")
                return view_result(c, ctx, project, previous, basis(c, ctx, project, identity))
            current = basis(c, ctx, project, identity, lock=True)
            if (
                current["result_revision"] != body.expected_revision
                or current["context_digest"] != body.expected_context_digest
            ):
                raise ConversationError("任务、来源或前次结果已变化，请刷新核对后继续")
            context = current["context"]
            refs = current_evidence(
                c, ctx.tenant.id, project, [item.model_dump(mode="json") for item in body.evidence]
            )
            if any(item["changed"] for item in refs):
                raise ConversationError("所选证据文件已变化，请重新读取核对")
            if body.outcome in {"addressed", "no_change_needed"}:
                if not context["source_available"] or any(
                    not item["current"] for item in context["original_sources"]
                ):
                    raise ConversationError("来源不完整时只能记录进展或后续要求")
                if not context["task"].get("expected_output"):
                    raise ConversationError("请先在实际任务补齐交付要求")
                allowed = {"done"} if body.outcome == "addressed" else {"done", "skipped"}
                if context["task"]["status"] not in allowed:
                    raise ConversationError(
                        "请先按实际任务流程完成办理，再登记完成或无需修改的核对结果"
                    )
            ref = current["binding"]["work_snapshot"].get("source")
            if body.business_reviews and (not ref or ref["kind"] != "decision"):
                raise ConversationError("本任务没有对应的决策业务来源")
            business_reviews = (
                freeze(c, ctx, project, UUID(ref["id"]), body.business_reviews)
                if body.business_reviews
                else []
            )
            result = (
                c.execute(
                    r.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=ctx.tenant.id,
                        project_id=project,
                        binding_id=identity,
                        revision=body.expected_revision + 1,
                        request_id=body.request_id,
                        request_digest=signature,
                        outcome=body.outcome,
                        summary=body.summary,
                        criteria_response=body.criteria_response,
                        remaining=body.remaining,
                        context_snapshot=context,
                        evidence_snapshot=refs,
                        business_reviews=business_reviews,
                        created_by_user_id=ctx.user.id,
                    )
                    .returning(r)
                )
                .mappings()
                .one()
            )
            record_event(
                c,
                ctx,
                project,
                UUID(current["binding"]["proposal_id"]),
                result["id"],
                "work_result",
            )
            return view_result(c, ctx, project, result, current)
