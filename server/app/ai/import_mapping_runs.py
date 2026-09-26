"""Application-owned metadata for a user's fixed report-mapping request."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, RowMapping, func, select, update

from app.ai.application_leases import bind_write
from app.ai.application_queue_claim import claim_application_queue
from app.ai.application_recovery import try_resume
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.run_budget_creation import freeze_created_application_run
from app.db.schema import tables


class ImportMappingRunError(ValueError):
    pass


class ImportMappingRunStore:
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
        request_context: dict[str, Any],
        enqueue: bool = False,
        claim_queue: bool = False,
    ) -> tuple[RowMapping, bool]:
        if enqueue and getattr(self._gateway, "creation_budget_profile", None) is None:
            raise BudgetLedgerError("APPLICATION_QUEUE_BUDGET_REQUIRED")
        with self._engine.begin() as c:
            c.execute(
                select(tables.tenants.c.id)
                .where(tables.tenants.c.id == tenant_id)
                .with_for_update()
            ).scalar_one()
            row = (
                c.execute(
                    select(tables.agent_runs).where(
                        tables.agent_runs.c.tenant_id == tenant_id,
                        tables.agent_runs.c.project_id == project_id,
                        tables.agent_runs.c.agent_key == "quality_intelligence",
                        tables.agent_runs.c.request_id == request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is not None:
                if (
                    row["requested_by_user_id"] != actor_user_id
                    or row["context_version"] != "report-mapping-request-v1"
                    or row["run_context"].get("mapping_request") != request_context
                ):
                    raise ImportMappingRunError("IMPORT_MAPPING_REQUEST_CONFLICT")
                if enqueue:
                    return row, False
                if (
                    row["run_context"].get("application_queue_version") == 1
                    and row["status"] != "succeeded"
                    and not claim_queue
                ):
                    raise ImportMappingRunError("IMPORT_MAPPING_REQUEST_CONFLICT")
                if (
                    row["status"] == "queued"
                    and row["run_context"].get("application_queue_version") == 1
                ):
                    return claim_application_queue(
                        c, self._gateway, row, auth_version=auth_version, purpose="report_mapping"
                    ), True
                if try_resume(
                    c,
                    self._gateway,
                    row,
                    actor=actor_user_id,
                    auth_version=auth_version,
                    purpose="report_mapping",
                ):
                    return row, True
                if row["status"] == "running":
                    raise ImportMappingRunError("IMPORT_MAPPING_REQUEST_CONFLICT")
                return row, False
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            row = (
                c.execute(
                    tables.agent_runs.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        project_id=project_id,
                        agent_key="quality_intelligence",
                        request_id=request_id,
                        requested_by_user_id=actor_user_id,
                        status="running",
                        window_started_at=now,
                        window_ended_at=now,
                        event_count=0,
                        event_row_ids=[],
                        context_version="report-mapping-request-v1",
                        run_context={
                            "mapping_request": request_context,
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
                c,
                self._gateway,
                tenant_id=tenant_id,
                run_id=row["id"],
                actor_user_id=actor_user_id,
                purpose="report_mapping",
                auth_version=auth_version,
                issue_lease=not enqueue,
            )
            if enqueue:
                row = (
                    c.execute(
                        tables.agent_runs.update()
                        .where(tables.agent_runs.c.id == row["id"])
                        .values(status="queued", started_at=None, updated_at=func.clock_timestamp())
                        .returning(tables.agent_runs)
                    )
                    .mappings()
                    .one()
                )
            return row, True

    def finish(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID,
        mapping: dict[str, Any] | None,
        error_code: str | None = None,
        invocation_id: UUID | None = None,
    ) -> None:
        if (mapping is None) != (error_code is not None):
            raise ValueError("mapping completion requires either result or error")
        with self._engine.begin() as c:
            row = (
                c.execute(
                    select(tables.agent_runs)
                    .where(
                        tables.agent_runs.c.tenant_id == tenant_id,
                        tables.agent_runs.c.id == run_id,
                        tables.agent_runs.c.agent_key == "quality_intelligence",
                        tables.agent_runs.c.context_version == "report-mapping-request-v1",
                        tables.agent_runs.c.request_id.is_not(None),
                    )
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            if row["status"] != "running":
                raise ImportMappingRunError("IMPORT_MAPPING_REQUEST_ALREADY_FINISHED")
            bind_write(c, self._gateway, tenant_id, run_id, success=mapping is not None)
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            keep_running = (
                mapping is not None and row["run_context"].get("application_queue_version") == 1
            )
            c.execute(
                update(tables.agent_runs)
                .where(tables.agent_runs.c.id == run_id, tables.agent_runs.c.tenant_id == tenant_id)
                .values(
                    status="running"
                    if keep_running
                    else "succeeded"
                    if mapping is not None
                    else "degraded",
                    error_code=error_code,
                    completed_at=None if keep_running else now,
                    updated_at=now,
                    run_context={
                        **row["run_context"],
                        "mapping_result": mapping,
                        "model_invocation_id": str(invocation_id) if invocation_id else None,
                    },
                )
            )
