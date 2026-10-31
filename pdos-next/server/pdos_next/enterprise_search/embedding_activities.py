"""Actual UOW/Outbox proof → registered LangGraph → embedding ledger/vector projection."""

from contextlib import contextmanager
from dataclasses import dataclass, replace
from uuid import UUID

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy import and_, select
from temporalio import activity

from pdos_next.database import tenant_session
from pdos_next.dispatch.context import event_context
from pdos_next.errors import DomainError
from pdos_next.models import Outbox, Principal, Receipt
from pdos_next.service import Context, require_access
from pdos_next.workflows.checkpoints import verified_checkpoint_url

from .embedding_jobs import plan
from .embedding_models import EmbeddingProfile, EmbeddingProfileHead
from .embedding_runtime import batch_readiness, context_value, execute_batch


@dataclass(frozen=True)
class EmbeddingPorts:
    secrets: object
    pricing_for: object
    client: object


class EmbeddingActivities:
    def __init__(self, engine, ports, *, checkpoint_url):
        self.engine, self.ports = engine, ports
        self.checkpoint = verified_checkpoint_url(checkpoint_url)

    @contextmanager
    def transaction(self, ctx):
        # Keep the same native RLS adapter; writing UOWs need a repeatable
        # snapshot too, so scan/dependency proofs and bodies cannot split.
        with tenant_session(
            self.engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            repeatable_read=True,
        ) as session:
            yield session

    @activity.defn(name="plan_enterprise_embeddings")
    def plan(self, reference):
        if reference.get("rebuild") is True:
            return self.rebuild_plan(reference)
        # Reuse the actual Outbox/Receipt envelope, never a browser-supplied source list.
        ctx = event_context(reference)
        with self.transaction(ctx) as session:
            event = session.get(Outbox, UUID(reference["event_id"]))
            receipt = session.get(Receipt, event.receipt_id) if event is not None else None
            if (
                event is None
                or receipt is None
                or event.tenant_id != ctx.tenant_id
                or event.actor_id != ctx.actor_id
                or receipt.requester_id != ctx.requester_id
                or event.category_id != ctx.category_id
                or receipt.category_id != ctx.category_id
                or receipt.tenant_id != ctx.tenant_id
                or event.type != reference["event_type"]
                or str(event.subject_id) != reference["subject_id"]
                or event.subject_revision != reference["subject_revision"]
            ):
                raise DomainError("FORBIDDEN_SCOPE", "Embedding 工作缺少真实启用回执。")
            from .events import EVENTS

            if event.type not in EVENTS | {"embedding.profile_saved"}:
                raise DomainError("FORBIDDEN_SCOPE", "未登记的 Embedding 来源事件。")
            profiles = (
                select(EmbeddingProfile)
                .join(
                    EmbeddingProfileHead,
                    and_(
                        EmbeddingProfileHead.tenant_id == EmbeddingProfile.tenant_id,
                        EmbeddingProfileHead.profile_id == EmbeddingProfile.profile_id,
                        EmbeddingProfileHead.revision == EmbeddingProfile.revision,
                        EmbeddingProfileHead.enabled,
                        EmbeddingProfile.enabled,
                    ),
                )
                .where(EmbeddingProfile.tenant_id == ctx.tenant_id)
            )
            if event.type == "embedding.profile_saved":
                if receipt.operation != "embedding.profile.save":
                    raise DomainError("FORBIDDEN_SCOPE", "Embedding 启用操作与原回执不一致。")
                profiles = profiles.where(EmbeddingProfile.id == event.subject_id)
            results = [
                plan(session, ctx, profile.id, generation=event.id, secrets=self.ports.secrets)
                for profile in session.scalars(profiles)
            ]
            return {
                "batches": [identity for result in results for identity in result["batches"]],
                "uncovered_chunks": sum(result["uncovered_chunks"] for result in results),
                "truncated": any(result["truncated"] for result in results),
                "context": context_value(ctx),
            }

    def rebuild_plan(self, reference):
        from .recovery import _context
        from .sources import select_sources

        if (
            not isinstance(reference, dict)
            or set(reference) != {"rebuild", "context", "generation"}
            or reference["rebuild"] is not True
            or not isinstance(reference["context"], dict)
            or set(reference["context"])
            != {
                "tenant_id",
                "actor_id",
                "requester_id",
                "category_id",
            }
        ):
            raise DomainError("FORBIDDEN_SCOPE", "Embedding 恢复范围必须由原恢复入口绑定。")
        try:
            generation = UUID(reference["generation"])
        except (TypeError, ValueError, AttributeError):
            raise DomainError("FORBIDDEN_SCOPE", "Embedding 恢复需要固定请求身份。") from None
        ctx = _context(reference["context"])
        with self.transaction(ctx) as session:
            person = session.get(Principal, ctx.requester_id)
            if (
                ctx.actor_id != ctx.requester_id
                or not person
                or not person.active
                or person.kind != "human"
            ):
                raise DomainError("FORBIDDEN_SCOPE", "恢复须当前本人身份与当前来源权限。")
            if ctx.category_id is not None:
                require_access(session, ctx, None)
            authority = select_sources().subquery("embedding_rebuild_current_scope")
            categories = list(session.scalars(select(authority.c.category_id).distinct()))
            versions = list(
                session.scalars(
                    select(EmbeddingProfile.id)
                    .join(
                        EmbeddingProfileHead,
                        and_(
                            EmbeddingProfileHead.tenant_id == EmbeddingProfile.tenant_id,
                            EmbeddingProfileHead.profile_id == EmbeddingProfile.profile_id,
                            EmbeddingProfileHead.revision == EmbeddingProfile.revision,
                            EmbeddingProfileHead.enabled,
                            EmbeddingProfile.enabled,
                        ),
                    )
                    .where(EmbeddingProfile.tenant_id == ctx.tenant_id)
                )
            )
        results, batch_refs = [], []
        for category in sorted(categories):
            source_ctx = replace(ctx, category_id=category)
            with self.transaction(source_ctx) as session:
                require_access(session, source_ctx, None)
                for version in versions:
                    result = plan(
                        session, source_ctx, version, generation=generation,
                        secrets=self.ports.secrets,
                    )
                    results.append(result)
                    batch_refs.extend(
                        {"context": context_value(source_ctx), "batch_id": identity}
                        for identity in result["batches"]
                    )
        return {
            "batch_refs": batch_refs,
            "batches": [row["batch_id"] for row in batch_refs],
            "context": context_value(ctx),
            "uncovered_chunks": sum(row["uncovered_chunks"] for row in results),
            "truncated": any(row["truncated"] for row in results),
        }

    @activity.defn(name="embed_enterprise_batch")
    def embed(self, reference):
        from pdos_agent_runtime.graph import registered_graph_context

        value = reference["context"]
        if set(value) != {"tenant_id", "actor_id", "requester_id", "category_id"}:
            raise DomainError("FORBIDDEN_SCOPE", "Embedding 批次信封无效。")
        ctx = Context(
            UUID(value["tenant_id"]),
            UUID(value["actor_id"]),
            UUID(value["requester_id"]),
            category_id=UUID(value["category_id"]),
        )
        identity = UUID(reference["batch_id"])
        graph = StateGraph(dict)

        def dispatch(_state):
            return execute_batch(
                self.transaction,
                ctx,
                identity,
                secrets=self.ports.secrets,
                pricing_for=self.ports.pricing_for,
                client=self.ports.client,
            )

        graph.add_node("embedding_dispatch", dispatch)
        graph.add_edge(START, "embedding_dispatch")
        graph.add_edge("embedding_dispatch", END)
        with PostgresSaver.from_conn_string(self.checkpoint) as saver:
            compiled = graph.compile(checkpointer=saver)
            config = {
                "configurable": {
                    "thread_id": f"xiaopai:embedding:{ctx.tenant_id}:{identity}",
                }
            }
            with registered_graph_context("xiaopai"):
                saved = compiled.get_state(config)
                if saved.values and not saved.next:
                    return batch_readiness(self.transaction, ctx, identity)
                payload = None if saved.values else {"batch_id": str(identity)}
                return compiled.invoke(payload, config)
