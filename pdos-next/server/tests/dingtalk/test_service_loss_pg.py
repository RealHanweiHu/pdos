"""Root-run actual service-loss fence/UOW rollback; no real channel or model."""
# ruff: noqa: F401,F811 -- exact native PG fixture tree

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from copy import deepcopy
from threading import Event
from uuid import UUID

import pytest
from pdos_next import models
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall
from pdos_next.dingtalk.models import Application, Delivery, Message
from pdos_next.dingtalk.runtime import ChannelService, delivery_key
from pdos_next.dingtalk.workflow import ChannelActivities
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from tests.dingtalk.test_channel_pg import bind, channel, incoming


def test_actual_service_loss_after_reserve_and_app_lock_wait_cancels_without_second_send(
    channel,
    monkeypatch,
):
    setup = channel.setup
    bind(channel)
    admitted = incoming(channel)
    assert admitted.status_code == 202, admitted.text
    reference = {"tenant_id": str(setup.tenant), "message_id": admitted.json()["message_id"]}
    message_id, run_id = UUID(reference["message_id"]), UUID(admitted.json()["run_id"])
    reserved, proceed, locking = Event(), Event(), Event()
    original = ChannelService.send_reserved
    denied = []

    def pause_before_send(service, ref, delivery_id, attempt_id):
        assert ref.message_id == message_id
        reserved.set()  # The real reserve UOW has already committed sending/P26.
        assert proceed.wait(10), "Root-run test did not release the original send path"
        return original(service, ref, delivery_id, attempt_id)

    def observe(_connection, _cursor, statement, *_args):
        if reserved.is_set() and "SELECT dingtalk_lock_message_binding(" in statement:
            locking.set()

    def error(context):
        if "dingtalk_lock_message_binding(" in (context.statement or ""):
            denied.append(
                (
                    getattr(context.original_exception, "sqlstate", None),
                    getattr(
                        getattr(context.original_exception, "diag", None), "message_primary", None
                    ),
                )
            )

    monkeypatch.setattr(ChannelService, "send_reserved", pause_before_send)
    event.listen(setup.engine, "before_cursor_execute", observe)
    event.listen(setup.engine, "handle_error", error)
    activities = ChannelActivities(setup.engine, setup.dispatch, None, runtime=channel.runtime)
    try:
        with ThreadPoolExecutor(1) as pool:
            completed = pool.submit(activities.deliver, reference)
            try:
                assert reserved.wait(10), "Original graph never committed a real reservation"
                with Session(setup.admin) as session, session.begin():
                    application = session.scalar(
                        select(Application)
                        .where(
                            Application.id == channel.app.id,
                        )
                        .with_for_update()
                    )
                    assert application.active and application.service_principal_id == setup.agent
                    before = session.scalar(
                        select(Delivery).where(
                            Delivery.request_key == delivery_key(message_id, "received"),
                        )
                    )
                    assert before.state == "sending" and before.attempts == 1 and before.p26
                    fixed = {
                        key: deepcopy(getattr(before, key))
                        for key in (
                            "id",
                            "state",
                            "attempts",
                            "attempt_id",
                            "payload_sha256",
                            "p26",
                        )
                    }
                    proceed.set()
                    assert locking.wait(5), "The actual helper was not called before transport"
                    with pytest.raises(FutureTimeout):
                        completed.result(timeout=0.2)
                    # This is solely revocation of the existing synthetic service
                    # Principal authorization fixture. All app/binding/message/run/
                    # delivery business history above is from native API/graph UOWs.
                    session.get(models.Principal, setup.agent).active = False
                result = completed.result(timeout=10)
            finally:
                proceed.set()
    finally:
        proceed.set()
        event.remove(setup.engine, "before_cursor_execute", observe)
        event.remove(setup.engine, "handle_error", error)
    assert denied == [("42501", "DingTalk service binding required")]
    assert result == {"state": "cancelled", "error_code": "CANCELLED_RUN"}
    assert channel.runtime.adapter.send_count == channel.runtime.adapter.lookup_count == 0
    with Session(setup.admin) as session:
        assert session.get(Application, channel.app.id).active
        message, run = session.get(Message, message_id), session.get(AgentRun, run_id)
        assert message.state == run.state == "cancelled" and run.error_code == "CANCELLED_RUN"
        assert run.cancel_epoch == 1
        journal = session.get(Delivery, fixed["id"])
        assert {key: getattr(journal, key) for key in fixed} == fixed
        assert journal.provider_receipt is None  # No fabricated delivered/unknown receipt.
        assert (
            session.scalar(select(AgentToolCall.id).where(AgentToolCall.run_id == run_id)) is None
        )
    # Existing dispatcher proof remains idempotent. No automatic resend of this
    # committed sending/unknown journal is introduced by the SQL-error branch.
    assert activities.deliver(reference)["state"] == "cancelled"
    with Session(setup.admin) as session:
        assert session.get(AgentRun, run_id).cancel_epoch == 1
        assert session.get(Delivery, fixed["id"]).attempts == 1
    assert channel.runtime.adapter.send_count == channel.runtime.adapter.lookup_count == 0
