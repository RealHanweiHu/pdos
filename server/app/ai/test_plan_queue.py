"""Queued test-plan conversations with the existing Finding and input-wait flow."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, and_, false, func, or_, select

from app.ai.application_leases import ApplicationLeaseKeeper
from app.ai.test_plan_suggestions import TestPlanSuggestionService
from app.auth.errors import ObjectPermissionDeniedError
from app.auth.project_access import ProjectAccessService, SqlProjectAccessRepository
from app.auth.repository import AuthContext, AuthRepository
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.test_plan_sources import SourceSelection

logger = logging.getLogger(__name__)


class TestPlanQueue:
    __test__ = False

    def __init__(self, engine: Engine, *, gateway: Any = None):
        self.engine, self.gateway = engine, gateway

    def _authorize(self, context: AuthContext, project: UUID) -> None:
        current = AuthRepository(self.engine).find_user_context(context.user.id)
        if (
            current is None
            or current.tenant.id != context.tenant.id
            or current.tenant.status != "active"
            or not current.user.is_active
            or current.user.auth_version != context.user.auth_version
        ):
            raise ObjectPermissionDeniedError
        ProjectAccessService(SqlProjectAccessRepository(self.engine)).authorize(
            context=current, project_id=project, action=Action.WORK_ITEM_EDIT
        )

    def submit(
        self,
        *,
        context: AuthContext,
        project_id: UUID,
        plan_id: UUID,
        message: str,
        request_id: UUID,
        previous_finding_id: UUID | None,
        sources: list[SourceSelection] | None = None,
        prompt_version: str | None = None,
    ) -> dict[str, Any]:
        self._authorize(context, project_id)
        result = TestPlanSuggestionService(self.engine, gateway=self.gateway).create(
            tenant_id=context.tenant.id,
            project_id=project_id,
            plan_id=plan_id,
            actor_user_id=context.user.id,
            auth_version=context.user.auth_version,
            message=message,
            request_id=request_id,
            previous_finding_id=previous_finding_id,
            sources=sources,
            enqueue=True,
            prompt_version=prompt_version,
        )
        return self.get(
            context=context, project_id=project_id, plan_id=plan_id, run_id=UUID(result["run_id"])
        )

    def get(
        self, *, context: AuthContext, project_id: UUID, plan_id: UUID, run_id: UUID
    ) -> dict[str, Any]:
        self._authorize(context, project_id)
        with self.engine.connect() as c:
            row = (
                c.execute(
                    select(tables.agent_runs).where(
                        tables.agent_runs.c.tenant_id == context.tenant.id,
                        tables.agent_runs.c.project_id == project_id,
                        tables.agent_runs.c.requested_by_user_id == context.user.id,
                        tables.agent_runs.c.id == run_id,
                        tables.agent_runs.c.context_version == "test-plan-request-v1",
                        tables.agent_runs.c.run_context["test_plan_request"]["plan_id"].as_string()
                        == str(plan_id),
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise ObjectPermissionDeniedError
        result = row["run_context"].get("result", {})
        return dict(
            run_id=str(run_id),
            status="cancelled"
            if row["error_code"] == "APPLICATION_REQUEST_CANCELLED"
            else row["status"],
            finding_id=result.get("finding_id"),
            error_code=row["error_code"],
        )

    def run_next(self) -> bool:
        recoverable = and_(
            tables.agent_runs.c.status == "degraded",
            tables.agent_runs.c.error_code == "APPLICATION_RUN_LEASE_EXPIRED",
            select(tables.application_result_checkpoints.c.id)
            .where(
                tables.application_result_checkpoints.c.tenant_id == tables.agent_runs.c.tenant_id,
                tables.application_result_checkpoints.c.run_id == tables.agent_runs.c.id,
            )
            .exists(),
        )
        with self.engine.connect() as c:
            row = (
                c.execute(
                    select(tables.agent_runs)
                    .where(
                        tables.agent_runs.c.context_version == "test-plan-request-v1",
                        tables.agent_runs.c.run_context["application_queue_version"].as_string()
                        == "1",
                        or_(tables.agent_runs.c.status == "queued", recoverable),
                    )
                    .order_by(tables.agent_runs.c.created_at, tables.agent_runs.c.id)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return False
        try:
            context = AuthRepository(self.engine).find_user_context(row["requested_by_user_id"])
            if context is None or context.tenant.id != row["tenant_id"]:
                raise ObjectPermissionDeniedError
            self._authorize(context, row["project_id"])
            request = row["run_context"]["test_plan_request"]
            TestPlanSuggestionService(self.engine, gateway=self.gateway).create(
                tenant_id=row["tenant_id"],
                project_id=row["project_id"],
                plan_id=UUID(request["plan_id"]),
                actor_user_id=context.user.id,
                auth_version=context.user.auth_version,
                message=request["message"],
                prompt_version=request.get("prompt_version"),
                request_id=UUID(request["request_id"]),
                previous_finding_id=UUID(request["previous_finding_id"])
                if request["previous_finding_id"]
                else None,
                sources=[SourceSelection.model_validate(s) for s in request["sources"]]
                if "sources" in request
                else None,
            )
        except Exception as error:
            raw = getattr(error, "code", str(error))
            code = (
                raw
                if raw.startswith(("APPLICATION_", "BUDGET_", "TEST_PLAN_")) and len(raw) <= 128
                else "TEST_PLAN_QUEUE_EXECUTION_FAILED"
            )
            if isinstance(error, ObjectPermissionDeniedError):
                code = "APPLICATION_AUTHORIZATION_CHANGED"
            keeper = getattr(self.gateway, "application_lease_keeper", None)
            acquired = (
                isinstance(keeper, ApplicationLeaseKeeper)
                and keeper.token(row["tenant_id"], row["id"]) is not None
            )
            # A rejected queued-input refresh rolls back acquisition; stop that row
            # even if the in-memory keeper saw its subsequently rolled-back token.
            with self.engine.begin() as c:
                c.execute(
                    tables.agent_runs.update()
                    .where(
                        tables.agent_runs.c.tenant_id == row["tenant_id"],
                        tables.agent_runs.c.id == row["id"],
                        or_(
                            tables.agent_runs.c.status == "queued",
                            recoverable if not acquired else false(),
                        ),
                    )
                    .values(
                        status="failed",
                        error_code=code,
                        completed_at=func.clock_timestamp(),
                        updated_at=func.clock_timestamp(),
                    )
                )
            logger.warning("application_test_plan_stopped run=%s reason=%s", row["id"], code)
        return True
