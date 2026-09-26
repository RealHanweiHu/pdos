"""Original audit report and selected source files, retained as an internal ZIP."""

import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID, uuid4
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from sqlalchemy import Connection, Engine, or_, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain, _role, digest
from app.domain.project_report_exports import ProjectReportExportService
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.quality_operations import authorize
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft
from app.exports.project_report_sources import ReportScope, source
from app.storage.documents import DocumentObjectStore, ReadableDocumentObjectStore

VERSION = "internal-audit-bundle.v1"
MAX_INPUT = 50 * 1024 * 1024
MAX_ZIP = 52 * 1024 * 1024
MAX_FILE = 20 * 1024 * 1024


class BundlePreview(Contract):
    report_id: UUID


class BundleHistory(BundlePreview):
    before_id: UUID | None = None


class BundleSave(BundlePreview):
    request_id: UUID
    expected_digest: Digest
    reason: Text


def document_access(c: Connection, context: AuthContext, project: UUID) -> None:
    # Match the original-download permission, not just visibility of the file's metadata.
    _role(context, Action.DOCUMENT_ANALYZE)
    authorize(c, context, project, Action.PROJECT_VIEW)


def report(c: Connection, context: AuthContext, project: UUID, identity: UUID) -> Any:
    authorize(c, context, project, Action.QUALITY_VIEW)
    t = tables.project_report_exports
    row = (
        c.execute(
            select(*(col for col in t.c if col.name != "content")).where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project,
                t.c.id == identity,
                t.c.kind == "audit",
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("请选择本项目已生成的审核证据包")
    if ProjectReportExportService.withdrawal(c, context, identity):
        raise ProductWorkError("原证据包已撤回，停止生成和下载附件包")
    current = source(
        c,
        context,
        project,
        ReportScope.model_validate(row["scope"]),
        audit_template=row["template_version"],
    )
    if current["digest"] != row["source_digest"]:
        raise ProductWorkError("原签核、条款依据或有效期已变化，请重新组包")
    return row


def prepare(c: Connection, context: AuthContext, project: UUID, identity: UUID) -> dict[str, Any]:
    original = report(c, context, project, identity)
    scope = ReportScope.model_validate(original["scope"])
    identities = sorted(
        {v.id for clause in scope.audit_clauses for v in clause.evidence if v.kind == "document"},
        key=str,
    )
    if identities:
        document_access(c, context, project)
    t = tables.documents
    files = (
        c.execute(
            select(
                t.c.id,
                t.c.filename,
                t.c.sha256,
                t.c.size_bytes,
                t.c.media_type,
                t.c.classification,
                t.c.created_at,
            )
            .where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project,
                t.c.id.in_(identities),
            )
            .order_by(t.c.id)
        )
        .mappings()
        .all()
    )
    if len(files) != len(identities):
        raise ProductWorkError("所选原文件缺失，不生成不完整附件包")
    documents = []
    for row in files:
        if not 1 <= row["size_bytes"] <= MAX_FILE:
            raise ProductWorkError("原文件超出20MiB读取上限，请先调整报告范围")
        suffix = PurePosixPath(row["filename"]).suffix.lower()
        suffix = suffix if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix) else ".bin"
        documents.append({**_plain(row), "path": f"originals/{row['id']}{suffix}"})
    raw_size = original["byte_size"] + sum(v["size_bytes"] for v in documents)
    if raw_size > MAX_INPUT:
        raise ProductWorkError("报告与附件合计超过50MiB，请缩小条款范围；不会省略文件")
    body = {
        "template_version": VERSION,
        "audience": "internal",
        "project_id": str(project),
        "report": {
            "id": str(original["id"]),
            "path": f"report/{original['id']}.{original['format']}",
            "filename": original["filename"],
            "sha256": original["content_digest"],
            "size_bytes": original["byte_size"],
            "source_digest": original["source_digest"],
            "template_version": original["template_version"],
            "created_at": original["created_at"].isoformat(),
        },
        "documents": documents,
        "source_size_bytes": raw_size,
        "clause_links": [
            {
                "standard": clause.standard,
                "edition": clause.edition,
                "clause": clause.clause,
                "applicability": clause.applicability,
                "references": [v.model_dump(mode="json") for v in clause.evidence],
            }
            for clause in scope.audit_clauses
        ],
        "limitations": [
            "内部审阅包，包含完整原文件；引用位置并不裁切或脱敏原件，未获客户披露批准。",
            "仅加入条款明确选择的项目文件；Gate/ECN记录内间接引用的其他附件不自动加入。",
            "原报告、签核、缺项与适用性保留；本包不证明审核/认证通过或所有资料齐全。",
            "报告撤回或原依据变化后停止下载，已经下载的文件无法追回。",
        ],
    }
    return {**body, "digest": digest(body)}


def metadata(row: Any) -> dict[str, Any]:
    return _plain(
        {
            k: row[k]
            for k in (
                "id",
                "report_id",
                "filename",
                "byte_size",
                "content_digest",
                "manifest",
                "reason",
                "actor_user_id",
                "created_at",
            )
        }
    )


def zip_content(entries: list[tuple[str, bytes]]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_STORED, allowZip64=False) as archive:
        for name, content in entries:
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_STORED
            info.external_attr = 0o100600 << 16
            archive.writestr(info, content)
    data = output.getvalue()
    if len(data) > MAX_ZIP:
        raise ProductWorkError("完整组包超过52MiB容量；未保存截断附件")
    return data


class AuditReportBundleService:
    def __init__(self, engine: Engine, store: DocumentObjectStore | None = None):
        self.engine = engine
        self.store = store

    def preview(self, context: AuthContext, project: UUID, query: BundlePreview) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return prepare(c, context, project, query.report_id)

    def save(self, context: AuthContext, project: UUID, command: BundleSave) -> dict[str, Any]:
        signature = digest({"project": str(project), "command": command.model_dump(mode="json")})
        t = tables.audit_report_bundles
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            current = prepare(c, context, project, command.report_id)
            old = self.existing(c, context, project, command, signature)
            if old is not None:
                return old
            if current["digest"] != command.expected_digest:
                raise ProductWorkError("报告或原附件信息已变化，请重新预览")
            f = tables.project_report_exports
            report_bytes = bytes(
                c.execute(
                    select(f.c.content).where(
                        f.c.tenant_id == context.tenant.id,
                        f.c.project_id == project,
                        f.c.id == command.report_id,
                    )
                ).scalar_one()
            )
            self.check_bytes(report_bytes, current["report"])
            d = tables.documents
            keys = {
                str(v.id): v.object_key
                for v in c.execute(
                    select(d.c.id, d.c.object_key).where(
                        d.c.tenant_id == context.tenant.id,
                        d.c.project_id == project,
                        d.c.id.in_([UUID(v["id"]) for v in current["documents"]]),
                    )
                )
            }
        # Read original bytes outside the write lock; recheck the full basis before persisting.
        entries = [(current["report"]["path"], report_bytes)]
        if current["documents"] and not isinstance(self.store, ReadableDocumentObjectStore):
            raise ProductWorkError("原件存储暂不可读取，未生成附件包")
        for document in current["documents"]:
            assert isinstance(self.store, ReadableDocumentObjectStore)
            try:
                data = self.store.get(
                    object_key=keys[document["id"]], max_bytes=document["size_bytes"]
                )
            except Exception as error:
                raise ProductWorkError(
                    "所选原件读取失败，未保存不完整附件包；原请求可重试"
                ) from error
            self.check_bytes(data, document)
            entries.append((document["path"], data))
        identity, now = uuid4(), datetime.now(UTC)
        manifest = {
            **current,
            "bundle_id": str(identity),
            "generated_at": now.isoformat(),
            "generated_by_user_id": str(context.user.id),
            "reason": command.reason,
        }
        entries.append(
            ("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
        )
        readme = "审核证据包（内部审阅）\n\n" + "\n".join(current["limitations"])
        readme += (
            "\n\n文件清单与条款对应见 manifest.json。"
            "originals 下按原件编号命名，原文件名在清单中保留。\n"
        )
        entries.append(("README.txt", readme.encode("utf-8")))
        content = zip_content(entries)
        with self.engine.begin() as c:
            if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
                raise ProductWorkError("项目不可用")
            latest = prepare(c, context, project, command.report_id)
            old = self.existing(c, context, project, command, signature)
            if old is not None:
                return old
            if latest["digest"] != current["digest"]:
                raise ProductWorkError("读取附件期间原依据变化，未保存旧包；请重新核对")
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        tenant_id=context.tenant.id,
                        project_id=project,
                        report_id=command.report_id,
                        filename=f"audit-bundle-{identity}.zip",
                        byte_size=len(content),
                        content=content,
                        content_digest=sha256(content).hexdigest(),
                        manifest=manifest,
                        source_digest=current["digest"],
                        reason=command.reason,
                        actor_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=signature,
                        created_at=now,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            EventAuditWriter(
                c, tenant_id=context.tenant.id, project_id=project, actor_user_id=context.user.id
            ).record(
                EventDraft(
                    event_id=f"audit-bundle:{identity}",
                    event_type="AUDIT_REPORT_BUNDLED",
                    source="report_export_service",
                    entity_id=identity,
                    payload={
                        "record_id": str(identity),
                        "report_id": str(command.report_id),
                        "content_digest": row["content_digest"],
                    },
                ),
                AuditDraft(
                    action="audit_report.bundled",
                    after_snapshot={
                        "record_id": str(identity),
                        "report_id": str(command.report_id),
                        "content_digest": row["content_digest"],
                    },
                ),
            )
            return metadata(row)

    @staticmethod
    def check_bytes(data: bytes, item: dict[str, Any]) -> None:
        if len(data) != item["size_bytes"] or sha256(data).hexdigest() != item["sha256"]:
            raise ProductWorkError("原文件字节与登记回执不符，停止组包；请先核对原件")

    @staticmethod
    def existing(
        c: Connection, context: AuthContext, project: UUID, command: BundleSave, signature: str
    ) -> dict[str, Any] | None:
        t = tables.audit_report_bundles
        row = (
            c.execute(
                select(*(col for col in t.c if col.name != "content")).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.actor_user_id == context.user.id,
                    t.c.request_id == command.request_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        if row["request_digest"] != signature or row["project_id"] != project:
            raise ProductWorkError("同一组包请求不能改变范围或用途")
        return metadata(row)

    def history(self, context: AuthContext, project: UUID, query: BundleHistory) -> dict[str, Any]:
        with self.engine.connect() as c:
            authorize(c, context, project, Action.QUALITY_VIEW)
            t = tables.audit_report_bundles
            q = select(*(col for col in t.c if col.name != "content")).where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project,
                t.c.report_id == query.report_id,
            )
            if query.before_id:
                cursor = (
                    c.execute(
                        select(t.c.id, t.c.created_at).where(
                            t.c.tenant_id == context.tenant.id,
                            t.c.project_id == project,
                            t.c.report_id == query.report_id,
                            t.c.id == query.before_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if cursor is None:
                    raise ProductWorkError("组包历史游标不属于当前报告")
                q = q.where(
                    or_(
                        t.c.created_at < cursor["created_at"],
                        (t.c.created_at == cursor["created_at"]) & (t.c.id < cursor["id"]),
                    )
                )
            page = (
                c.execute(q.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21))
                .mappings()
                .all()
            )
            rows = page[:20]
            if any(v["manifest"]["documents"] for v in rows):
                document_access(c, context, project)
            # Source-specific roles still apply to historical manifests containing clause positions.
            from app.exports.audit_report_sources import source_access

            for kind in {
                ref["kind"]
                for r in rows
                for clause in r["manifest"]["clause_links"]
                for ref in clause["references"]
            }:
                source_access(c, context, project, kind)
            return {
                "items": [metadata(v) for v in rows],
                "next_before_id": str(rows[-1]["id"]) if len(page) > 20 else None,
                "withdrawal": ProjectReportExportService.withdrawal(c, context, query.report_id),
            }

    def download(self, context: AuthContext, project: UUID, identity: UUID) -> tuple[bytes, str]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            authorize(c, context, project, Action.QUALITY_VIEW)
            t = tables.audit_report_bundles
            row = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.project_id == project,
                        t.c.id == identity,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProductWorkError("原附件包不存在或不可读取")
            current = prepare(c, context, project, row["report_id"])
            if current["digest"] != row["source_digest"]:
                raise ProductWorkError("原来源或附件信息已变化，停止旧附件包下载")
            content = bytes(row["content"])
            self.check_bytes(
                content, {"size_bytes": row["byte_size"], "sha256": row["content_digest"]}
            )
            return content, row["filename"]
