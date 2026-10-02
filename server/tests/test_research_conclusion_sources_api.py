"""Queued real research conclusion/cancellation API cases; never model qualification.

Collection does not execute PostgreSQL fixtures. The coordinator must allocate an
explicit isolated pdos_test; the strong session guard precedes shared cleanup.
"""

from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from tests.product_master_reference_fixtures import (
    master_reference_database_guard as master_reference_database_guard,
)
from tests.test_product_manager_loop_api import command
from tests.test_product_work_preparation_api import space
from tests.test_product_work_result_evidence_api import evidence, post, started, state
from tests.test_test_runs_api import Scope, bearer_headers
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def conclusion(row: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        **command(row),
        "research_task_id": row["id"],
        "conclusion": "合成研究核对完成，原正文可回查；不代表实际业务资格",
        "findings": [],
        "unresolved": ["实际业务效果待联合验证"],
        "source_refs": sources,
    }


def test_substantive_conclusion_without_sources_is_422_without_any_write(
    client: TestClient,
    isolated_test_run_database: str,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        headers = bearer_headers(client)
        base = f"/api/product-work/spaces/{space(client, headers)}"
        row = started(client, base, headers, scope.owner_id, "research")
        identity = UUID(row["id"])
        before = state(scope, identity, "research")
        assert before[0]["state"] == "active"
        refused = post(
            client, base, headers, f"/research/{row['id']}/conclude", conclusion(row, []), 422
        )
        assert "research_conclusion_requires_snapshot_sources" in str(refused)
        assert state(scope, identity, "research") == before
    finally:
        scope.dispose()


def test_real_body_snapshot_allows_empty_findings_and_exact_original_replay(
    client: TestClient,
    isolated_test_run_database: str,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        headers = bearer_headers(client)
        base = f"/api/product-work/spaces/{space(client, headers)}"
        row = started(client, base, headers, scope.owner_id, "research")
        reference = evidence(scope, "body")
        body = conclusion(row, [reference])
        path = f"/research/{row['id']}/conclude"
        done = post(client, base, headers, path, body)
        assert done["state"] == "completed" and done["findings"] == []
        assert done["conclusion"] == body["conclusion"]
        assert done["sources"][0]["ref_id"] == reference["ref_id"]
        before = state(scope, UUID(row["id"]), "research")
        assert before[0]["completed_at"] is not None
        assert post(client, base, headers, path, body) == done
        assert state(scope, UUID(row["id"]), "research") == before
    finally:
        scope.dispose()


def test_no_evidence_can_cancel_with_reason_but_cannot_become_completed(
    client: TestClient,
    isolated_test_run_database: str,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        headers = bearer_headers(client)
        base = f"/api/product-work/spaces/{space(client, headers)}"
        row = started(client, base, headers, scope.owner_id, "research")
        body = {**command(row), "reason": "本轮没有可回查证据，停止研究并保留未决事项"}
        path = f"/research/{row['id']}/cancel"
        cancelled = post(client, base, headers, path, body)
        assert cancelled["state"] == "cancelled"
        assert cancelled["cancellation_reason"] == body["reason"]
        before = state(scope, UUID(row["id"]), "research")
        assert before[0]["state"] == "cancelled" and before[0]["completed_at"] is None
        assert before[0]["conclusion"] is None and before[0]["sources"] == []
        assert post(client, base, headers, path, body) == cancelled
        assert state(scope, UUID(row["id"]), "research") == before
        post(
            client, base, headers, f"/research/{row['id']}/conclude", conclusion(cancelled, []), 422
        )
        assert state(scope, UUID(row["id"]), "research") == before
    finally:
        scope.dispose()
