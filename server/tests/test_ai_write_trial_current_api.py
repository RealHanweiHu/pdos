"""Current checks are scoped reads; synthetic fixtures never confer qualification."""

# ruff: noqa: F811 -- shared pytest fixture injection
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.schema import tables
from tests.test_ai_meeting_draft_lifecycle import DraftCase, draft_case  # noqa: F401
from tests.test_ai_write_trial_preparation_api import current_body, fixture_publication, install
from tests.test_ai_write_trials_api import BASE, post
from tests.test_meetings_api import client, isolated_meeting_database, scope  # noqa: F401


def test_current_check_is_read_only_and_does_not_promote_synthetic_material(
    draft_case: DraftCase, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    case = draft_case
    body = current_body(case)
    install(
        monkeypatch,
        tmp_path / "simulated-publication.json",
        fixture_publication(case, body["binding"]),
    )
    protocol = post(case, BASE, body)["protocol"]
    original = post(case, f"{BASE}/{protocol['id']}/receipts", {"request_id": str(uuid4())})[
        "receipt"
    ]
    with case.scope.engine.connect() as c:
        counts = [
            len(c.execute(select(t)).all())
            for t in (
                tables.ai_write_trial_protocols,
                tables.ai_write_trial_receipts,
                tables.events,
                tables.audit_log,
            )
        ]
    path = f"{BASE}/{protocol['id']}/current-check"
    response = case.client.get(path, headers=case.headers)
    assert response.status_code == 200, response.text
    assert "no-store" in response.headers["cache-control"]
    result = response.json()
    assert result["runtime_matches"]
    assert result["selected_project_id"] == body["project_ids"][0]
    assert result["projects"][0]["name"]
    assert result["check"]["state"] != "current"
    assert not result["check"]["qualification_granted"]
    assert "real_business_trial_missing" in {r["code"] for r in result["check"]["reasons"]}
    assert case.client.get(path + f"?project_id={uuid4()}", headers=case.headers).status_code == 403
    assert (
        case.client.get(f"{BASE}/{uuid4()}/current-check", headers=case.headers).status_code == 404
    )
    with case.scope.engine.connect() as c:
        assert counts == [
            len(c.execute(select(t)).all())
            for t in (
                tables.ai_write_trial_protocols,
                tables.ai_write_trial_receipts,
                tables.events,
                tables.audit_log,
            )
        ]
        assert c.execute(select(tables.ai_write_trial_receipts.c.receipt)).scalar_one() == original


def test_current_check_marks_changed_runtime_without_altering_registration(
    draft_case: DraftCase,
) -> None:
    case = draft_case
    body = current_body(case)
    body["binding"]["release_bundle_version"] = "sha256:" + "e" * 64
    protocol = post(case, BASE, body)["protocol"]
    response = case.client.get(f"{BASE}/{protocol['id']}/current-check", headers=case.headers)
    assert response.status_code == 200, response.text
    assert not response.json()["runtime_matches"]
    assert response.json()["check"]["state"] == "blocked"
    assert "runtime_bundle_changed" in {r["code"] for r in response.json()["check"]["reasons"]}
    assert (
        case.client.get(f"{BASE}/{protocol['id']}", headers=case.headers).json()
        == protocol
    )
