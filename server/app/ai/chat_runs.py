"""Trusted application metadata for one authenticated, read-only Chat request."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, func, select, update

from app.ai.application_leases import bind_write
from app.ai.application_recovery import try_resume
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.run_budget_creation import freeze_created_application_run
from app.db.schema import tables


class ChatRequestConflictError(ValueError):
    pass


class ChatRunStore:
    def __init__(self, engine: Engine, *, gateway: object = None):
        self._engine = engine
        self._gateway = gateway

    def start(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        auth_version: int | None = None,
        request_id: str,
        question: str,
        enqueue: bool = False,
        attachment_ids: tuple[UUID, ...] = (),
        object_focus: dict[str, Any] | None = None,
    ) -> tuple[RowMapping, bool]:
        with self._engine.begin() as connection:
            connection.execute(
                select(tables.tenants.c.id)
                .where(tables.tenants.c.id == tenant_id)
                .with_for_update()
            ).scalar_one()
            existing = (
                connection.execute(
                    select(tables.agent_runs)
                    .where(
                        tables.agent_runs.c.tenant_id == tenant_id,
                        tables.agent_runs.c.project_id == project_id,
                        tables.agent_runs.c.agent_key == "ai_chat",
                        tables.agent_runs.c.request_id == request_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                if (
                    existing["requested_by_user_id"] != actor_user_id
                    or existing["run_context"].get("chat_question") != question
                    or existing["run_context"].get("chat_attachment_ids", [])
                    != [str(a) for a in attachment_ids]
                    or existing["run_context"].get("chat_object_focus") != object_focus
                ):
                    raise ChatRequestConflictError("CHAT_REQUEST_CONFLICT")
                if enqueue:
                    return existing, False
                if existing["status"] == "queued":
                    return self._claim(connection, existing, auth_version), True
                if try_resume(
                    connection,
                    self._gateway,
                    existing,
                    actor=actor_user_id,
                    auth_version=auth_version,
                    purpose="chat_answer",
                ):
                    return existing, True
                if existing["status"] == "running":
                    raise ChatRequestConflictError("CHAT_REQUEST_CONFLICT")
                return existing, False
            if enqueue and getattr(self._gateway, "creation_budget_profile", None) is None:
                raise BudgetLedgerError("APPLICATION_QUEUE_BUDGET_REQUIRED")
            now = connection.execute(select(func.clock_timestamp())).scalar_one()
            row = (
                connection.execute(
                    tables.agent_runs.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        project_id=project_id,
                        agent_key="ai_chat",
                        request_id=request_id,
                        requested_by_user_id=actor_user_id,
                        status="running",
                        window_started_at=now,
                        window_ended_at=now,
                        event_count=0,
                        event_row_ids=[],
                        context_version="chat-request-object-v1"
                        if object_focus
                        else "chat-request-v1",
                        run_context={
                            "chat_question": question,
                            **({"chat_object_focus": object_focus} if object_focus else {}),
                            **(
                                {"chat_attachment_ids": [str(a) for a in attachment_ids]}
                                if attachment_ids
                                else {}
                            ),
                            **({"application_queue_version": 1} if enqueue else {}),
                        },
                        started_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                    .returning(tables.agent_runs)
                )
                .mappings()
                .one()
            )
            freeze_created_application_run(
                connection,
                self._gateway,
                tenant_id=tenant_id,
                run_id=row["id"],
                actor_user_id=actor_user_id,
                purpose="chat_answer",
                auth_version=auth_version,
                issue_lease=not enqueue,
            )
            if enqueue:
                row = (
                    connection.execute(
                        tables.agent_runs.update()
                        .where(tables.agent_runs.c.id == row["id"])
                        .values(status="queued", started_at=None, updated_at=func.clock_timestamp())
                        .returning(tables.agent_runs)
                    )
                    .mappings()
                    .one()
                )
            return row, True

    def _claim(self, c: Connection, row: RowMapping, auth_version: int | None) -> RowMapping:
        from app.ai.application_queue_claim import claim_application_queue

        return claim_application_queue(
            c, self._gateway, row, auth_version=auth_version, purpose="chat_answer"
        )

    def save_evidence(
        self, *, tenant_id: UUID, run_id: UUID, evidence: list[dict[str, Any]]
    ) -> None:
        self._write(tenant_id, run_id, {"chat_evidence": evidence})

    def finish(self, *, tenant_id: UUID, run_id: UUID, result: dict[str, Any]) -> None:
        self._write(tenant_id, run_id, {"chat_result": result}, result=result)

    def _write(
        self,
        tenant: UUID,
        run: UUID,
        context_changes: dict[str, Any],
        *,
        result: dict[str, Any] | None = None,
    ) -> None:
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(tables.agent_runs)
                    .where(
                        tables.agent_runs.c.tenant_id == tenant,
                        tables.agent_runs.c.id == run,
                        tables.agent_runs.c.agent_key == "ai_chat",
                    )
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            if row["status"] != "running":
                raise ChatRequestConflictError("CHAT_REQUEST_ALREADY_FINISHED")
            bind_write(
                connection,
                self._gateway,
                tenant,
                run,
                success=result is None or result["status"] != "unavailable",
            )
            now = connection.execute(select(func.clock_timestamp())).scalar_one()
            changes: dict[str, Any] = {
                "run_context": {**row["run_context"], **context_changes},
                "updated_at": now,
            }
            if result is not None:
                degraded = result["status"] == "unavailable"
                changes.update(
                    status="degraded" if degraded else "succeeded",
                    completed_at=now,
                    error_code=result["error_code"] if degraded else None,
                )
            connection.execute(
                update(tables.agent_runs)
                .where(
                    tables.agent_runs.c.tenant_id == tenant,
                    tables.agent_runs.c.id == run,
                )
                .values(**changes)
            )
