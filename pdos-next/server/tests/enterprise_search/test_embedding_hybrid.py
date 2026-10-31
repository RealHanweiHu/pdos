"""Mechanism/schema/SQL tests; no generated evaluation question set or real embedding."""

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pdos_agent_runtime.graph import registered_graph_context
from pydantic import SecretStr, ValidationError
from sqlalchemy import Boolean, Integer, String, column, table
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID

from pdos_next.agent_kernel.pricing import RateCard
from pdos_next.enterprise_search import embedding_hybrid as hybrid
from pdos_next.enterprise_search.embedding_jobs import pack
from pdos_next.enterprise_search.embedding_models import Vector
from pdos_next.enterprise_search.embedding_profiles import active, bound_secret
from pdos_next.enterprise_search.embedding_provider import OpenAIEmbeddingClient
from pdos_next.enterprise_search.embedding_runtime import (
    _finish_charge,
    execute_batch,
    settlement,
    unit_vector,
)
from pdos_next.enterprise_search.embedding_schemas import (
    EmbeddingMetadata,
    EmbeddingResponse,
    bounded_inputs,
    validate_response,
)
from pdos_next.enterprise_search.retrieval_filters import scoped_authority
from pdos_next.errors import DomainError
from pdos_next.model_configuration.ports import SecretBinding, SecretMaterial
from pdos_next.providers.types import ProviderError


def metadata(**changes):
    return EmbeddingMetadata(
        base_url="https://embedding.invalid/v1",
        model="synthetic-embed",
        model_version="synthetic@1",
        dimensions=2,
        connection_id=uuid4(),
        data_categories=["internal"],
        **changes,
    )


def card():
    current = datetime.now(UTC)
    return RateCard(
        "embedding.invalid",
        "synthetic-embed",
        "synthetic@1",
        "synthetic fixture",
        current - timedelta(days=1),
        current + timedelta(days=1),
        Decimal(1),
        Decimal(0),
        Decimal(0),
        Decimal(0),
        text_tokens_per_utf8_byte=Decimal(1),
        text_framing_tokens=10,
        text_billing_source="synthetic fixture",
        output_cap_covers_all_billing=True,
        covers_all_fees=True,
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True])
def test_nonfinite_or_bool_vectors_rejected(value):
    with pytest.raises(DomainError):
        validate_response(EmbeddingResponse(((1, value),)), count=1, dimensions=2)


@pytest.mark.parametrize("vectors", [(), ((0.0, 0.0),), ((1.0,),), ((1.0, 2.0), (3.0, 4.0))])
def test_wrong_count_dimension_and_zero_vector_fail_closed(vectors):
    with pytest.raises(DomainError):
        validate_response(EmbeddingResponse(vectors), count=1, dimensions=2)


def test_separate_slot_never_falls_back_to_chat_and_exception_is_redacted():
    tenant = uuid4()

    class OnlyChat:
        def current(self, *_args):
            raise AssertionError("Must not borrow chat credentials")

    with pytest.raises(DomainError, match="独立 Embedding"):
        bound_secret(OnlyChat(), tenant, metadata(), required=True)
    with pytest.raises(DomainError):
        bound_secret(None, tenant, metadata(), required=True)
    assert bound_secret(None, tenant, metadata(), required=False) is None
    wrong = SecretBinding(uuid4(), uuid4(), uuid4(), "openai-compatible", True)
    with pytest.raises(DomainError):
        bound_secret(
            SimpleNamespace(current_embedding=lambda *_: wrong), tenant, metadata(), required=True
        )


def test_originals_require_separate_explicit_category_selection():
    value = metadata().model_dump()
    for fields in (
        {"include_customer_original": True},
        {"data_categories": ["internal", "customer_original"]},
    ):
        with pytest.raises(ValidationError):
            EmbeddingMetadata.model_validate({**value, **fields})
    accepted = EmbeddingMetadata.model_validate(
        {
            **value,
            "include_customer_original": True,
            "data_categories": ["internal", "customer_original"],
        }
    )
    assert accepted.provider == "embedding.invalid"


def test_stable_normalization_handles_large_finite_values_without_overflow():
    normalized = unit_vector((1e300, -1e300))
    assert all(math.isfinite(value) for value in normalized)
    assert sum(value * value for value in normalized) == pytest.approx(1)
    assert Vector(2).get_col_spec() == "vector(2)"
    with pytest.raises(ValueError):
        Vector("2); DROP TABLE X;")


def test_unknown_usage_remains_conservatively_charged_known_usage_uses_existing_card():
    rates = card()
    reserved = rates.reserve(1000, 0)
    assert settlement(reserved_micro_usd=reserved, response=None, pricing=rates) == (
        reserved,
        None,
        "unknown",
    )
    response = EmbeddingResponse(((1.0, 0.0),), None)
    assert settlement(reserved_micro_usd=reserved, response=response, pricing=rates) == (
        reserved,
        None,
        "unknown_usage",
    )
    assert settlement(
        reserved_micro_usd=reserved, response=replace(response, input_tokens=7), pricing=rates
    ) == (7, 7, "completed")


def test_charge_exactly_once_and_unknown_reservation_cannot_disappear():
    budget = SimpleNamespace(held_micro_usd=100, spent_micro_usd=5)
    call = SimpleNamespace(state="started", reserved_micro_usd=100)
    _finish_charge(budget, call, 100, None, "unknown")
    assert (budget.held_micro_usd, budget.spent_micro_usd, call.state) == (0, 105, "unknown")
    with pytest.raises(DomainError):
        _finish_charge(budget, call, 0, 0, "completed")
    assert budget.spent_micro_usd == 105


def test_dispatch_rejects_before_any_io_outside_registered_graph():
    with pytest.raises(DomainError, match="注册执行图"):
        execute_batch(None, None, None, secrets=None, pricing_for=None, client=None)


def test_fixed_manifest_pack_has_bounded_size_and_count():
    rows = [{"text": "x" * 20_000, "id": n} for n in range(17)]
    chunks = list(pack(rows))
    assert [row for group in chunks for row in group] == rows
    assert all(
        len(group) <= 16 and sum(len(row["text"]) for row in group) <= 64_000 for group in chunks
    )
    with pytest.raises(DomainError):
        bounded_inputs(("x" * 20_001,))
    with pytest.raises(DomainError):
        bounded_inputs(tuple("a" for _ in range(17)))


def test_disabled_or_new_generation_cannot_reuse_old_vector_space():
    tenant, identity, logical = uuid4(), uuid4(), uuid4()
    profile = SimpleNamespace(
        tenant_id=tenant,
        profile_id=logical,
        revision=1,
        enabled=True,
        metadata_json=metadata().model_dump(mode="json"),
    )
    for head in (
        None,
        SimpleNamespace(enabled=False, revision=1),
        SimpleNamespace(enabled=True, revision=2),
    ):
        session = SimpleNamespace(get=lambda *_: profile, scalar=lambda *_, head=head: head)
        with pytest.raises(DomainError):
            active(session, tenant, identity)


def test_default_keyword_path_returns_original_without_vector_or_provider(monkeypatch):
    result = {"items": [], "coverage": {"status": "current"}}
    monkeypatch.setattr(hybrid, "search", lambda *_args, **_kwargs: result)
    monkeypatch.setattr(hybrid, "semantic_rows", lambda *_args, **_kwargs: pytest.fail("semantic"))
    assert hybrid.hybrid_search(None, None, None) is result


def test_rrf_preserves_exact_identifier_priority_and_deterministic_ties():
    rows = [
        {"source_type": "artifact", "source_id": key, "chunk_id": key, "channel": "keyword"}
        for key in ["b", "a", "c"]
    ]
    exact = {**rows[2], "channel": "exact_code"}
    first = hybrid.rrf([rows[0], exact], [rows[1], rows[0]], limit=3)
    assert [row["source_id"] for row in first] == ["c", "b", "a"]
    assert hybrid.rrf([rows[0], exact], [rows[1], rows[0]], limit=3) == first


def authority():
    return table(
        "current_authority",
        *[
            column(key, UUID)
            for key in (
                "tenant_id",
                "category_id",
                "product_id",
                "project_id",
                "proposal_id",
                "source_id",
                "object_id",
            )
        ],
        column("source_type", String),
        column("source_revision", Integer),
        column("content_hash", String),
        column("is_current", Boolean),
        column("private", Boolean),
        column("customer_original", Boolean),
    )


def test_shared_predicate_keeps_closed_source_version_hash_focus_and_exclusions_before_limit():
    source, tenant, category, source_id = authority(), uuid4(), uuid4(), uuid4()
    statement = scoped_authority(
        source,
        tenant,
        {"category_id": category, "project_id": uuid4()},
        include_history=True,
        include_sources={("artifact", source_id, 4, "a" * 64)},
        focus_object=("artifact", source_id),
        current_only=True,
        exclude_sources={("artifact", uuid4())},
        allow_customer_private=False,
    )
    sql = str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    for fragment in (
        "source_revision",
        "content_hash",
        "'" + "a" * 64 + "'",
        "is_current",
        "NOT",
        "customer_original",
        "object_id",
    ):
        assert fragment in sql
    assert "LIMIT" not in sql
    assert f"category_id = '{category}'" in sql


def test_explicit_empty_source_set_remains_closed_in_both_recall_channels():
    statement = scoped_authority(authority(), uuid4(), {}, include_history=True, include_sources=())
    sql = str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "1 != 1" in sql


def material():
    return SecretMaterial(
        SecretBinding(uuid4(), uuid4(), uuid4(), "openai-compatible", True),
        SecretStr("synthetic-key-only"),
    )


def test_bounded_transport_preserves_index_order_and_unknown_usage_without_network():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "model": "synthetic-embed",
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ],
            },
        )

    client = OpenAIEmbeddingClient(transport=httpx.MockTransport(respond))
    try:
        with registered_graph_context("xiaopai"):
            response = client.embed(metadata(), ("first", "second"), material(), timeout=1)
        assert response.vectors == ((1.0, 0.0), (0.0, 1.0)) and response.input_tokens is None
        assert len(requests) == 1 and requests[0].url.path == "/v1/embeddings"
        assert b"first" in requests[0].content and b"dimensions" in requests[0].content
    finally:
        client.close()


def test_invalid_vector_keeps_known_provider_usage_for_actual_accounting():
    client = OpenAIEmbeddingClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "data": [{"index": 0, "embedding": [1.0]}],
                    "usage": {"prompt_tokens": 9, "total_tokens": 9},
                },
            )
        )
    )
    try:
        with registered_graph_context("xiaopai"), pytest.raises(ProviderError) as caught:
            client.embed(metadata(), ("first",), material(), timeout=1)
        assert caught.value.usage.input_tokens == 9
    finally:
        client.close()


def test_transport_has_no_redirect_retry_or_unregistered_graph_escape():
    attempts = []

    def respond(request):
        attempts.append(request)
        return httpx.Response(
            307, headers={"Location": "https://unselected.invalid/embeddings"}, json={"data": []}
        )

    client = OpenAIEmbeddingClient(transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(DomainError):
            client.embed(metadata(), ("first",), material(), timeout=1)
        assert not attempts
        with registered_graph_context("xiaopai"), pytest.raises(ProviderError):
            client.embed(metadata(), ("first",), material(), timeout=1)
        assert len(attempts) == 1
    finally:
        client.close()


def test_exact_and_ann_sql_join_current_authority_before_distance_limit():
    from pdos_next.enterprise_search.embedding_hybrid import nearest_statement

    authorized = (
        table(
            "authorized_chunks",
            column("chunk_id", UUID),
            column("tenant_id", UUID),
            column("category_id", UUID),
            column("chunk_hash", String),
            column("source_type", String),
            column("source_id", UUID),
        )
        .select()
        .cte("allowed")
    )
    for strategy in ("exact", "iterative"):
        statement = nearest_statement(
            authorized, uuid4(), uuid4(), 2, (1.0, 0.0), limit=3, strategy=strategy
        )
        sql = str(statement.compile(dialect=postgresql.dialect()))
        if strategy == "exact":
            assert "JOIN enterprise_chunk_embeddings ON" in sql
            assert "exact_semantic_pool AS MATERIALIZED" in sql
        else:
            assert "FROM enterprise_chunk_embeddings" in sql
            assert "iterative_semantic_authority AS MATERIALIZED" in sql
            assert (
                "(enterprise_chunk_embeddings.chunk_id, enterprise_chunk_embeddings.chunk_hash, "
                "enterprise_chunk_embeddings.category_id) IN (SELECT "
                "iterative_semantic_authority.chunk_id, "
                "iterative_semantic_authority.chunk_hash, iterative_semantic_authority.category_id"
                in sql
            )
            assert "IS true" in sql
        assert "allowed.chunk_hash" in sql and "allowed.category_id" in sql
        assert "enterprise_chunk_embeddings.profile_version_id =" in sql
        assert "enterprise_chunk_embeddings.dimensions =" in sql
        assert "vector(2)" in sql and "source_rank" in sql
    with pytest.raises(ValueError):
        nearest_statement(authorized, uuid4(), uuid4(), "2);DROP TABLE x;", (1.0, 0.0), limit=1)


def test_temporal_embedding_definitions_remain_sandboxed_without_provider_imports():
    import asyncio

    from temporalio import workflow
    from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

    from pdos_next.enterprise_search.embedding_workflow import (
        EnterpriseEmbedding,
        EnterpriseEmbeddingProjection,
        EnterpriseEmbeddingRebuild,
    )

    async def validate():
        for registered in (
            EnterpriseEmbedding,
            EnterpriseEmbeddingProjection,
            EnterpriseEmbeddingRebuild,
        ):
            SandboxedWorkflowRunner().prepare_workflow(
                workflow._Definition.must_from_class(registered)
            )

    asyncio.run(validate())


def test_legacy_chat_slot_is_not_an_embedding_host_and_no_key_is_resolved():
    from pdos_next.enterprise_search.embedding_composition import configured_ports

    class Chat:
        def current(self, *_args):
            raise AssertionError("No default chat fallback")

        def resolve(self, *_args):
            raise AssertionError("Composition must not resolve a key")

    ports = configured_ports(SimpleNamespace(secrets=Chat()))
    assert ports.secrets is None and ports.pricing_for is None and ports.client is None


def test_projection_sender_routes_exact_new_event_and_preserves_legacy_projection():
    import asyncio

    from pdos_next.enterprise_search import events as module
    from pdos_next.enterprise_search.embedding_workflow import (
        EnterpriseEmbedding,
        EnterpriseEmbeddingProjection,
    )
    from pdos_next.enterprise_search.workflow import EnterpriseProjection

    started = []

    class Client:
        async def start_workflow(self, entry, reference, **options):
            started.append((entry, reference, options))

    event = SimpleNamespace(
        event_type="embedding.profile_saved", tenant_id="tenant", event_id="event"
    )
    # event() uses the actual dataclass Envelope; no invented command dispatch.
    from pdos_next.dispatch.outbox import Envelope

    event = Envelope(
        "event",
        "tenant",
        "category",
        None,
        "profile",
        1,
        event.event_type,
        1,
        "correlation",
        "lease",
        "actor",
        "actor",
    )

    async def run():
        sender = module.ProjectionSender(Client())
        first = await sender.event(event)
        assert started[-1][0] is EnterpriseEmbedding.run
        source = replace(event, event_type="artifact.registered")
        assert await sender.event(source) == first
        assert started[-1][0] is EnterpriseProjection.run
        await module.ProjectionSender(Client(), embedding=True).event(source)
        assert started[-1][0] is EnterpriseEmbeddingProjection.run
        assert await sender.event(replace(event, event_type="embedding.call_reconciled")) is None
        from pdos_next.enterprise_search.embedding_workflow import (
            EnterpriseEmbeddingRebuild,
        )
        from pdos_next.enterprise_search.recovery_workflow import EnterpriseRebuild

        ctx = SimpleNamespace(
            tenant_id=uuid4(), actor_id=uuid4(), requester_id=uuid4(), category_id=None
        )
        generation = uuid4()
        await sender.rebuild(ctx, generation)
        assert started[-1][0] is EnterpriseRebuild.run
        await module.ProjectionSender(Client(), embedding=True).rebuild(ctx, generation)
        assert started[-1][0] is EnterpriseEmbeddingRebuild.run
        assert started[-1][1]["generation"] == str(generation)
        assert started[-1][1]["rebuild"] is True

    asyncio.run(run())


def test_public_profile_and_cost_views_omit_vectors_body_and_credential_references():
    from pdos_next.enterprise_search.embedding_api import call_view, profile_view

    profile = SimpleNamespace(
        profile_id=uuid4(),
        id=uuid4(),
        revision=2,
        budget_revision=3,
        metadata_json=metadata().model_dump(mode="json"),
        enabled=True,
        secret_json={
            "reference": "DO_NOT_RETURN_SECRET_REF",
            "version": "DO_NOT_RETURN_SECRET_VERSION",
            "available": True,
        },
    )
    call = SimpleNamespace(
        id=uuid4(),
        revision=1,
        attempt=1,
        state="unknown_usage",
        egress={"provider": "embedding.invalid"},
        data_categories=["internal"],
        source_count=2,
        character_count=500,
        reserved_micro_usd=100,
        charged_micro_usd=100,
        input_tokens=None,
        created_at=datetime.now(UTC),
        vector="NO_VECTOR",
        text="NO_BODY",
    )
    batch = SimpleNamespace(
        id=uuid4(), profile_version_id=profile.id, state="ready", last_error=None
    )
    value = {
        "profile": profile_view(profile, SimpleNamespace(enabled=True)),
        "call": call_view(call, batch),
    }
    assert value["call"]["usage_known"] is False and value["call"]["input_tokens"] is None
    assert value["call"]["charged_micro_usd"] == value["call"]["reserved_micro_usd"] == 100
    assert all(
        marker not in str(value)
        for marker in (
            "DO_NOT_RETURN_SECRET_REF",
            "DO_NOT_RETURN_SECRET_VERSION",
            "NO_VECTOR",
            "NO_BODY",
        )
    )


def test_semantic_relation_uuid_normalization_matches_native_keyword_json_rows():
    from pdos_next.enterprise_search.relations import FIELDS, decorate

    origin_id, target_id = uuid4(), uuid4()
    origin = dict.fromkeys(FIELDS)
    origin.update(
        source_type="issue",
        source_id=str(origin_id),
        source_revision=1,
        content_hash="a" * 64,
        private=True,
        customer_original=False,
    )
    target = dict.fromkeys(FIELDS)
    target.update(
        source_type="capa",
        source_id=target_id,
        source_revision=1,
        private=False,
        customer_original=False,
        direct_target=False,
        origin_kind="issue",
        origin_id=origin_id,
        relation="registered",
        body_chars=10,
    )
    result = decorate({"items": [origin]}, hybrid.public_rows([target]))
    assert result["related_returned"] == 1
    related = result["items"][1]
    assert related["source_id"] == str(target_id)
    assert related["relation"]["source_id"] == str(origin_id) and related["private"] is True


def test_disabling_does_not_require_an_available_embedding_key_service():
    class Broken:
        def current_embedding(self, *_args):
            raise RuntimeError("DO_NOT_EXPOSE_CREDENTIAL_BACKEND")

    assert bound_secret(Broken(), uuid4(), metadata(), required=False) is None
    with pytest.raises(DomainError) as failure:
        bound_secret(Broken(), uuid4(), metadata(), required=True)
    assert "DO_NOT_EXPOSE_CREDENTIAL_BACKEND" not in str(failure.value)


def test_metadata_get_reuses_the_native_dependency_without_an_extra_command_entry():
    from fastapi import Depends, FastAPI

    from pdos_next.enterprise_search.embedding_api import register_routes

    app = FastAPI()
    register_routes(app, object(), Depends(lambda: None))
    routes = app.openapi()["paths"]
    assert list(routes) == ["/v1/categories/{category_id}/embedding-profile"]
    assert set(routes["/v1/categories/{category_id}/embedding-profile"]) == {"get"}


@pytest.mark.parametrize(
    "reference",
    [
        None,
        {},
        {"rebuild": True, "context": None, "generation": "x"},
        {
            "rebuild": True,
            "context": {
                "tenant_id": str(uuid4()),
                "actor_id": str(uuid4()),
                "requester_id": str(uuid4()),
                "category_id": None,
            },
            "generation": "not-a-uuid",
        },
    ],
)
def test_invalid_rebuild_envelopes_fail_before_any_database_or_provider(reference):
    from pdos_next.enterprise_search.embedding_activities import EmbeddingActivities

    activities = object.__new__(EmbeddingActivities)
    with pytest.raises(DomainError):
        activities.rebuild_plan(reference)


def test_real_artifact_authority_chunk_join_compiles_with_fixed_pin_and_exclusion(monkeypatch):
    from pdos_next.enterprise_search import embedding_sources as sources
    from pdos_next.enterprise_search.schemas import SearchInput

    tenant, category, source_id, excluded = (uuid4() for _ in range(4))
    ctx = SimpleNamespace(tenant_id=tenant)
    monkeypatch.setattr(sources, "require_context", lambda *_: None)
    monkeypatch.setattr(
        sources,
        "_narrow",
        lambda *_: {
            "category_id": category,
            "product_id": None,
            "project_id": None,
            "proposal_id": None,
        },
    )
    monkeypatch.setattr(sources, "prepare_read", lambda *_: None)
    monkeypatch.setattr(sources, "dependency_originals", lambda *_: set())
    monkeypatch.setattr(sources, "safe_originals", lambda *_: set())
    statement = sources.readable_chunks(
        object(),
        ctx,
        SearchInput(query="synthetic", source_types=["artifact"]),
        include_sources=[("artifact", source_id, 3, "b" * 64)],
        exclude_sources=[("artifact", excluded)],
        current_only=True,
        allow_customer_private=False,
    )
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "embedding_scoped_authority" in sql and "enterprise_search_chunks" in sql
    assert "enterprise_search_sources.work_key = enterprise_search_chunks.work_key" in sql
    assert "enterprise_search_chunks.chunker_version =" in sql
    assert any(
        ("artifact", source_id, 3, "b" * 64) in value
        for value in compiled.params.values()
        if isinstance(value, list)
    )
