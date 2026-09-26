"""Explicit in-use manufacturer part mappings to existing public subscriptions."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, select, true

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.document_previews import document_row, metadata
from app.domain.material_exceptions import _authorize, _editable
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _line,
    _plain,
    _space,
    digest,
)
from app.domain.research_collection import source_origin
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class WatchDraft(Contract):
    watch_id: UUID | None = None
    request_id: UUID
    expected_version: int = Field(ge=0)
    subscription_id: UUID
    bom_item_id: UUID
    manufacturer: str = Field(min_length=1, max_length=128)
    manufacturer_part_number: str = Field(min_length=1, max_length=128)
    active: bool = True
    evidence_id: UUID
    evidence_location: Text
    in_use_basis: Text
    source_basis: Text
    reason: Text


class WatchApply(WatchDraft):
    expected_digest: Digest


def subscription(c: Connection, context: AuthContext, identity: UUID) -> dict[str, Any]:
    t = tables.research_subscriptions
    row = (
        c.execute(select(t).where(t.c.tenant_id == context.tenant.id, t.c.id == identity))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("原公开订阅不存在")
    _space(c, context, row["market_space_id"])
    _line(c, context, row["market_space_id"], row["product_line_id"])
    return dict(row)


def source_state(
    c: Connection, context: AuthContext, project: UUID, command: WatchDraft
) -> dict[str, Any]:
    sub = subscription(c, context, command.subscription_id)
    source_origin(c, context.tenant.id, sub["source_id"])
    i, b = tables.development_bom_items, tables.development_boms
    row = (
        c.execute(
            select(
                i,
                b.c.code.label("bom_code"),
                b.c.version.label("bom_version"),
                b.c.bom_type,
                b.c.name.label("bom_name"),
            )
            .join(
                b,
                (b.c.tenant_id == i.c.tenant_id)
                & (b.c.project_id == i.c.project_id)
                & (b.c.id == i.c.bom_id),
            )
            .where(
                i.c.tenant_id == context.tenant.id,
                i.c.project_id == project,
                i.c.id == command.bom_item_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("请选择本项目实际BOM项，不能以手写料号代替在用对象")
    source = (
        c.execute(
            select(tables.research_sources).where(
                tables.research_sources.c.tenant_id == context.tenant.id,
                tables.research_sources.c.id == sub["source_id"],
            )
        )
        .mappings()
        .one()
    )
    return {
        "bom_item": _plain(row),
        "subscription": _plain(
            {k: sub[k] for k in ("id", "source_id", "market_space_id", "product_line_id", "url")}
        ),
        "source": _plain(
            {
                k: source[k]
                for k in (
                    "id",
                    "name",
                    "base_url",
                    "source_type",
                    "allowed_use",
                    "license_note",
                    "trust_tier",
                    "status",
                )
            }
        ),
        "evidence": metadata(document_row(c, context.tenant.id, project, command.evidence_id)),
    }


def row(c: Connection, tenant: UUID, project: UUID, identity: UUID) -> Any:
    t = tables.supplier_notice_watches
    found = (
        c.execute(
            select(t).where(t.c.tenant_id == tenant, t.c.project_id == project, t.c.id == identity)
        )
        .mappings()
        .one_or_none()
    )
    if found is None:
        raise ProductWorkError("订阅映射不存在或不属于本项目")
    return found


def preview(
    c: Connection, context: AuthContext, project: UUID, command: WatchDraft
) -> dict[str, Any]:
    _authorize(c, context, project, write=True)
    current = row(c, context.tenant.id, project, command.watch_id) if command.watch_id else None
    if command.expected_version != (current["version"] if current else 0):
        raise ProductWorkError("在用件映射已有新版本，请读取后重新核对")
    if current and current["owner_user_id"] != context.user.id:
        raise ProductWorkError("请由原映射负责人维护在用依据和订阅关联")
    if current and not command.active:
        old = WatchDraft.model_validate(current["command"])
        stable = {"watch_id", "request_id", "expected_version", "active", "reason"}
        if command.model_dump(exclude=stable | {"expected_digest"}) != old.model_dump(
            exclude=stable
        ):
            raise ProductWorkError("暂停时保留原映射内容；更改对应关系请先重新核对来源")
        snapshot = dict(current["snapshot"])
        collection_state = "not_rechecked"
    else:
        snapshot = source_state(c, context, project, command)
        collection_state = subscription(c, context, command.subscription_id)["status"]
    body = command.model_dump(mode="json", exclude={"expected_digest"})
    return {
        "digest": digest({"command": body, "source": snapshot}),
        "command": body,
        "source": snapshot,
        "collection_state": collection_state,
    }


class SupplierNoticeWatches:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(
        self,
        context: AuthContext,
        project: UUID,
        watch_id: UUID | None = None,
        before_version: int | None = None,
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            _authorize(c, context, project)
            t = tables.supplier_notice_watches
            query = select(t).where(t.c.tenant_id == context.tenant.id, t.c.project_id == project)
            if watch_id:
                query = query.where(t.c.id == watch_id)
            found = (
                c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(101))
                .mappings()
                .all()
            )
            items = []
            inaccessible = 0
            for r in found[:100]:
                try:
                    sub = subscription(c, context, r["subscription_id"])
                except (ProductWorkAccessError, ProductWorkError):
                    inaccessible += 1
                    continue
                try:
                    current = source_state(
                        c, context, project, WatchDraft.model_validate(r["command"])
                    )
                    unchanged = digest(current) == r["source_digest"]
                except (LookupError, ValueError):
                    unchanged = False
                items.append(
                    {
                        **_plain(r),
                        "sources_current": unchanged,
                        "can_edit": r["owner_user_id"] == context.user.id
                        and _editable(c, context, project),
                        "collection": _plain(
                            {
                                k: sub[k]
                                for k in (
                                    "status",
                                    "frequency",
                                    "next_due_at",
                                    "last_success_at",
                                    "last_snapshot_id",
                                    "last_error_code",
                                )
                            }
                        ),
                    }
                )
            s = tables.research_subscriptions
            candidates = (
                c.execute(
                    select(s.c.id)
                    .where(s.c.tenant_id == context.tenant.id)
                    .order_by(s.c.created_at.desc(), s.c.id.desc())
                    .limit(201)
                )
                .scalars()
                .all()
            )
            subscriptions = []
            for identity in candidates[:200]:
                try:
                    sub = subscription(c, context, identity)
                except (ProductWorkAccessError, ProductWorkError):
                    continue
                subscriptions.append(
                    _plain(
                        {k: sub[k] for k in ("id", "market_space_id", "url", "status", "frequency")}
                    )
                )
            b, i = tables.development_boms, tables.development_bom_items
            parts = (
                c.execute(
                    select(
                        i.c.id,
                        i.c.part_number,
                        i.c.description,
                        i.c.bom_id,
                        b.c.code,
                        b.c.version,
                        b.c.bom_type,
                    )
                    .join(b, (b.c.tenant_id == i.c.tenant_id) & (b.c.id == i.c.bom_id))
                    .where(i.c.tenant_id == context.tenant.id, i.c.project_id == project)
                    .order_by(b.c.updated_at.desc(), b.c.id, i.c.line_number)
                    .limit(201)
                )
                .mappings()
                .all()
            )
            d = tables.documents
            docs = (
                c.execute(
                    select(d.c.id, d.c.filename)
                    .where(d.c.tenant_id == context.tenant.id, d.c.project_id == project)
                    .order_by(d.c.created_at.desc(), d.c.id.desc())
                    .limit(101)
                )
                .mappings()
                .all()
            )
            history = []
            next_version = None
            if watch_id and items:
                revisions_table = tables.supplier_notice_watch_revisions
                query = select(revisions_table).where(
                    revisions_table.c.tenant_id == context.tenant.id,
                    revisions_table.c.project_id == project,
                    revisions_table.c.watch_id == watch_id,
                )
                if before_version is not None:
                    query = query.where(revisions_table.c.version < before_version)
                versions = (
                    c.execute(query.order_by(revisions_table.c.version.desc()).limit(21))
                    .mappings()
                    .all()
                )
                # Historical mappings may point at a different, now restricted source.
                for version in versions[:20]:
                    try:
                        subscription(c, context, UUID(version["command"]["subscription_id"]))
                    except (ProductWorkAccessError, ProductWorkError):
                        continue
                    history.append(_plain(version))
                next_version = versions[19]["version"] if len(versions) > 20 else None
            return {
                "items": items,
                "has_more": len(found) > 100,
                "inaccessible_count": inaccessible,
                "subscriptions": subscriptions,
                "more_subscriptions": len(candidates) > 200,
                "parts": [_plain(r) for r in parts[:200]],
                "more_parts": len(parts) > 200,
                "documents": [_plain(r) for r in docs[:100]],
                "more_documents": len(docs) > 100,
                "can_create": _editable(c, context, project),
                "history": history,
                "next_before_version": next_version,
            }

    def preview(self, context: AuthContext, project: UUID, command: WatchDraft) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return preview(c, context, project, command)

    def apply(self, context: AuthContext, project: UUID, command: WatchApply) -> dict[str, Any]:
        signature = digest({"project": str(project), "command": command.model_dump(mode="json")})
        with self.engine.begin() as c:
            NpiExecutionService._project(
                c, tenant_id=context.tenant.id, project_id=project, lock=True
            )
            _authorize(c, context, project, write=True)
            r, t = tables.supplier_notice_watch_revisions, tables.supplier_notice_watches
            prior = (
                c.execute(
                    select(r).where(
                        r.c.tenant_id == context.tenant.id,
                        r.c.created_by_user_id == context.user.id,
                        r.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != signature:
                    raise ProductWorkError("原请求已用于另一在用映射，请保留原回执")
                return _plain(prior)
            observed = preview(c, context, project, command)
            if observed["digest"] != command.expected_digest:
                raise ProductWorkError("BOM、订阅来源或核对文件已变化，请重新预览")
            duplicate = c.execute(
                select(t.c.id).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.project_id == project,
                    t.c.subscription_id == command.subscription_id,
                    t.c.bom_item_id == command.bom_item_id,
                    t.c.manufacturer_part_key == command.manufacturer_part_number.upper(),
                    t.c.id != command.watch_id if command.watch_id else true(),
                )
            ).scalar_one_or_none()
            if duplicate:
                raise ProductWorkError("此BOM项和厂商料号已有同一来源映射，请维护原记录")
            identity = command.watch_id or uuid4()
            now = datetime.now(UTC)
            values = dict(
                version=command.expected_version + 1,
                subscription_id=command.subscription_id,
                bom_id=UUID(observed["source"]["bom_item"]["bom_id"]),
                bom_item_id=command.bom_item_id,
                manufacturer=command.manufacturer,
                manufacturer_part_number=command.manufacturer_part_number,
                manufacturer_part_key=command.manufacturer_part_number.upper(),
                active=command.active,
                command=observed["command"],
                snapshot=observed["source"],
                source_digest=digest(observed["source"]),
                updated_at=now,
            )
            if command.watch_id:
                c.execute(
                    t.update()
                    .where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.project_id == project,
                        t.c.id == identity,
                    )
                    .values(**values)
                )
            else:
                c.execute(
                    t.insert().values(
                        id=identity,
                        tenant_id=context.tenant.id,
                        project_id=project,
                        owner_user_id=context.user.id,
                        created_at=now,
                        **values,
                    )
                )
            revision = dict(
                id=uuid4(),
                tenant_id=context.tenant.id,
                project_id=project,
                watch_id=identity,
                version=values["version"],
                command=observed["command"],
                snapshot=observed["source"],
                source_digest=values["source_digest"],
                request_id=command.request_id,
                request_digest=signature,
                created_by_user_id=context.user.id,
                created_at=now,
            )
            c.execute(r.insert().values(**revision))
            from app.domain.supplier_notice_dispatches import cancel_old, enqueue

            cancel_old(c, context.tenant.id, identity)
            if command.active:
                enqueue(c, context.tenant.id, command.subscription_id, identity)
            EventAuditWriter(
                c, tenant_id=context.tenant.id, project_id=project, actor_user_id=context.user.id
            ).record(
                EventDraft(
                    event_id=f"supplier-notice-watch:{revision['id']}",
                    event_type="SUPPLIER_NOTICE_WATCH_RECORDED",
                    source="supplier_service",
                    entity_id=identity,
                    payload={"watch_id": str(identity), "version": values["version"]},
                ),
                AuditDraft(
                    action="supplier.notice.watch_recorded", after_snapshot=_plain(revision)
                ),
            )
            return _plain(revision)
