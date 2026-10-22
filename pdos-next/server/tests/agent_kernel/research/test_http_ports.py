"""Actual loopback HTTP plus transport/DNS seams; these tests never call public networks."""

import asyncio
import json
import socket
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from pdos_next.research import (
    PinnedHTTPTransport,
    ResearchError,
    ResourceLimits,
    SearxSearchAdapter,
    web,
)


@contextmanager
def local_http():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, dict(self.headers)))
            if self.path.startswith("/search"):
                body = json.dumps(
                    {
                        "results": [
                            {
                                "url": "https://maker.example/specs",
                                "title": "Local fixture",
                                "content": "lead",
                            }
                        ]
                    }
                ).encode()
                mime = "application/json"
            else:
                body, mime = b"<title>Local wire</title><p>Pressure 20 psi.</p>", "text/html"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address, requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_real_search_adapter_local_http_ignores_proxy_auth_environment(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1/")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1/")
    monkeypatch.setenv("SEARCH_API_KEY", "must-not-leave-process")
    with local_http() as (address, requests):
        adapter = SearxSearchAdapter(
            f"http://127.0.0.1:{address[1]}/search", provider="local-searx"
        )
        hits = asyncio.run(adapter.search("pump specs & public"))
    assert hits[0].title == "Local fixture" and hits[0].provider == "local-searx"
    path, headers = requests[0]
    assert parse_qs(urlsplit(path).query) == {"q": ["pump specs & public"], "format": ["json"]}
    assert "Authorization" not in headers and "Cookie" not in headers
    assert headers["Accept-Encoding"] == "identity"
    assert "must-not-leave-process" not in json.dumps(requests)


def test_pinned_transport_real_http_wire_has_validated_ip_target_and_original_host(monkeypatch):
    attempts = []
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1/")
    with local_http() as (local_address, requests):
        # The trusted test socket routes the public-IP target to loopback. Production socket
        # has no such mapping. This validates the actual HTTP pipeline without an external call.
        class FixtureSocket:
            def __init__(self, family, kind):
                self.socket = socket.socket(family, kind)

            def connect(self, target):
                attempts.append(target)
                assert target == ("8.8.8.8", 80)
                self.socket.connect(local_address)

            def getpeername(self):
                return "8.8.8.8", 80

            def __getattr__(self, key):
                return getattr(self.socket, key)

        monkeypatch.setattr(
            web,
            "socket",
            SimpleNamespace(
                AF_INET=socket.AF_INET,
                AF_INET6=socket.AF_INET6,
                SOCK_STREAM=socket.SOCK_STREAM,
                socket=FixtureSocket,
            ),
        )
        response = asyncio.run(
            PinnedHTTPTransport().request(
                "http://maker.example/specs?q=public", "8.8.8.8", ResourceLimits()
            )
        )
    assert attempts == [("8.8.8.8", 80)]
    assert response.status == 200 and b"Pressure 20 psi." in response.body
    assert requests[0][0] == "/specs?q=public"
    headers = requests[0][1]
    assert headers["Host"] == "maker.example"
    assert "Authorization" not in headers and "Cookie" not in headers


def test_pinned_transport_tls_keeps_original_hostname_for_sni_and_ca_verification(monkeypatch):
    observed = []

    class Response:
        status = 200
        fp = None

        def getheader(self, name):
            return None

        def getheaders(self):
            return (("Content-Type", "text/plain"),)

        def read(self, limit):
            return b""

    class Connection:
        def __init__(self, host, port, *, timeout, context):
            observed.append((host, port, context.check_hostname, context.verify_mode))

        def request(self, method, target, headers):
            assert method == "GET" and target == "/specs"
            assert "Authorization" not in headers

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(web.http.client, "HTTPSConnection", Connection)
    asyncio.run(
        PinnedHTTPTransport().request("https://maker.example/specs", "8.8.8.8", ResourceLimits())
    )
    assert observed[0][0:3] == ("maker.example", 443, True)
    assert observed[0][3] == web.ssl.CERT_REQUIRED


def test_pinned_transport_rejects_actual_peer_different_from_validated_ip(monkeypatch):
    class WrongPeer:
        def settimeout(self, timeout):
            pass

        def connect(self, target):
            pass

        def getpeername(self):
            return "127.0.0.1", 80

        def close(self):
            pass

    monkeypatch.setattr(
        web,
        "socket",
        SimpleNamespace(
            AF_INET=socket.AF_INET,
            AF_INET6=socket.AF_INET6,
            SOCK_STREAM=socket.SOCK_STREAM,
            socket=lambda *args: WrongPeer(),
        ),
    )
    with pytest.raises(ResearchError) as error:
        asyncio.run(
            PinnedHTTPTransport().request("http://maker.example/specs", "8.8.8.8", ResourceLimits())
        )
    assert error.value.reason == "peer_address_changed"


@pytest.mark.parametrize(
    "response,reason",
    [
        (httpx.Response(200, json={"no_results": []}), "invalid_search_result"),
        (httpx.Response(200, json={"results": "wrong"}), "invalid_search_result"),
        (
            httpx.Response(200, json={"results": [{"url": "https://maker.example/", "title": 22}]}),
            "invalid_search_result",
        ),
        (httpx.Response(200, content=b"x" * 101), "search_body_limit"),
        (
            httpx.Response(302, headers={"Location": "http://127.0.0.1:9999/secret"}),
            "search_http_error",
        ),
    ],
)
def test_search_adapter_validation_budget_and_no_redirect_follow(response, reason):
    async def handler(request):
        return response

    adapter = SearxSearchAdapter(
        "https://search.example/search",
        provider="fixture",
        transport=httpx.MockTransport(handler),
        max_response_bytes=100,
    )
    with pytest.raises(ResearchError) as error:
        asyncio.run(adapter.search("pump"))
    assert error.value.reason == reason


def test_search_adapter_original_service_failure_details_preserved():
    def handler(request):
        return httpx.Response(
            429,
            text="Search rate allowance exhausted",
            headers={"Retry-After": "5", "X-Request-ID": "search-local-22"},
        )

    adapter = SearxSearchAdapter(
        "https://search.example/search", provider="fixture", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ResearchError) as error:
        asyncio.run(adapter.search("pump"))
    actual = error.value
    assert actual.message == "Search rate allowance exhausted"
    assert (actual.http_status, actual.retry_after, actual.request_id) == (
        429,
        "5",
        "search-local-22",
    )
