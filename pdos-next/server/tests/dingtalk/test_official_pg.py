"""Real native account/Run/Delivery PG cases; official HTTPS is MockTransport only.

Root applies G+delta+protocol and its reviewed migration first. No test here was
run against PG by this agent. Original setup verifies the explicit test target.
"""
# ruff: noqa: F401 -- original real PG fixture is re-exported, never replaced

import base64
import hashlib
import hmac
import json
import time
from dataclasses import replace
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall
from pdos_next.dingtalk.accounts import credential
from pdos_next.dingtalk.models import Delivery, Message
from pdos_next.dingtalk.official import OfficialAdapter
from pdos_next.dingtalk.runtime import ChannelService, configure
from pdos_next.dingtalk.schemas import DeliveryReference
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.dingtalk.test_channel_pg import channel as channel


def protocol(channel, *, lose_response=False):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        path = request.url.path
        if path == "/v1.0/oauth2/userAccessToken":
            return httpx.Response(
                200, json={"accessToken": "offline-user", "corpId": channel.app.corp_id}
            )
        if path == "/v1.0/contact/users/me":
            return httpx.Response(200, json={"unionId": "offline-union"})
        if path == "/v1.0/oauth2/accessToken":
            return httpx.Response(200, json={"accessToken": "offline-app"})
        if path == "/topapi/user/getbyunionid":
            return httpx.Response(
                200,
                json={"errcode": 0, "result": {"contact_type": 0, "userid": "offline-employee"}},
            )
        if path == "/v1.0/robot/oToMessages/batchSend":
            if lose_response:
                raise httpx.ReadTimeout("offline response lost", request=request)
            return httpx.Response(200, json={"processQueryKey": "offline+query/key="})
        if path == "/v1.0/robot/groupMessages/send":
            return httpx.Response(200, json={"processQueryKey": "offline+group/query/key="})
        if path == "/v1.0/robot/groupMessages/query":
            return httpx.Response(200, json={"sendStatus": "SUCCESS"})
        assert path == "/v1.0/robot/oToMessages/readStatus"
        return httpx.Response(200, json={"sendStatus": "SUCCESS"})

    adapter = OfficialAdapter(
        httpx.Client(transport=httpx.MockTransport(handler)),
        "https://pdos.synthetic.invalid/?area=settings&dingtalk_callback=1",
    )
    runtime = replace(channel.runtime, adapter=adapter)
    configure(channel.setup.engine, runtime)
    service = ChannelService(channel.setup.engine, channel.setup.dispatch, runtime=runtime)
    return SimpleNamespace(adapter=adapter, runtime=runtime, service=service, calls=calls)


def bind_official(channel):
    response = channel.client.post(
        "/v1/personal/dingtalk/bindings/begin",
        headers=channel.setup.headers,
        json={"application_id": str(channel.app.id)},
    )
    assert response.status_code == 200, response.text
    state = parse_qs(urlsplit(response.json()["authorization_url"]).query)["state"][0]
    response = channel.client.post(
        "/v1/personal/dingtalk/bindings/finish",
        headers=channel.setup.headers,
        json={"application_id": str(channel.app.id), "state": state, "auth_code": "offline-code"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def incoming_official(channel, runtime):
    body = json.dumps(
        {
            "msgtype": "text",
            "text": {"content": "读取本人可见依据"},
            "robotCode": channel.app.robot_code,
            "chatbotCorpId": channel.app.corp_id,
            "senderCorpId": channel.app.corp_id,
            "senderStaffId": "offline-employee",
            "conversationType": "2",
            "conversationId": "offline-group",
            "msgId": "offline-message",
            "isInAtList": True,
        },
        ensure_ascii=False,
    ).encode()
    at = str(int(time.time() * 1000))
    secret = credential(runtime, channel.app).get_secret_value()
    signature = base64.b64encode(
        hmac.new(secret.encode(), (at + "\n" + secret).encode(), hashlib.sha256).digest()
    ).decode()
    return channel.client.post(
        f"/v1/dingtalk/applications/{channel.app.id}/events",
        content=body,
        headers={"Content-Type": "application/json", "timestamp": at, "sign": signature},
    )


def test_official_binding_ingress_and_pending_receipt_use_actual_native_rows(channel):
    setup = channel.setup
    wire = protocol(channel)
    view = channel.client.get("/v1/personal/dingtalk/settings", headers=setup.headers)
    assert view.status_code == 200 and view.json()["can_manage"] and view.json()["configured"]
    assert wire.calls == []  # Ordinary GET does not acquire a secret or call a provider.
    binding = bind_official(channel)
    assert binding["active"]
    response = incoming_official(channel, wire.runtime)
    assert response.status_code == 200 and response.json() == {"msgtype": "empty"}
    assert incoming_official(channel, wire.runtime).json() == {"msgtype": "empty"}
    with Session(setup.admin) as session:
        messages = list(session.scalars(select(Message).where(Message.tenant_id == setup.tenant)))
        assert len(messages) == 1
        message = messages[0]
        run = session.get(AgentRun, message.run_id)
        assert run.requester_id == setup.human and run.writer_id == setup.agent
        assert run.goal == "读取本人可见依据" and run.state == "queued"
        message_id = message.id
    ref = DeliveryReference(tenant_id=setup.tenant, message_id=message_id, phase="received")
    first = wire.service.deliver(ref)
    assert first["state"] == "unknown" and first["attempts"] == 1
    # New adapter instance has no in-memory UUID→processQueryKey map. The actual
    # Delivery.provider_receipt supplies the server-bound query handle after restart.
    fresh = protocol(channel)
    second = fresh.service.deliver(ref)
    assert second["state"] == "delivered" and second["attempts"] == 1
    assert fresh.calls == ["/v1.0/oauth2/accessToken", "/v1.0/robot/oToMessages/readStatus"]
    with Session(setup.admin) as session:
        row = session.get(Delivery, UUID(first["delivery_id"]))
        assert row.provider_receipt["message_id"] == "offline+query/key="
        assert row.provider_receipt["status"] == "delivered"
        assert row.p26["provider"] == "dingtalk" and row.p26["checked_at"]
        assert (
            session.scalar(
                select(func.count())
                .select_from(AgentToolCall)
                .where(AgentToolCall.tenant_id == setup.tenant)
            )
            == 0
        )
    peer = {"Authorization": "Bearer " + setup.tokens[setup.peer]}
    view = channel.client.get("/v1/personal/dingtalk/settings", headers=peer)
    assert view.status_code == 200 and not view.json()["can_manage"] and not view.json()["bindings"]
    assert "secret_arn" not in view.json()["application"]


def test_official_lost_send_response_remains_unknown_without_second_send(channel):
    wire = protocol(channel, lose_response=True)
    bind_official(channel)
    assert incoming_official(channel, wire.runtime).status_code == 200
    with Session(channel.setup.admin) as session:
        message = session.scalar(select(Message).where(Message.tenant_id == channel.setup.tenant))
        ref = DeliveryReference(
            tenant_id=channel.setup.tenant, message_id=message.id, phase="received"
        )
    first = wire.service.deliver(ref)
    assert first["state"] == "unknown"
    before = len(wire.calls)
    assert wire.service.deliver(ref)["state"] == "unknown"
    assert len(wire.calls) == before  # No documented provider query is possible without its key.
    with Session(channel.setup.admin) as session:
        row = session.get(Delivery, UUID(first["delivery_id"]))
        assert row.attempts == 1 and row.provider_receipt is None
