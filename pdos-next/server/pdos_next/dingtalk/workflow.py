"""Reference-only channel completion orchestration; native XiaopaiWork owns all inference."""

from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from .schemas import ChannelReference, DeliveryReference


@workflow.defn
class DingTalkCompletion:
    @workflow.run
    async def run(self, reference: dict):
        if "phase" in reference:
            DeliveryReference.model_validate(reference)
        else:
            ChannelReference.model_validate(reference)
        for _ in range(100):
            value = await workflow.execute_activity(
                "deliver_dingtalk_completion",
                reference,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_interval=timedelta(minutes=1)),
            )
            if value["state"] == "cancelled":
                await workflow.execute_activity(
                    "cancel_dingtalk_native_execution",
                    reference,
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_interval=timedelta(minutes=1)),
                )
            if value["state"] != "waiting":
                return value
            await workflow.sleep(timedelta(seconds=30))
        workflow.continue_as_new(reference)


class ChannelActivities:
    def __init__(self, engine, metadata_engine, native_sender, *, runtime=None):
        self.engine, self.metadata_engine, self.runtime = engine, metadata_engine, runtime
        self.native_sender = native_sender

    @activity.defn(name="cancel_dingtalk_native_execution")
    async def cancel(self, reference):
        from .runtime import ChannelService

        ref = (
            DeliveryReference.model_validate(reference)
            if "phase" in reference
            else ChannelReference.model_validate(reference)
        )
        service = ChannelService(self.engine, self.metadata_engine, runtime=self.runtime)
        run_id = service.cancel_lost(ref)
        if run_id is None:
            return {"state": "active"}
        # Exact UUID from the dispatcher-only lost-binding primitive; works even
        # after the actual Agent is inactive, without a body READ or borrowed owner.
        await self.native_sender.cancel(ref.tenant_id, run_id)
        return {"state": "cancelled"}

    @activity.defn(name="deliver_dingtalk_completion")
    def deliver(self, reference):
        from uuid import UUID

        from sqlalchemy.exc import DBAPIError

        from pdos_next.errors import DomainError

        from .graph import execute
        from .runtime import ChannelService

        service = ChannelService(self.engine, self.metadata_engine, runtime=self.runtime)
        ref = (
            DeliveryReference.model_validate(reference)
            if "phase" in reference
            else ChannelReference.model_validate(reference)
        )
        try:
            result = execute(service, reference)
        except DBAPIError as error:
            if (
                getattr(error.orig, "sqlstate", None) != "42501"
                or getattr(getattr(error.orig, "diag", None), "message_primary", None)
                != "DingTalk service binding required"
                or not (error.statement or "")
                .lstrip()
                .startswith("SELECT dingtalk_lock_message_binding(")
            ):
                raise
            # The failed service UOW has exited and rolled back. Only the existing
            # dispatcher primitive can now prove the actual Message/Run lost its
            # binding; do not write via the revoked service or retry a send.
            if not isinstance(service.cancel_lost(ref), UUID):
                raise
            result = {"state": "cancelled", "error_code": "CANCELLED_RUN"}
        except DomainError as error:
            result = {"state": "blocked", "error_code": error.reason}
        if not isinstance(ref, DeliveryReference) and result["state"] == "blocked":
            with service.metadata(ref) as (_session, message, _app):
                message.state, message.error_code = "blocked", result.get("error_code")
        return result


class ChannelSender:
    def __init__(self, client, metadata_engine, native_sender, *, task_queue="pdos-next-domain-v1"):
        self.client, self.metadata_engine = client, metadata_engine
        self.native_sender, self.task_queue = native_sender, task_queue

    async def discover(self, tenant_id):
        from sqlalchemy import text

        from pdos_next.database import tenant_session

        with tenant_session(self.metadata_engine, tenant_id) as session:
            refs = (
                session.execute(
                    text("SELECT * FROM dingtalk_pending_references(:tenant,100)"),
                    {"tenant": tenant_id},
                )
                .mappings()
                .all()
            )
        for row in refs:
            # Original native workflow, exact persisted Message→Run reference.
            await self.native_sender.start(
                {
                    "tenant_id": str(tenant_id),
                    "category_id": "",
                    "actor_id": str(row["owner_id"]),
                    "requester_id": str(row["owner_id"]),
                    "subject_id": str(row["run_id"]),
                }
            )
            ref = {"tenant_id": str(tenant_id), "message_id": str(row["message_id"])}
            if row["consent_id"]:
                ref.update(phase="share", consent_id=str(row["consent_id"]))
            identity = (
                f"pdos-next:dingtalk:{tenant_id}:{row['message_id']}:{row['consent_id'] or 'reply'}"
            )
            try:
                await self.client.start_workflow(
                    DingTalkCompletion.run,
                    ref,
                    id=identity,
                    task_queue=self.task_queue,
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                )
            except WorkflowAlreadyStartedError:
                pass
            with tenant_session(self.metadata_engine, tenant_id) as session:
                session.execute(
                    text("SELECT dingtalk_mark_dispatched(:tenant,:message,:consent)"),
                    {
                        "tenant": tenant_id,
                        "message": row["message_id"],
                        "consent": row["consent_id"],
                    },
                )
        from .summary_workflow import SummarySender

        summaries = await SummarySender(
            self.client,
            self.metadata_engine,
            task_queue=self.task_queue,
        ).discover(tenant_id)
        return {"discovered": len(refs), **summaries}
