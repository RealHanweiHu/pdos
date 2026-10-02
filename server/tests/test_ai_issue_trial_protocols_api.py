"""Isolated synthetic publication fixture; no model call or real qualification."""

# ruff: noqa: F811
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from app.ai.application_domain_context import bundle
from app.ai.issue_event_proposal import OPERATION
from app.ai.write_policy import POLICY_VERSION, WRITE_OPERATIONS
from app.db.schema import tables
from app.domain.product_workspace import digest
from tests.test_issue_evaluation_publication import configured_file, fixture_document
from tests.test_test_runs_api import (
    PASSWORD,
    Scope,
    bearer_headers,
    client,  # noqa: F401
    isolated_test_run_database,  # noqa: F401
)


def ok(reply: Any) -> dict[str, Any]:
    assert reply.status_code == 200, reply.text
    assert reply.headers["cache-control"] == "no-store"
    return dict(reply.json())


def test_preregister_bound_originals_replay_scope_changes_and_history(
    client: TestClient,
    isolated_test_run_database: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        project, headers = scope.project(), bearer_headers(client)
        base = f"/api/projects/{project}/ai-issue-trials"
        grant_base = f"/api/projects/{project}/ai-issue-applications/scope"
        assert ok(client.get(base + "/preparation", headers=headers))["blockers"]
        settings = ok(client.get("/api/ai/governance/write-policy", headers=headers))
        settings["operation_settings"][OPERATION]["mode"] = "confirm"
        policy = ok(
            client.post(
                "/api/ai/governance/write-policy",
                headers=headers,
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": settings["revision"],
                    "mode": "tiered",
                    "operation_settings": settings["operation_settings"],
                    "reason": "隔离模拟：仅登记试运行，不启用模型或自动建单",
                },
            )
        )
        assert ok(client.get(base + "/preparation", headers=headers))["candidates"] == []
        ok(
            client.post(
                grant_base,
                headers=headers,
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": 0,
                    "enabled": True,
                    "reason": "隔离模拟：固定项目授权",
                },
            )
        )
        assert ok(client.get(base + "/preparation", headers=headers))["candidates"] == []
        with scope.engine.connect() as c:
            now = c.execute(select(func.clock_timestamp())).scalar_one()
        document = fixture_document()
        # Claims in this temporary artifact are synthetic test inputs, not external evidence.
        document.update(
            tenant_id=str(scope.tenant_id),
            published_at=(now - timedelta(hours=1)).isoformat(),
            valid_from=(now - timedelta(minutes=30)).isoformat(),
            valid_until=(now + timedelta(days=2)).isoformat(),
        )
        entry = document["evaluations"][0]
        runtime = bundle("event_issue")
        binding = entry["evaluation"]["binding"]
        binding.update(
            policy_version=POLICY_VERSION,
            policy_revision=policy["policy"]["revision"],
            release_bundle_version="sha256:" + digest(runtime),
            adapter_version=runtime["compiled"]["reader"],
        )
        entry["evaluation"].update(
            outcome="passed", completed_at=(now - timedelta(hours=2)).isoformat()
        )
        entry["golden_fixed_at"] = (now - timedelta(days=2)).isoformat()
        for call in entry["original_calls"]:
            call.update(
                tenant_id=str(scope.tenant_id),
                binding=deepcopy(binding),
                started_at=(now - timedelta(hours=4)).isoformat(),
                completed_at=(now - timedelta(hours=3)).isoformat(),
            )
        environment = configured_file(tmp_path, document)
        for key, value in environment.items():
            monkeypatch.setenv(key, value)
        ready = ok(client.get(base + "/preparation", headers=headers))
        assert ready["can_register"] and len(ready["candidates"]) == 1
        candidate = ready["candidates"][0]
        body = {
            "request_id": str(uuid4()),
            "preparation_digest": candidate["key"],
            "binding": candidate["binding"],
            "evidence_kind": "synthetic",
            "window_start": (now - timedelta(days=1)).isoformat(),
            "window_end": now.isoformat(),
            "configuration": {
                "minimum_handled_runs": 20,
                "minimum_followup_seconds": 3600,
                "sampling_basis_points": 10000,
                "confirmation_basis": "retained_original",
                "recovery_protocol_version": "fixture-recovery-v1",
                "recovery_conditions": "模拟：暂停后重新核对原评测和具名授权",
            },
            "reason": "隔离模拟合同登记；不是真实模型原件或资格",
        }
        first = ok(client.post(base, headers=headers, json=body))
        protocol = first["protocol"]
        assert first["replayed"] is False and protocol["qualification_granted"] is False
        assert protocol["binding_label"] == candidate["label"]
        assert protocol["configuration"]["minimum_confirmation_basis_points"] == 9000
        assert protocol["configuration"]["maximum_retraction_basis_points"] == 500
        assert ok(client.post(base, headers=headers, json=body)) == {
            "protocol": protocol,
            "replayed": True,
        }
        assert ok(client.get(base + "/" + protocol["id"], headers=headers)) == protocol
        assert (
            client.post(base, headers=headers, json={**body, "reason": "changed"}).status_code
            == 409
        )
        assert (
            client.post(
                base,
                headers=headers,
                json={**body, "request_id": str(uuid4()), "evidence_kind": "real_business"},
            ).json()["detail"]["code"]
            == "TRIAL_REQUIRES_PREREGISTRATION"
        )
        for _ in range(20):
            ok(client.post(base, headers=headers, json={**body, "request_id": str(uuid4())}))
        page = ok(client.get(base, headers=headers))
        assert len(page["items"]) == 20 and page["next_before_id"]
        tail = ok(client.get(base, headers=headers, params={"before_id": page["next_before_id"]}))
        assert [p["id"] for p in tail["items"]] == [protocol["id"]] and tail[
            "next_before_id"
        ] is None
        assert (
            client.get(base, headers=headers, params={"before_id": str(uuid4())}).status_code == 409
        )
        assert client.get(base + "/" + str(uuid4()), headers=headers).status_code == 404
        with pytest.raises(DBAPIError), scope.engine.begin() as c:
            c.execute(
                tables.ai_issue_trial_protocols.update().values(evidence_kind="real_business")
            )
        ok(
            client.post(
                grant_base,
                headers=headers,
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": 1,
                    "enabled": False,
                    "reason": "模拟：撤回项目授权",
                },
            )
        )
        assert ok(client.get(base + "/preparation", headers=headers))["candidates"] == []
        assert (
            client.post(base, headers=headers, json={**body, "request_id": str(uuid4())}).json()[
                "detail"
            ]["code"]
            == "TRIAL_PREPARATION_CHANGED"
        )
        assert ok(client.post(base, headers=headers, json=body))["protocol"] == protocol
        assert ok(client.get(base + "/" + protocol["id"], headers=headers)) == protocol
        for key in environment:
            monkeypatch.delenv(key)
        assert ok(client.get(base + "/" + protocol["id"], headers=headers)) == protocol
        user = client.post(
            "/api/admin/users",
            headers=headers,
            json={
                "username": "trial-supplier",
                "display_name": "隔离模拟供方",
                "role": "supplier",
                "password": PASSWORD,
            },
        )
        assert user.status_code == 201, user.text
        login = client.post(
            "/api/auth/login",
            json={"tenant_slug": "beepump", "username": "trial-supplier", "password": PASSWORD},
        )
        assert login.status_code == 200, login.text
        forbidden = {"Authorization": "Bearer " + login.json()["access_token"]}
        for path in (base, base + "/preparation", base + "/" + protocol["id"]):
            assert client.get(path, headers=forbidden).status_code == 403
        assert client.post(base, headers=forbidden, json=body).status_code == 403
        assert (
            client.get(
                f"/api/projects/{uuid4()}/ai-issue-trials/{protocol['id']}", headers=headers
            ).status_code
            == 404
        )
        # A different readable project cannot see the original protocol or cursor.
        other_workflow = scope._insert(
            tables.workflows, {"code": "WF-OTHER", "name": "Other workflow"}
        )
        other = scope._insert(
            tables.projects,
            {
                "workflow_id": other_workflow,
                "owner_user_id": scope.owner_id,
                "code": "OTHER",
                "name": "Other project",
                "status": "active",
            },
        )
        other_base = f"/api/projects/{other}/ai-issue-trials"
        assert client.get(other_base + "/" + protocol["id"], headers=headers).status_code == 404
        assert (
            client.get(
                other_base, headers=headers, params={"before_id": protocol["id"]}
            ).status_code
            == 409
        )
        assert client.post(other_base, headers=headers, json=body).status_code == 409
        # No rollout, trial-ready flag, AI run, or business Issue changed by registration.
        assert WRITE_OPERATIONS[OPERATION].trial_ready is True
        with scope.engine.connect() as c:
            assert c.execute(select(func.count()).select_from(tables.agent_runs)).scalar_one() == 0
            assert c.execute(select(func.count()).select_from(tables.issues)).scalar_one() == 0
    finally:
        scope.dispose()
