"""Real PostgreSQL candidate: exact historical metadata, not recent-list inference.

Prepared for isolated coordinated execution; collecting does not execute fixtures.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.domain.evidence import EvidenceService
from tests.product_master_reference_fixtures import (
    master_reference_database_guard as master_reference_database_guard,
)
from tests.test_product_work_preparation_api import space
from tests.test_test_runs_api import Scope, bearer_headers
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def test_exact_old_snapshot_quality_survives_recent_limit(
    client: TestClient, isolated_test_run_database: str
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        headers = bearer_headers(client)
        sid = space(client, headers)
        service = EvidenceService(scope.engine)
        source = service.create_source(
            tenant_id=scope.tenant_id,
            actor_user_id=scope.owner_id,
            name="合成历史来源",
            source_type="file",
            allowed_use="internal_analysis",
            collection_frequency="on_demand",
            retention_policy="standard",
            trust_tier="unknown",
        )
        old = service.capture(
            tenant_id=scope.tenant_id,
            actor_user_id=scope.owner_id,
            source_id=source.id,
            content="合成原工况",
            source_version="original-v1",
            freshness_expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        newer = [
            service.capture(
                tenant_id=scope.tenant_id,
                actor_user_id=scope.owner_id,
                source_id=source.id,
                content=f"合成新观测{index}",
                source_version=f"v{index + 2}",
            )
            for index in range(201)
        ]
        service.supersede(
            tenant_id=scope.tenant_id,
            actor_user_id=scope.owner_id,
            snapshot_id=old.id,
            superseded_by_id=newer[0].id,
        )
        service.record_conflict(
            tenant_id=scope.tenant_id,
            actor_user_id=scope.owner_id,
            snapshot_id=old.id,
            conflicts_with_id=newer[1].id,
            note="合成工况冲突待核对",
        )
        url = f"/api/product-work/spaces/{sid}/evidence"
        recent = client.get(url, headers=headers)
        assert recent.status_code == 200, recent.text
        assert len(recent.json()["items"]) == 200
        assert str(old.id) not in {item["id"] for item in recent.json()["items"]}
        exact = client.get(url, headers=headers, params=[("snapshot_ids", str(old.id))] * 2)
        assert exact.status_code == 200, exact.text
        rows = exact.json()["items"]
        assert len(rows) == 1
        assert rows[0]["reference"]["digest"] == old.content_digest
        assert rows[0]["source_version"] == "original-v1"
        assert rows[0]["is_stale"] and rows[0]["superseded"] and rows[0]["has_conflict"]
        missing = client.get(url, headers=headers, params={"snapshot_ids": str(uuid4())})
        assert missing.status_code == 200 and missing.json()["items"] == []
        assert client.get(url, params={"snapshot_ids": str(old.id)}).status_code == 401
        oversized = client.get(url, headers=headers, params=[("snapshot_ids", str(old.id))] * 101)
        assert oversized.status_code == 422
    finally:
        scope.dispose()
