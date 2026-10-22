"""Tenant-scoped KMS references and default MCP port composition, with synthetic KMS."""

import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import SecretStr

from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.mcp_runtime import McpConfiguration
from pdos_next.errors import DomainError
from pdos_next.model_configuration.host import HostConfiguration, TenantRuntime, runtime_ports
from tests.model_configuration.test_host_runtime import document, write_config


def configuration(tmp_path, tenant):
    value = document(tenant)
    value["mcp"] = {
        "artifact_root": str(tmp_path / "mcp-private"),
        "secrets": [
            {
                "tenant_id": str(tenant),
                "reference": "synthetic-mcp-reference",
                "secret_arn": "acs:kms:cn-hangzhou:123456789012:secret/synthetic-mcp",
            }
        ],
    }
    return value


def test_server_metadata_selects_exact_tenant_and_reference_without_exposing_key(tmp_path):
    tenant, calls = uuid4(), []

    class Kms:
        def current_version(self, arn):
            calls.append(("metadata", arn))
            return "synthetic-current"

        def value(self, arn, version):
            calls.append(("value", arn, version))
            return SecretStr("synthetic-key-not-for-context")

    value = configuration(tmp_path, tenant)
    host = TenantRuntime(
        write_config(tmp_path / "runtime.json", value), kms_factory=lambda *_: Kms()
    )
    assert host.mcp_secret(uuid4(), "synthetic-mcp-reference") is None
    assert host.mcp_secret(tenant, "wrong-reference") is None and not calls
    material = host.mcp_secret(tenant, "synthetic-mcp-reference")
    assert material.get_secret_value() == "synthetic-key-not-for-context"
    assert "synthetic-key-not-for-context" not in repr(material) + str(value)
    assert len(calls) == 2


def test_default_ports_register_discovery_and_read_even_when_actual_runtime_missing(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("PDOS_TENANT_RUNTIME_CONFIG", raising=False)
    bootstrap = Bootstrap(SimpleNamespace())
    adapters = bootstrap.adapters()
    assert {"mcp.tools.list", "mcp.read"} <= set(adapters.read_resumes)
    assert "mcp.read" in adapters.read_restores
    assert runtime_ports().mcp_transport is None
    tenant = uuid4()
    path = write_config(tmp_path / "runtime.json", configuration(tmp_path, tenant))
    monkeypatch.setenv("PDOS_TENANT_RUNTIME_CONFIG", str(path))
    ports = runtime_ports(object())
    assert ports.mcp_transport and ports.mcp_artifacts and ports.mcp_checkpointer_factory
    assert ports.mcp_artifacts.root == tmp_path / "mcp-private"


@pytest.mark.parametrize("change", ["inline-secret", "duplicate", "region", "relative-path"])
def test_runtime_rejects_secret_values_ambiguous_bindings_and_invalid_locations(tmp_path, change):
    value = configuration(tmp_path, uuid4())
    if change == "inline-secret":
        value["mcp"]["secrets"][0]["credential"] = "never-save-key"
    elif change == "duplicate":
        value["mcp"]["secrets"].append(deepcopy(value["mcp"]["secrets"][0]))
    elif change == "region":
        value["mcp"]["secrets"][0]["secret_arn"] = value["mcp"]["secrets"][0]["secret_arn"].replace(
            "cn-hangzhou", "cn-shanghai"
        )
    else:
        value["mcp"]["artifact_root"] = "relative"
    with pytest.raises(ValueError):
        HostConfiguration.model_validate_json(json.dumps(value))


def test_legacy_metadata_stays_compatible_and_invalid_metadata_fails_visibly(tmp_path, monkeypatch):
    tenant = uuid4()
    assert HostConfiguration.model_validate_json(json.dumps(document(tenant))).mcp is None
    with pytest.raises(ValueError):
        McpConfiguration(artifact_root="relative")
    path = write_config(tmp_path / "runtime.json", {"not": "runtime"})
    monkeypatch.setenv("PDOS_TENANT_RUNTIME_CONFIG", str(path))
    ports = runtime_ports(object())
    assert ports.mcp_transport is None and ports.research_service is None
    with pytest.raises(DomainError):
        TenantRuntime(path).configuration()
