"""Synthetic secure storage only; no real Keychain/KMS/model access."""

import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from pdos_next.errors import DomainError
from pdos_next.model_configuration.commands import SavePayload, semantic
from pdos_next.model_configuration.connections import AddConnection, add, readings
from pdos_next.model_configuration.host import TenantRuntime
from pdos_next.model_configuration.kms import AliyunKms
from pdos_next.model_configuration.local_kms import LOCAL_ENDPOINT, LOCAL_REGION, LocalKeychainKms
from pdos_next.schemas.model_configuration import ModelMetadata
from tests.model_configuration.test_host_runtime import KmsSdk, document, write_config

KEY = "synthetic-provider-key-private"


class MemoryKms:
    def __init__(self):
        self.items, self.writes = {}, 0

    def create(self, name, version, credential):
        arn = "acs:kms:cn-hangzhou:123456789012:secret/" + name
        item = (version, credential.get_secret_value())
        if arn in self.items:
            assert self.items[arn] == item
        else:
            self.items[arn] = item
            self.writes += 1
        return arn

    def current_version(self, arn):
        return self.items[arn][0] if arn in self.items else "legacy-v1"

    def value(self, arn, version):
        assert self.items[arn][0] == version
        return SecretStr(self.items[arn][1])


def configured_host(tmp_path, tenant):
    kms = MemoryKms()
    host = TenantRuntime(write_config(tmp_path / "runtime.json", document(tenant)),
        kms_factory=lambda *_: kms)
    return host, kms


def request(**updates):
    return AddConnection(request_id=uuid4(), name="Custom provider",
        metadata=ModelMetadata(protocol="openai-compatible", base_url="https://custom.invalid/v1",
            model="custom-model", model_version="custom@1", openai_response_mode="tools"),
        api_key=SecretStr(KEY), **updates)


def test_save_masks_credential_and_replay_does_not_repeat_secret_write(tmp_path):
    tenant, actor = uuid4(), uuid4()
    host, kms = configured_host(tmp_path, tenant)
    data = request()
    saved = add(host, tenant, actor, data)
    assert KEY not in repr(data) + data.model_dump_json() + host.path.read_text()
    assert KEY not in json.dumps(saved) + json.dumps(readings(host, tenant))
    assert "secret_arn" not in json.dumps(saved) and "request_digest" not in saved
    assert saved["credential_display"] == "已保存 ••••"
    legacy = {**data.model_dump(mode="json"), "tenant": str(tenant), "actor": str(actor),
              "key": KEY}
    legacy["metadata"].pop("context_window_tokens")
    assert host.configuration().connections[0].request_digest == hashlib.sha256(
        json.dumps(legacy, sort_keys=True).encode()).hexdigest()
    assert add(host, tenant, actor, data) == saved and kms.writes == 1
    with pytest.raises(DomainError) as conflict:
        add(host, tenant, actor, data.model_copy(update={"api_key": SecretStr("changed-private")}))
    assert conflict.value.code == "DUPLICATE_INTENT_CONFLICT" and kms.writes == 1


def test_same_protocol_and_endpoint_connections_resolve_only_their_own_keys(tmp_path):
    tenant, actor = uuid4(), uuid4()
    host, kms = configured_host(tmp_path, tenant)
    first = add(host, tenant, actor, request())
    second_request = request().model_copy(update={"api_key": SecretStr("key-two")})
    second = add(host, tenant, actor, second_request)
    for public, expected in [(first, KEY), (second, "key-two")]:
        metadata = ModelMetadata.model_validate_json(json.dumps(public["metadata"]))
        binding = host.current_for(tenant, metadata)
        assert host.resolve(binding).credential.get_secret_value() == expected
        route = metadata.route(SecretStr(expected), metadata.model_version)
        scope = type("Scope", (), {"tenant_id": tenant})()
        assert host.provider_for(scope, route) == "custom.invalid"
        with pytest.raises(DomainError):
            host.current_for(uuid4(), metadata)
        with pytest.raises(DomainError):
            host.current_for(tenant, metadata.model_copy(update={"base_url": "https://other.invalid"}))
        assert host.resolve(replace(binding, version=uuid4())) is None
    assert first["id"] != second["id"] and kms.writes == 2
    assert len(readings(host, uuid4())["connections"]) == 0


def test_known_endpoint_keeps_server_provider_identity_and_exact_model_price(tmp_path):
    tenant, actor = uuid4(), uuid4()
    host, _ = configured_host(tmp_path, tenant)
    known = host.configuration().models[0]
    before = host.current(tenant, known.protocol)
    metadata = ModelMetadata(protocol=known.protocol, base_url=known.base_url,
        model=known.model, model_version=known.model_version)
    saved = add(host, tenant, actor, request().model_copy(update={"metadata": metadata}))
    assert saved["provider"] == known.provider and saved["pricing_configured"]
    assert host.current(tenant, known.protocol) == before


def test_prior_confirmed_requests_without_connection_id_keep_their_semantic_hash():
    metadata = request().metadata.model_dump(mode="json", exclude={"connection_id", "context_window_tokens"})
    original = {"expected_revision": 1, "metadata": metadata, "enabled": True}
    assert semantic(SavePayload.model_validate(original)) == original
    for connection_id in (None, str(uuid4())):
        current = {**original, "metadata": {**metadata, "connection_id": connection_id}}
        assert semantic(SavePayload.model_validate(current)) == current
    configured = {**original, "metadata": {**metadata, "context_window_tokens": 200000}}
    assert semantic(SavePayload.model_validate(configured)) == configured
    unset = {**original, "metadata": {**metadata, "context_window_tokens": None}}
    assert semantic(SavePayload.model_validate(unset)) == original


def test_file_failure_retries_same_immutable_secret_without_changing_existing_bindings(
    tmp_path, monkeypatch
):
    tenant, actor = uuid4(), uuid4()
    host, kms = configured_host(tmp_path, tenant)
    before = host.path.read_bytes()
    data = request()
    import pdos_next.model_configuration.connections as connections
    original = connections.os.replace

    def unavailable(*_):
        raise OSError("synthetic interrupted replacement")

    monkeypatch.setattr(connections.os, "replace", unavailable)
    with pytest.raises(DomainError):
        add(host, tenant, actor, data)
    assert host.path.read_bytes() == before
    assert kms.writes == 1 and list(tmp_path.glob(".model-connections-*")) == []
    monkeypatch.setattr(connections.os, "replace", original)
    assert add(host, tenant, actor, data)["name"] == data.name
    assert kms.writes == 1


@pytest.mark.parametrize("key", ["", "private\ninvalid", "private\x00invalid", "x" * 8193])
def test_invalid_keys_are_rejected_without_echo(key):
    with pytest.raises(ValidationError) as failed:
        AddConnection.model_validate({
            "request_id": uuid4(), "name": "provider", "api_key": key,
            "metadata": request().metadata.model_dump()})
    assert key not in str(failed.value) if key else True


def test_price_card_json_is_accepted_and_missing_prices_remain_explicit(tmp_path):
    tenant, actor = uuid4(), uuid4()
    host, _ = configured_host(tmp_path, tenant)
    prices = document(tenant)["models"][0]["pricing"]
    data = AddConnection.model_validate({**request().model_dump(mode="json"),
        "api_key": KEY, "pricing": prices})
    public = add(host, tenant, actor, data)
    metadata = ModelMetadata.model_validate_json(json.dumps(public["metadata"]))
    route = metadata.route(SecretStr(KEY), metadata.model_version)
    scope = type("Scope", (), {"tenant_id": tenant})()
    assert host.rate_card_for(scope, route).provider == "custom.invalid"
    assert host.output_limit_for(scope, replace(route, max_output_tokens=4096)) == 4096
    missing = add(host, tenant, actor, request())
    no_prices = ModelMetadata.model_validate_json(json.dumps(missing["metadata"]))
    with pytest.raises(DomainError):
        host.rate_card_for(scope, no_prices.route(SecretStr(KEY), no_prices.model_version))


@pytest.mark.parametrize("unknown_creation", [False, True])
def test_kms_sdk_creation_and_unknown_outcome_reconcile_without_another_write(unknown_creation):
    class WriterSdk(KmsSdk):
        def __init__(self):
            super().__init__()
            self.writes = 0
            self.get_hook = lambda result: setattr(result, "secret_data", KEY)

        def create_secret_with_options(self, request, options):
            assert options.autoretry is False
            assert request.secret_type == "Generic" and request.secret_data_type == "text"
            assert request.secret_data == KEY
            self.version = request.version_id
            self.writes += 1
            self.arn = "acs:kms:cn-hangzhou:123456789012:secret/" + request.secret_name
            if unknown_creation:
                raise TimeoutError("synthetic lost creation response")
            return SimpleNamespace(body=SimpleNamespace(arn=self.arn))

        def describe_secret_with_options(self, request, options):
            assert options.autoretry is False and self.arn.endswith("/" + request.secret_name)
            return SimpleNamespace(body=SimpleNamespace(arn=self.arn))

    sdk = WriterSdk()
    kms = AliyunKms("cn-hangzhou", "kms.cn-hangzhou.aliyuncs.com", client=sdk)
    arn = kms.create("synthetic-ui-secret", "synthetic-v1", SecretStr(KEY))
    assert arn.endswith("/synthetic-ui-secret") and sdk.writes == 1


def test_local_creation_replay_never_overwrites_a_key_with_changed_request():
    items = {}
    kms = LocalKeychainKms(LOCAL_REGION, LOCAL_ENDPOINT, client=items.get,
        writer=lambda name, value: items.setdefault(name, value))
    arn = kms.create("synthetic-ui-secret", "v1", SecretStr(KEY))
    assert kms.create("synthetic-ui-secret", "v1", SecretStr(KEY)) == arn
    with pytest.raises(DomainError) as failed:
        kms.create("synthetic-ui-secret", "v1", SecretStr("different-private-key"))
    assert KEY not in str(failed.value)
    assert kms.value(arn, "v1").get_secret_value() == KEY


def test_context_window_survives_managed_connection_storage(tmp_path):
    tenant, actor = uuid4(), uuid4()
    host, _ = configured_host(tmp_path, tenant)
    data = request()
    data = data.model_copy(update={"metadata": data.metadata.model_copy(update={
        "context_window_tokens": 200000,
    })})
    saved = add(host, tenant, actor, data)
    assert saved["metadata"]["context_window_tokens"] == 200000
    metadata = ModelMetadata.model_validate(saved["metadata"])
    assert metadata.route(SecretStr(KEY), metadata.model_version).context_window_tokens == 200000
    stored = host.configuration().connections[0]
    assert stored.metadata.context_window_tokens == 200000
