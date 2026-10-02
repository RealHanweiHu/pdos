"""Synthetic temporary-file fixtures only; no real evaluation is published."""

from __future__ import annotations

import json
import socket
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from app.ai.issue_evaluation_publication import (
    ISSUE_EVALUATION_PUBLICATION_PATH,
    ISSUE_EVALUATION_PUBLICATION_SHA256,
    WriteEvaluationPublicationError,
    configured_issue_evaluation,
    configured_issue_evaluation_publication,
    select_issue_evaluation,
)
from app.ai.write_evaluation_publication import MAX_PUBLICATION_BYTES
from app.contracts.ai_issue_evaluation import IssueEvaluationBinding

TENANT = UUID(int=1)
NOW = datetime(2026, 9, 27, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_external_access(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("publication unit tests must never access network, SQL or a model")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def fixture_document() -> dict[str, Any]:
    """Reusable synthetic publication structure, never real qualification evidence."""
    binding = {
        "operation_key": "event.issue.create",
        "provider": "openai",
        "model": "fixture-model",
        "model_version": "fixture-revision-1",
        "release_bundle_version": "sha256:" + "a" * 64,
        "suite_version": "gateway-admission.fixture.v1",
        "suite_digest": "b" * 64,
        "adapter_version": "event-issue.fixture.v1",
        "policy_version": "dc11.fixture.v1",
        "policy_revision": 1,
    }
    return {
        "version": "dc11-issue-write-evaluation-publication.v1",
        "publication_id": str(UUID(int=2)),
        "tenant_id": str(TENANT),
        "published_by": str(UUID(int=3)),
        "actor_kind": "human",
        "actor_identity_source": "operator_verified_identity",
        "actor_identity_ref": "fixture-only:identity",
        "actor_identity_digest": "c" * 64,
        "published_at": (NOW - timedelta(hours=1)).isoformat(),
        "valid_from": NOW.isoformat(),
        "valid_until": (NOW + timedelta(days=1)).isoformat(),
        "evaluations": [
            {
                "evaluation": {
                    "evaluation_id": str(UUID(int=4)),
                    "execution_source": "live_model_evaluation",
                    "evidence_ref": "fixture-only:evaluation-report",
                    "receipt_digest": "d" * 64,
                    "golden_publication_ref": "fixture-only:independent-golden",
                    "golden_publication_digest": "e" * 64,
                    "binding": binding,
                    "real_provider_call": True,
                    "completed_at": (NOW - timedelta(hours=2)).isoformat(),
                    "outcome": "failed",
                },
                "operation_key": "event.issue.create",
                "capability_suite_version": "independent-event-issue.fixture.v1",
                "capability_suite_digest": "f" * 64,
                "golden_fixed_at": (NOW - timedelta(days=2)).isoformat(),
                "golden_external_review_ref": "fixture-only:human-original-review",
                "golden_external_review_digest": "1" * 64,
                "original_calls": [
                    {
                        "invocation_id": str(UUID(int=5)),
                        "tenant_id": str(TENANT),
                        "invocation_ref": "fixture-only:original-provider-call",
                        "receipt_digest": "2" * 64,
                        "binding": deepcopy(binding),
                        "execution_source": "live_model_evaluation",
                        "real_provider_call": True,
                        "started_at": (NOW - timedelta(hours=4)).isoformat(),
                        "completed_at": (NOW - timedelta(hours=3)).isoformat(),
                    }
                ],
            }
        ],
    }


def configured_file(tmp_path: Path, document: Any) -> dict[str, str]:
    body = json.dumps(document).encode()
    path = tmp_path / "synthetic-unit-fixture.json"
    path.write_bytes(body)
    return {
        ISSUE_EVALUATION_PUBLICATION_PATH: str(path),
        ISSUE_EVALUATION_PUBLICATION_SHA256: sha256(body).hexdigest(),
    }


def test_unconfigured_returns_none_and_never_grants_authority() -> None:
    expected = IssueEvaluationBinding.model_validate(
        fixture_document()["evaluations"][0]["evaluation"]["binding"]
    )
    assert configured_issue_evaluation_publication({}, tenant_id=TENANT, as_of=NOW) is None
    assert (
        configured_issue_evaluation({}, tenant_id=TENANT, expected_binding=expected, as_of=NOW)
        is None
    )


@pytest.mark.parametrize("outcome", ["passed", "failed"])
def test_original_bytes_and_outcome_preserved_without_grant(tmp_path: Path, outcome: str) -> None:
    document = fixture_document()
    document["evaluations"][0]["evaluation"]["outcome"] = outcome
    environment = configured_file(tmp_path, document)
    loaded = configured_issue_evaluation_publication(environment, tenant_id=TENANT, as_of=NOW)
    assert loaded is not None
    assert loaded.publication_sha256 == environment[ISSUE_EVALUATION_PUBLICATION_SHA256]
    assert not loaded.qualification_granted
    entry = loaded.publication.evaluations[0]
    assert entry.capability_suite_digest != entry.evaluation.binding.suite_digest
    selected = select_issue_evaluation(loaded, expected_binding=entry.evaluation.binding)
    assert selected.evaluation == entry.evaluation
    assert selected.evaluation.outcome == outcome
    assert selected.published_at == loaded.publication.published_at
    assert selected.valid_until == loaded.publication.valid_until
    assert not selected.qualification_granted
    assert (
        configured_issue_evaluation(
            environment, tenant_id=TENANT, expected_binding=entry.evaluation.binding, as_of=NOW
        )
        == selected
    )


@pytest.mark.parametrize(
    "key", [ISSUE_EVALUATION_PUBLICATION_PATH, ISSUE_EVALUATION_PUBLICATION_SHA256]
)
def test_partial_configuration_fails_closed(key: str) -> None:
    with pytest.raises(WriteEvaluationPublicationError, match="configuration_incomplete"):
        configured_issue_evaluation_publication({key: "configured"}, tenant_id=TENANT, as_of=NOW)


@pytest.mark.parametrize("pin", ["wrong", "A" * 64, "0" * 64])
def test_invalid_or_wrong_digest_rejected(tmp_path: Path, pin: str) -> None:
    environment = configured_file(tmp_path, fixture_document())
    environment[ISSUE_EVALUATION_PUBLICATION_SHA256] = pin
    with pytest.raises(WriteEvaluationPublicationError, match="sha256_pin|digest_mismatch"):
        configured_issue_evaluation_publication(environment, tenant_id=TENANT, as_of=NOW)


@pytest.mark.parametrize("offset", [-1, 86400, 86401])
def test_validity_window_is_start_inclusive_end_exclusive(tmp_path: Path, offset: int) -> None:
    environment = configured_file(tmp_path, fixture_document())
    with pytest.raises(WriteEvaluationPublicationError, match="outside_validity_window"):
        configured_issue_evaluation_publication(
            environment, tenant_id=TENANT, as_of=NOW + timedelta(seconds=offset)
        )


def test_tenant_and_aware_time_required(tmp_path: Path) -> None:
    environment = configured_file(tmp_path, fixture_document())
    with pytest.raises(WriteEvaluationPublicationError, match="tenant_mismatch"):
        configured_issue_evaluation_publication(environment, tenant_id=UUID(int=90), as_of=NOW)
    with pytest.raises(WriteEvaluationPublicationError, match="aware_cutoff"):
        configured_issue_evaluation_publication(
            environment, tenant_id=TENANT, as_of=NOW.replace(tzinfo=None)
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider", "deepseek"),
        ("model", "different-model"),
        ("model_version", "different-revision"),
        ("release_bundle_version", "sha256:" + "0" * 64),
        ("suite_version", "gateway.fixture.v2"),
        ("suite_digest", "0" * 64),
        ("adapter_version", "adapter.fixture.v2"),
        ("policy_version", "policy.fixture.v2"),
        ("policy_revision", 2),
    ],
)
def test_every_binding_field_matches_exactly(tmp_path: Path, field: str, value: Any) -> None:
    environment = configured_file(tmp_path, fixture_document())
    loaded = configured_issue_evaluation_publication(environment, tenant_id=TENANT, as_of=NOW)
    assert loaded is not None
    changes = loaded.publication.evaluations[0].evaluation.binding.model_dump()
    changes[field] = value
    with pytest.raises(WriteEvaluationPublicationError, match="binding_not_found"):
        select_issue_evaluation(
            loaded, expected_binding=IssueEvaluationBinding.model_validate(changes)
        )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("version",), "dc11-issue-write-evaluation-publication.v2"),
        (("actor_kind",), "ai"),
        (("actor_identity_source",), "http_client_claim"),
        (("valid_until",), NOW.isoformat()),
        (("published_at",), (NOW + timedelta(seconds=1)).isoformat()),
        (("evaluations", 0, "evaluation", "execution_source"), "offline_replay"),
        (("evaluations", 0, "evaluation", "execution_source"), "synthetic_output"),
        (("evaluations", 0, "evaluation", "binding", "operation_key"), "meeting.minutes.draft"),
        (("evaluations", 0, "evaluation", "real_provider_call"), False),
        (("evaluations", 0, "evaluation", "real_provider_call"), "true"),
        (("evaluations", 0, "evaluation", "outcome"), "incomplete"),
        (("evaluations", 0, "evaluation", "binding", "model_version"), None),
        (("evaluations", 0, "evaluation", "binding", "model_version"), "latest"),
        (("evaluations", 0, "evaluation", "binding", "model"), "unknown"),
        (("evaluations", 0, "evaluation", "binding", "provider"), "unknown"),
        (("evaluations", 0, "operation_key"), "meeting.actions.draft"),
        (("evaluations", 0, "capability_suite_digest"), "b" * 64),
        (("evaluations", 0, "golden_fixed_at"), NOW.isoformat()),
        (("evaluations", 0, "original_calls"), []),
        (("evaluations", 0, "original_calls", 0, "tenant_id"), str(UUID(int=99))),
        (("evaluations", 0, "original_calls", 0, "real_provider_call"), False),
        (("evaluations", 0, "original_calls", 0, "execution_source"), "synthetic_output"),
        (("evaluations", 0, "original_calls", 0, "binding", "policy_revision"), 2),
        (("evaluations", 0, "original_calls", 0, "completed_at"), NOW.isoformat()),
        (("evaluations", 0, "original_calls", 0, "started_at"), NOW.isoformat()),
    ],
)
def test_bad_originals_or_document_fail_closed(
    tmp_path: Path, path: tuple[Any, ...], value: Any
) -> None:
    document = fixture_document()
    target: Any = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    environment = configured_file(tmp_path, document)
    with pytest.raises(WriteEvaluationPublicationError, match="invalid_document"):
        configured_issue_evaluation_publication(environment, tenant_id=TENANT, as_of=NOW)


@pytest.mark.parametrize("mode", ["evaluation", "call", "binding", "golden"])
def test_duplicate_or_conflicting_originals_rejected(tmp_path: Path, mode: str) -> None:
    document = fixture_document()
    entry = document["evaluations"][0]
    if mode == "call":
        entry["original_calls"].append(deepcopy(entry["original_calls"][0]))
    else:
        second = deepcopy(entry)
        if mode != "evaluation":
            second["evaluation"]["evaluation_id"] = str(UUID(int=100))
        if mode == "golden":
            second["evaluation"]["binding"]["policy_revision"] = 2
            second["evaluation"]["golden_publication_digest"] = "0" * 64
            second["original_calls"][0]["binding"]["policy_revision"] = 2
        document["evaluations"].append(second)
    environment = configured_file(tmp_path, document)
    with pytest.raises(WriteEvaluationPublicationError, match="invalid_document"):
        configured_issue_evaluation_publication(environment, tenant_id=TENANT, as_of=NOW)


@pytest.mark.parametrize(
    "mode", ["size", "duplicate_key", "malformed", "symlink", "missing", "fifo"]
)
def test_file_boundary(tmp_path: Path, mode: str) -> None:
    path = tmp_path / "original.json"
    if mode == "size":
        body = b" " * (MAX_PUBLICATION_BYTES + 1)
    elif mode == "duplicate_key":
        body = b'{"version":"a","version":"b"}'
    else:
        body = b"not json"
    if mode == "fifo":
        import os

        os.mkfifo(path)
    elif mode != "missing":
        path.write_bytes(body)
    if mode == "symlink":
        link = tmp_path / "link.json"
        link.symlink_to(path)
        path = link
    environment = {
        ISSUE_EVALUATION_PUBLICATION_PATH: str(path),
        ISSUE_EVALUATION_PUBLICATION_SHA256: sha256(body).hexdigest(),
    }
    expected = {
        "size": "too_large",
        "duplicate_key": "duplicate_json_key",
        "malformed": "invalid_document",
        "symlink": "unreadable",
        "missing": "unreadable",
        "fifo": "regular_file",
    }[mode]
    with pytest.raises(WriteEvaluationPublicationError, match=expected):
        configured_issue_evaluation_publication(environment, tenant_id=TENANT, as_of=NOW)




def test_meeting_publication_configuration_does_not_enable_issue_evaluation() -> None:
    assert configured_issue_evaluation_publication(
        {
            "PDOS_AI_WRITE_EVALUATION_PUBLICATION_PATH": "meeting-publication.json",
            "PDOS_AI_WRITE_EVALUATION_PUBLICATION_SHA256": "a" * 64,
        },
        tenant_id=TENANT,
        as_of=NOW,
    ) is None
