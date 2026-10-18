"""Metadata discovery and persisted event fanout before the shared Outbox acknowledgement."""

import asyncio
import logging
from uuid import UUID

from sqlalchemy import text
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.workflows.automation import REFERENCE_KEYS, AutomationRuleWork

from . import service_runtime

SCOPE_SKIP_REASON = "AUTOMATION_SOURCE_SCOPE_INVALID"
_LOGGER = logging.getLogger(__name__)


def workflow_id(tenant_id, grant_id):
    return f"pdos-next:automation:{UUID(str(tenant_id))}:{UUID(str(grant_id))}"


def _reference(row, tenant):
    if set(row) != REFERENCE_KEYS:
        raise ValueError("Automation dispatcher must return only the five fixed UUID references")
    try:
        value = {key: str(UUID(str(row[key]))) for key in sorted(REFERENCE_KEYS)}
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Automation dispatcher returned an invalid UUID reference") from None
    if value["tenant_id"] != str(tenant):
        raise DomainError("FORBIDDEN_SCOPE", "派发引用与当前实际租户不一致。", 403)
    return value


class ServiceAutomationSender:
    def __init__(self, client, engine, dispatch_engine, task_queue="pdos-next-domain-v1"):
        self.client, self.engine, self.dispatch_engine = client, engine, dispatch_engine
        self.task_queue = task_queue
        self._handles = {}

    def _metadata(self, tenant, event=None):
        # Open and close the entire synchronous transaction in this worker thread.
        # The dispatcher sees references only, never business source bodies or sessions.
        with tenant_session(self.dispatch_engine, tenant) as session:
            if event is None:
                statement = text("SELECT * FROM automation_active_grants(:tenant)")
                params = {"tenant": tenant}
            else:
                statement = text("SELECT * FROM automation_event_targets(:tenant,:event,:lease)")
                params = {
                    "tenant": tenant,
                    "event": UUID(event.event_id),
                    "lease": UUID(event.lease_id),
                }
            rows = session.execute(statement, params).mappings().all()
        return tuple(_reference(row, tenant) for row in rows)

    async def _ensure(self, reference):
        identity = workflow_id(reference["tenant_id"], reference["grant_id"])
        if identity in self._handles:
            return self._handles[identity]
        try:
            handle = await self.client.start_workflow(
                AutomationRuleWork.run,
                dict(reference),
                id=identity,
                task_queue=self.task_queue,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
        except WorkflowAlreadyStartedError:
            handle = self.client.get_workflow_handle(identity)
        self._handles[identity] = handle
        return handle

    async def discover(self, tenant):
        tenant = UUID(str(tenant))
        references = await asyncio.to_thread(self._metadata, tenant)
        for reference in references:
            await self._ensure(reference)
        return {"ensured": len(references)}

    async def event(self, event):
        tenant = UUID(event.tenant_id)
        references = await asyncio.to_thread(self._metadata, tenant, event)
        pending, skipped, ignored = [], [], 0
        for reference in references:
            try:
                attempt = await asyncio.to_thread(
                    service_runtime.queue_event, self.engine, dict(reference), event
                )
            except DomainError as error:
                if error.code != "FORBIDDEN_SCOPE" and not (
                    error.code == "SOURCE_UNAVAILABLE" and error.status == 403
                ):
                    raise
                skipped.append({"grant_id": reference["grant_id"], "reason": SCOPE_SKIP_REASON})
                _LOGGER.info(
                    "Automation event target skipped: reason=%s grant_id=%s event_id=%s",
                    SCOPE_SKIP_REASON,
                    reference["grant_id"],
                    event.event_id,
                )
                continue
            if attempt is None:
                ignored += 1
                continue
            # The actual owner returns only the persisted Attempt reference.
            UUID(attempt)
            pending.append(reference)
        # Every target has committed its own ordinary-scope queue transaction
        # before any workflow is signalled and before the caller may acknowledge.
        for reference in pending:
            handle = await self._ensure(reference)
            await handle.signal(AutomationRuleWork.wake)
        return {"persisted": len(pending), "ignored": ignored, "skipped": skipped}
