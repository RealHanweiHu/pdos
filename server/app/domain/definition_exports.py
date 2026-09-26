"""Internal-only definition exports with immutable bytes and source receipts."""

from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, SourceRef, Text
from app.db.schema import tables
from app.domain.product_definitions import _release, _row
from app.domain.product_evidence import evidence_quality
from app.domain.product_workspace import ProductWorkError, _emit, _plain, _sources, _space, digest
from app.exports.definition_documents import MIMES, VERSION, Format, render, sections


class ExportOptions(Contract):
    search: str = Field(default="", max_length=128)
    before_id: UUID | None = None


class ExportPreview(Contract):
    definition_id: UUID
    format: Format
    reason: Text


class ExportSave(ExportPreview):
    request_id: UUID
    expected_digest: Digest


class ExportHistory(Contract):
    definition_id: UUID
    before_id: UUID | None = None


def references(content: Any) -> tuple[SourceRef, ...]:
    refs: dict[str, SourceRef] = {}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "sources" and isinstance(child, list):
                    for raw in child:
                        ref = SourceRef.model_validate(raw)
                        refs[digest(ref.model_dump(mode="json"))] = ref
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(content)
    return tuple(refs.values())


def source(c: Connection, context: AuthContext, space: UUID, identity: UUID) -> dict[str, Any]:
    _space(c, context, space, allow_archived=True)
    row = _row(c, context, space, identity)
    d = _plain(row)
    r, release = tables.definition_reviews, tables.definition_releases
    reviews = (
        c.execute(
            select(r)
            .where(r.c.tenant_id == context.tenant.id, r.c.definition_id == identity)
            .order_by(r.c.review_round, r.c.discipline)
            .limit(1001)
        )
        .mappings()
        .all()
    )
    releases = (
        c.execute(
            select(release)
            .where(release.c.tenant_id == context.tenant.id, release.c.definition_id == identity)
            .order_by(release.c.sequence)
            .limit(1001)
        )
        .mappings()
        .all()
    )
    if len(reviews) > 1000 or len(releases) > 1000:
        raise ProductWorkError("此定义历史超过单次导出容量，需分包，不截断签核历史")
    review_values = [_plain(v) for v in reviews]
    refs = references([d["content"], review_values])
    if refs:
        from app.domain.product_workspace import _role

        _role(context, Action.EVIDENCE_VIEW)
    resolved = _sources(c, context, refs)
    latest = _release(c, context, row["product_id"])
    current = bool(latest and latest["definition_id"] == identity and latest["action"] == "publish")
    status = (
        "当前已发布定义"
        if row["state"] == "published" and current
        else "历史已发布定义（当前不生效）"
        if row["state"] == "published"
        else "草稿 · 协审中"
        if row["state"] == "in_review"
        else "草稿 · 尚未发布"
    )
    product = (
        c.execute(
            select(
                tables.product_nodes.c.id, tables.product_nodes.c.name, tables.product_nodes.c.code
            ).where(
                tables.product_nodes.c.tenant_id == context.tenant.id,
                tables.product_nodes.c.id == row["product_id"],
            )
        )
        .mappings()
        .one()
    )
    # Explicit template projection, never a generic dump of project/internal conversation data.
    definition = {
        key: d[key]
        for key in (
            "id",
            "title",
            "product_id",
            "series_id",
            "revision_number",
            "version",
            "state",
            "review_round",
            "review_digest",
            "approval",
            "published_at",
            "content",
        )
    }
    body = {
        "definition": definition,
        "product": _plain(product),
        "status_label": status,
        "reviews": review_values,
        "releases": [_plain(v) for v in releases],
        "current_release": _plain(latest) if latest else None,
        "sources": resolved,
        "warnings": evidence_quality(c, context, resolved),
        "template_version": VERSION,
        "audience": "internal",
        "source_policy": "definition-export.v1",
    }
    return {**body, "digest": digest(body)}


def preview(
    c: Connection, context: AuthContext, space: UUID, command: ExportPreview
) -> dict[str, Any]:
    snapshot = source(c, context, space, command.definition_id)
    body = {
        "source": snapshot,
        "format": command.format,
        "reason": command.reason,
        "template_version": VERSION,
    }
    return {**body, "digest": digest(body)}


def metadata(row: Any) -> dict[str, Any]:
    return _plain(
        {
            k: row[k]
            for k in (
                "id",
                "definition_id",
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


class DefinitionExportService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def options(self, context: AuthContext, space: UUID, query: ExportOptions) -> dict[str, Any]:
        from app.domain.product_workspace import _line_filter

        with self.engine.connect() as c:
            _space(c, context, space, allow_archived=True)
            t = tables.product_definitions
            q = select(t.c.id, t.c.title, t.c.state, t.c.version, t.c.revision_number).where(
                t.c.tenant_id == context.tenant.id,
                t.c.market_space_id == space,
                _line_filter(t, context),
            )
            if query.search:
                q = q.where(t.c.title.icontains(query.search, autoescape=True))
            if query.before_id:
                q = q.where(t.c.id < query.before_id)
            values = c.execute(q.order_by(t.c.id.desc()).limit(21)).mappings().all()
            return {
                "items": [_plain(v) for v in values[:20]],
                "next_before_id": str(values[19]["id"]) if len(values) > 20 else None,
                "template_version": VERSION,
                "audience": "internal",
                "formats": list(MIMES),
            }

    def preview(self, context: AuthContext, space: UUID, command: ExportPreview) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            value = preview(c, context, space, command)
            return {
                **value,
                "sections": [
                    {"title": title, "text": text} for title, text in sections(value["source"])
                ],
            }

    def save(self, context: AuthContext, space: UUID, command: ExportSave) -> dict[str, Any]:
        with self.engine.begin() as c:
            _space(c, context, space, lock=True, allow_archived=True)
            _row(c, context, space, command.definition_id)
            t = tables.definition_exports
            signature = digest({"space": str(space), "command": command.model_dump(mode="json")})
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
                    raise ProductWorkError("同一请求不能更换导出输入或格式")
                _sources(
                    c,
                    context,
                    tuple(SourceRef.model_validate(v) for v in old["snapshot"]["sources"]),
                )
                return metadata(old)
            value = preview(c, context, space, command)
            if value["digest"] != command.expected_digest:
                raise ProductWorkError("定义、来源或签核状态已变化，请重新预览")
            identity = uuid4()
            from datetime import UTC, datetime

            now = datetime.now(UTC)
            receipt = {
                "编号": str(identity),
                "生成时点": now.isoformat(),
                "记录人": str(context.user.id),
                "来源摘要": value["source"]["digest"],
                "用途": command.reason,
            }
            try:
                content = render(value["source"], command.format, receipt)
            except (ValueError, TypeError) as error:
                raise ProductWorkError("原文含当前格式无法呈现的内容，请核对资料后重试") from error
            if len(content) > 12 * 1024 * 1024:
                raise ProductWorkError("文件超过12MB单次导出容量，需分包，不保存截断文件")
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        tenant_id=context.tenant.id,
                        market_space_id=space,
                        definition_id=command.definition_id,
                        format=command.format,
                        template_version=VERSION,
                        filename=f"definition-{command.definition_id}-v{value['source']['definition']['version']}-{identity}.{command.format}",
                        mime_type=MIMES[command.format],
                        byte_size=len(content),
                        content_digest=sha256(content).hexdigest(),
                        content=content,
                        snapshot=value["source"],
                        source_digest=value["source"]["digest"],
                        preview_digest=value["digest"],
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
            _emit(
                c,
                context,
                space,
                "definition_export",
                "generated",
                {"id": identity, "version": 1, "definition_id": command.definition_id},
            )
            return metadata(row)

    def history(self, context: AuthContext, space: UUID, query: ExportHistory) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            _space(c, context, space, allow_archived=True)
            _row(c, context, space, query.definition_id)
            try:
                current = source(c, context, space, query.definition_id)["digest"]
            except ProductWorkError:
                current = None
            t = tables.definition_exports
            q = select(*(col for col in t.c if col.name not in {"content", "snapshot"})).where(
                t.c.tenant_id == context.tenant.id,
                t.c.market_space_id == space,
                t.c.definition_id == query.definition_id,
            )
            if query.before_id:
                q = q.where(t.c.id < query.before_id)
            values = c.execute(q.order_by(t.c.id.desc()).limit(21)).mappings().all()
            return {
                "items": [
                    {**metadata(v), "sources_current": current == v["source_digest"]}
                    for v in values[:20]
                ],
                "next_before_id": str(values[19]["id"]) if len(values) > 20 else None,
            }

    def download(self, context: AuthContext, space: UUID, identity: UUID) -> tuple[bytes, str, str]:
        with self.engine.connect() as c:
            _space(c, context, space, allow_archived=True)
            t = tables.definition_exports
            row = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.market_space_id == space,
                        t.c.id == identity,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProductWorkError("导出文件不存在或不可读取")
            _row(c, context, space, row["definition_id"])
            _sources(
                c, context, tuple(SourceRef.model_validate(v) for v in row["snapshot"]["sources"])
            )
            if row["snapshot"]["sources"]:
                from app.domain.product_workspace import _role

                _role(context, Action.EVIDENCE_VIEW)
            content = bytes(row["content"])
            if (
                sha256(content).hexdigest() != row["content_digest"]
                or len(content) != row["byte_size"]
            ):
                raise ProductWorkError("文件与原回执不一致，停止下载")
            return content, row["mime_type"], row["filename"]
