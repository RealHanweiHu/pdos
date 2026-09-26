"""Explicit Decision relationships, authorized snapshots and named impact reviews."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, and_, func, or_, select, tuple_

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.conversations import ConversationError
from app.domain.decision_intake_state import reference_edges
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.knowledge_push import KnowledgeAccessError
from app.domain.product_workspace import _plain, digest

ReferenceKind = Literal[
    "follow_up", "initialization", "issue", "historical_issue", "ecr", "ecn", "memory"
]
KINDS = {
    "follow_up": ("决策原跟进任务", Action.WORK_ITEM_VIEW),
    "initialization": ("以决策为依据的初始化任务", Action.WORK_ITEM_VIEW),
    "issue": ("决策原问题关联", Action.WORK_ITEM_VIEW),
    "historical_issue": ("历史来源的实际问题关系", Action.WORK_ITEM_VIEW),
    "ecr": ("引用决策的变更批准", Action.CHANGE_VIEW),
    "ecn": ("引用决策的生效办理", Action.CHANGE_VIEW),
    "memory": ("由决策整理的知识", Action.MEMORY_VIEW),
}


class DecisionReferenceReview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: ReferenceKind
    id: UUID
    path_id: UUID
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    result: Literal["unaffected", "handled", "follow_up"]
    explanation: str = Field(min_length=1, max_length=4000)


def query_for(kind: str, tenant: UUID, project: UUID, decision: UUID) -> tuple[Any, Any]:
    d = tables.decisions
    scope = [d.c.tenant_id == tenant, d.c.project_id == project, d.c.id == decision]
    path: Any = d.c.id
    extra: list[Any] = []
    if kind == "follow_up":
        t = tables.tasks
        joined = d.join(t, t.c.id == d.c.follow_up_task_id)
        extra = [
            d.c.follow_up_state.label("relation_state"),
            d.c.follow_up_note.label("relation_note"),
        ]
    elif kind == "initialization":
        t, b = tables.tasks, tables.project_intake_work
        joined = d.join(
            b,
            (b.c.tenant_id == tenant)
            & (b.c.project_id == project)
            & (b.c.work_snapshot["source"]["kind"].astext == "decision")
            & (b.c.work_snapshot["source"]["id"].astext == str(decision)),
        ).join(t, t.c.id == b.c.task_id)
        path = b.c.id
        extra = [
            b.c.work_snapshot.label("relation_basis"),
            b.c.proposal_id.label("origin_proposal_id"),
        ]
    elif kind == "issue":
        t = tables.issues
        joined = d.join(t, t.c.id == d.c.issue_id)
    elif kind == "historical_issue":
        t, h = tables.issues, tables.decision_intake_corrections
        edges = reference_edges(tenant, project)
        joined = d.join(edges, edges.c.decision_id == d.c.id).join(t, t.c.id == edges.c.issue_id)
        path = edges.c.source_id
        # Any later relationship revision invalidates a review of this historical path.
        revision = (
            select(func.coalesce(func.max(h.c.revision), 0))
            .where(
                h.c.tenant_id == tenant,
                h.c.project_id == project,
                h.c.source_row_id == edges.c.source_id,
            )
            .correlate(edges)
            .scalar_subquery()
        )
        extra = [revision.label("source_revision")]
    elif kind in {"ecr", "ecn"}:
        t = (
            tables.engineering_change_requests
            if kind == "ecr"
            else tables.engineering_change_notices
        )
        fk = "approval_decision_id" if kind == "ecr" else "effectivity_decision_id"
        joined = d.join(t, t.c[fk] == d.c.id)
    elif kind == "memory":
        t, j = tables.memories, tables.knowledge_candidate_jobs
        joined = d.join(
            j,
            (j.c.tenant_id == tenant)
            & (j.c.project_id == project)
            & (j.c.source_kind == "decision")
            & (j.c.source_id == d.c.id),
        ).join(t, t.c.id == j.c.memory_id)
        path = j.c.id
        extra = [j.c.state.label("capture_state"), j.c.source_snapshot.label("captured_decision")]
    else:
        raise ConversationError("业务引用类型不存在")
    return select(t, path.label("path_id"), *extra).select_from(joined).where(
        *scope, t.c.tenant_id == tenant, t.c.project_id == project
    ), t


def view(kind: str, project: UUID, row: Any) -> dict[str, Any]:
    facts = {key: value for key, value in _plain(row).items() if key != "tenant_id"}
    base = f"/projects?project={project}"
    href = f"{base}&tab=work-items&entity_id={row['id']}"
    if kind in {"ecr", "ecn"}:
        href = f"{base}&tab=engineering#{kind}-{row['id']}"
    elif kind == "memory":
        href = "/knowledge"
    return {
        "kind": kind,
        "id": str(row["id"]),
        "path_id": str(row["path_id"]),
        "title": row["title"],
        "facts": facts,
        "digest": digest(facts),
        "href": href,
    }


def key(item: dict[str, Any]) -> tuple[str, str, str]:
    return str(item["kind"]), str(item["id"]), str(item["path_id"])


def resolve(
    c: Connection,
    ctx: AuthContext,
    project: UUID,
    decision: UUID,
    requested: list[dict[str, Any]],
    *,
    strict: bool = False,
) -> dict[tuple[str, str, str], dict[str, Any] | None]:
    result: dict[tuple[str, str, str], dict[str, Any] | None] = {}
    for kind in sorted({str(item["kind"]) for item in requested}):
        try:
            KnowledgeCorrectionService._authorize(
                c, ctx.tenant.id, ctx.user.id, project, KINDS[kind][1]
            )
        except KnowledgeAccessError:
            if strict:
                raise
            continue
        wanted = {key(item) for item in requested if item["kind"] == kind}
        query, table = query_for(kind, ctx.tenant.id, project, decision)
        if strict:
            c.execute(
                select(table.c.id)
                .where(
                    table.c.tenant_id == ctx.tenant.id,
                    table.c.project_id == project,
                    table.c.id.in_([UUID(value[1]) for value in wanted]),
                )
                .order_by(table.c.id)
                .with_for_update()
            ).all()
        q = query.subquery()
        records = c.execute(
            select(q).where(
                or_(
                    *[
                        and_(q.c.id == UUID(value[1]), q.c.path_id == UUID(value[2]))
                        for value in wanted
                    ]
                )
            )
        ).mappings()
        result.update({value: None for value in wanted})
        for row in records:
            item = view(kind, project, row)
            result[key(item)] = item
    return result


def freeze(
    c: Connection,
    ctx: AuthContext,
    project: UUID,
    decision: UUID,
    requested: list[DecisionReferenceReview],
) -> list[dict[str, Any]]:
    values = [item.model_dump(mode="json") for item in requested]
    actual = resolve(c, ctx, project, decision, values, strict=True)
    result = []
    for item in values:
        current = actual[key(item)]
        if current is None or current["digest"] != item["expected_digest"]:
            raise ConversationError("所选下游业务记录或关系已变化，请重新读取核对")
        result.append(item | {"snapshot": current})
    return result


class DecisionIntakeReferences:
    def __init__(self, engine: Engine):
        self.engine = engine

    def read(
        self,
        ctx: AuthContext,
        project: UUID,
        decision: UUID,
        kind: ReferenceKind,
        before_id: UUID | None = None,
        before_path_id: UUID | None = None,
    ) -> dict[str, Any]:
        if (before_id is None) != (before_path_id is None):
            raise ConversationError("引用分页位置不完整")
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            KnowledgeCorrectionService._authorize(
                c, ctx.tenant.id, ctx.user.id, project, Action.WORK_ITEM_VIEW
            )
            allowed = []
            for name, (label, action) in KINDS.items():
                try:
                    KnowledgeCorrectionService._authorize(
                        c, ctx.tenant.id, ctx.user.id, project, action
                    )
                except KnowledgeAccessError:
                    continue
                allowed.append({"kind": name, "label": label})
            if kind not in {item["kind"] for item in allowed}:
                raise KnowledgeAccessError("当前不可读取此类业务引用")
            query, _ = query_for(kind, ctx.tenant.id, project, decision)
            q = query.subquery()
            query = select(q)
            if before_id is not None:
                query = query.where(tuple_(q.c.id, q.c.path_id) < (before_id, before_path_id))
            records = list(
                c.execute(query.order_by(q.c.id.desc(), q.c.path_id.desc()).limit(21)).mappings()
            )
            return {
                "kinds": allowed,
                "items": [view(kind, project, row) for row in records[:20]],
                "next": {
                    "before_id": str(records[19]["id"]),
                    "before_path_id": str(records[19]["path_id"]),
                }
                if len(records) > 20
                else None,
            }
