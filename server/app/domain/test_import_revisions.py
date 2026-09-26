"""Human mapping revisions reparse original bytes into separate linked drafts."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.documents import DocumentRecord
from app.domain.product_workspace import digest
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.test_import_preview import get_preview, preview_in_connection
from app.domain.test_report_import import (
    ExcelImportMapping,
    ImportRevision,
    TestReportImportService,
)
from app.domain.test_report_workbook import ImportError_, ParsedWorkbook, parse_workbook
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft
from app.storage.documents import DocumentObjectStore, ReadableDocumentObjectStore


class TestImportRevisions:
    def __init__(self, engine: Engine, object_store: DocumentObjectStore | None) -> None:
        self.engine, self.object_store = engine, object_store
        self.service = TestReportImportService(engine, object_store=None, gateway=None)

    def _authorize(self, context: AuthContext, project_id: UUID) -> None:
        self.service._authorize_import(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            auth_version=context.user.auth_version,
        )

    def _source(self, c: Connection, context: AuthContext, project_id: UUID, batch_id: UUID) -> Any:
        t, d = tables.test_report_import_batches, tables.documents
        batch = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.project_id == project_id,
                    t.c.id == batch_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if batch is None:
            raise ImportError_("IMPORT_BATCH_NOT_FOUND", "批次不存在")
        document = (
            c.execute(
                select(d).where(
                    d.c.tenant_id == context.tenant.id,
                    d.c.project_id == project_id,
                    d.c.id == batch["document_id"],
                )
            )
            .mappings()
            .one_or_none()
        )
        if document is None or document["classification"] != "internal":
            raise ImportError_("IMPORT_SOURCE_UNAVAILABLE", "原始项目报告当前不可用于重解析")
        return document

    def _bytes(self, document: Any) -> bytes:
        if not isinstance(self.object_store, ReadableDocumentObjectStore):
            raise ImportError_("IMPORT_SOURCE_UNAVAILABLE", "原始报告存储暂不可读")
        try:
            content = self.object_store.get(
                object_key=document["object_key"], max_bytes=20 * 1024 * 1024
            )
        except Exception as error:
            raise ImportError_(
                "IMPORT_SOURCE_UNAVAILABLE", "原始报告读取失败，请稍后重试同一请求"
            ) from error
        if (
            len(content) != document["size_bytes"]
            or hashlib.sha256(content).hexdigest() != document["sha256"]
        ):
            raise ImportError_("IMPORT_SOURCE_UNAVAILABLE", "原始报告字节与登记摘要不一致")
        return content

    def options(self, *, context: AuthContext, project_id: UUID, batch_id: UUID) -> dict[str, Any]:
        self._authorize(context, project_id)
        with self.engine.connect() as c:
            document = self._source(c, context, project_id, batch_id)
        report = parse_workbook(self._bytes(document))
        self._authorize(context, project_id)
        preview = get_preview(
            self.engine, context=context, project_id=project_id, batch_id=batch_id
        )
        return dict(
            headers=report.headers,
            layout=report.layout,
            mapping=preview["mapping"],
            digest=preview["digest"],
            can_reparse=preview["can_reparse"] and report.layout == "flat_v1",
            notice=None
            if report.layout == "flat_v1"
            else "此报告使用固定表单适配器，不能通过列映射修改表单结构",
        )

    @staticmethod
    def _mapping(mapping: ExcelImportMapping, report: ParsedWorkbook) -> ExcelImportMapping:
        if report.layout != "flat_v1":
            raise ImportError_("IMPORT_REMAP_INVALID", "此报告不使用可编辑列映射")
        columns = [
            v for k, v in mapping.model_dump().items() if k.endswith("_column") and v is not None
        ]
        columns.extend(metric.column for metric in mapping.metric_columns)
        passed = {v.strip().lower() for v in mapping.pass_values}
        failed = {v.strip().lower() for v in mapping.fail_values}
        if (
            len(set(report.headers)) != len(report.headers)
            or any(v not in report.headers for v in columns)
            or mapping.case_title_column == mapping.result_column
            or not passed
            or not failed
            or "" in passed | failed
            or passed & failed
            or len({m.name.strip() for m in mapping.metric_columns}) != len(mapping.metric_columns)
            or any(not m.name.strip() for m in mapping.metric_columns)
        ):
            raise ImportError_(
                "IMPORT_REMAP_INVALID",
                "请使用原报告已有列，填写不冲突的通过/失败原值及不重复的指标名称",
            )
        return mapping.model_copy(
            update={
                "confidence": 1.0,
                "unmapped_headers": [h for h in report.headers if h not in columns][:50],
            }
        )

    def reparse(
        self,
        *,
        context: AuthContext,
        project_id: UUID,
        batch_id: UUID,
        request_id: UUID,
        expected_digest: str,
        mapping: ExcelImportMapping,
        reason: str,
    ) -> dict[str, Any]:
        self._authorize(context, project_id)
        if not 1 <= len(reason.strip()) <= 2000:
            raise ImportError_("IMPORT_REMAP_INVALID", "请填写映射修正依据")
        request_digest = digest(
            dict(
                actor=str(context.user.id),
                parent=str(batch_id),
                expected_digest=expected_digest,
                mapping=mapping.model_dump(mode="json"),
                reason=reason.strip(),
            )
        )
        t = tables.test_report_import_batches

        def replay(c: Connection) -> UUID | None:
            previous = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.project_id == project_id,
                        t.c.parent_batch_id == batch_id,
                        t.c.remap_request_id == request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if previous is None:
                return None
            if previous["remap_request_digest"] != request_digest:
                raise ImportError_(
                    "IMPORT_REMAP_CONFLICT", "同一修订请求内容已不同，请重新核对后发起新请求"
                )
            return UUID(str(previous["id"]))

        with self.engine.connect() as c:
            existing_id = replay(c)
            document = (
                self._source(c, context, project_id, batch_id) if existing_id is None else None
            )
        if existing_id is not None:
            return get_preview(
                self.engine, context=context, project_id=project_id, batch_id=existing_id
            )
        if document is None:
            raise ImportError_("IMPORT_SOURCE_UNAVAILABLE", "原始报告登记不存在")
        content = self._bytes(document)
        corrected = self._mapping(mapping, parse_workbook(content))
        with self.engine.begin() as c:
            if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project_id):
                raise ImportError_("IMPORT_PROJECT_NOT_FOUND", "项目不可用")
            self._authorize(context, project_id)
            existing_id = replay(c)
            if existing_id is None:
                preview = preview_in_connection(
                    c, tenant_id=context.tenant.id, project_id=project_id, batch_id=batch_id
                )
                if not preview["can_reparse"]:
                    raise ImportError_(
                        "IMPORT_BATCH_NOT_PENDING", "原批次已确认或已有后续版本，请打开当前回执"
                    )
                if preview["digest"] != expected_digest:
                    raise ImportError_(
                        "IMPORT_PREVIEW_CHANGED", "原批次或目标资料已变化，请刷新后重新核对"
                    )
                current = self._source(c, context, project_id, batch_id)
                if any(
                    current[k] != document[k] for k in ("id", "object_key", "sha256", "size_bytes")
                ):
                    raise ImportError_("IMPORT_SOURCE_UNAVAILABLE", "原报告登记已变化")
                plan = (
                    c.execute(
                        select(tables.test_plans).where(
                            tables.test_plans.c.tenant_id == context.tenant.id,
                            tables.test_plans.c.project_id == project_id,
                            tables.test_plans.c.id == UUID(preview["plan"]["id"]),
                        )
                    )
                    .mappings()
                    .one()
                )
                result = self.service._parse_import(
                    c,
                    tenant_id=context.tenant.id,
                    actor_user_id=context.user.id,
                    project_id=project_id,
                    plan_id=plan["id"],
                    plan=plan,
                    document=DocumentRecord(
                        **{
                            k: current[k]
                            for k in (
                                "id",
                                "project_id",
                                "filename",
                                "media_type",
                                "classification",
                                "size_bytes",
                                "sha256",
                                "extraction_status",
                                "created_at",
                            )
                        },
                        fragments=(),
                    ),
                    content=content,
                    prepared_mapping=None,
                    corrected_mapping=corrected,
                    revision=ImportRevision(batch_id, request_id, request_digest, reason.strip()),
                )
                existing_id = result.id
                now = datetime.now(UTC)
                c.execute(
                    t.update()
                    .where(t.c.tenant_id == context.tenant.id, t.c.id == batch_id)
                    .values(superseded_by_batch_id=existing_id, updated_at=now)
                )
                EventAuditWriter(
                    c,
                    tenant_id=context.tenant.id,
                    actor_user_id=context.user.id,
                    project_id=project_id,
                ).record(
                    EventDraft(
                        event_id=f"test-import:{batch_id}:reparse:{uuid4()}",
                        event_type="NPI_RECORD_CHANGED",
                        source="npi_service",
                        entity_id=existing_id,
                        payload={
                            "record_type": "test_report_import",
                            "action": "mapping_reparsed",
                        },
                        occurred_at=now,
                    ),
                    AuditDraft(
                        action="test_report_import.reparse",
                        before_snapshot={"batch_id": str(batch_id), "mapping": preview["mapping"]},
                        after_snapshot={
                            "batch_id": str(existing_id),
                            "mapping": corrected.model_dump(mode="json"),
                            "reason": reason.strip(),
                        },
                    ),
                )
        return get_preview(
            self.engine, context=context, project_id=project_id, batch_id=existing_id
        )


def comparison(
    engine: Engine, *, context: AuthContext, project_id: UUID, batch_id: UUID
) -> dict[str, Any]:
    current = get_preview(engine, context=context, project_id=project_id, batch_id=batch_id)
    parent_id = current["batch"]["parent_batch_id"]
    if parent_id is None:
        return dict(parent_batch_id=None, items=[], counts={})
    parent = get_preview(engine, context=context, project_id=project_id, batch_id=UUID(parent_id))

    def keyed(preview: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        entries: dict[str, list[dict[str, Any]]] = {}
        for item in preview["items"]:
            run, source = item["run"], item["source"]
            configuration = item["configuration_revision"]
            key = f"{source.get('sheet', '未知表')}:{source.get('row', '未知行')}"
            entries.setdefault(key, []).append(
                dict(
                    kind="run",
                    case_title=item["case"]["title"] if item["case"] else None,
                    sample_serial=item["sample"]["serial_number"] if item["sample"] else None,
                    **{
                        k: run[k]
                        for k in (
                            "test_case_id",
                            "sample_id",
                            "status",
                            "metrics",
                            "result_notes",
                            "executed_at",
                            "execution_time_source",
                            "execution_time_precision",
                        )
                    },
                    configuration=configuration["snapshot"] if configuration else None,
                )
            )
        for skip in preview["skipped_rows"]:
            source = skip.get("source") or skip
            key = f"{source.get('sheet', '未知表')}:{source.get('row', '整表')}"
            entries.setdefault(key, []).append(
                dict(kind="skipped", reason=skip["reason"], value=skip.get("value"))
            )
        return entries

    before, after = keyed(parent), keyed(current)
    counts = dict(added=0, removed=0, changed=0, unchanged=0)
    items = []
    for key in sorted(before.keys() | after.keys()):
        left, right = before.get(key, []), after.get(key, [])
        kind = (
            "added"
            if not left
            else "removed"
            if not right
            else "unchanged"
            if left == right
            else "changed"
        )
        counts[kind] += 1
        items.append(dict(source=key, change=kind, before=left, after=right))
    return dict(
        parent_batch_id=parent_id,
        batch_id=str(batch_id),
        items=items,
        counts=counts,
        notice="按原工作表和行位置比较；新版本重新提取原值，旧版人工补录时间不自动沿用，请重新核对。",
    )
