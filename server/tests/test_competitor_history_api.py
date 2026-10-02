"""Historical comparisons retain selected values and disclose later revisions."""

# ruff: noqa: F811
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.schema import tables
from app.domain.evidence import EvidenceService
from tests.test_product_work_preparation_api import space
from tests.test_test_runs_api import Scope, bearer_headers
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def test_new_observation_requires_review_without_replacing_selected_history(
    client: TestClient, isolated_test_run_database: str
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        headers = bearer_headers(client)
        base = f"/api/product-work/spaces/{space(client, headers)}"
        service = EvidenceService(scope.engine)
        source = service.create_source(
            tenant_id=scope.tenant_id,
            actor_user_id=scope.owner_id,
            name="合成同工况竞品记录",
            source_type="file",
            allowed_use="internal_analysis",
            collection_frequency="on_demand",
            retention_policy="standard",
            trust_tier="unknown",
        )
        snapshot = service.capture(
            tenant_id=scope.tenant_id,
            actor_user_id=scope.owner_id,
            source_id=source.id,
            content="合成历史A压力100kPa、价格200CNY；新观察110kPa、210CNY。非业务实测。",
            freshness_expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        ref = dict(
            tenant_id=str(scope.tenant_id),
            kind="evidence_snapshot",
            ref_id=str(snapshot.id),
            as_of=snapshot.captured_at.isoformat(),
            digest=snapshot.content_digest,
        )
        today = datetime.now(UTC).date().isoformat()
        body: dict[str, Any] = dict(
            brand="合成品牌",
            model="A",
            variant="基本型",
            competitor_kind="direct",
            region="TEST",
            channel="online",
            configuration="合成同配置",
            lifecycle="available",
            observed_on=today,
            identity_sources=[ref],
            metrics=[
                dict(
                    key="pressure",
                    label="压力",
                    number="100",
                    unit="kPa",
                    nature="claimed",
                    conditions="25℃",
                    method="同一声明口径",
                    source_refs=[ref],
                )
            ],
            price_quote=dict(
                amount="200",
                currency="CNY",
                as_of=today,
                quantity=1,
                basis="retail",
                tax_included=True,
                shipping_included=True,
                conditions="合成同报价条件",
                source_refs=[ref],
            ),
            revision_reason="合成起始记录",
        )

        def create(value: dict[str, Any]) -> dict[str, Any]:
            response = client.post(
                base + "/competitors",
                headers=headers,
                json={**value, "request_id": str(uuid4())},
            )
            assert response.status_code == 201, response.text
            return response.json()

        old, other = create(body), create({**body, "model": "B"})

        def compare(left: str) -> dict[str, Any]:
            response = client.post(
                base + "/competitor-comparison",
                headers=headers,
                json={"observation_ids": [left, other["id"]]},
            )
            assert response.status_code == 200, response.text
            return response.json()

        before = compare(old["id"])
        assert all(r["status"] == "comparable" for r in before["rows"])
        changed = deepcopy(body)
        changed["metrics"][0]["number"] = "110"
        changed["price_quote"]["amount"] = "210"
        changed["supersedes_id"] = old["id"]
        changed["revision_reason"] = "合成参数与价格变化"
        revised = create(changed)
        historical = compare(old["id"])
        assert not historical["observations"][0]["is_latest"]
        assert historical["observations"][1]["is_latest"]
        assert all(r["status"] == "review_needed" for r in historical["rows"])
        assert all(any("后续修订" in reason for reason in r["reasons"]) for r in historical["rows"])
        assert [r["cells"] for r in historical["rows"]] == [r["cells"] for r in before["rows"]]
        current = compare(revised["id"])
        assert all(r["status"] == "comparable" for r in current["rows"])
        assert all(r["is_latest"] for r in current["observations"])
        assert current["rows"][0]["cells"][0]["number"] == "110"
        assert current["rows"][1]["cells"][0]["amount"] == "210"
        # Cross-space input must not leak a version warning or observation.
        denied = client.post(
            f"/api/product-work/spaces/{space(client, headers)}/competitor-comparison",
            headers=headers,
            json={"observation_ids": [old["id"], other["id"]]},
        )
        assert denied.status_code == 403 and "observations" not in denied.json()
        with scope.engine.connect() as connection:
            assert (
                connection.execute(
                    select(func.count()).select_from(tables.model_invocations)
                ).scalar_one()
                == 0
            )
    finally:
        scope.dispose()
