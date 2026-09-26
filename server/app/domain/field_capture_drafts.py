"""Versioned human field drafts and atomic conversion through existing business services."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.field_capture_inputs import CaptureDraft
from app.domain.field_captures import CaptureError, FieldCaptureService, summary
from app.domain.field_recognitions import require_source
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.test_runs import TestRunDraft, TestRunService


class CaptureConflict(CaptureError):
    pass


def case_source(row: Any) -> dict[str, Any]:
    return _plain(
        {
            key: row[key]
            for key in (
                "id",
                "project_id",
                "plan_id",
                "title",
                "method",
                "acceptance_criteria",
                "specification_id",
                "severity",
            )
        }
    )


class FieldCaptureDraftService:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.captures = FieldCaptureService(engine)

    @staticmethod
    def latest(c: Connection, ctx: AuthContext, identity: UUID) -> Any:
        t = tables.field_capture_drafts
        return (
            c.execute(
                select(t)
                .where(t.c.tenant_id == ctx.tenant.id, t.c.capture_id == identity)
                .order_by(t.c.version.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )

    def save(
        self,
        ctx: AuthContext,
        project: UUID,
        identity: UUID,
        request_id: UUID,
        expected_version: int,
        draft: CaptureDraft,
    ) -> dict[str, Any]:
        body = draft.model_dump(mode="json")
        with self.engine.begin() as c:
            capture = self.captures.row(c, ctx, project, identity, write=True)
            if capture["submitted_at"]:
                raise CaptureConflict("此记录已经提交，请进入原业务记录办理")
            require_source(c, ctx, identity, draft.recognition_id)
            if draft.kind == "test":
                KnowledgeCorrectionService._authorize(
                    c, ctx.tenant.id, ctx.user.id, project, Action.TEST_RUN_RECORD
                )
            latest = self.latest(c, ctx, identity)
            version = latest["version"] if latest else 0
            t = tables.field_capture_drafts
            prior = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.capture_id == identity,
                        t.c.request_id == request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["body"] != body or prior["version"] != expected_version + 1:
                    raise CaptureConflict("此保存请求已用于另一份内容")
                if prior["version"] != version:
                    raise CaptureConflict("此草稿保存后已有新版本，请刷新核对")
                return _plain(prior)
            if expected_version != version:
                raise CaptureConflict("草稿已在另一窗口更新，请保留当前输入并重新打开核对")
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=ctx.tenant.id,
                        project_id=project,
                        capture_id=identity,
                        request_id=request_id,
                        version=version + 1,
                        body=body,
                        created_by_user_id=ctx.user.id,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            return _plain(row)

    def history(
        self, ctx: AuthContext, project: UUID, identity: UUID, before: int | None
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            capture = self.captures.row(c, ctx, project, identity)
            if capture["created_by_user_id"] != ctx.user.id:
                raise CaptureError("草稿编辑历史仅创建人可读，请查看已提交核对记录")
            t = tables.field_capture_drafts
            q = select(t).where(t.c.tenant_id == ctx.tenant.id, t.c.capture_id == identity)
            if before is not None:
                q = q.where(t.c.version < before)
            result = list(c.execute(q.order_by(t.c.version.desc()).limit(21)).mappings())
            return {
                "items": [_plain(r) for r in result[:20]],
                "next_before": result[19]["version"] if len(result) > 20 else None,
            }

    def cases(self, ctx: AuthContext, project: UUID, query: str) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            self.captures.authorize(c, ctx, project)
            KnowledgeCorrectionService._authorize(
                c, ctx.tenant.id, ctx.user.id, project, Action.TEST_RUN_RECORD
            )
            t = tables.test_cases
            q = select(t).where(t.c.tenant_id == ctx.tenant.id, t.c.project_id == project)
            if query.strip():
                q = q.where(
                    t.c.title.ilike(
                        "%"
                        + query.strip()
                        .replace("\\", "\\\\")
                        .replace("%", "\\%")
                        .replace("_", "\\_")
                        + "%",
                        escape="\\",
                    )
                )
            return [
                case_source(r) | {"digest": digest(case_source(r))}
                for r in c.execute(q.order_by(t.c.title, t.c.id).limit(50)).mappings()
            ]

    def submit(
        self, ctx: AuthContext, project: UUID, identity: UUID, expected_version: int
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            capture = self.captures.row(c, ctx, project, identity, write=True)
            latest = self.latest(c, ctx, identity)
            if latest is None or latest["version"] != expected_version:
                raise CaptureConflict("请先保存并核对最新草稿版本")
            if capture["submitted_at"]:
                if capture["review"].get("draft_version") != expected_version:
                    raise CaptureConflict("此现场记录已经转入其他业务记录")
                return summary(capture)
            if capture["filename"] and not capture["uploaded_at"]:
                raise CaptureError("请先补传原件")
            d = CaptureDraft.model_validate(latest["body"])
            require_source(c, ctx, identity, d.recognition_id)
            if d.recognition_id and not d.recognition_note.strip():
                raise CaptureError("请记录识别文字的核对情况及仍不确定之处")
            if not d.description.strip() or (d.sample_id is None and not d.sample_reason.strip()):
                raise CaptureError("请填写现场描述，未关联样机时说明待核对内容")
            if d.kind == "issue":
                if not d.title.strip():
                    raise CaptureError("请填写问题标题")
                review = {
                    key: latest["body"][key]
                    for key in (
                        "title",
                        "description",
                        "issue_type",
                        "severity",
                        "sample_id",
                        "sample_reason",
                    )
                }
                review.update(
                    confirmed=True,
                    draft_version=expected_version,
                    recognition_id=str(d.recognition_id) if d.recognition_id else None,
                    recognition_note=d.recognition_note,
                )
                return self.captures.submit(
                    ctx, project, identity, review, connection=c, from_saved_draft=True
                )
            KnowledgeCorrectionService._authorize(
                c, ctx.tenant.id, ctx.user.id, project, Action.TEST_RUN_RECORD
            )
            if d.test_case_id is None or not d.test_case_digest:
                raise CaptureError("请选择实际测试用例并核对方法和判据")
            if d.status != "in_progress" and (
                d.executed_at is None
                or d.execution_time_precision == "unknown"
                or not d.execution_time_reason.strip()
            ):
                raise CaptureError(
                    "完成的测试须填写实际测试时间及登记依据，不使用拍照或上传时间替代"
                )
            if any(not m.name.strip() or not m.value.strip() for m in d.metrics):
                raise CaptureError("请补全每个测量项的名称和值，未知结果请在说明中保留")
            if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
                raise CaptureError("项目当前不可办理")
            case = (
                c.execute(
                    select(tables.test_cases)
                    .where(
                        tables.test_cases.c.tenant_id == ctx.tenant.id,
                        tables.test_cases.c.project_id == project,
                        tables.test_cases.c.id == d.test_case_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if case is None or digest(case_source(case)) != d.test_case_digest:
                raise CaptureConflict("测试用例或方法、判据已变化，请重新选择核对并保存草稿")
            notes = (
                d.description + f"\n\n现场原始资料：/capture?project={project}&capture={identity}"
            )
            if d.sample_id is None:
                notes += "\n样机未关联：" + d.sample_reason
            run = TestRunService(self.engine).record_run(
                tenant_id=ctx.tenant.id,
                actor_user_id=ctx.user.id,
                project_id=project,
                test_case_id=d.test_case_id,
                connection=c,
                draft=TestRunDraft(
                    status=d.status,
                    sample_id=d.sample_id,
                    conditions={"description": d.conditions},
                    metrics=tuple(m.model_dump() for m in d.metrics),
                    equipment=d.equipment or None,
                    environment=d.environment or None,
                    result_notes=notes,
                    expected_completion_at=d.expected_completion_at,
                    evidence_document_id=d.evidence_document_id,
                    executed_at=d.executed_at,
                    execution_time_precision=d.execution_time_precision,
                    execution_time_reason=d.execution_time_reason or None,
                    configuration_mode=d.configuration_mode,
                    configuration_revision_id=d.configuration_revision_id,
                    configuration_reason=d.configuration_reason or None,
                ),
            )
            review = {
                key: value
                for key, value in latest["body"].items()
                if key not in {"title", "issue_type", "severity"}
            } | {
                "confirmed": True,
                "draft_version": expected_version,
                "test_case_snapshot": case_source(case),
            }
            c.execute(
                tables.field_captures.update()
                .where(tables.field_captures.c.id == identity)
                .values(test_run_id=run.id, review=review, submitted_at=datetime.now(UTC))
            )
            return summary(self.captures.row(c, ctx, project, identity, write=True))
