"""Explicit private-message to shared test-report import receipts."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import Connection, Engine, func, select

from app.ai.application_gateway import ApplicationModelGateway
from app.ai.report_import_queue import ReportImportQueue
from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.conversation_attachments import (
    ConversationAttachmentService,
    message_attachment_ids,
)
from app.domain.conversations import ConversationError, ConversationService
from app.domain.documents import MAX_DOCUMENT_BYTES
from app.domain.product_workspace import _plain, digest
from app.domain.test_import_preview import authorize_preview, get_preview
from app.domain.test_report_import import TestReportImportService
from app.domain.test_report_workbook import ImportError_
from app.storage.documents import DocumentObjectStore, ReadableDocumentObjectStore


class ConversationReportImports:
    def __init__(
        self,
        engine: Engine,
        *,
        object_store: DocumentObjectStore | None = None,
        gateway: ApplicationModelGateway | None = None,
    ):
        self.engine, self.object_store, self.gateway = engine, object_store, gateway

    def _operation(
        self, c: Connection, context: AuthContext, conversation_id: UUID, operation_id: UUID
    ) -> Any:
        conv = ConversationService(self.engine)._conversation(c, context, conversation_id)
        authorize_preview(self.engine, context, conv["project_id"])
        row = (
            c.execute(
                select(tables.conversation_report_imports).where(
                    tables.conversation_report_imports.c.tenant_id == context.tenant.id,
                    tables.conversation_report_imports.c.conversation_id == conversation_id,
                    tables.conversation_report_imports.c.created_by_user_id == context.user.id,
                    tables.conversation_report_imports.c.id == operation_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ConversationError("此报告办理不属于当前会话")
        return row

    def create(
        self,
        *,
        context: AuthContext,
        conversation_id: UUID,
        message_id: UUID,
        attachment_id: UUID,
        plan_id: UUID,
        request_id: UUID,
        publish_to_project: bool,
    ) -> dict[str, Any]:
        if not publish_to_project:
            raise ConversationError("导入会把报告原件登记为项目证据，请先明确此用途")
        with self.engine.begin() as c:
            conv = ConversationService(self.engine)._conversation(
                c, context, conversation_id, lock=True
            )
            TestReportImportService(self.engine, object_store=None, gateway=None)._authorize_import(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=conv["project_id"],
                auth_version=context.user.auth_version,
            )
            signature = digest(
                dict(
                    message_id=str(message_id),
                    attachment_id=str(attachment_id),
                    plan_id=str(plan_id),
                    publish_to_project=True,
                )
            )
            existing = (
                c.execute(
                    select(tables.conversation_report_imports).where(
                        tables.conversation_report_imports.c.tenant_id == context.tenant.id,
                        tables.conversation_report_imports.c.conversation_id == conversation_id,
                        tables.conversation_report_imports.c.request_id == request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                if existing["request_digest"] != signature:
                    raise ConversationError("此办理请求已用于不同附件或计划")
                operation_id = existing["id"]
            else:
                if conv["archived_at"] is not None:
                    raise ConversationError("会话已归档，请先恢复")
                message = c.execute(
                    select(tables.conversation_messages.c.id).where(
                        tables.conversation_messages.c.tenant_id == context.tenant.id,
                        tables.conversation_messages.c.conversation_id == conversation_id,
                        tables.conversation_messages.c.id == message_id,
                    )
                ).scalar_one_or_none()
                if message is None or attachment_id not in message_attachment_ids(
                    c, context.tenant.id, message_id
                ):
                    raise ConversationError("请从这条消息已保存的附件开始办理")
                attachment = ConversationAttachmentService._row(
                    c, context.tenant.id, conversation_id, attachment_id
                )
                self._check_source(attachment)
                plan = c.execute(
                    select(tables.test_plans.c.id).where(
                        tables.test_plans.c.tenant_id == context.tenant.id,
                        tables.test_plans.c.project_id == conv["project_id"],
                        tables.test_plans.c.id == plan_id,
                    )
                ).scalar_one_or_none()
                if plan is None:
                    raise ConversationError("所选测试计划不属于当前项目")
                operation_id = uuid5(conversation_id, "report-import:" + str(request_id))
                key = hashlib.sha256(
                    json.dumps(
                        dict(
                            actor_user_id=str(context.user.id),
                            plan_id=str(plan_id),
                            file_sha256=attachment["sha256"],
                        ),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                c.execute(
                    tables.conversation_report_imports.insert().values(
                        id=operation_id,
                        tenant_id=context.tenant.id,
                        project_id=conv["project_id"],
                        conversation_id=conversation_id,
                        message_id=message_id,
                        attachment_id=attachment_id,
                        plan_id=plan_id,
                        created_by_user_id=context.user.id,
                        request_id=request_id,
                        request_digest=signature,
                        source_sha256=attachment["sha256"],
                        mapping_request_id="report-mapping.v1:" + key,
                    )
                )
        return self.prepare(
            context=context, conversation_id=conversation_id, operation_id=operation_id
        )

    @staticmethod
    def _check_source(row: Any) -> None:
        if (
            row["revoked_at"] is not None
            or row["classification"] != "internal"
            or row["status"] != "extracted"
            or not row["filename"].lower().endswith(".xlsx")
        ):
            raise ConversationError(
                "报告导入目前使用已抽取的内部XLSX；PDF仍可阅读，正式录入请提供适用表格"
            )

    def _receipt(self, c: Connection, context: AuthContext, row: Any) -> dict[str, Any]:
        # Reconcile uncertain HTTP receipts against the actual existing import identities.
        batch = (
            c.execute(
                select(tables.test_report_import_batches)
                .join(
                    tables.documents,
                    (tables.documents.c.tenant_id == tables.test_report_import_batches.c.tenant_id)
                    & (tables.documents.c.id == tables.test_report_import_batches.c.document_id),
                )
                .where(
                    tables.test_report_import_batches.c.tenant_id == context.tenant.id,
                    tables.test_report_import_batches.c.project_id == row["project_id"],
                    tables.test_report_import_batches.c.plan_id == row["plan_id"],
                    *(
                        [
                            tables.test_report_import_batches.c.status.in_(["parsed", "confirmed"]),
                            tables.test_report_import_batches.c.superseded_by_batch_id.is_(None),
                        ]
                        if row["batch_id"] is None
                        else []
                    ),
                    tables.documents.c.project_id == row["project_id"],
                    tables.documents.c.sha256 == row["source_sha256"],
                    *(
                        [tables.test_report_import_batches.c.id == row["batch_id"]]
                        if row["batch_id"]
                        else []
                    ),
                )
                .order_by(
                    (tables.test_report_import_batches.c.status == "confirmed").desc(),
                    tables.test_report_import_batches.c.created_at,
                    tables.test_report_import_batches.c.id,
                )
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        run = (
            c.execute(
                select(tables.agent_runs).where(
                    tables.agent_runs.c.tenant_id == context.tenant.id,
                    tables.agent_runs.c.project_id == row["project_id"],
                    tables.agent_runs.c.requested_by_user_id == context.user.id,
                    tables.agent_runs.c.context_version == "report-mapping-request-v1",
                    tables.agent_runs.c.request_id == row["mapping_request_id"],
                )
            )
            .mappings()
            .one_or_none()
        )
        if run is not None:
            source = run["run_context"].get("mapping_request", {})
            if source.get("file_sha256") != row["source_sha256"] or source.get("plan_id") != str(
                row["plan_id"]
            ):
                raise ConversationError("原运行与选定报告或计划不一致")
        staged_error = (
            c.execute(
                select(tables.application_import_inputs.c.error_code).where(
                    tables.application_import_inputs.c.tenant_id == context.tenant.id,
                    tables.application_import_inputs.c.run_id == run["id"],
                )
            ).scalar_one_or_none()
            if run is not None
            else None
        )
        error_code = (
            staged_error or (run["error_code"] if run is not None else None) or row["error_code"]
        )
        return _plain(
            dict(
                id=row["id"],
                message_id=row["message_id"],
                attachment_id=row["attachment_id"],
                project_id=row["project_id"],
                plan_id=row["plan_id"],
                run_id=run["id"] if run is not None else None,
                batch_id=batch["id"] if batch is not None else None,
                status=batch["status"]
                if batch is not None
                else "cancelled"
                if error_code == "APPLICATION_REQUEST_CANCELLED"
                else "failed"
                if staged_error
                else run["status"]
                if run is not None
                else "failed"
                if error_code
                else "pending",
                error_code=None if batch is not None else error_code,
                reused_existing=row["reused_existing"],
                created_at=row["created_at"],
            )
        )

    def get(
        self, *, context: AuthContext, conversation_id: UUID, operation_id: UUID
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            row = self._operation(c, context, conversation_id, operation_id)
            result = self._receipt(c, context, row)
        if result["batch_id"] is not None:
            result["preview"] = get_preview(
                self.engine,
                context=context,
                project_id=UUID(result["project_id"]),
                batch_id=UUID(result["batch_id"]),
            )
        return result

    def list(
        self, *, context: AuthContext, conversation_id: UUID, message_id: UUID
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            conv = ConversationService(self.engine)._conversation(c, context, conversation_id)
            authorize_preview(self.engine, context, conv["project_id"])
            rows = c.execute(
                select(tables.conversation_report_imports)
                .where(
                    tables.conversation_report_imports.c.tenant_id == context.tenant.id,
                    tables.conversation_report_imports.c.conversation_id == conversation_id,
                    tables.conversation_report_imports.c.message_id == message_id,
                )
                .order_by(tables.conversation_report_imports.c.created_at)
            ).mappings()
            items = [self._receipt(c, context, row) for row in rows]
            plans = [
                _plain(dict(p))
                for p in c.execute(
                    select(
                        tables.test_plans.c.id,
                        tables.test_plans.c.title,
                        tables.test_plans.c.phase,
                        tables.test_plans.c.status,
                    )
                    .where(
                        tables.test_plans.c.tenant_id == context.tenant.id,
                        tables.test_plans.c.project_id == conv["project_id"],
                    )
                    .order_by(tables.test_plans.c.created_at.desc())
                ).mappings()
            ]
            return {"items": items, "plans": plans}

    def prepare(
        self, *, context: AuthContext, conversation_id: UUID, operation_id: UUID
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            row = self._operation(c, context, conversation_id, operation_id)
            receipt = self._receipt(c, context, row)
            if receipt["batch_id"] is not None:
                return self.get(
                    context=context, conversation_id=conversation_id, operation_id=operation_id
                )
            conv = ConversationService(self.engine)._conversation(c, context, conversation_id)
            if conv["archived_at"] is not None:
                raise ConversationError("已归档会话不能继续导入")
            source = ConversationAttachmentService._row(
                c, context.tenant.id, conversation_id, row["attachment_id"]
            )
            self._check_source(source)
        try:
            if (
                not isinstance(self.object_store, ReadableDocumentObjectStore)
                or self.gateway is None
            ):
                raise ConversationError("导入处理服务暂不可用，原请求已保存")
            content = self.object_store.get(
                object_key=source["object_key"], max_bytes=MAX_DOCUMENT_BYTES
            )
            if (
                len(content) != source["size_bytes"]
                or hashlib.sha256(content).hexdigest() != row["source_sha256"]
            ):
                raise ConversationError("原件与已登记摘要不一致")
            result = ReportImportQueue(
                self.engine, object_store=self.object_store, gateway=self.gateway
            ).submit(
                context=context,
                project_id=row["project_id"],
                plan_id=row["plan_id"],
                filename=source["filename"],
                content=content,
            )
            batch = result.get("batch")
            with self.engine.begin() as c:
                current = self._operation(c, context, conversation_id, operation_id)
                c.execute(
                    tables.conversation_report_imports.update()
                    .where(tables.conversation_report_imports.c.id == operation_id)
                    .values(
                        run_id=UUID(str(result["run_id"]))
                        if result.get("run_id")
                        else current["run_id"],
                        batch_id=UUID(str(batch["id"])) if batch else current["batch_id"],
                        reused_existing=batch.get("reused_existing")
                        if batch
                        else current["reused_existing"],
                        error_code=None,
                        updated_at=func.clock_timestamp(),
                    )
                )
        except Exception as error:
            with self.engine.begin() as c:
                c.execute(
                    tables.conversation_report_imports.update()
                    .where(tables.conversation_report_imports.c.id == operation_id)
                    .values(
                        error_code=error.code
                        if isinstance(error, ImportError_)
                        else "CONVERSATION_IMPORT_INCOMPLETE",
                        updated_at=func.clock_timestamp(),
                    )
                )
            raise
        return self.get(context=context, conversation_id=conversation_id, operation_id=operation_id)
