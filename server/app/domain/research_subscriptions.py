"""Deterministic public-source subscriptions; no model calls or outbound messages."""

import calendar
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, exists, func, or_, select, text

from app.ai.reach import ReachDeniedError, ReachFetchError, ReachPolicy
from app.auth.repository import AuthContext, AuthRepository
from app.auth.roles import Action
from app.contracts.object_operations import CommandPrecondition
from app.db.schema import tables
from app.domain.evidence import EvidenceSnapshotRecord, EvidenceValidationError
from app.domain.product_workspace import (
    Input,
    ProductWorkAccessError,
    ProductWorkError,
    _emit,
    _line,
    _line_filter,
    _plain,
    _precondition,
    _record,
    _role,
    _space,
    digest,
)
from app.domain.research_collection import authorize_collection, collect_page, source_origin

Frequency = Literal["daily", "weekly", "monthly"]


class SubscriptionDraft(Input):
    request_id: UUID
    source_id: UUID
    product_line_id: UUID | None = None
    url: str = Field(min_length=1, max_length=1024)
    frequency: Frequency
    freshness_days: int | None = Field(default=None, ge=1, le=366)


class SubscriptionAction(CommandPrecondition):
    action: Literal["pause", "resume", "reschedule"]
    reason: str = Field(min_length=1, max_length=2048)
    frequency: Frequency | None = None
    freshness_days: int | None = Field(default=None, ge=1, le=366)


class CollectionLeaseLost(RuntimeError):
    pass


def next_collection(now: datetime, frequency: str) -> datetime:
    if frequency == "daily":
        return now + timedelta(days=1)
    if frequency == "weekly":
        return now + timedelta(days=7)
    year = now.year + int(now.month == 12)
    month = now.month % 12 + 1
    return now.replace(
        year=year, month=month, day=min(now.day, calendar.monthrange(year, month)[1])
    )


def _manage(connection: Connection, context: AuthContext, row: Any) -> None:
    _role(context, Action.EVIDENCE_CAPTURE)
    _space(connection, context, row["market_space_id"], access="contributor")
    _line(connection, context, row["market_space_id"], row["product_line_id"], access="contributor")
    if row["owner_user_id"] != context.user.id:
        _role(context, Action.RESEARCH_SOURCE_MANAGE)
        _space(connection, context, row["market_space_id"], access="manager")
        _line(connection, context, row["market_space_id"], row["product_line_id"], access="manager")


def _cancel_attempt(connection: Connection, row: Any, reason: str) -> None:
    if row["lease_token"] is not None:
        run = tables.research_collection_runs
        connection.execute(
            run.update()
            .where(run.c.id == row["lease_token"], run.c.status == "running")
            .values(
                status="cancelled",
                finished_at=datetime.now(UTC),
                error_code="SUBSCRIPTION_CHANGED",
                error_message=reason,
            )
        )


class ResearchSubscriptionService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list(
        self, context: AuthContext, space_id: UUID, subscription_id: UUID | None = None
    ) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _space(connection, context, space_id)
            table = tables.research_subscriptions
            rows = list(
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        _line_filter(table, context),
                    )
                    .order_by(table.c.created_at.desc())
                    .limit(100)
                ).mappings()
            )
            if subscription_id and not any(r["id"] == subscription_id for r in rows):
                selected = (
                    connection.execute(
                        select(table).where(
                            table.c.tenant_id == context.tenant.id,
                            table.c.market_space_id == space_id,
                            table.c.id == subscription_id,
                            _line_filter(table, context),
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if selected is None:
                    raise ProductWorkAccessError("订阅不存在或不可访问")
                rows.insert(0, selected)
            items = []
            for row in rows:
                try:
                    _manage(connection, context, row)
                    can_manage = True
                except ProductWorkAccessError:
                    can_manage = False
                items.append({**_record(row), "can_manage": can_manage})
            run = tables.research_collection_runs
            attempts = connection.execute(
                select(run)
                .where(
                    run.c.tenant_id == context.tenant.id,
                    run.c.subscription_id.in_([row["id"] for row in rows]),
                )
                .order_by(run.c.started_at.desc())
                .limit(100)
            ).mappings()
            return {"items": items, "runs": [_plain(row) for row in attempts]}

    def create(
        self, context: AuthContext, space_id: UUID, draft: SubscriptionDraft
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            authorize_collection(connection, context, space_id, draft.product_line_id)
            table = tables.research_subscriptions
            fingerprint = digest(draft.model_dump(mode="json"))
            audit = tables.audit_log
            creation = select(audit.c.id).where(
                audit.c.tenant_id == table.c.tenant_id,
                audit.c.entity_id == table.c.id,
                audit.c.action == "research_subscription.created",
            )
            creator = or_(
                exists(creation.where(audit.c.actor_user_id == context.user.id)),
                (table.c.owner_user_id == context.user.id) & ~exists(creation),
            )
            existing = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        creator,
                        table.c.request_id == draft.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing:
                if existing["request_digest"] != fingerprint:
                    raise ProductWorkError("同一订阅请求编号不能用于不同内容")
                return _record(existing)
            origin = source_origin(connection, context.tenant.id, draft.source_id)
            ReachPolicy().assert_url_allowed(draft.url)
            parsed = urlsplit(draft.url)
            actual_origin = (
                parsed.scheme,
                (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip("."),
                parsed.port or (443 if parsed.scheme == "https" else 80),
            )
            if actual_origin != origin:
                raise ProductWorkError("订阅页面须属于所选来源")
            duplicate = connection.execute(
                select(table.c.id).where(
                    table.c.tenant_id == context.tenant.id,
                    table.c.market_space_id == space_id,
                    table.c.product_line_id.is_not_distinct_from(draft.product_line_id),
                    table.c.source_id == draft.source_id,
                    table.c.url == draft.url,
                    table.c.owner_user_id == context.user.id,
                    table.c.status == "active",
                )
            ).first()
            if duplicate:
                raise ProductWorkError("此范围已存在相同页面的活动订阅，请调整现有订阅")
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        **draft.model_dump(),
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        market_space_id=space_id,
                        owner_user_id=context.user.id,
                        hostname=origin[1],
                        request_digest=fingerprint,
                        status="active",
                        next_due_at=datetime.now(UTC),
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            _emit(connection, context, space_id, "research_subscription", "created", row)
            return _record(row)

    def act(
        self,
        context: AuthContext,
        space_id: UUID,
        subscription_id: UUID,
        command: SubscriptionAction,
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            _space(connection, context, space_id, lock=True, allow_archived=True)
            table = tables.research_subscriptions
            row = (
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        table.c.id == subscription_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProductWorkAccessError("订阅不存在或不可访问")
            _manage(connection, context, row)
            if not _precondition(connection, context, row, command):
                return _record(row)
            values: dict[str, Any] = {
                "version": row["version"] + 1,
                "updated_at": datetime.now(UTC),
                "lease_token": None,
                "lease_expires_at": None,
            }
            if command.action == "pause":
                values.update(status="paused", next_due_at=None)
            else:
                authorize_collection(connection, context, space_id, row["product_line_id"])
                source_origin(connection, context.tenant.id, row["source_id"])
                if command.action == "resume":
                    if row["status"] == "active":
                        raise ProductWorkError("订阅已启用，可刷新查看下一次采集时间")
                    values.update(
                        status="active",
                        next_due_at=datetime.now(UTC),
                        consecutive_failures=0,
                        last_error_code=None,
                        last_error_message=None,
                    )
                else:
                    if command.frequency is None:
                        raise ProductWorkError("调整周期时须指定频率")
                    values.update(
                        frequency=command.frequency,
                        freshness_days=command.freshness_days,
                        next_due_at=next_collection(datetime.now(UTC), command.frequency)
                        if row["status"] == "active"
                        else None,
                    )
            _cancel_attempt(connection, row, command.reason)
            after = (
                connection.execute(
                    table.update()
                    .where(table.c.id == subscription_id)
                    .values(**values)
                    .returning(table)
                )
                .mappings()
                .one()
            )
            _emit(
                connection,
                context,
                space_id,
                "research_subscription",
                command.action,
                after,
                before=row,
                operation=command,
            )
            return _record(after)


class ResearchCollectionWorker:
    """One fenced collection per cycle, using the app service role, not pdos_agent."""

    def __init__(self, engine: Engine, *, enabled: bool = False) -> None:
        self.engine = engine
        self.enabled = enabled

    def _fail(
        self,
        connection: Connection,
        context: AuthContext,
        row: Any,
        code: str,
        message: str,
        *,
        permanent: bool = False,
        run_status: str = "failed",
    ) -> str:
        now = datetime.now(UTC)
        failures = row["consecutive_failures"] + 1
        quarantine = permanent or failures >= 5
        run = tables.research_collection_runs
        if row["lease_token"] is not None:
            connection.execute(
                run.update()
                .where(run.c.id == row["lease_token"], run.c.status == "running")
                .values(status=run_status, finished_at=now, error_code=code, error_message=message)
            )
        table = tables.research_subscriptions
        after = (
            connection.execute(
                table.update()
                .where(table.c.id == row["id"])
                .values(
                    status="quarantined" if quarantine else "active",
                    next_due_at=None
                    if quarantine
                    else now + timedelta(minutes=min(5 * 2 ** (failures - 1), 1440)),
                    consecutive_failures=failures,
                    lease_token=None,
                    lease_expires_at=None,
                    last_error_code=code,
                    last_error_message=message,
                    version=row["version"] + 1,
                    updated_at=now,
                )
                .returning(table)
            )
            .mappings()
            .one()
        )
        _emit(
            connection,
            context,
            row["market_space_id"],
            "research_subscription",
            "quarantined" if quarantine else "retry_scheduled",
            after,
            before=row,
        )
        return "quarantined" if quarantine else "retry_scheduled"

    def run_once(self) -> dict[str, Any]:
        if not self.enabled:
            return {"status": "disabled"}
        table = tables.research_subscriptions
        now = datetime.now(UTC)
        with self.engine.connect() as connection:
            candidate = (
                connection.execute(
                    select(table)
                    .where(
                        table.c.status == "active",
                        table.c.next_due_at <= now,
                        (table.c.lease_expires_at.is_(None)) | (table.c.lease_expires_at <= now),
                    )
                    .order_by(table.c.next_due_at, table.c.id)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        if candidate is None:
            return {"status": "idle"}
        context = AuthRepository(self.engine).find_user_context(candidate["owner_user_id"])
        if context is None or context.tenant.id != candidate["tenant_id"]:
            raise RuntimeError("Subscription owner identity is missing")
        with self.engine.begin() as connection:
            # All writers take the space lock before subscription or receipt locks.
            space_lock = connection.execute(
                select(tables.market_spaces.c.id)
                .where(
                    tables.market_spaces.c.id == candidate["market_space_id"],
                    tables.market_spaces.c.tenant_id == candidate["tenant_id"],
                )
                .with_for_update(skip_locked=True)
            ).first()
            if space_lock is None:
                return {"status": "busy"}
            row = (
                connection.execute(
                    select(table).where(table.c.id == candidate["id"]).with_for_update()
                )
                .mappings()
                .one()
            )
            if (
                row["owner_user_id"] != context.user.id
                or row["status"] != "active"
                or row["next_due_at"] > now
                or (row["lease_expires_at"] is not None and row["lease_expires_at"] > now)
            ):
                return {"status": "busy"}
            if row["lease_token"] is not None:
                self._fail(
                    connection,
                    context,
                    row,
                    "COLLECTION_INTERRUPTED",
                    "采集租约超时，将按退避策略处理",
                    run_status="timed_out",
                )
                return {"status": "recovered"}
            try:
                authorize_collection(
                    connection, context, row["market_space_id"], row["product_line_id"]
                )
                source_origin(connection, row["tenant_id"], row["source_id"])
            except (ProductWorkAccessError, ProductWorkError) as error:
                self._fail(
                    connection,
                    context,
                    row,
                    "COLLECTION_AUTHORIZATION_CHANGED",
                    str(error),
                    permanent=True,
                )
                return {"status": "quarantined"}
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"research-host:{row['tenant_id']}:{row['hostname']}"},
            )
            runs = tables.research_collection_runs
            used = connection.execute(
                select(func.count())
                .select_from(runs.join(table, table.c.id == runs.c.subscription_id))
                .where(
                    runs.c.tenant_id == row["tenant_id"],
                    table.c.hostname == row["hostname"],
                    runs.c.started_at > now - timedelta(hours=1),
                )
            ).scalar_one()
            if used >= 12:
                after = (
                    connection.execute(
                        table.update()
                        .where(table.c.id == row["id"])
                        .values(
                            next_due_at=now + timedelta(hours=1),
                            last_error_code="HOST_READ_LIMIT",
                            last_error_message="同租户来源每小时采集上限已到，稍后继续",
                            version=row["version"] + 1,
                            updated_at=now,
                        )
                        .returning(table)
                    )
                    .mappings()
                    .one()
                )
                _emit(
                    connection,
                    context,
                    row["market_space_id"],
                    "research_subscription",
                    "deferred",
                    after,
                    before=row,
                )
                return {"status": "deferred"}
            token = uuid4()
            claimed = (
                connection.execute(
                    table.update()
                    .where(table.c.id == row["id"])
                    .values(
                        lease_token=token,
                        lease_expires_at=now + timedelta(seconds=90),
                        last_attempt_at=now,
                        version=row["version"] + 1,
                        updated_at=now,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            connection.execute(
                runs.insert().values(
                    id=token,
                    tenant_id=row["tenant_id"],
                    subscription_id=row["id"],
                    subscription_version=claimed["version"],
                    status="running",
                    started_at=now,
                )
            )
            _emit(
                connection,
                context,
                row["market_space_id"],
                "research_subscription",
                "collection_started",
                claimed,
                before=row,
            )

        def guard(connection: Connection) -> None:
            current = (
                connection.execute(
                    select(table).where(table.c.id == claimed["id"]).with_for_update()
                )
                .mappings()
                .one()
            )
            if (
                current["status"] != "active"
                or current["lease_token"] != token
                or current["lease_expires_at"] <= datetime.now(UTC)
            ):
                raise CollectionLeaseLost("采集已暂停、超时或由新的执行接管")

        def saved(connection: Connection, snapshot: EvidenceSnapshotRecord) -> None:
            guard(connection)
            current = (
                connection.execute(select(table).where(table.c.id == claimed["id"]))
                .mappings()
                .one()
            )
            previous_digest = (
                connection.execute(
                    select(tables.evidence_snapshots.c.content_digest).where(
                        tables.evidence_snapshots.c.tenant_id == row["tenant_id"],
                        tables.evidence_snapshots.c.id == current["last_snapshot_id"],
                    )
                ).scalar_one_or_none()
                if current["last_snapshot_id"]
                else None
            )
            finished = datetime.now(UTC)
            connection.execute(
                runs.update()
                .where(runs.c.id == token, runs.c.status == "running")
                .values(
                    status="completed",
                    finished_at=finished,
                    snapshot_id=snapshot.id,
                    content_changed=previous_digest != snapshot.content_digest,
                )
            )
            after = (
                connection.execute(
                    table.update()
                    .where(table.c.id == claimed["id"])
                    .values(
                        last_snapshot_id=snapshot.id,
                        last_success_at=finished,
                        consecutive_failures=0,
                        last_error_code=None,
                        last_error_message=None,
                        next_due_at=next_collection(finished, current["frequency"]),
                        lease_token=None,
                        lease_expires_at=None,
                        version=current["version"] + 1,
                        updated_at=finished,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            _emit(
                connection,
                context,
                row["market_space_id"],
                "research_subscription",
                "collected",
                after,
                before=current,
            )

            from app.domain.supplier_notice_dispatches import enqueue

            enqueue(connection, row["tenant_id"], claimed["id"])

        try:
            collect_page(
                self.engine,
                context,
                space_id=claimed["market_space_id"],
                line_id=claimed["product_line_id"],
                source_id=claimed["source_id"],
                url=claimed["url"],
                freshness_days=claimed["freshness_days"],
                guard=guard,
                on_capture=saved,
            )
            return {"status": "completed"}
        except Exception as error:
            permanent = isinstance(
                error,
                (
                    ReachDeniedError,
                    ProductWorkAccessError,
                    ProductWorkError,
                    EvidenceValidationError,
                ),
            )
            code = (
                error.reason
                if isinstance(error, ReachDeniedError)
                else "COLLECTION_STOPPED"
                if isinstance(error, CollectionLeaseLost)
                else "COLLECTION_UNAVAILABLE"
            )
            message = (
                str(error)
                if isinstance(
                    error,
                    (
                        ReachDeniedError,
                        ReachFetchError,
                        ProductWorkAccessError,
                        ProductWorkError,
                        CollectionLeaseLost,
                    ),
                )
                else "来源采集失败，已安排后续处置"
            )
            with self.engine.begin() as connection:
                connection.execute(
                    select(tables.market_spaces.c.id)
                    .where(tables.market_spaces.c.id == claimed["market_space_id"])
                    .with_for_update()
                )
                current = (
                    connection.execute(
                        select(table).where(table.c.id == claimed["id"]).with_for_update()
                    )
                    .mappings()
                    .one()
                )
                if current["lease_token"] != token:
                    recorded = connection.execute(
                        select(runs.c.status).where(runs.c.id == token)
                    ).scalar_one()
                    return {"status": "completed" if recorded == "completed" else "discarded"}
                outcome = self._fail(
                    connection,
                    context,
                    current,
                    code,
                    message,
                    permanent=permanent,
                    run_status="timed_out" if isinstance(error, CollectionLeaseLost) else "failed",
                )
            return {"status": outcome}
