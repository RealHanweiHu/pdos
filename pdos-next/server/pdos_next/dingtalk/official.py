"""Internal-app robot HTTPS protocol. No client/runtime is created automatically.

Protocols: official DingTalk receive-message, OAuth/user token, corporate unionId
conversion, robot batchSend/groupMessages and read-status documentation. Transport
is injected; tests use only httpx.MockTransport. No webhook/history fallback.
"""

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode, urlsplit

import httpx

from pdos_next.errors import DomainError
from pdos_next.service import digest

from .ports import ExternalIdentity, Members, SingleMessage


class OfficialAdapter:
    """China internal-app contract; secrets/tokens live only inside this port."""

    group_citations = False
    protocol = "dingtalk-internal-http/v1"

    def __init__(self, client: httpx.Client, redirect_uri: str, *, clock=time.time):
        uri = urlsplit(redirect_uri)
        if (
            uri.scheme != "https"
            or not uri.hostname
            or uri.username
            or uri.password
            or uri.fragment
        ):
            raise ValueError("An explicit HTTPS PDOS callback is required")
        self.client, self.redirect_uri, self.clock = client, redirect_uri, clock

    def _request(self, method, path, *, token=None, legacy=False, **kwargs):
        host = "https://oapi.dingtalk.com" if legacy else "https://api.dingtalk.com"
        headers = {"Accept": "application/json"}
        if token is not None:
            headers["x-acs-dingtalk-access-token"] = token
        try:
            response = self.client.request(
                method, host + path, headers=headers, timeout=8, follow_redirects=False, **kwargs
            )
            if response.status_code != 200 or len(response.content) > 524288:
                raise ValueError("provider response unavailable")
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("provider response invalid")
            return data
        except (httpx.HTTPError, ValueError, UnicodeError):
            # SDK/provider exceptions may echo tokens, code, headers or answer body.
            raise DomainError("SOURCE_UNAVAILABLE", "钉钉协议响应尚未核实。") from None

    @staticmethod
    def _text(value, maximum=200):
        if not isinstance(value, str) or not value or len(value) > maximum:
            raise DomainError("FORBIDDEN_SCOPE", "钉钉固定身份字段缺失或无效。", 403)
        return value

    def _app_token(self, application, credential):
        data = self._request(
            "POST",
            "/v1.0/oauth2/accessToken",
            json={"appKey": application.client_id, "appSecret": credential.get_secret_value()},
        )
        return self._text(data.get("accessToken"), 4096)

    def authorization_url(self, application, state):
        self._text(state, 200)
        return "https://login.dingtalk.com/oauth2/auth?" + urlencode(
            {
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "client_id": application.client_id,
                "scope": "openid corpid",
                "corpId": application.corp_id,
                "state": state,
                "prompt": "consent",
            }
        )

    def exchange_identity(self, application, credential, code, state_sha256):
        data = self._request(
            "POST",
            "/v1.0/oauth2/userAccessToken",
            json={
                "clientId": application.client_id,
                "clientSecret": credential.get_secret_value(),
                "code": code.get_secret_value(),
                "grantType": "authorization_code",
            },
        )
        if data.get("corpId") != application.corp_id:
            raise DomainError("FORBIDDEN_SCOPE", "钉钉授权企业与当前登记不一致。", 403)
        profile = self._request(
            "GET", "/v1.0/contact/users/me", token=self._text(data.get("accessToken"), 4096)
        )
        union_id = self._text(profile.get("unionId"))
        # App token resolves the OAuth identity to the actual employee ID in the
        # registered corporation. Never match display name, phone, email or openId.
        member = self._request(
            "POST",
            "/topapi/user/getbyunionid",
            legacy=True,
            # Official legacy cURL form example keeps the token out of request
            # URLs (httpx/access logs otherwise include query strings).
            data={"access_token": self._app_token(application, credential), "unionid": union_id},
        )
        result = member.get("result")
        if (
            member.get("errcode") not in (0, "0")
            or not isinstance(result, dict)
            or result.get("contact_type") not in (0, "0")
        ):
            raise DomainError("FORBIDDEN_SCOPE", "钉钉账号尚未核实为当前企业成员。", 403)
        return ExternalIdentity(
            application.id, application.corp_id, self._text(result.get("userid")), state_sha256
        )

    def verify_message(self, application, credential, body, *, signature, timestamp):
        try:
            if len(body) > 32768 or not timestamp.isascii() or not timestamp.isdecimal():
                raise ValueError("invalid timestamp")
            sent = int(timestamp)
            if abs(int(self.clock() * 1000) - sent) > 3_600_000:
                raise ValueError("expired timestamp")
            secret = credential.get_secret_value().encode()
            expected = base64.b64encode(
                hmac.new(secret, timestamp.encode() + b"\n" + secret, hashlib.sha256).digest()
            ).decode()
            if not hmac.compare_digest(expected, signature):
                raise ValueError("signature mismatch")
            data = json.loads(body)
            if (
                not isinstance(data, dict)
                or data.get("msgtype") != "text"
                or data.get("chatbotCorpId") != application.corp_id
                or data.get("senderCorpId") != application.corp_id
                or data.get("robotCode") != application.robot_code
                or data.get("conversationType") not in ("1", "2")
                or not isinstance(data.get("text"), dict)
                or data.get("errorCode") is not None
            ):
                raise ValueError("wrong app or unsupported message")
            text = self._text(data["text"].get("content"), 8000)
            if not text.strip():
                raise ValueError("empty message")
            values = {
                "application_id": str(application.id),
                "corp_id": application.corp_id,
                "external_user_id": self._text(data.get("senderStaffId")),
                "message_id": self._text(data.get("msgId")),
                "conversation_kind": "direct" if data["conversationType"] == "1" else "group",
                "conversation_id": self._text(data.get("conversationId")),
                "mentioned": data.get("isInAtList") is True,
                "text": text,
            }
            # Only this one verified text reaches the Run. Ignore sessionWebhook,
            # nick/admin claims, media URLs and any conversation context extension.
            return SingleMessage(
                **{**values, "application_id": application.id}, envelope_sha256=digest(values)
            )
        except (ValueError, TypeError, UnicodeError, DomainError):
            raise DomainError("FORBIDDEN_SCOPE", "钉钉单条消息来源验证未通过。", 403) from None

    def members(self, application, credential, conversation_id):
        # The available robot protocol does not supply an atomic complete audience
        # version for sending. Do not invent that authority from atUsers or readUsers.
        return Members(application.id, conversation_id, (), False, "unverified")

    @staticmethod
    def _content(payload):
        if (
            not isinstance(payload, dict)
            or set(payload) - {"target_kind", "target_id", "text", "url"}
            or payload.get("target_kind") not in {"direct", "group"}
        ):
            raise DomainError("FORBIDDEN_SCOPE", "当前协议尚不支持已核全员受众的引文投递。", 403)
        target = OfficialAdapter._text(payload.get("target_id"))
        text = payload.get("text")
        url = payload.get("url")
        if not isinstance(text, str) or len(text) > 20000 or not isinstance(url, str):
            raise DomainError("VALIDATION_FAILED", "钉钉投递正文无效。", 422)
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise DomainError("VALIDATION_FAILED", "继续链接须指向当前 PDOS HTTPS 入口。", 422)
        # Plain text avoids an answer-supplied image/mention being executed by the
        # external renderer. The PDOS deep link remains visible and clickable.
        return target, text + "\n\n" + url

    def send(self, application, credential, request_key, payload):
        target, content = self._content(payload)
        group = payload["target_kind"] == "group"
        data = self._request(
            "POST",
            "/v1.0/robot/groupMessages/send" if group else "/v1.0/robot/oToMessages/batchSend",
            token=self._app_token(application, credential),
            json={
                "robotCode": application.robot_code,
                "msgKey": "sampleText",
                "msgParam": json.dumps({"content": content}, ensure_ascii=False),
                **({"openConversationId": target} if group else {"userIds": [target]}),
            },
        )
        key = self._text(data.get("processQueryKey"))
        excluded = any(
            target in (data.get(field) or [])
            for field in ("invalidStaffIdList", "flowControlledStaffIdList", "filteredStaffIdList")
        )
        return {
            "provider": "dingtalk",
            "message_id": key,
            "payload_sha256": digest(payload),
            "status": "failed" if excluded else "pending",
            "target_kind": payload["target_kind"],
            **({"conversation_id": target} if group else {}),
        }

    def lookup(self, application, credential, request_key):
        # There is no documented query by our UUID. An absent processQueryKey is
        # permanently unknown. Do not send again or scan somebody's chat history.
        return None

    def lookup_receipt(self, application, credential, request_key, receipt):
        if not isinstance(receipt, dict) or receipt.get("provider") != "dingtalk":
            return None
        key = self._text(receipt.get("message_id"))
        group = receipt.get("target_kind") == "group"
        if receipt.get("target_kind") not in {"group", "direct"}:
            return None
        token = self._app_token(application, credential)
        if group:
            data = self._request(
                "POST",
                "/v1.0/robot/groupMessages/query",
                token=token,
                json={
                    "robotCode": application.robot_code,
                    "processQueryKey": key,
                    "openConversationId": self._text(receipt.get("conversation_id")),
                    "maxResults": 1,
                },
            )
        else:
            data = self._request(
                "GET",
                "/v1.0/robot/oToMessages/readStatus",
                token=token,
                params={
                    "robotCode": application.robot_code,
                    "processQueryKey": key,
                },
            )
        state = data.get("sendStatus")
        # Official enum is SUCCESS; its published example also contains SUCESS.
        status = (
            "delivered"
            if state in {"SUCCESS", "SUCESS"}
            else ("failed" if state == "RECALLED" else "pending")
        )
        return {**receipt, "status": status}
