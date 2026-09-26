"""Replayable source-bound notice scans; local matching never sends project data."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, select, tuple_

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract
from app.db.schema import tables
from app.domain.evidence import content_digest
from app.domain.material_exceptions import _authorize, _editable
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError, _plain, digest
from app.domain.supplier_notice_matching import POLICY, match_notices
from app.domain.supplier_notice_watches import WatchDraft, row, source_state, subscription
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class ScanRequest(Contract):
    request_id: UUID
    expected_version: int = Field(ge=1)
    snapshot_id: UUID


def current_input(c: Connection, context: AuthContext, project: UUID, watch: Any) -> dict[str, Any]:
    if not watch["active"]:
        raise ProductWorkError("此在用映射已暂停")
    sub = subscription(c, context, watch["subscription_id"])
    if sub["status"] != "active":
        raise ProductWorkError("原订阅已暂停或隔离，恢复后再匹配")
    current = source_state(c, context, project, WatchDraft.model_validate(watch["command"]))
    if digest(current) != watch["source_digest"]:
        raise ProductWorkError("在用BOM、来源或核对文件已变化，请先修订映射")
    if sub["last_snapshot_id"] is None:
        raise ProductWorkError("原订阅尚无成功采集的快照")
    t = tables.evidence_snapshots
    snap = (
        c.execute(
            select(t).where(
                t.c.tenant_id == context.tenant.id,
                t.c.id == sub["last_snapshot_id"],
                t.c.source_id == sub["source_id"],
            )
        )
        .mappings()
        .one_or_none()
    )
    if snap is None:
        raise ProductWorkError("原快照与当前来源不一致")
    if (
        snap["superseded_by_id"]
        or snap["conflicts_with_id"]
        or (snap["freshness_expires_at"] and snap["freshness_expires_at"] <= datetime.now(UTC))
    ):
        raise ProductWorkError("原快照已失效或存在冲突，请先核对来源并重新采集")
    runs = tables.research_collection_runs
    receipt = c.execute(
        select(runs.c.id)
        .where(
            runs.c.tenant_id == context.tenant.id,
            runs.c.subscription_id == sub["id"],
            runs.c.snapshot_id == snap["id"],
            runs.c.status == "completed",
        )
        .order_by(runs.c.finished_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if receipt is None:
        raise ProductWorkError("缺少原订阅成功采集回执")
    r = tables.supplier_notice_watch_revisions
    revision = (
        c.execute(
            select(r).where(
                r.c.tenant_id == context.tenant.id,
                r.c.project_id == project,
                r.c.watch_id == watch["id"],
                r.c.version == watch["version"],
            )
        )
        .mappings()
        .one()
    )
    return {
        "watch_revision": _plain(revision),
        "watch_source": current,
        "snapshot": _plain(snap),
        "subscription_id": str(sub["id"]),
        "collection_run_id": str(receipt),
        "part_number": watch["manufacturer_part_number"],
        "manufacturer": watch["manufacturer"],
        "scope_digest": digest(
            {
                "source": current,
                "part": watch["manufacturer_part_key"],
                "manufacturer": watch["manufacturer"],
            }
        ),
    }


def exact_match(body: str, match: dict[str, Any]) -> bool:
    return (
        body[match["part_start"] : match["part_end"]] == match["part"]
        and body[match["marker_start"] : match["marker_end"]] == match["marker"]
        and all(body[q["start"] : q["end"]] == q["text"] for q in match["quotes"])
    )


def receipt_view(c: Connection, context: AuthContext, scan: Any) -> dict[str, Any]:
    source_id = scan["source_snapshot"]["snapshot"]["source_id"]
    active = (
        c.execute(
            select(tables.research_sources.c.id).where(
                tables.research_sources.c.tenant_id == context.tenant.id,
                tables.research_sources.c.id == UUID(source_id),
                tables.research_sources.c.status == "active",
            )
        ).scalar_one_or_none()
        is not None
    )
    visible = _plain(scan)
    if not active:
        visible["matches"] = []
    return {**visible, "content_available": active}


class SupplierNoticeScans:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(
        self, context: AuthContext, project: UUID, watch_id: UUID, before_id: UUID | None = None
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            _authorize(c, context, project)
            watch = row(c, context.tenant.id, project, watch_id)
            subscription(c, context, watch["subscription_id"])
            current = None
            error = None
            try:
                current = current_input(c, context, project, watch)
            except (LookupError, ValueError):
                error = "当前映射、订阅或快照未就绪，请核对在用依据、原采集回执及有效期"
            t = tables.supplier_notice_scans
            query = select(t).where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project,
                t.c.watch_id == watch_id,
            )
            if before_id:
                cursor = c.execute(query.where(t.c.id == before_id)).mappings().one_or_none()
                if cursor is None:
                    raise ProductWorkError("请从原匹配记录继续翻页")
                query = query.where(
                    tuple_(t.c.created_at, t.c.id) < tuple_(cursor["created_at"], cursor["id"])
                )
            found = (
                c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21))
                .mappings()
                .all()
            )
            items = []
            for scan in found[:20]:
                try:
                    subscription(c, context, scan["subscription_id"])
                except (ProductWorkAccessError, ProductWorkError):
                    continue
                same_scope = bool(
                    current and current["scope_digest"] == scan["source_snapshot"]["scope_digest"]
                )
                same_snapshot = bool(
                    current and current["snapshot"]["id"] == str(scan["snapshot_id"])
                )
                items.append(
                    {
                        **receipt_view(c, context, scan),
                        "scope_current": same_scope,
                        "snapshot_current": same_snapshot,
                    }
                )
            return {
                "current": current,
                "current_error": error,
                "watch_version": watch["version"],
                "can_scan": current is not None and _editable(c, context, project),
                "items": items,
                "next_before_id": str(found[19]["id"]) if len(found) > 20 else None,
            }

    def scan(
        self, context: AuthContext, project: UUID, watch_id: UUID, command: ScanRequest
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            return self.scan_in_connection(c, context, project, watch_id, command)

    def scan_in_connection(
        self,
        c: Connection,
        context: AuthContext,
        project: UUID,
        watch_id: UUID,
        command: ScanRequest,
    ) -> dict[str, Any]:
        signature = digest(
            {
                "project": str(project),
                "watch": str(watch_id),
                "command": command.model_dump(mode="json"),
            }
        )
        NpiExecutionService._project(c, tenant_id=context.tenant.id, project_id=project, lock=True)
        _authorize(c, context, project, write=True)
        watch = row(c, context.tenant.id, project, watch_id)
        subscription(c, context, watch["subscription_id"])
        t = tables.supplier_notice_scans
        prior = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.created_by_user_id == context.user.id,
                    t.c.request_id == command.request_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if prior:
            if prior["request_digest"] != signature:
                raise ProductWorkError("原请求已用于另一匹配，请保留原回执")
            subscription(c, context, prior["subscription_id"])
            return receipt_view(c, context, prior)
        source = current_input(c, context, project, watch)
        if watch["version"] != command.expected_version or source["snapshot"]["id"] != str(
            command.snapshot_id
        ):
            raise ProductWorkError("映射版本或最新快照已变化，请读取后重试")
        revision_id = UUID(source["watch_revision"]["id"])
        prior = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.project_id == project,
                    t.c.watch_revision_id == revision_id,
                    t.c.snapshot_id == command.snapshot_id,
                    t.c.policy_version == POLICY,
                )
            )
            .mappings()
            .one_or_none()
        )
        if prior:
            return receipt_view(c, context, prior)
        content = c.execute(
            select(tables.evidence_contents.c.body).where(
                tables.evidence_contents.c.tenant_id == context.tenant.id,
                tables.evidence_contents.c.content_digest == source["snapshot"]["content_digest"],
            )
        ).scalar_one_or_none()
        if content is None or content_digest(content) != source["snapshot"]["content_digest"]:
            raise ProductWorkError("原快照正文缺失或摘要不一致，请重新采集")
        parsed = match_notices(content, watch["manufacturer_part_number"])
        if not all(exact_match(content, m) for m in parsed["matches"]):
            raise ProductWorkError("原文位置无法精确复核，本轮不生成候选")
        identity, now = uuid4(), datetime.now(UTC)
        candidates = tables.supplier_notice_candidates
        matches: list[dict[str, Any]] = []
        pending: dict[str, dict[str, Any]] = {}
        for match in parsed["matches"]:
            origin = digest(
                {
                    "watch": str(watch_id),
                    "scope": source["scope_digest"],
                    "policy": POLICY,
                    "quotes": [" ".join(q["text"].split()) for q in match["quotes"]],
                }
            )
            prior_id = c.execute(
                select(candidates.c.id).where(
                    candidates.c.tenant_id == context.tenant.id,
                    candidates.c.project_id == project,
                    candidates.c.watch_id == watch_id,
                    candidates.c.origin_digest == origin,
                )
            ).scalar_one_or_none()
            if prior_id:
                candidate_id = prior_id
                created = False
            elif origin in pending:
                candidate_id = pending[origin]["id"]
                created = False
            else:
                candidate_id = uuid4()
                created = True
                pending[origin] = dict(
                    id=candidate_id,
                    tenant_id=context.tenant.id,
                    project_id=project,
                    watch_id=watch_id,
                    first_scan_id=identity,
                    watch_revision_id=revision_id,
                    snapshot_id=command.snapshot_id,
                    origin_digest=origin,
                    scope_digest=source["scope_digest"],
                    evidence=match,
                    state="pending_review",
                    created_at=now,
                )
            matches.append({**match, "candidate_id": str(candidate_id), "created": created})
        values = dict(
            id=identity,
            tenant_id=context.tenant.id,
            project_id=project,
            watch_id=watch_id,
            watch_revision_id=revision_id,
            subscription_id=watch["subscription_id"],
            snapshot_id=command.snapshot_id,
            collection_run_id=UUID(source["collection_run_id"]),
            policy_version=POLICY,
            request_id=command.request_id,
            request_digest=signature,
            source_snapshot=source,
            outcome="matched" if matches else "no_match",
            matches=matches,
            full_part_hits=parsed["full_part_hits"],
            truncated=parsed["truncated"],
            coverage=parsed["coverage"],
            created_by_user_id=context.user.id,
            created_at=now,
        )
        c.execute(t.insert().values(**values))
        for candidate in pending.values():
            c.execute(candidates.insert().values(**candidate))
        EventAuditWriter(
            c, tenant_id=context.tenant.id, project_id=project, actor_user_id=context.user.id
        ).record(
            EventDraft(
                event_id=f"supplier-notice-scan:{identity}",
                event_type="SUPPLIER_NOTICE_SCANNED",
                source="supplier_service",
                entity_id=identity,
                payload={"watch_id": str(watch_id), "new_candidates": len(pending)},
            ),
            AuditDraft(
                action="supplier.notice.scanned",
                after_snapshot={
                    "scan_id": str(identity),
                    "snapshot_id": str(command.snapshot_id),
                    "new_candidate_ids": [str(v["id"]) for v in pending.values()],
                },
            ),
        )
        return receipt_view(c, context, values)
