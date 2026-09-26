"""Internal project report generation and retained, permission-bound downloads."""

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Engine, func, select, tuple_

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain, _role, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.quality_operations import authorize
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft
from app.exports.audit_report_sources import AuditOptions
from app.exports.audit_report_sources import options as audit_options
from app.exports.definition_documents import MIMES, Format, render_sections
from app.exports.project_report_sources import Kind, ReportScope, access, source


class Options(Contract):
    kind: Kind
    search: str = Field(default="", max_length=128)
    before_id: UUID | None = None


class Preview(Contract):
    scope: ReportScope
    format: Format
    reason: Text


class Save(Preview):
    request_id: UUID
    expected_digest: Digest


class Withdraw(Contract):
    report_id: UUID
    request_id: UUID
    reason: Text


class History(Contract):
    kind: Kind
    before_id: UUID | None = None


def meta(row: Any) -> dict[str, Any]:
    return _plain(
        {
            key: row[key]
            for key in (
                "id",
                "kind",
                "scope",
                "format",
                "template_version",
                "filename",
                "mime_type",
                "byte_size",
                "content_digest",
                "source_digest",
                "reason",
                "actor_user_id",
                "created_at",
            )
        }
    )


def prepare(c: Any, context: AuthContext, project: UUID, command: Preview) -> dict[str, Any]:
    snapshot = source(c, context, project, command.scope)
    value = {"source": snapshot, "format": command.format, "reason": command.reason}
    return {**value, "digest": digest(value)}


class ProjectReportExportService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def options(self, context: AuthContext, project: UUID, query: Options) -> dict[str, Any]:
        with self.engine.connect() as c:
            access(c, context, project, query.kind)
            if query.kind in {"weekly", "audit"}:
                return {"items": [], "next_before_id": None}
            if query.kind == "dfmea":
                t = tables.fmea_versions
                latest = (
                    select(t.c.entry_id, func.max(t.c.version).label("version"))
                    .where(t.c.tenant_id == context.tenant.id, t.c.project_id == project)
                    .group_by(t.c.entry_id)
                    .subquery()
                )
                q = (
                    select(
                        t.c.entry_id.label("id"),
                        t.c.body["title"].as_string().label("title"),
                        t.c.version,
                    )
                    .join(
                        latest,
                        (latest.c.entry_id == t.c.entry_id) & (latest.c.version == t.c.version),
                    )
                    .where(t.c.tenant_id == context.tenant.id, t.c.project_id == project)
                )
                id_column = t.c.entry_id
                title = t.c.body["title"].as_string()
            else:
                t = tables.nonconformance_reports if query.kind == "8d" else tables.gates
                title = t.c.nonconformity if query.kind == "8d" else t.c.name
                q = select(t.c.id, title.label("title"), t.c.code, t.c.status).where(
                    t.c.tenant_id == context.tenant.id, t.c.project_id == project
                )
                id_column = t.c.id
            if query.search:
                q = q.where(title.icontains(query.search, autoescape=True))
            if query.before_id:
                q = q.where(id_column < query.before_id)
            values = c.execute(q.order_by(id_column.desc()).limit(21)).mappings().all()
            return {
                "items": [_plain(v) for v in values[:20]],
                "next_before_id": str(values[19]["id"]) if len(values) > 20 else None,
            }

    def audit_options(
        self, context: AuthContext, project: UUID, query: AuditOptions
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            return audit_options(c, context, project, query)

    @staticmethod
    def withdrawal(c: Any, context: AuthContext, report: UUID) -> dict[str, Any] | None:
        t = tables.project_report_withdrawals
        row = (
            c.execute(select(t).where(t.c.tenant_id == context.tenant.id, t.c.report_id == report))
            .mappings()
            .one_or_none()
        )
        return _plain(row) if row else None

    def withdraw(self, context: AuthContext, project: UUID, command: Withdraw) -> dict[str, Any]:
        with self.engine.begin() as c:
            authorize(c, context, project, Action.QUALITY_MANAGE)
            if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
                raise ProductWorkError("项目不可用")
            signature = digest(
                {"project": str(project), "command": command.model_dump(mode="json")}
            )
            t = tables.project_report_withdrawals
            old = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.actor_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old:
                if old["request_digest"] != signature:
                    raise ProductWorkError("原请求不能改变撤回对象或原因")
                return _plain(old)
            f = tables.project_report_exports
            report = (
                c.execute(
                    select(f.c.id, f.c.kind).where(
                        f.c.tenant_id == context.tenant.id,
                        f.c.project_id == project,
                        f.c.id == command.report_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if report is None or report["kind"] != "audit":
                raise ProductWorkError("请选择本项目审核证据包")
            previous = self.withdrawal(c, context, command.report_id)
            if previous:
                raise ProductWorkError("该证据包已撤回，请刷新历史")
            identity = uuid4()
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        tenant_id=context.tenant.id,
                        project_id=project,
                        report_id=command.report_id,
                        actor_user_id=context.user.id,
                        reason=command.reason,
                        request_id=command.request_id,
                        request_digest=signature,
                        created_at=datetime.now(UTC),
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            EventAuditWriter(
                c, tenant_id=context.tenant.id, actor_user_id=context.user.id, project_id=project
            ).record(
                EventDraft(
                    event_id=f"report-withdrawal:{identity}",
                    event_type="PROJECT_REPORT_WITHDRAWN",
                    source="report_export_service",
                    entity_id=command.report_id,
                    payload={"record_id": str(identity), "report_id": str(command.report_id)},
                ),
                AuditDraft(
                    action="project_report.withdrawn",
                    after_snapshot={
                        "record_id": str(identity),
                        "report_id": str(command.report_id),
                    },
                ),
            )
            return _plain(row)

    def preview(self, context: AuthContext, project: UUID, command: Preview) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return prepare(c, context, project, command)

    def save(self, context: AuthContext, project: UUID, command: Save) -> dict[str, Any]:
        with self.engine.begin() as c:
            access(c, context, project, command.scope.kind)
            if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
                raise ProductWorkError("原项目不可用")
            t = tables.project_report_exports
            signature = digest(
                {"project": str(project), "command": command.model_dump(mode="json")}
            )
            old = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.actor_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old:
                if old["request_digest"] != signature:
                    raise ProductWorkError("同一请求不能改变报表范围或内容")
                return meta(old)
            current = prepare(c, context, project, command)
            if current["digest"] != command.expected_digest:
                raise ProductWorkError("原记录或依据已变化，请重新预览后生成")
            identity = uuid4()
            now = datetime.now(UTC)
            snapshot = current["source"]
            receipt = {
                "编号": str(identity),
                "生成时点": now.isoformat(),
                "记录人": context.user.display_name + f"（{context.user.id}）",
                "来源摘要": snapshot["digest"],
                "用途": command.reason,
            }
            content = render_sections(
                snapshot["title"],
                snapshot["status_label"],
                [(v["title"], v["text"]) for v in snapshot["sections"]],
                command.format,
                receipt,
            )
            if len(content) > 12 * 1024 * 1024:
                raise ProductWorkError("文件超过12MB组包容量，请缩小范围；未保存截断内容")
            record = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        tenant_id=context.tenant.id,
                        project_id=project,
                        kind=command.scope.kind,
                        scope=command.scope.model_dump(mode="json"),
                        ncr_id=command.scope.object_id if command.scope.kind == "8d" else None,
                        gate_id=command.scope.object_id if command.scope.kind == "gate" else None,
                        format=command.format,
                        template_version=snapshot["template_version"],
                        filename=f"{command.scope.kind}-{identity}.{command.format}",
                        mime_type=MIMES[command.format],
                        byte_size=len(content),
                        content=content,
                        content_digest=sha256(content).hexdigest(),
                        snapshot=snapshot,
                        source_digest=snapshot["digest"],
                        preview_digest=current["digest"],
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
            if command.scope.kind == "audit":
                refs = tables.project_report_sources
                for ref in snapshot["actual"]["sources"]:
                    c.execute(
                        refs.insert().values(
                            id=uuid4(),
                            tenant_id=context.tenant.id,
                            project_id=project,
                            report_id=identity,
                            kind=ref["kind"],
                            source_id=UUID(ref["id"]),
                            **{ref["kind"] + "_id": UUID(ref["id"])},
                        )
                    )
            EventAuditWriter(
                c, tenant_id=context.tenant.id, actor_user_id=context.user.id, project_id=project
            ).record(
                EventDraft(
                    event_id=f"project-report:{identity}",
                    event_type="PROJECT_REPORT_EXPORTED",
                    source="report_export_service",
                    entity_id=identity,
                    payload={
                        "record_id": str(identity),
                        "kind": command.scope.kind,
                        "format": command.format,
                        "content_digest": record["content_digest"],
                    },
                ),
                AuditDraft(
                    action="project_report.exported",
                    after_snapshot={
                        "record_id": str(identity),
                        "kind": command.scope.kind,
                        "content_digest": record["content_digest"],
                    },
                ),
            )
            return meta(record)

    def history(self, context: AuthContext, project: UUID, query: History) -> dict[str, Any]:
        with self.engine.connect() as c:
            access(c, context, project, query.kind)
            t = tables.project_report_exports
            q = select(*(col for col in t.c if col.name not in {"content", "snapshot"})).where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project,
                t.c.kind == query.kind,
            )
            if query.before_id:
                cursor = c.execute(
                    select(t.c.created_at, t.c.id).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.project_id == project,
                        t.c.kind == query.kind,
                        t.c.id == query.before_id,
                    )
                ).one_or_none()
                if cursor is None:
                    raise ProductWorkError("历史位置不可用，请重新读取生成历史")
                q = q.where(tuple_(t.c.created_at, t.c.id) < tuple_(cursor.created_at, cursor.id))
            values = (
                c.execute(q.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21))
                .mappings()
                .all()
            )
            return {
                "items": [
                    {**meta(v), "withdrawal": self.withdrawal(c, context, v["id"])}
                    for v in values[:20]
                ],
                "next_before_id": str(values[19]["id"]) if len(values) > 20 else None,
            }

    def download(
        self, context: AuthContext, project: UUID, identity: UUID
    ) -> tuple[bytes, str, str]:
        with self.engine.connect() as c:
            t = tables.project_report_exports
            record = (
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
            if record is None:
                raise ProductWorkError("报表不存在或不可读取")
            access(c, context, project, record["kind"])
            if self.withdrawal(c, context, identity):
                raise ProductWorkError("该证据包已具名撤回，停止下载；原记录保留")
            if record["kind"] == "audit":
                current = source(
                    c,
                    context,
                    project,
                    ReportScope.model_validate(record["scope"]),
                    audit_template=record["template_version"],
                )
                if current["digest"] != record["source_digest"]:
                    raise ProductWorkError("签核、依据或有效期已变化，停止旧版下载；请重新组包核对")
            if record["kind"] == "gate" and "condition_tasks" in record["snapshot"].get(
                "actual", {}
            ):
                authorize(c, context, project, Action.WORK_ITEM_VIEW)
            # The 8D projection can contain shared evidence metadata governed by a separate role.
            if record["kind"] == "8d":
                for ref in record["snapshot"]["actual"]["evidence"]:
                    if ref["kind"] == "evidence_snapshot":
                        _role(context, Action.EVIDENCE_VIEW)
                        s = tables.research_sources
                        e = tables.evidence_snapshots
                        active = c.execute(
                            select(s.c.id)
                            .join(e, (e.c.tenant_id == s.c.tenant_id) & (e.c.source_id == s.c.id))
                            .where(
                                e.c.tenant_id == context.tenant.id,
                                e.c.id == UUID(ref["reference"]),
                                s.c.status == "active",
                            )
                        ).first()
                        if active is None:
                            raise ProductWorkError("原共享来源已停用，不提供含原引用资料的文件")
            content = bytes(record["content"])
            if (
                len(content) != record["byte_size"]
                or sha256(content).hexdigest() != record["content_digest"]
            ):
                raise ProductWorkError("文件与生成回执不一致，停止下载")
            return content, record["mime_type"], record["filename"]
