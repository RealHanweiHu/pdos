"""Default research composition with explicit server metadata, no network or database."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.agent_kernel.bootstrap import Bootstrap, RuntimePorts
from pdos_next.errors import DomainError
from pdos_next.model_configuration.host import TenantRuntime
from pdos_next.research.runtime import checkpoints
from tests.model_configuration.test_host_runtime import document, write_config


def configuration(tmp_path):
    value = document(uuid4())
    value["research"] = {
        "search_endpoint": "http://127.0.0.1:18888/search",
        "search_provider": "synthetic-search",
        "artifact_root": str(tmp_path / "research"),
    }
    return value


def test_default_bootstrap_composes_research_domain_storage_and_durable_children(
    tmp_path, monkeypatch
):
    path = write_config(tmp_path / "host.json", configuration(tmp_path))
    monkeypatch.setenv("PDOS_TENANT_RUNTIME_CONFIG", str(path))
    owner = Bootstrap(SimpleNamespace())
    adapters = owner.adapters()
    assert {"research.search", "research.read", "research.fanout"} <= adapters.read_tools.keys()
    assert owner.ports.research_service.search_adapter.provider == "synthetic-search"
    assert owner.commands.artifacts is owner.ports.research_artifacts
    assert owner.ports.research_service.snapshot_sink.__self__ is owner.commands.artifacts
    assert owner.ports.research_checkpointer_factory is checkpoints
    explicit = RuntimePorts()
    assert Bootstrap(SimpleNamespace(), ports=explicit).ports is explicit


@pytest.mark.parametrize(
    "field,value",
    [
        ("search_endpoint", "https://user:synthetic-key@search.invalid/search"),
        ("search_endpoint", "https://search.invalid/search?api_key=synthetic-key"),
        ("artifact_root", "relative/research"),
    ],
)
def test_research_metadata_does_not_accept_credentials_or_ambiguous_storage(tmp_path, field, value):
    config = configuration(tmp_path)
    config["research"][field] = value
    host = TenantRuntime(write_config(tmp_path / "host.json", config))
    with pytest.raises(DomainError) as error:
        host.configuration()
    assert error.value.code == "SOURCE_UNAVAILABLE"
    assert "synthetic-key" not in str(error.value)


def test_invalid_metadata_keeps_independent_business_bootstrap_available(tmp_path, monkeypatch):
    path = tmp_path / "host.json"
    path.write_text(json.dumps({"malformed": True}))
    monkeypatch.setenv("PDOS_TENANT_RUNTIME_CONFIG", str(path))
    owner = Bootstrap(SimpleNamespace())
    assert owner.ports.research_service is None
    with pytest.raises(DomainError):
        owner.ports.secrets.current(uuid4(), "openai-compatible")


def test_research_never_silently_falls_back_to_volatile_child_checkpoints(monkeypatch):
    monkeypatch.delenv("PDOS_CHECKPOINT_DATABASE_URL", raising=False)
    with pytest.raises(DomainError) as error:
        checkpoints()
    assert error.value.code == "SOURCE_UNAVAILABLE"


def test_missing_research_volume_only_disables_dependent_ports(tmp_path, monkeypatch):
    value = configuration(tmp_path)
    blocked = tmp_path / "file-not-directory"
    blocked.write_text("synthetic")
    value["research"]["artifact_root"] = str(blocked / "research")
    path = write_config(tmp_path / "host.json", value)
    monkeypatch.setenv("PDOS_TENANT_RUNTIME_CONFIG", str(path))
    owner = Bootstrap(SimpleNamespace())
    assert owner.ports.secrets is not None and owner.ports.research_service is None
