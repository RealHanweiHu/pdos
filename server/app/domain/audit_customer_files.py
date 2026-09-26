"""Customer ZIP includes only the independently approved projection and file bytes."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.audit_customer_projection import VERSION, sections
from app.domain.audit_report_bundles import AuditReportBundleService, zip_content
from app.domain.customer_report_packages import PackageExport, approved, file_meta, record_event
from app.domain.product_workspace import ProductWorkError
from app.domain.project_write_lock import lock_project_write_scope
from app.exports.definition_documents import render_sections
from app.storage.documents import DocumentObjectStore, ReadableDocumentObjectStore


def export_zip(
    engine: Engine,
    store: DocumentObjectStore | None,
    context: AuthContext,
    project: UUID,
    command: PackageExport,
) -> dict[str, Any]:
    t = tables.customer_report_files
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        row, decision = approved(c, context, project, command.package_id, command.decision_id)
        projection = row["snapshot"]["projection"]
        if projection["template_version"] != VERSION:
            raise ProductWorkError("此入口只生成已核准的客户审核附件包")
        old = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.package_id == row["id"],
                    t.c.decision_id == decision["id"],
                    t.c.format == "zip",
                )
            )
            .mappings()
            .one_or_none()
        )
        if old:
            return file_meta(old)
        d = tables.documents
        keys = {
            str(v.id): v.object_key
            for v in c.execute(
                select(d.c.id, d.c.object_key).where(
                    d.c.tenant_id == context.tenant.id,
                    d.c.project_id == project,
                    d.c.id.in_([UUID(v["document_id"]) for v in row["draft"]["documents"]]),
                )
            )
        }
        documents = row["draft"]["documents"]
        source_digest = row["source_digest"]
        approval_at = decision["created_at"].isoformat()
    identity, now = uuid4(), datetime.now(UTC)
    pdf = render_sections(
        projection["title"],
        "已核准客户披露内容",
        sections(projection),
        "pdf",
        {
            "编号": str(identity),
            "内容批准时间": approval_at,
            "生成时间": now.isoformat(),
            "模板": VERSION,
        },
        audience="customer",
    )
    if len(pdf) > 12 * 1024 * 1024:
        raise ProductWorkError("客户正文超过12MiB，请缩小范围重新核准")
    entries = [("report.pdf", pdf)]
    if documents and not isinstance(store, ReadableDocumentObjectStore):
        raise ProductWorkError("原件存储暂不可读取，未生成客户附件包")
    for selected, public in zip(documents, projection["documents"], strict=True):
        assert isinstance(store, ReadableDocumentObjectStore)
        try:
            data = store.get(
                object_key=keys[selected["document_id"]], max_bytes=public["size_bytes"]
            )
        except Exception as error:
            raise ProductWorkError(
                "获准文件读取失败，未生成不完整客户附件包；可按原批准重试"
            ) from error
        AuditReportBundleService.check_bytes(data, public)
        entries.append((public["path"], data))
    manifest = {
        "template_version": VERSION,
        "title": projection["title"],
        "customer_name": projection["customer_name"],
        "approval_at": approval_at,
        "report": {"path": "report.pdf", "sha256": sha256(pdf).hexdigest(), "size_bytes": len(pdf)},
        "documents": projection["documents"],
        "interpretation": projection["interpretation"],
    }
    entries.append(
        ("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
    )
    content = zip_content(entries)
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
            raise ProductWorkError("项目不可用")
        row, decision = approved(c, context, project, command.package_id, command.decision_id)
        if row["source_digest"] != source_digest:
            raise ProductWorkError("读取文件期间获准内容已变化，请重新核准")
        old = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.package_id == row["id"],
                    t.c.decision_id == decision["id"],
                    t.c.format == "zip",
                )
            )
            .mappings()
            .one_or_none()
        )
        if old:
            return file_meta(old)
        saved = (
            c.execute(
                t.insert()
                .values(
                    id=identity,
                    tenant_id=context.tenant.id,
                    project_id=project,
                    package_id=row["id"],
                    decision_id=decision["id"],
                    format="zip",
                    filename=f"customer-audit-{identity}.zip",
                    mime_type="application/zip",
                    content=content,
                    byte_size=len(content),
                    content_digest=sha256(content).hexdigest(),
                    created_by_user_id=context.user.id,
                    created_at=now,
                )
                .returning(t)
            )
            .mappings()
            .one()
        )
        record_event(c, context, project, identity, "customer_audit_zip_created")
        return file_meta(saved)
