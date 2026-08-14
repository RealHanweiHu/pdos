from __future__ import annotations

import httpx2
import pytest

import app.integrations.dingtalk_delivery as delivery
from app.integrations.dingtalk_delivery import (
    APP_TOKEN_URL,
    DingTalkDeliveryClient,
    DingTalkDeliveryError,
)


def test_app_token_is_cached_and_refreshed_before_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = 1000.0
    calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        assert str(request.url) == APP_TOKEN_URL
        calls += 1
        return httpx2.Response(
            200,
            json={"accessToken": f"token-{calls}", "expireIn": 7200},
        )

    monkeypatch.setattr(delivery, "monotonic", lambda: current)
    with httpx2.Client(transport=httpx2.MockTransport(handler), trust_env=False) as http:
        client = DingTalkDeliveryClient(http)
        assert client.app_token(client_id="client", client_secret="secret") == "token-1"
        current += 6899
        assert client.app_token(client_id="client", client_secret="secret") == "token-1"
        current += 1
        assert client.app_token(client_id="client", client_secret="secret") == "token-2"
    assert calls == 2


@pytest.mark.parametrize("expires_in", [None, True, 0, -1, 86_401, "7200"])
def test_app_token_rejects_invalid_expiry(expires_in: object) -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={"accessToken": "token", "expireIn": expires_in},
        )

    with (
        httpx2.Client(transport=httpx2.MockTransport(handler), trust_env=False) as http,
        pytest.raises(DingTalkDeliveryError, match="DINGTALK_TOKEN_INVALID_RESPONSE"),
    ):
        DingTalkDeliveryClient(http).app_token(client_id="client", client_secret="secret")
