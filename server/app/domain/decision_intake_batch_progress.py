"""Current execution and evidence across an actual historical Decision import batch."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, String, and_, cast, func, select, tuple_, union

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.conversations import ConversationError
from app.domain.decision_intake_state import source_states
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.product_workspace import digest
from app.domain.project_intake import authorize
from app.domain.project_intake_results import basis, view_result

ZERO = UUID(int=0)


def scope_query(tenant: UUID, project: UUID, identities: list[UUID]) -> Any:
    r, h = tables.decision_intake_rows, tables.decision_intake_corrections
    initial = select(r.c.id.label("source_id"), r.c.decision_id).where(
        r.c.tenant_id == tenant, r.c.project_id == project, r.c.id.in_(identities)
    )
    history = []
    for key in ("previous_decision_id", "target_decision_id"):
        history.append(
            select(h.c.source_row_id.label("source_id"), h.c[key].label("decision_id")).where(
                h.c.tenant_id == tenant,
                h.c.project_id == project,
                h.c.source_row_id.in_(identities),
                h.c[key].is_not(None),
            )
        )
    return union(initial, *history).subquery("batch_decision_scope")


def work_state(
    c: Connection, ctx: AuthContext, project: UUID, binding: UUID, latest: Any
) -> dict[str, Any]:
    current = basis(c, ctx, project, binding)
    if latest is None:
        return {"status": "result_missing", "result": None, "basis": current}
    result = view_result(c, ctx, project, latest, current)
    status = (
        "recheck"
        if not result["current"]
        else "follow_up"
        if result["outcome"] in {"progress", "follow_up"}
        else "recorded"
    )
    return {"status": status, "result": result, "basis": current}


class DecisionIntakeBatchProgress:
    def __init__(self, engine: Engine):
        self.engine = engine

    def batches(
        self, ctx: AuthContext, project: UUID, source: UUID, before_id: UUID | None = None
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            authorize(c, ctx, project)
            r, b = tables.decision_intake_rows, tables.decision_intake_batches
            exists = c.execute(
                select(r.c.id).where(
                    r.c.tenant_id == ctx.tenant.id, r.c.project_id == project, r.c.id == source
                )
            ).scalar_one_or_none()
            if exists is None:
                raise ConversationError("此历史来源不属于本项目")
            query = select(b.c.id, b.c.created_at).where(
                b.c.tenant_id == ctx.tenant.id,
                b.c.project_id == project,
                b.c.results.contains([{"source_row_id": str(source)}]),
            )
            if before_id is not None:
                query = query.where(b.c.id < before_id)
            rows = list(c.execute(query.order_by(b.c.id.desc()).limit(21)).mappings())
            return {
                "items": [
                    {"id": str(row["id"]), "created_at": row["created_at"].isoformat()}
                    for row in rows[:20]
                ],
                "next_id": str(rows[19]["id"]) if len(rows) > 20 else None,
            }

    def read(
        self,
        ctx: AuthContext,
        project: UUID,
        batch: UUID,
        *,
        before_source_id: UUID | None = None,
        before_decision_id: UUID | None = None,
        before_binding_id: UUID | None = None,
        expected_scope_digest: str | None = None,
    ) -> dict[str, Any]:
        cursor = (before_source_id, before_decision_id, before_binding_id)
        if any(v is not None for v in cursor) and (
            any(v is None for v in cursor) or expected_scope_digest is None
        ):
            raise ConversationError("汇总分页位置不完整，请刷新后继续")
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            authorize(c, ctx, project)
            KnowledgeCorrectionService._authorize(
                c, ctx.tenant.id, ctx.user.id, project, Action.DOCUMENT_ANALYZE
            )
            b = tables.decision_intake_batches
            batch_row = (
                c.execute(
                    select(b).where(
                        b.c.tenant_id == ctx.tenant.id, b.c.project_id == project, b.c.id == batch
                    )
                )
                .mappings()
                .one_or_none()
            )
            if batch_row is None:
                raise ConversationError("本项目没有此历史决策导入批次")
            identities = sorted(
                {
                    UUID(item["source_row_id"])
                    for item in batch_row["results"]
                    if item.get("source_row_id")
                    and item["status"] in {"created", "linked", "reused"}
                },
                key=str,
            )
            r, d, w, result, u = (
                tables.decision_intake_rows,
                tables.decisions,
                tables.project_intake_work,
                tables.project_intake_work_results,
                tables.users,
            )
            sources = {
                row["id"]: row
                for row in c.execute(
                    select(r).where(
                        r.c.tenant_id == ctx.tenant.id,
                        r.c.project_id == project,
                        r.c.id.in_(identities),
                    )
                ).mappings()
            }
            states = source_states(c, ctx.tenant.id, list(sources.values()))
            scope = scope_query(ctx.tenant.id, project, identities)
            joined = scope.outerjoin(
                w,
                and_(
                    w.c.tenant_id == ctx.tenant.id,
                    w.c.project_id == project,
                    w.c.work_snapshot["source"]["kind"].astext == "decision",
                    w.c.work_snapshot["source"]["id"].astext == cast(scope.c.decision_id, String),
                ),
            )
            # Scope changes invalidate pagination; task/result progress remains live per read.
            binding_ids = [
                str(value)
                for value in c.execute(
                    select(w.c.id)
                    .select_from(joined)
                    .where(w.c.id.is_not(None))
                    .distinct()
                    .order_by(w.c.id)
                ).scalars()
            ]
            scope_digest = digest(
                {
                    "sources": {str(key): value for key, value in states.items()},
                    "bindings": binding_ids,
                }
            )
            if expected_scope_digest is not None and scope_digest != expected_scope_digest:
                raise ConversationError("本批来源关系或工作范围已变化，请刷新汇总后继续")
            total = c.execute(select(func.count()).select_from(scope)).scalar_one()
            key = func.coalesce(w.c.id, ZERO)
            query = select(
                scope.c.source_id, scope.c.decision_id, key.label("binding_id")
            ).select_from(joined)
            if before_source_id is not None:
                query = query.where(tuple_(scope.c.source_id, scope.c.decision_id, key) < cursor)
            page = list(
                c.execute(
                    query.order_by(
                        scope.c.source_id.desc(), scope.c.decision_id.desc(), key.desc()
                    ).limit(21)
                ).mappings()
            )
            current_page = page[:20]
            decisions = {
                row["id"]: row
                for row in c.execute(
                    select(d).where(
                        d.c.tenant_id == ctx.tenant.id,
                        d.c.project_id == project,
                        d.c.id.in_({row["decision_id"] for row in current_page}),
                    )
                ).mappings()
            }
            latest = {
                row["binding_id"]: row
                for row in c.execute(
                    select(result, u.c.display_name.label("actor_name"))
                    .join(
                        u,
                        (u.c.tenant_id == result.c.tenant_id)
                        & (u.c.id == result.c.created_by_user_id),
                    )
                    .where(
                        result.c.tenant_id == ctx.tenant.id,
                        result.c.project_id == project,
                        result.c.binding_id.in_(
                            {row["binding_id"] for row in current_page if row["binding_id"] != ZERO}
                        ),
                    )
                    .distinct(result.c.binding_id)
                    .order_by(result.c.binding_id, result.c.revision.desc())
                ).mappings()
            }
            evaluated: dict[UUID, dict[str, Any]] = {}
            items = []
            for row in current_page:
                source, state = sources[row["source_id"]], states[row["source_id"]]
                decision = decisions.get(row["decision_id"])
                binding_id = row["binding_id"]
                work = None
                if binding_id != ZERO:
                    if binding_id not in evaluated:
                        evaluated[binding_id] = work_state(
                            c, ctx, project, binding_id, latest.get(binding_id)
                        )
                    work = evaluated[binding_id]
                items.append(
                    {
                        "source_id": str(source["id"]),
                        "locator": source["locator"],
                        "filename": source["source_snapshot"]["filename"],
                        "source_state": state,
                        "document_href": (
                            f"/projects?project={project}&tab=documents"
                            f"&document_id={source['document_id']}"
                        ),
                        "decision_id": str(row["decision_id"]),
                        "decision_title": decision["title"] if decision else "记录当前不可读取",
                        "decision_href": (
                            f"/projects?project={project}&tab=decisions"
                            f"#decision-{row['decision_id']}"
                        ),
                        "on_current_decision": state["current_decision_id"]
                        == str(row["decision_id"]),
                        "binding_id": str(binding_id) if binding_id != ZERO else None,
                        "status": work["status"] if work else "arrangement_missing",
                        "work": work,
                    }
                )
            unassigned = c.execute(
                select(func.count()).select_from(joined).where(w.c.id.is_(None))
            ).scalar_one()
            return {
                "batch_id": str(batch),
                "created_at": batch_row["created_at"].isoformat(),
                "read_at": datetime.now(UTC).isoformat(),
                "scope_digest": scope_digest,
                "counts": {
                    "sources": len(sources),
                    "historical_pairs": total,
                    "work_arrangements": len(binding_ids),
                    "unassigned_pairs": unassigned,
                    "import_errors": sum(
                        item["status"] == "error" for item in batch_row["results"]
                    ),
                },
                "items": items,
                "next": {
                    "before_source_id": str(page[19]["source_id"]),
                    "before_decision_id": str(page[19]["decision_id"]),
                    "before_binding_id": str(page[19]["binding_id"]),
                    "expected_scope_digest": scope_digest,
                }
                if len(page) > 20
                else None,
                "scope_note": (
                    "本批已登记或复用来源，以及这些来源至本次读取曾关联的决策和全部初始化任务。"
                    "来源纠错与内容更正前的旧工作保留。"
                ),
                "completion_note": (
                    "未安排工作不自动代表缺失或完成，请核对是否需要后续处理；"
                    "同一任务可能支持多条来源。结果仅覆盖已登记任务，"
                    "关联问题、其他后继影响与阶段验收仍须另行核对。"
                ),
            }
