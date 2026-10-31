"""Registered-graph embedding dispatch, using P26 and the existing RateCard rules.

Background costs belong exclusively to the tenant's indexing budget. No user Run
or chat model is manufactured for indexing, and no provider fallback exists.
"""

import math
from dataclasses import asdict
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert

from pdos_next.errors import DomainError
from pdos_next.model_configuration.ports import SecretBinding
from pdos_next.model_configuration.service import secret_digest
from pdos_next.providers.types import ProviderError, ProviderUsage
from pdos_next.service import digest

from .embedding_identity import canonical_provider
from .embedding_models import (
    ChunkEmbedding,
    EmbeddingBatch,
    EmbeddingBudget,
    EmbeddingCall,
)
from .embedding_profiles import active, bound_secret
from .embedding_schemas import EmbeddingResponse, bounded_inputs, validate_response
from .embedding_sources import categories, fixed_rows

MAX_ATTEMPTS = 3


def unit_vector(vector):
    if not vector or not any(vector) or any(not math.isfinite(value) for value in vector):
        raise DomainError("SOURCE_UNAVAILABLE", "Embedding 数值无效。")
    largest = max(abs(value) for value in vector)
    scaled = [value / largest for value in vector]
    norm = math.sqrt(sum(value * value for value in scaled))
    return tuple(value / norm for value in scaled)


def wire_bytes(metadata, texts):
    from pdos_next.agent_kernel.result_continuation import serialized

    from .embedding_provider import body_for

    return len(serialized(body_for(metadata, texts)).encode())


def settlement(*, reserved_micro_usd, response, pricing):
    """Unknown input usage never becomes a zero charge or a measured token count."""
    if response is None or response.input_tokens is None:
        return reserved_micro_usd, None, "unknown" if response is None else "unknown_usage"
    usage = ProviderUsage(response.input_tokens, 0)
    return pricing.actual(usage), response.input_tokens, "completed"


def budget_row(session, tenant_id):
    row = session.scalar(
        select(EmbeddingBudget)
        .where(
            EmbeddingBudget.tenant_id == tenant_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise DomainError("SOURCE_UNAVAILABLE", "租户索引预算尚未配置。")
    return row


def _call(session, ctx, identity):
    row = session.scalar(
        select(EmbeddingCall)
        .where(
            EmbeddingCall.tenant_id == ctx.tenant_id,
            EmbeddingCall.id == identity,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise DomainError("FORBIDDEN_SCOPE", "Embedding 调用不可读。")
    return row


def reconciliation_plan(session, ctx, payload):
    budget = budget_row(session, ctx.tenant_id)
    row = _call(session, ctx, payload.call_id)
    if row.revision != payload.expected_revision or row.state not in {"unknown", "unknown_usage"}:
        raise DomainError("VERSION_CONFLICT", "原调用已对账或版本已变化。")
    return {
        "row": row,
        "budget": budget,
        "public": {
            "call_id": str(row.id),
            "state": row.state,
            "charged_micro_usd": row.charged_micro_usd,
            "actual_micro_usd": payload.actual_micro_usd,
            "input_tokens": payload.input_tokens,
            "evidence_ref": payload.evidence_ref,
            "effect": "仅核对原费用；不重新调用、不恢复索引、不改变原结果未知事实。",
        },
    }


def reconcile(plan, payload):
    row, budget = plan["row"], plan["budget"]
    budget.spent_micro_usd += payload.actual_micro_usd - row.charged_micro_usd
    row.charged_micro_usd, row.input_tokens = payload.actual_micro_usd, payload.input_tokens
    row.state, row.evidence_ref = "reconciled", payload.evidence_ref
    row.revision += 1
    row.action_result = {
        "charged_micro_usd": row.charged_micro_usd,
        "input_tokens": row.input_tokens,
        "result_reissued": False,
    }
    return row


def _finish_charge(budget, call, cost, tokens, state):
    if call.state != "started":
        raise DomainError("VERSION_CONFLICT", "原调用已结算，不能重复占账。")
    if budget.held_micro_usd < call.reserved_micro_usd or cost < 0:
        raise DomainError("VALIDATION_FAILED", "原 Embedding 预算计数需要核对。")
    budget.held_micro_usd -= call.reserved_micro_usd
    budget.spent_micro_usd += cost
    call.charged_micro_usd, call.input_tokens, call.state = cost, tokens, state


def _vectors_present(session, ctx, batch):
    pairs = [(UUID(row["chunk_id"]), row["chunk_hash"]) for row in batch.manifest["chunks"]]
    count = session.scalar(
        select(func.count())
        .select_from(ChunkEmbedding)
        .where(
            ChunkEmbedding.tenant_id == ctx.tenant_id,
            ChunkEmbedding.profile_version_id == batch.profile_version_id,
            tuple_(ChunkEmbedding.chunk_id, ChunkEmbedding.chunk_hash).in_(pairs),
        )
    )
    return count == len(pairs)


def batch_readiness(transaction, ctx, identity):
    with transaction(ctx) as session:
        batch = session.get(EmbeddingBatch, identity)
        if batch is None or batch.manifest["context"] != context_value(ctx):
            raise DomainError("FORBIDDEN_SCOPE", "Embedding 检查点不属于固定批次。")
        try:
            active(session, ctx.tenant_id, batch.profile_version_id)
            fixed_rows(session, ctx, batch.manifest)
        except DomainError:
            return {"batch_id": str(identity), "status": "unavailable", "code": "SOURCE_STALE"}
        if not _vectors_present(session, ctx, batch):
            return {
                "batch_id": str(identity),
                "status": "unavailable",
                "code": "DERIVED_INDEX_MISSING",
            }
        return {"batch_id": str(identity), "status": "ready", "replayed": True}


def execute_batch(transaction, ctx, batch_id, *, secrets, pricing_for, client):
    """The caller MUST execute this inside the registered LangGraph node.

    transaction is the existing tenant_session factory bound to this exact ctx;
    provider I/O occurs after a committed started row, never inside a DB UOW.
    """
    from pdos_agent_runtime.graph import in_registered_agent_graph

    if not in_registered_agent_graph():
        raise DomainError("FORBIDDEN_SCOPE", "Embedding 必须经已注册执行图。")
    if client is None or not callable(getattr(client, "embed", None)):
        raise DomainError("SOURCE_UNAVAILABLE", "尚未配置独立 Embedding 端口。")
    # Same PostgreSQL advisory-lock mechanism as kernel composition. This outer
    # UOW holds only a lock, not source rows; started/settled rows commit in their
    # own UOWs. A duplicate worker cannot mistake a live provider call for a crash.
    lock_key = int(digest(["embedding-batch/v1", ctx.tenant_id, batch_id])[:15], 16)
    with transaction(ctx) as session:
        if not session.scalar(select(func.pg_try_advisory_xact_lock(lock_key))):
            raise DomainError("RATE_LIMITED", "同一 Embedding 批次正在处理。")
        return _execute_locked(
            transaction, ctx, batch_id, secrets=secrets, pricing_for=pricing_for, client=client
        )


def _execute_locked(transaction, ctx, batch_id, *, secrets, pricing_for, client):
    from pdos_next.agent_kernel import policy

    # Recovery bookkeeping commits even if the next attempt cannot be admitted.
    with transaction(ctx) as session:
        budget = budget_row(session, ctx.tenant_id)
        batch = session.scalar(
            select(EmbeddingBatch)
            .where(
                EmbeddingBatch.id == batch_id,
                EmbeddingBatch.tenant_id == ctx.tenant_id,
            )
            .with_for_update()
        )
        if batch is None or batch.manifest["context"] != context_value(ctx):
            raise DomainError("FORBIDDEN_SCOPE", "Embedding 批次不属于固定服务器信封。")
        previous = session.scalar(
            select(EmbeddingCall)
            .where(
                EmbeddingCall.batch_id == batch.id,
            )
            .order_by(EmbeddingCall.attempt.desc())
            .limit(1)
            .with_for_update()
        )
        if previous is not None and previous.state == "started":
            _finish_charge(budget, previous, previous.reserved_micro_usd, None, "unknown")
            batch.state = "retryable"
    with transaction(ctx) as session:
        budget = budget_row(session, ctx.tenant_id)
        batch = session.scalar(
            select(EmbeddingBatch)
            .where(
                EmbeddingBatch.id == batch_id,
                EmbeddingBatch.tenant_id == ctx.tenant_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if batch is None or batch.manifest["context"] != context_value(ctx):
            raise DomainError("FORBIDDEN_SCOPE", "Embedding 批次不属于固定服务器信封。")
        profile, metadata = active(session, ctx.tenant_id, batch.profile_version_id, lock=True)
        if batch.state == "ready":
            fixed_rows(session, ctx, batch.manifest)
            if _vectors_present(session, ctx, batch):
                return {"batch_id": str(batch.id), "status": "ready", "replayed": True}
            batch.state, batch.last_error = "unavailable", "DERIVED_INDEX_MISSING"
            return {"batch_id": str(batch.id), "status": batch.state, "code": batch.last_error}
        if batch.attempts >= MAX_ATTEMPTS:
            raise DomainError("SOURCE_UNAVAILABLE", "Embedding 已达有限重试上限，保留未知费用。")
        rows = fixed_rows(session, ctx, batch.manifest)
        texts = bounded_inputs(tuple(row["text"] for row in rows))
        actual_categories = set().union(*(categories(row) for row in rows))
        if not actual_categories <= set(metadata.data_categories):
            raise DomainError("FORBIDDEN_SCOPE", "批次来源类别未被当前 profile 明确启用。")
        provider = canonical_provider(secrets, ctx.tenant_id, metadata)
        decision = policy.egress(session, ctx, provider, data_categories=actual_categories)
        secret = bound_secret(secrets, ctx.tenant_id, metadata, required=True)
        frozen_secret = SecretBinding(
            **{
                **profile.secret_json,
                "tenant_id": UUID(profile.secret_json["tenant_id"]),
                "reference": UUID(profile.secret_json["reference"]),
                "version": UUID(profile.secret_json["version"]),
            }
        )
        if secret_digest(secret) != secret_digest(frozen_secret):
            raise DomainError("VERSION_CONFLICT", "Embedding 凭据已轮换，须重新确认 profile。")
        card = pricing_for(ctx.tenant_id, metadata)
        card.validate(
            provider, SimpleNamespace(model=metadata.model, version=metadata.model_version)
        )
        reserve_tokens = card.input_upper_bound(wire_bytes(metadata, texts))
        reserve_cost = card.reserve(reserve_tokens, 0)
        if budget.spent_micro_usd + budget.held_micro_usd + reserve_cost > budget.limit_micro_usd:
            raise DomainError("RATE_LIMITED", "租户索引预算不足；关键词检索仍可用。")
        try:
            material = secrets.resolve(secret)
        except Exception:  # noqa: BLE001 -- provider/KMS errors must be redacted
            raise DomainError("SOURCE_UNAVAILABLE", "Embedding 独立凭据暂不可用。") from None
        if material is None or material.binding != secret:
            raise DomainError("SOURCE_UNAVAILABLE", "Embedding 独立凭据暂不可用。")
        call = EmbeddingCall(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            category_id=ctx.category_id,
            batch_id=batch.id,
            attempt=batch.attempts + 1,
            revision=1,
            state="started",
            profile_digest=profile.binding_digest,
            input_digest=digest(texts),
            source_count=len({(row["source_type"], row["source_id"]) for row in rows}),
            character_count=sum(map(len, texts)),
            data_categories=sorted(actual_categories),
            egress={**asdict(decision), "checked_at": decision.checked_at.isoformat()},
            pricing=card.snapshot(),
            reserved_tokens=reserve_tokens,
            reserved_micro_usd=reserve_cost,
            charged_micro_usd=0,
        )
        session.add(call)
        budget.held_micro_usd += reserve_cost
        batch.attempts, batch.state = call.attempt, "running"
        session.flush()
        identity, profile_version = call.id, profile.id
    response, measured, failure = None, None, None
    try:
        response = client.embed(metadata, texts, material, timeout=30.0)
        if isinstance(response, EmbeddingResponse) and (
            response.input_tokens is None
            or type(response.input_tokens) is int
            and 0 <= response.input_tokens <= 2_147_483_647
        ):
            measured = response
        validate_response(response, count=len(texts), dimensions=metadata.dimensions)
        if response.input_tokens is not None and response.input_tokens > reserve_tokens:
            raise ProviderError("BILLING_BOUNDS", unknown=True)
    except ProviderError as error:
        measured = None
        if (
            not error.unknown
            and error.usage is not None
            and error.usage.input_tokens <= reserve_tokens
        ):
            measured = EmbeddingResponse((), error.usage.input_tokens, error.request_id)
        response, failure = None, "SOURCE_UNAVAILABLE"
    except Exception:  # noqa: BLE001 -- provider/KMS errors must be redacted
        # No provider/body/credential/exception text enters ordinary logs or receipts.
        response, failure = None, "SOURCE_UNAVAILABLE"
    with transaction(ctx) as session:
        budget = budget_row(session, ctx.tenant_id)
        call = _call(session, ctx, identity)
        batch = session.get(EmbeddingBatch, batch_id)
        cost, tokens, state = settlement(
            reserved_micro_usd=call.reserved_micro_usd, response=measured, pricing=card
        )
        _finish_charge(budget, call, cost, tokens, state)
        if response is not None:
            call.provider_request_id = response.request_id
            try:
                active(session, ctx.tenant_id, profile_version, lock=True)
                current = fixed_rows(session, ctx, batch.manifest)
            except DomainError:
                batch.state, batch.last_error = "unavailable", "SOURCE_STALE"
                return {"batch_id": str(batch.id), "status": "unavailable", "code": "SOURCE_STALE"}
            for row, vector in zip(current, response.vectors, strict=True):
                values = {
                    "tenant_id": ctx.tenant_id,
                    "category_id": row["category_id"],
                    "chunk_id": row["chunk_id"],
                    "chunk_hash": row["chunk_hash"],
                    "profile_version_id": profile_version,
                    "dimensions": metadata.dimensions,
                    "vector": unit_vector(vector),
                    "norm": 1.0,
                }
                session.execute(
                    insert(ChunkEmbedding)
                    .values(**values)
                    .on_conflict_do_update(
                        index_elements=["tenant_id", "chunk_id", "profile_version_id"],
                        set_=values,
                        where=ChunkEmbedding.chunk_hash != row["chunk_hash"],
                    )
                )
            batch.state, batch.last_error = "ready", None
        else:
            batch.state, batch.last_error = "retryable", failure
    if failure:
        raise DomainError("SOURCE_UNAVAILABLE", "Embedding 未形成可核对结果，费用已保守占账。")
    return {"batch_id": str(batch_id), "status": "ready", "replayed": False}


def context_value(ctx):
    return {
        key: str(getattr(ctx, key)) if getattr(ctx, key) is not None else None
        for key in ("tenant_id", "actor_id", "requester_id", "category_id")
    }
