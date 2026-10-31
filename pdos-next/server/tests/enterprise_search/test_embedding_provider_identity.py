"""Canonical provider/P26 regressions; fake KMS and query transport, no DB/network."""

import json
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.agent_kernel.policy import egress as native_egress
from pdos_next.clock import now
from pdos_next.enterprise_search.embedding_identity import canonical_provider
from pdos_next.enterprise_search.embedding_provider import HostEmbeddingSecrets
from pdos_next.errors import DomainError
from pdos_next.model_configuration.connections import add
from tests.enterprise_search.test_embedding_managed_connections import configured, profile, request
from tests.enterprise_search.test_embedding_query import configured as query_configured
from tests.enterprise_search.test_embedding_query import run as run_query


class AgreementSession:
    def __init__(self, provider, allowed):
        self.provider, self.allowed, self.seen = provider, allowed, []
        self.agreement = SimpleNamespace(
            id=uuid4(), revision=1, active=True,
            signed_on=now() - timedelta(days=1), expires_at=now() + timedelta(days=1),
            data_categories=allowed,
        )

    def scalar(self, query):
        provider = query.compile().params["provider_1"]
        self.seen.append(provider)
        return self.agreement if provider == self.provider else None


def test_registered_endpoint_alias_remains_the_same_provider_for_prices_and_p26(tmp_path):
    tenant, actor, host, kms = configured(tmp_path)
    data = request()
    document = host.configuration().model_dump(mode="json")
    document["models"] = [{
        "tenant_id": str(tenant), "protocol": "openai-compatible",
        "base_url": data.metadata.base_url, "model": "chat-model", "model_version": "chat@1",
        "provider": "registered-provider", "pricing": data.pricing.model_dump(mode="json"),
    }]
    host.path.write_text(json.dumps(document))
    saved = add(host, tenant, actor, data)
    assert saved["provider"] == "registered-provider"
    metadata = profile(saved)
    port = HostEmbeddingSecrets(host)
    provider = canonical_provider(port, tenant, metadata)
    assert provider == "registered-provider" and provider != metadata.provider
    card = port.pricing_for(tenant, metadata)
    card.validate(provider, SimpleNamespace(model=metadata.model, version=metadata.model_version))
    assert card.provider == "registered-provider"  # Never relabel the price card.
    agreement = AgreementSession(provider, ["public"])
    scope = SimpleNamespace(tenant_id=tenant, data_categories=["internal"])
    before = len(kms.value_reads)
    with pytest.raises(DomainError) as denied:
        native_egress(agreement, scope, provider, data_categories={"internal"})
    assert denied.value.detail["reason_key"] == "provider_agreement_category"
    assert agreement.seen == [provider] and len(kms.value_reads) == before


def test_provider_is_server_connection_bound_and_missing_identity_fails_closed():
    metadata, tenant = SimpleNamespace(provider="untrusted-fallback.invalid"), uuid4()
    for port in [None, SimpleNamespace(), SimpleNamespace(provider_for=lambda *_: ""),
                 SimpleNamespace(provider_for=lambda *_: "injected private provider")]:
        with pytest.raises(DomainError) as failure:
            canonical_provider(port, tenant, metadata)
        assert failure.value.code == "SOURCE_UNAVAILABLE"
        assert canonical_provider(port, tenant, metadata, required=False) is None
    seen = []
    port = SimpleNamespace(
        provider_for=lambda actual, route: seen.append((actual, route)) or "known"
    )
    assert canonical_provider(port, tenant, metadata) == "known"
    assert seen == [(tenant, metadata)]


def test_query_uses_canonical_agreement_and_denies_before_claim_or_embedding(monkeypatch):
    c = query_configured(monkeypatch)
    backend = c.ports.backend
    backend.secrets.provider_for = lambda *_: "registered-provider"
    card = replace(backend.pricing_for(c.f.scope.tenant_id, c.meta), provider="registered-provider")
    backend.pricing_for = lambda *_: card
    agreement = AgreementSession("registered-provider", ["public"])
    monkeypatch.setattr(
        "pdos_next.enterprise_search.embedding_query.policy.egress",
        lambda _session, scope, provider, **options: native_egress(
            agreement, scope, provider, **options
        ),
    )
    result = run_query(c)
    assert result.status == "query_egress_not_permitted" and result.vector is None
    assert agreement.seen == ["registered-provider"]
    assert not c.provider_calls and not any(kind == "claim" for kind, _ in c.store.calls)


def test_query_rechecks_provider_identity_before_the_actual_send(monkeypatch):
    c = query_configured(monkeypatch)
    seen = []

    def provider(*_):
        seen.append(True)
        return c.meta.provider if len(seen) == 1 else "changed-provider"

    c.ports.backend.secrets.provider_for = provider
    with pytest.raises(DomainError) as changed:
        run_query(c)
    assert changed.value.code == "VERSION_CONFLICT" and not c.provider_calls
    assert len(seen) == 2
