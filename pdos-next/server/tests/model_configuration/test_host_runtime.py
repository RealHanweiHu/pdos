"""Real SDK DTOs and tenant host adapters; every KMS response is synthetic."""

import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alibabacloud_kms20160120 import models
from pydantic import SecretStr

from pdos_next.agent_kernel.bootstrap import Bootstrap, RuntimePorts
from pdos_next.errors import DomainError
from pdos_next.model_configuration.host import TenantRuntime, runtime_ports
from pdos_next.model_configuration.kms import AliyunKms
from pdos_next.models import now
from pdos_next.schemas.model_configuration import ModelMetadata
from tests.agent_kernel.test_cost_budget import rate


class KmsSdk:
    def __init__(self):
        self.version, self.calls = "synthetic-version-1", []
        self.get_hook = None

    def list_secret_version_ids_with_options(self, request, options):
        self.calls.append(("metadata", request.to_map()))
        assert options.autoretry is False and options.read_timeout == 5000
        return SimpleNamespace(
            body=models.ListSecretVersionIdsResponseBody().from_map(
                {
                    "SecretName": request.secret_name,
                    "PageNumber": request.page_number,
                    "PageSize": 100,
                    "TotalCount": 1,
                    "VersionIds": {
                        "VersionId": [
                            {
                                "VersionId": self.version,
                                "VersionStages": {"VersionStage": ["ACSCurrent"]},
                            }
                        ]
                    },
                }
            )
        )

    def get_secret_value_with_options(self, request, options):
        self.calls.append(("value", request.to_map()))
        assert request.version_stage == "ACSCurrent" and request.version_id == self.version
        body = models.GetSecretValueResponseBody().from_map(
            {
                "SecretName": request.secret_name,
                "VersionId": self.version,
                "SecretType": "Generic",
                "SecretDataType": "text",
                "SecretData": "synthetic-only-key",
                "VersionStages": {"VersionStage": ["ACSCurrent"]},
            }
        )
        if self.get_hook:
            self.get_hook(body)
        return SimpleNamespace(body=body)


def document(tenant, *, protocol="openai-compatible"):
    card = rate().snapshot()
    for field in ["digest", "provider", "model", "configuration_version"]:
        card.pop(field)
    metadata = ModelMetadata(
        protocol=protocol,
        base_url="https://synthetic.invalid/v1",
        model="synthetic-model",
        model_version="synthetic@1",
    ).model_dump(mode="json")
    return {
        "format_version": 1,
        "kms": {"region": "cn-hangzhou", "endpoint": "kms-vpc.cn-hangzhou.aliyuncs.com"},
        "secrets": [
            {
                "tenant_id": str(tenant),
                "protocol": protocol,
                "reference": str(uuid4()),
                "secret_arn": "acs:kms:cn-hangzhou:123456789012:secret/synthetic-model",
            }
        ],
        "models": [
            {
                "tenant_id": str(tenant),
                **{k: metadata[k] for k in ["protocol", "base_url", "model", "model_version"]},
                "provider": "synthetic@1",
                "pricing": card,
            }
        ],
    }


def write_config(path, value):
    path.write_text(json.dumps(value))
    return path


@pytest.mark.parametrize("protocol", ["openai-compatible", "anthropic-native"])
def test_tenant_protocol_metadata_isolated_and_secret_material_resolves_exact_current_version(
    tmp_path, protocol
):
    tenant, sdk = uuid4(), KmsSdk()
    path = write_config(tmp_path / "runtime.json", document(tenant, protocol=protocol))
    host = TenantRuntime(
        path, kms_factory=lambda region, endpoint: AliyunKms(region, endpoint, client=sdk)
    )
    assert host.current(uuid4(), protocol) is None and sdk.calls == []
    binding = host.current(tenant, protocol)
    assert binding.tenant_id == tenant and [kind for kind, _ in sdk.calls] == ["metadata"]
    material = host.resolve(binding)
    assert material.binding == binding
    assert material.credential.get_secret_value() == "synthetic-only-key"
    assert "synthetic-only-key" not in repr(material)
    sdk.version = "synthetic-version-2"
    assert host.current(tenant, protocol).version != binding.version
    before = len([kind for kind, _ in sdk.calls if kind == "value"])
    assert host.resolve(binding) is None
    assert len([kind for kind, _ in sdk.calls if kind == "value"]) == before


def test_kms_value_scope_version_and_generic_text_are_checked_with_no_sdk_error_exposure():
    sdk = KmsSdk()
    port = AliyunKms("cn-hangzhou", "kms.cn-hangzhou.aliyuncs.com", client=sdk)
    arn = "acs:kms:cn-hangzhou:123:secret/synthetic-model"
    for field, value in [
        ("version_id", "old"),
        ("secret_name", "other"),
        ("secret_type", "Rds"),
        ("secret_data_type", "binary"),
    ]:
        sdk.get_hook = lambda body, field=field, value=value: setattr(body, field, value)
        with pytest.raises(DomainError) as failed:
            port.value(arn, sdk.version)
        assert failed.value.code == "SOURCE_UNAVAILABLE"
        assert "synthetic-only-key" not in str(failed.value)


def test_retargeting_same_reference_changes_binding_and_runtime_reload_keeps_current_metadata(
    tmp_path,
):
    tenant, sdk = uuid4(), KmsSdk()
    value = document(tenant)
    path = write_config(tmp_path / "runtime.json", value)
    host = TenantRuntime(path, kms_factory=lambda *_: AliyunKms("r", "e", client=sdk))
    first = host.current(tenant, "openai-compatible")
    value["secrets"][0]["secret_arn"] += "-rotated-target"
    write_config(path, value)
    assert host.current(tenant, "openai-compatible").version != first.version
    assert host.resolve(first) is None


@pytest.mark.parametrize("change", ["credential", "duplicate", "region", "endpoint"])
def test_runtime_manifest_rejects_credential_values_and_ambiguous_or_mismatched_bindings(
    tmp_path, change
):
    value = document(uuid4())
    if change == "credential":
        value["secrets"][0]["credential"] = "synthetic-should-never-be-config"
    elif change == "duplicate":
        value["models"].append(deepcopy(value["models"][0]))
    elif change == "region":
        value["secrets"][0]["secret_arn"] = value["secrets"][0]["secret_arn"].replace(
            "cn-hangzhou", "cn-shanghai"
        )
    else:
        value["kms"]["endpoint"] = "synthetic.invalid"
    host = TenantRuntime(write_config(tmp_path / "runtime.json", value))
    with pytest.raises(DomainError) as failed:
        host.configuration()
    assert "synthetic-should-never-be-config" not in str(failed.value)


def test_provider_and_decimal_rate_card_require_exact_tenant_model_and_current_billing(tmp_path):
    tenant = uuid4()
    value = document(tenant)
    path = write_config(tmp_path / "runtime.json", value)
    host = TenantRuntime(path)
    scope = SimpleNamespace(tenant_id=tenant)
    route = ModelMetadata(
        protocol="openai-compatible",
        base_url="https://synthetic.invalid/v1",
        model="synthetic-model",
        model_version="synthetic@1",
    ).route(SecretStr("synthetic-only-key"), "synthetic@1")
    assert host.provider_for(scope, route) == "synthetic@1"
    card = host.rate_card_for(scope, route)
    assert (
        card.actual(
            SimpleNamespace(
                input_tokens=20, output_tokens=10, cache_read_tokens=0, cache_creation_tokens=0
            )
        )
        == 120
    )
    for other_scope, other_route in [
        (SimpleNamespace(tenant_id=uuid4()), route),
        (scope, replace(route, model="other")),
    ]:
        with pytest.raises(DomainError):
            host.provider_for(other_scope, other_route)
    value["models"][0]["pricing"]["valid_until"] = (now() - timedelta(seconds=1)).isoformat()
    write_config(path, value)
    with pytest.raises(DomainError):
        host.rate_card_for(scope, route)


def test_default_bootstrap_loads_one_host_for_all_three_ports_and_explicit_injection_still_wins(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("PDOS_TENANT_RUNTIME_CONFIG", raising=False)
    assert runtime_ports().secrets is None
    path = write_config(tmp_path / "runtime.json", document(uuid4()))
    monkeypatch.setenv("PDOS_TENANT_RUNTIME_CONFIG", str(path))
    owner = Bootstrap(SimpleNamespace())
    assert isinstance(owner.ports.secrets, TenantRuntime)
    assert owner.ports.provider_for.__self__ is owner.ports.secrets
    assert owner.ports.rate_card_for.__self__ is owner.ports.secrets
    explicit = RuntimePorts()
    assert Bootstrap(SimpleNamespace(), ports=explicit).ports is explicit


def test_relative_metadata_path_cannot_select_different_api_and_worker_files(tmp_path, monkeypatch):
    write_config(tmp_path / "runtime.json", document(uuid4()))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(DomainError) as error:
        TenantRuntime("runtime.json").configuration()
    assert error.value.code == "SOURCE_UNAVAILABLE"


@pytest.mark.parametrize("ambiguous", [False, True])
def test_kms_metadata_pagination_finds_one_current_version_or_rejects_ambiguity(ambiguous):
    class Pages:
        def __init__(self):
            self.pages = []

        def list_secret_version_ids_with_options(self, request, _options):
            self.pages.append(request.page_number)
            ids = range(100) if request.page_number == 1 else [100]
            rows = [
                {
                    "VersionId": f"synthetic-{index}",
                    "VersionStages": {
                        "VersionStage": [
                            "ACSCurrent"
                            if index == 100 or ambiguous and index == 0
                            else "ACSPrevious"
                        ]
                    },
                }
                for index in ids
            ]
            return SimpleNamespace(
                body=models.ListSecretVersionIdsResponseBody().from_map(
                    {
                        "SecretName": request.secret_name,
                        "PageNumber": request.page_number,
                        "PageSize": 100,
                        "TotalCount": 101,
                        "VersionIds": {"VersionId": rows},
                    }
                )
            )

    sdk = Pages()
    port = AliyunKms("cn-hangzhou", "kms.cn-hangzhou.aliyuncs.com", client=sdk)
    arn = "acs:kms:cn-hangzhou:123:secret/synthetic-model"
    if ambiguous:
        with pytest.raises(DomainError) as error:
            port.current_version(arn)
        assert error.value.code == "SOURCE_UNAVAILABLE"
    else:
        assert port.current_version(arn) == "synthetic-100"
    assert sdk.pages == [1, 2]
