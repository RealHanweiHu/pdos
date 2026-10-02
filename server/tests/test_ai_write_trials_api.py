"""Trial registration and original-draft selection over an exclusively owned test DB."""

# ruff: noqa: F811 -- shared pytest fixture injection

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, local
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Connection, select
from sqlalchemy.exc import DBAPIError

from app.contracts.ai_write_trial_protocol import CollectTrial
from app.db.schema import tables
from app.domain import ai_write_trial_protocols as trial_service
from app.domain.ai_write_trial_protocols import _digest
from tests.test_ai_meeting_draft_lifecycle import (
    DraftCase,
    draft_case,  # noqa: F401
)
from tests.test_meetings_api import (
    bearer_headers,
    client,  # noqa: F401
    isolated_meeting_database,  # noqa: F401
    scope,  # noqa: F401
)

BASE = "/api/ai/governance/write-policy/trials"


def registration(case: DraftCase, *, real: bool = False) -> dict[str, Any]:
    with case.scope.engine.connect() as c:
        draft = (
            c.execute(
                select(tables.ai_meeting_drafts).where(
                    tables.ai_meeting_drafts.c.id == case.draft_id
                )
            )
            .mappings()
            .one()
        )
    end = datetime.now(UTC) + (timedelta(hours=2) if real else timedelta())
    return {
        "request_id": str(uuid4()),
        "project_ids": [str(draft["project_id"])],
        "binding": {
            "operation_key": "meeting.minutes.draft",
            "provider": "fixed-fixture",
            "model": "simulated-model",
            "model_version": "fixture-v1",
            "release_bundle_version": "sha256:" + "a" * 64,
            "suite_version": "fixed-suite.v1",
            "suite_digest": "b" * 64,
            "adapter_version": "fixture-reader.v1",
            "policy_version": "dc11-write-policy.v1",
            "policy_revision": 1,
        },
        "evidence_kind": "real_business" if real else "synthetic",
        "window_start": (end - timedelta(hours=1)).isoformat(),
        "window_end": end.isoformat(),
        "configuration": {
            "minimum_handled_drafts": 10,
            "cohort_window_seconds": 3600,
            "minimum_followup_seconds": 1,
            "sampling_basis_points": 10000,
            "confirmation_basis": "retained_original",
            "recovery_protocol_version": "recovery.v1",
            "recovery_conditions": "异常时暂停并重新核对原依据。",
        },
        "reason": "隔离场景确认，固定模型输出不构成真实模型资格。",
    }


def post(case: DraftCase, path: str, body: dict[str, Any]) -> dict[str, Any]:
    response = case.client.post(path, headers=case.headers, json=body)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def test_registration_preregisters_policy_and_replays_without_overwriting(
    draft_case: DraftCase,
) -> None:
    case = draft_case
    body = registration(case, real=True)
    first = post(case, BASE, body)
    protocol = first["protocol"]
    assert not first["replayed"]
    assert protocol["configuration"]["minimum_confirmation_basis_points"] == 9000
    assert protocol["configuration"]["maximum_retraction_basis_points"] == 500
    assert protocol["protocol_digest"] == _digest(
        {k: v for k, v in protocol.items() if k != "protocol_digest"}
    )
    config = protocol["configuration"]
    assert config["configuration_digest"] == _digest(
        {k: v for k, v in config.items() if k != "configuration_digest"}
    )
    second = post(case, BASE, body)
    assert second == {"protocol": protocol, "replayed": True}
    changed = case.client.post(BASE, headers=case.headers, json={**body, "reason": "不同内容"})
    assert changed.status_code == 409
    invalid = registration(case)
    invalid["evidence_kind"] = "real_business"
    response = case.client.post(BASE, headers=case.headers, json=invalid)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "TRIAL_MUST_BE_PREREGISTERED"
    response = case.client.post(
        f"{BASE}/{protocol['id']}/receipts", headers=case.headers, json={"request_id": str(uuid4())}
    )
    assert response.status_code == 409
    with case.scope.engine.connect() as c:
        assert len(c.execute(select(tables.ai_write_trial_protocols)).all()) == 1
        assert c.execute(
            select(tables.events).where(tables.events.c.event_type == "AI_WRITE_TRIAL_REGISTERED")
        ).one()
    with pytest.raises(DBAPIError), case.scope.engine.begin() as c:
        c.execute(tables.ai_write_trial_protocols.update().values(protocol={}))


def test_fixed_receipts_keep_all_originals_and_preserve_previous_cutoff(
    draft_case: DraftCase,
) -> None:
    case = draft_case
    protocol = post(case, BASE, registration(case))["protocol"]
    path = f"{BASE}/{protocol['id']}/receipts"
    request = {"request_id": str(uuid4())}
    first = post(case, path, request)["receipt"]
    collection = first["collection"]
    assert collection["raw_total"] == 1
    assert collection["original_draft_ids"] == [str(case.draft_id)]
    assert collection["raw_counts"]["pending"] == 1
    assert collection["unverified_total"] == 1
    assert not collection["cohort"]["selection_complete"]
    assert not first["qualification"]["qualification_granted"]
    assert "evaluation_missing" in first["qualification"]["reasons"]
    assert first["receipt_digest"] == _digest(
        {k: v for k, v in first.items() if k != "receipt_digest"}
    )
    case.change("confirm", 0)
    second = post(case, path, {"request_id": str(uuid4())})["receipt"]
    assert second["collection"]["raw_counts"]["confirmed"] == 1
    assert second["collection"]["raw_total"] == 1
    assert post(case, path, request) == {"receipt": first, "replayed": True}
    history = case.client.get(path, headers=case.headers)
    assert history.status_code == 200
    assert history.json()["items"] == [second, first]
    assert case.client.get(f"{BASE}/{protocol['id']}", headers=case.headers).json() == protocol
    assert case.client.get(BASE, headers=case.headers).json()["items"] == [protocol]
    with pytest.raises(DBAPIError), case.scope.engine.begin() as c:
        c.execute(tables.ai_write_trial_receipts.delete())


def test_registration_enforces_actor_project_policy_and_rejects_caller_counts(
    draft_case: DraftCase,
) -> None:
    case = draft_case
    case.scope.user("trial-engineer", "engineer")
    headers = bearer_headers(case.client, username="trial-engineer")
    body = registration(case)
    assert case.client.post(BASE, headers=headers, json=body).status_code == 403
    assert case.client.get(BASE, headers=headers).status_code == 403
    assert (
        case.client.post(
            BASE, headers=case.headers, json={**body, "project_ids": [str(uuid4())]}
        ).status_code
        == 403
    )
    assert (
        case.client.post(
            BASE,
            headers=case.headers,
            json={
                **body,
                "binding": {**body["binding"], "policy_revision": 2},
            },
        ).status_code
        == 409
    )
    assert (
        case.client.post(
            BASE,
            headers=case.headers,
            json={
                **body,
                "configuration": {**body["configuration"], "minimum_confirmation_basis_points": 1},
            },
        ).status_code
        == 422
    )
    protocol = post(case, BASE, body)["protocol"]
    path = f"{BASE}/{protocol['id']}/receipts"
    assert (
        case.client.post(
            path,
            headers=case.headers,
            json={
                "request_id": str(uuid4()),
                "confirmed": 100,
            },
        ).status_code
        == 422
    )
    assert (
        case.client.post(
            path,
            headers=case.headers,
            json={
                "request_id": str(uuid4()),
                "as_of": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            },
        ).status_code
        == 409
    )
    assert case.client.get(f"{BASE}/{uuid4()}", headers=case.headers).status_code == 404


def test_concurrent_same_request_replays_from_fresh_snapshot(
    draft_case: DraftCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = draft_case
    protocol = post(case, BASE, registration(case))["protocol"]
    original = trial_service._authorize
    rendezvous, seen = Barrier(2), local()

    def authorize(c: Connection, *args: Any, write: bool, **kwargs: Any) -> None:
        if write and not getattr(seen, "started", False):
            seen.started = True
            c.execute(select(1))  # Fix both RR snapshots before either receipt exists.
            rendezvous.wait(timeout=10)
        original(c, *args, write=write, **kwargs)

    monkeypatch.setattr(trial_service, "_authorize", authorize)
    from uuid import UUID

    service = trial_service.AiWriteTrialProtocolService(case.scope.engine)
    body = CollectTrial(request_id=uuid4())

    def collect() -> dict[str, Any]:
        return service.collect(
            tenant_id=case.scope.tenant_id,
            actor_id=case.scope.owner_id,
            protocol_id=UUID(protocol["id"]),
            body=body,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(collect) for _ in range(2)]
        results = [future.result(timeout=20) for future in futures]
    assert sorted(row["replayed"] for row in results) == [False, True]
    assert results[0]["receipt"] == results[1]["receipt"]
    with case.scope.engine.connect() as c:
        assert len(c.execute(select(tables.ai_write_trial_receipts)).all()) == 1
        assert (
            len(
                c.execute(
                    select(tables.events).where(
                        tables.events.c.event_type == "AI_WRITE_TRIAL_COLLECTED"
                    )
                ).all()
            )
            == 1
        )
