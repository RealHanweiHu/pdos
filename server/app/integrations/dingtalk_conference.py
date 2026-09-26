"""DingTalk scheduled conferences (official alibabacloud-dingtalk 2.2.59 schema).

https://pypi.org/project/alibabacloud-dingtalk/2.2.59/
The create API has no caller idempotency key. Never replay an ambiguous mutation.
"""

from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import quote, urlsplit

import httpx2

from app.integrations.dingtalk_delivery import DingTalkDeliveryError

URL = "https://api.dingtalk.com/v1.0/conference/scheduleConferences"


def valid_booking(id: object, url: object) -> bool:
    if not isinstance(id, str) or not 1 <= len(id.strip()) <= 256:
        return False
    if not isinstance(url, str) or not 1 <= len(url) <= 1024:
        return False
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname is not None
            and (parsed.hostname == "dingtalk.com" or parsed.hostname.endswith(".dingtalk.com"))
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
        )
    except ValueError:
        return False


class DingTalkConferenceClient:
    def __init__(self, client: httpx2.Client) -> None:
        self.client = client

    def perform(
        self,
        token: str,
        operation: Literal["create", "update", "cancel", "query"],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        method = {"create": "POST", "update": "PUT", "cancel": "POST", "query": "GET"}[operation]
        url = URL
        if operation == "cancel":
            url += "/cancel"
        elif operation == "query":
            url += f"/{quote(str(payload['scheduleConferenceId']), safe='')}/infos"
        try:
            response = self.client.request(
                method,
                url,
                headers={"x-acs-dingtalk-access-token": token},
                json=payload if operation != "query" else None,
                params={"requestUnionId": payload["creatorUnionId"]}
                if operation == "query"
                else None,
                timeout=20.0,
                follow_redirects=False,
            )
        except httpx2.HTTPError as error:
            raise DingTalkDeliveryError(
                "CONFERENCE_RESPONSE_UNKNOWN", uncertain=operation != "query"
            ) from error
        # A gateway/server error cannot establish that the mutation did not happen.
        if response.status_code >= 500 or response.status_code in (408, 429):
            raise DingTalkDeliveryError(
                "CONFERENCE_RESPONSE_UNKNOWN", uncertain=operation != "query"
            )
        try:
            body = response.json()
        except ValueError as error:
            raise DingTalkDeliveryError(
                "CONFERENCE_RESPONSE_INVALID", uncertain=operation != "query"
            ) from error
        if not isinstance(body, Mapping):
            raise DingTalkDeliveryError(
                "CONFERENCE_RESPONSE_INVALID", uncertain=operation != "query"
            )
        if not response.is_success:
            raise DingTalkDeliveryError("CONFERENCE_REQUEST_REJECTED")
        if body.get("code") not in (None, 0, "0", "OK") or body.get("success") is False:
            raise DingTalkDeliveryError("CONFERENCE_REQUEST_REJECTED")
        if operation in ("create", "query"):
            if not valid_booking(body.get("scheduleConferenceId"), body.get("url")):
                raise DingTalkDeliveryError(
                    "CONFERENCE_BOOKING_INCOMPLETE", uncertain=operation == "create"
                )
            result = {"external_meeting_id": body["scheduleConferenceId"], "join_url": body["url"]}
            if operation == "query":
                result["title"] = body.get("title") if isinstance(body.get("title"), str) else None
                for key in ("startTime", "endTime"):
                    value = body.get(key)
                    result[key] = (
                        value if type(value) is int and 0 <= value <= 253402300799999 else None
                    )
            if isinstance(body.get("requestId"), str):
                result["provider_request_id"] = body["requestId"][:256]
            return result
        if body.get("success") is not True:
            raise DingTalkDeliveryError("CONFERENCE_ACKNOWLEDGEMENT_MISSING", uncertain=True)
        return {"success": True, "external_meeting_id": payload["scheduleConferenceId"]}
