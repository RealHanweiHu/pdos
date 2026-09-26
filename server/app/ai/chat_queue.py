"""Persistent user Chat queue, served by the Owner application worker."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine, RowMapping, and_, func, or_, select

from app.ai.application_gateway import ApplicationModelGateway
from app.ai.application_leases import ApplicationLeaseKeeper
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.chat import ChatResult, ChatService
from app.ai.chat_runs import ChatRequestConflictError, ChatRunStore
from app.ai.embeddings import EmbeddingGateway
from app.auth.errors import ObjectPermissionDeniedError
from app.auth.repository import AuthContext, AuthRepository
from app.db.schema import tables

logger = logging.getLogger(__name__)


class ChatQueueReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_id: UUID
    project_id: UUID
    request_id: str
    status: str
    created_at: datetime
    started_at: datetime | None
    error_code: str | None
    result: ChatResult | None


class ChatQueue:
    def __init__(self, engine: Engine, *, gateway: ApplicationModelGateway):
        self.engine = engine
        self.gateway = gateway
        self.chat = ChatService(engine, gateway=gateway)

    def submit(
        self,
        *,
        context: AuthContext,
        project_id: UUID,
        question: str,
        request_id: str,
        attachment_ids: tuple[UUID, ...] = (),
        object_focus: dict[str, Any] | None = None,
    ) -> ChatQueueReceipt:
        self.chat._authorize(context, project_id)
        if object_focus:
            from app.domain.conversation_focus import current

            with self.engine.connect() as c:
                current(c, context.tenant.id, project_id, context.user.id, object_focus)
        row, _ = ChatRunStore(self.engine, gateway=self.gateway).start(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            auth_version=context.user.auth_version,
            question=question,
            request_id=request_id,
            enqueue=True,
            attachment_ids=attachment_ids,
            object_focus=object_focus,
        )
        return self._receipt(context, row)

    def _row(self, context: AuthContext, run_id: UUID) -> RowMapping:
        with self.engine.connect() as c:
            row = (
                c.execute(
                    select(tables.agent_runs).where(
                        tables.agent_runs.c.tenant_id == context.tenant.id,
                        tables.agent_runs.c.requested_by_user_id == context.user.id,
                        tables.agent_runs.c.id == run_id,
                        tables.agent_runs.c.agent_key == "ai_chat",
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise ObjectPermissionDeniedError
        self.chat._authorize(context, row["project_id"])
        return row

    def get(self, *, context: AuthContext, run_id: UUID) -> ChatQueueReceipt:
        return self._receipt(context, self._row(context, run_id))

    def cancel(self, *, context: AuthContext, run_id: UUID) -> ChatQueueReceipt:
        self._row(context, run_id)
        from app.ai.application_control import cancel_application_run

        cancel_application_run(self.engine, context=context, run_id=run_id)
        return self.get(context=context, run_id=run_id)

    def _receipt(self, context: AuthContext, row: RowMapping) -> ChatQueueReceipt:
        result = None
        if row["status"] not in {"queued", "running"}:
            result = self.chat.read_result(context=context, row=row)
        return ChatQueueReceipt(
            run_id=row["id"],
            project_id=row["project_id"],
            request_id=row["request_id"],
            status="cancelled"
            if row["error_code"] == "APPLICATION_REQUEST_CANCELLED"
            else row["status"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            error_code=row["error_code"],
            result=result,
        )

    def run_next(self, *, embedding_gateway: EmbeddingGateway | None = None) -> bool:
        recoverable = and_(
            tables.agent_runs.c.status == "degraded",
            tables.agent_runs.c.error_code == "APPLICATION_RUN_LEASE_EXPIRED",
            tables.agent_runs.c.run_context["application_queue_version"].as_string() == "1",
            select(tables.application_result_checkpoints.c.id)
            .where(
                tables.application_result_checkpoints.c.tenant_id == tables.agent_runs.c.tenant_id,
                tables.application_result_checkpoints.c.run_id == tables.agent_runs.c.id,
            )
            .exists(),
        )
        # Claiming happens in ChatRunStore under the tenant lock. Two workers may
        # observe this row; only one gets its first lease. No lock spans inference.
        with self.engine.connect() as c:
            row = (
                c.execute(
                    select(tables.agent_runs)
                    .where(
                        tables.agent_runs.c.agent_key == "ai_chat",
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
            # _claim compares this current session version to the original envelope.
            ChatService(
                self.engine, gateway=self.gateway, embedding_gateway=embedding_gateway
            ).answer(
                context=context,
                project_id=row["project_id"],
                question=row["run_context"]["chat_question"],
                attachment_ids=tuple(
                    UUID(a) for a in row["run_context"].get("chat_attachment_ids", [])
                ),
                request_id=row["request_id"],
                object_focus=row["run_context"].get("chat_object_focus"),
            )
        except ChatRequestConflictError:
            pass  # Another worker owns it, or the user cancelled it.
        except Exception as error:
            code = (
                error.code
                if isinstance(error, BudgetLedgerError)
                else "APPLICATION_AUTHORIZATION_CHANGED"
                if isinstance(error, ObjectPermissionDeniedError)
                else "APPLICATION_QUEUE_EXECUTION_FAILED"
            )
            # Failure before acquisition otherwise leaves a poison item at queue head.
            # After acquisition the existing Chat/lease supervisor owns cleanup.
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
            logger.warning("application_chat_stopped run=%s reason=%s", row["id"], code)
        return True
