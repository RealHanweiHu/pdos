"""Local publication fixtures exercise wiring, never certify a real provider."""

# ruff: noqa: F811 -- shared pytest fixture injection
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.ai.application_domain_context import bundle
from app.ai.observations import digest
from app.ai.write_evaluation_publication import (
    WRITE_EVALUATION_PUBLICATION_PATH,
    WRITE_EVALUATION_PUBLICATION_SHA256,
)
from app.contracts.ai_write_trial_protocol import RegisterTrial
from app.db.schema import tables
from app.domain.ai_write_trial_protocols import _digest
from tests.test_ai_meeting_draft_lifecycle import DraftCase, draft_case  # noqa: F401
from tests.test_ai_write_trials_api import BASE, post, registration
from tests.test_meetings_api import client, isolated_meeting_database, scope  # noqa: F401


def fixture_publication(case: DraftCase, binding: dict[str, Any]) -> dict[str, Any]:
    """Synthetically declared trusted records, installed only by test monkeypatch."""
    now = datetime.now(UTC)
    return {
        "version": "dc11-meeting-write-evaluation-publication.v1",
        "publication_id": str(uuid4()),
        "tenant_id": str(case.scope.tenant_id),
        "published_by": str(case.scope.owner_id),
        "actor_kind": "human",
        "actor_identity_source": "operator_verified_identity",
        "actor_identity_ref": "fixture:simulated-operator",
        "actor_identity_digest": "1" * 64,
        "published_at": (now - timedelta(minutes=30)).isoformat(),
        "valid_from": (now - timedelta(minutes=30)).isoformat(),
        "valid_until": (now + timedelta(days=30)).isoformat(),
        "evaluations": [
            {
                "evaluation": {
                    "evaluation_id": str(uuid4()),
                    "execution_source": "live_model_evaluation",
                    "evidence_ref": "fixture:not-a-real-provider-report",
                    "receipt_digest": "2" * 64,
                    "golden_publication_ref": "fixture:independent-capability-golden",
                    "golden_publication_digest": "3" * 64,
                    "binding": binding,
                    "real_provider_call": True,
                    "completed_at": (now - timedelta(hours=1)).isoformat(),
                    "outcome": "passed",
                },
                "operation_key": binding["operation_key"],
                "capability_suite_version": "meeting-minutes-independent-fixture.v1",
                "capability_suite_digest": "4" * 64,
                "golden_fixed_at": (now - timedelta(hours=3)).isoformat(),
                "golden_external_review_ref": "fixture:simulated-external-review",
                "golden_external_review_digest": "5" * 64,
                "original_calls": [
                    {
                        "invocation_id": str(uuid4()),
                        "tenant_id": str(case.scope.tenant_id),
                        "invocation_ref": "fixture:synthetically-declared-call",
                        "receipt_digest": "6" * 64,
                        "binding": binding,
                        "execution_source": "live_model_evaluation",
                        "real_provider_call": True,
                        "started_at": (now - timedelta(hours=2)).isoformat(),
                        "completed_at": (now - timedelta(hours=1)).isoformat(),
                    }
                ],
            }
        ],
    }


def install(monkeypatch: pytest.MonkeyPatch, path: Path, value: dict[str, Any]) -> str:
    data = json.dumps(value).encode()
    path.write_bytes(data)
    fingerprint = hashlib.sha256(data).hexdigest()
    monkeypatch.setenv(WRITE_EVALUATION_PUBLICATION_PATH, str(path))
    monkeypatch.setenv(WRITE_EVALUATION_PUBLICATION_SHA256, fingerprint)
    return fingerprint


def current_body(case: DraftCase) -> dict[str, Any]:
    body = registration(case)
    current = bundle("meeting_minutes")
    body["binding"].update(
        provider="minimax",
        model="fixture-model",
        model_version="fixture-v1",
        release_bundle_version="sha256:" + digest(current),
        adapter_version=current["compiled"]["reader"],
    )
    return body


def test_preparation_selects_current_published_binding_and_rechecks_on_register(
    draft_case: DraftCase,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = draft_case
    monkeypatch.delenv(WRITE_EVALUATION_PUBLICATION_PATH, raising=False)
    monkeypatch.delenv(WRITE_EVALUATION_PUBLICATION_SHA256, raising=False)
    empty = case.client.get(BASE + "/preparation", headers=case.headers)
    assert empty.status_code == 200
    assert empty.json()["candidates"] == []
    assert "尚无受信" in empty.json()["blockers"][0]
    body = current_body(case)
    publication = fixture_publication(case, body["binding"])
    path = tmp_path / "synthetic-publication.json"
    install(monkeypatch, path, publication)
    prepared = case.client.get(BASE + "/preparation", headers=case.headers).json()
    assert prepared["blockers"] == []
    assert len(prepared["candidates"]) == 1
    assert prepared["candidates"][0]["binding"] == body["binding"]
    assert [row["id"] for row in prepared["projects"]] == body["project_ids"]
    body["preparation_digest"] = prepared["candidates"][0]["key"]
    created = post(case, BASE, body)
    # A new trusted file changes preparation identity without rewriting old receipts.
    publication["publication_id"] = str(uuid4())
    install(monkeypatch, path, publication)
    changed = case.client.post(
        BASE, headers=case.headers, json={**body, "request_id": str(uuid4())}
    )
    assert changed.status_code == 409
    assert changed.json()["detail"]["code"] == "TRIAL_PREPARATION_CHANGED"
    assert post(case, BASE, body) == {"protocol": created["protocol"], "replayed": True}
    # Caller-altered binding cannot reuse a genuine prepared key.
    altered = {**body, "request_id": str(uuid4()), "binding": {**body["binding"], "model": "other"}}
    assert case.client.post(BASE, headers=case.headers, json=altered).status_code == 409


def test_collection_fixes_evaluation_publication_and_preserves_unverified_counts(
    draft_case: DraftCase,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = draft_case
    body = current_body(case)
    publication = fixture_publication(case, body["binding"])
    path = tmp_path / "synthetic-publication.json"
    fingerprint = install(monkeypatch, path, publication)
    protocol = post(case, BASE, body)["protocol"]
    request = {"request_id": str(uuid4())}
    endpoint = f"{BASE}/{protocol['id']}/receipts"
    receipt = post(case, endpoint, request)["receipt"]
    assert receipt["evaluation_publication"]["status"] == "verified"
    assert receipt["evaluation_publication"]["publication_sha256"] == fingerprint
    assert (
        receipt["evaluation"]["evaluation_id"]
        == publication["evaluations"][0]["evaluation"]["evaluation_id"]
    )
    assert "evaluation_missing" not in receipt["qualification"]["reasons"]
    assert receipt["collection"]["raw_total"] == 1
    assert receipt["collection"]["unverified_total"] == 1
    assert not receipt["qualification"]["qualification_granted"]
    assert receipt["qualification"]["status"] != "meets_candidate_criteria"
    path.write_text("invalid publication")
    later = post(case, endpoint, {"request_id": str(uuid4())})["receipt"]
    assert later["evaluation"] is None
    assert later["evaluation_publication"]["status"] == "unavailable"
    assert "evaluation_missing" in later["qualification"]["reasons"]
    assert post(case, endpoint, request) == {"receipt": receipt, "replayed": True}


def test_stale_runtime_and_legacy_request_digest_are_preserved(
    draft_case: DraftCase,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = draft_case
    body = current_body(case)
    publication = fixture_publication(case, body["binding"])
    for item in (
        publication["evaluations"][0]["evaluation"],
        publication["evaluations"][0]["original_calls"][0],
    ):
        item["binding"] = {**body["binding"], "release_bundle_version": "sha256:" + "f" * 64}
    install(monkeypatch, tmp_path / "synthetic-publication.json", publication)
    prepared = case.client.get(BASE + "/preparation", headers=case.headers).json()
    assert prepared["candidates"] == []
    assert prepared["blockers"]
    created = post(case, BASE, body)
    with case.scope.engine.connect() as c:
        stored = (
            c.execute(
                select(tables.ai_write_trial_protocols).where(
                    tables.ai_write_trial_protocols.c.request_id == body["request_id"]
                )
            )
            .mappings()
            .one()
        )
    assert stored["request_digest"] == _digest(
        RegisterTrial.model_validate(body).model_dump(
            mode="json", exclude={"request_id", "preparation_digest"}
        )
    )
    assert post(case, BASE, body) == {"protocol": created["protocol"], "replayed": True}
