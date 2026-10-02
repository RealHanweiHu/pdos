"""Human publication from AI drafts preserves domain guards and transaction receipts."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.ai import capability_contract as registry
from app.ai.capability_contract import CapabilityKey, CapabilityRollout
from app.ai.meeting_reading import source_state
from app.ai.write_policy import default_settings
from app.db.schema import tables
from app.domain.meeting_minutes import MeetingMinutesService
from app.domain.meeting_minutes_proposals import persist_minutes_proposal
from app.domain.meetings import MeetingStateError
from tests.test_meetings_api import (
    Scope,
    bearer_headers,
    client,  # noqa: F401 -- shared pytest fixture
    create_meeting,
    isolated_meeting_database,  # noqa: F401 -- shared pytest fixture
    scope,  # noqa: F401 -- shared pytest fixture
)


@dataclass
class DraftCase:
    client: TestClient
    scope: Scope
    headers: dict[str, str]
    base: str
    draft_id: UUID
    finding_id: UUID
    run_id: UUID

    def request(self, suffix: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(self.base + suffix, headers=self.headers, json=payload)
        assert response.status_code == 200, response.text
        result: dict[str, Any] = response.json()
        return result

    def change(self, action: str, revision: int, **extra: Any) -> dict[str, Any]:
        return self.request(
            f"/{self.draft_id}/actions",
            {
                "request_id": str(uuid4()),
                "expected_revision": revision,
                "action": action,
                "reason": "具名回归确认",
                **extra,
            },
        )

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        """Include formal records and event/audit receipts to detect partial commits."""
        with self.scope.engine.connect() as connection:
            return {
                table.name: [
                    dict(row)
                    for row in connection.execute(
                        select(table)
                        .where(table.c.tenant_id == self.scope.tenant_id)
                        .order_by(table.c.id)
                    ).mappings()
                ]
                for table in (
                    tables.findings,
                    tables.finding_actions,
                    tables.ai_meeting_draft_actions,
                    tables.meeting_minutes_versions,
                    tables.events,
                    tables.audit_log,
                )
            }


@pytest.fixture
def draft_case(
    client: TestClient,  # noqa: F811 -- injected shared pytest fixture
    scope: Scope,  # noqa: F811 -- injected shared pytest fixture
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[DraftCase]:
    # A process-local capability fixture and fixed output exercise persistence;
    # no provider is called and no production rollout policy is changed.
    contracts = dict(registry.CAPABILITY_CONTRACTS)
    key = CapabilityKey("knowledge_lite.meeting_minutes")
    contracts[key] = contracts[key].model_copy(update={"rollout": CapabilityRollout.LIVE})
    monkeypatch.setattr(registry, "CAPABILITY_CONTRACTS", contracts)
    project = scope.project()
    headers = bearer_headers(client)
    meeting = create_meeting(client, headers, project)
    base = f"/api/projects/{project}/meetings/{meeting['id']}"
    transcript = client.post(
        base + "/transcripts",
        headers=headers,
        json={
            "authorized_source": True,
            "content": "负责人：本周样机装配完成。",
            "segments": [{"sequence": 1, "content": "本周样机装配完成。"}],
        },
    )
    assert transcript.status_code == 201, transcript.text
    for status in ("in_progress", "completed"):
        response = client.post(base + "/status", headers=headers, json={"status": status})
        assert response.status_code == 200, response.text
    settings = {key: value.model_dump(mode="json") for key, value in default_settings().items()}
    settings["meeting.minutes.draft"]["mode"] = "confirm"
    policy = client.post(
        "/api/ai/governance/write-policy",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "expected_revision": 0,
            "mode": "tiered",
            "operation_settings": settings,
            "reason": "固定输出的隔离回归",
        },
    )
    assert policy.status_code == 200, policy.text
    base += "/ai-minutes-drafts"
    grant = client.post(
        base + "/scope",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "expected_revision": 0,
            "enabled": True,
            "reason": "仅本模拟项目",
        },
    )
    assert grant.status_code == 200, grant.text
    now, run_id, invocation_id = datetime.now(UTC), uuid4(), uuid4()
    with scope.engine.begin() as connection:
        snapshot = source_state(
            connection,
            scope.tenant_id,
            project,
            UUID(meeting["id"]),
            UUID(transcript.json()["id"]),
            include_minutes=True,
        )
        run = (
            connection.execute(
                tables.agent_runs.insert()
                .values(
                    id=run_id,
                    tenant_id=scope.tenant_id,
                    project_id=project,
                    agent_key="knowledge_lite",
                    request_id=str(uuid4()),
                    requested_by_user_id=scope.owner_id,
                    status="succeeded",
                    window_started_at=now,
                    window_ended_at=now,
                    event_count=0,
                    event_row_ids=[],
                    context_version="meeting-minutes-request-v1",
                    run_context={"reading_source": snapshot, "reading_propose_minutes": True},
                    started_at=now,
                    completed_at=now,
                )
                .returning(tables.agent_runs)
            )
            .mappings()
            .one()
        )
        connection.execute(
            tables.model_invocations.insert().values(
                id=invocation_id,
                tenant_id=scope.tenant_id,
                project_id=project,
                run_id=run_id,
                agent_key="knowledge_lite",
                prompt_version="fixture-fixed-output-v1",
                provider="openai",
                model="FIXTURE_NO_PROVIDER_CALL",
                model_version="fixture-v1",
                protocol="openai-compatible",
                status="succeeded",
            )
        )
        finding_id = persist_minutes_proposal(
            connection,
            row=run,
            snapshot=snapshot,
            output={
                "disposition": "reading",
                "claims": [
                    {
                        "text": "本周样机装配完成。",
                        "citations": [
                            {
                                "segment_id": snapshot["segments"][0]["id"],
                                "exact_quote": "本周样机装配完成。",
                            }
                        ],
                    }
                ],
                "open_questions": ["后续验证时间待确认。"],
            },
            invocation_id=invocation_id,
            created_at=now,
        )
        assert finding_id is not None
        draft_id = connection.execute(
            select(tables.ai_meeting_drafts.c.id).where(
                tables.ai_meeting_drafts.c.finding_id == finding_id
            )
        ).scalar_one()
    yield DraftCase(client, scope, headers, base, draft_id, finding_id, run_id)


def test_human_publication_links_original_finding_and_replays_once(draft_case: DraftCase) -> None:
    case = draft_case
    case.change("confirm", 0)
    confirmed = case.snapshot()
    assert confirmed["findings"][0]["status"] == "archived"
    assert confirmed["meeting_minutes_versions"] == []
    body = {
        "request_id": str(uuid4()),
        "expected_revision": 1,
        "action": "publish",
        "reason": "具名正式发布",
    }
    published = case.request(f"/{case.draft_id}/actions", body)
    before_replay = case.snapshot()
    replay = case.request(f"/{case.draft_id}/actions", body)
    assert replay["reused"] is True
    assert replay["receipt"] == published["receipt"]
    assert case.snapshot() == before_replay
    finding = before_replay["findings"][0]
    minutes = before_replay["meeting_minutes_versions"]
    assert len(minutes) == 1
    assert finding["status"] == "applied"
    assert finding["applied_entity_type"] == "meeting_minutes"
    assert finding["applied_entity_id"] == minutes[0]["id"]
    assert minutes[0]["source_finding_id"] == case.finding_id
    assert finding["reviewed_by_user_id"] == finding["applied_by_user_id"] == case.scope.owner_id
    assert finding["reviewed_at"] < finding["applied_at"]
    assert {a["action"] for a in before_replay["finding_actions"]} >= {
        "archived",
        "restored",
        "accepted",
        "applied",
    }
    result = case.request(
        f"/runs/{case.run_id}/withdraw",
        {
            "request_id": str(uuid4()),
            "reason": "核对已正式引用的整次撤回",
        },
    )
    assert result["items"][0]["result"] == "skipped"
    assert result["items"][0]["reason"] == "已被正式业务记录引用"
    assert case.snapshot()["meeting_minutes_versions"] == minutes


def test_failed_publication_rolls_back_finding_domain_and_receipts(
    draft_case: DraftCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = draft_case
    case.change("confirm", 0)
    before = case.snapshot()
    original = MeetingMinutesService.confirm

    def fail_after_domain_write(service: MeetingMinutesService, **kwargs: Any) -> dict[str, Any]:
        result = original(service, **kwargs)
        assert result["id"]
        raise MeetingStateError("模拟正式记录保存后的事务失败")

    body = {
        "request_id": str(uuid4()),
        "expected_revision": 1,
        "action": "publish",
        "reason": "确认失败后可重试",
    }
    with monkeypatch.context() as isolated_patch:
        isolated_patch.setattr(MeetingMinutesService, "confirm", fail_after_domain_write)
        failed = case.client.post(
            f"{case.base}/{case.draft_id}/actions",
            headers=case.headers,
            json=body,
        )
    assert failed.status_code == 409, failed.text
    assert "模拟正式记录保存后的事务失败" in failed.text
    assert case.snapshot() == before
    retry = case.request(f"/{case.draft_id}/actions", body)
    assert retry["reused"] is False
    assert case.snapshot()["findings"][0]["status"] == "applied"


def test_run_withdrawal_preserves_human_edited_draft(draft_case: DraftCase) -> None:
    case = draft_case
    case.change("confirm", 0)
    case.change(
        "edit",
        1,
        body="人工补充：装配完成，验证计划待定。",
        unresolved_points="验证时间待具名确定。",
    )
    before = case.snapshot()
    payload = {"request_id": str(uuid4()), "reason": "整次撤回不能覆盖人工修订"}
    result = case.request(f"/runs/{case.run_id}/withdraw", payload)
    replay = case.request(f"/runs/{case.run_id}/withdraw", payload)
    assert result["items"][0]["result"] == "skipped"
    assert result["items"][0]["reason"] == "已有人工修改"
    assert replay["items"] == result["items"]
    after = case.snapshot()
    assert after["ai_meeting_draft_actions"] == before["ai_meeting_draft_actions"]
    assert after["findings"] == before["findings"]
    assert after["meeting_minutes_versions"] == []


def test_official_minutes_record_link_preserves_history_and_scope(draft_case: DraftCase) -> None:
    case = draft_case
    case.change("confirm", 0)
    case.change("publish", 1)
    path = case.base.removesuffix("/ai-minutes-drafts") + "/minutes"
    first_response = case.client.get(path, headers=case.headers)
    assert first_response.status_code == 200, first_response.text
    first = first_response.json()["items"][0]
    newer = case.client.post(
        path,
        headers=case.headers,
        json={
            "request_id": str(uuid4()),
            "expected_version": 1,
            "body": "后续人工纪要修订，原版本保持可回查。",
            "unresolved_points": "验证时间仍待确认。",
            "reason": "核对历史版本深链",
            "citations": [
                {
                    "transcript_id": citation["transcript_id"],
                    "segment_id": citation["segment_id"],
                    "expected_digest": citation["source_digest"],
                    "exact_quote": citation["exact_quote"],
                }
                for citation in first["citations"]
            ],
        },
    )
    assert newer.status_code == 200, newer.text
    latest = case.client.get(path, headers=case.headers).json()
    assert [item["version_no"] for item in latest["items"]] == [2, 1]
    selected_response = case.client.get(
        path, headers=case.headers, params={"record_id": first["id"]}
    )
    assert selected_response.status_code == 200, selected_response.text
    selected = selected_response.json()
    assert selected["items"] == [first]
    assert selected["current_version"] == 2
    assert selected["next_before"] is None
    assert selected["sources"] == latest["sources"]
    assert selected["editable"] == latest["editable"]
    paged = case.client.get(path, headers=case.headers, params={"before_version": 2})
    assert paged.status_code == 200, paged.text
    assert paged.json()["items"] == [first]
    assert (
        case.client.get(
            path, headers=case.headers, params={"record_id": first["id"], "before_version": 2}
        ).status_code
        == 409
    )
    assert (
        case.client.get(path, headers=case.headers, params={"record_id": str(uuid4())}).status_code
        == 404
    )
    other_meeting = create_meeting(case.client, case.headers, UUID(first["project_id"]))
    other_path = f"/api/projects/{first['project_id']}/meetings/{other_meeting['id']}/minutes"
    assert (
        case.client.get(
            other_path, headers=case.headers, params={"record_id": first["id"]}
        ).status_code
        == 404
    )
    case.scope.user("outside", "engineer")
    outside_headers = bearer_headers(case.client, username="outside")
    assert (
        case.client.get(
            path, headers=outside_headers, params={"record_id": first["id"]}
        ).status_code
        == 403
    )
