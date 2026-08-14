from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import httpx2
from pydantic import SecretStr

from app.ai.egress import ProviderEgressPolicy
from app.ai.model_catalog import AgentTier, ProtocolKind, ProviderName, ResolvedModelRoute
from app.ai.provider_adapters import AnthropicNativeAdapter, ChatMessage, OpenAICompatibleAdapter


class FakeProviderHandler(BaseHTTPRequestHandler):
    requests: list[tuple[str, dict[str, str], dict[str, object]]] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length))
        headers = {name.lower(): value for name, value in self.headers.items()}
        self.requests.append((self.path, headers, body))
        if self.path == "/openai/v1/chat/completions":
            payload = {
                "id": "real-http-openai",
                "model": "minimax-fake-v1",
                "choices": [{"message": {"content": '{"label":"high"}'}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            }
        elif self.path == "/anthropic/v1/messages":
            payload = {
                "id": "real-http-anthropic",
                "model": "claude-fake-v1",
                "content": [{"type": "text", "text": '{"label":"low"}'}],
                "usage": {"input_tokens": 8, "output_tokens": 2},
            }
        else:
            self.send_error(404)
            return
        encoded = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        return


@contextmanager
def fake_provider() -> Iterator[str]:
    FakeProviderHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeProviderHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_both_frozen_protocols_cross_a_real_http_socket() -> None:
    with fake_provider() as base_url:
        openai_route = ResolvedModelRoute(
            provider=ProviderName.MINIMAX,
            protocol=ProtocolKind.OPENAI_COMPATIBLE,
            base_url=f"{base_url}/openai/v1",
            model="minimax-fake",
            api_key=SecretStr("openai-fake-secret"),
            agent_tier=AgentTier.DEFAULT,
        )
        anthropic_route = ResolvedModelRoute(
            provider=ProviderName.ANTHROPIC,
            protocol=ProtocolKind.ANTHROPIC_NATIVE,
            base_url=f"{base_url}/anthropic",
            model="claude-fake",
            api_key=SecretStr("anthropic-fake-secret"),
            agent_tier=AgentTier.DEFAULT,
        )
        policy = ProviderEgressPolicy.from_routes([openai_route, anthropic_route])
        with httpx2.Client(follow_redirects=False, trust_env=False) as client:
            openai = OpenAICompatibleAdapter(client, policy).complete(
                openai_route,
                [ChatMessage(role="user", content="Return JSON")],
            )
            anthropic = AnthropicNativeAdapter(client, policy).complete(
                anthropic_route,
                [
                    ChatMessage(role="system", content="Frozen system"),
                    ChatMessage(role="user", content="Return JSON"),
                ],
            )

    assert openai.request_id == "real-http-openai"
    assert anthropic.request_id == "real-http-anthropic"
    assert [request[0] for request in FakeProviderHandler.requests] == [
        "/openai/v1/chat/completions",
        "/anthropic/v1/messages",
    ]
    assert FakeProviderHandler.requests[0][1]["authorization"] == "Bearer openai-fake-secret"
    assert FakeProviderHandler.requests[1][1]["x-api-key"] == "anthropic-fake-secret"
    assert FakeProviderHandler.requests[0][2]["temperature"] == 0
    assert FakeProviderHandler.requests[1][2]["system"] == "Frozen system"
