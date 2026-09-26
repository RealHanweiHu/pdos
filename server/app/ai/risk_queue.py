"""Persistent risk requests executed by the existing application worker."""

from __future__ import annotations

import logging
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine, RowMapping, and_, func, or_, select

from app.ai.application_gateway import ApplicationModelGateway
from app.ai.application_leases import ApplicationLeaseKeeper
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.risk_suggestions import RiskSuggestionRequestConflictError, RiskSuggestionService
from app.auth.errors import ObjectPermissionDeniedError
from app.auth.project_access import ProjectAccessService, SqlProjectAccessRepository
from app.auth.repository import AuthContext, AuthRepository
from app.auth.roles import Action, is_allowed
from app.db.schema import tables

logger = logging.getLogger(__name__)


class RiskQueueReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_id: UUID
    project_id: UUID
    request_id: str
    status: str
    finding_id: UUID | None
    error_code: str | None


class RiskQueue:
    def __init__(self, engine: Engine, *, gateway: ApplicationModelGateway):
        self.engine, self.gateway = engine, gateway

    def _authorize(self, context: AuthContext, project: UUID) -> None:
        current = AuthRepository(self.engine).find_user_context(context.user.id)
        if (
            current is None
            or current.tenant.id != context.tenant.id
            or current.tenant.status != "active"
            or not current.user.is_active
            or current.user.auth_version != context.user.auth_version
            or not is_allowed(current.user.role, Action.RISK_SUGGESTION_CREATE)
        ):
            raise ObjectPermissionDeniedError
        ProjectAccessService(SqlProjectAccessRepository(self.engine)).authorize(
            context=current, project_id=project, action=Action.PROJECT_VIEW
        )

    def submit(
        self,
        *,
        context: AuthContext,
        project_id: UUID,
        request_id: str,
        concern: str,
        evidence_event_ids: tuple[int, ...],
    ) -> RiskQueueReceipt:
        self._authorize(context, project_id)
        result = RiskSuggestionService(self.engine, gateway=self.gateway).create(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            auth_version=context.user.auth_version,
            request_id=request_id,
            concern=concern,
            evidence_event_ids=evidence_event_ids,
            enqueue=True,
        )
        return self.get(context=context, run_id=result.run_id)

    def get(self, *, context: AuthContext, run_id: UUID) -> RiskQueueReceipt:
        with self.engine.connect() as c:
            row = (
                c.execute(
                    select(tables.agent_runs).where(
                        tables.agent_runs.c.tenant_id == context.tenant.id,
                        tables.agent_runs.c.requested_by_user_id == context.user.id,
                        tables.agent_runs.c.id == run_id,
                        tables.agent_runs.c.context_version == "risk-suggestion-request-v1",
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ObjectPermissionDeniedError
            self._authorize(context, row["project_id"])
            finding = c.execute(
                select(tables.findings.c.id).where(
                    tables.findings.c.tenant_id == context.tenant.id,
                    tables.findings.c.run_id == run_id,
                )
            ).scalar_one_or_none()
        return RiskQueueReceipt(
            run_id=run_id,
            project_id=row["project_id"],
            request_id=row["request_id"],
            status="cancelled"
            if row["error_code"] == "APPLICATION_REQUEST_CANCELLED"
            else row["status"],
            finding_id=finding,
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
            row: RowMapping | None = (
                c.execute(
                    select(tables.agent_runs)
                    .where(
                        tables.agent_runs.c.context_version == "risk-suggestion-request-v1",
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
            RiskSuggestionService(self.engine, gateway=self.gateway).create(
                tenant_id=row["tenant_id"],
                project_id=row["project_id"],
                actor_user_id=context.user.id,
                auth_version=context.user.auth_version,
                request_id=row["request_id"],
                concern=row["run_context"]["api_concern"],
                evidence_event_ids=tuple(row["event_row_ids"]),
            )
        except RiskSuggestionRequestConflictError:
            pass
        except Exception as error:
            code = (
                error.code
                if isinstance(error, BudgetLedgerError)
                else "APPLICATION_AUTHORIZATION_CHANGED"
                if isinstance(error, ObjectPermissionDeniedError)
                else "APPLICATION_QUEUE_EXECUTION_FAILED"
            )
            keeper = getattr(self.gateway, "application_lease_keeper", None)
            acquired = (
                isinstance(keeper, ApplicationLeaseKeeper)
                and keeper.token(row["tenant_id"], row["id"]) is not None
            )
            if not acquired:
                with self.engine.begin() as c:
                    c.execute(
                        tables.agent_runs.update()
                        .where(
                            tables.agent_runs.c.tenant_id == row["tenant_id"],
                            tables.agent_runs.c.id == row["id"],
                            or_(tables.agent_runs.c.status == "queued", recoverable),
                        )
                        .values(
                            status="failed",
                            error_code=code,
                            completed_at=func.clock_timestamp(),
                            updated_at=func.clock_timestamp(),
                        )
                    )
            logger.warning("application_risk_stopped run=%s reason=%s", row["id"], code)
        return True
