"""Synthetic operator publications test verification only, never real qualification."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from app.ai.issue_business_call_publication import PATH, SHA256, originals_digest
from tests.test_ai_issue_trial_provenance import binding, codes, collect, original
from tests.test_ai_write_trial_collection import CUTOFF, TENANT, uid


def publication(row: dict[str, Any]) -> dict[str, Any]:
    return dict(
        version="issue-business-call-publication.v1",
        publication_id=uid(901),
        tenant_id=str(TENANT),
        published_by=uid(902),
        actor_kind="human",
        actor_identity_source="operator_verified_identity",
        actor_identity_ref="fixture:operator",
        actor_identity_digest="d" * 64,
        published_at=CUTOFF.isoformat(),
        valid_from=CUTOFF.isoformat(),
        valid_until=CUTOFF.replace(year=CUTOFF.year + 1).isoformat(),
        calls=[
            dict(
                project_id=row["run"]["project_id"],
                run_id=row["run"]["id"],
                invocation_id=row["call"]["id"],
                binding=binding(row).model_dump(mode="json"),
                execution_source="real_business",
                originals_digest=originals_digest(row),
                provider_receipt_ref="fixture:external-receipt",
                provider_receipt_digest="e" * 64,
                completed_at=row["result"]["created_at"],
            )
        ],
    )


def install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, document: dict[str, Any]) -> None:
    body = json.dumps(document).encode()
    path = tmp_path / "synthetic-business-calls.json"
    path.write_bytes(body)
    monkeypatch.setenv(PATH, str(path))
    monkeypatch.setenv(SHA256, sha256(body).hexdigest())


def test_exact_operator_originals_verify_provider_without_changing_cohort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = original()
    install(tmp_path, monkeypatch, publication(row))
    result = collect([row])
    assert result["provider_verified"] and result["provenance_verified"]
    assert codes(result) == set()
    assert UUID(result["provider_evidence"]["invocation_id"]) == UUID(row["call"]["id"])
    changed = deepcopy(row)
    changed["call"]["total_tokens"] += 1
    assert not collect([changed])["provider_verified"]


@pytest.mark.parametrize(
    "change",
    [
        "pin",
        "tenant",
        "expired",
        "run",
        "project",
        "invocation",
        "digest",
        "binding",
        "duplicate",
        "synthetic",
    ],
)
def test_wrong_originals_cannot_verify_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    row = original()
    doc = publication(row)
    call = doc["calls"][0]
    if change == "tenant":
        doc["tenant_id"] = uid(999)
    elif change == "expired":
        doc["valid_until"] = CUTOFF.isoformat()
    elif change in {"run", "project", "invocation"}:
        call[change + "_id"] = uid(999)
    elif change == "digest":
        call["originals_digest"] = "0" * 64
    elif change == "binding":
        call["binding"]["policy_revision"] += 1
    elif change == "duplicate":
        doc["calls"].append(deepcopy(call))
    elif change == "synthetic":
        call["execution_source"] = "synthetic"
    install(tmp_path, monkeypatch, doc)
    if change == "pin":
        monkeypatch.setenv(SHA256, "0" * 64)
    result = collect([row])
    assert result["provenance_verified"] and not result["provider_verified"]
    assert "provider_unverified" in codes(result)
