"""Private staged Excel uploads processed by the application worker."""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import Engine, and_, false, func, or_, select, text

from app.ai.application_leases import ApplicationLeaseKeeper
from app.ai.import_mapping_runs import ImportMappingRunStore
from app.auth.repository import AuthContext, AuthRepository
from app.db.schema import tables
from app.domain.documents import MAX_DOCUMENT_BYTES, extract_document
from app.domain.test_report_import import (
    ImportBatchResult,
    ImportError_,
    TestReportImportService,
    _fingerprint,
    mapping_request,
)
from app.domain.test_report_workbook import parse_workbook
from app.storage.documents import DocumentObjectStore, ReadableDocumentObjectStore

logger = logging.getLogger(__name__)


def batch_body(batch: ImportBatchResult) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(json.dumps(asdict(batch), default=str)))


class ReportImportQueue:
    def __init__(
        self,
        engine: Engine,
        *,
        object_store: DocumentObjectStore | None = None,
        gateway: Any = None,
    ):
        self.engine, self.object_store, self.gateway = engine, object_store, gateway
        self.service = TestReportImportService(engine, object_store=object_store, gateway=gateway)

    def submit(
        self,
        *,
        context: AuthContext,
        project_id: UUID,
        plan_id: UUID,
        filename: str,
        content: bytes,
    ) -> dict[str, Any]:
        self.service._authorize_import(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            auth_version=context.user.auth_version,
        )
        filename = Path(filename).name
        if not filename.lower().endswith(".xlsx") or len(filename) > 512:
            raise ImportError_("IMPORT_FILE_INVALID", "请上传有效的 Excel 文件")
        extract_document(filename=filename, content=content)
        report = parse_workbook(content)
        fingerprint = _fingerprint(
            report.headers if report.layout == "flat_v1" else [report.layout, *report.headers]
        )
        with self.engine.connect() as c:
            if (
                c.execute(
                    select(tables.test_plans.c.id).where(
                        tables.test_plans.c.tenant_id == context.tenant.id,
                        tables.test_plans.c.project_id == project_id,
                        tables.test_plans.c.id == plan_id,
                    )
                ).first()
                is None
            ):
                raise ImportError_("IMPORT_PLAN_NOT_FOUND", "test plan was not found")
            existing = self.service._existing_import(
                c,
                tenant_id=context.tenant.id,
                project_id=project_id,
                plan_id=plan_id,
                content=content,
            )
            known = (
                report.layout == "test_form_v1"
                or self.service._latest_confirmed_mapping(
                    c, tenant_id=context.tenant.id, fingerprint=fingerprint
                )
                is not None
            )
        if existing is not None:
            return dict(
                run_id=None, status="completed", batch=batch_body(existing), error_code=None
            )
        if known:
            return self._immediate(context, project_id, plan_id, filename, content)
        if not isinstance(self.object_store, ReadableDocumentObjectStore):
            raise ImportError_("IMPORT_QUEUE_STORAGE_REQUIRED", "暂存文件服务不可用")
        content_sha = hashlib.sha256(content).hexdigest()
        request_id, request_context, _ = mapping_request(
            report=report,
            actor_user_id=context.user.id,
            plan_id=plan_id,
            content_sha256=content_sha,
        )
        # This guard also serializes the original upload endpoint for the same bytes.
        with self.engine.begin() as guard:
            guard.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {
                    "key": (
                        f"pdos-import-request:{context.tenant.id}:{project_id}:"
                        f"{plan_id}:{content_sha}"
                    )
                },
            )
            run, _ = ImportMappingRunStore(self.engine, gateway=self.gateway).start(
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                auth_version=context.user.auth_version,
                request_id=request_id,
                request_context=request_context,
                enqueue=True,
            )
            if run["status"] == "succeeded" and run["run_context"].get("mapping_result"):
                # The original successful mapping is deterministic to consume now.
                return self._immediate(
                    context, project_id, plan_id, filename, content, serialized=True
                )
            with self.engine.connect() as c:
                staged = c.execute(
                    select(tables.application_import_inputs.c.id).where(
                        tables.application_import_inputs.c.tenant_id == context.tenant.id,
                        tables.application_import_inputs.c.run_id == run["id"],
                    )
                ).first()
            if staged is None:
                if run["status"] != "queued":
                    raise ImportError_("IMPORT_MODEL_UNAVAILABLE", "原映射请求不可继续")
                key = (
                    f"tenants/{context.tenant.id}/projects/{project_id}/"
                    f"application-inputs/{run['id']}/source.xlsx"
                )
                try:
                    self.object_store.put(
                        object_key=key,
                        content=content,
                        media_type=(
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        ),
                        sha256=content_sha,
                    )
                    with self.engine.begin() as c:
                        c.execute(
                            tables.application_import_inputs.insert().values(
                                id=uuid4(),
                                tenant_id=context.tenant.id,
                                run_id=run["id"],
                                project_id=project_id,
                                plan_id=plan_id,
                                filename=filename,
                                object_key=key,
                                content_sha256=content_sha,
                                byte_size=len(content),
                                created_at=func.clock_timestamp(),
                            )
                        )
                except Exception:
                    with suppress(Exception):
                        self.object_store.delete(object_key=key)
                    with self.engine.begin() as c:
                        c.execute(
                            tables.agent_runs.update()
                            .where(
                                tables.agent_runs.c.id == run["id"],
                                tables.agent_runs.c.status == "queued",
                            )
                            .values(
                                status="failed",
                                error_code="APPLICATION_IMPORT_STAGING_FAILED",
                                completed_at=func.clock_timestamp(),
                                updated_at=func.clock_timestamp(),
                            )
                        )
                    raise
        return self.get(context=context, project_id=project_id, run_id=run["id"])

    def _immediate(
        self,
        context: AuthContext,
        project: UUID,
        plan: UUID,
        filename: str,
        content: bytes,
        *,
        serialized: bool = False,
    ) -> dict[str, Any]:
        method = self.service._start_import_serialized if serialized else self.service.start_import
        batch = method(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project,
            plan_id=plan,
            filename=filename,
            content=content,
            auth_version=context.user.auth_version,
        )
        return dict(run_id=None, status="completed", batch=batch_body(batch), error_code=None)

    def get(self, *, context: AuthContext, project_id: UUID, run_id: UUID) -> dict[str, Any]:
        self.service._authorize_import(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            auth_version=context.user.auth_version,
        )
        with self.engine.connect() as c:
            row = (
                c.execute(
                    select(
                        tables.application_import_inputs,
                        tables.agent_runs.c.status.label("run_status"),
                        tables.agent_runs.c.error_code.label("run_error"),
                    )
                    .join(
                        tables.agent_runs,
                        tables.agent_runs.c.id == tables.application_import_inputs.c.run_id,
                    )
                    .where(
                        tables.application_import_inputs.c.tenant_id == context.tenant.id,
                        tables.application_import_inputs.c.project_id == project_id,
                        tables.application_import_inputs.c.run_id == run_id,
                        tables.agent_runs.c.requested_by_user_id == context.user.id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ImportError_("IMPORT_ACCESS_DENIED", "请求不可见")
            batch = None
            if row["batch_id"] is not None:
                b = (
                    c.execute(
                        select(tables.test_report_import_batches).where(
                            tables.test_report_import_batches.c.tenant_id == context.tenant.id,
                            tables.test_report_import_batches.c.id == row["batch_id"],
                        )
                    )
                    .mappings()
                    .one()
                )
                batch = dict(
                    id=str(b["id"]),
                    project_id=str(project_id),
                    plan_id=str(b["plan_id"]),
                    document_id=str(b["document_id"]),
                    template_fingerprint=b["template_fingerprint"],
                    mapping_source=b["mapping_source"],
                    status=b["status"],
                    confidence=b["parse_confidence"].get("mapping_confidence"),
                    created_run_ids=b["created_run_ids"],
                    skipped_rows=b["skipped_rows"],
                    reused_existing=False,
                )
            recoverable = (
                row["resolved_at"] is None
                and row["run_error"] == "APPLICATION_RUN_LEASE_EXPIRED"
                and c.execute(
                    select(tables.application_result_checkpoints.c.id).where(
                        tables.application_result_checkpoints.c.run_id == run_id
                    )
                ).first()
                is not None
            )
            error = row["error_code"] or row["run_error"]
            state = (
                "completed"
                if batch
                else "cancelled"
                if error == "APPLICATION_REQUEST_CANCELLED"
                else "queued"
                if recoverable
                else row["run_status"]
            )
            return dict(run_id=str(run_id), status=state, batch=batch, error_code=error)

    def run_next(self) -> bool:
        if not isinstance(self.object_store, ReadableDocumentObjectStore):
            raise ImportError_("IMPORT_QUEUE_STORAGE_REQUIRED", "暂存文件服务不可用")
        recoverable = and_(
            tables.agent_runs.c.status == "degraded",
            tables.agent_runs.c.error_code == "APPLICATION_RUN_LEASE_EXPIRED",
            select(tables.application_result_checkpoints.c.id)
            .where(tables.application_result_checkpoints.c.run_id == tables.agent_runs.c.id)
            .exists(),
        )
        with self.engine.connect() as c:
            row = (
                c.execute(
                    select(tables.application_import_inputs)
                    .join(
                        tables.agent_runs,
                        tables.agent_runs.c.id == tables.application_import_inputs.c.run_id,
                    )
                    .where(
                        or_(
                            and_(
                                tables.application_import_inputs.c.resolved_at.is_not(None),
                                tables.application_import_inputs.c.released_at.is_(None),
                            ),
                            and_(
                                tables.application_import_inputs.c.resolved_at.is_(None),
                                or_(
                                    tables.agent_runs.c.status.in_(
                                        ["queued", "failed", "degraded"]
                                    ),
                                    recoverable,
                                ),
                            ),
                        )
                    )
                    .order_by(
                        tables.application_import_inputs.c.resolved_at.is_not(None),
                        tables.application_import_inputs.c.created_at,
                    )
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return False
        if row["resolved_at"] is None:
            with self.engine.connect() as c:
                run = (
                    c.execute(
                        select(tables.agent_runs).where(tables.agent_runs.c.id == row["run_id"])
                    )
                    .mappings()
                    .one()
                )
                known = (
                    c.execute(
                        select(tables.application_result_checkpoints.c.id).where(
                            tables.application_result_checkpoints.c.run_id == row["run_id"]
                        )
                    ).first()
                    is not None
                )
            resumable = (
                run["status"] == "queued"
                or run["status"] == "degraded"
                and run["error_code"] == "APPLICATION_RUN_LEASE_EXPIRED"
                and known
            )
            if resumable:
                try:
                    context = AuthRepository(self.engine).find_user_context(
                        run["requested_by_user_id"]
                    )
                    if context is None or context.tenant.id != row["tenant_id"]:
                        raise ImportError_("IMPORT_ACCESS_DENIED", "发起人不可用")
                    self.service._authorize_import(
                        tenant_id=row["tenant_id"],
                        actor_user_id=context.user.id,
                        project_id=row["project_id"],
                        auth_version=context.user.auth_version,
                    )
                    content = self.object_store.get(
                        object_key=row["object_key"], max_bytes=MAX_DOCUMENT_BYTES
                    )
                    if (
                        len(content) != row["byte_size"]
                        or hashlib.sha256(content).hexdigest() != row["content_sha256"]
                    ):
                        raise ImportError_("IMPORT_STAGED_FILE_CHANGED", "暂存文件已变化")
                    mapping = self.service._suggest_mapping(
                        queue_worker=True,
                        tenant_id=row["tenant_id"],
                        project_id=row["project_id"],
                        report=parse_workbook(content),
                        actor_user_id=context.user.id,
                        plan_id=row["plan_id"],
                        content_sha256=row["content_sha256"],
                        auth_version=context.user.auth_version,
                    )
                    self.service.start_import(
                        tenant_id=row["tenant_id"],
                        actor_user_id=context.user.id,
                        project_id=row["project_id"],
                        plan_id=row["plan_id"],
                        filename=row["filename"],
                        content=content,
                        auth_version=context.user.auth_version,
                        queued_run_id=row["run_id"],
                        queued_mapping=mapping,
                    )
                except Exception as error:
                    code = getattr(error, "code", "APPLICATION_IMPORT_EXECUTION_FAILED")
                    keeper = getattr(self.gateway, "application_lease_keeper", None)
                    acquired = (
                        isinstance(keeper, ApplicationLeaseKeeper)
                        and keeper.token(row["tenant_id"], row["run_id"]) is not None
                    )
                    with self.engine.begin() as c:
                        c.execute(
                            tables.agent_runs.update()
                            .where(
                                tables.agent_runs.c.id == row["run_id"],
                                or_(
                                    tables.agent_runs.c.status == "queued",
                                    recoverable if not acquired else false(),
                                ),
                            )
                            .values(
                                status="failed",
                                error_code=code,
                                completed_at=func.clock_timestamp(),
                                updated_at=func.clock_timestamp(),
                            )
                        )
                    logger.warning(
                        "application_import_stopped run=%s reason=%s", row["run_id"], code
                    )
            with self.engine.begin() as c:
                run = (
                    c.execute(
                        select(tables.agent_runs).where(tables.agent_runs.c.id == row["run_id"])
                    )
                    .mappings()
                    .one()
                )
                known = (
                    c.execute(
                        select(tables.application_result_checkpoints.c.id).where(
                            tables.application_result_checkpoints.c.run_id == row["run_id"]
                        )
                    ).first()
                    is not None
                )
                still_recoverable = (
                    run["status"] == "degraded"
                    and run["error_code"] == "APPLICATION_RUN_LEASE_EXPIRED"
                    and known
                )
                if run["status"] in {"failed", "degraded"} and not still_recoverable:
                    c.execute(
                        tables.application_import_inputs.update()
                        .where(
                            tables.application_import_inputs.c.id == row["id"],
                            tables.application_import_inputs.c.resolved_at.is_(None),
                        )
                        .values(
                            resolved_at=func.clock_timestamp(),
                            error_code=run["error_code"] or "APPLICATION_IMPORT_FAILED",
                        )
                    )
        with self.engine.connect() as c:
            resolved = c.execute(
                select(tables.application_import_inputs.c.resolved_at).where(
                    tables.application_import_inputs.c.id == row["id"]
                )
            ).scalar_one()
        if resolved is not None:
            try:
                self.object_store.delete(object_key=row["object_key"])
            except Exception:
                logger.warning("application_import_cleanup_pending run=%s", row["run_id"])
                return False
            with self.engine.begin() as c:
                c.execute(
                    tables.application_import_inputs.update()
                    .where(
                        tables.application_import_inputs.c.id == row["id"],
                        tables.application_import_inputs.c.released_at.is_(None),
                    )
                    .values(released_at=func.clock_timestamp())
                )
        return True
