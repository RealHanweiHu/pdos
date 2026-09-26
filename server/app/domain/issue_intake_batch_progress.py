"""Live, paged compensation progress for the historical scope of a correction batch."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, and_, exists, func, or_, select, union

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.conversations import ConversationError
from app.domain.issue_intake_compensation_results import current_evidence, public_result
from app.domain.issue_intake_compensations import task_view
from app.domain.issue_intake_corrections import public_source, source_states
from app.domain.issue_intake_reference_reviews import reference_key, resolve
from app.domain.issue_intake_reuse import target_snapshot
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.product_workspace import _plain


def scope_query(tenant: UUID, project: UUID, results: list[dict[str, Any]]) -> Any:
    s, h = tables.issue_intake_rows, tables.issue_intake_corrections
    ids = [UUID(item["source_row_id"]) for item in results]
    history = [
        h.c.tenant_id == tenant,
        h.c.project_id == project,
        or_(
            *[
                and_(
                    h.c.source_row_id == UUID(item["source_row_id"]),
                    h.c.revision <= item["revision"],
                )
                for item in results
            ]
        ),
    ]
    return union(
        select(s.c.id.label("source_id"), s.c.issue_id).where(
            s.c.tenant_id == tenant, s.c.project_id == project, s.c.id.in_(ids)
        ),
        select(h.c.source_row_id.label("source_id"), h.c.previous_issue_id.label("issue_id")).where(
            *history, h.c.previous_issue_id.is_not(None)
        ),
        select(h.c.source_row_id.label("source_id"), h.c.target_issue_id.label("issue_id")).where(
            *history, h.c.target_issue_id.is_not(None)
        ),
    ).subquery("batch_issue_scope")


def evaluate(
    c: Connection,
    ctx: AuthContext,
    project: UUID,
    source: dict[str, Any],
    state: dict[str, Any],
    issue: dict[str, Any],
    task: dict[str, Any],
    result: Any,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    if result is None:
        return {
            "status": "result_missing",
            "reasons": ["已安排任务，尚未登记补偿办理结果"],
            "result": None,
        }
    reasons = []
    if result["source_revision"] != state["revision"]:
        reasons.append("来源已有后续纠错")
    if result["after_snapshot"] != issue:
        reasons.append("原问题已有后续变化")
    original_task = result["context_snapshot"]["task"]
    if any(
        original_task.get(key) != task.get(key)
        for key in (
            "id",
            "title",
            "description",
            "assignee_user_id",
            "stage_id",
            "start_date",
            "due_date",
            "expected_output",
        )
    ):
        reasons.append("任务负责人、日期或处理要求已变化")
    if any(item["changed"] for item in evidence):
        reasons.append("所选原文件已变化或不可读")
    saved = result["context_snapshot"].get("business_references", [])
    current = resolve(c, ctx, project, source, UUID(issue["id"]), saved)
    incomplete_visibility = any(reference_key(item) not in current for item in saved)
    if incomplete_visibility:
        reasons.append("当前权限不足以核对全部已选业务引用，请由有权限的人员续办")
    visible = [item for item in saved if reference_key(item) in current]
    if any(
        current[reference_key(item)] is None
        or (current[reference_key(item)] or {}).get("digest") != item["expected_digest"]
        for item in visible
    ):
        reasons.append("已选业务记录或关系有后续变化")
    pending = result["outcome"] in {"recorded", "needs_follow_up"} or any(
        item["result"] == "follow_up" for item in visible
    )
    status = "recheck" if reasons else "follow_up" if pending else "recorded"
    if pending:
        reasons.append("最近一次办理仍登记了进展或后续处理要求")
    # Raw business snapshots remain behind the per-domain result detail checks.
    return {"status": status, "reasons": reasons, "result": public_result(result)}


class IssueIntakeBatchProgress:
    def __init__(self, engine: Engine):
        self.engine = engine

    def read(
        self,
        ctx: AuthContext,
        project: UUID,
        batch: UUID,
        *,
        before_source_id: UUID | None = None,
        before_issue_id: UUID | None = None,
    ) -> dict[str, Any]:
        if (before_source_id is None) != (before_issue_id is None):
            raise ConversationError("汇总分页位置不完整，请重新读取")
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            KnowledgeCorrectionService._authorize(
                c, ctx.tenant.id, ctx.user.id, project, Action.WORK_ITEM_VIEW
            )
            b = tables.issue_intake_correction_batches
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
                raise ConversationError("本项目没有此纠错批次")
            scope = scope_query(ctx.tenant.id, project, batch_row["results"])
            t = tables.issue_intake_compensations
            assigned = exists(
                select(t.c.id).where(
                    t.c.tenant_id == ctx.tenant.id,
                    t.c.project_id == project,
                    t.c.source_row_id == scope.c.source_id,
                    t.c.issue_id == scope.c.issue_id,
                )
            )
            total = c.execute(select(func.count()).select_from(scope)).scalar_one()
            assigned_count = c.execute(
                select(func.count()).select_from(scope).where(assigned)
            ).scalar_one()
            page = select(scope)
            if before_source_id is not None:
                page = page.where(
                    or_(
                        scope.c.source_id < before_source_id,
                        (scope.c.source_id == before_source_id)
                        & (scope.c.issue_id < before_issue_id),
                    )
                )
            pairs = (
                c.execute(
                    page.order_by(scope.c.source_id.desc(), scope.c.issue_id.desc()).limit(21)
                )
                .mappings()
                .all()
            )
            pairs_page = pairs[:20]
            source_ids = {row["source_id"] for row in pairs_page}
            sources = {
                row["id"]: row
                for row in c.execute(
                    select(tables.issue_intake_rows).where(
                        tables.issue_intake_rows.c.tenant_id == ctx.tenant.id,
                        tables.issue_intake_rows.c.project_id == project,
                        tables.issue_intake_rows.c.id.in_(source_ids),
                    )
                ).mappings()
            }
            states = source_states(c, ctx.tenant.id, list(sources.values()))
            issues = {
                row["id"]: target_snapshot(row)
                for row in c.execute(
                    select(tables.issues).where(
                        tables.issues.c.tenant_id == ctx.tenant.id,
                        tables.issues.c.project_id == project,
                        tables.issues.c.id.in_({row["issue_id"] for row in pairs_page}),
                    )
                ).mappings()
            }
            bindings = (
                c.execute(
                    select(
                        t,
                        func.count()
                        .over(partition_by=(t.c.source_row_id, t.c.issue_id))
                        .label("binding_count"),
                    )
                    .where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.project_id == project,
                        or_(
                            *[
                                and_(
                                    t.c.source_row_id == row["source_id"],
                                    t.c.issue_id == row["issue_id"],
                                )
                                for row in pairs_page
                            ]
                        ),
                    )
                    .distinct(t.c.source_row_id, t.c.issue_id)
                    .order_by(
                        t.c.source_row_id, t.c.issue_id, t.c.source_revision.desc(), t.c.id.desc()
                    )
                )
                .mappings()
                .all()
                if pairs_page
                else []
            )
            by_pair = {(row["source_row_id"], row["issue_id"]): row for row in bindings}
            task_table = tables.tasks
            tasks = {
                row["id"]: task_view(row)
                for row in c.execute(
                    select(task_table).where(
                        task_table.c.tenant_id == ctx.tenant.id,
                        task_table.c.project_id == project,
                        task_table.c.id.in_({row["task_id"] for row in bindings}),
                    )
                ).mappings()
            }
            r, u = tables.issue_intake_compensation_results, tables.users
            results = (
                c.execute(
                    select(r, u.c.display_name.label("actor_name"))
                    .join(u, (u.c.tenant_id == r.c.tenant_id) & (u.c.id == r.c.created_by_user_id))
                    .where(
                        r.c.tenant_id == ctx.tenant.id,
                        r.c.project_id == project,
                        r.c.binding_id.in_({row["id"] for row in bindings}),
                    )
                    .distinct(r.c.binding_id)
                    .order_by(r.c.binding_id, r.c.revision.desc())
                )
                .mappings()
                .all()
            )
            latest = {row["binding_id"]: row for row in results}
            checked_evidence = current_evidence(
                c,
                ctx.tenant.id,
                project,
                [item for row in results for item in row["evidence_snapshot"]],
            )
            evidence_by_key = {
                (item["document_id"], item["expected_digest"]): item for item in checked_evidence
            }
            batch_revisions = {
                UUID(item["source_row_id"]): item["revision"] for item in batch_row["results"]
            }
            items = []
            for pair in pairs_page:
                source_id, issue_id = pair["source_id"], pair["issue_id"]
                source, state, issue = (
                    public_source(sources[source_id]),
                    states[source_id],
                    issues[issue_id],
                )
                binding = by_pair.get((source_id, issue_id))
                value: dict[str, Any] = {
                    "source": source,
                    "issue": issue,
                    "current_source": state,
                    "batch_source_revision": batch_revisions[source_id],
                    "binding": None,
                    "status": "unassigned",
                    "reasons": ["本问题尚无来源纠错补偿任务"],
                    "result": None,
                }
                if binding is not None:
                    task, result = tasks[binding["task_id"]], latest.get(binding["id"])
                    evidence = (
                        [
                            evidence_by_key[(item["document_id"], item["expected_digest"])]
                            for item in result["evidence_snapshot"]
                        ]
                        if result is not None
                        else []
                    )
                    value.update(
                        evaluate(c, ctx, project, source, state, issue, task, result, evidence)
                    )
                    value["binding"] = _plain(binding) | {
                        "task": task,
                        "current_source": state,
                        "source_changed": state["revision"] != binding["source_revision"],
                    }
                items.append(value)
            return {
                "batch_id": str(batch),
                "read_at": datetime.now(UTC).isoformat(),
                "scope_total": total,
                "assigned_total": assigned_count,
                "unassigned_total": total - assigned_count,
                "items": items,
                "page_counts": {
                    key: sum(item["status"] == key for item in items)
                    for key in ("unassigned", "result_missing", "recheck", "follow_up", "recorded")
                },
                "next": {
                    "before_source_id": str(pairs[19]["source_id"]),
                    "before_issue_id": str(pairs[19]["issue_id"]),
                }
                if len(pairs) > 20
                else None,
                "scope_note": (
                    "范围固定为本批各来源最初及截至本批纠错版本曾关联的问题；"
                    "每项展示最新安排和最近办理。后续新关联须另行核对。"
                ),
                "completion_note": (
                    "已有核对结果不等于全部后继已处理或整批业务已撤销；"
                    "旧任务保留，未选引用、更深层影响及正式验证仍须继续办理。"
                ),
            }
