"""Root-run synthetic transport/native revoke serialization. No live DingTalk/model."""
# ruff: noqa: F401,F811 -- exact existing native fixture registration

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from threading import Event
from uuid import UUID, uuid4

import pytest
from pdos_next.database import tenant_session
from pdos_next.dingtalk.guards import message_binding
from pdos_next.dingtalk.models import Application, Binding
from pdos_next.dingtalk.schemas import DeliveryReference
from pdos_next.errors import DomainError
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.dingtalk.test_channel_pg import bind, channel, incoming


@pytest.mark.parametrize("change", ["self_revoke", "admin_disable"])
def test_real_transport_row_fence_serializes_human_revoke_or_config_change(channel, change):
    setup = channel.setup
    account, _ = bind(channel)
    incoming_result = incoming(channel)
    assert incoming_result.status_code == 202, incoming_result.text
    ref = DeliveryReference(
        tenant_id=setup.tenant,
        message_id=UUID(incoming_result.json()["message_id"]),
        phase="received",
    )
    delivery_id = channel.service.plan(ref)
    attempt = channel.service.reserve(ref, delivery_id)
    assert attempt is not None
    entered, release, changing = Event(), Event(), Event()
    original = channel.runtime.adapter.send

    def send(*args, **kwargs):
        entered.set()
        assert release.wait(10), "root-run synthetic transport was not released"
        return original(*args, **kwargs)

    def mutation():
        if change == "self_revoke":
            return channel.client.post(
                "/v1/personal/dingtalk/bindings/revoke", headers=setup.headers,
                json={"binding_id": account["binding_id"], "expected_epoch": 1,
                      "request_key": str(uuid4()), "reason": "本人撤销合成绑定"},
            )
        app = channel.app
        return channel.client.put(
            "/v1/dingtalk/application", headers=setup.headers,
            json={"expected_revision": app.revision, "corp_id": app.corp_id,
                  "client_id": app.client_id, "robot_code": app.robot_code,
                  "secret_arn": app.secret_arn, "secret_version": app.secret_version,
                  "active": False},
        )

    # TestClient may execute on an ASGI worker thread: identify only the target
    # statement, while the sending helper is PL/pgSQL and contains no client-side
    # Binding/Application FOR UPDATE statement.
    def observe(_connection, _cursor, statement, _params, _context, _many):
        table = "dingtalk_account_bindings" if change == "self_revoke" else "dingtalk_applications"
        if table in statement and "FOR UPDATE" in statement:
            changing.set()

    channel.runtime.adapter.send = send
    event.listen(setup.engine, "before_cursor_execute", observe)
    try:
        with ThreadPoolExecutor(2) as pool:
            sending = pool.submit(channel.service.send_reserved, ref, delivery_id, attempt)
            assert entered.wait(5)
            changing_future = pool.submit(mutation)
            try:
                assert changing.wait(5), "native Human command never attempted its row lock"
                with pytest.raises(FutureTimeout):
                    changing_future.result(timeout=0.2)
            finally:
                release.set()
            assert sending.result(timeout=10)["state"] == "delivered"
            changed = changing_future.result(timeout=10)
            assert changed.status_code == 200, changed.text
    finally:
        release.set()
        event.remove(setup.engine, "before_cursor_execute", observe)
        channel.runtime.adapter.send = original
    assert channel.runtime.adapter.send_count == 1
    # Once the Human transaction has committed, the exact old Message cannot
    # pass the sending fence, even though metadata reconciliation remains allowed.
    with channel.service.metadata(ref) as (session, message, _app):
        with pytest.raises(DomainError) as error:
            message_binding(session, message, lock=True)
        assert error.value.reason == "CANCELLED_RUN"
    assert channel.runtime.adapter.send_count == 1


def test_service_helper_is_fixed_scope_only_and_runtime_update_rls_stays_closed(channel):
    setup = channel.setup
    bind(channel)
    result = incoming(channel)
    assert result.status_code == 202, result.text
    ref = DeliveryReference(
        tenant_id=setup.tenant, message_id=UUID(result.json()["message_id"]), phase="received",
    )
    with channel.service.metadata(ref) as (session, message, _app):
        # Reproduce the original permissions without changing runtime policies.
        assert session.scalar(select(Binding).where(
            Binding.id == message.binding_id,
        ).with_for_update()) is None
        assert session.scalar(select(Application).where(
            Application.id == message.application_id,
        ).with_for_update()) is None
        app, account = message_binding(session, message, lock=True)
        assert app.id == message.application_id and account.id == message.binding_id
    for actor, tenant in [(setup.human, setup.tenant), (channel.app.service_principal_id, uuid4())]:
        with pytest.raises(DBAPIError) as error:
            with tenant_session(setup.engine, setup.tenant, actor_id=actor) as session:
                session.execute(text("SELECT dingtalk_lock_message_binding(:tenant,:message)"),
                                {"tenant": tenant, "message": ref.message_id})
        assert error.value.orig.sqlstate == "42501"
    with Session(setup.admin) as session:
        for role in ["pdos_next_app", "pdos_agent", "pdos_next_auth", "pdos_next_dispatch"]:
            permitted = session.scalar(text(
                "SELECT has_function_privilege(:role,"
                "'public.dingtalk_lock_message_binding(uuid,uuid)','EXECUTE')"
            ), {"role": role})
            assert permitted == (role == "pdos_next_app")
        assert session.scalar(text(
            "SELECT has_function_privilege('pdos_next_owner',"
            "'public.dingtalk_lock_message_binding(uuid,uuid)','EXECUTE')"
        ))
        assert not session.scalar(text(
            "SELECT has_schema_privilege('pdos_next_dingtalk_maintenance','public','CREATE')"
        ))
        for table in ["dingtalk_applications", "dingtalk_account_bindings"]:
            assert session.scalar(text(
                "SELECT has_column_privilege('pdos_next_dingtalk_maintenance',:table,'id','UPDATE')"
            ), {"table": table})
            assert not session.scalar(text(
                "SELECT has_column_privilege('pdos_next_dingtalk_maintenance',"
                ":table,'active','UPDATE')"
            ), {"table": table})
