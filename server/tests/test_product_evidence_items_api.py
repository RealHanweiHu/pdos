"""Independent item decisions, immutable AI input, scoped reads and atomic application."""

# ruff: noqa: F811
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.schema import tables
from tests.test_product_evidence_findings_api import review_body, setup_candidate
from tests.test_test_runs_api import Scope
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def read_item(
    client: TestClient, base: str, headers: dict[str, str], parent: dict[str, Any], position: int
) -> dict[str, Any]:
    result = client.post(
        base + "/evidence-ai-item",
        headers=headers,
        json={
            "run_id": parent["finding"]["run_id"],
            "parent_finding_id": parent["finding"]["id"],
            "position": position,
        },
    )
    assert result.status_code == 200, result.text
    return result.json()


def item_review(parent: dict[str, Any], item: dict[str, Any], position: int) -> dict[str, Any]:
    return {
        "run_id": item["finding"]["run_id"],
        "parent_finding_id": parent["finding"]["id"],
        "position": position,
        "review": review_body(item),
    }


@pytest.mark.parametrize("capability", ["competitor_analysis", "market_analysis"])
def test_items_are_readonly_until_named_review_and_apply_independently(
    request: pytest.FixtureRequest,
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capability: str,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        base, headers, parent, calls = setup_candidate(
            client, scope, tmp_path, monkeypatch, capability, request=request
        )
        original = deepcopy(parent["finding"]["proposed_payload"])
        assert len(parent["item_candidates"]) == len(parent["proposal"]["items"])
        item = read_item(client, base, headers, parent, 1)
        assert item["proposal"]["items"] == parent["proposal"]["items"][:1]
        table = (
            tables.competitor_observations
            if capability == "competitor_analysis"
            else tables.market_segments
        )
        with scope.engine.connect() as c:
            assert c.execute(select(func.count()).select_from(tables.findings)).scalar_one() == 1
        body = item_review(parent, item, 1)
        accepted = client.post(base + "/evidence-ai-item-review", headers=headers, json=body)
        assert accepted.status_code == 200, accepted.text
        assert (
            client.post(base + "/evidence-ai-item-review", headers=headers, json=body).json()
            == accepted.json()
        )
        with scope.engine.connect() as c:
            assert c.execute(select(func.count()).select_from(table)).scalar_one() == 0
        blocked_bulk = client.post(
            base + "/evidence-ai-review", headers=headers, json=review_body(parent)
        )
        assert blocked_bulk.status_code == 409
        queue = client.post(
            base + "/product-work-attention", headers=headers, json={"all_lines": True}
        ).json()
        assert len(queue["candidates"]) == len(parent["proposal"]["items"])
        assert queue["candidates"][0]["parent_finding_id"] == parent["finding"]["id"]
        assert queue["candidates"][0]["status"] == "accepted"
        apply = {
            "run_id": item["finding"]["run_id"],
            "finding_id": item["finding"]["id"],
            "accepted_digest": accepted.json()["finding"]["accepted_digest"],
        }
        result = client.post(base + "/evidence-ai-item-apply", headers=headers, json=apply)
        assert result.status_code == 200, result.text
        assert len(result.json()["records"]) == 1
        assert (
            client.post(base + "/evidence-ai-item-apply", headers=headers, json=apply).json()
            == result.json()
        )
        if capability == "competitor_analysis":
            second = read_item(client, base, headers, parent, 2)
            assert second["finding"]["status"] == "pending_review"
            accepted2 = client.post(
                base + "/evidence-ai-item-review",
                headers=headers,
                json=item_review(parent, second, 2),
            )
            assert accepted2.status_code == 200, accepted2.text
            result2 = client.post(
                base + "/evidence-ai-item-apply",
                headers=headers,
                json={
                    "run_id": second["finding"]["run_id"],
                    "finding_id": second["finding"]["id"],
                    "accepted_digest": accepted2.json()["finding"]["accepted_digest"],
                },
            )
            assert result2.status_code == 200, result2.text
            assert result2.json()["records"][0]["id"] != result.json()["records"][0]["id"]
        with scope.engine.connect() as c:
            saved_parent = (
                c.execute(
                    select(tables.findings).where(
                        tables.findings.c.id == UUID(parent["finding"]["id"])
                    )
                )
                .mappings()
                .one()
            )
            assert saved_parent["proposed_payload"] == original
            assert saved_parent["status"] == "pending_review"
            assert c.execute(select(func.count()).select_from(table)).scalar_one() == len(
                parent["proposal"]["items"]
            )
        assert (
            client.post(
                base + "/product-work-attention", headers=headers, json={"all_lines": True}
            ).json()["candidates"]
            == []
        )
        assert len(calls) == 1
    finally:
        scope.engine.dispose()


def test_item_ignore_requires_reason_and_cannot_change_position_or_scope(
    request: pytest.FixtureRequest,
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        base, headers, parent, _ = setup_candidate(
            client, scope, tmp_path, monkeypatch, "competitor_analysis", request=request
        )
        item = read_item(client, base, headers, parent, 1)
        body = item_review(parent, item, 2)
        assert (
            client.post(base + "/evidence-ai-item-review", headers=headers, json=body).status_code
            == 409
        )
        body["position"] = 1
        body["review"].update(decision="rejected", proposal=None, comment=" ")
        assert (
            client.post(base + "/evidence-ai-item-review", headers=headers, json=body).status_code
            == 422
        )
        body["review"]["comment"] = "此工况不符合本次研究边界"
        result = client.post(base + "/evidence-ai-item-review", headers=headers, json=body)
        assert result.status_code == 200, result.text
        assert result.json()["finding"]["review_comment"] == body["review"]["comment"]
        assert read_item(client, base, headers, parent, 2)["finding"]["status"] == "pending_review"
        assert (
            client.post(
                base + "/evidence-ai-item-apply",
                headers=headers,
                json={
                    "run_id": item["finding"]["run_id"],
                    "finding_id": item["finding"]["id"],
                    "accepted_digest": "a" * 64,
                },
            ).status_code
            == 409
        )
        with scope.engine.connect() as c:
            assert (
                c.execute(
                    select(func.count()).select_from(tables.competitor_observations)
                ).scalar_one()
                == 0
            )
    finally:
        scope.engine.dispose()


def test_failed_item_review_rolls_back_materialization(
    request: pytest.FixtureRequest,
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        base, headers, parent, _ = setup_candidate(
            client, scope, tmp_path, monkeypatch, "competitor_analysis", request=request
        )
        item = read_item(client, base, headers, parent, 1)
        body = item_review(parent, item, 1)
        body["review"]["proposal"]["items"][0]["identity_sources"][0]["digest"] = "e" * 64
        assert (
            client.post(base + "/evidence-ai-item-review", headers=headers, json=body).status_code
            == 409
        )
        with scope.engine.connect() as c:
            assert c.execute(select(func.count()).select_from(tables.findings)).scalar_one() == 1
        assert read_item(client, base, headers, parent, 1)["finding"]["status"] == "pending_review"
    finally:
        scope.engine.dispose()


@pytest.mark.parametrize(
    "capability",
    ["opportunity_mapping", "experiment_design", "product_strategy", "product_definition"],
)
def test_item_application_preserves_discovery_and_t2_draft_boundaries(
    request: pytest.FixtureRequest,
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capability: str,
) -> None:
    from tests.test_product_discovery_findings_api import setup_candidate as discovery
    from tests.test_product_planning_findings_api import setup_candidate as planning

    scope = Scope(client, isolated_test_run_database)
    try:
        setup = (
            discovery if capability in {"opportunity_mapping", "experiment_design"} else planning
        )
        base, headers, parent, _ = setup(
            client, scope, tmp_path, monkeypatch, capability, request=request
        )
        item = read_item(client, base, headers, parent, 1)
        accepted = client.post(
            base + "/evidence-ai-item-review", headers=headers, json=item_review(parent, item, 1)
        )
        assert accepted.status_code == 200, accepted.text
        result = client.post(
            base + "/evidence-ai-item-apply",
            headers=headers,
            json={
                "run_id": item["finding"]["run_id"],
                "finding_id": item["finding"]["id"],
                "accepted_digest": accepted.json()["finding"]["accepted_digest"],
            },
        )
        assert result.status_code == 200, result.text
        saved = result.json()["records"]
        assert len(saved) == 1
        assert saved[0]["source_finding_id"] == item["finding"]["id"]
        if capability != "opportunity_mapping":
            assert saved[0]["state"] == "draft"
            assert saved[0].get("approval") is None
    finally:
        scope.engine.dispose()
