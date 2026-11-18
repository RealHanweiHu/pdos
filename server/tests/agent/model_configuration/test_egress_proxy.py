"""D614: server-owned outbound proxy per exact provider host; synthetic HTTP only."""

import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from pdos_next.agent.kernel.bootstrap import Bootstrap
from pdos_next.agent.kernel.gateway import AgentGateway
from pdos_next.agent.model_configuration.host import (
    EgressProxy,
    HostConfiguration,
    TenantRuntime,
)
from pdos_next.errors import DomainError
from pdos_next.providers.agent_client import AgentProviderClient
from tests.agent.kernel.test_native_protocols import SCHEMA, TOOLS, reply, route
from tests.agent.model_configuration.test_host_runtime import document, write_config


def configured(tmp_path, egress):
    return TenantRuntime(write_config(tmp_path / "runtime.json", {
        **document(uuid4()), "egress": egress}))


@pytest.mark.parametrize("proxy", [
    "http://127.0.0.1:7897", "https://egress.internal:3128", "http://10.0.0.8:3128/",
])
def test_plain_proxy_urls_are_accepted(proxy):
    assert EgressProxy(host="api.openai.com", proxy=proxy).proxy == proxy


@pytest.mark.parametrize("value", [
    {"host": "api.openai.com", "proxy": "http://user:secret@127.0.0.1:7897"},
    {"host": "api.openai.com", "proxy": "socks5://127.0.0.1:7897"},
    {"host": "api.openai.com", "proxy": "http://127.0.0.1:7897/path"},
    {"host": "api.openai.com", "proxy": "http://127.0.0.1:7897?x=1"},
    {"host": "api.openai.com", "proxy": "http://127.0.0.1:notaport"},
    {"host": "API.openai.com", "proxy": "http://127.0.0.1:7897"},
    {"host": "*.openai.com", "proxy": "http://127.0.0.1:7897"},
    {"host": "https://api.openai.com", "proxy": "http://127.0.0.1:7897"},
])
def test_proxy_credentials_wildcards_and_non_http_schemes_are_rejected(value):
    with pytest.raises(ValidationError):
        EgressProxy.model_validate(value)


def test_duplicate_hosts_are_rejected_and_old_files_without_egress_still_load():
    base = document(uuid4())
    # The server reads the file as JSON text, as TenantRuntime.configuration does.
    assert HostConfiguration.model_validate_json(json.dumps(base)).egress == []
    with pytest.raises(ValidationError):
        HostConfiguration.model_validate_json(json.dumps({**base, "egress": [
            {"host": "api.openai.com", "proxy": "http://127.0.0.1:1"},
            {"host": "api.openai.com", "proxy": "http://127.0.0.1:2"},
        ]}))


def test_lookup_is_exact_hostname_and_read_per_call(tmp_path):
    host = configured(tmp_path, [{"host": "api.openai.com", "proxy": "http://127.0.0.1:7897"}])
    assert host.egress_for("https://api.openai.com/v1/chat/completions") == "http://127.0.0.1:7897"
    for other in ("https://api.openai.com.evil.invalid/v1/chat/completions",
                  "https://evil.invalid/api.openai.com/chat/completions",
                  "https://api.minimaxi.com/v1/chat/completions"):
        assert host.egress_for(other) is None
    # The file is re-read: removing the entry takes effect without a restart.
    write_config(host.path, document(uuid4()))
    assert host.egress_for("https://api.openai.com/v1/chat/completions") is None
    write_config(host.path, {"format_version": 1})
    with pytest.raises(DomainError):
        host.egress_for("https://api.openai.com/v1/chat/completions")


def test_default_bootstrap_carries_host_egress_lookup(tmp_path, monkeypatch):
    path = write_config(tmp_path / "runtime.json", document(uuid4()))
    monkeypatch.setenv("PDOS_TENANT_RUNTIME_CONFIG", str(path))
    owner = Bootstrap(SimpleNamespace())
    assert owner.ports.egress_for.__self__ is owner.ports.secrets


class Recorder:
    def __init__(self):
        self.direct, self.proxied, self.closed = [], [], []

    def transport(self, sink):
        return httpx.MockTransport(lambda request: (
            sink.append(str(request.url)),
            httpx.Response(200, json=reply("openai-compatible")),
        )[1])

    def proxy_transport(self, proxy):
        sink = []
        self.proxied.append((proxy, sink))
        return self.transport(sink)


def test_configured_host_uses_proxy_transport_and_others_stay_direct():
    recorder = Recorder()
    proxies = {"api.openai.com": "http://127.0.0.1:7897"}
    client = AgentProviderClient(
        transport=recorder.transport(recorder.direct),
        egress_for=lambda target: proxies.get(httpx.URL(target).host),
        proxy_transport=recorder.proxy_transport,
    )
    openai = replace(route("openai-compatible"), base_url="https://api.openai.com/v1")
    other = route("openai-compatible")
    for _ in range(2):
        client.turn(openai, system="frozen", messages=[{"role": "user", "content": "task"}],
                    tools=TOOLS, output_schema=SCHEMA)
    client.turn(other, system="frozen", messages=[{"role": "user", "content": "task"}],
                tools=TOOLS, output_schema=SCHEMA)
    # One client per proxy, reused; the direct transport never saw the OpenAI call.
    assert [proxy for proxy, _ in recorder.proxied] == ["http://127.0.0.1:7897"]
    assert recorder.proxied[0][1] == ["https://api.openai.com/v1/chat/completions"] * 2
    assert recorder.direct == [other.target_url]
    client.close()
    assert client._proxied == {}


def test_no_lookup_keeps_the_original_direct_client_and_ignores_environment(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    client = AgentProviderClient()
    selected = replace(route("openai-compatible"), base_url="https://api.openai.com/v1")
    assert client._client_for(selected.target_url) is client.client
    assert client.client._trust_env is False
    client.close()


def test_lookup_failure_stops_before_any_request():
    seen = []
    client = AgentProviderClient(
        transport=httpx.MockTransport(lambda request: seen.append(request) or httpx.Response(500)),
        egress_for=lambda target: (_ for _ in ()).throw(
            DomainError("SOURCE_UNAVAILABLE", "租户模型宿主配置暂不可用。")),
    )
    with pytest.raises(DomainError):
        client.turn(route("openai-compatible"), system="frozen",
                    messages=[{"role": "user", "content": "task"}], tools=TOOLS,
                    output_schema=SCHEMA)
    assert seen == []


def test_gateway_records_proxy_host_without_credentials_and_nothing_when_direct():
    lookup = {"https://api.openai.com/v1/chat/completions": "http://127.0.0.1:7897"}
    gateway = AgentGateway(SimpleNamespace(), route_for=None, egress_for=lookup.get)
    assert gateway._egress_via("https://api.openai.com/v1/chat/completions") == {
        "egress_via": "127.0.0.1:7897"}
    assert gateway._egress_via("https://api.minimaxi.com/v1/chat/completions") == {}
    assert AgentGateway(SimpleNamespace(), route_for=None)._egress_via("https://x.invalid") == {}
    assert json.dumps(gateway._egress_via("https://api.openai.com/v1/chat/completions"))
    gateway.close()
