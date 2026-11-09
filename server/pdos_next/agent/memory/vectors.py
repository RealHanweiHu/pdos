"""Optional episode vectors (P85 第 3 项, design §6.2, §14.4, §14.9 嵌入版本).

Only when the tenant's active embedding profile selects the data category
“本人会话记录” (``owner_session``; off by default, enabled by an administrator's
one confirmation of the profile, P30 第 2 项). The background work runs as the
episode owner (actor = requester = owner), so only the owner's own episodes are
read; it sends only the owner's own words (page material already removed).

The server decides the provider (the profile's registered connection) and the
data categories: ``owner_session`` plus customer categories the original Run
carried. An episode whose original Run was private, or whose categories the
profile does not select, stays keyword-only. Every call leaves a receipt with
the P26 decision and cost, charged to the tenant index budget. Vectors carry the
profile version; recall only compares vectors of the same version.
"""

import math
from dataclasses import asdict
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert

from pdos_next.core.service import Context, digest
from pdos_next.errors import DomainError

from .models import MemoryEmbeddingCall, MemoryEpisode, MemoryEpisodeVector
from .policy import OWNER_SESSION

MAX_BATCH = 16
TEXT_CHARS = 2000
REFERENCE_KEYS = {"tenant_id", "owner_id", "profile_version_id", "episode_ids"}
CUSTOMER = frozenset({"customer", "customer_original"})


def reference(value):
    if (not isinstance(value, dict) or set(value) != REFERENCE_KEYS
            or not isinstance(value["episode_ids"], list)
            or not 1 <= len(value["episode_ids"]) <= MAX_BATCH):
        raise DomainError("FORBIDDEN_SCOPE", "情景向量化只接受固定的本人情景引用。")
    return {"tenant_id": UUID(str(value["tenant_id"])), "owner_id": UUID(str(value["owner_id"])),
            "profile_version_id": UUID(str(value["profile_version_id"])),
            "episode_ids": sorted({UUID(str(item)) for item in value["episode_ids"]})}


def categories(origin):
    """Server-decided outbound categories for one episode, or None (keyword only)."""
    if origin is None or origin.private_context:
        return None
    result = {OWNER_SESSION} | (set(origin.data_categories or ()) & CUSTOMER)
    if origin.customer_identities:
        result.add("customer")
    return result


def plan(session, ctx, ref):
    from pdos_next.agent.enterprise_search.embedding_profiles import active
    from pdos_next.agent.kernel.models import AgentRun

    profile, metadata = active(session, ctx.tenant_id, ref["profile_version_id"])
    if OWNER_SESSION not in metadata.data_categories:
        raise DomainError("FORBIDDEN_SCOPE", "当前 Embedding 配置未勾选“本人会话记录”。")
    episodes = session.scalars(select(MemoryEpisode).where(
        MemoryEpisode.id.in_(ref["episode_ids"]), MemoryEpisode.owner_id == ctx.requester_id,
    ).order_by(MemoryEpisode.created_at, MemoryEpisode.id)).all()
    done = set(session.scalars(select(MemoryEpisodeVector.episode_id).where(
        MemoryEpisodeVector.episode_id.in_(ref["episode_ids"]),
        MemoryEpisodeVector.profile_version_id == profile.id)))
    origins = {row.id: row for row in session.scalars(select(AgentRun).where(
        AgentRun.id.in_([episode.run_id for episode in episodes])))} if episodes else {}
    rows, skipped = [], 0
    for episode in episodes:
        if episode.id in done:
            continue
        chosen = categories(origins.get(episode.run_id))
        body = " ".join(episode.goal.split())[:TEXT_CHARS]
        if chosen is None or not chosen <= set(metadata.data_categories) or not body:
            skipped += 1
            continue
        rows.append((episode, chosen, body))
    return profile, metadata, rows, skipped


def _finish(budget, call, cost, tokens, state):
    if call.state != "started":
        raise DomainError("VERSION_CONFLICT", "原向量化调用已结算。")
    budget.held_micro_usd -= call.reserved_micro_usd
    budget.spent_micro_usd += cost
    call.charged_micro_usd, call.input_tokens, call.state = cost, tokens, state
    call.revision += 1


def execute(transaction, ctx, value, *, secrets, pricing_for, client):
    """The caller MUST run this inside the registered LangGraph node (不可协商项 6)."""
    from pdos_agent_runtime.graph import in_registered_agent_graph

    if not in_registered_agent_graph():
        raise DomainError("FORBIDDEN_SCOPE", "情景向量化必须经已注册执行图。")
    if client is None or not callable(getattr(client, "embed", None)):
        raise DomainError("SOURCE_UNAVAILABLE", "尚未配置独立 Embedding 端口。")
    ref = reference(value)
    if ref["tenant_id"] != ctx.tenant_id or ref["owner_id"] != ctx.requester_id \
            or ctx.actor_id != ctx.requester_id:
        raise DomainError("FORBIDDEN_SCOPE", "情景向量化只能由记录本人的身份办理。")
    with transaction(ctx) as session:
        key = int(digest(["memory-vectors/v1", ctx.tenant_id, ctx.requester_id])[:15], 16)
        if not session.scalar(select(func.pg_try_advisory_xact_lock(key))):
            raise DomainError("RATE_LIMITED", "本人情景向量化正在处理。")
        return _locked(transaction, ctx, ref, secrets=secrets, pricing_for=pricing_for,
                       client=client)


def _locked(transaction, ctx, ref, *, secrets, pricing_for, client):
    from pdos_next.agent.enterprise_search.embedding_identity import canonical_provider
    from pdos_next.agent.enterprise_search.embedding_profiles import bound_secret
    from pdos_next.agent.enterprise_search.embedding_runtime import (
        budget_row,
        settlement,
        unit_vector,
        wire_bytes,
    )
    from pdos_next.agent.enterprise_search.embedding_schemas import (
        bounded_inputs,
        validate_response,
    )
    from pdos_next.agent.kernel import policy
    from pdos_next.agent.model_configuration.ports import SecretBinding
    from pdos_next.agent.model_configuration.service import secret_digest
    from pdos_next.providers.types import ProviderError

    # A call left "started" by a crashed attempt is closed conservatively first.
    with transaction(ctx) as session:
        budget = budget_row(session, ctx.tenant_id)
        for call in session.scalars(select(MemoryEmbeddingCall).where(
                MemoryEmbeddingCall.owner_id == ctx.requester_id,
                MemoryEmbeddingCall.state == "started").with_for_update()).all():
            _finish(budget, call, call.reserved_micro_usd, None, "unknown")
    with transaction(ctx) as session:
        budget = budget_row(session, ctx.tenant_id)
        profile, metadata, rows, skipped = plan(session, ctx, ref)
        if not rows:
            return {"status": "ready", "embedded": 0, "skipped": skipped}
        texts = bounded_inputs(tuple(body for _episode, _categories, body in rows))
        chosen = set().union(*(item for _episode, item, _body in rows))
        provider = canonical_provider(secrets, ctx.tenant_id, metadata)
        decision = policy.egress(session, ctx, provider, data_categories=chosen)
        secret = bound_secret(secrets, ctx.tenant_id, metadata, required=True)
        frozen = SecretBinding(**{
            **profile.secret_json, "tenant_id": UUID(profile.secret_json["tenant_id"]),
            "reference": UUID(profile.secret_json["reference"]),
            "version": UUID(profile.secret_json["version"]),
        })
        if secret_digest(secret) != secret_digest(frozen):
            raise DomainError("VERSION_CONFLICT", "Embedding 凭据已轮换，须重新确认 profile。")
        card = pricing_for(ctx.tenant_id, metadata)
        card.validate(provider, SimpleNamespace(model=metadata.model,
                                                version=metadata.model_version))
        reserve_tokens = card.input_upper_bound(wire_bytes(metadata, texts))
        reserve_cost = card.reserve(reserve_tokens, 0)
        if budget.spent_micro_usd + budget.held_micro_usd + reserve_cost > budget.limit_micro_usd:
            raise DomainError("RATE_LIMITED", "租户索引预算不足；本人情景仍可用关键词检索。")
        try:
            material = secrets.resolve(secret)
        except Exception:  # noqa: BLE001 -- provider/KMS errors must be redacted
            raise DomainError("SOURCE_UNAVAILABLE", "Embedding 独立凭据暂不可用。") from None
        if material is None or material.binding != secret:
            raise DomainError("SOURCE_UNAVAILABLE", "Embedding 独立凭据暂不可用。")
        call = MemoryEmbeddingCall(
            id=uuid4(), tenant_id=ctx.tenant_id, owner_id=ctx.requester_id,
            profile_version_id=profile.id, state="started", revision=1,
            episode_ids=[str(episode.id) for episode, _categories, _body in rows],
            character_count=sum(map(len, texts)), input_digest=digest(texts),
            data_categories=sorted(chosen),
            egress={**asdict(decision), "checked_at": decision.checked_at.isoformat()},
            pricing=card.snapshot(), reserved_tokens=reserve_tokens,
            reserved_micro_usd=reserve_cost, charged_micro_usd=0,
        )
        session.add(call)
        budget.held_micro_usd += reserve_cost
        session.flush()
        identity, version = call.id, profile.id
        planned = [(episode.id, episode.session_id, digest(body))
                   for episode, _categories, body in rows]
    response = measured = None
    failed = False
    try:
        response = client.embed(metadata, texts, material, timeout=30.0)
        measured = response
        validate_response(response, count=len(texts), dimensions=metadata.dimensions)
        if response.input_tokens is not None and response.input_tokens > reserve_tokens:
            raise ProviderError("BILLING_BOUNDS", unknown=True)
    except Exception:  # noqa: BLE001 -- provider/KMS bodies and credentials are redacted
        response, measured, failed = None, None, True
    with transaction(ctx) as session:
        budget = budget_row(session, ctx.tenant_id)
        call = session.scalar(select(MemoryEmbeddingCall).where(
            MemoryEmbeddingCall.id == identity).with_for_update())
        cost, tokens, state = settlement(reserved_micro_usd=call.reserved_micro_usd,
                                         response=measured, pricing=card)
        _finish(budget, call, cost, tokens, state)
        if response is not None:
            call.provider_request_id = response.request_id
        session.flush()
        if response is not None:
            for (episode_id, session_id, text_digest), vector in zip(
                planned, response.vectors, strict=True,
            ):
                session.execute(insert(MemoryEpisodeVector).values(
                    id=uuid4(), tenant_id=ctx.tenant_id, owner_id=ctx.requester_id,
                    session_id=session_id, episode_id=episode_id, profile_version_id=version,
                    call_id=identity, text_digest=text_digest, dimensions=metadata.dimensions,
                    vector=unit_vector(vector), norm=1.0,
                ).on_conflict_do_nothing(
                    index_elements=["tenant_id", "episode_id", "profile_version_id"]))
    if failed:
        raise DomainError("SOURCE_UNAVAILABLE", "情景向量化未形成可核对结果，费用已保守占账。")
    return {"status": "ready", "embedded": len(planned), "skipped": skipped,
            "call_id": str(identity)}


def owner_context(ref):
    return Context(ref["tenant_id"], ref["owner_id"], ref["owner_id"])


def workflow_id(value):
    ref = reference(value)
    return (f"pdos-memory-vectors:{ref['tenant_id']}:{ref['owner_id']}:"
            f"{ref['profile_version_id']}:{digest([str(i) for i in ref['episode_ids']])[:16]}")


async def dispatch_pending(engine, tenant_id, client, *, task_queue="pdos-next-domain-v1"):
    """The dispatch role learns only UUIDs of eligible episodes still lacking a vector."""
    from temporalio.common import WorkflowIDReusePolicy
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from pdos_next.core.database import tenant_session

    from .vector_workflow import MemoryEpisodeVectors

    with tenant_session(engine, tenant_id) as session:
        rows = session.execute(
            text("SELECT * FROM memory_pending_vector_references(:tenant,200)"),
            {"tenant": tenant_id},
        ).mappings().all()
    groups = {}
    for row in rows:
        groups.setdefault((row["owner_id"], row["profile_version_id"]), []).append(
            str(row["episode_id"]))
    delivered = unavailable = 0
    for (owner, profile), ids in groups.items():
        for start in range(0, len(ids), MAX_BATCH):
            value = {"tenant_id": str(tenant_id), "owner_id": str(owner),
                     "profile_version_id": str(profile),
                     "episode_ids": ids[start:start + MAX_BATCH]}
            try:
                await client.start_workflow(
                    MemoryEpisodeVectors.run, value, id=workflow_id(value),
                    task_queue=task_queue,
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                )
            except WorkflowAlreadyStartedError:
                continue
            except Exception:  # noqa: BLE001 -- discovery retries on the next loop
                unavailable += 1
            else:
                delivered += 1
    return {"pending": len(rows), "delivered": delivered, "unavailable": unavailable}


# ---------------------------------------------------------------------------
# Recall: exact cosine over the owner's own vectors of the same profile version.

VECTOR_POOL = 50


def nearest(session, run, vector, profile_version_id, conditions):
    """Owner's episode ids ordered by similarity; exact scan (personal data is small)."""
    literal = "[" + ",".join(str(float(value)) for value in vector) + "]"
    rows = session.execute(
        select(MemoryEpisodeVector.episode_id,
               MemoryEpisodeVector.vector.op("<#>")(text("CAST(:query AS vector)").bindparams(
                   query=literal)).label("distance"))
        .join(MemoryEpisode, MemoryEpisode.id == MemoryEpisodeVector.episode_id)
        .where(MemoryEpisodeVector.owner_id == run.requester_id,
               MemoryEpisodeVector.profile_version_id == profile_version_id,
               MemoryEpisodeVector.dimensions == len(vector), *conditions)
        .order_by(text("distance"), MemoryEpisodeVector.episode_id)
        .limit(VECTOR_POOL)
    ).all()
    return [row.episode_id for row in rows if math.isfinite(row.distance)]
