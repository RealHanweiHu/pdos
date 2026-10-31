"""Synthetic orchestration and native provenance mechanisms; not a PG substitute."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from pdos_agent_runtime.graph import registered_graph_context
from pydantic import SecretStr, ValidationError

from pdos_next.agent_kernel.bindings import ModelBinding, execution_key
from pdos_next.agent_kernel.models import AgentToolCall
from pdos_next.agent_kernel.read_execution import (
    ReadBinding,
    build_read_binding,
)
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.enterprise_search import embedding_query as query_module
from pdos_next.enterprise_search.embedding_query import (
    QueryEmbedding,
    QueryPorts,
    QueryResult,
)
from pdos_next.enterprise_search.embedding_query_binding import (
    SNAPSHOT,
    TOOL,
    QueryBinding,
    QueryProfile,
    bind,
    key,
    payload,
    source,
)
from pdos_next.enterprise_search.embedding_schemas import EmbeddingResponse
from pdos_next.errors import DomainError
from pdos_next.model_configuration.ports import SecretBinding, SecretMaterial
from pdos_next.service import digest
from tests.agent_kernel.test_read_execution import MemorySession, fixture
from tests.enterprise_search.test_embedding_hybrid import card, metadata


def actual_parent():
    f = fixture()
    f.spec = default_registry().get("assistant.search")
    f.arguments = {"query": "固定模型的实际查询"}
    f.model.result = {
        "calls": [
            {"id": "provider-label", "name": "assistant.search", "arguments": deepcopy(f.arguments)}
        ]
    }
    binding = build_read_binding(
        f.scope, f.run, f.spec, f.source, ModelBinding.model_validate(f.model.execution_binding)
    )
    f.parent = AgentToolCall(
        id=uuid4(),
        tenant_id=f.run.tenant_id,
        run_id=f.run.id,
        tool="assistant.search",
        call_key=execution_key(f.run.id, f.model.id, 0),
        state="started",
        input_digest=digest(["assistant.search", f.arguments]),
        error_code=None,
        receipt_id=None,
        execution_binding=binding.model_dump(mode="json"),
    )
    f.session = MemorySession(f.run, f.model, f.parent)
    return f


def test_query_binding_inherits_exact_model_read_and_never_becomes_a_tool_or_read_handle():
    f = actual_parent()
    parent, text = source(f.session, f.scope, f.run, f.parent.id, f.arguments)
    profile = QueryProfile(profile_version_id=uuid4(), binding_digest="e" * 64, dimensions=2)
    proof = bind(parent, profile, text, f.scope.cancel_epoch)
    assert proof.kind == "embedding_query" and proof.query_digest == digest(text)
    assert proof.parent_input_digest == f.parent.input_digest
    assert key(f.run.id, f.parent.id) != f.parent.call_key
    assert payload(parent.id, profile, text)["query"] == f.arguments["query"]
    with pytest.raises(ValidationError):
        ReadBinding.model_validate(proof.model_dump(mode="json"))
    with pytest.raises(DomainError):
        default_registry().get(TOOL)
    with pytest.raises(ValidationError):
        QueryBinding.model_validate({**proof.model_dump(), "model_route_digest": "a" * 64})


@pytest.mark.parametrize(
    "target,field,value",
    [
        ("parent", "state", "completed"),
        ("parent", "tool", "assistant.extract"),
        ("parent", "run_id", uuid4()),
        ("parent", "error_code", "SOURCE_UNAVAILABLE"),
        ("model", "state", "started"),
        ("model", "receipt_id", uuid4()),
    ],
)
def test_missing_or_forged_parent_and_completed_model_are_rejected(target, field, value):
    f = actual_parent()
    setattr(getattr(f, target), field, value)
    with pytest.raises(DomainError):
        source(f.session, f.scope, f.run, f.parent.id, f.arguments)


def test_query_arguments_and_epoch_cannot_replace_model_or_run_facts():
    f = actual_parent()
    with pytest.raises(DomainError):
        source(f.session, f.scope, f.run, f.parent.id, {"query": "browser replacement"})
    f.parent.execution_binding = {**f.parent.execution_binding, "cancel_epoch": 1}
    with pytest.raises(DomainError):
        source(f.session, f.scope, f.run, f.parent.id, f.arguments)


class PortStore:
    """Records calls only; budget/SQL/claim correctness belongs to actual PG drafts."""

    def __init__(self, f):
        self.f, self.child, self.calls = f, None, []
        self.session = NS(get=f.session.get, scalar=self.scalar)

    def scalar(self, statement):
        if "pg_try_advisory_xact_lock" in str(statement):
            return True
        return self.child

    @contextmanager
    def transaction(self, _scope, *, lock=False):
        yield self.session, self.f.run

    @contextmanager
    def composition_lock(self, _scope, call_key):
        self.calls.append(("fence", call_key))
        yield

    def current(self, _scope):
        pass

    def emit(self, _scope, value):
        self.calls.append(("event", value))

    def claim(self, _scope, call_key, tool, arguments, **options):
        self.calls.append(("claim", options))
        self.child = AgentToolCall(
            id=uuid4(),
            tenant_id=self.f.run.tenant_id,
            run_id=self.f.run.id,
            tool=tool,
            call_key=call_key,
            input_digest=digest([tool, arguments]),
            execution_binding=options["execution_binding"],
            state="started",
        )
        return self.child.id, None

    def settle(self, _scope, _identity, **value):
        self.calls.append(("settle", value))
        self.child.state, self.child.result = "completed", value["result"]

    def release_call(self, _scope, _identity, **value):
        self.calls.append(("release", value))
        self.child.state = "unknown" if value.get("unknown") else "failed"


def configured(monkeypatch, *, response=None, error=None):
    f = actual_parent()
    meta = metadata()
    secret = SecretBinding(f.scope.tenant_id, uuid4(), uuid4(), "openai-compatible", True)
    profile = NS(
        id=uuid4(),
        binding_digest="e" * 64,
        secret_json={
            "tenant_id": str(secret.tenant_id),
            "reference": str(secret.reference),
            "version": str(secret.version),
            "protocol": secret.protocol,
            "available": True,
        },
    )
    active_calls, provider_calls = [], []

    def active(*_args):
        active_calls.append(True)
        return profile, meta

    monkeypatch.setattr(query_module, "active", active)
    from pdos_next.agent_kernel.policy import EgressDecision
    from pdos_next.clock import now

    monkeypatch.setattr(
        query_module.policy,
        "egress",
        lambda *_a, **_kw: EgressDecision(meta.provider, ("internal",), None, None, now()),
    )

    def embed(*args, **kwargs):
        provider_calls.append((args, kwargs))
        if error:
            raise error
        return response if response is not None else EmbeddingResponse(((3.0, 4.0),), 10)

    backend = NS(
        secrets=NS(
            provider_for=lambda *_: meta.provider,
            current_embedding=lambda *_: secret,
            resolve=lambda _value: SecretMaterial(secret, SecretStr("PRIVATE_KEY")),
        ),
        pricing_for=lambda *_: price,
        client=NS(embed=embed),
    )
    price = card()
    store = PortStore(f)
    ports = QueryPorts(backend, lambda _: profile.id)
    runtime = QueryEmbedding(store, ports, source_guard=lambda _: frozenset({"internal"}))
    return NS(
        f=f,
        meta=meta,
        secret=secret,
        profile=profile,
        active_calls=active_calls,
        provider_calls=provider_calls,
        store=store,
        runtime=runtime,
        ports=ports,
    )


def run(c):
    with registered_graph_context("xiaopai"):
        return c.runtime.prepare(c.f.scope, c.f.parent.id, c.f.arguments)


def test_real_orchestration_uses_independent_fee_lease_and_completed_replay(monkeypatch):
    c = configured(monkeypatch)
    result = run(c)
    assert result.status == "ready" and result.vector == (0.6, 0.8)
    assert len(c.provider_calls) == 1
    lease = next(value for kind, value in c.store.calls if kind == "claim")
    assert lease["execution_binding"]["kind"] == "embedding_query"
    assert lease["execution_binding"]["profile_version_id"] == str(c.profile.id)
    assert lease["cost_lease"][2] == 0 and lease["reservation"] > 10
    settlement = next(value for kind, value in c.store.calls if kind == "settle")
    assert settlement["usage"] == 10 and settlement["cost_usage"].input_tokens == 10
    events = [value for kind, value in c.store.calls if kind == "event"]
    assert events[0]["purpose"] == "query_embedding"
    assert "PRIVATE_KEY" not in str(events) and "vector" not in str(events)
    c.runtime.ports = replace(
        c.ports, profile_for=lambda _: pytest.fail("Profile is already frozen")
    )
    c.ports.backend.secrets.resolve = lambda _: pytest.fail(
        "Completed vector does not resolve a key"
    )
    assert run(c) == result and len(c.provider_calls) == 1


def test_no_selected_profile_is_keyword_and_has_no_fee_or_provider(monkeypatch):
    c = configured(monkeypatch)
    c.runtime.ports = replace(c.ports, profile_for=lambda _: None)
    result = run(c)
    assert result.status == "keyword" and result.vector is None
    assert c.f.run.versions[SNAPSHOT] is None
    assert not [row for row in c.store.calls if row[0] != "fence"] and c.provider_calls == []


def test_unknown_usage_retains_native_conservative_charge_and_does_not_invent_tokens(monkeypatch):
    c = configured(monkeypatch, response=EmbeddingResponse(((1.0, 0.0),), None))
    result = run(c)
    assert result.vector is None and result.status == "query_usage_unknown"
    release = next(value for kind, value in c.store.calls if kind == "release")
    assert release["unknown"] is True and "cost_usage" not in release and "usage" not in release
    assert not any(kind == "settle" for kind, _ in c.store.calls)
    assert run(c).vector is None and len(c.provider_calls) == 1


def test_known_invalid_provider_response_records_actual_fee_without_semantic_result(monkeypatch):
    from pdos_next.providers.types import ProviderError, ProviderUsage

    c = configured(
        monkeypatch, error=ProviderError("PROVIDER_RESPONSE_INVALID", usage=ProviderUsage(7, 0))
    )
    assert run(c).vector is None
    release = next(value for kind, value in c.store.calls if kind == "release")
    assert release["unknown"] is False and release["usage"] == 7
    assert release["cost_usage"].input_tokens == 7


def test_frozen_query_profile_cannot_be_changed_or_silently_switched(monkeypatch):
    c = configured(monkeypatch)
    run(c)
    c.f.run.versions = {
        **c.f.run.versions,
        SNAPSHOT: {**c.f.run.versions[SNAPSHOT], "profile_version_id": str(uuid4())},
    }
    with pytest.raises(DomainError) as failure:
        run(c)
    assert failure.value.code == "VERSION_CONFLICT" and len(c.provider_calls) == 1


def test_query_is_unavailable_outside_registered_main_graph(monkeypatch):
    c = configured(monkeypatch)
    with pytest.raises(DomainError):
        c.runtime.prepare(c.f.scope, c.f.parent.id, c.f.arguments)
    with registered_graph_context("xiaopai"), pytest.raises(DomainError):
        c.runtime.prepare(c.f.scope.child("assistant_extract"), c.f.parent.id, c.f.arguments)
    assert c.store.calls == [] and c.provider_calls == []


def test_query_projection_keeps_strict_correction_filters_and_uses_one_fixed_vector(monkeypatch):
    capture = []

    def search(*_args, **kwargs):
        capture.append(kwargs)
        return {"items": []}

    monkeypatch.setattr(query_module, "hybrid_search", search)
    profile = QueryProfile(profile_version_id=uuid4(), binding_digest="e" * 64, dimensions=2)
    result = QueryResult(profile, (0.6, 0.8), "ready")
    filters = {
        "include_sources": {("issue", str(uuid4()), 3, "f" * 64)},
        "focus_object": ("issue", str(uuid4())),
        "exclude_sources": [("artifact", str(uuid4()))],
    }
    result.search(None, None, None, **filters)
    result.search(None, None, None, **filters)
    assert len(capture) == 2
    assert all(all(row[name] == value for name, value in filters.items()) for row in capture)
    assert capture[0]["vector"] == capture[1]["vector"] == (0.6, 0.8)
    assert capture[0]["strategy"] == "exact"


def test_provider_unknown_flag_cannot_be_relabelled_as_actual_fee(monkeypatch):
    from pdos_next.providers.types import ProviderError, ProviderUsage

    c = configured(
        monkeypatch,
        error=ProviderError("TRANSPORT_UNKNOWN", unknown=True, usage=ProviderUsage(7, 0)),
    )
    assert run(c).vector is None
    release = next(value for kind, value in c.store.calls if kind == "release")
    assert release["unknown"] is True and release["cost_usage"] is None


def test_current_original_categories_are_not_downgraded_to_fit_profile(monkeypatch):
    c = configured(monkeypatch)
    c.runtime.source_guard = lambda _: {"internal", "customer_original"}
    captured = []
    original = query_module.policy.egress

    def egress(*args, **kwargs):
        captured.append(kwargs["data_categories"])
        return original(*args, **kwargs)

    monkeypatch.setattr(query_module.policy, "egress", egress)
    assert run(c).status == "ready"
    assert captured == [frozenset({"internal", "customer_original"})] * 2


def test_key_rotation_preserves_keyword_without_borrowing_chat_or_dispatching(monkeypatch):
    c = configured(monkeypatch)
    c.ports.backend.secrets.current_embedding = lambda *_: replace(c.secret, version=uuid4())
    assert run(c).status == "query_configuration_changed"
    assert not [row for row in c.store.calls if row[0] != "fence"] and not c.provider_calls


def test_p26_denial_preserves_keyword_without_a_fee_or_outbound(monkeypatch):
    c = configured(monkeypatch)

    def deny(*_args, **_kwargs):
        raise DomainError(
            "FORBIDDEN_SCOPE", "P26", detail={"reason_key": "provider_agreement_category"}
        )

    monkeypatch.setattr(query_module.policy, "egress", deny)
    assert run(c).status == "query_egress_not_permitted"
    assert not [row for row in c.store.calls if row[0] != "fence"] and not c.provider_calls


def test_private_cached_vector_shape_and_normalization_are_rechecked(monkeypatch):
    c = configured(monkeypatch)
    run(c)
    c.store.child.result["vector"] = [3.0, 4.0]
    with pytest.raises(DomainError) as failure:
        run(c)
    assert failure.value.code == "VERSION_CONFLICT" and len(c.provider_calls) == 1


def test_completed_vector_replay_rechecks_current_carried_source_authority(monkeypatch):
    c = configured(monkeypatch)
    assert run(c).status == "ready"

    def revoked(_scope):
        raise DomainError("SOURCE_UNAVAILABLE", "A carried fixed citation is no longer readable")

    c.runtime.source_guard = revoked
    with pytest.raises(DomainError):
        run(c)
    assert len(c.provider_calls) == 1


def test_closed_binding_version_does_not_accept_boolean_as_integer():
    f = actual_parent()
    profile = QueryProfile(profile_version_id=uuid4(), binding_digest="e" * 64, dimensions=2)
    value = bind(f.parent, profile, f.arguments["query"], 0).model_dump()
    with pytest.raises(ValidationError):
        QueryBinding.model_validate({**value, "proof_version": True})


def test_concurrent_native_fence_refuses_before_claim_or_provider(monkeypatch):
    c = configured(monkeypatch)

    @contextmanager
    def busy(*_args):
        raise RuntimeError("Existing native composition fence is held")
        yield

    c.store.composition_lock = busy
    with pytest.raises(RuntimeError):
        run(c)
    assert c.store.child is None and not c.provider_calls


def test_invalid_vector_with_known_usage_still_records_real_fee(monkeypatch):
    c = configured(monkeypatch, response=EmbeddingResponse(((1.0,),), 7))
    assert run(c).status == "query_unavailable"
    release = next(value for kind, value in c.store.calls if kind == "release")
    assert release["unknown"] is False and release["cost_usage"].input_tokens == 7
    assert not any(kind == "settle" for kind, _ in c.store.calls)


def test_acl_loss_after_measured_response_releases_actual_fee_without_result(monkeypatch):
    c = configured(monkeypatch)
    checked = []

    def current(_scope):
        checked.append(True)
        if len(checked) == 2:
            raise DomainError("FORBIDDEN_SCOPE", "Current source is revoked")

    c.store.current = current
    with pytest.raises(DomainError):
        run(c)
    release = next(value for kind, value in c.store.calls if kind == "release")
    assert release["unknown"] is False and release["usage"] == 10
    assert release["cost_usage"].input_tokens == 10
    assert not any(kind == "settle" for kind, _ in c.store.calls)


def test_unknown_or_excess_usage_is_never_recorded_as_actual(monkeypatch):
    c = configured(monkeypatch, response=EmbeddingResponse(((1.0, 0.0),), 2_147_483_647))
    assert run(c).status == "query_usage_unknown"
    release = next(value for kind, value in c.store.calls if kind == "release")
    assert release["unknown"] is True and "cost_usage" not in release


def test_actual_scope_orchestration_keeps_frozen_filters_in_both_hybrid_searches(monkeypatch):
    from pdos_next.enterprise_search import assistant_scope
    from pdos_next.enterprise_search.assistant_schemas import AssistantSearchInput
    from tests.agent_kernel.test_context_corrections import case, selection

    current_run, ctx, ref = case()
    condition = selection(
        ref,
        focus=None,
        sources=[ref],
        version_mode="fixed",
        versions=[ref],
    )
    state = {
        "context_selection": condition,
        "search_preferences": {"scope": "same_category", "include_customer_private": False},
    }
    current_run.versions = {"work_state": state, "work_state_digest": digest(state)}
    session = NS(get=lambda *_: current_run)
    scope = NS(run_id=current_run.id, project_id=uuid4(), proposal_id=None)
    denied = ("artifact", str(uuid4()))
    monkeypatch.setattr(assistant_scope, "excluded_sources", lambda *_: (denied,))
    monkeypatch.setattr("pdos_next.agent_kernel.context_corrections.recheck", lambda *_: condition)
    monkeypatch.setattr(assistant_scope, "_verified", lambda _session, value: value)
    monkeypatch.setattr(assistant_scope, "search", lambda *_a, **_kw: pytest.fail("Wrong searcher"))
    calls = []

    def hybrid(_session, _ctx, query, **filters):
        calls.append((query, filters))
        rows = [dict(ref, channel="semantic")] if len(calls) == 1 else []
        return {
            "items": rows,
            "returned": len(rows),
            "truncated": False,
            "related_truncated": False,
            "scope": {"category_id": str(current_run.category_id)},
            "coverage": {"status": "current", "notice": None, "indexed_as_of": None},
        }

    result = assistant_scope.retrieve(
        session,
        ctx,
        scope,
        AssistantSearchInput(query="合成查询"),
        searcher=hybrid,
    )
    assert result["scope_policy"]["fallback_performed"] is True and len(calls) == 2
    expected = {(ref["source_type"], ref["source_id"], ref["source_revision"], ref["content_hash"])}
    assert all(
        query.include_history
        and filters["include_sources"] == expected
        and denied in filters["exclude_sources"]
        for query, filters in calls
    )
    assert calls[1][1]["exclude_project"] == scope.project_id
    assert calls[1][1]["allow_customer_private"] is False
