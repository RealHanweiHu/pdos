"""Tencent enterprise meeting REST API, with exact-body AK/SK signing.

Official contracts:
https://meeting.tencent.com/support/topic/510/
https://meeting.tencent.com/support/topic/532/
https://meeting.tencent.com/support/topic/877/
https://meeting.tencent.com/support/topic/874/index.html
https://meeting.tencent.com/support/topic/875/index.html
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import quote, urlencode, urlsplit

import httpx2

from app.integrations.dingtalk_delivery import DingTalkDeliveryError
from app.settings import Settings


def valid_booking(id: object, url: object) -> bool:
    if (
        not isinstance(id, str)
        or not 1 <= len(id.strip()) <= 256
        or not isinstance(url, str)
        or len(url) > 1024
    ):
        return False
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname in ("meeting.tencent.com", "wemeet.qq.com")
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
        )
    except ValueError:
        return False


def signed_headers(settings: Settings, method: str, uri: str, body: str) -> dict[str, str]:
    key, secret = settings.tencent_meeting_key_id, settings.tencent_meeting_secret
    if not key or secret is None or not settings.tencent_meeting_app_id:
        raise DingTalkDeliveryError("CONFERENCE_CONFIGURATION_MISSING")
    timestamp, nonce = str(int(time.time())), str(secrets.randbelow(2**31 - 1) + 1)
    headers = {"X-TC-Key": key, "X-TC-Nonce": nonce, "X-TC-Timestamp": timestamp}
    canonical = "&".join(f"{name}={headers[name]}" for name in sorted(headers))
    message = f"{method}\n{canonical}\n{uri}\n{body}"
    hexadecimal = hmac.new(
        secret.get_secret_value().encode(), message.encode(), hashlib.sha256
    ).hexdigest()
    headers.update(
        {
            "X-TC-Signature": base64.b64encode(hexadecimal.encode("ascii")).decode("ascii"),
            "AppId": settings.tencent_meeting_app_id,
            "X-TC-Registered": "1",
            "Content-Type": "application/json; charset=utf-8",
        }
    )
    if settings.tencent_meeting_sdk_id:
        headers["SdkId"] = settings.tencent_meeting_sdk_id
    return headers


def milliseconds(value: object) -> int | None:
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 12:
        return int(value) * 1000 if int(value) <= 253402300799 else None
    return None


class TencentConferenceClient:
    def __init__(self, client: httpx2.Client, settings: Settings) -> None:
        self.client, self.settings = client, settings

    def perform(
        self, operation: Literal["create", "update", "cancel", "query"], payload: dict[str, Any]
    ) -> dict[str, Any]:
        method = {"create": "POST", "update": "PUT", "cancel": "POST", "query": "GET"}[operation]
        uri = "/v1/meetings"
        body_values = dict(payload)
        remote = body_values.pop("meeting_id", None)
        if operation != "create":
            uri += "/" + quote(str(remote), safe="")
        if operation == "cancel":
            uri += "/cancel"
        elif operation == "query":
            uri += "?" + urlencode(
                {"userid": payload["userid"], "instanceid": payload["instanceid"]}
            )
        body = (
            ""
            if operation == "query"
            else json.dumps(body_values, ensure_ascii=False, separators=(",", ":"))
        )
        headers = signed_headers(self.settings, method, uri, body)
        try:
            response = self.client.request(
                method,
                "https://api.meeting.qq.com" + uri,
                headers=headers,
                content=body.encode("utf-8"),
                timeout=20.0,
                follow_redirects=False,
            )
        except httpx2.HTTPError as error:
            raise DingTalkDeliveryError(
                "CONFERENCE_RESPONSE_UNKNOWN", uncertain=operation != "query"
            ) from error
        if response.status_code >= 500 or response.status_code in (408, 429):
            raise DingTalkDeliveryError(
                "CONFERENCE_RESPONSE_UNKNOWN", uncertain=operation != "query"
            )
        if not response.is_success:
            raise DingTalkDeliveryError("CONFERENCE_REQUEST_REJECTED")
        if operation == "cancel" and not response.content.strip():
            return {"success": True, "external_meeting_id": remote}
        try:
            value = response.json()
        except ValueError as error:
            raise DingTalkDeliveryError(
                "CONFERENCE_RESPONSE_INVALID", uncertain=operation != "query"
            ) from error
        if not isinstance(value, Mapping):
            raise DingTalkDeliveryError(
                "CONFERENCE_RESPONSE_INVALID", uncertain=operation != "query"
            )
        if value.get("error_info") or value.get("error_code") not in (None, 0, "0"):
            raise DingTalkDeliveryError("CONFERENCE_REQUEST_REJECTED")
        rows = value.get("meeting_info_list")
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
            raise DingTalkDeliveryError(
                "CONFERENCE_ACKNOWLEDGEMENT_MISSING", uncertain=operation != "query"
            )
        row = rows[0]
        id = row.get("meeting_id")
        if not isinstance(id, str) or not id or (operation != "create" and id != remote):
            raise DingTalkDeliveryError(
                "CONFERENCE_BOOKING_MISMATCH", uncertain=operation != "query"
            )
        result: dict[str, Any] = {"external_meeting_id": id}
        if operation in ("create", "query"):
            if not valid_booking(id, row.get("join_url")):
                raise DingTalkDeliveryError(
                    "CONFERENCE_BOOKING_INCOMPLETE", uncertain=operation == "create"
                )
            result["join_url"] = row["join_url"]
        if operation == "query":
            result.update(
                title=row.get("subject") if isinstance(row.get("subject"), str) else None,
                startTime=milliseconds(row.get("start_time")),
                endTime=milliseconds(row.get("end_time")),
                provider_state=row.get("status") if isinstance(row.get("status"), str) else None,
            )
        # Never persist passwords, participants, recording configuration or unrelated response data.
        return result
