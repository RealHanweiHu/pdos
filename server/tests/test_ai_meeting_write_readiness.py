"""Mock connection + real provenance verification; never database/model execution."""

from __future__ import annotations

import os
import socket
from copy import deepcopy
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import Connection
from sqlalchemy.dialects import postgresql

from app.ai.write_evaluation_publication import (
    LoadedWriteEvaluationPublication,
    WriteEvaluationPublication,
    WriteEvaluationPublicationError,
    select_write_evaluation,
)
from app.domain import ai_meeting_write_readiness as readiness
from app.domain.ai_write_qualification_state import (
    QualificationPublicationRef,
    QualificationReason,
    QualificationState,
)
from tests import test_ai_write_trial_collection as fixtures
from tests import test_write_evaluation_publication as publication_fixtures


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("readiness tests cannot access SQL or models")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def publication(row: dict[str, Any]) -> LoadedWriteEvaluationPublication:
    document = publication_fixtures.fixture_document()
    document.update(
        tenant_id=str(fixtures.TENANT),
        published_at=(fixtures.START - timedelta(hours=1)).isoformat(),
        valid_from=fixtures.START.isoformat(),
        valid_until=(fixtures.CUTOFF + timedelta(days=1)).isoformat(),
    )
    entry = document["evaluations"][0]
    entry["operation_key"] = fixtures.expected(row).operation_key
    entry["golden_fixed_at"] = (fixtures.START - timedelta(days=2)).isoformat()
    entry["evaluation"].update(
        binding=fixtures.expected(row).model_dump(mode="json"),
        outcome="passed",
        completed_at=(fixtures.START - timedelta(hours=2)).isoformat(),
    )
    entry["original_calls"][0].update(
        tenant_id=str(fixtures.TENANT),
        binding=fixtures.expected(row).model_dump(mode="json"),
        started_at=(fixtures.START - timedelta(hours=4)).isoformat(),
        completed_at=(fixtures.START - timedelta(hours=3)).isoformat(),
    )
    return LoadedWriteEvaluationPublication(
        publication_sha256="7" * 64,
        publication=WriteEvaluationPublication.model_validate(document),
    )


def setup(
    monkeypatch: pytest.MonkeyPatch, row: dict[str, Any] | None = None
) -> tuple[dict[str, Any], fixtures.ReadConnection, dict[str, Any]]:
    row = row or fixtures.receipt()
    loaded = publication(row)
    binding = fixtures.expected(row)
    selected = select_write_evaluation(loaded, expected_binding=binding)
    state = QualificationState(
        state="current",
        checked_at=fixtures.CUTOFF,
        tenant_id=fixtures.TENANT,
        project_id=fixtures.PROJECT,
        operation_key=binding.operation_key,
        binding=binding,
        policy_id=UUID(row["policy"]["id"]),
        publication=QualificationPublicationRef(
            publication_id=selected.publication_id,
            publication_sha256=selected.publication_sha256,
            evaluation_id=selected.evaluation.evaluation_id,
            evidence_ref=selected.evaluation.evidence_ref,
            golden_publication_ref=selected.evaluation.golden_publication_ref,
            published_at=selected.published_at,
            valid_from=selected.valid_from,
            valid_until=selected.valid_until,
        ),
    )
    controls: dict[str, Any] = {"loaded": loaded, "state": state, "reader_calls": 0}

    def load(environment: Any, **kwargs: Any) -> Any:
        assert environment is os.environ
        assert kwargs == {"tenant_id": fixtures.TENANT, "as_of": fixtures.CUTOFF}
        return controls["loaded"]

    def read(connection: Any, **kwargs: Any) -> Any:
        controls["reader_calls"] += 1
        assert kwargs["binding"] == binding
        assert kwargs["project_id"] == fixtures.PROJECT
        return controls["state"]

    monkeypatch.setattr(readiness, "configured_write_evaluation_publication", load)
    monkeypatch.setattr(readiness, "read_qualification_state", read)
    monkeypatch.setattr(readiness, "bundle", lambda purpose: row["observation"]["bundle"])
    return row, fixtures.ReadConnection([row]), controls


def assess(row: dict[str, Any], connection: fixtures.ReadConnection) -> dict[str, Any]:
    return readiness.assess_generated_write(
        cast(Connection, connection), draft=row["draft"], as_of=fixtures.CUTOFF
    )


def codes(result: dict[str, Any]) -> set[str]:
    return {item["code"] for item in result["reasons"]}


@pytest.mark.parametrize("kind", ["minutes", "actions", "decisions"])
def test_current_uses_actual_chain_and_returns_full_material_without_grant(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    row, connection, controls = setup(monkeypatch, fixtures.receipt(kind=kind))
    before = deepcopy(row)
    result = assess(row, connection)
    assert result["state"] == "current"
    assert result["binding"] == fixtures.expected(row).model_dump(mode="json")
    assert result["qualification_state"] == controls["state"].model_dump(mode="json")
    assert result["source_receipt_digest"]
    assert result["evaluation_publication"]["publication_sha256"] == "7" * 64
    assert result["qualification_granted"] is False
    assert controls["reader_calls"] == 1
    assert row == before
    assert len(connection.queries) == 1
    assert connection.queries[0].is_select


@pytest.mark.parametrize(
    "source", ["call", "policy", "observation", "checkpoint", "manifest", "admission"]
)
def test_missing_original_never_qualifies(monkeypatch: pytest.MonkeyPatch, source: str) -> None:
    row, connection, controls = setup(monkeypatch)
    row[source] = None
    result = assess(row, connection)
    assert result["state"] == "blocked"
    assert controls["reader_calls"] == 0


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("call", "usage_status", "unknown"),
        ("call", "status", "failed"),
        ("call", "model_version", "unknown"),
        ("call", "total_tokens", 99),
        ("observation", "run_id", str(UUID(int=999))),
        ("checkpoint", "manifest_id", str(UUID(int=999))),
        ("admission", "reservation_status", "released"),
        ("policy", "principal_id", str(UUID(int=999))),
    ],
)
def test_original_chain_mismatch_blocks_before_qualification(
    monkeypatch: pytest.MonkeyPatch, section: str, field: str, value: Any
) -> None:
    row, connection, controls = setup(monkeypatch)
    row[section][field] = value
    result = assess(row, connection)
    assert result["state"] == "blocked"
    assert controls["reader_calls"] == 0


def test_forged_gateway_suite_does_not_reproduce_original_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row, connection, controls = setup(monkeypatch)
    document = controls["loaded"].publication.model_dump(mode="json")
    entry = document["evaluations"][0]
    entry["evaluation"]["binding"]["suite_digest"] = "0" * 64
    entry["original_calls"][0]["binding"]["suite_digest"] = "0" * 64
    controls["loaded"] = LoadedWriteEvaluationPublication(
        publication_sha256="8" * 64, publication=WriteEvaluationPublication.model_validate(document)
    )
    result = assess(row, connection)
    assert result["state"] == "blocked"
    assert "suite_binding_unverified" in codes(result)
    assert controls["reader_calls"] == 0


def test_duplicate_call_join_never_picks_first(monkeypatch: pytest.MonkeyPatch) -> None:
    row, connection, controls = setup(monkeypatch)
    connection.rows.append(deepcopy(row))
    assert codes(assess(row, connection)) == {"generated_provenance_ambiguous"}
    assert controls["reader_calls"] == 0


def test_call_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    row, connection, _ = setup(monkeypatch)
    connection.rows = []
    result = assess(row, connection)
    assert result["state"] == "unavailable"
    assert codes(result) == {"generated_call_missing"}


@pytest.mark.parametrize("mode", ["absent", "invalid"])
def test_publication_absent_or_invalid_never_falls_back_to_http_candidate(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    row, connection, controls = setup(monkeypatch)
    row["draft"]["binding"] = fixtures.expected(row).model_dump(mode="json")
    if mode == "absent":
        controls["loaded"] = None
    else:

        def rejected(*args: Any, **kwargs: Any) -> Any:
            raise WriteEvaluationPublicationError("publication_digest_mismatch")

        monkeypatch.setattr(readiness, "configured_write_evaluation_publication", rejected)
    result = assess(row, connection)
    assert result["state"] == "unavailable"
    assert result["binding"] is None
    assert controls["reader_calls"] == 0


def test_current_runtime_must_match_original_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    row, connection, controls = setup(monkeypatch)
    changed = deepcopy(row["observation"]["bundle"])
    changed["source_sha256"]["new-source.py"] = "f" * 64
    monkeypatch.setattr(readiness, "bundle", lambda purpose: changed)
    result = assess(row, connection)
    assert result["state"] == "blocked"
    assert codes(result) == {"runtime_bundle_changed"}
    assert controls["reader_calls"] == 0


@pytest.mark.parametrize("state", ["blocked", "unavailable"])
def test_full_noncurrent_qualification_state_is_preserved(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    row, connection, controls = setup(monkeypatch)
    controls["state"] = controls["state"].model_copy(
        update={
            "state": state,
            "reasons": (QualificationReason(code="fresh_criteria_not_met", message="测试阻塞"),),
        }
    )
    result = assess(row, connection)
    assert result["state"] == state
    assert result["qualification_state"] == controls["state"].model_dump(mode="json")
    assert codes(result) == {"fresh_criteria_not_met"}


def test_publication_rotation_between_reads_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    row, connection, controls = setup(monkeypatch)
    changed = controls["state"].publication.model_copy(update={"publication_sha256": "8" * 64})
    controls["state"] = controls["state"].model_copy(update={"publication": changed})
    result = assess(row, connection)
    assert result["state"] == "blocked"
    assert codes(result) == {"evaluation_publication_changed_during_check"}
    assert result["qualification_state"]


@pytest.mark.parametrize(
    "field,value", [("policy_id", UUID(int=999)), ("project_id", UUID(int=999))]
)
def test_qualification_reader_identity_mismatch_blocks(
    monkeypatch: pytest.MonkeyPatch, field: str, value: Any
) -> None:
    row, connection, controls = setup(monkeypatch)
    controls["state"] = controls["state"].model_copy(update={field: value})
    assert codes(assess(row, connection)) == {"qualification_material_binding_changed"}


@pytest.mark.parametrize(
    "field,value",
    [
        ("origin", "human"),
        ("draft_kind", "other"),
        ("created_at", "2026-09-01T00:00:00"),
        ("id", "not-uuid"),
    ],
)
def test_invalid_draft_fails_before_any_read(
    monkeypatch: pytest.MonkeyPatch, field: str, value: Any
) -> None:
    row, connection, _ = setup(monkeypatch)
    row["draft"][field] = value
    assert codes(assess(row, connection)) == {"generated_draft_identity_invalid"}
    assert not connection.queries


def test_query_targets_actual_call_without_inserted_draft_or_history() -> None:
    query = readiness.generated_provenance_query(fixtures.receipt()["draft"])
    compiled = query.compile(dialect=postgresql.dialect())  # type: ignore[no-untyped-call]
    sql = str(compiled)
    assert sql.count("LEFT OUTER JOIN") == 5
    assert "ai_meeting_drafts" not in sql
    assert "model_invocations.project_id =" in sql
    assert "model_invocations.run_id =" in sql
    assert "model_invocations.id =" in sql
    assert "model_invocations.tenant_id =" in sql
    assert compiled.params["param_1"] == 2


def test_failed_published_evaluation_cannot_reach_current(monkeypatch: pytest.MonkeyPatch) -> None:
    row, connection, controls = setup(monkeypatch)
    document = controls["loaded"].publication.model_dump(mode="json")
    document["evaluations"][0]["evaluation"]["outcome"] = "failed"
    controls["loaded"] = LoadedWriteEvaluationPublication(
        publication_sha256="7" * 64, publication=WriteEvaluationPublication.model_validate(document)
    )
    result = assess(row, connection)
    assert result["state"] == "blocked"
    assert codes(result) == {"passing_evaluation_material_missing"}
    assert result["qualification_state"]


def test_connection_error_propagates_for_parent_transaction_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.exc import SQLAlchemyError

    row, connection, _ = setup(monkeypatch)

    def unavailable(query: Any) -> Any:
        raise SQLAlchemyError("synthetic connection failure")

    monkeypatch.setattr(connection, "execute", unavailable)
    with pytest.raises(SQLAlchemyError, match="synthetic connection failure"):
        assess(row, connection)
