"""Tenant-scoped id-cursor dispatcher with deterministic Project debounce windows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import Engine, Select, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection, RowMapping

from app.ai.budget_adoption import approved_budget_profile
from app.ai.loop_policy import LoopBinding
from app.ai.rollout_guard import CapabilityUnavailableError, require_employee_agent
from app.ai.runtime_contract import AgentKey, agents_for_event
from app.db.schema import tables

DEFAULT_CONSUMER_KEY = "agent_dispatcher_v1"


@dataclass(frozen=True)
class DispatchResult:
    scanned_event_count: int
    routed_event_count: int
    created_run_count: int
    merged_event_count: int
    last_event_row_id: int


@dataclass(frozen=True)
class SealResult:
    queued_run_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class DispatchCycleResult:
    tenant_count: int
    scanned_event_count: int
    routed_event_count: int
    created_run_count: int
    merged_event_count: int
    queued_run_count: int
    recovered_run_count: int = 0
    stopped_run_count: int = 0


class AgentDispatcher:
    def __init__(
        self,
        engine: Engine,
        *,
        debounce_minutes: int = 15,
        batch_size: int = 500,
        consumer_key: str = DEFAULT_CONSUMER_KEY,
        budget_profile_key: str | None = None,
        scheduling: Literal["legacy", "approved"] = "legacy",
        loop_binding: LoopBinding | None = None,
    ) -> None:
        if not 1 <= debounce_minutes <= 24 * 60:
            raise ValueError("debounce window must be between 1 minute and 1 day")
        if not 1 <= batch_size <= 5_000:
            raise ValueError("dispatcher batch size must be between 1 and 5000")
        if not consumer_key.strip():
            raise ValueError("dispatcher consumer key must be nonblank")
        if scheduling not in {"legacy", "approved"}:
            raise ValueError("unknown event scheduling policy")
        self._scheduling = scheduling
        if loop_binding is not None and budget_profile_key is None:
            raise ValueError("bounded tool loop requires a creation-time run budget")
        self._loop_binding = loop_binding
        self._engine = engine
        self._debounce_minutes = debounce_minutes
        self._batch_size = batch_size
        self._consumer_key = consumer_key
        self._budget_profile_key = (
            approved_budget_profile(budget_profile_key).key
            if budget_profile_key is not None
            else None
        )

    def dispatch_tenant(self, *, tenant_id: UUID) -> DispatchResult:
        with self._engine.begin() as connection:
            # Always set/reset within this transaction; pooled sessions cannot inherit policy.
            connection.execute(
                text("SELECT set_config('pdos.event_budget_profile', :profile, true)"),
                {"profile": self._budget_profile_key or ""},
            )
            connection.execute(
                text("SELECT set_config('pdos.event_loop_binding', :binding, true)"),
                {"binding": self._loop_binding.model_dump_json() if self._loop_binding else ""},
            )
            self._lock_tenant_consumer(connection, tenant_id=tenant_id)
            cursor = self._cursor(connection, tenant_id=tenant_id)
            rows = list(
                connection.execute(
                    select(tables.events)
                    .where(
                        tables.events.c.tenant_id == tenant_id,
                        tables.events.c.id > cursor["last_event_row_id"],
                    )
                    .order_by(tables.events.c.id)
                    .limit(self._batch_size)
                ).mappings()
            )

            routed_count = 0
            created_count = 0
            merged_count = 0
            for event in rows:
                project_id = event["project_id"]
                if project_id is None:
                    continue
                for agent_key in agents_for_event(str(event["event_type"])):
                    try:
                        require_employee_agent(agent_key)
                    except CapabilityUnavailableError:
                        continue
                    subscription = self._subscription(
                        connection,
                        tenant_id=tenant_id,
                        agent_key=agent_key,
                    )
                    if subscription["status"] != "active":
                        continue
                    routed_count += 1
                    created = self._route_event(
                        connection,
                        event=event,
                        subscription=subscription,
                        agent_key=agent_key,
                    )
                    created_count += int(created)
                    merged_count += int(not created)

            last_event_row_id = int(rows[-1]["id"]) if rows else int(cursor["last_event_row_id"])
            if rows:
                connection.execute(
                    update(tables.agent_dispatcher_cursors)
                    .where(tables.agent_dispatcher_cursors.c.id == cursor["id"])
                    .values(last_event_row_id=last_event_row_id, updated_at=datetime.now(UTC))
                )

        return DispatchResult(
            scanned_event_count=len(rows),
            routed_event_count=routed_count,
            created_run_count=created_count,
            merged_event_count=merged_count,
            last_event_row_id=last_event_row_id,
        )

    def dispatch_once(self, *, now: datetime | None = None) -> DispatchCycleResult:
        with self._engine.begin() as connection:
            expired = connection.execute(
                text("SELECT cehub_ai.expire_queued_dispatch_runs(1000)")
            ).scalar_one()
            expired += connection.execute(
                text("SELECT cehub_ai.expire_application_runs(100)")
            ).scalar_one()
            recoveries = list(
                connection.execute(
                    text("SELECT * FROM cehub_ai.recover_expired_agent_runs(100)")
                ).mappings()
            )
        with self._engine.connect() as connection:
            tenant_ids = tuple(
                UUID(str(value))
                for value in connection.execute(
                    select(tables.events.c.tenant_id).distinct().order_by(tables.events.c.tenant_id)
                ).scalars()
            )
        results = [self.dispatch_tenant(tenant_id=tenant_id) for tenant_id in tenant_ids]
        sealed = self.seal_due_runs(now=now)
        return DispatchCycleResult(
            tenant_count=len(tenant_ids),
            scanned_event_count=sum(result.scanned_event_count for result in results),
            routed_event_count=sum(result.routed_event_count for result in results),
            created_run_count=sum(result.created_run_count for result in results),
            merged_event_count=sum(result.merged_event_count for result in results),
            queued_run_count=len(sealed.queued_run_ids),
            recovered_run_count=sum(r["action"] != "stopped" for r in recoveries),
            stopped_run_count=expired + sum(r["action"] == "stopped" for r in recoveries),
        )

    def seal_due_runs(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> SealResult:
        if not 1 <= limit <= 1_000:
            raise ValueError("seal batch size must be between 1 and 1000")
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        queued_run_ids: list[UUID] = []
        with self._engine.begin() as connection:
            due_runs = list(
                connection.execute(
                    select(tables.agent_runs)
                    .where(
                        tables.agent_runs.c.status == "debouncing",
                        tables.agent_runs.c.window_ended_at <= current_time,
                    )
                    .order_by(tables.agent_runs.c.window_ended_at, tables.agent_runs.c.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                ).mappings()
            )
            for run in due_runs:
                connection.execute(
                    update(tables.agent_runs)
                    .where(
                        tables.agent_runs.c.id == run["id"],
                        tables.agent_runs.c.status == "debouncing",
                    )
                    .values(
                        status="queued",
                        updated_at=current_time,
                    )
                )
                queued_run_ids.append(run["id"])
        return SealResult(queued_run_ids=tuple(queued_run_ids))

    def _lock_tenant_consumer(self, connection: Connection, *, tenant_id: UUID) -> None:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
            {"scope": f"{tenant_id}:{self._consumer_key}"},
        )

    def _cursor(self, connection: Connection, *, tenant_id: UUID) -> RowMapping:
        statement = self._cursor_statement(tenant_id=tenant_id).with_for_update()
        existing = connection.execute(statement).mappings().one_or_none()
        if existing is not None:
            return existing
        connection.execute(
            tables.agent_dispatcher_cursors.insert(),
            {
                "id": uuid4(),
                "tenant_id": tenant_id,
                "consumer_key": self._consumer_key,
            },
        )
        return connection.execute(statement).mappings().one()

    def _cursor_statement(self, *, tenant_id: UUID) -> Select[tuple[object, ...]]:
        return select(tables.agent_dispatcher_cursors).where(
            tables.agent_dispatcher_cursors.c.tenant_id == tenant_id,
            tables.agent_dispatcher_cursors.c.consumer_key == self._consumer_key,
        )

    @staticmethod
    def _subscription(
        connection: Connection,
        *,
        tenant_id: UUID,
        agent_key: AgentKey,
    ) -> RowMapping:
        statement = select(tables.agent_subscriptions).where(
            tables.agent_subscriptions.c.tenant_id == tenant_id,
            tables.agent_subscriptions.c.agent_key == agent_key.value,
        )
        existing = connection.execute(statement).mappings().one_or_none()
        if existing is not None:
            return existing
        connection.execute(
            tables.agent_subscriptions.insert(),
            {
                "id": uuid4(),
                "tenant_id": tenant_id,
                "agent_key": agent_key.value,
            },
        )
        return connection.execute(statement).mappings().one()

    def _route_event(
        self,
        connection: Connection,
        *,
        event: RowMapping,
        subscription: RowMapping,
        agent_key: AgentKey,
    ) -> bool:
        occurred_at = event["timestamp"].astimezone(UTC)
        window_started_at = self._window_start(occurred_at)
        window_ended_at = window_started_at + timedelta(minutes=self._debounce_minutes)
        dispatch_key = dispatch_policy = None
        dispatch_deadline = None
        if self._scheduling == "approved":
            from app.worker.trigger_policy import policy_for_event

            policy = policy_for_event(str(event["event_type"]))
            dispatch_policy = f"{policy}.v1"
            if policy == "milestone":
                dispatch_key = f"event:{event['id']}"
                window_started_at = window_ended_at = occurred_at
                dispatch_deadline = occurred_at + timedelta(seconds=180)
            else:
                # Approved frequent edit policy is always 900 seconds.
                epoch_seconds = int(occurred_at.timestamp())
                window_started_at = datetime.fromtimestamp(epoch_seconds // 900 * 900, UTC)
                window_ended_at = window_started_at + timedelta(seconds=900)
                dispatch_key = f"window:{int(window_started_at.timestamp())}"

        run_statement = (
            select(tables.agent_runs)
            .where(
                tables.agent_runs.c.tenant_id == event["tenant_id"],
                tables.agent_runs.c.project_id == event["project_id"],
                tables.agent_runs.c.agent_key == agent_key.value,
                tables.agent_runs.c.window_started_at == window_started_at,
                tables.agent_runs.c.dispatch_key == dispatch_key,
            )
            .with_for_update()
        )
        existing = connection.execute(run_statement).mappings().one_or_none()
        if (
            existing is not None
            and self._scheduling == "approved"
            and existing["status"] != "debouncing"
            and int(event["id"]) not in existing["event_row_ids"]
        ):
            # A late event after a sealed window is new work, not a duplicate.
            dispatch_key = f"{dispatch_key}:late:{event['id']}"
            existing = (
                connection.execute(
                    select(tables.agent_runs)
                    .where(
                        tables.agent_runs.c.tenant_id == event["tenant_id"],
                        tables.agent_runs.c.project_id == event["project_id"],
                        tables.agent_runs.c.agent_key == agent_key.value,
                        tables.agent_runs.c.dispatch_key == dispatch_key,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
        if existing is None:
            run_id = uuid4()
            connection.execute(
                insert(tables.agent_runs).values(
                    id=run_id,
                    tenant_id=event["tenant_id"],
                    project_id=event["project_id"],
                    subscription_id=subscription["id"],
                    agent_key=agent_key.value,
                    status="debouncing",
                    window_started_at=window_started_at,
                    window_ended_at=window_ended_at,
                    dispatch_key=dispatch_key,
                    dispatch_policy=dispatch_policy,
                    dispatch_deadline=dispatch_deadline,
                    first_event_row_id=event["id"],
                    last_event_row_id=event["id"],
                    event_count=1,
                    event_row_ids=[event["id"]],
                )
            )
            if dispatch_policy == "milestone.v1":
                # Budget freezing runs on the initial debouncing INSERT. Queue within
                # this same transaction so no polling or 15-minute window is required.
                connection.execute(
                    update(tables.agent_runs)
                    .where(tables.agent_runs.c.id == run_id)
                    .values(status="queued")
                )
            return True
        if existing["status"] != "debouncing":
            return False

        event_ids = [int(value) for value in existing["event_row_ids"]]
        event_id = int(event["id"])
        if event_id in event_ids:
            return False
        event_ids.append(event_id)
        event_ids.sort()
        connection.execute(
            update(tables.agent_runs)
            .where(tables.agent_runs.c.id == existing["id"])
            .values(
                last_event_row_id=event_ids[-1],
                event_count=len(event_ids),
                event_row_ids=event_ids,
                updated_at=datetime.now(UTC),
            )
        )
        return False

    def _window_start(self, occurred_at: datetime) -> datetime:
        normalized = occurred_at.astimezone(UTC)
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        elapsed_minutes = int((normalized - epoch).total_seconds() // 60)
        window_minutes = (elapsed_minutes // self._debounce_minutes) * self._debounce_minutes
        return epoch + timedelta(minutes=window_minutes)
