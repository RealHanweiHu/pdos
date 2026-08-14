"""Local-only ASGI harness for the S5-1 real-browser OAuth acceptance flow."""

from __future__ import annotations

import json

import httpx2

from app.api.dingtalk import get_dingtalk_http_client
from app.integrations.dingtalk_client import ME_URL, TOKEN_URL
from app.main import app


def _fake_dingtalk_client() -> httpx2.Client:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if str(request.url) == TOKEN_URL:
            body = json.loads(request.content)
            if body.get("code") != "browser-valid-code":
                return httpx2.Response(401, json={"code": "INVALID_CODE"})
            return httpx2.Response(
                200,
                json={
                    "accessToken": "browser-ephemeral-token",
                    "corpId": "browser-dingtalk-corp",
                    "expireIn": 7200,
                },
            )
        if str(request.url) == ME_URL:
            return httpx2.Response(
                200,
                json={
                    "openId": "browser-open-id",
                    "userId": "browser-staff-id",
                    "unionId": "browser-union-id",
                },
            )
        raise AssertionError(f"unexpected fake DingTalk request: {request.method} {request.url}")

    return httpx2.Client(
        transport=httpx2.MockTransport(handler),
        follow_redirects=False,
        trust_env=False,
    )


app.dependency_overrides[get_dingtalk_http_client] = _fake_dingtalk_client
