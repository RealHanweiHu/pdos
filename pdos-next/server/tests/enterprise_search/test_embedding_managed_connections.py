"""Pure host/KMS proof; no database, Keychain, cloud KMS or embedding provider."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pdos_next.enterprise_search.embedding_provider import HostEmbeddingSecrets
from pdos_next.enterprise_search.embedding_schemas import EmbeddingMetadata
from pdos_next.errors import DomainError
from pdos_next.model_configuration.connections import AddConnection, add, readings
from pdos_next.model_configuration.host import TenantRuntime
from pdos_next.schemas.model_configuration import ModelMetadata
from pydantic import SecretStr


class MemoryKms:
    def __init__(self, chat_arn):
        self.items = {chat_arn: ("chat-version-1", "synthetic-chat-key")}
        self.writes = 0
        self.value_reads = []

    def create(self, name, version, credential):
        arn = "acs:kms:cn-hangzhou:123:secret/" + name
        value = (version, credential.get_secret_value())
        if arn in self.items:
            assert self.items[arn] == value
        else:
            self.items[arn] = value
            self.writes += 1
        return arn

    def current_version(self, arn):
        return self.items.get(arn, (None, None))[0]

    def value(self, arn, version):
        self.value_reads.append((arn, version))
        assert self.items[arn][0] == version
        return SecretStr(self.items[arn][1])


def configured(tmp_path):
    tenant, actor = uuid4(), uuid4()
    arn = "acs:kms:cn-hangzhou:123:secret/synthetic-chat"
    document = {
        "format_version": 1,
        "kms": {"region": "cn-hangzhou", "endpoint": "kms.cn-hangzhou.aliyuncs.com"},
        "secrets": [{
            "tenant_id": str(tenant), "protocol": "openai-compatible",
            "reference": str(uuid4()), "secret_arn": arn,
        }],
        "models": [],
    }
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(document))
    kms = MemoryKms(arn)
    host = TenantRuntime(path, kms_factory=lambda *_: kms)
    return tenant, actor, host, kms


def request(key="synthetic-embedding-key", *, prices=True):
    checked = datetime.now(UTC)
    pricing = {
        "source": "synthetic-embedding-rate-card",
        "verified_at": (checked - timedelta(minutes=1)).isoformat(),
        "valid_until": (checked + timedelta(days=1)).isoformat(),
        "input_per_million": "0.25", "output_per_million": "0",
        "cache_read_per_million": "0", "cache_creation_per_million": "0",
        "request_fee": "0.0001", "currency": "USD",
        "text_tokens_per_utf8_byte": "1", "text_framing_tokens": 100,
        "text_billing_source": "synthetic-embedding-billing-upper-bound",
        "output_cap_covers_all_billing": True, "covers_all_fees": True,
    }
    return AddConnection.model_validate({
        "request_id": str(uuid4()), "name": "Independent embedding",
        "metadata": ModelMetadata(
            protocol="openai-compatible", base_url="https://embedding.invalid/v1",
            model="embed-model", model_version="embed@1",
        ).model_dump(),
        "api_key": key, "pricing": pricing if prices else None,
    })


def profile(saved):
    metadata = saved["metadata"]
    return EmbeddingMetadata(
        base_url=metadata["base_url"], model=metadata["model"],
        model_version=metadata["model_version"], dimensions=512,
        connection_id=UUID(saved["id"]), data_categories=["internal"],
    )


def test_existing_secure_registration_binds_embedding_without_changing_chat(tmp_path):
    tenant, actor, host, kms = configured(tmp_path)
    before = host.configuration()
    chat = host.current(tenant, "openai-compatible")
    saved = add(host, tenant, actor, request())
    assert host.current(tenant, "openai-compatible") == chat
    assert host.configuration().secrets == before.secrets
    assert host.configuration().models == before.models
    assert len(host.configuration().connections) == 1 and kms.writes == 1
    secrets = HostEmbeddingSecrets(host)
    binding = secrets.current_embedding(tenant, profile(saved))
    assert binding.reference == UUID(saved["id"]) and binding != chat
    assert secrets.resolve(binding).credential.get_secret_value() == "synthetic-embedding-key"
    assert host.resolve(chat).credential.get_secret_value() == "synthetic-chat-key"
    before_reads = list(kms.value_reads)
    public = readings(host, tenant)
    assert kms.value_reads == before_reads
    assert "synthetic-embedding-key" not in json.dumps(public) + host.path.read_text()
    assert "secret_arn" not in json.dumps(public) and "secret_reference" not in json.dumps(public)
    assert secrets.pricing_for(tenant, profile(saved)).input_per_million == Decimal("0.25")


def test_rotation_adds_new_immutable_connection_and_requires_explicit_profile_selection(tmp_path):
    tenant, actor, host, kms = configured(tmp_path)
    chat = host.current(tenant, "openai-compatible")
    first_data = request()
    first = add(host, tenant, actor, first_data)
    assert add(host, tenant, actor, first_data) == first and kms.writes == 1
    second = add(host, tenant, actor, request("synthetic-rotated-embedding-key"))
    port = HostEmbeddingSecrets(host)
    first_binding = port.current_embedding(tenant, profile(first))
    second_binding = port.current_embedding(tenant, profile(second))
    assert first_binding != second_binding and kms.writes == 2
    assert port.resolve(first_binding).credential.get_secret_value() == "synthetic-embedding-key"
    assert port.resolve(second_binding).credential.get_secret_value() == (
        "synthetic-rotated-embedding-key"
    )
    assert host.current(tenant, "openai-compatible") == chat
    assert port.current_embedding(tenant, profile(first)) == first_binding
    assert host.resolve(replace(first_binding, version=uuid4())) is None
    with pytest.raises(DomainError):
        port.current_embedding(uuid4(), profile(first))
    with pytest.raises(DomainError):
        port.current_embedding(tenant, profile(first).model_copy(update={"connection_id": uuid4()}))
    with pytest.raises(DomainError):
        port.current_embedding(tenant, profile(first).model_copy(update={
            "base_url": "https://other.invalid/v1",
        }))
    assert not readings(host, uuid4())["connections"]


def test_missing_embedding_metering_never_falls_back_to_chat_prices_or_key(tmp_path):
    tenant, actor, host, kms = configured(tmp_path)
    chat = host.current(tenant, "openai-compatible")
    data = request(prices=False)
    saved = add(host, tenant, actor, data)
    assert saved["pricing_configured"] is False
    port = HostEmbeddingSecrets(host)
    assert port.current_embedding(tenant, profile(saved)).reference == UUID(saved["id"])
    with pytest.raises(DomainError) as missing:
        port.pricing_for(tenant, profile(saved))
    assert missing.value.code == "SOURCE_UNAVAILABLE"
    assert host.current(tenant, "openai-compatible") == chat
    assert "synthetic-embedding-key" not in repr(data) + data.model_dump_json()
    assert kms.writes == 1
