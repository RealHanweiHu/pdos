"""Official wire protocol with explicit MockTransport; never resolves a socket."""

import base64
import hashlib
import hmac
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from pdos_next.dingtalk.official import OfficialAdapter
from pdos_next.dingtalk.runtime import ChannelService
from pdos_next.errors import DomainError
from pdos_next.service import digest
from pydantic import SecretStr


@pytest.fixture
def app():
    return SimpleNamespace(
        id=uuid4(), client_id="ding-app", corp_id="ding-corp", robot_code="robot"
    )


def adapter(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return OfficialAdapter(
        client, "https://pdos.invalid/?area=settings&dingtalk_callback=1", clock=lambda: 10000
    )


def no_http(request):
    pytest.fail(f"unexpected HTTP path {request.url.path}")


def envelope(app, **changes):
    body = {
        "msgtype": "text",
        "text": {"content": "只读取当前一条"},
        "robotCode": app.robot_code,
        "chatbotCorpId": app.corp_id,
        "senderCorpId": app.corp_id,
        "senderStaffId": "real-staff-id",
        "msgId": "m1",
        "conversationType": "2",
        "conversationId": "group",
        "isInAtList": True,
        "isAdmin": True,
        "senderNick": "not authority",
        "sessionWebhook": "https://evil.invalid/",
        "conversationMsgContext": [{"text": "NEVER_INCLUDE_HISTORY"}],
        **changes,
    }
    return json.dumps(body, ensure_ascii=False).encode()


def sign(at="10000000", secret="not-a-real-secret"):
    return base64.b64encode(
        hmac.new(secret.encode(), (at + "\n" + secret).encode(), hashlib.sha256).digest()
    ).decode()


def test_official_callback_projects_only_one_corporate_text_and_ignores_webhook_history(app):
    channel = adapter(no_http)
    event = channel.verify_message(
        app, SecretStr("not-a-real-secret"), envelope(app), signature=sign(), timestamp="10000000"
    )
    assert event.text == "只读取当前一条" and event.external_user_id == "real-staff-id"
    assert event.mentioned and event.conversation_kind == "group"
    assert "NEVER_INCLUDE_HISTORY" not in repr(event) and "not-a-real-secret" not in repr(event)
    # Timestamp/sign protocol does not include body. The envelope hash binds the
    # accepted one-message identity and text; rotating webhook metadata is irrelevant.
    other = channel.verify_message(
        app,
        SecretStr("not-a-real-secret"),
        envelope(app, sessionWebhook="changed"),
        signature=sign(),
        timestamp="10000000",
    )
    assert event.envelope_sha256 == other.envelope_sha256


@pytest.mark.parametrize(
    "changes",
    [
        {"senderCorpId": "other"},
        {"chatbotCorpId": "other"},
        {"robotCode": "other"},
        {"senderStaffId": ""},
        {"msgtype": "file"},
        {"text": {}},
        {"errorCode": 20001},
        {"conversationType": "9"},
        {"text": {"content": " "}},
    ],
)
def test_external_identity_and_unsupported_payload_cannot_enter_a_run(app, changes):
    with pytest.raises(DomainError):
        adapter(no_http).verify_message(
            app,
            SecretStr("not-a-real-secret"),
            envelope(app, **changes),
            signature=sign(),
            timestamp="10000000",
        )


@pytest.mark.parametrize(
    "timestamp,signature",
    [("10000", sign("10000")), ("6400000", "bad"), ("-1", "bad"), ("99999999999", "bad")],
)
def test_milliseconds_signature_and_official_hour_window_are_checked(app, timestamp, signature):
    with pytest.raises(DomainError):
        adapter(no_http).verify_message(
            app,
            SecretStr("not-a-real-secret"),
            envelope(app),
            signature=signature,
            timestamp=timestamp,
        )


def test_authorization_url_keeps_explicit_callback_corporation_and_nonce(app):
    value = adapter(no_http).authorization_url(app, "opaque-one-use-state")
    parsed = urlsplit(value)
    q = parse_qs(parsed.query)
    assert parsed.netloc == "login.dingtalk.com"
    assert q["state"] == ["opaque-one-use-state"] and q["scope"] == ["openid corpid"]
    assert q["corpId"] == [app.corp_id] and q["client_id"] == [app.client_id]
    assert q["redirect_uri"] == ["https://pdos.invalid/?area=settings&dingtalk_callback=1"]


@pytest.mark.parametrize(
    "wrong_corp,external_member", [(False, False), (True, False), (False, True)]
)
def test_oauth_identity_uses_actual_unionid_to_employee_mapping(app, wrong_corp, external_member):
    calls = []

    def handler(request):
        calls.append(request)
        path = request.url.path
        if path == "/v1.0/oauth2/userAccessToken":
            assert json.loads(request.content) == {
                "clientId": app.client_id,
                "clientSecret": "synthetic-secret",
                "code": "synthetic-code",
                "grantType": "authorization_code",
            }
            return httpx.Response(
                200,
                json={
                    "accessToken": "user-token",
                    "corpId": "other" if wrong_corp else app.corp_id,
                },
            )
        if path == "/v1.0/contact/users/me":
            assert request.headers["x-acs-dingtalk-access-token"] == "user-token"
            return httpx.Response(
                200,
                json={
                    "unionId": "exact-union",
                    "nick": "not matching",
                    "openId": "not employee",
                    "mobile": "not used",
                },
            )
        if path == "/v1.0/oauth2/accessToken":
            return httpx.Response(200, json={"accessToken": "app-token"})
        assert path == "/topapi/user/getbyunionid" and request.url.host == "oapi.dingtalk.com"
        assert parse_qs(request.content.decode()) == {
            "unionid": ["exact-union"],
            "access_token": ["app-token"],
        }
        assert not request.url.query
        return httpx.Response(
            200,
            json={
                "errcode": 0,
                "result": {"contact_type": 1 if external_member else 0, "userid": "employee-7"},
            },
        )

    channel = adapter(handler)
    if wrong_corp or external_member:
        with pytest.raises(DomainError):
            channel.exchange_identity(
                app, SecretStr("synthetic-secret"), SecretStr("synthetic-code"), "a" * 64
            )
    else:
        identity = channel.exchange_identity(
            app, SecretStr("synthetic-secret"), SecretStr("synthetic-code"), "a" * 64
        )
        assert identity.external_user_id == "employee-7" and identity.state_sha256 == "a" * 64
    assert len(calls) == (1 if wrong_corp else 4)


def payload(group=False):
    return {
        "target_kind": "group" if group else "direct",
        "target_id": "target-7",
        "text": "实际回答",
        "url": "https://pdos.invalid/dingtalk/runs/" + str(uuid4()),
    }


@pytest.mark.parametrize("group", [False, True])
def test_send_pending_receipt_survives_new_adapter_and_only_query_confirms_success(app, group):
    calls = []

    def handler(request):
        calls.append(request)
        path = request.url.path
        if path == "/v1.0/oauth2/accessToken":
            return httpx.Response(200, json={"accessToken": "synthetic-token"})
        assert request.headers["x-acs-dingtalk-access-token"] == "synthetic-token"
        if path.endswith("/send") or path.endswith("/batchSend"):
            data = json.loads(request.content)
            assert data["robotCode"] == app.robot_code and data["msgKey"] == "sampleText"
            assert "request_key" not in data
            assert json.loads(data["msgParam"])["content"].startswith(
                "实际回答\n\nhttps://pdos.invalid/"
            )
            return httpx.Response(200, json={"processQueryKey": "query+key/with=special"})
        assert path == (
            "/v1.0/robot/groupMessages/query" if group else "/v1.0/robot/oToMessages/readStatus"
        )
        if not group:
            assert request.url.params["processQueryKey"] == "query+key/with=special"
        return httpx.Response(
            200, json={"sendStatus": "SUCCESS", "messageReadInfoList": [{"name": "not retained"}]}
        )

    body = payload(group)
    channel = adapter(handler)
    receipt = channel.send(app, SecretStr("synthetic-secret"), uuid4(), body)
    row = SimpleNamespace(
        payload_sha256=digest(body), state="sending", error_code=None, provider_receipt=None
    )
    ChannelService.accept_receipt(row, receipt)
    assert row.state == "unknown" and row.provider_receipt["message_id"] == "query+key/with=special"
    recovered = adapter(handler).lookup_receipt(
        app, SecretStr("synthetic-secret"), uuid4(), json.loads(json.dumps(row.provider_receipt))
    )
    ChannelService.accept_receipt(row, recovered)
    assert row.state == "delivered" and "messageReadInfoList" not in row.provider_receipt
    assert sum(r.url.path.endswith(("/send", "/batchSend")) for r in calls) == 1


def test_response_lost_before_process_key_is_unknown_and_never_retried(app):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/v1.0/oauth2/accessToken":
            return httpx.Response(200, json={"accessToken": "token"})
        raise httpx.ReadTimeout("response contained synthetic-secret", request=request)

    channel = adapter(handler)
    with pytest.raises(DomainError) as error:
        channel.send(app, SecretStr("synthetic-secret"), uuid4(), payload())
    assert "synthetic-secret" not in str(error.value)
    assert channel.lookup(app, SecretStr("synthetic-secret"), uuid4()) is None
    assert channel.lookup_receipt(app, SecretStr("synthetic-secret"), uuid4(), None) is None
    assert len(calls) == 2


def test_unknown_audience_never_becomes_at_users_or_read_users_authority(app):
    channel = adapter(no_http)
    members = channel.members(app, SecretStr("synthetic-secret"), "group")
    assert not members.complete and not members.external_user_ids and not channel.group_citations
    with pytest.raises(DomainError):
        channel.send(
            app,
            SecretStr("synthetic-secret"),
            uuid4(),
            {**payload(True), "citations": [{"quote": "secret"}], "membership_version": "invented"},
        )


def test_provider_redirect_does_not_forward_a_token_or_code(app):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://evil.invalid/?code=secret"})

    with pytest.raises(DomainError):
        adapter(handler).exchange_identity(
            app, SecretStr("synthetic-secret"), SecretStr("synthetic-code"), "a" * 64
        )
    assert len(calls) == 1 and all("evil.invalid" not in url for url in calls)


@pytest.mark.parametrize(
    "status,state",
    [
        ("pending", "unknown"),
        ("failed", "blocked"),
        ("delivered", "delivered"),
        ("invented", "unknown"),
    ],
)
def test_pending_or_filtered_send_is_not_falsely_marked_delivered(status, state):
    row = SimpleNamespace(payload_sha256="b" * 64, provider_receipt=None)
    ChannelService.accept_receipt(
        row,
        {
            "provider": "dingtalk",
            "message_id": "actual-key",
            "payload_sha256": "b" * 64,
            "status": status,
            "target_kind": "direct",
            "raw": "never retain",
        },
    )
    assert row.state == state
    if row.provider_receipt:
        assert "raw" not in row.provider_receipt


def test_pending_explicit_share_keeps_native_completion_waiting_for_query_only():
    from contextlib import contextmanager
    from uuid import uuid4

    from pdos_next.dingtalk.schemas import DeliveryReference

    service = object.__new__(ChannelService)
    consent = SimpleNamespace(message_id=uuid4(), state="planned", error_code=None)
    session = SimpleNamespace(get=lambda *args: consent)
    message = SimpleNamespace(id=consent.message_id)

    @contextmanager
    def metadata(ref):
        yield session, message, None

    service.metadata = metadata
    service.cancel_lost = lambda ref: None
    service.deliver = lambda ref: {"state": "unknown", "error_code": "EXTERNAL_OUTCOME_UNKNOWN"}
    ref = DeliveryReference(
        tenant_id=uuid4(), message_id=message.id, phase="share", consent_id=uuid4()
    )
    assert service.tick(ref) == {"state": "waiting", "delivery_state": "unknown"}
    assert consent.state == "unknown"  # honest metadata while Temporal keeps reconciling
