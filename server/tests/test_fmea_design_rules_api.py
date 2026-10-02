"""Synthetic FMEA-to-knowledge drafts, independent review and live-source invalidation."""

# ruff: noqa: F811
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.api.memories import get_embedding_gateway
from app.db.engine import get_engine
from app.db.schema import tables
from app.main import app
from tests.test_memory_api import FakeEmbeddingGateway
from tests.test_quality_capa_api import (
    SERVER_ROOT,
    client,  # noqa: F401
    isolated_quality_database,  # noqa: F401
    login,
    seed_project_and_engineer,
)
from tests.test_quality_issue_links_api import QualityLoop


def fmea(scope: QualityLoop) -> tuple[str, dict]:
    scope.escalate()
    root = scope.base + "/quality/fmea"
    refs = []
    for kind in ("issue", "ncr", "test_run"):
        res = scope.client.get(root + f"/sources?kind={kind}", headers=scope.headers["quality"])
        assert res.status_code == 200, res.text
        source = res.json()["items"][0]
        refs.append(
            {
                "kind": kind,
                "id": source["id"],
                "expected_digest": source["digest"],
                "relationship": "Original observed synthetic evidence",
            }
        )
    body = {
        "title": "Seal design",
        "design_function": "Retain pressure",
        "failure_mode": "Leakage",
        "effect": "Loss of pressure",
        "possible_cause": "Investigation pending",
        "cause_status": "hypothesis",
        "control_gaps": "Only synthetic test conditions covered",
        "scoring_method": "Not yet scored",
        "scoring_basis": "Await representative samples",
        "unknown_reason": "No population data",
        "next_action": "Assess professional applicability",
        "references": refs,
        "reason": "Original quality facts",
    }
    res = scope.client.post(
        root + "/versions",
        headers=scope.headers["quality"],
        json={"request_id": str(uuid4()), "content": body},
    )
    assert res.status_code == 200, res.text
    return res.json()["version"]["entry_id"], body


def publish(scope: QualityLoop, entry: str) -> dict:
    url = scope.base + f"/quality/fmea/{entry}"
    state = scope.client.get(url, headers=scope.headers["quality"]).json()
    res = scope.client.post(
        url + "/publish",
        headers=scope.headers["quality"],
        json={
            "request_id": str(uuid4()),
            "version_id": state["latest"]["id"],
            "expected_publication_id": state["publication"]["id"] if state["publication"] else None,
            "expected_digest": state["digest"],
            "details_confirmed": True,
            "reason": "Human publication of limited synthetic scope",
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_fmea_design_rule_draft_review_replay_and_source_scope(
    client: TestClient, isolated_quality_database: str
) -> None:
    scope = QualityLoop(client, isolated_quality_database)
    entry, _ = fmea(scope)
    url = scope.base + f"/quality/fmea/{entry}/design-rules"
    preview = client.get(url, headers=scope.headers["quality"])
    assert preview.status_code == 200, preview.text
    assert preview.json()["publication"] is None
    payload = {
        "publication_id": str(uuid4()),
        "expected_digest": preview.json()["digest"],
        "title": "Seal rule",
        "content": "Validate seal geometry under stated conditions",
        "applicability": "Synthetic device at measured pressure only; no general population claim",
    }
    assert client.post(url, headers=scope.headers["quality"], json=payload).status_code == 409
    publish(scope, entry)
    ready = client.get(url, headers=scope.headers["quality"]).json()
    assert ready["basis"] and ready["source_gaps"] == []
    payload.update(publication_id=ready["publication"]["id"], expected_digest=ready["digest"])
    assert (
        client.post(
            url, headers=scope.headers["quality"], json={**payload, "applicability": " "}
        ).status_code
        == 422
    )
    result = client.post(url, headers=scope.headers["quality"], json=payload)
    assert result.status_code == 200, result.text
    memory_id = result.json()["memory"]["id"]
    assert result.json()["memory"]["status"] == "draft"
    assert result.json()["memory"]["knowledge_kind"] == "design_rule"
    assert (
        client.post(url, headers=scope.headers["quality"], json=payload).json()["memory"]["id"]
        == memory_id
    )
    assert (
        client.post(
            url, headers=scope.headers["reviewer"], json={**payload, "content": "Different rule"}
        ).status_code
        == 409
    )
    other, _ = seed_project_and_engineer(
        isolated_quality_database,
        scope.tenant,
        scope.owner,
        suffix="OTHER",
        engineer_username="outsider",
    )
    assert client.get(url, headers=login(client, "outsider")).status_code == 403
    assert (
        client.post(
            f"/api/projects/{other}/quality/fmea/{entry}/design-rules",
            headers=scope.headers["owner"],
            json=payload,
        ).status_code
        == 409
    )
    records = client.get(scope.base + "/memories", headers=scope.headers["quality"]).json()["items"]
    assert len(records) == 1
    memory = records[0]
    assert memory["source_refs"][0]["reference"] == payload["publication_id"]
    gateway = FakeEmbeddingGateway()
    app.dependency_overrides[get_embedding_gateway] = lambda: gateway
    try:
        verify_url = scope.base + f"/memories/{memory_id}/verify"
        assert (
            client.post(
                verify_url,
                headers=scope.headers["quality"],
                json={"expected_review_digest": memory["review_digest"]},
            ).status_code
            == 409
        )
        assert gateway.inputs == []
        accepted = client.post(
            verify_url,
            headers=scope.headers["reviewer"],
            json={"expected_review_digest": memory["review_digest"]},
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["verified_by_user_id"] == str(scope.reviewer)
        assert len(gateway.inputs) == 1
        sources_url = scope.base + f"/memories/{memory_id}/sources"
        assert (
            client.get(sources_url, headers=scope.headers["reviewer"]).json()["state"] == "current"
        )
        found = client.post(
            "/api/knowledge/search",
            headers=scope.headers["reviewer"],
            json={
                "project_id": str(scope.project),
                "query": "Seal rule",
                "limit": 10,
                "knowledge_kind": "design_rule",
            },
        )
        assert found.status_code == 200, found.text
        assert [item["memory"]["id"] for item in found.json()["items"]] == [memory_id]
        # Changing an actual linked fact invalidates verified reuse, while retaining review history.
        changed = client.patch(
            scope.base + f"/issues/{scope.issue}",
            headers=scope.headers["owner"],
            json={"description": "Observed new failure condition"},
        )
        assert changed.status_code == 200, changed.text
        assert client.get(sources_url, headers=scope.headers["reviewer"]).json()["state"] == "stale"
        assert (
            client.get(url, headers=scope.headers["quality"]).json()["items"][0]["status"]
            == "verified"
        )
        hidden = client.post(
            "/api/knowledge/search",
            headers=scope.headers["reviewer"],
            json={"project_id": str(scope.project), "query": "Seal rule", "limit": 10},
        )
        assert hidden.status_code == 200, hidden.text
        assert hidden.json()["items"] == []
        # Downgrade cannot discard the new source meaning once actual candidate history exists.
        with pytest.raises(Exception, match="Retain FMEA knowledge source history"):
            command.downgrade(Config(str(SERVER_ROOT / "alembic.ini")), "0395_xiaopai_delegations")
    finally:
        app.dependency_overrides.pop(get_embedding_gateway, None)


@pytest.mark.parametrize("change", ["publication", "quality", "test_evidence", "during_embedding"])
def test_fmea_source_change_blocks_review_before_embedding(
    client: TestClient, isolated_quality_database: str, change: str
) -> None:
    scope = QualityLoop(client, isolated_quality_database)
    entry, body = fmea(scope)
    publish(scope, entry)
    url = scope.base + f"/quality/fmea/{entry}/design-rules"
    ready = client.get(url, headers=scope.headers["quality"]).json()
    payload = {
        "publication_id": ready["publication"]["id"],
        "expected_digest": ready["digest"],
        "title": "Scoped seal rule",
        "content": "Verify measured leak rate",
        "applicability": "Only tested geometry and pressure; broader use requires validation",
    }
    created = client.post(url, headers=scope.headers["quality"], json=payload)
    assert created.status_code == 200, created.text
    memory_id = created.json()["memory"]["id"]
    if change == "publication":
        revised = client.post(
            scope.base + "/quality/fmea/versions",
            headers=scope.headers["quality"],
            json={
                "request_id": str(uuid4()),
                "entry_id": entry,
                "expected_version_id": ready["version"]["id"],
                "content": {**body, "reason": "Updated professional control"},
            },
        )
        assert revised.status_code == 200, revised.text
        publish(scope, entry)
    elif change == "quality":
        scope.transition("containment")
    elif change == "test_evidence":
        # Storage-level mutation models a corrected actual test; it is explicitly synthetic.
        test_id = next(r["id"] for r in body["references"] if r["kind"] == "test_run")
        with get_engine().begin() as c:
            c.execute(
                tables.test_runs.update()
                .where(tables.test_runs.c.id == UUID(test_id))
                .values(result_notes="Corrected measured evidence")
            )
    memory = client.get(scope.base + "/memories", headers=scope.headers["quality"]).json()["items"][
        0
    ]

    class SourceChangesDuringEmbedding(FakeEmbeddingGateway):
        def embed(self, value: str):
            result = super().embed(value)
            changed = client.patch(
                scope.base + f"/issues/{scope.issue}",
                headers=scope.headers["owner"],
                json={"description": "Source changed while embedding was in flight"},
            )
            assert changed.status_code == 200, changed.text
            return result

    gateway = (
        SourceChangesDuringEmbedding() if change == "during_embedding" else FakeEmbeddingGateway()
    )
    app.dependency_overrides[get_embedding_gateway] = lambda: gateway
    try:
        res = client.post(
            scope.base + f"/memories/{memory_id}/verify",
            headers=scope.headers["reviewer"],
            json={"expected_review_digest": memory["review_digest"]},
        )
        assert res.status_code == 409, res.text
        assert res.json()["detail"]["code"] == "MEMORY_SOURCE_INVALID"
        assert len(gateway.inputs) == (1 if change == "during_embedding" else 0)
        with get_engine().connect() as c:
            assert (
                c.execute(
                    select(tables.memories.c.status).where(tables.memories.c.id == UUID(memory_id))
                ).scalar_one()
                == "draft"
            )
    finally:
        app.dependency_overrides.pop(get_embedding_gateway, None)


def test_fmea_knowledge_view_migration_round_trip(isolated_quality_database: str) -> None:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    command.downgrade(config, "0395_xiaopai_delegations")
    command.upgrade(config, "head")
    with get_engine().connect() as c:
        assert (
            c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "0396_fmea_knowledge_basis"
        )
