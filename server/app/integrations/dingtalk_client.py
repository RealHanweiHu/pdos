"""Fixed-egress DingTalk OAuth client with strict response parsing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import httpx2

TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/userAccessToken"
ME_URL = "https://api.dingtalk.com/v1.0/contact/users/me"


class DingTalkClientError(RuntimeError):
    """A remote OAuth exchange failed or returned an invalid shape."""


@dataclass(frozen=True)
class DingTalkIdentity:
    corp_id: str
    open_id: str
    union_id: str | None


def _required_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DingTalkClientError("DINGTALK_INVALID_RESPONSE")
    return value.strip()


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    return _required_text(value)


class DingTalkOAuthClient:
    def __init__(self, client: httpx2.Client) -> None:
        self._client = client

    def exchange_identity(
        self,
        *,
        client_id: str,
        client_secret: str,
        auth_code: str,
    ) -> DingTalkIdentity:
        try:
            token_response = self._client.post(
                TOKEN_URL,
                json={
                    "clientId": client_id,
                    "clientSecret": client_secret,
                    "code": auth_code,
                    "grantType": "authorization_code",
                },
                timeout=15.0,
            )
            token_response.raise_for_status()
            token_body = token_response.json()
            if not isinstance(token_body, Mapping):
                raise DingTalkClientError("DINGTALK_INVALID_RESPONSE")
            user_access_token = _required_text(token_body.get("accessToken"))
            corp_id = _required_text(token_body.get("corpId"))

            me_response = self._client.get(
                ME_URL,
                headers={"x-acs-dingtalk-access-token": user_access_token},
                timeout=15.0,
            )
            me_response.raise_for_status()
            me_body = me_response.json()
            if not isinstance(me_body, Mapping):
                raise DingTalkClientError("DINGTALK_INVALID_RESPONSE")
            return DingTalkIdentity(
                corp_id=corp_id,
                open_id=_required_text(me_body.get("openId")),
                union_id=_optional_text(me_body.get("unionId")),
            )
        except DingTalkClientError:
            raise
        except (httpx2.HTTPError, TypeError, ValueError) as error:
            raise DingTalkClientError("DINGTALK_OAUTH_UNAVAILABLE") from error
