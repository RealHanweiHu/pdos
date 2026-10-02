"""Actual HTTP/auth/Issue transactions in the coordinator-assigned recovery database."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.auth.repository import AuthContext
from app.auth.tokens import TokenCodec
from app.db.engine import get_engine
from app.db.schema import tables
from app.domain.issues import IssueDraft, IssueService
from app.main import app
from app.settings import get_settings
from tests.test_material_recovery_postgres import (
    capture,
    prepare_verification,
    restored,
)
from tests.test_material_recovery_postgres import recovery_scope as recovery_scope
from tests.test_parallel_supply_postgres import counts
from tests.test_supplier_replies_postgres import SupplyPostgresScope


def headers(actor: AuthContext) -> dict[str, str]:
    token = TokenCodec(get_settings()).issue(
        user_id=actor.user.id, tenant_id=actor.tenant.id, auth_version=actor.user.auth_version
    )
    return {"Authorization": f"Bearer {token.token}"}


@pytest.fixture
def client(recovery_scope: SupplyPostgresScope) -> Iterator[TestClient]:
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_engine] = lambda: recovery_scope.engine
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_current_work_card_reference_and_named_http_close(
    recovery_scope: SupplyPostgresScope, client: TestClient
) -> None:
    s = recovery_scope
    demand, identity, issue, _, _, reference = restored(s)
    prepare_verification(s, demand, issue)
    base = f"/api/projects/{demand.project}/issues/{issue}"
    response = client.get(base + "/work-card", headers=headers(s.peer))
    assert response.status_code == 200, response.text
    assert "no-store" in response.headers["cache-control"]
    card = response.json()
    material = card["material_closure"]
    assert material["required"] and material["ready"]
    assert material["items"][0]["exception_id"] == str(identity)
    assert material["items"][0]["closure"]["reference"] == reference.model_dump(mode="json")
    result = client.post(
        base + "/transitions",
        headers=headers(s.peer),
        json={
            "to_status": "closed",
            "expected_updated_at": card["item"]["updated_at"],
            "closure_evidence_ref": "Named verification of synthetic recovery",
            "material_closures": [reference.model_dump(mode="json")],
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["id"] == str(issue) and result.json()["status"] == "closed"


def test_changed_source_returns_409_without_issue_event_or_audit_write(
    recovery_scope: SupplyPostgresScope, client: TestClient
) -> None:
    s = recovery_scope
    demand, _, issue, _, _, reference = restored(s)
    prepare_verification(s, demand, issue)
    base = f"/api/projects/{demand.project}/issues/{issue}"
    card = client.get(base + "/work-card", headers=headers(s.peer)).json()
    capture(s, 1, 3, quality="frozen")
    before = counts(s, tables.issues, tables.events, tables.audit_log)
    result = client.post(
        base + "/transitions",
        headers=headers(s.peer),
        json={
            "to_status": "closed",
            "expected_updated_at": card["item"]["updated_at"],
            "closure_evidence_ref": "Retained original input",
            "material_closures": [reference.model_dump(mode="json")],
        },
    )
    assert result.status_code == 409, result.text
    assert result.json()["detail"]["code"] == "ISSUE_MATERIAL_SOURCE_CHANGED"
    assert counts(s, tables.issues, tables.events, tables.audit_log) == before
    latest = client.get(base + "/work-card", headers=headers(s.peer)).json()
    assert latest["item"]["status"] == "verification"
    assert not latest["material_closure"]["ready"]
    assert latest["material_closure"]["items"][0]["closure"]["reference"] is None
    with s.engine.begin() as c:
        c.execute(
            tables.project_members.delete().where(
                tables.project_members.c.tenant_id == s.owner.tenant.id,
                tables.project_members.c.project_id == demand.project,
                tables.project_members.c.user_id == s.peer.user.id,
            )
        )
    assert client.get(base + "/work-card", headers=headers(s.peer)).status_code == 403


def test_non_material_issue_retains_existing_close_and_rejects_foreign_reference(
    recovery_scope: SupplyPostgresScope, client: TestClient
) -> None:
    s = recovery_scope
    service = IssueService(s.engine)
    item = service.create(
        tenant_id=s.owner.tenant.id,
        actor_user_id=s.owner.user.id,
        project_id=s.project,
        draft=IssueDraft(
            title="Ordinary synthetic Issue",
            severity="low",
            stage_id=None,
            owner_user_id=None,
            verifier_user_id=None,
            sample_id=None,
            description=None,
            issue_type="engineering",
            root_cause=None,
            resolution=None,
            closure_criteria=None,
            target_date=None,
        ),
    )
    with s.engine.begin() as c:
        c.execute(
            update(tables.issues).where(tables.issues.c.id == item.id).values(status="verification")
        )
    base = f"/api/projects/{s.project}/issues/{item.id}"
    card = client.get(base + "/work-card", headers=headers(s.owner)).json()
    assert card["material_closure"] == {"required": False, "ready": True, "items": []}
    invalid = client.post(
        base + "/transitions",
        headers=headers(s.owner),
        json={
            "to_status": "closed",
            "material_closures": [
                {
                    "exception_id": str(uuid4()),
                    "review_id": str(uuid4()),
                    "source_digest": "a" * 64,
                }
            ],
        },
    )
    assert invalid.status_code == 409
    result = client.post(
        base + "/transitions",
        headers=headers(s.owner),
        json={
            "to_status": "closed",
            "expected_updated_at": card["item"]["updated_at"],
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "closed"
