"""Durable in-flight registration and owner-controlled model admission transitions.

Compatibility registers calls without claiming atomic legacy token reservations.
Draining waits indefinitely for evidence: timeout never releases an unknown call.
This service does not qualify meters, authorize deployments, or stop old binaries.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, select, text

from app.ai.budget_accounting import unbound_usage
from app.ai.budget_ledger import BudgetLedger
from app.ai.run_store import AgentRunStore
from app.db.schema import tables


class ModelCallFenceError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ModelCallFence:
    def __init__(self, engine: Engine, run_store: AgentRunStore | None = None):
        self._engine = engine
        self._run_store = run_store

    @property
    def restricted(self) -> bool:
        return self._run_store is not None and self._run_store.projection_only

    def begin(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID | None,
        project_id: UUID | None,
        agent_key: str,
        budgeted: bool,
    ) -> UUID:
        with self._engine.begin() as connection:
            if self.restricted:
                assert self._run_store is not None
                self._run_store.bind(connection)
                statement = (
                    "SELECT * FROM cehub_ai.agent_open_budgeted_model_call()"
                    if budgeted
                    else "SELECT * FROM cehub_ai.agent_open_model_call()"
                )
                params = {}
            else:
                statement = (
                    "SELECT * FROM cehub_ai.open_model_call(:tenant, :run, :project, :agent, :mode)"
                )
                params = dict(
                    tenant=tenant_id,
                    run=run_id,
                    project=project_id,
                    agent=agent_key,
                    mode="budgeted" if budgeted else "legacy",
                )
            row = connection.execute(text(statement), params).mappings().one()
            if row["error_code"] is not None:
                raise ModelCallFenceError(row["error_code"])
            return UUID(str(row["session_id"]))

    def finish(
        self,
        *,
        tenant_id: UUID,
        session_id: UUID,
        invocation_id: UUID,
        before_commit: Callable[[Connection], None] | None = None,
    ) -> None:
        self._transition("finish_model_call", tenant_id, session_id, invocation_id, before_commit)

    def unknown(self, *, tenant_id: UUID, session_id: UUID) -> None:
        self._transition("mark_model_call_unknown", tenant_id, session_id)

    def _transition(
        self,
        function: str,
        tenant: UUID,
        session: UUID,
        invocation: UUID | None = None,
        before_commit: Callable[[Connection], None] | None = None,
    ) -> None:
        with self._engine.begin() as connection:
            args = ":tenant, :session"
            if self.restricted:
                assert self._run_store is not None
                self._run_store.bind(connection)
                function = "agent_" + function
                args = ":session"
            if invocation is not None:
                args += ", :invocation"
            connection.execute(
                text(f"SELECT cehub_ai.{function}({args})"),
                dict(tenant=tenant, session=session, invocation=invocation),
            )

            if before_commit is not None:
                before_commit(connection)


class ModelCallModeService:
    """Owner/service port; never an Agent tool. Revision is required for every change."""

    def __init__(self, engine: Engine):
        self._engine = engine

    @staticmethod
    def _latest(connection: Connection, tenant: UUID) -> RowMapping | None:
        return (
            connection.execute(
                select(tables.model_call_mode_events)
                .where(tables.model_call_mode_events.c.tenant_id == tenant)
                .order_by(tables.model_call_mode_events.c.revision.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )

    def change(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        expected_revision: int,
        action: Literal["request", "complete", "cancel"],
        evidence_ref: str,
        target: Literal["compatibility", "budgeted"] | None = None,
    ) -> int:
        if (
            type(expected_revision) is not int
            or expected_revision < 0
            or not evidence_ref.strip()
            or action not in {"request", "complete", "cancel"}
            or (action == "request" and target not in {"compatibility", "budgeted"})
            or (action != "request" and target is not None)
        ):
            raise ModelCallFenceError("MODEL_CALL_TRANSITION_INVALID")
        with self._engine.begin() as connection:
            now = BudgetLedger._lock(connection, tenant_id)
            actor = connection.execute(
                select(tables.users.c.id)
                .where(
                    tables.users.c.tenant_id == tenant_id,
                    tables.users.c.id == actor_user_id,
                    tables.users.c.is_active.is_(True),
                    tables.users.c.role.in_(["owner", "admin"]),
                )
                .with_for_update(read=True)
            ).first()
            if actor is None:
                raise ModelCallFenceError("MODEL_CALL_TRANSITION_FORBIDDEN")
            latest = self._latest(connection, tenant_id)
            revision = latest["revision"] if latest is not None else 0
            mode = latest["mode"] if latest is not None else "compatibility"
            if revision != expected_revision:
                raise ModelCallFenceError("MODEL_CALL_REVISION_CONFLICT")
            if action == "request":
                if mode == "draining" or mode == target:
                    raise ModelCallFenceError("MODEL_CALL_TRANSITION_INVALID")
                previous, next_mode, next_target = mode, "draining", target
            else:
                if latest is None or mode != "draining":
                    raise ModelCallFenceError("MODEL_CALL_TRANSITION_INVALID")
                previous = latest["previous_mode"]
                next_mode = previous if action == "cancel" else latest["target_mode"]
                next_target = None
                if action == "complete":
                    calls = (
                        select(tables.model_call_events)
                        .where(tables.model_call_events.c.tenant_id == tenant_id)
                        .distinct(tables.model_call_events.c.session_id)
                        .order_by(
                            tables.model_call_events.c.session_id,
                            tables.model_call_events.c.revision.desc(),
                        )
                        .subquery()
                    )
                    if connection.execute(
                        select(calls.c.id).where(calls.c.state != "closed").limit(1)
                    ).first():
                        raise ModelCallFenceError("MODEL_CALL_IN_FLIGHT")
                    journal = list(
                        connection.execute(
                            select(tables.budget_journal)
                            .where(tables.budget_journal.c.tenant_id == tenant_id)
                            .distinct(tables.budget_journal.c.attempt_id)
                            .order_by(
                                tables.budget_journal.c.attempt_id,
                                tables.budget_journal.c.revision.desc(),
                            )
                        ).mappings()
                    )
                    if any(row["reservation_status"] in {"reserved", "unknown"} for row in journal):
                        raise ModelCallFenceError("MODEL_CALL_BUDGET_UNRESOLVED")
                    if unbound_usage(
                        connection, tenant=tenant_id, now=now, journal=journal
                    ).unresolved_invocation_ids:
                        raise ModelCallFenceError("MODEL_CALL_USAGE_UNRESOLVED")
            connection.execute(
                tables.model_call_mode_events.insert(),
                dict(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    revision=revision + 1,
                    mode=next_mode,
                    previous_mode=previous,
                    target_mode=next_target,
                    actor_user_id=actor_user_id,
                    evidence_ref=evidence_ref,
                    created_at=now,
                ),
            )
            return revision + 1
