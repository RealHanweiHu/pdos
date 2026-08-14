from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import create_engine, func, select, text

from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.integrations.dingtalk_cards import (
    DingTalkCardCallbackError,
    DingTalkCardCallbackService,
    card_callback_signature,
)
from app.integrations.dingtalk_delivery import (
    APP_TOKEN_URL,
    APPROVAL_URL,
    CARD_CREATE_URL,
    GROUP_MESSAGE_URL,
    DingTalkDeliveryClient,
)
from app.integrations.dingtalk_outbox import (
    DingTalkIntentError,
    DingTalkIntentService,
    DingTalkOutboxProcessor,
)
from app.integrations.dingtalk_readiness import assess_dingtalk_readiness
from app.settings import Settings

SERVER_ROOT = Path(__file__).resolve().parents[1]
DATABASE_SENTINEL = "postgresql://pdos:pdos@localhost:57432/pdos_test"
JWT_SECRET = SecretStr("dingtalk-outbox-test-jwt-secret-is-at-least-32-bytes")
CLIENT_ID = "ding-delivery-client"
CLIENT_SECRET = "ding-delivery-secret"
NOW = datetime(2099, 8, 12, 20, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def isolated_database() -> Iterator[str]:
    test_url = configured_test_database_url()
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    cleanup_engine = create_engine(psycopg_database_url(test_url))
    try:
        with cleanup_engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE cehub_core.tenants CASCADE"))
    finally:
        cleanup_engine.dispose()
    command.downgrade(config, "0025_context_builder_v2")
    command.upgrade(config, "head")
    engine = create_engine(psycopg_database_url(test_url))
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE cehub_core.tenants CASCADE"))
        yield test_url
    finally:
        engine.dispose()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _settings(*, enabled: bool) -> Settings:
    return Settings(
        database_url=DATABASE_SENTINEL,
        jwt_secret=JWT_SECRET,
        dingtalk_client_id=CLIENT_ID,
        dingtalk_client_secret=SecretStr(CLIENT_SECRET),
        dingtalk_delivery_enabled=enabled,
        public_base_url="https://pdos.example",
    )


def _seed(database_url: str) -> dict[str, UUID]:
    ids = {
        "tenant": uuid4(),
        "owner": uuid4(),
        "approver": uuid4(),
        "workflow": uuid4(),
        "stage": uuid4(),
        "project": uuid4(),
        "gate": uuid4(),
        "channel": uuid4(),
    }
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert().values(
                    id=ids["tenant"], slug=f"tenant-{ids['tenant']}", name="Tenant"
                )
            )
            connection.execute(
                tables.users.insert(),
                [
                    {
                        "id": ids["owner"],
                        "tenant_id": ids["tenant"],
                        "username": "owner",
                        "display_name": "Owner",
                        "role": "owner",
                    },
                    {
                        "id": ids["approver"],
                        "tenant_id": ids["tenant"],
                        "username": "approver",
                        "display_name": "Approver",
                        "role": "quality",
                    },
                ],
            )
            connection.execute(
                tables.workflows.insert().values(
                    id=ids["workflow"],
                    tenant_id=ids["tenant"],
                    code="npd",
                    name="NPD",
                )
            )
            connection.execute(
                tables.stages.insert().values(
                    id=ids["stage"],
                    tenant_id=ids["tenant"],
                    workflow_id=ids["workflow"],
                    code="concept",
                    name="Concept",
                    sequence=1,
                )
            )
            connection.execute(
                tables.projects.insert().values(
                    id=ids["project"],
                    tenant_id=ids["tenant"],
                    workflow_id=ids["workflow"],
                    current_stage_id=ids["stage"],
                    owner_user_id=ids["owner"],
                    code="P-001",
                    name="Project 001",
                    status="active",
                )
            )
            connection.execute(
                tables.project_members.insert(),
                [
                    {
                        "id": uuid4(),
                        "tenant_id": ids["tenant"],
                        "project_id": ids["project"],
                        "user_id": user_id,
                        "added_by_user_id": ids["owner"],
                    }
                    for user_id in (ids["owner"], ids["approver"])
                ],
            )
            connection.execute(
                tables.gates.insert().values(
                    id=ids["gate"],
                    tenant_id=ids["tenant"],
                    project_id=ids["project"],
                    stage_id=ids["stage"],
                    code="G-CONCEPT",
                    name="Concept Gate",
                    status="reviewing",
                )
            )
            connection.execute(
                tables.dingtalk_tenant_bindings.insert().values(
                    tenant_id=ids["tenant"],
                    corp_id="ding-delivery-corp",
                    client_id=CLIENT_ID,
                    agent_id="12345",
                    robot_code="robot-code",
                    oauth_redirect_uri="https://pdos.example/dingtalk/callback",
                    callback_route_key="delivery-event-callback",
                    approval_process_code="approval-process",
                    card_template_id="card-template",
                    card_callback_route_key="delivery-card-callback",
                    status="active",
                    configured_by_user_id=ids["owner"],
                )
            )
            connection.execute(
                tables.dingtalk_user_bindings.insert(),
                [
                    {
                        "id": uuid4(),
                        "tenant_id": ids["tenant"],
                        "user_id": user_id,
                        "corp_id": "ding-delivery-corp",
                        "open_id": open_id,
                        "staff_id": staff_id,
                    }
                    for user_id, open_id, staff_id in (
                        (ids["owner"], "open-owner", "staff-owner"),
                        (ids["approver"], "open-approver", "staff-approver"),
                    )
                ],
            )
            connection.execute(
                tables.dingtalk_project_channels.insert().values(
                    id=ids["channel"],
                    tenant_id=ids["tenant"],
                    project_id=ids["project"],
                    open_conversation_id="open-conversation",
                    display_name="Project Group",
                    configured_by_user_id=ids["owner"],
                )
            )
    finally:
        engine.dispose()
    return ids


def _processor(
    database_url: str,
    handler: object,
) -> tuple[DingTalkOutboxProcessor, httpx2.Client]:
    client = httpx2.Client(
        transport=httpx2.MockTransport(handler),  # type: ignore[arg-type]
        follow_redirects=False,
        trust_env=False,
    )
    return (
        DingTalkOutboxProcessor(
            engine=create_engine(psycopg_database_url(database_url)),
            client=DingTalkDeliveryClient(client),
            settings=_settings(enabled=True),
            worker_id="test-worker",
        ),
        client,
    )


def test_disabled_delivery_creates_manual_intents_without_remote_calls(
    isolated_database: str,
) -> None:
    ids = _seed(isolated_database)
    service = DingTalkIntentService(
        create_engine(psycopg_database_url(isolated_database)),
        _settings(enabled=False),
    )
    group = service.enqueue_group_markdown(
        tenant_id=ids["tenant"],
        project_id=ids["project"],
        actor_user_id=ids["owner"],
        title="Gate review",
        text="Review requested",
        idempotency_key="group-manual-0001",
    )
    approval = service.enqueue_gate_approval(
        tenant_id=ids["tenant"],
        project_id=ids["project"],
        gate_id=ids["gate"],
        actor_user_id=ids["owner"],
        approver_user_id=ids["approver"],
        idempotency_key="approval-manual-0001",
    )
    card = service.enqueue_interactive_card(
        tenant_id=ids["tenant"],
        project_id=ids["project"],
        actor_user_id=ids["owner"],
        recipient_user_id=ids["approver"],
        action_key="acknowledge",
        title="Please review",
        body="Open PDOS to complete the review",
        idempotency_key="card-manual-0001",
    )
    assert {group.status, approval.outbox.status, card.outbox.status} == {"manual"}
    assert group.last_error_code == "DINGTALK_DELIVERY_DISABLED"


def test_successful_group_approval_and_card_use_server_built_payloads_and_stable_ids(
    isolated_database: str,
) -> None:
    ids = _seed(isolated_database)
    service = DingTalkIntentService(
        create_engine(psycopg_database_url(isolated_database)),
        _settings(enabled=True),
    )
    group = service.enqueue_group_markdown(
        tenant_id=ids["tenant"],
        project_id=ids["project"],
        actor_user_id=ids["owner"],
        title="Gate review",
        text="Review requested",
        idempotency_key="group-success-0001",
    )
    approval = service.enqueue_gate_approval(
        tenant_id=ids["tenant"],
        project_id=ids["project"],
        gate_id=ids["gate"],
        actor_user_id=ids["owner"],
        approver_user_id=ids["approver"],
        idempotency_key="approval-success-0001",
    )
    same_approval = service.enqueue_gate_approval(
        tenant_id=ids["tenant"],
        project_id=ids["project"],
        gate_id=ids["gate"],
        actor_user_id=ids["owner"],
        approver_user_id=ids["approver"],
        idempotency_key="approval-success-0001",
    )
    assert same_approval.id == approval.id
    card = service.enqueue_interactive_card(
        tenant_id=ids["tenant"],
        project_id=ids["project"],
        actor_user_id=ids["owner"],
        recipient_user_id=ids["approver"],
        action_key="open",
        title="Please review",
        body="Open PDOS",
        idempotency_key="card-success-0001",
    )
    seen: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        seen.append((str(request.url), body))
        if str(request.url) == APP_TOKEN_URL:
            return httpx2.Response(200, json={"accessToken": "app-token", "expireIn": 7200})
        assert request.headers["x-acs-dingtalk-access-token"] == "app-token"
        if str(request.url) == GROUP_MESSAGE_URL:
            return httpx2.Response(200, json={"processQueryKey": "group-remote-1"})
        if str(request.url) == APPROVAL_URL:
            return httpx2.Response(200, json={"instanceId": "approval-remote-1"})
        if str(request.url) == CARD_CREATE_URL:
            return httpx2.Response(200, json={"success": True})
        raise AssertionError(str(request.url))

    processor, client = _processor(isolated_database, handler)
    try:
        assert processor.process_one(now=NOW).id == group.id  # type: ignore[union-attr]
        assert processor.process_one(now=NOW).id == approval.outbox.id  # type: ignore[union-attr]
        assert processor.process_one(now=NOW).id == card.outbox.id  # type: ignore[union-attr]
    finally:
        processor._engine.dispose()
        client.close()

    approval_payload = next(body for url, body in seen if url == APPROVAL_URL)
    assert approval_payload["originatorUserId"] == "staff-owner"
    assert approval_payload["approvers"] == [{"actionType": "AND", "userIds": ["staff-approver"]}]
    assert approval_payload["formComponentValues"] == [
        {"name": "Project", "value": "P-001 · Project 001"},
        {"name": "Gate", "value": "G-CONCEPT · Concept Gate"},
        {"name": "PDOS status", "value": "reviewing"},
    ]
    card_payload = next(body for url, body in seen if url == CARD_CREATE_URL)
    assert card_payload["outTrackId"] == card.out_track_id
    assert card_payload["userId"] == "staff-approver"
    assert card_payload["callbackType"] == "HTTP"
    card_data = cast(dict[str, dict[str, str]], card_payload["cardData"])
    assert card_data["cardParamMap"]["actionPath"] == (f"/projects/{ids['project']}/gates")
    group_payload = next(body for url, body in seen if url == GROUP_MESSAGE_URL)
    group_params = json.loads(cast(str, group_payload["msgParam"]))
    assert group_params["text"].endswith(
        f"[Open PDOS](https://pdos.example/projects/{ids['project']})"
    )
    assert sum(url == APP_TOKEN_URL for url, _body in seen) == 1

    engine = create_engine(psycopg_database_url(isolated_database))
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(
                    select(tables.gates.c.status).where(tables.gates.c.id == ids["gate"])
                ).scalar_one()
                == "reviewing"
            )
            assert (
                connection.execute(
                    select(tables.dingtalk_approval_instances.c.status).where(
                        tables.dingtalk_approval_instances.c.id == approval.id
                    )
                ).scalar_one()
                == "pending"
            )
            assert (
                connection.execute(
                    select(func.count())
                    .select_from(tables.events)
                    .where(tables.events.c.event_type == "DINGTALK_NOTIFICATION_DELIVERED")
                ).scalar_one()
                == 3
            )
    finally:
        engine.dispose()


def test_readiness_is_read_only_and_fails_on_unresolved_outbox(
    isolated_database: str,
) -> None:
    ids = _seed(isolated_database)
    settings = _settings(enabled=False).model_copy(
        update={
            "dingtalk_callback_token": SecretStr("callback-token"),
            "dingtalk_callback_aes_key": SecretStr("AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"),
            "dingtalk_card_callback_secret": SecretStr("card-callback-secret"),
        }
    )
    engine = create_engine(psycopg_database_url(isolated_database))
    try:
        ready = assess_dingtalk_readiness(
            engine=engine,
            settings=settings,
            tenant_slug=f"tenant-{ids['tenant']}",
        )
        assert ready.ready
        assert next(check for check in ready.checks if check.name == "delivery_switch").passed

        with engine.begin() as connection:
            connection.execute(
                tables.integration_outbox.insert().values(
                    id=uuid4(),
                    tenant_id=ids["tenant"],
                    project_id=ids["project"],
                    operation="group_markdown",
                    idempotency_key="readiness-manual-0001",
                    payload={},
                    status="manual",
                )
            )
        blocked = assess_dingtalk_readiness(
            engine=engine,
            settings=settings,
            tenant_slug=f"tenant-{ids['tenant']}",
            require_delivery_enabled=True,
        )
        assert not blocked.ready
        assert not next(check for check in blocked.checks if check.name == "delivery_switch").passed
        assert not next(check for check in blocked.checks if check.name == "outbox_baseline").passed
    finally:
        engine.dispose()


def test_token_failure_retries_but_ambiguous_create_is_quarantined(
    isolated_database: str,
) -> None:
    ids = _seed(isolated_database)
    service = DingTalkIntentService(
        create_engine(psycopg_database_url(isolated_database)),
        _settings(enabled=True),
    )
    retry = service.enqueue_group_markdown(
        tenant_id=ids["tenant"],
        project_id=ids["project"],
        actor_user_id=ids["owner"],
        title="Retry token",
        text="No remote create happened",
        idempotency_key="group-token-retry-0001",
    )

    def token_failure(request: httpx2.Request) -> httpx2.Response:
        assert str(request.url) == APP_TOKEN_URL
        return httpx2.Response(503, json={"code": "TEMPORARY"})

    processor, client = _processor(isolated_database, token_failure)
    try:
        retried = processor.process_one(now=NOW)
    finally:
        processor._engine.dispose()
        client.close()
    assert retried is not None
    assert retried.id == retry.id
    assert retried.status == "retry_wait"

    engine = create_engine(psycopg_database_url(isolated_database))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.integration_outbox.delete().where(tables.integration_outbox.c.id == retry.id)
            )
    finally:
        engine.dispose()

    uncertain = service.enqueue_gate_approval(
        tenant_id=ids["tenant"],
        project_id=ids["project"],
        gate_id=ids["gate"],
        actor_user_id=ids["owner"],
        approver_user_id=ids["approver"],
        idempotency_key="approval-uncertain-0001",
    )

    def create_timeout(request: httpx2.Request) -> httpx2.Response:
        if str(request.url) == APP_TOKEN_URL:
            return httpx2.Response(
                200,
                json={"accessToken": "app-token", "expireIn": 7200},
            )
        assert str(request.url) == APPROVAL_URL
        return httpx2.Response(503, json={"code": "TEMPORARY"})

    processor, client = _processor(isolated_database, create_timeout)
    try:
        quarantined = processor.process_one(now=NOW)
        assert processor.process_one(now=NOW) is None
    finally:
        processor._engine.dispose()
        client.close()
    assert quarantined is not None
    assert quarantined.id == uncertain.outbox.id
    assert quarantined.status == "uncertain"
    assert quarantined.last_error_code == "DINGTALK_CREATE_OUTCOME_UNKNOWN"


def test_expired_sending_lease_is_quarantined_without_remote_resend(
    isolated_database: str,
) -> None:
    ids = _seed(isolated_database)
    service = DingTalkIntentService(
        create_engine(psycopg_database_url(isolated_database)),
        _settings(enabled=True),
    )
    approval = service.enqueue_gate_approval(
        tenant_id=ids["tenant"],
        project_id=ids["project"],
        gate_id=ids["gate"],
        actor_user_id=ids["owner"],
        approver_user_id=ids["approver"],
        idempotency_key="approval-expired-lease-0001",
    )
    engine = create_engine(psycopg_database_url(isolated_database))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.integration_outbox.update()
                .where(tables.integration_outbox.c.id == approval.outbox.id)
                .values(
                    status="sending",
                    attempt_count=1,
                    lease_owner="crashed-worker",
                    lease_expires_at=NOW,
                )
            )
            connection.execute(
                tables.dingtalk_approval_instances.update()
                .where(tables.dingtalk_approval_instances.c.id == approval.id)
                .values(status="creating")
            )
    finally:
        engine.dispose()

    calls = 0

    def must_not_call_remote(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        raise AssertionError(str(request.url))

    processor, client = _processor(isolated_database, must_not_call_remote)
    try:
        assert processor.process_one(now=NOW.replace(second=1)) is None
    finally:
        processor._engine.dispose()
        client.close()
    assert calls == 0

    engine = create_engine(psycopg_database_url(isolated_database))
    try:
        with engine.connect() as connection:
            outbox = (
                connection.execute(
                    select(tables.integration_outbox).where(
                        tables.integration_outbox.c.id == approval.outbox.id
                    )
                )
                .mappings()
                .one()
            )
            assert outbox["status"] == "uncertain"
            assert outbox["last_error_code"] == "DINGTALK_LEASE_EXPIRED_OUTCOME_UNKNOWN"
            assert (
                connection.execute(
                    select(tables.dingtalk_approval_instances.c.status).where(
                        tables.dingtalk_approval_instances.c.id == approval.id
                    )
                ).scalar_one()
                == "uncertain"
            )
    finally:
        engine.dispose()


def test_idempotency_key_reuse_with_different_payload_fails_closed(
    isolated_database: str,
) -> None:
    ids = _seed(isolated_database)
    service = DingTalkIntentService(
        create_engine(psycopg_database_url(isolated_database)),
        _settings(enabled=False),
    )
    first = service.enqueue_group_markdown(
        tenant_id=ids["tenant"],
        project_id=ids["project"],
        actor_user_id=ids["owner"],
        title="First",
        text="First payload",
        idempotency_key="group-conflict-0001",
    )
    replay = service.enqueue_group_markdown(
        tenant_id=ids["tenant"],
        project_id=ids["project"],
        actor_user_id=ids["owner"],
        title="First",
        text="First payload",
        idempotency_key="group-conflict-0001",
    )
    assert replay.id == first.id
    with pytest.raises(DingTalkIntentError, match="DINGTALK_IDEMPOTENCY_CONFLICT"):
        service.enqueue_group_markdown(
            tenant_id=ids["tenant"],
            project_id=ids["project"],
            actor_user_id=ids["owner"],
            title="Second",
            text="Changed payload",
            idempotency_key="group-conflict-0001",
        )


def test_remote_approval_sync_and_card_callback_update_only_external_evidence(
    isolated_database: str,
) -> None:
    ids = _seed(isolated_database)
    service = DingTalkIntentService(
        create_engine(psycopg_database_url(isolated_database)),
        _settings(enabled=True),
    )
    approval = service.enqueue_gate_approval(
        tenant_id=ids["tenant"],
        project_id=ids["project"],
        gate_id=ids["gate"],
        actor_user_id=ids["owner"],
        approver_user_id=ids["approver"],
        idempotency_key="approval-sync-0001",
    )
    card = service.enqueue_interactive_card(
        tenant_id=ids["tenant"],
        project_id=ids["project"],
        actor_user_id=ids["owner"],
        recipient_user_id=ids["approver"],
        action_key="acknowledge",
        title="Acknowledge",
        body="Acknowledge only",
        idempotency_key="card-callback-0001",
    )
    engine = create_engine(psycopg_database_url(isolated_database))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.integration_outbox.update()
                .where(tables.integration_outbox.c.id.in_([approval.outbox.id, card.outbox.id]))
                .values(status="succeeded", completed_at=NOW)
            )
            connection.execute(
                tables.dingtalk_approval_instances.update()
                .where(tables.dingtalk_approval_instances.c.id == approval.id)
                .values(
                    status="pending",
                    remote_instance_id="approval-remote-sync",
                    sync_requested_at=NOW,
                )
            )
            connection.execute(
                tables.dingtalk_interactive_cards.update()
                .where(tables.dingtalk_interactive_cards.c.id == card.id)
                .values(status="sent", remote_instance_id=card.out_track_id)
            )
    finally:
        engine.dispose()

    def handler(request: httpx2.Request) -> httpx2.Response:
        if str(request.url) == APP_TOKEN_URL:
            return httpx2.Response(
                200,
                json={"accessToken": "app-token", "expireIn": 7200},
            )
        assert str(request.url).startswith(APPROVAL_URL)
        assert request.url.params["processInstanceId"] == "approval-remote-sync"
        return httpx2.Response(
            200,
            json={"result": {"status": "COMPLETED", "result": "agree"}},
        )

    processor, client = _processor(isolated_database, handler)
    try:
        assert processor.sync_one_approval(now=NOW) == approval.id
    finally:
        processor._engine.dispose()
        client.close()

    card_settings = _settings(enabled=True).model_copy(
        update={"dingtalk_card_callback_secret": SecretStr("card-callback-secret")}
    )
    timestamp = str(int(NOW.timestamp() * 1000))
    signature = card_callback_signature(secret="card-callback-secret", timestamp=timestamp)
    card_service = DingTalkCardCallbackService(
        engine=create_engine(psycopg_database_url(isolated_database)),
        settings=card_settings,
    )
    payload = {
        "type": "actionCallback",
        "corpId": "ding-delivery-corp",
        "userId": "staff-approver",
        "outTrackId": card.out_track_id,
        "content": json.dumps(
            {
                "cardPrivateData": {
                    "actionIds": ["acknowledge"],
                    "params": {"action": "acknowledge"},
                }
            }
        ),
    }
    assert card_service.handle(
        route_key="delivery-card-callback",
        timestamp=timestamp,
        signature=signature,
        payload=payload,
        now=NOW,
    )
    assert card_service.handle(
        route_key="delivery-card-callback",
        timestamp=timestamp,
        signature=signature,
        payload=payload,
        now=NOW,
    )
    conflict = {**payload, "extra": "changed digest"}
    with pytest.raises(DingTalkCardCallbackError, match="DINGTALK_CARD_REPLAY_CONFLICT"):
        card_service.handle(
            route_key="delivery-card-callback",
            timestamp=timestamp,
            signature=signature,
            payload=conflict,
            now=NOW,
        )

    engine = create_engine(psycopg_database_url(isolated_database))
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(
                    select(tables.dingtalk_approval_instances.c.status).where(
                        tables.dingtalk_approval_instances.c.id == approval.id
                    )
                ).scalar_one()
                == "approved"
            )
            assert (
                connection.execute(
                    select(tables.dingtalk_interactive_cards.c.status).where(
                        tables.dingtalk_interactive_cards.c.id == card.id
                    )
                ).scalar_one()
                == "acknowledged"
            )
            assert (
                connection.execute(
                    select(tables.gates.c.status).where(tables.gates.c.id == ids["gate"])
                ).scalar_one()
                == "reviewing"
            )
            assert (
                connection.execute(
                    select(func.count())
                    .select_from(tables.events)
                    .where(
                        tables.events.c.event_type.in_(
                            ["DINGTALK_APPROVAL_UPDATED", "DINGTALK_CARD_ACTION_RECEIVED"]
                        )
                    )
                ).scalar_one()
                == 2
            )
    finally:
        engine.dispose()


def test_uncertain_delivery_requires_reconciliation_before_human_replay(
    isolated_database: str,
) -> None:
    ids = _seed(isolated_database)
    service = DingTalkIntentService(
        create_engine(psycopg_database_url(isolated_database)),
        _settings(enabled=True),
    )
    approval = service.enqueue_gate_approval(
        tenant_id=ids["tenant"],
        project_id=ids["project"],
        gate_id=ids["gate"],
        actor_user_id=ids["owner"],
        approver_user_id=ids["approver"],
        idempotency_key="approval-reconcile-0001",
    )
    group = service.enqueue_group_markdown(
        tenant_id=ids["tenant"],
        project_id=ids["project"],
        actor_user_id=ids["owner"],
        title="Reconcile delivery",
        text="Unknown remote result",
        idempotency_key="group-reconcile-0001",
    )
    engine = create_engine(psycopg_database_url(isolated_database))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.integration_outbox.update()
                .where(tables.integration_outbox.c.id.in_([approval.outbox.id, group.id]))
                .values(
                    status="uncertain",
                    attempt_count=1,
                    next_attempt_at=None,
                    last_error_code="DINGTALK_CREATE_OUTCOME_UNKNOWN",
                )
            )
            connection.execute(
                tables.dingtalk_approval_instances.update()
                .where(tables.dingtalk_approval_instances.c.id == approval.id)
                .values(status="uncertain")
            )
    finally:
        engine.dispose()

    with pytest.raises(DingTalkIntentError, match="DINGTALK_REPLAY_NOT_ALLOWED"):
        service.replay_outbox(
            tenant_id=ids["tenant"],
            outbox_id=approval.outbox.id,
            actor_user_id=ids["owner"],
            now=NOW,
        )

    not_delivered = service.reconcile_outbox(
        tenant_id=ids["tenant"],
        outbox_id=approval.outbox.id,
        actor_user_id=ids["owner"],
        outcome="confirmed_not_delivered",
        remote_reference=None,
        now=NOW,
    )
    assert not_delivered.status == "failed"
    replayed = service.replay_outbox(
        tenant_id=ids["tenant"],
        outbox_id=approval.outbox.id,
        actor_user_id=ids["owner"],
        now=NOW,
    )
    assert replayed.status == "pending"

    delivered = service.reconcile_outbox(
        tenant_id=ids["tenant"],
        outbox_id=group.id,
        actor_user_id=ids["owner"],
        outcome="confirmed_delivered",
        remote_reference="verified-remote-message",
        now=NOW,
    )
    assert delivered.status == "succeeded"
    assert delivered.remote_reference == "verified-remote-message"
    listed = service.list_outbox(
        tenant_id=ids["tenant"],
        project_id=ids["project"],
    )
    assert {record.id for record in listed} == {approval.outbox.id, group.id}

    engine = create_engine(psycopg_database_url(isolated_database))
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(
                    select(tables.dingtalk_approval_instances.c.status).where(
                        tables.dingtalk_approval_instances.c.id == approval.id
                    )
                ).scalar_one()
                == "queued"
            )
            assert (
                connection.execute(
                    select(func.count())
                    .select_from(tables.audit_log)
                    .where(
                        tables.audit_log.c.action.in_(
                            ["dingtalk.outbox.reconcile", "dingtalk.outbox.replay"]
                        )
                    )
                ).scalar_one()
                == 3
            )
    finally:
        engine.dispose()
