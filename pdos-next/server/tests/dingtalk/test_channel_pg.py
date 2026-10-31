"""Actual PG/native HTTP drafts. Root applies the reviewed unnumbered DDL before running.

No live credentials, protocol, provider, embeddings, transport or external network.
The shared TEST_DATABASE_URL fixture retains the explicit verified target check.
"""

from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pdos_next.agent_kernel.bootstrap import RuntimePorts
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall, TenantAdministrator
from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.api import create_app
from pdos_next.database import tenant_session
from pdos_next.dingtalk.accounts import credential
from pdos_next.dingtalk.graph import execute
from pdos_next.dingtalk.models import Application, Binding, BindingNonce, Delivery, Message
from pdos_next.dingtalk.ports import ChannelRuntime
from pdos_next.dingtalk.runtime import ChannelService, configure, delivery_key
from pdos_next.dingtalk.schemas import ChannelReference, DeliveryReference
from pdos_next.dingtalk.synthetic import SyntheticAdapter, SyntheticKms
from pdos_next.errors import DomainError
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session


@pytest.fixture
def channel(setup):
    with Session(setup.admin) as session, session.begin():
        if not session.scalar(
            select(TenantAdministrator.id).where(
                TenantAdministrator.tenant_id == setup.tenant,
                TenantAdministrator.principal_id == setup.human,
            )
        ):
            session.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=setup.human))
    kms, adapter = SyntheticKms(), SyntheticAdapter()
    arn = "acs:kms:local:0:secret/dingtalk-" + str(uuid4())
    kms.install(arn, "1")
    runtime = ChannelRuntime(kms, adapter, "https://pdos.synthetic.invalid")
    configure(setup.engine, runtime)
    client = TestClient(create_app(setup.engine, setup.auth, agent_runtime_ports=RuntimePorts()))
    response = client.put(
        "/v1/dingtalk/application",
        headers=setup.headers,
        json={
            "expected_revision": 0,
            "corp_id": "synthetic-" + str(uuid4()),
            "client_id": "synthetic-client",
            "robot_code": "synthetic-robot",
            "secret_arn": arn,
            "secret_version": "1",
            "active": True,
        },
    )
    assert response.status_code == 200, response.text
    identity = UUID(response.json()["application_id"])
    with Session(setup.admin) as session:
        app = session.get(Application, identity)
        session.expunge(app)
    yield SimpleNamespace(
        setup=setup,
        app=app,
        runtime=runtime,
        client=client,
        service=ChannelService(setup.engine, setup.dispatch, runtime=runtime),
    )
    client.close()


def bind(channel, person=None, *, external_user="external-owner"):
    setup = channel.setup
    person = person or setup.human
    headers = {"Authorization": "Bearer " + setup.tokens[person]}
    response = channel.client.post(
        "/v1/personal/dingtalk/bindings/begin",
        headers=headers,
        json={"application_id": str(channel.app.id)},
    )
    assert response.status_code == 200, response.text
    state = parse_qs(urlsplit(response.json()["authorization_url"]).query)["state"][0]
    code = channel.runtime.adapter.issue_code(channel.app, external_user, state)
    payload = {
        "application_id": str(channel.app.id),
        "state": state,
        "auth_code": code.get_secret_value(),
    }
    result = channel.client.post(
        "/v1/personal/dingtalk/bindings/finish", headers=headers, json=payload
    )
    assert result.status_code == 200, result.text
    return result.json(), payload


def incoming(
    channel, *, message_id="synthetic-message-1", external_user="external-owner", mentioned=True
):
    app, runtime = channel.app, channel.runtime
    body, signature, at = runtime.adapter.envelope(
        app,
        credential(runtime, app),
        {
            "corp_id": app.corp_id,
            "external_user_id": external_user,
            "message_id": message_id,
            "conversation_kind": "group",
            "conversation_id": "synthetic-group",
            "mentioned": mentioned,
            "text": "以前漏气如何处理？",
        },
    )
    return channel.client.post(
        f"/v1/dingtalk/applications/{app.id}/events",
        content=body,
        headers={
            "content-type": "application/json",
            "x-channel-signature": signature,
            "x-channel-timestamp": at,
        },
    )


def test_verified_binding_nonce_consume_no_unbound_run_and_one_to_one(channel):
    setup = channel.setup
    empty = incoming(channel)
    assert empty.status_code == 202 and empty.json()["binding_required"]
    with Session(setup.admin) as session:
        assert (
            session.scalar(
                select(func.count()).select_from(AgentRun).where(AgentRun.tenant_id == setup.tenant)
            )
            == 0
        )
    binding, original = bind(channel)
    replay = channel.client.post(
        "/v1/personal/dingtalk/bindings/finish", headers=setup.headers, json=original
    )
    assert replay.status_code == 403
    ignored = incoming(channel, message_id="not-mentioned", mentioned=False)
    assert ignored.status_code == 202 and ignored.json()["ignored"]
    admitted = incoming(channel)
    assert admitted.status_code == 202 and admitted.json()["accepted"]
    repeated = incoming(channel)
    assert repeated.json() == admitted.json()
    with Session(setup.admin) as session:
        run = session.get(AgentRun, UUID(admitted.json()["run_id"]))
        assert run.requester_id == setup.human and run.writer_id == setup.agent
        assert run.category_id is None and run.trigger == "conversation"
        assert run.versions["dingtalk"] == {"version": 1}
        assert (
            session.scalar(
                select(func.count()).select_from(Message).where(Message.tenant_id == setup.tenant)
            )
            == 1
        )
        nonce = session.scalar(select(BindingNonce).where(BindingNonce.tenant_id == setup.tenant))
        assert nonce.consumed_at is not None and original["state"] != nonce.state_sha256
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.peer, requester_id=setup.peer, read_snapshot=True
    ) as session:
        assert session.get(AgentRun, run.id) is None
        # Service may resolve verified external IDs, other Humans cannot enumerate bindings.
        assert session.get(Binding, UUID(binding["binding_id"])) is None
    assert channel.runtime.adapter.send_count == 0


def test_native_ack_and_unknown_delivery_recover_by_lookup_with_durable_p26(channel):
    setup = channel.setup
    bind(channel)
    result = incoming(channel)
    assert result.status_code == 202, result.text
    ref = DeliveryReference(
        tenant_id=setup.tenant, message_id=UUID(result.json()["message_id"]), phase="received"
    )
    key = delivery_key(ref.message_id, "received")
    channel.runtime.adapter.lose_after_send.add(key)
    first = channel.service.deliver(ref)
    assert first["state"] == "unknown" and first["attempts"] == 1
    # Fresh process/service instance never calls send() again for sending/unknown.
    recovered = ChannelService(setup.engine, setup.dispatch, runtime=channel.runtime).deliver(ref)
    assert recovered["state"] == "delivered" and recovered["attempts"] == 1
    assert channel.runtime.adapter.send_count == channel.runtime.adapter.lookup_count == 1
    with Session(setup.admin) as session:
        receipt = session.get(Delivery, UUID(first["delivery_id"]))
        assert receipt.p26["provider"] == "dingtalk"
        assert receipt.p26["data_categories"] == ["internal"]
        assert receipt.p26["checked_at"] and receipt.provider_receipt["synthetic"]
        assert receipt.payload_sha256 == receipt.provider_receipt["payload_sha256"]
        assert (
            session.scalar(
                select(func.count())
                .select_from(AgentToolCall)
                .where(AgentToolCall.tenant_id == setup.tenant)
            )
            == 0
        )


@pytest.mark.parametrize("revoker", ["owner", "administrator"])
def test_actual_revoke_cancels_fixed_run_and_blocks_completion_without_owner_impersonation(
    channel, revoker
):
    setup = channel.setup
    # Bind peer for administrator case: actual owner remains peer; admin stays human.
    person = setup.human if revoker == "owner" else setup.peer
    binding, _payload = bind(channel, person=person)
    response = incoming(channel)
    assert response.status_code == 202, response.text
    run_id = UUID(response.json()["run_id"])
    ref = ChannelReference(tenant_id=setup.tenant, message_id=UUID(response.json()["message_id"]))
    headers = {"Authorization": "Bearer " + setup.tokens[setup.human]}
    revoked = channel.client.post(
        "/v1/personal/dingtalk/bindings/revoke",
        headers=headers,
        json={
            "binding_id": binding["binding_id"],
            "expected_epoch": 1,
            "reason": "本人/具名管理员在合成测试中撤销",
            "request_key": str(uuid4()),
        },
    )
    assert revoked.status_code == 200, revoked.text
    assert execute(channel.service, ref.model_dump(mode="json"))["state"] == "cancelled"
    with Session(setup.admin) as session:
        run = session.get(AgentRun, run_id)
        assert run.state == "cancelled" and run.cancel_epoch == 1 and run.used_tokens == 0
        assert run.held_tokens == 0 and run.requester_id == person
        assert session.get(Binding, UUID(binding["binding_id"])).revoked_by == setup.human
    store = KernelStore(setup.engine)
    with pytest.raises(DomainError):
        store.scope(
            tenant_id=setup.tenant,
            requester_id=person,
            writer_id=setup.agent,
            category_id=None,
            run_id=run_id,
        )
    assert channel.runtime.adapter.send_count == 0


def test_maintenance_role_is_metadata_only_and_has_no_runtime_membership(channel):
    setup = channel.setup
    with Session(setup.admin) as session:
        role = session.execute(
            text(
                "SELECT rolcanlogin,rolsuper,rolbypassrls,rolcreaterole "
                "FROM pg_roles WHERE rolname='pdos_next_dingtalk_maintenance'"
            )
        ).one()
        assert not any(role)
        for runtime in ["pdos_next_app", "pdos_next_auth", "pdos_next_dispatch", "pdos_agent"]:
            assert not session.scalar(
                text("SELECT pg_has_role(:role,'pdos_next_dingtalk_maintenance','MEMBER')"),
                {"role": runtime},
            )
        for table, column in [
            ("agent_runs", "goal"),
            ("agent_runs", "result"),
            ("artifact_versions", "content"),
            ("dingtalk_deliveries", "payload"),
        ]:
            assert not session.scalar(
                text(
                    "SELECT has_column_privilege('pdos_next_dingtalk_maintenance',"
                    ":table,:column,'SELECT')"
                ),
                {"table": table, "column": column},
            )
