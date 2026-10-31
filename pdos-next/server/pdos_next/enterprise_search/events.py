"""Outbox-bound projection maintenance and durable Temporal dispatch."""

from dataclasses import asdict
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from pdos_next.database import tenant_session
from pdos_next.dispatch.context import event_context
from pdos_next.domain.preproject.category_models import KnowledgeEntry
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, OriginalScanRequest, OriginalScanResult, Outbox, Receipt
from pdos_next.service import require_access

from . import business_events
from .indexing import project, record_failure
from .models import SearchSource
from .workflow import EnterpriseProjection

EVENTS = business_events.EVENTS | frozenset(
    {
        "artifact.registered",
        "knowledge.rule_published",
        "category.knowledge_added",
        "category.knowledge_withdrawn",
        "category.knowledge_promoted",
        "original.scan_recorded",
        "original.parsed",
        "original.withdrawn",
        "original.scan_requested",
        "original.lifecycle_requested",
    }
)


class ProjectionSender:
    def __init__(self, client, task_queue="pdos-next-domain-v1", *, embedding=False):
        self.client, self.task_queue = client, task_queue
        self.embedding = embedding

    async def event(self, event):
        if event.event_type == "embedding.profile_saved":
            from .embedding_workflow import EnterpriseEmbedding

            entry = EnterpriseEmbedding.run
        elif event.event_type in EVENTS:
            if self.embedding:
                from .embedding_workflow import EnterpriseEmbeddingProjection

                entry = EnterpriseEmbeddingProjection.run
            else:
                entry = EnterpriseProjection.run
        else:
            return None
        identity = f"pdos-enterprise-projection:{event.tenant_id}:{event.event_id}"
        try:
            await self.client.start_workflow(
                entry,
                asdict(event),
                id=identity,
                task_queue=self.task_queue,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
        except WorkflowAlreadyStartedError:
            pass
        return identity

    async def rebuild(self, ctx, request_id):
        """A server-supplied caller scope starts one durable recovery request."""
        from .recovery import context_reference
        from .recovery_workflow import EnterpriseRebuild

        identity = f"pdos-enterprise-rebuild:{ctx.tenant_id}:{UUID(str(request_id))}"
        entry, reference = EnterpriseRebuild.run, context_reference(ctx)
        if self.embedding:
            from .embedding_workflow import EnterpriseEmbeddingRebuild

            entry = EnterpriseEmbeddingRebuild.run
            reference = {
                "rebuild": True, "context": reference,
                "generation": str(UUID(str(request_id))),
            }
        try:
            await self.client.start_workflow(
                entry,
                reference,
                id=identity,
                task_queue=self.task_queue,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
        except WorkflowAlreadyStartedError:
            pass
        return identity


def process_event(engine, reference):
    ctx = event_context(reference)
    with tenant_session(
        engine,
        ctx.tenant_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        category_id=ctx.category_id,
    ) as session:
        require_access(session, ctx, None, lock=True)
        bound = session.execute(
            select(Outbox, Receipt)
            .join(
                Receipt,
                Receipt.id == Outbox.receipt_id,
            )
            .where(Outbox.id == UUID(reference["event_id"]))
        ).one_or_none()
        if bound is None:
            raise DomainError("FORBIDDEN_SCOPE", "投影工作没有当前可读的实际 Outbox 来源。")
        event, receipt = bound
        if (
            event.tenant_id != ctx.tenant_id
            or event.category_id != ctx.category_id
            or event.actor_id != ctx.actor_id
            or receipt.requester_id != ctx.requester_id
            or str(event.subject_id) != reference["subject_id"]
            or event.subject_revision != reference["subject_revision"]
            or event.type != reference["event_type"]
            or event.type not in EVENTS
        ):
            raise DomainError("FORBIDDEN_SCOPE", "投影信封与原事件不一致。")
        targets = []
        if event.type in business_events.EVENTS:
            targets = business_events.targets(session, event, receipt)
        elif event.type == "artifact.registered":
            targets = [("artifact", event.subject_id)]
        elif event.type == "knowledge.rule_published":
            from pdos_next.domain.knowledge.models import DesignRuleVersion

            rule_ids = select(DesignRuleVersion.rule_id).where(DesignRuleVersion.receipt_id == receipt.id)
            targets = [("knowledge", identity) for identity in session.scalars(
                select(DesignRuleVersion.id).where(DesignRuleVersion.rule_id.in_(rule_ids))
            )]
        elif event.type.startswith("category.knowledge_"):
            lineage = select(KnowledgeEntry.lineage_id).where(
                or_(
                    KnowledgeEntry.id == event.subject_id,
                    KnowledgeEntry.lineage_id == event.subject_id,
                    KnowledgeEntry.receipt_id == receipt.id,
                ),
            )
            targets = [
                ("knowledge", identity)
                for identity in session.scalars(
                    select(KnowledgeEntry.id).where(KnowledgeEntry.lineage_id.in_(lineage)),
                )
            ]
        else:
            originals = {event.subject_id}
            originals.update(
                session.scalars(
                    select(OriginalScanRequest.original_id).where(
                        OriginalScanRequest.id == event.subject_id,
                    )
                )
            )
            originals.update(
                session.scalars(
                    select(OriginalScanResult.original_id).where(
                        OriginalScanResult.id == event.subject_id,
                    )
                )
            )
            live = set(
                session.scalars(
                    select(Artifact.id).where(
                        or_(Artifact.original_id.in_(originals), Artifact.id == event.subject_id),
                    )
                )
            )
            live.update(
                session.scalars(
                    select(SearchSource.source_id).where(
                        SearchSource.source_type == "artifact",
                        SearchSource.original_id.in_(originals),
                    )
                )
            )
            targets = [("artifact", identity) for identity in live]
        results, failed = [], 0
        for kind, identity in sorted(set(targets)):
            try:
                with session.begin_nested():
                    results.append(
                        project(
                            session,
                            ctx,
                            kind,
                            identity,
                            event_id=event.id,
                            expected_revision=event.subject_revision,
                        )
                    )
            except (DomainError, SQLAlchemyError) as error:
                failed += 1
                record_failure(
                    session,
                    ctx,
                    kind,
                    identity,
                    ctx.category_id,
                    event.subject_revision,
                    error,
                    event.id,
                )
    if failed:
        raise DomainError("SOURCE_UNAVAILABLE", "企业索引有未完成的来源，已保存错误并等待重试。")
    return {"processed": len(results), "changed": sum(row["changed"] for row in results)}
