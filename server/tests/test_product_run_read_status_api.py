"""Saved PM runs use real API/budget plumbing with synthetic model transport.

These cases do not grant production qualification or prove a real model/Exit.
"""

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.db.schema import tables
from tests.product_master_reference_fixtures import (
    master_reference_database_guard as master_reference_database_guard,
)
from tests.test_product_conversations_api import Candidate, colleague
from tests.test_product_conversations_api import candidate as candidate
from tests.test_product_work_runs_api import configure, enable_test_only, output_for, prepared
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def stored_state(candidate: Candidate) -> dict[str, list[dict[str, Any]]]:
    """Reads and denials must preserve the run, receipts and business records."""
    checked = (
        tables.agent_runs,
        tables.model_invocations,
        tables.budget_lineages,
        tables.findings,
        tables.product_source_files,
        tables.scoped_work_items,
        tables.research_tasks,
        tables.product_nodes,
        tables.market_segments,
        tables.opportunities,
        tables.experiments,
        tables.product_strategies,
        tables.product_definitions,
        tables.product_master_references,
    )
    with candidate.scope.engine.connect() as c:
        return {
            table.name: [
                dict(row)
                for row in c.execute(
                    select(table)
                    .where(table.c.tenant_id == candidate.scope.tenant_id)
                    .order_by(table.c.id)
                ).mappings()
            ]
            for table in checked
        }


@pytest.mark.parametrize("endpoint", ["product-ai-run-read", "product-ai-progress"])
def test_saved_run_read_hides_missing_and_other_actor_then_honors_current_line_revoke(
    candidate: Candidate,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    endpoint: str,
) -> None:
    user_id, headers = colleague(candidate)
    requester = Candidate(
        candidate.client, candidate.scope, headers, candidate.space_id, candidate.line
    )
    line_id = UUID(candidate.line["id"])
    with candidate.scope.engine.connect() as c:
        assert (
            c.execute(
                select(tables.users.c.role).where(
                    tables.users.c.tenant_id == candidate.scope.tenant_id,
                    tables.users.c.id == user_id,
                )
            ).scalar_one()
            == "engineer"
        )
        assert (
            c.execute(
                select(tables.product_nodes.c.owner_user_id).where(
                    tables.product_nodes.c.tenant_id == candidate.scope.tenant_id,
                    tables.product_nodes.c.id == line_id,
                )
            ).scalar_one()
            != user_id
        )
        assert (
            c.execute(
                select(tables.product_line_members.c.access).where(
                    tables.product_line_members.c.tenant_id == candidate.scope.tenant_id,
                    tables.product_line_members.c.product_line_id == line_id,
                    tables.product_line_members.c.user_id == user_id,
                )
            ).scalar_one()
            == "contributor"
        )

    # Existing fixture validates committed budget lineage and authorization before
    # invoking MockTransport; LIVE/qualification are scoped test doubles only.
    enable_test_only(monkeypatch, "research_planning")
    calls = configure(
        candidate.scope,
        tmp_path,
        monkeypatch,
        output_for("research_planning"),
        request=request,
    )
    base = f"/api/product-work/spaces/{candidate.space_id}"
    body = prepared(
        requester.client, base, requester.headers, "research_planning", candidate.line["id"]
    )
    saved = requester.post(base + "/product-ai-runs", body)
    assert saved["status"] == "succeeded" and saved["invocation_id"]
    assert len(calls) == 1

    before = stored_state(candidate)
    assert len(before["agent_runs"]) == len(before["model_invocations"]) == 1
    assert len(before["budget_lineages"]) == 1
    assert before["findings"] == before["product_source_files"] == []
    original = before["agent_runs"][0]
    assert str(original["id"]) == saved["run_id"]
    assert original["requested_by_user_id"] == user_id
    assert original["project_id"] is None and original["scope_kind"] == "market_space"
    frozen = original["run_context"]
    assert frozen["product_work_selection"] == body["selection"]
    assert frozen["product_work_source"]["actor_id"] == str(user_id)
    assert frozen["product_work_source"]["market_space_id"] == candidate.space_id
    assert frozen["product_work_expected_digest"] == body["expected_digest"]
    assert frozen["product_work_invocation_id"] == saved["invocation_id"]

    url = base + "/" + endpoint
    own = requester.post(url, {"run_id": saved["run_id"]})
    if endpoint == "product-ai-run-read":
        (item,) = own["items"]
        assert item["run_id"] == saved["run_id"] and item["requested_by_me"]
        assert item["selection"] == frozen["product_work_selection"]
        assert item["source_digest"] == frozen["product_work_expected_digest"]
        assert item["frozen_sources"] == frozen["product_work_source"]["references"]
        assert item["invocation_id"] == saved["invocation_id"]
    else:
        assert own["run_id"] == saved["run_id"] and own["status"] == "succeeded"
        assert own["model_receipts"] == 1 and own["budget"] is not None
    assert stored_state(candidate) == before and len(calls) == 1

    hidden = {
        "detail": {
            "code": "PRODUCT_WORK_RUN_NOT_FOUND",
            "message": "产品工作运行不存在或不属于当前发起人",
        }
    }
    # Even a real tenant owner with Space/Line access cannot read another actor's
    # private run. Missing IDs and wrong owners disclose exactly the same body.
    for run_id, actor_headers in (
        (str(uuid4()), requester.headers),
        (saved["run_id"], candidate.headers),
    ):
        rejected = requester.client.post(url, headers=actor_headers, json={"run_id": run_id})
        assert rejected.status_code == 404, rejected.text
        assert rejected.json() == hidden
        assert stored_state(candidate) == before and len(calls) == 1

    extra = requester.client.post(
        url,
        headers=requester.headers,
        json={
            "run_id": saved["run_id"],
            "capability": "rfq_requirements",
            "product_line_id": candidate.line["id"],
        },
    )
    assert extra.status_code == 422, extra.text
    assert {tuple(error["loc"]) for error in extra.json()["detail"]} == {
        ("body", "capability"),
        ("body", "product_line_id"),
    }
    assert all(error["type"] == "extra_forbidden" for error in extra.json()["detail"])
    assert stored_state(candidate) == before and len(calls) == 1

    with candidate.scope.engine.begin() as c:
        removed = c.execute(
            tables.product_line_members.delete().where(
                tables.product_line_members.c.tenant_id == candidate.scope.tenant_id,
                tables.product_line_members.c.product_line_id == line_id,
                tables.product_line_members.c.user_id == user_id,
            )
        )
        assert removed.rowcount == 1
    revoked = requester.client.post(
        url, headers=requester.headers, json={"run_id": saved["run_id"]}
    )
    assert revoked.status_code == 403, revoked.text
    assert revoked.json() == {
        "detail": {
            "code": "PRODUCT_WORK_FORBIDDEN",
            "message": "产品线不存在或无权访问",
        }
    }
    assert stored_state(candidate) == before and len(calls) == 1
