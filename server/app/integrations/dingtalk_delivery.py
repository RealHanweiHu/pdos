"""Fixed-egress DingTalk application-token and outbound API client."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from time import monotonic

import httpx2

APP_TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
GROUP_MESSAGE_URL = "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
APPROVAL_URL = "https://api.dingtalk.com/v1.0/workflow/processInstances"
CARD_CREATE_URL = "https://api.dingtalk.com/v1.0/card/instances/createAndDeliver"
CARD_UPDATE_URL = "https://api.dingtalk.com/v1.0/card/instances"
TOKEN_REFRESH_MARGIN_SECONDS = 300


class DingTalkDeliveryError(RuntimeError):
    def __init__(self, code: str, *, uncertain: bool = False, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.uncertain = uncertain
        self.retryable = retryable


@dataclass(frozen=True)
class DeliveryResult:
    remote_reference: str


@dataclass(frozen=True)
class ApprovalSnapshot:
    status: str
    result: str | None


def _mapping(response: httpx2.Response) -> Mapping[str, object]:
    try:
        body = response.json()
    except ValueError as error:
        raise DingTalkDeliveryError(
            "DINGTALK_INVALID_RESPONSE",
            uncertain=response.status_code < 500,
        ) from error
    if not isinstance(body, Mapping):
        raise DingTalkDeliveryError("DINGTALK_INVALID_RESPONSE", uncertain=True)
    return body


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _api_error(body: Mapping[str, object]) -> bool:
    if body.get("success") is False:
        return True
    for key in ("code", "errcode"):
        value = body.get(key)
        if value not in (None, 0, "0", "OK"):
            return True
    return False


class DingTalkDeliveryClient:
    def __init__(self, client: httpx2.Client) -> None:
        self._client = client
        self._app_token: str | None = None
        self._app_token_client_id: str | None = None
        self._app_token_refresh_at = 0.0

    def app_token(self, *, client_id: str, client_secret: str) -> str:
        current = monotonic()
        if (
            self._app_token is not None
            and self._app_token_client_id == client_id
            and current < self._app_token_refresh_at
        ):
            return self._app_token
        try:
            response = self._client.post(
                APP_TOKEN_URL,
                json={"appKey": client_id, "appSecret": client_secret},
                timeout=15.0,
            )
        except httpx2.HTTPError as error:
            raise DingTalkDeliveryError(
                "DINGTALK_TOKEN_UNAVAILABLE",
                retryable=True,
            ) from error
        if response.status_code == 429 or response.status_code >= 500:
            raise DingTalkDeliveryError("DINGTALK_TOKEN_UNAVAILABLE", retryable=True)
        body = _mapping(response)
        if not response.is_success or _api_error(body):
            raise DingTalkDeliveryError("DINGTALK_TOKEN_REJECTED")
        token = _text(body.get("accessToken"))
        expires_in = body.get("expireIn")
        if token is None or type(expires_in) is not int or not 1 <= expires_in <= 86_400:
            raise DingTalkDeliveryError("DINGTALK_TOKEN_INVALID_RESPONSE", retryable=True)
        self._app_token = token
        self._app_token_client_id = client_id
        self._app_token_refresh_at = current + max(
            1,
            expires_in - TOKEN_REFRESH_MARGIN_SECONDS,
        )
        return token

    def send_group_markdown(
        self,
        *,
        token: str,
        robot_code: str,
        open_conversation_id: str,
        title: str,
        text: str,
    ) -> DeliveryResult:
        return self._create(
            GROUP_MESSAGE_URL,
            token=token,
            payload={
                "robotCode": robot_code,
                "openConversationId": open_conversation_id,
                "msgKey": "sampleMarkdown",
                "msgParam": '{"title":'
                + _json_string(title)
                + ',"text":'
                + _json_string(text)
                + "}",
            },
            reference_keys=("processQueryKey", "messageId", "taskId"),
        )

    def create_gate_approval(
        self,
        *,
        token: str,
        process_code: str,
        originator_staff_id: str,
        approver_staff_id: str,
        agent_id: int | None,
        request_id: str,
        form_values: list[dict[str, str]],
    ) -> DeliveryResult:
        payload: dict[str, object] = {
            "processCode": process_code,
            "originatorUserId": originator_staff_id,
            "deptId": -1,
            "approvers": [{"actionType": "AND", "userIds": [approver_staff_id]}],
            "formComponentValues": form_values,
            "requestId": request_id,
        }
        if agent_id is not None:
            payload["microappAgentId"] = agent_id
        return self._create(
            APPROVAL_URL,
            token=token,
            payload=payload,
            reference_keys=("instanceId", "processInstanceId"),
        )

    def create_interactive_card(
        self,
        *,
        token: str,
        staff_id: str,
        template_id: str,
        out_track_id: str,
        callback_route_key: str,
        card_params: dict[str, str],
    ) -> DeliveryResult:
        self._create(
            CARD_CREATE_URL,
            token=token,
            payload={
                "userId": staff_id,
                "userIdType": 1,
                "cardTemplateId": template_id,
                "outTrackId": out_track_id,
                "callbackType": "HTTP",
                "callbackRouteKey": callback_route_key,
                "openSpaceId": f"dtv1.card//IM_ROBOT.{staff_id}",
                "cardData": {"cardParamMap": card_params},
                "imRobotOpenSpaceModel": {"supportForward": False},
                "imRobotOpenDeliverModel": {"spaceType": "IM_ROBOT"},
            },
            reference_keys=(),
        )
        return DeliveryResult(remote_reference=out_track_id)

    def get_approval(self, *, token: str, process_instance_id: str) -> ApprovalSnapshot:
        try:
            response = self._client.get(
                APPROVAL_URL,
                headers={"x-acs-dingtalk-access-token": token},
                params={"processInstanceId": process_instance_id},
                timeout=15.0,
            )
        except httpx2.HTTPError as error:
            raise DingTalkDeliveryError(
                "DINGTALK_APPROVAL_SYNC_UNAVAILABLE", retryable=True
            ) from error
        if response.status_code == 429 or response.status_code >= 500:
            raise DingTalkDeliveryError("DINGTALK_APPROVAL_SYNC_UNAVAILABLE", retryable=True)
        body = _mapping(response)
        if not response.is_success or _api_error(body):
            raise DingTalkDeliveryError("DINGTALK_APPROVAL_SYNC_REJECTED")
        nested = body.get("result")
        detail = nested if isinstance(nested, Mapping) else body
        remote_status = (
            _text(detail.get("status")) or _text(detail.get("instanceStatus")) or ""
        ).lower()
        remote_result = (
            _text(detail.get("result")) or _text(detail.get("approveResult")) or ""
        ).lower()
        if "terminate" in remote_status or "cancel" in remote_status:
            status = "terminated"
        elif any(value in remote_result for value in ("refuse", "reject", "disagree")):
            status = "rejected"
        elif any(value in remote_result for value in ("agree", "approve")) or (
            "complete" in remote_status and not remote_result
        ):
            status = "approved"
        elif not remote_status or "running" in remote_status or "pending" in remote_status:
            status = "pending"
        else:
            status = "sync_failed"
        return ApprovalSnapshot(status=status, result=remote_result or None)

    def _create(
        self,
        url: str,
        *,
        token: str,
        payload: dict[str, object],
        reference_keys: tuple[str, ...],
    ) -> DeliveryResult:
        try:
            response = self._client.post(
                url,
                headers={"x-acs-dingtalk-access-token": token},
                json=payload,
                timeout=20.0,
            )
        except httpx2.HTTPError as error:
            raise DingTalkDeliveryError(
                "DINGTALK_CREATE_OUTCOME_UNKNOWN", uncertain=True
            ) from error
        if response.status_code in {408, 429} or response.status_code >= 500:
            raise DingTalkDeliveryError("DINGTALK_CREATE_OUTCOME_UNKNOWN", uncertain=True)
        body = _mapping(response)
        if not response.is_success or _api_error(body):
            raise DingTalkDeliveryError("DINGTALK_CREATE_REJECTED")
        nested = body.get("result")
        nested_mapping = nested if isinstance(nested, Mapping) else {}
        for key in reference_keys:
            reference = _text(body.get(key)) or _text(nested_mapping.get(key))
            if reference is not None:
                return DeliveryResult(remote_reference=reference)
        if reference_keys:
            raise DingTalkDeliveryError("DINGTALK_CREATE_OUTCOME_UNKNOWN", uncertain=True)
        return DeliveryResult(remote_reference="accepted")


def _json_string(value: str) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
