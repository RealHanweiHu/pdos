"""Native T1/Run/summary/channel receipts. Root alone runs these on reviewed PG.

Official HTTPS uses only httpx.MockTransport; no inbound Message, new chat,
model skill/wallet or provider is created for delivery. All facts use native commands.
"""
# ruff: noqa: F401 -- the native business fixture dependency tree is intentionally re-exported

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace as NS
from uuid import UUID, uuid4

import pytest
from pdos_next.agent_kernel.activities import KernelActivities
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall, ValidationBudget
from pdos_next.agent_kernel.temporal_port import TemporalPort, workflow_id
from pdos_next.dingtalk.models import Delivery, Message
from pdos_next.dingtalk.summary_delivery import SummaryDeliveryService
from pdos_next.dingtalk.summary_models import SummaryDelivery
from pdos_next.dingtalk.summary_workflow import (
    DingTalkSummaryDelivery,
    SummaryActivities,
    SummarySender,
)
from pdos_next.domain.automations import service_runtime
from pdos_next.domain.automations.schemas import ZERO_MODEL_BUDGET
from pdos_next.domain.automations.service_models import AutomationServiceAttempt
from pdos_next.models import Grant, now
from pdos_next.workflows.xiaopai import XiaopaiWork
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from temporalio.client import Client
from temporalio.worker import Worker
from tests.automations_pg.test_personal_summary_pg import (
    original_security_work,
    work_case,
)
from tests.automations_pg.test_personal_summary_pg import (
    summary_work as summary_work,
)
from tests.automations_pg.test_service_automation_pg import _activate
from tests.dingtalk.test_channel_pg import channel as channel
from tests.dingtalk.test_official_pg import bind_official, protocol


@pytest.fixture
def summary_channel(summary_work, request, monkeypatch):
    setup = summary_work.setup
    wire_channel = request.getfixturevalue("channel")
    assert wire_channel.setup.tenant == setup.tenant and wire_channel.setup.human == setup.human
    wire = protocol(wire_channel)
    binding = bind_official(wire_channel)
    options = wire_channel.client.get("/v1/personal/inbox/summary-channels", headers=setup.headers)
    assert options.status_code == 200, options.text
    assert options.json()["principal_id"] == str(setup.human)
    assert options.json()["bindings"][0]["binding_id"] == binding["binding_id"]
    assert "secret" not in str(options.json()) and "external_user_id" not in str(options.json())
    spec = {
        "name": "Native summary to my verified DingTalk account",
        "goal": "Read the owner's actual registered project facts",
        "purpose": "Explicit private summary subscription",
        "stop_condition": "Finish once or retain an honest unavailable outcome",
        "trigger_kind": "schedule",
        "trigger_config": {
            "first_at": (now() - timedelta(minutes=2)).isoformat(),
            "original_timezone": "UTC",
        },
        "personal_summary": {
            "followed_project_ids": [str(summary_work.work.project_id)],
            "category_ids": [str(setup.category)],
            "groups": ["following"],
            "dingtalk_binding_id": binding["binding_id"],
        },
        "product_id": str(setup.product),
        "skill_keys": [],
        "validation_budget_id": None,
        "token_limit": 1,
        "budget": dict(ZERO_MODEL_BUDGET),
        "cooldown_seconds": 0,
        "max_runs": 2,
    }
    _rule, ref = _activate(setup, spec)
    assert service_runtime.tick(setup.engine, ref)["state"] == "active"
    with Session(setup.admin) as s:
        attempt = s.scalar(
            select(AutomationServiceAttempt).where(
                AutomationServiceAttempt.service_grant_id == UUID(ref["grant_id"]),
                AutomationServiceAttempt.state == "admitted",
            )
        )
        run = s.get(AgentRun, attempt.run_id)
        envelope = {
            "tenant_id": str(run.tenant_id),
            "category_id": str(run.category_id),
            "actor_id": str(run.writer_id),
            "requester_id": str(run.requester_id),
            "subject_id": str(run.id),
        }
    monkeypatch.setattr(setup.engine, "_pdos_agent_kernel_adapters", None, raising=False)
    monkeypatch.setattr("pdos_next.agent_kernel.activities.activity.heartbeat", lambda *_a: None)
    activity = KernelActivities(
        setup.engine,
        checkpoint_url=os.environ["PDOS_CHECKPOINT_DATABASE_URL"],
        technical_engine=setup.dispatch,
    )
    service = SummaryDeliveryService(setup.engine, setup.dispatch, runtime=wire.runtime)
    return NS(
        setup=setup,
        work=summary_work,
        channel=wire_channel,
        wire=wire,
        binding=binding,
        reference={"tenant_id": str(setup.tenant), "run_id": envelope["subject_id"]},
        envelope=envelope,
        activity=activity,
        service=service,
    )


def complete(work):
    result = work.activity.advance(work.envelope)
    assert result["status"] == "completed", result
    with Session(work.setup.admin) as s:
        run = s.get(AgentRun, UUID(work.envelope["subject_id"]))
        summary = run.result["result"]["personal_summary"]
        assert summary["groups"][0]["items"] and summary["model_used"] is False
        assert run.validation_budget_id is None and run.used_tokens == run.held_tokens == 0
    return work.service.reference(work.reference)


def body_sends(work):
    return work.wire.calls.count("/v1.0/robot/oToMessages/batchSend")


def test_actual_summary_pending_receipt_reconciles_after_revoke_without_resend(summary_channel):
    work = summary_channel
    meta = complete(work)
    before = len(work.wire.calls)
    sent = work.service.deliver(work.reference)
    assert sent["state"] == "unknown" and sent["attempts"] == 1
    assert body_sends(work) == 1
    revoked = work.channel.client.post(
        "/v1/personal/dingtalk/bindings/revoke",
        headers=work.setup.headers,
        json={
            "binding_id": work.binding["binding_id"],
            "expected_epoch": work.binding["epoch"],
            "reason": "Native local receipt recovery",
            "request_key": str(uuid4()),
        },
    )
    assert revoked.status_code == 200, revoked.text
    # A fresh service does lookup only using its original durable provider receipt.
    restarted = SummaryDeliveryService(
        work.setup.engine, work.setup.dispatch, runtime=work.wire.runtime
    )
    restored = restarted.reconcile(meta, UUID(sent["delivery_id"]))
    assert restored["state"] == "delivered" and body_sends(work) == 1
    receipts = work.channel.client.get(
        "/v1/personal/inbox/summary-deliveries", headers=work.setup.headers
    )
    assert receipts.status_code == 200 and len(receipts.json()["items"]) == 1
    with Session(work.setup.admin) as s:
        row = s.get(SummaryDelivery, UUID(sent["delivery_id"]))
        assert row.run_id == UUID(work.envelope["subject_id"])
        assert row.p26["provider"] == "dingtalk" and row.attempts == 1
        assert UUID(work.work.receipt["subject_id"]) in row.source_ids
        summary = s.get(AgentRun, row.run_id).result["result"]["personal_summary"]
        for group in summary["groups"]:
            for item in group["items"]:
                for value in (
                    item["title"],
                    item["change"]["text"],
                    item["relationship"]["text"],
                    item["next_step"]["text"],
                    item["continue_url"],
                ):
                    assert value in row.payload["text"]
        assert row.payload["target_kind"] == "direct"
        assert f"/dingtalk/runs/{row.run_id}?category={row.category_id}" in row.payload["url"]
        for model in (Message, Delivery, AgentToolCall, ValidationBudget):
            assert (
                s.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.tenant_id == work.setup.tenant)
                )
                == 0
            )
    assert len(work.wire.calls) > before


@pytest.mark.parametrize("boundary", ["binding", "application", "source"])
def test_actual_reserved_summary_rechecks_current_binding_app_and_source_before_wire(
    summary_channel,
    boundary,
):
    work = summary_channel
    meta = complete(work)
    identity = work.service.plan(meta)
    attempt = work.service.reserve(meta, identity)
    assert attempt is not None and body_sends(work) == 0
    if boundary == "binding":
        response = work.channel.client.post(
            "/v1/personal/dingtalk/bindings/revoke",
            headers=work.setup.headers,
            json={
                "binding_id": work.binding["binding_id"],
                "expected_epoch": work.binding["epoch"],
                "reason": "Native before-send withdrawal",
                "request_key": str(uuid4()),
            },
        )
        assert response.status_code == 200, response.text
    elif boundary == "application":
        app = work.channel.app
        response = work.channel.client.put(
            "/v1/dingtalk/application",
            headers=work.setup.headers,
            json={
                "expected_revision": app.revision,
                "corp_id": app.corp_id,
                "client_id": app.client_id,
                "robot_code": app.robot_code,
                "secret_arn": app.secret_arn,
                "secret_version": app.secret_version,
                "active": False,
            },
        )
        assert response.status_code == 200, response.text
    else:
        # Explicit actual authorization change, not fake source/body business history.
        with Session(work.setup.admin) as s, s.begin():
            s.execute(
                update(Grant)
                .where(
                    Grant.tenant_id == work.setup.tenant,
                    Grant.category_id == work.setup.category,
                    Grant.principal_id == work.setup.human,
                )
                .values(expires_at=now() - timedelta(seconds=1))
            )
    blocked = work.service.send_reserved(meta, identity, attempt)
    assert blocked["state"] in {"blocked", "cancelled"} and body_sends(work) == 0
    assert blocked["attempts"] == 1


@pytest.mark.skipif(
    not os.environ.get("PDOS_TEMPORAL_ADDRESS")
    or not os.environ.get("PDOS_CHECKPOINT_DATABASE_URL"),
    reason="Explicit verified local Temporal/checkpoint required",
)
def test_actual_summary_temporal_delivery_uses_original_run_and_official_mock(summary_channel):
    work = summary_channel

    async def actual():
        client = await Client.connect(
            os.environ["PDOS_TEMPORAL_ADDRESS"], namespace=os.environ["PDOS_TEMPORAL_NAMESPACE"]
        )
        native = TemporalPort(client, task_queue="summary-dingtalk-" + str(uuid4()))
        summary_activity = SummaryActivities(
            work.setup.engine, work.setup.dispatch, runtime=work.wire.runtime
        )
        sender = SummarySender(client, work.setup.dispatch, task_queue=native.task_queue)
        with ThreadPoolExecutor(max_workers=4) as executor:
            async with Worker(
                client,
                task_queue=native.task_queue,
                workflows=[XiaopaiWork, DingTalkSummaryDelivery],
                activities=[
                    work.activity.advance,
                    work.activity.reconcile,
                    summary_activity.deliver,
                ],
                activity_executor=executor,
            ):
                await native.start(work.envelope)
                result = await asyncio.wait_for(
                    client.get_workflow_handle(
                        workflow_id(work.setup.tenant, UUID(work.envelope["subject_id"]))
                    ).result(),
                    65,
                )
                assert result["status"] == "completed", result
                await sender.discover(work.setup.tenant)
                handle = client.get_workflow_handle(
                    f"pdos-next:dingtalk-summary:{work.setup.tenant}:{work.envelope['subject_id']}"
                )
                delivery = await asyncio.wait_for(handle.result(), 65)
                assert delivery["state"] == "unknown" and body_sends(work) == 1
                await sender.discover(work.setup.tenant)
                assert body_sends(work) == 1
                history = str(await handle.fetch_history())
                assert "具名登记" not in history and "synthetic-fixture-only" not in history
                response = work.channel.client.post(
                    f"/v1/personal/inbox/summary-deliveries/{delivery['delivery_id']}/reconcile",
                    headers=work.setup.headers,
                    json={},
                )
                assert response.status_code == 200 and response.json()["state"] == "delivered"
                assert body_sends(work) == 1

    asyncio.run(actual())
