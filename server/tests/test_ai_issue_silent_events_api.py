"""Committed AI/human creation through the real application and withdrawal chain."""

# ruff: noqa: F811
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url

from app.auth.repository import AuthRepository
from app.db.schema import tables
from app.db.url import psycopg_database_url
from app.domain.ai_issue_silent_events import is_silent_ai_issue_event
from app.domain.product_workspace import ProductWorkError
from app.domain.project_webhooks import insert_delivery
from app.domain.webhook_sources import SilentAICompletion, has_explicit_send, notification
from app.integrations.webhook_worker import WebhookWorker
from app.worker.dispatcher import AgentDispatcher
from tests.test_ai_issue_withdrawals_api import (
    client,  # noqa: F401
    factory_setup,  # noqa: F401
    fixture_meter,  # noqa: F401
    isolated_test_run_database,  # noqa: F401
)
from tests.test_ai_issue_withdrawals_api import (
    test_actual_withdrawal_chain as exercise_chain,
)


@pytest.mark.parametrize("kind", ["edited", "single", "reuse"])
def test_committed_silent_creation(
    client: TestClient,
    isolated_test_run_database: str,
    factory_setup: Any,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    # Reuse the actual synthetic transport -> result -> apply -> handling chain.
    exercise_chain(client, isolated_test_run_database, factory_setup, monkeypatch, kind)
    engine = create_engine(psycopg_database_url(isolated_test_run_database))
    try:
        context = AuthRepository(engine).find_login_context(tenant_slug="beepump", username="owner")
        assert context is not None
        with engine.begin() as c:
            app = c.execute(select(tables.ai_issue_applications)).mappings().one()
            e = tables.events
            event = (
                c.execute(
                    select(e).where(
                        e.c.event_type == "ISSUE_CREATED", e.c.entity_id == app["issue_id"]
                    )
                )
                .mappings()
                .one()
            )
            expected = kind != "reuse"
            assert is_silent_ai_issue_event(c, event) is expected
            assert not is_silent_ai_issue_event(c, {**event, "entity_id": uuid4()})
            assert not is_silent_ai_issue_event(c, {**event, "tenant_id": uuid4()})
            assert not is_silent_ai_issue_event(c, {**event, "event_type": "ISSUE_STATUS_CHANGED"})
            c.execute(text("SET LOCAL ROLE pdos_worker"))
            assert is_silent_ai_issue_event(c, event) is expected
            c.execute(text("RESET ROLE"))
            consumer_key = "silent_issue_real_worker"
            if expected:
                c.execute(
                    tables.agent_dispatcher_cursors.insert().values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        consumer_key=consumer_key,
                        last_event_row_id=event["id"] - 1,
                    )
                )
            now = datetime.now(UTC)
            endpoint = dict(
                id=uuid4(),
                tenant_id=context.tenant.id,
                project_id=app["project_id"],
                label="隔离静默验证",
                url="https://receiver.invalid/pdos",
                audience="internal",
                topics=["work.updated"],
                expires_at=now + timedelta(days=1),
                purpose="模拟验证，不连接外部",
                principal_user_id=context.user.id,
                principal_auth_version=context.user.auth_version,
                key_nonce=b"0" * 12,
                key_envelope=b"0" * 48,
                request_id=uuid4(),
                request_digest="a" * 64,
                auto_start_at=event["timestamp"],
                created_at=now,
            )
            c.execute(tables.webhook_endpoints.insert().values(**endpoint))
            c.execute(
                tables.webhook_controls.insert().values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    project_id=app["project_id"],
                    endpoint_id=endpoint["id"],
                    version=1,
                    status="active",
                    receiver_contract_confirmed=True,
                    delivery_authorized=True,
                    reason="隔离自动登记模拟",
                    actor_user_id=context.user.id,
                    request_id=uuid4(),
                    request_digest="b" * 64,
                    created_at=now,
                )
            )
            if expected:
                with pytest.raises(SilentAICompletion):
                    notification(c, context, endpoint, event["id"], automated=True)
            else:
                assert (
                    notification(c, context, endpoint, event["id"], automated=True)["topic"]
                    == "work.updated"
                )
            if kind == "single":
                with pytest.raises(ProductWorkError, match="原工作项不可读取"):
                    notification(c, context, endpoint, event["id"])
            else:
                basis = notification(c, context, endpoint, event["id"])
                original = insert_delivery(
                    c,
                    context,
                    endpoint,
                    basis,
                    uuid4(),
                    "c" * 64,
                    "模拟历史自动队列",
                    automated=True,
                )
                assert not has_explicit_send(c, original)
                c.execute(
                    tables.webhook_delivery_actions.insert().values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=app["project_id"],
                        delivery_id=original["id"],
                        action="retry",
                        reason="模拟具名重试回执",
                        actor_user_id=context.user.id,
                        request_id=uuid4(),
                        request_digest="d" * 64,
                        created_at=now,
                    )
                )
                assert has_explicit_send(c, original)
                manual_endpoint = {
                    **endpoint,
                    "id": uuid4(),
                    "request_id": uuid4(),
                    "auto_start_at": None,
                }
                c.execute(tables.webhook_endpoints.insert().values(**manual_endpoint))
                manual = insert_delivery(
                    c,
                    context,
                    manual_endpoint,
                    basis,
                    uuid4(),
                    "e" * 64,
                    "模拟具名发送",
                    automated=False,
                )
                assert has_explicit_send(c, manual)
        if expected:
            worker_engine = create_engine(
                make_url(psycopg_database_url(isolated_test_run_database)).set(
                    username="pdos_worker"
                )
            )
            try:
                outcome = AgentDispatcher(
                    worker_engine, batch_size=1, consumer_key=consumer_key
                ).dispatch_tenant(tenant_id=context.tenant.id)
                assert outcome.scanned_event_count == 1
                assert outcome.last_event_row_id == event["id"]
                assert outcome.routed_event_count == outcome.created_run_count == 0
            finally:
                worker_engine.dispose()
        # Dispatch registers outbox rows only; transport is never called.
        WebhookWorker(engine).dispatch()
        with engine.connect() as c:
            scan = (
                c.execute(
                    select(tables.webhook_scans).where(
                        tables.webhook_scans.c.endpoint_id == endpoint["id"],
                        tables.webhook_scans.c.source_event_id == event["id"],
                    )
                )
                .mappings()
                .one()
            )
            if expected:
                assert scan["delivery_id"] is None
                assert scan["result"] == "not_applicable_or_unavailable"
            else:
                assert scan["delivery_id"] == original["id"]
        assert WebhookWorker(engine).dispatch() == 0
    finally:
        engine.dispose()
