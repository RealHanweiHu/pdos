"""Isolated durable meeting events with actual budgets and synthetic model transport."""

# ruff: noqa: F811
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.ai import capability_contract as registry
from app.ai.application_gateway import configured_application_gateway
from app.ai.capability_contract import CapabilityKey, CapabilityRollout
from app.ai.meeting_event_queue import MeetingEventQueue
from app.ai.write_policy import default_settings
from app.db.schema import tables
from app.domain.meetings import MeetingService
from tests import test_application_budget_factory as factory
from tests.test_application_budget_factory import factory_setup  # noqa: F401
from tests.test_input_metering import publication
from tests.test_meetings_api import (
    Scope,
    bearer_headers,
    client,  # noqa: F401
    create_meeting,
    isolated_meeting_database,  # noqa: F401
    scope,  # noqa: F401
)
from tests.test_model_budget_controller import response


@dataclass
class EventCase:
    client: TestClient
    scope: Scope
    headers: dict[str, str]
    base: str
    kind: str


@pytest.fixture(params=("minutes", "actions", "decisions"))
def event_case(
    client: TestClient,
    scope: Scope,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> EventCase:
    # Only actual HTTP business setup: no fabricated legacy run or model usage.
    kind = str(request.param)
    contracts = dict(registry.CAPABILITY_CONTRACTS)
    for name in ("meeting_reading", f"meeting_{kind}"):
        key = CapabilityKey(f"knowledge_lite.{name}")
        contracts[key] = contracts[key].model_copy(update={"rollout": CapabilityRollout.LIVE})
    monkeypatch.setattr(registry, "CAPABILITY_CONTRACTS", contracts)
    project = scope.project()
    headers = bearer_headers(client)
    meeting = create_meeting(client, headers, project)
    base = f"/api/projects/{project}/meetings/{meeting['id']}"
    for status in ("in_progress", "completed"):
        changed = client.post(base + "/status", headers=headers, json={"status": status})
        assert changed.status_code == 200, changed.text
    settings = {key: value.model_dump(mode="json") for key, value in default_settings().items()}
    settings[f"meeting.{kind}.draft"]["mode"] = "confirm"
    policy = client.post(
        "/api/ai/governance/write-policy",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "expected_revision": 0,
            "mode": "tiered",
            "operation_settings": settings,
            "reason": "隔离会后事件模拟初始政策",
        },
    )
    assert policy.status_code == 200, policy.text
    base += "/ai-minutes-drafts"
    grant = client.post(
        base + f"/scope?kind={kind}",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "expected_revision": 0,
            "enabled": True,
            "reason": "仅本隔离模拟项目与草稿类型",
        },
    )
    assert grant.status_code == 200, grant.text
    return EventCase(client, scope, headers, base, kind)


@pytest.fixture(autouse=True)
def large_fixture_meter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        factory, "publication", lambda path: publication(path, qualified_input_limit=6000)
    )


def auto_policy(case: EventCase, *, revision: int = 1, enabled: bool = True) -> None:
    settings = {key: value.model_dump(mode="json") for key, value in default_settings().items()}
    settings[f"meeting.{case.kind}.draft"]["mode"] = "automatic" if enabled else "disabled"
    r = case.client.post(
        "/api/ai/governance/write-policy",
        headers=case.headers,
        json={
            "request_id": str(uuid4()),
            "expected_revision": revision,
            "mode": "tiered",
            "operation_settings": settings,
            "reason": "隔离事件队列模拟",
        },
    )
    assert r.status_code == 200, r.text


def source(
    case: EventCase, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], dict[str, Any]]:
    contracts = dict(registry.CAPABILITY_CONTRACTS)
    key = CapabilityKey("knowledge_lite.meeting_reading")
    contracts[key] = contracts[key].model_copy(update={"rollout": CapabilityRollout.LIVE})
    monkeypatch.setattr(registry, "CAPABILITY_CONTRACTS", contracts)
    auto_policy(case)
    content = {
        "minutes": "【事件模拟】样机验证已完成。",
        "actions": "【事件模拟】安排下一轮样机验证，责任与日期待确认。",
        "decisions": "【事件模拟】讨论选择方案A或方案B，尚未决定。",
    }[case.kind]
    r = case.client.post(
        case.base.removesuffix("/ai-minutes-drafts") + "/transcripts",
        headers=case.headers,
        json={
            "authorized_source": True,
            "content": content,
            "segments": [{"sequence": 1, "content": content}],
        },
    )
    assert r.status_code == 201, r.text
    with case.scope.engine.connect() as c:
        event = dict(
            c.execute(
                select(tables.events)
                .where(tables.events.c.event_type == "MEETING_STATE_CHANGED")
                .order_by(tables.events.c.id.desc())
                .limit(1)
            )
            .mappings()
            .one()
        )
        segment = (
            c.execute(
                select(tables.meeting_transcript_segments).where(
                    tables.meeting_transcript_segments.c.transcript_id == UUID(r.json()["id"])
                )
            )
            .mappings()
            .one()
        )
        output = {
            "disposition": "reading",
            "claims": [
                {
                    "text": "样机验证已完成。",
                    "citations": [
                        {"segment_id": str(segment["id"]), "exact_quote": segment["content"]}
                    ],
                }
            ],
            "open_questions": ["后续验证计划未提供。"],
        }
    citation = {"segment_id": str(segment["id"]), "exact_quote": segment["content"]}
    if case.kind == "actions":
        output = {
            "disposition": "actions",
            "actions": [
                {
                    "title": "安排下一轮样机验证",
                    "description": content,
                    "owner_text": None,
                    "date_text": None,
                    "expected_output": None,
                    "citations": [citation],
                }
            ],
            "open_questions": ["责任与日期待确认。"],
        }
    elif case.kind == "decisions":
        output = {
            "disposition": "decisions",
            "decisions": [
                {
                    "title": "方案选择待决",
                    "context": content,
                    "options": ["方案A", "方案B"],
                    "trade_offs": None,
                    "outcome": None,
                    "rationale": None,
                    "consequence": None,
                    "citations": [citation],
                }
            ],
            "open_questions": ["批准人与最终结论待确认。"],
        }
    monkeypatch.setattr(
        factory, "response", lambda: response(json.dumps(output, ensure_ascii=False))
    )
    return event, r.json()


def test_event_queue_budget_execution_and_history_are_idempotent(
    event_case: EventCase,
    factory_setup: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = event_case
    event, transcript = source(case, monkeypatch)
    environment, calls, _ = factory_setup
    with configured_application_gateway(case.scope.engine, environment) as gateway:
        q = MeetingEventQueue(case.scope.engine, gateway)
        first = q.dispatch_once()
        assert first.queued_count == 1, first
        assert calls == []
        assert q.dispatch_once().scanned_event_count == 0
        with case.scope.engine.connect() as c:
            receipt = (
                c.execute(
                    select(tables.ai_meeting_event_receipts).where(
                        tables.ai_meeting_event_receipts.c.status == "queued"
                    )
                )
                .mappings()
                .one()
            )
            run_id = receipt["run_id"]
            assert (
                c.execute(
                    select(tables.application_authorizations).where(
                        tables.application_authorizations.c.run_id == run_id
                    )
                ).first()
                is not None
            )
            assert (
                c.execute(
                    select(tables.budget_run_links).where(
                        tables.budget_run_links.c.run_id == run_id
                    )
                ).first()
                is not None
            )
        assert q.execute_next()
        with case.scope.engine.connect() as c:
            run = (
                c.execute(select(tables.agent_runs).where(tables.agent_runs.c.id == run_id))
                .mappings()
                .one()
            )
            assert run["status"] == "succeeded", run["error_code"]
            draft = (
                c.execute(
                    select(tables.ai_meeting_drafts).where(
                        tables.ai_meeting_drafts.c.run_id == run_id
                    )
                )
                .mappings()
                .one()
            )
            assert (
                draft["capture_mode"] == "trial"
            )  # Synthetic wire does not grant direct qualification.
            assert draft["principal_id"] == receipt["principal_id"]
            assert draft["draft_kind"] == case.kind
            assert run["event_count"] == 0 and run["event_row_ids"] == []
            assert (
                c.execute(
                    select(tables.budget_journal.c.id).where(
                        tables.budget_journal.c.run_id == run_id,
                        tables.budget_journal.c.reservation_status == "settled",
                    )
                ).first()
                is not None
            )
            assert run["run_context"]["reading_event_trigger"]["event_row_id"] == event["id"]
        assert len(calls) == 1
        assert not q.execute_next()
        # Another original event referencing identical current source reuses this run.
        with case.scope.engine.begin() as c:
            original = MeetingService._get(
                c,
                tenant_id=event["tenant_id"],
                project_id=event["project_id"],
                meeting_id=event["entity_id"],
            )
            from datetime import UTC, datetime

            MeetingService._emit(
                c,
                tenant_id=event["tenant_id"],
                actor_user_id=case.scope.owner_id,
                record=original,
                action="transcript_original_restored",
                before=original,
                occurred_at=datetime.now(UTC),
                audit_context={
                    "transcript_id": transcript["id"],
                    "source_authorized": True,
                    "content_digest": transcript["content_digest"],
                },
            )
        assert q.dispatch_once().reused_count == 1
        assert not q.execute_next() and len(calls) == 1
    drafts = case.client.get(case.base, params={"kind": case.kind}, headers=case.headers)
    assert drafts.status_code == 200, drafts.text
    assert any(item["id"] == str(draft["id"]) for item in drafts.json()["items"])
    history = case.client.get(
        case.base.removesuffix("ai-minutes-drafts") + "ai-event-history", headers=case.headers
    )
    assert history.status_code == 200, history.text
    assert any(i["run"] and i["run"]["status"] == "succeeded" for i in history.json()["items"])


def test_revoked_automatic_policy_stops_queued_event_before_transport(
    event_case: EventCase,
    factory_setup: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = event_case
    source(case, monkeypatch)
    environment, calls, _ = factory_setup
    with configured_application_gateway(case.scope.engine, environment) as gateway:
        q = MeetingEventQueue(case.scope.engine, gateway)
        assert q.dispatch_once().queued_count == 1
        auto_policy(case, revision=2, enabled=False)
        assert q.execute_next()
        assert calls == []
        with case.scope.engine.connect() as c:
            stopped = (
                c.execute(
                    select(tables.agent_runs).where(
                        tables.agent_runs.c.run_context["reading_event_trigger"].is_not(None),
                        tables.agent_runs.c.status == "failed",
                    )
                )
                .mappings()
                .one()
            )
            assert stopped["error_code"] == "MEETING_EVENT_AUTHORITY_CHANGED"
        assert not q.execute_next()
