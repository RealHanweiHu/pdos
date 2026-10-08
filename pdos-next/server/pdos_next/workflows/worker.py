"""Local durable activities; domain truth is reread on every activity attempt."""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

from temporalio import activity
from temporalio.client import Client
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker

from pdos_next.database import configured_engines, tenant_session
from pdos_next.dispatch.outbox import dispatch_once
from pdos_next.errors import DomainError
from pdos_next.models import WorkRequest
from pdos_next.original_security import configure, queue_uploaded, scan_requested
from pdos_next.original_store import OriginalStore
from pdos_next.originals import parse_uploaded
from pdos_next.runtime import resume
from pdos_next.service import Context
from pdos_next.workflows.definitions import (
    OriginalLifecycle,
    ParseOriginal,
    QueueOriginalSecurity,
    SecureOriginal,
    SourceWork,
    UploadTerminal,
)
from pdos_next.workflows.transport import TemporalSender


class Activities:
    def __init__(self, engine, store, checkpoint_url, *, provider_factory=None):
        from pdos_next.agent_execution import configured_provider_factory

        self.engine, self.store, self.checkpoint_url = engine, store, checkpoint_url
        self.provider_factory = provider_factory or configured_provider_factory(engine)

    @activity.defn(name="advance_source_work")
    def advance(self, reference: dict):
        tenant, product, work_id = (
            UUID(reference[k]) for k in ("tenant_id", "product_id", "subject_id")
        )
        with tenant_session(self.engine, tenant) as s:
            work = s.get(WorkRequest, work_id)
            if not work or work.product_id != product:
                raise ApplicationError(
                    "Work unavailable", type="FORBIDDEN_SCOPE", non_retryable=True
                )
            ctx = Context(tenant, work.accountable_owner_id, work.accountable_owner_id)
            if work.status == "cancelled":
                return {"status": "cancelled"}
            completed = work.status == "completed"
        try:
            from pdos_agent_runtime.graph import execute_graph

            from pdos_next.agent_execution import selected_provider

            def execute(_):
                try:
                    if completed:
                        value = resume(
                            self.engine, ctx, work_id, None, checkpoint_url=self.checkpoint_url
                        )
                    else:
                        with selected_provider(self.provider_factory, ctx, work_id) as provider:
                            value = resume(
                                self.engine,
                                ctx,
                                work_id,
                                provider,
                                checkpoint_url=self.checkpoint_url,
                            )
                except DomainError as error:
                    if not error.code.startswith("MODEL_"):
                        raise
                    from pdos_next.runtime import model_unavailable

                    value = model_unavailable(self.engine, ctx, work_id, error.code)
                return {"value": value}

            return execute_graph(execute, {}, thread_id=f"pdos-next:{tenant}:{work_id}")["value"]
        except DomainError as exc:
            raise ApplicationError(exc.message, type=exc.code, non_retryable=True) from None

    @activity.defn(name="parse_uploaded_original")
    def parse(self, reference: dict):
        try:
            return parse_uploaded(self.engine, reference, self.store)
        except DomainError as exc:
            raise ApplicationError(exc.message, type=exc.code, non_retryable=True) from None

    @activity.defn(name="queue_original_security")
    def queue(self, reference: dict):
        try:
            return queue_uploaded(self.engine, reference)
        except DomainError as exc:
            raise ApplicationError(exc.message, type=exc.code, non_retryable=True) from None

    @activity.defn(name="scan_original_request")
    def scan(self, reference: dict):
        try:
            return scan_requested(self.engine, reference)
        except DomainError as exc:
            raise ApplicationError(exc.message, type=exc.code, non_retryable=True) from None

    @activity.defn(name="advance_original_lifecycle")
    def lifecycle(self, reference: dict):
        from pdos_next.lifecycle_worker import process
        from pdos_next.original_lifecycle.types import LifecycleFailure

        try:
            return process(self.engine, reference)
        except (DomainError, LifecycleFailure) as exc:
            raise ApplicationError(
                "Lifecycle requires current reconciliation", type=exc.code, non_retryable=True
            ) from None

    @activity.defn(name="reconcile_upload_terminal")
    def terminal_upload(self, reference: dict):
        from pdos_next.models import UploadAttempt
        from pdos_next.object_storage import StorageFailure
        from pdos_next.upload_lifecycle import reconcile_terminal

        tenant, pid, oid = (UUID(reference[k]) for k in ("tenant_id", "product_id", "subject_id"))
        try:
            with tenant_session(self.engine, tenant) as s:
                row = s.get(UploadAttempt, oid)
                if not row or row.product_id != pid:
                    raise DomainError("SOURCE_UNAVAILABLE", "上传登记不可用。", 403)
                ctx = Context(tenant, row.owner_id, row.owner_id)
                reconcile_terminal(s, ctx, pid, oid, self.store)
                return {"status": row.status}
        except (DomainError, StorageFailure) as exc:
            raise ApplicationError(
                "Upload journal requires reconciliation", type=exc.code, non_retryable=True
            ) from None


async def main(*, model_runtime_ports=None):
    engine, auth = configured_engines()
    if model_runtime_ports is not None:
        from pdos_next.agent_execution import configure_model_runtime

        configure_model_runtime(engine, model_runtime_ports)
    store = OriginalStore(os.environ["PDOS_OBJECT_ROOT"])
    from pdos_next.lifecycle_worker import configure_lifecycle

    configure_lifecycle(engine, store, allow_local_profile=True)
    from pdos_next.security_bootstrap import local_runtime

    configure(engine, await local_runtime(store))
    tenants = [UUID(value) for value in os.environ["PDOS_WORKFLOW_TENANTS"].split(",")]
    client = await Client.connect(
        os.environ["PDOS_TEMPORAL_ADDRESS"], namespace=os.environ["PDOS_TEMPORAL_NAMESPACE"]
    )
    activities = Activities(engine, store, os.environ["PDOS_CHECKPOINT_DATABASE_URL"])
    sender = TemporalSender(client)
    stop = asyncio.Event()

    async def deliver():
        while not stop.is_set():
            for tenant in tenants:
                await dispatch_once(engine, tenant, sender)
            try:
                await asyncio.wait_for(stop.wait(), 1)
            except TimeoutError:
                pass

    with ThreadPoolExecutor(max_workers=4) as executor:
        async with Worker(
            client,
            task_queue=sender.task_queue,
            workflows=[
                SourceWork,
                ParseOriginal,
                QueueOriginalSecurity,
                SecureOriginal,
                OriginalLifecycle,
                UploadTerminal,
            ],
            activities=[
                activities.advance,
                activities.parse,
                activities.queue,
                activities.scan,
                activities.lifecycle,
                activities.terminal_upload,
            ],
            activity_executor=executor,
        ):
            task = asyncio.create_task(deliver())
            try:
                await asyncio.Event().wait()
            finally:
                stop.set()
                await task
                runtime = getattr(engine, "_pdos_security_runtime", None)
                if runtime and hasattr(runtime.scanner, "close"):
                    await runtime.scanner.close()
                engine.dispose()
                auth.dispose()


if __name__ == "__main__":
    asyncio.run(main())
