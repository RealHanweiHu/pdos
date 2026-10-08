import httpx2
import pytest

from app.ai.public_dns import resolve_public
from app.ai.reach import ReachDeniedError, ReachPolicy, _default_resolver


def install(monkeypatch, handler):
    original = httpx2.Client

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(transport=httpx2.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx2, "Client", client)


def response(request, address="93.184.216.34"):
    kind = int(request.url.params["type"])
    return httpx2.Response(
        200,
        json={
            "Status": 0,
            "Question": [{"name": request.url.params["name"], "type": kind}],
            "Answer": [{"type": 1, "data": address}] if kind == 1 else [],
        },
    )


def test_explicit_resolver_returns_public_pinnable_addresses(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        assert str(request.url).startswith("https://1.1.1.1/dns-query?")
        return response(request)

    install(monkeypatch, handler)
    monkeypatch.setenv("PDOS_RESEARCH_DNS_MODE", "cloudflare_doh")
    assert _default_resolver("example.com") == ("93.184.216.34",)
    assert len(seen) == 2
    assert ReachPolicy().assert_url_allowed("https://example.com/public")


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "198.18.0.9", "::1"]
)
def test_private_or_fake_answers_never_fall_back(monkeypatch, address):
    install(monkeypatch, lambda r: response(r, address))
    with pytest.raises(ReachDeniedError, match="非公开"):
        resolve_public("example.com")


@pytest.mark.parametrize(
    "host", ["localhost", "metadata.google.internal", "private.local", "127.0.0.1"]
)
def test_internal_targets_do_not_reach_dns(monkeypatch, host):
    install(monkeypatch, lambda _: pytest.fail("internal target sent to DNS"))
    with pytest.raises(ReachDeniedError):
        resolve_public(host)


@pytest.mark.parametrize(
    "payload",
    [
        {"Status": 3},
        {"Status": 0, "Question": [{"name": "other.com", "type": 1}]},
        {"Status": 0, "Question": [{"name": "example.com", "type": 1}], "Answer": []},
    ],
)
def test_missing_or_mismatched_response_refuses(monkeypatch, payload):
    install(monkeypatch, lambda _: httpx2.Response(200, json=payload))
    with pytest.raises(ReachDeniedError):
        resolve_public("example.com")


def test_unknown_config_refuses(monkeypatch):
    monkeypatch.setenv("PDOS_RESEARCH_DNS_MODE", "skip-private-check")
    with pytest.raises(ReachDeniedError, match="DNS配置无效"):
        _default_resolver("example.com")
