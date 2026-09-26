"""Durable local matching jobs, committed atomically with their scan receipts."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, select, tuple_
from sqlalchemy.dialects.postgresql import insert

from app.auth.repository import AuthContext, AuthRepository
from app.contracts.common_objects import Contract
from app.db.schema import tables
from app.domain.material_exceptions import _authorize, _editable
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import ProductWorkError, _plain
from app.domain.supplier_notice_matching import POLICY
from app.domain.supplier_notice_watches import row, subscription
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft
from app.settings import get_settings


class RetryRequest(Contract):
    expected_attempts: int = Field(ge=0)


def enqueue(
    c: Connection, tenant: UUID, subscription_id: UUID, watch_id: UUID | None = None
) -> None:
    """Capture and mapping saves enqueue identities; execution checks live authority."""
    w, r, s, runs = (
        tables.supplier_notice_watches,
        tables.supplier_notice_watch_revisions,
        tables.research_subscriptions,
        tables.research_collection_runs,
    )
    receipt = (
        select(runs.c.id)
        .where(
            runs.c.tenant_id == tenant,
            runs.c.subscription_id == s.c.id,
            runs.c.snapshot_id == s.c.last_snapshot_id,
            runs.c.status == "completed",
        )
        .order_by(runs.c.finished_at.desc(), runs.c.id.desc())
        .limit(1)
        .correlate(s)
        .scalar_subquery()
    )
    query = (
        select(
            w,
            r.c.id.label("revision_id"),
            s.c.last_snapshot_id.label("snapshot_id"),
            receipt.label("collection_run_id"),
        )
        .select_from(
            w.join(r, (r.c.watch_id == w.c.id) & (r.c.version == w.c.version)).join(
                s, (s.c.id == w.c.subscription_id) & (s.c.tenant_id == w.c.tenant_id)
            )
        )
        .where(
            w.c.tenant_id == tenant,
            w.c.subscription_id == subscription_id,
            w.c.active.is_(True),
            s.c.status == "active",
            s.c.last_snapshot_id.is_not(None),
        )
    )
    if watch_id:
        query = query.where(w.c.id == watch_id)
    now = datetime.now(UTC)
    for item in c.execute(query).mappings():
        if item["collection_run_id"] is None:
            continue
        c.execute(
            insert(tables.supplier_notice_dispatches)
            .values(
                id=uuid4(),
                tenant_id=tenant,
                project_id=item["project_id"],
                watch_id=item["id"],
                watch_revision_id=item["revision_id"],
                watch_version=item["version"],
                subscription_id=subscription_id,
                snapshot_id=item["snapshot_id"],
                collection_run_id=item["collection_run_id"],
                owner_user_id=item["owner_user_id"],
                policy_version=POLICY,
                status="queued",
                attempts=0,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_notice_dispatch_input")
        )


def cancel_old(c: Connection, tenant: UUID, watch_id: UUID) -> None:
    t = tables.supplier_notice_dispatches
    c.execute(
        t.update()
        .where(
            t.c.tenant_id == tenant, t.c.watch_id == watch_id, t.c.status.in_(("queued", "blocked"))
        )
        .values(
            status="cancelled",
            last_error_code="WATCH_REVISED",
            last_error_message="原映射已修订或暂停；原输入停止，历史匹配保留",
            updated_at=datetime.now(UTC),
        )
    )


def record(c: Connection, job: Any, after: Any, action: str) -> None:
    EventAuditWriter(
        c,
        tenant_id=job["tenant_id"],
        project_id=job["project_id"],
        actor_user_id=job["owner_user_id"],
    ).record(
        EventDraft(
            event_id=f"supplier-notice-dispatch:{job['id']}:{action}:{after['attempts']}",
            event_type="SUPPLIER_NOTICE_DISPATCH_UPDATED",
            source="supplier_service",
            entity_id=job["id"],
            payload={"status": after["status"]},
        ),
        AuditDraft(
            action=f"supplier.notice.dispatch_{action}",
            before_snapshot=_plain(job),
            after_snapshot=_plain(after),
        ),
    )


def current_job(c: Connection, context: AuthContext, job: Any) -> None:
    from app.domain.supplier_notice_scans import current_input

    _authorize(c, context, job["project_id"], write=True)
    watch = row(c, job["tenant_id"], job["project_id"], job["watch_id"])
    source = current_input(c, context, job["project_id"], watch)
    if (
        watch["owner_user_id"] != context.user.id
        or watch["version"] != job["watch_version"]
        or source["watch_revision"]["id"] != str(job["watch_revision_id"])
        or source["snapshot"]["id"] != str(job["snapshot_id"])
        or job["policy_version"] != POLICY
    ):
        raise ProductWorkError("原排队输入已变化，请使用当前映射和快照的新队列")


class SupplierNoticeDispatches:
    def __init__(self, engine: Engine, *, enabled: bool = False) -> None:
        self.engine, self.enabled = engine, enabled

    def get(
        self, context: AuthContext, project: UUID, watch_id: UUID, before_id: UUID | None = None
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            _authorize(c, context, project)
            watch = row(c, context.tenant.id, project, watch_id)
            subscription(c, context, watch["subscription_id"])
            t = tables.supplier_notice_dispatches
            query = select(t).where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project,
                t.c.watch_id == watch_id,
            )
            if before_id:
                cursor = c.execute(query.where(t.c.id == before_id)).mappings().one_or_none()
                if cursor is None:
                    raise ProductWorkError("请从原匹配队列继续翻页")
                query = query.where(
                    tuple_(t.c.created_at, t.c.id) < tuple_(cursor["created_at"], cursor["id"])
                )
            found = (
                c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21))
                .mappings()
                .all()
            )
            editable = _editable(c, context, project) and context.user.id == watch["owner_user_id"]
            items = []
            for item in found[:20]:
                try:
                    original_sub = subscription(c, context, item["subscription_id"])
                except (LookupError, ValueError, PermissionError):
                    continue
                items.append(
                    {
                        **_plain(item),
                        "can_retry": editable
                        and watch["active"]
                        and watch["version"] == item["watch_version"]
                        and item["status"] == "blocked"
                        and original_sub["status"] == "active"
                        and original_sub["last_snapshot_id"] == item["snapshot_id"],
                    }
                )
            return {
                "items": items,
                "enabled": get_settings().supplier_notice_matching_enabled,
                "next_before_id": str(found[19]["id"]) if len(found) > 20 else None,
            }

    def retry(
        self,
        context: AuthContext,
        project: UUID,
        watch_id: UUID,
        job_id: UUID,
        command: RetryRequest,
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            NpiExecutionService._project(
                c, tenant_id=context.tenant.id, project_id=project, lock=True
            )
            t = tables.supplier_notice_dispatches
            job = (
                c.execute(
                    select(t)
                    .where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.project_id == project,
                        t.c.watch_id == watch_id,
                        t.c.id == job_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if job is None:
                raise ProductWorkError("原匹配队列不存在")
            current_job(c, context, job)
            if job["status"] in {"queued", "completed"}:
                return _plain(job)
            if job["status"] != "blocked" or job["attempts"] != command.expected_attempts:
                raise ProductWorkError("原队列已变化，请读取原回执")
            after = (
                c.execute(
                    t.update()
                    .where(t.c.id == job_id)
                    .values(status="queued", updated_at=datetime.now(UTC))
                    .returning(t)
                )
                .mappings()
                .one()
            )
            record(c, job, after, "retried")
            return _plain(after)

    def run_once(self) -> dict[str, Any]:
        if not self.enabled:
            return {"status": "disabled"}
        t = tables.supplier_notice_dispatches
        with self.engine.connect() as c:
            candidate = (
                c.execute(
                    select(t)
                    .where(t.c.status == "queued")
                    .order_by(t.c.created_at, t.c.id)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        if candidate is None:
            return {"status": "idle"}
        context = AuthRepository(self.engine).find_user_context(candidate["owner_user_id"])
        with self.engine.begin() as c:
            # Match is bounded, local, and uses this transaction: a process loss rolls
            # back both the scan and claim, leaving the same input queued for recovery.
            NpiExecutionService._project(
                c, tenant_id=candidate["tenant_id"], project_id=candidate["project_id"], lock=True
            )
            # Collection and pause both lock the subscription before touching jobs.
            # Keep that order so a completed scan cannot cross an earlier pause.
            sub = tables.research_subscriptions
            c.execute(
                select(sub.c.id)
                .where(
                    sub.c.tenant_id == candidate["tenant_id"],
                    sub.c.id == candidate["subscription_id"],
                )
                .with_for_update()
            ).one()
            job = (
                c.execute(
                    select(t)
                    .where(t.c.id == candidate["id"], t.c.status == "queued")
                    .with_for_update(skip_locked=True)
                )
                .mappings()
                .one_or_none()
            )
            if job is None:
                return {"status": "busy"}
            values: dict[str, Any] = {
                "attempts": job["attempts"] + 1,
                "updated_at": datetime.now(UTC),
            }
            watch = row(c, job["tenant_id"], job["project_id"], job["watch_id"])
            if not watch["active"] or watch["version"] != job["watch_version"]:
                values.update(
                    status="cancelled",
                    last_error_code="WATCH_REVISED",
                    last_error_message="原映射已修订或暂停，原输入不再派发",
                )
            else:
                try:
                    with c.begin_nested():
                        if (
                            context is None
                            or context.tenant.id != job["tenant_id"]
                            or context.tenant.status != "active"
                            or not context.user.is_active
                        ):
                            raise ProductWorkError("原负责人或租户不可用")
                        current_job(c, context, job)
                        from app.domain.supplier_notice_scans import (
                            ScanRequest,
                            SupplierNoticeScans,
                        )

                        scan = SupplierNoticeScans(self.engine).scan_in_connection(
                            c,
                            context,
                            job["project_id"],
                            job["watch_id"],
                            ScanRequest(
                                request_id=job["id"],
                                expected_version=job["watch_version"],
                                snapshot_id=job["snapshot_id"],
                            ),
                        )
                        values.update(
                            status="completed",
                            scan_id=UUID(scan["id"]),
                            last_error_code=None,
                            last_error_message=None,
                        )
                except Exception as error:
                    values.update(
                        status="blocked",
                        scan_id=None,
                        last_error_code=type(error).__name__[:80],
                        last_error_message="原权限、映射、快照或本地匹配未通过；核对后重试原输入",
                    )
            after = (
                c.execute(t.update().where(t.c.id == job["id"]).values(**values).returning(t))
                .mappings()
                .one()
            )
            record(c, job, after, "attempted")
            return {"status": after["status"], "dispatch_id": str(job["id"])}
