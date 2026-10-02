"""Personal read queue on an isolated PG database; synthetic transport, no qualification."""

from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth.repository import AuthRepository
from app.db.schema import tables
from app.domain import product_work_attention as attention
from app.domain.product_work_attention import (
    AttentionScope,
    product_work_attention,
    selection_for_summary,
)
from app.domain.product_workspace import ProductWorkError
from tests.test_product_research_findings_api import candidate, review_body
from tests.test_test_runs_api import Scope
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def test_queue_read_accept_apply_and_scope(
    request: pytest.FixtureRequest,
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        base, headers, finding, calls = candidate(
            client, scope, tmp_path, monkeypatch, request=request
        )
        with scope.engine.connect() as c:
            before = c.execute(select(func.count()).select_from(tables.audit_log)).scalar_one()
        response = client.post(
            base + "/product-work-attention", headers=headers, json={"all_lines": True}
        )
        assert response.status_code == 200, response.text
        value = response.json()
        assert response.headers["cache-control"] == "no-store"
        assert [item["id"] for item in value["candidates"]] == [finding["id"]]
        assert value["candidates"][0]["status"] == "pending_review"
        assert value["runs"][0]["run_id"] == finding["run_id"]
        assert value["runs"][0]["missing"] == ["需真实研究材料"]
        with scope.engine.connect() as c:
            assert (
                c.execute(select(func.count()).select_from(tables.audit_log)).scalar_one() == before
            )
        assert len(calls) == 1
        assert (
            client.post(base + "/product-work-attention", headers=headers, json={}).json()[
                "candidates"
            ]
            == value["candidates"]
        )
        assert (
            client.post(
                base + "/product-work-attention",
                headers=headers,
                json={"all_lines": True, "product_line_id": str(uuid4())},
            ).status_code
            == 422
        )
        inaccessible = client.post(
            base + "/product-work-attention",
            headers=headers,
            json={"product_line_id": str(uuid4())},
        )
        assert inaccessible.status_code in (403, 404)
        accepted = client.post(
            base + "/research-ai-review", headers=headers, json=review_body(finding)
        )
        assert accepted.status_code == 200, accepted.text
        assert (
            client.post(base + "/product-work-attention", headers=headers, json={}).json()[
                "candidates"
            ][0]["status"]
            == "accepted"
        )
        applied = client.post(
            base + "/research-ai-apply",
            headers=headers,
            json={
                "run_id": finding["run_id"],
                "finding_id": finding["id"],
                "accepted_digest": accepted.json()["finding"]["accepted_digest"],
            },
        )
        assert applied.status_code == 200, applied.text
        assert not client.post(base + "/product-work-attention", headers=headers, json={}).json()[
            "candidates"
        ]
        assert len(calls) == 1
    finally:
        scope.dispose()


def test_queue_excludes_other_actor_and_corrupted_frozen_binding(
    request: pytest.FixtureRequest,
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        base, headers, finding, _ = candidate(client, scope, tmp_path, monkeypatch, request=request)
        actor = uuid4()
        with scope.engine.begin() as c:
            password = c.execute(
                select(tables.users.c.password_hash).where(tables.users.c.id == scope.owner_id)
            ).scalar_one()
            c.execute(
                tables.users.insert().values(
                    id=actor,
                    tenant_id=scope.tenant_id,
                    username="queue-other",
                    display_name="Other",
                    role="admin",
                    password_hash=password,
                    is_active=True,
                )
            )
        context = AuthRepository(scope.engine).find_user_context(actor)
        assert context is not None
        other = product_work_attention(
            scope.engine, context, UUID(base.split("/")[-1]), AttentionScope(all_lines=True)
        )
        assert not other["candidates"] and not other["runs"]
        with scope.engine.connect() as c:
            run_context: dict[str, Any] = deepcopy(
                c.execute(
                    select(tables.agent_runs.c.run_context).where(
                        tables.agent_runs.c.id == UUID(finding["run_id"])
                    )
                ).scalar_one()
            )
        run_context["product_work_source"]["actor_id"] = str(actor)
        original_actor = AuthRepository(scope.engine).find_user_context(scope.owner_id)
        assert original_actor is not None
        with pytest.raises(ProductWorkError):
            selection_for_summary(
                {"run_context": run_context}, original_actor, UUID(base.split("/")[-1])
            )

        def revoked(*_args: Any) -> None:
            raise PermissionError("Private source access revoked")

        monkeypatch.setattr(attention, "readable", revoked)
        response = client.post(
            base + "/product-work-attention", headers=headers, json={"all_lines": True}
        )
        assert response.status_code == 200, response.text
        assert response.json() == {
            "candidates": [],
            "runs": [],
            "limited": False,
            "unavailable": True,
        }
        assert finding["title"] not in response.text
    finally:
        scope.dispose()
