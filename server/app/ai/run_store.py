"""Agent run persistence ports for owner tests and restricted production execution."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from sqlalchemy import Connection, Engine, RowMapping, select, text, update

from app.ai.runtime_contract import FrozenRunContext
from app.db.schema import tables


@dataclass(frozen=True)
class ClaimedAgentRun:
    values: RowMapping | dict[str, Any]
    lease_token: UUID | None = None

    @property
    def id(self) -> UUID:
        return UUID(str(self.values["id"]))


class AgentRunStore(Protocol):
    projection_only: bool

    def claim(self, *, started_at: datetime) -> ClaimedAgentRun | None: ...

    def bind(self, connection: Connection) -> None: ...

    def scope(self, claim: ClaimedAgentRun) -> AbstractContextManager[None]: ...

    def persist_context(
        self,
        *,
        claim: ClaimedAgentRun,
        context: FrozenRunContext,
        persisted_at: datetime,
    ) -> None: ...

    def complete(
        self,
        *,
        claim: ClaimedAgentRun,
        status: Literal["succeeded", "degraded"],
        error_code: str | None,
        completed_at: datetime,
    ) -> None: ...

    def fail(
        self,
        *,
        claim: ClaimedAgentRun,
        error_code: str,
        completed_at: datetime,
    ) -> None: ...


class OwnerAgentRunStore:
    projection_only = False

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def claim(self, *, started_at: datetime) -> ClaimedAgentRun | None:
        with self._engine.begin() as connection:
            run = (
                connection.execute(
                    select(tables.agent_runs)
                    .where(tables.agent_runs.c.status == "queued")
                    .order_by(tables.agent_runs.c.created_at, tables.agent_runs.c.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                .mappings()
                .one_or_none()
            )
            if run is None:
                return None
            connection.execute(
                update(tables.agent_runs)
                .where(
                    tables.agent_runs.c.id == run["id"],
                    tables.agent_runs.c.status == "queued",
                )
                .values(status="running", started_at=started_at, updated_at=started_at)
            )
            return ClaimedAgentRun(values=dict(run))

    def bind(self, connection: Connection) -> None:
        del connection

    @contextmanager
    def scope(self, claim: ClaimedAgentRun) -> Iterator[None]:
        del claim
        yield

    def persist_context(
        self,
        *,
        claim: ClaimedAgentRun,
        context: FrozenRunContext,
        persisted_at: datetime,
    ) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                update(tables.agent_runs)
                .where(
                    tables.agent_runs.c.id == claim.id,
                    tables.agent_runs.c.status == "running",
                )
                .values(
                    context_version="run-context-v2",
                    run_context=context.model_dump(mode="json"),
                    updated_at=persisted_at,
                )
            )

    def complete(
        self,
        *,
        claim: ClaimedAgentRun,
        status: Literal["succeeded", "degraded"],
        error_code: str | None,
        completed_at: datetime,
    ) -> None:
        with self._engine.begin() as connection:
            run = (
                connection.execute(
                    select(tables.agent_runs)
                    .where(tables.agent_runs.c.id == claim.id)
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            connection.execute(
                update(tables.agent_runs)
                .where(
                    tables.agent_runs.c.id == claim.id,
                    tables.agent_runs.c.status == "running",
                )
                .values(
                    status=status,
                    completed_at=completed_at,
                    error_code=error_code,
                    updated_at=completed_at,
                )
            )
            connection.execute(
                update(tables.agent_subscriptions)
                .where(tables.agent_subscriptions.c.id == run["subscription_id"])
                .values(consecutive_failure_count=0, updated_at=completed_at)
            )

    def fail(
        self,
        *,
        claim: ClaimedAgentRun,
        error_code: str,
        completed_at: datetime,
    ) -> None:
        with self._engine.begin() as connection:
            run = (
                connection.execute(
                    select(tables.agent_runs)
                    .where(tables.agent_runs.c.id == claim.id)
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            subscription = (
                connection.execute(
                    select(tables.agent_subscriptions)
                    .where(tables.agent_subscriptions.c.id == run["subscription_id"])
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            failure_count = int(subscription["consecutive_failure_count"]) + 1
            threshold = int(subscription["failure_threshold"])
            connection.execute(
                update(tables.agent_runs)
                .where(
                    tables.agent_runs.c.id == claim.id,
                    tables.agent_runs.c.status == "running",
                )
                .values(
                    status="failed",
                    completed_at=completed_at,
                    error_code=error_code,
                    updated_at=completed_at,
                )
            )
            values: dict[str, object] = {
                "consecutive_failure_count": failure_count,
                "updated_at": completed_at,
            }
            if failure_count >= threshold:
                values.update(
                    status="paused",
                    paused_reason=(
                        "AGENT_RUN_FAILURE_THRESHOLD_REACHED:"
                        f"{error_code}:count={failure_count}:threshold={threshold}"
                    ),
                )
            connection.execute(
                update(tables.agent_subscriptions)
                .where(tables.agent_subscriptions.c.id == subscription["id"])
                .values(**values)
            )


class RestrictedAgentRunStore:
    projection_only = True

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._active_claim: ContextVar[ClaimedAgentRun | None] = ContextVar(
            "pdos_agent_run_claim",
            default=None,
        )

    def claim(self, *, started_at: datetime) -> ClaimedAgentRun | None:
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    text("SELECT * FROM cehub_ai.claim_agent_run(:started_at)"),
                    {"started_at": started_at},
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return ClaimedAgentRun(
            values={key: value for key, value in row.items() if key != "lease_token"},
            lease_token=UUID(str(row["lease_token"])),
        )

    def bind(self, connection: Connection) -> None:
        claim = self._active_claim.get()
        if claim is None or claim.lease_token is None:
            raise RuntimeError("restricted Agent database access has no active run lease")
        connection.execute(
            text("SELECT cehub_ai.bind_agent_scope(:run_id, :lease_token)"),
            {"run_id": claim.id, "lease_token": claim.lease_token},
        )

    @contextmanager
    def scope(self, claim: ClaimedAgentRun) -> Iterator[None]:
        if claim.lease_token is None:
            raise RuntimeError("restricted Agent run has no lease token")
        token = self._active_claim.set(claim)
        try:
            yield
        finally:
            self._active_claim.reset(token)

    def persist_context(
        self,
        *,
        claim: ClaimedAgentRun,
        context: FrozenRunContext,
        persisted_at: datetime,
    ) -> None:
        with self._engine.begin() as connection:
            self.bind(connection)
            connection.execute(
                text(
                    "SELECT cehub_ai.persist_agent_run_context("
                    ":run_id, :lease_token, CAST(:frozen_context AS jsonb), :persisted_at)"
                ),
                {
                    "run_id": claim.id,
                    "lease_token": claim.lease_token,
                    "frozen_context": context.model_dump_json(),
                    "persisted_at": persisted_at,
                },
            )

    def complete(
        self,
        *,
        claim: ClaimedAgentRun,
        status: Literal["succeeded", "degraded"],
        error_code: str | None,
        completed_at: datetime,
    ) -> None:
        with self._engine.begin() as connection:
            self.bind(connection)
            connection.execute(
                text(
                    "SELECT cehub_ai.complete_agent_run("
                    ":run_id, :lease_token, :status, :error_code, :completed_at)"
                ),
                {
                    "run_id": claim.id,
                    "lease_token": claim.lease_token,
                    "status": status,
                    "error_code": error_code,
                    "completed_at": completed_at,
                },
            )

    def fail(
        self,
        *,
        claim: ClaimedAgentRun,
        error_code: str,
        completed_at: datetime,
    ) -> None:
        with self._engine.begin() as connection:
            self.bind(connection)
            connection.execute(
                text(
                    "SELECT cehub_ai.fail_agent_run(:run_id, :lease_token, :error_code, :failed_at)"
                ),
                {
                    "run_id": claim.id,
                    "lease_token": claim.lease_token,
                    "error_code": error_code,
                    "failed_at": completed_at,
                },
            )
