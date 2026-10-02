"""Isolated synthetic qualification exercises direct persistence, never real rollout."""

# ruff: noqa: F811 -- shared pytest fixture injection
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.ai.write_policy import default_settings
from app.db.schema import tables
from app.domain import ai_meeting_direct_route as route
from app.domain.ai_meeting_drafts import capture_minutes_draft
from app.domain.ai_write_qualification_state import QualificationState
from app.domain.findings import FindingService
from app.domain.meeting_minutes_proposals import MeetingMinutesPayload, persist_minutes_proposal
from app.events.writer import EventAuditWriter
from tests.test_ai_meeting_draft_lifecycle import DraftCase, draft_case  # noqa: F401
from tests.test_ai_write_qualification_contract import binding, configuration
from tests.test_meetings_api import client, isolated_meeting_database, scope  # noqa: F401


def automatic(case: DraftCase, monkeypatch: pytest.MonkeyPatch, *, sampled: bool) -> None:
    settings = {key: value.model_dump(mode="json") for key, value in default_settings().items()}
    settings["meeting.minutes.draft"]["mode"] = "automatic"
    response = case.client.post(
        "/api/ai/governance/write-policy",
        headers=case.headers,
        json={
            "request_id": str(uuid4()),
            "expected_revision": 1,
            "mode": "tiered",
            "operation_settings": settings,
            "reason": "隔离模拟资格，仅验证direct路径",
        },
    )
    assert response.status_code == 200, response.text

    def synthetic_readiness(c: Any, *, draft: dict[str, Any], as_of: datetime) -> dict[str, Any]:
        state = QualificationState(
            state="current",
            checked_at=as_of,
            tenant_id=draft["tenant_id"],
            project_id=draft["project_id"],
            operation_key="meeting.minutes.draft",
            binding=binding(policy_revision=2),
            policy_id=draft["policy_id"],
            configuration=configuration(sampling_basis_points=10000),
        )
        return {
            "state": "current",
            "qualification_state": state.model_dump(mode="json"),
            "binding": state.binding.model_dump(mode="json"),
            "reasons": [],
        }

    monkeypatch.setattr(route, "assess_generated_write", synthetic_readiness)
    monkeypatch.setattr(route, "sampled_draft", lambda draft_id, config: sampled)


def generate(case: DraftCase) -> tuple[dict[str, Any], dict[str, Any]]:
    with case.scope.engine.begin() as c:
        prior = (
            c.execute(
                select(tables.ai_meeting_drafts).where(
                    tables.ai_meeting_drafts.c.id == case.draft_id
                )
            )
            .mappings()
            .one()
        )
        source_run = (
            c.execute(select(tables.agent_runs).where(tables.agent_runs.c.id == case.run_id))
            .mappings()
            .one()
        )
        call = dict(
            c.execute(
                select(tables.model_invocations).where(
                    tables.model_invocations.c.id == prior["model_invocation_id"]
                )
            )
            .mappings()
            .one()
        )
        now = datetime.now(UTC)
        run_values = {
            **dict(source_run),
            "id": uuid4(),
            "request_id": str(uuid4()),
            "created_at": now,
            "window_started_at": now,
            "window_ended_at": now,
            "started_at": now,
            "completed_at": now,
        }
        run = (
            c.execute(tables.agent_runs.insert().values(**run_values).returning(tables.agent_runs))
            .mappings()
            .one()
        )
        call.update(id=uuid4(), run_id=run["id"], created_at=now)
        c.execute(tables.model_invocations.insert().values(**call))
        payload = MeetingMinutesPayload.model_validate(prior["payload"])
        finding = persist_minutes_proposal(
            c,
            row=run,
            snapshot=prior["source_snapshot"],
            output={
                "disposition": "reading",
                "claims": [
                    {
                        "text": payload.body,
                        "citations": [q.model_dump(mode="json") for q in payload.citations],
                    }
                ],
                "open_questions": [payload.unresolved_points],
            },
            invocation_id=call["id"],
            created_at=now,
        )
        draft = dict(
            c.execute(
                select(tables.ai_meeting_drafts).where(
                    tables.ai_meeting_drafts.c.finding_id == finding
                )
            )
            .mappings()
            .one()
        )
        repeated = capture_minutes_draft(
            c,
            row=run,
            finding_id=finding,
            payload=payload,
            snapshot=prior["source_snapshot"],
            invocation_id=call["id"],
            now=now,
        )
        assert repeated == draft["id"]
        return draft, dict(run)


def pending(case: DraftCase) -> set[UUID]:
    return {
        record.id
        for record in FindingService(case.scope.engine).list(
            tenant_id=case.scope.tenant_id,
            status="pending_review",
            actor_user_id=case.scope.owner_id,
        )
    }


def test_direct_silent_withdrawal_latches_stop_and_next_capture_falls_back(
    draft_case: DraftCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = draft_case
    automatic(case, monkeypatch, sampled=False)
    first, run = generate(case)
    assert first["capture_mode"] == "direct"
    assert first["write_receipt"]["sampled"] is False
    assert first["finding_id"] not in pending(case)
    item = next(
        item
        for item in case.client.get(case.base, headers=case.headers).json()["items"]
        if item["id"] == str(first["id"])
    )
    assert item["state"] == "active" and not item["review_required"]
    change = {
        "request_id": str(uuid4()),
        "expected_revision": 0,
        "action": "withdraw",
        "reason": "模拟直接草稿撤回",
    }
    response = case.request(f"/{first['id']}/actions", change)
    assert not response["reused"]
    assert case.request(f"/{first['id']}/actions", change)["reused"]
    with case.scope.engine.connect() as c:
        stop = c.execute(select(tables.ai_write_runtime_stops)).mappings().one()
        assert stop["receipt"]["generated"] == stop["receipt"]["withdrawn"] == 1
        assert (
            c.execute(
                select(tables.events).where(
                    tables.events.c.event_type == "AI_WRITE_AUTOMATIC_STOPPED"
                )
            )
            .mappings()
            .one()
        )
    second, _ = generate(case)
    assert second["capture_mode"] == "trial"
    assert second["write_receipt"]["reason"] == "quality_stop"
    assert second["finding_id"] in pending(case)
    with case.scope.engine.connect() as c:
        assert len(c.execute(select(tables.ai_write_runtime_stops)).all()) == 1
        assert (
            c.execute(
                select(tables.ai_meeting_drafts.c.write_receipt).where(
                    tables.ai_meeting_drafts.c.id == first["id"]
                )
            ).scalar_one()
            == first["write_receipt"]
        )


def test_direct_sample_confirmation_and_formal_publication_remain_named(
    draft_case: DraftCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = draft_case
    automatic(case, monkeypatch, sampled=True)
    first, _ = generate(case)
    assert first["finding_id"] in pending(case)
    item = next(
        item
        for item in case.client.get(case.base, headers=case.headers).json()["items"]
        if item["id"] == str(first["id"])
    )
    assert item["review_required"] and item["state"] == "active"
    confirm = {
        "request_id": str(uuid4()),
        "expected_revision": 0,
        "action": "confirm",
        "reason": "模拟抽检确认",
    }
    case.request(f"/{first['id']}/actions", confirm)
    assert first["finding_id"] not in pending(case)
    publication = case.request(
        f"/{first['id']}/actions",
        {
            "request_id": str(uuid4()),
            "expected_revision": 1,
            "action": "publish",
            "reason": "负责人正式发布",
        },
    )
    assert publication["receipt"]["actor_user_id"] == str(case.scope.owner_id)
    with case.scope.engine.connect() as c:
        assert (
            c.execute(select(tables.meeting_minutes_versions.c.source_finding_id)).scalar_one()
            == first["finding_id"]
        )


def test_failed_stop_receipt_rolls_back_withdrawal_and_can_retry(
    draft_case: DraftCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = draft_case
    automatic(case, monkeypatch, sampled=False)
    first, _ = generate(case)
    before = case.snapshot()
    original = EventAuditWriter.record

    def fail_stop(self: Any, event: Any, audit: Any) -> Any:
        result = original(self, event, audit)
        if event.event_type == "AI_WRITE_AUTOMATIC_STOPPED":
            raise RuntimeError("simulated stop receipt failure")
        return result

    monkeypatch.setattr(EventAuditWriter, "record", fail_stop)
    change = {
        "request_id": str(uuid4()),
        "expected_revision": 0,
        "action": "withdraw",
        "reason": "模拟暂停回执失败后重试",
    }
    with pytest.raises(RuntimeError, match="simulated stop receipt failure"):
        case.request(f"/{first['id']}/actions", change)
    assert case.snapshot() == before
    with case.scope.engine.connect() as c:
        assert not c.execute(select(tables.ai_write_runtime_stops)).all()
    monkeypatch.setattr(EventAuditWriter, "record", original)
    assert not case.request(f"/{first['id']}/actions", change)["reused"]
    with case.scope.engine.connect() as c:
        assert len(c.execute(select(tables.ai_write_runtime_stops)).all()) == 1
