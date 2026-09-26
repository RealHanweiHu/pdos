"""Durable, model-free learning capture from committed business records."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select, text
from sqlalchemy.dialects.postgresql import insert

from app.auth.roles import Action
from app.db.schema import tables
from app.domain.knowledge_candidates import build_candidate_draft
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.memories import MemoryDraft, MemoryService
from app.domain.product_workspace import _plain
from app.domain.quality_learning import QUALITY_LEARNING_KINDS, learning_refs


def enqueue_learning(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    actor_id: UUID,
    event_type: str,
    entity_id: UUID,
    event_id: str,
    audit_id: int,
    payload: dict[str, Any],
    snapshot: dict[str, Any],
    occurred_at: datetime,
) -> None:
    kind = None
    if event_type == "ISSUE_STATUS_CHANGED" and payload.get("to_status") == "closed":
        kind = "issue"
    elif event_type == "DECISION_RECORDED":
        kind = "decision"
    elif (
        event_type == "ROOT_CAUSE_ANALYSIS_CHANGED"
        and payload.get("action") == "approved"
        and snapshot.get("status") == "approved"
    ):
        kind = "root_cause"
    elif event_type == "EFFECTIVENESS_REVIEWED" and snapshot.get("result") in {
        "effective",
        "ineffective",
    }:
        kind = "effectiveness_review"
    elif (
        event_type == "NPI_RECORD_CHANGED"
        and payload.get("record_type") == "test_report"
        and payload.get("action") == "reviewed"
        and snapshot.get("review_status") == "approved"
    ):
        kind = "test_review"
    elif (
        event_type == "MEETING_STATE_CHANGED"
        and payload.get("meeting_type") == "project_retrospective"
        and payload.get("status") == "completed"
        and payload.get("action") in {"status_completed", "retrospective_confirmed"}
    ):
        kind = "project_retrospective"
    if kind is None:
        return
    connection.execute(
        insert(tables.knowledge_candidate_jobs)
        .values(
            id=uuid4(),
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=actor_id,
            source_kind=kind,
            source_id=entity_id,
            source_version=snapshot.get("retrospective_version", 0)
            if kind == "project_retrospective"
            else snapshot.get("version", 0)
            if kind == "root_cause"
            else snapshot.get("review_number", 0)
            if kind == "effectiveness_review"
            else 0,
            source_audit_id=audit_id,
            source_event_id=event_id,
            source_snapshot=snapshot,
            state="pending",
            available_at=occurred_at,
            created_at=occurred_at,
            updated_at=occurred_at,
        )
        .on_conflict_do_nothing(constraint="uq_knowledge_candidate_audit")
    )


def learning_draft(kind: str, source: dict[str, Any]) -> tuple[MemoryDraft | None, str]:
    def value(key: str) -> str:
        item = source.get(key)
        return item.strip() if isinstance(item, str) else ""

    if kind == "issue":
        draft = build_candidate_draft(
            title=value("title"),
            issue_type=value("issue_type"),
            severity=value("severity"),
            root_cause=value("root_cause"),
            resolution=value("resolution"),
            closure_criteria=value("closure_criteria"),
        )
        if draft is not None and len(draft.content) > 20_000:
            return None, "source_requires_manual_curation"
        return draft, "nothing_learned" if draft is None else "ready"
    title = value("title")
    if kind == "root_cause":
        if source.get("status") != "approved" or not value("root_cause"):
            return None, "quality_source_unavailable"
        title = "已批准根因分析"
        parts = [
            ("分析方法", value("method")),
            ("原分析过程", value("analysis")),
            ("具名批准的根因", value("root_cause")),
        ]
        applicability = (
            "仅来自该次已批准根因与原证据，不等于已验证整改有效；复用须核对失效模式、产品及工况。"
        )
    elif kind == "effectiveness_review":
        if source.get("result") not in {"effective", "ineffective"} or not value("actual_result"):
            return None, "quality_source_unavailable"
        title = "整改有效性复核" if source["result"] == "effective" else "整改无效经验"
        parts = [
            ("原验证判据", value("criteria")),
            ("观察到期日", value("observation_due_at")),
            ("实际结果", value("actual_result")),
            ("具名复核结论", "有效" if source["result"] == "effective" else "无效"),
            ("复核时点", value("reviewed_at")),
        ]
        applicability = (
            "仅代表该次观察范围和判据下的结果；无效结果保留，不能推定其他产品/工况的效果或发生率。"
        )
    elif kind == "decision":
        if not value("rationale") or not value("outcome"):
            return None, "decision_has_no_learning_basis"
        parts = [
            ("背景", value("context")),
            ("当时考虑的选项", "\n".join(str(x) for x in source.get("options", []))),
            ("当时选择", value("outcome")),
            ("选择理由", value("rationale")),
            ("权衡", value("trade_offs")),
            ("记录的预期后果（不代表已经发生）", value("consequence")),
        ]
        applicability = "来自当时记录的决策依据；实际效果和适用条件仍须知识审核人核对。"
    elif kind == "test_review":
        if source.get("review_status") != "approved" or not value("summary"):
            return None, "test_review_has_no_approved_summary"
        parts = [
            ("测试结果", value("result")),
            ("已审核报告摘要", value("summary")),
            ("测试报告审核意见", value("review_note")),
        ]
        applicability = "来自已审核测试报告；仅描述当次报告，复用前须核对样机、条件与范围。"
    else:
        # A schedule, agenda, or raw transcript is not a confirmed retrospective.
        if source.get("conclusion_confirmed") is not True or not value("retrospective_conclusion"):
            return None, "retrospective_has_no_confirmed_conclusion"
        parts = [("已确认复盘结论", value("retrospective_conclusion"))]
        applicability = (
            value("retrospective_applicability")
            or "来自具名确认的项目复盘结论，复用仍须核对适用条件。"
        )
    content = "\n\n".join(f"## {name}\n{body}" for name, body in parts if body)
    if len(content) > 20_000:
        return None, "source_requires_manual_curation"
    return MemoryDraft(
        title=f"经验候选：{title}"[:512],
        content=content,
        applicability=applicability,
        tags=(kind, "classification_pending"),
    ), "ready"


class KnowledgeLearningWorker:
    def __init__(self, engine: Engine):
        self.engine = engine

    def run_once(
        self,
        *,
        tenant_id: UUID | None = None,
        project_id: UUID | None = None,
        job_id: UUID | None = None,
        requested_by: UUID | None = None,
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            if requested_by is not None:
                if tenant_id is None or project_id is None:
                    raise ValueError("Manual collection requires a bound tenant and project")
                KnowledgeCorrectionService._authorize(
                    connection, tenant_id, requested_by, project_id, Action.MEMORY_DRAFT
                )
            table = tables.knowledge_candidate_jobs
            query = select(table)
            if job_id is None:
                query = query.where(
                    table.c.state == "pending", table.c.available_at <= datetime.now(UTC)
                )
            else:
                query = query.where(table.c.id == job_id)
            if tenant_id is not None:
                query = query.where(table.c.tenant_id == tenant_id)
            if project_id is not None:
                query = query.where(table.c.project_id == project_id)
            job = (
                connection.execute(
                    query.order_by(table.c.created_at, table.c.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                .mappings()
                .one_or_none()
            )
            if job is None:
                return {"state": "idle"}
            if job["state"] not in {"pending", "failed"}:
                return _plain(
                    {key: job[key] for key in ("id", "state", "memory_id", "reason", "attempts")}
                )
            attempts = job["attempts"] + 1
            now = datetime.now(UTC)
            result: dict[str, Any]
            try:
                # A failed candidate rolls back only this savepoint. The source
                # action already committed before any worker can see its job.
                with connection.begin_nested():
                    KnowledgeCorrectionService._authorize(
                        connection,
                        job["tenant_id"],
                        job["actor_user_id"],
                        job["project_id"],
                        Action.MEMORY_DRAFT,
                    )
                    connection.execute(
                        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                        {
                            "key": (
                                f"knowledge-origin:{job['tenant_id']}:{job['source_kind']}:"
                                f"{job['source_id']}"
                            )
                        },
                    )
                    existing = connection.execute(
                        select(table.c.memory_id).where(
                            table.c.tenant_id == job["tenant_id"],
                            table.c.source_kind == job["source_kind"],
                            table.c.source_id == job["source_id"],
                            table.c.source_version == job["source_version"],
                            table.c.state == "created",
                        )
                    ).scalar_one_or_none()
                    if existing is None and job["source_kind"] == "issue":
                        existing = connection.execute(
                            select(tables.memories.c.id).where(
                                tables.memories.c.tenant_id == job["tenant_id"],
                                tables.memories.c.project_id == job["project_id"],
                                tables.memories.c.source_issue_id == job["source_id"],
                            )
                        ).scalar_one_or_none()
                    if existing is not None:
                        result = dict(
                            state="duplicate", memory_id=existing, reason="already_captured"
                        )
                    else:
                        draft, reason = learning_draft(job["source_kind"], job["source_snapshot"])
                        quality_refs: list[dict[str, object]] = []
                        if draft is not None and job["source_kind"] in QUALITY_LEARNING_KINDS:
                            KnowledgeCorrectionService._authorize(
                                connection,
                                job["tenant_id"],
                                job["actor_user_id"],
                                job["project_id"],
                                Action.QUALITY_VIEW,
                            )
                            resolved, reason = learning_refs(connection, job)
                            if resolved is None:
                                draft = None
                            else:
                                quality_refs = resolved
                        if draft is not None and job["source_kind"] == "project_retrospective":
                            meeting = (
                                connection.execute(
                                    select(tables.meetings)
                                    .where(
                                        tables.meetings.c.tenant_id == job["tenant_id"],
                                        tables.meetings.c.project_id == job["project_id"],
                                        tables.meetings.c.id == job["source_id"],
                                    )
                                    .with_for_update()
                                )
                                .mappings()
                                .one_or_none()
                            )
                            if (
                                meeting is None
                                or meeting["deleted_at"] is not None
                                or meeting["status"] != "completed"
                                or meeting["retrospective_version"] != job["source_version"]
                                or meeting["retrospective_digest"]
                                != job["source_snapshot"].get("retrospective_digest")
                            ):
                                draft, reason = None, "retrospective_version_superseded"
                        if draft is None:
                            result = dict(state="skipped", memory_id=None, reason=reason)
                        else:
                            refs: list[dict[str, object]] = [
                                {"kind": "event", "reference": job["source_event_id"]},
                                *quality_refs,
                            ]
                            if job["source_kind"] == "project_retrospective":
                                refs.extend(
                                    job["source_snapshot"].get("retrospective_source_refs", [])
                                )
                                refs.append(
                                    {
                                        "kind": "meeting_retrospective",
                                        "reference": str(job["source_id"]),
                                        "version": job["source_version"],
                                        "digest": job["source_snapshot"].get(
                                            "retrospective_digest"
                                        ),
                                    }
                                )
                            if job["source_kind"] == "issue":
                                refs.append({"kind": "issue", "reference": str(job["source_id"])})
                                evidence = job["source_snapshot"].get("closure_evidence_ref")
                                if isinstance(evidence, str) and evidence.strip():
                                    refs.append({"kind": "closure_evidence", "reference": evidence})
                            memory = MemoryService(self.engine).create(
                                tenant_id=job["tenant_id"],
                                project_id=job["project_id"],
                                actor_user_id=job["actor_user_id"],
                                draft=draft,
                                source_issue_id=job["source_id"]
                                if job["source_kind"] == "issue"
                                else None,
                                source_refs=tuple(refs),
                                connection=connection,
                            )
                            result = dict(
                                state="created",
                                memory_id=memory.id,
                                reason="awaiting_knowledge_review",
                            )
            except Exception as error:
                result = dict(
                    state="failed" if attempts >= 5 else "pending",
                    memory_id=None,
                    reason=f"capture_failed:{type(error).__name__}"[:128],
                )
            connection.execute(
                table.update()
                .where(table.c.id == job["id"])
                .values(
                    **result,
                    attempts=attempts,
                    updated_at=now,
                    available_at=now + timedelta(seconds=min(300, 30 * 2 ** min(attempts, 4))),
                )
            )
            return _plain({"id": job["id"], **result, "attempts": attempts})

    def list(self, *, tenant_id: UUID, project_id: UUID, actor_id: UUID) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            KnowledgeCorrectionService._authorize(
                connection, tenant_id, actor_id, project_id, Action.MEMORY_VIEW
            )
            table = tables.knowledge_candidate_jobs
            rows = connection.execute(
                select(
                    table.c.id,
                    table.c.source_kind,
                    table.c.source_version,
                    table.c.source_id,
                    table.c.state,
                    table.c.memory_id,
                    table.c.reason,
                    table.c.attempts,
                    table.c.created_at,
                    table.c.source_snapshot["title"].as_string().label("title"),
                )
                .where(table.c.tenant_id == tenant_id, table.c.project_id == project_id)
                .order_by(table.c.created_at.desc())
                .limit(200)
            ).mappings()
            return [_plain(row) for row in rows]
