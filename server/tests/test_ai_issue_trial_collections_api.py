"""Isolated HTTP collection over real receipts and synthetic transport/publication.

Only a dedicated disposable database may execute this test. Synthetic publication
claims are temporary test fixtures, never actual evaluation or qualification.
"""

# ruff: noqa: F811
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import DBAPIError

from app.ai.application_domain_context import bundle
from app.ai.issue_event_proposal import OPERATION
from app.ai.write_policy import POLICY_VERSION
from app.db.schema import tables
from app.db.url import psycopg_database_url
from app.domain.product_workspace import digest
from tests.test_ai_issue_proposal_reviews_api import (
    test_generation_binding_review_history_replay_and_application_guards as exercise_chain,
)
from tests.test_application_budget_factory import factory_setup  # noqa: F401
from tests.test_issue_evaluation_publication import configured_file, fixture_document
from tests.test_issue_event_runs_api import fixture_meter  # noqa: F401
from tests.test_test_runs_api import (
    PASSWORD,
    bearer_headers,
    client,  # noqa: F401
    isolated_test_run_database,  # noqa: F401
)


def ok(reply: Any) -> dict[str, Any]:
    assert reply.status_code == 200, reply.text
    assert reply.headers["cache-control"] == "no-store"
    return dict(reply.json())


def conflict(reply: Any, code: str) -> None:
    assert reply.status_code == 409, reply.text
    assert reply.json()["detail"]["code"] == code, reply.text


def test_registered_collection_preserves_unmatched_originals_replay_and_concurrent_history(
    client: TestClient,
    isolated_test_run_database: str,
    factory_setup: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    exercise_chain(client, isolated_test_run_database, factory_setup, monkeypatch)
    _, calls, _ = factory_setup
    assert len(calls) == 3
    engine = create_engine(psycopg_database_url(isolated_test_run_database))
    try:
        headers = bearer_headers(client)
        original_tables = (
            tables.agent_runs,
            tables.ai_issue_event_results,
            tables.ai_issue_generation_bindings,
            tables.ai_issue_proposal_reviews,
            tables.ai_issue_applications,
            tables.issues,
        )
        with engine.connect() as c:
            runs = list(
                c.execute(
                    select(tables.agent_runs).where(
                        tables.agent_runs.c.context_version == "event-issue-request-v1"
                    )
                ).mappings()
            )
            assert len(runs) == 3
            tenant, project = runs[0]["tenant_id"], runs[0]["project_id"]
            assert all(r["tenant_id"] == tenant and r["project_id"] == project for r in runs)
            originals = {
                t.name: [
                    dict(r)
                    for r in c.execute(
                        select(t)
                        .where(t.c.tenant_id == tenant, t.c.project_id == project)
                        .order_by(t.c.id)
                    ).mappings()
                ]
                for t in original_tables
            }
            now = c.execute(select(func.clock_timestamp())).scalar_one()
        assert len(originals["issues"]) == 1
        assert len(originals["ai_issue_generation_bindings"]) == 3
        assert len(originals["ai_issue_proposal_reviews"]) == 24
        base = f"/api/projects/{project}/ai-issue-trials"
        grant_url = f"/api/projects/{project}/ai-issue-applications/scope"
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
                    "reason": "隔离模拟：登记当前政策，不补记原生成版本",
                },
            )
        )
        previous_scope = ok(client.get(grant_url, headers=headers))["scope"]
        assert previous_scope["enabled"] is False
        ok(
            client.post(
                grant_url,
                headers=headers,
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": previous_scope["revision"],
                    "enabled": True,
                    "reason": "隔离模拟：重新授权登记，不替换旧scope",
                },
            )
        )
        document = fixture_document()
        document.update(
            tenant_id=str(tenant),
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
                tenant_id=str(tenant),
                binding=deepcopy(binding),
                started_at=(now - timedelta(hours=4)).isoformat(),
                completed_at=(now - timedelta(hours=3)).isoformat(),
            )
        environment = configured_file(tmp_path, document)
        for key, value in environment.items():
            monkeypatch.setenv(key, value)
        candidate = ok(client.get(base + "/preparation", headers=headers))["candidates"][0]
        registration = {
            "request_id": str(uuid4()),
            "preparation_digest": candidate["key"],
            "binding": candidate["binding"],
            "evidence_kind": "synthetic",
            "window_start": (min(r["created_at"] for r in runs) - timedelta(seconds=1)).isoformat(),
            "window_end": now.isoformat(),
            "configuration": {
                "minimum_handled_runs": 20,
                "minimum_followup_seconds": 86400,
                "sampling_basis_points": 10000,
                "confirmation_basis": "retained_original",
                "recovery_protocol_version": "fixture-recovery-v1",
                "recovery_conditions": "模拟：重新核对原件和具名授权",
            },
            "reason": "仅隔离模拟采集，不是真实provider评测或资格",
        }
        protocol = ok(client.post(base, headers=headers, json=registration))["protocol"]
        other_protocol = ok(
            client.post(base, headers=headers, json={**registration, "request_id": str(uuid4())})
        )["protocol"]
        future = ok(
            client.post(
                base,
                headers=headers,
                json={
                    **registration,
                    "request_id": str(uuid4()),
                    "window_start": (now + timedelta(days=1)).isoformat(),
                    "window_end": (now + timedelta(days=2)).isoformat(),
                },
            )
        )["protocol"]
        url = base + f"/{protocol['id']}/collections"
        other_url = base + f"/{other_protocol['id']}/collections"
        current_url = base + f"/{protocol['id']}/current"
        empty_current = ok(client.get(current_url, headers=headers))
        assert empty_current["state"] == "unavailable"
        assert empty_current["latest_collection_id"] is None
        assert empty_current["original_result"] is None and empty_current["fresh_result"] is None
        assert empty_current["qualification_granted"] is False
        assert "collection_missing" in {r["code"] for r in empty_current["reasons"]}
        assert ok(client.get(url, headers=headers))["items"] == []
        request = {"request_id": str(uuid4())}
        first_reply = ok(client.post(url, headers=headers, json=request))
        first = first_reply["collection"]
        assert first_reply["replayed"] is False
        assert first["selection_complete"] is True and first["qualification_granted"] is False
        assert first["total_runs"] == first["counts"]["total_runs"] == len(first["items"]) == 3
        assert first["matching_runs"] == first["matching_counts"]["total_runs"] == 0
        assert {i["run_id"] for i in first["items"]} == {str(r["id"]) for r in runs}
        for key, expected in {
            "succeeded_runs": 3,
            "proposal_runs": 3,
            "created_issues": 1,
            "insufficient_runs": 1,
            "same_source_applied_runs": 1,
            "failed_runs": 0,
            "pending_runs": 0,
            "reused_issues": 0,
            "human_edited_issues": 0,
            "withdrawn_issues": 0,
            "trial_candidates": 2,
            "evidence_only_runs": 1,
        }.items():
            assert first["counts"][key] == expected
        initial_current = ok(client.get(current_url, headers=headers))
        assert initial_current["latest_collection_id"] == first["id"]
        assert initial_current["latest_collection_as_of"] == first["as_of"]
        assert initial_current["qualification_granted"] is False
        assert initial_current["original_result"] is not None
        assert initial_current["fresh_result"] is not None
        assert initial_current["state"] != "current"
        assert "non_business_evidence" in {r["code"] for r in initial_current["reasons"]}
        for result_key in ("original_result", "fresh_result"):
            checked = initial_current[result_key]
            assert checked["total_runs"] == checked["counts"]["total_runs"] == 3
            assert checked["matching_runs"] == 0
            assert checked["qualification_granted"] is False
            assert checked["status"] == "insufficient_evidence"
        assert "sampling_evidence_missing" not in {r["code"] for r in first["blockers"]}
        assert "sampling_evidence_missing" not in {
            r["code"] for r in initial_current["fresh_result"]["reasons"]
        }
        assert initial_current["operational_requirements"][0]["code"] == "t0_continuous_sampling"
        assert ok(client.get(url + "/" + first["id"], headers=headers)) == first
        assert first["criteria"]["followup_complete"] is False
        for ratio in ("confirmation", "withdrawal"):
            assert first["criteria"][ratio]["denominator"] == 0
            assert first["criteria"][ratio]["basis_points"] is None
        with engine.connect() as c:
            for item in first["items"]:
                assert item["provider_verified"] is False
                assert item["match"]["matches_protocol"] is False
                assert "generation_control_mismatch" in {
                    r["code"] for r in item["match"]["reasons"]
                }
                proof = item["provenance"]
                assert proof["provider_verified"] is False
                assert proof["provenance_verified"] is False and proof["binding"] is None
                assert "provider_unverified" in {r["code"] for r in proof["reasons"]}
                refs = proof["references"]
                for key, table in (
                    ("result_id", tables.ai_issue_event_results),
                    ("invocation_id", tables.model_invocations),
                    ("observation_id", tables.application_context_observations),
                    ("checkpoint_id", tables.application_result_checkpoints),
                    ("manifest_id", tables.application_context_manifests),
                    ("admission_id", tables.budget_journal),
                ):
                    assert refs[key]
                    row = (
                        c.execute(
                            select(table).where(
                                table.c.tenant_id == tenant,
                                table.c.id == UUID(refs[key]),
                                table.c.run_id == UUID(item["run_id"]),
                            )
                        )
                        .mappings()
                        .one()
                    )
                    if key == "checkpoint_id":
                        assert str(row["invocation_id"]) == refs["invocation_id"]
                        assert str(row["observation_id"]) == refs["observation_id"]
                        assert str(row["manifest_id"]) == refs["manifest_id"]
                    elif key == "manifest_id":
                        assert str(row["admission_id"]) == refs["admission_id"]
        assert ok(client.post(url, headers=headers, json=request)) == {
            "collection": first,
            "replayed": True,
        }
        assert ok(client.get(url + "/" + first["id"], headers=headers)) == first
        conflict(client.post(other_url, headers=headers, json=request), "REQUEST_ID_REUSED")
        conflict(
            client.post(
                base + f"/{future['id']}/collections",
                headers=headers,
                json={"request_id": str(uuid4())},
            ),
            "TRIAL_WINDOW_OPEN",
        )
        assert client.get(other_url + "/" + first["id"], headers=headers).status_code == 404
        conflict(
            client.get(other_url, headers=headers, params={"before_id": first["id"]}),
            "CURSOR_INVALID",
        )

        barrier = Barrier(2)
        concurrent_request = {"request_id": str(uuid4())}

        def capture_once() -> dict[str, Any]:
            barrier.wait(timeout=10)
            return ok(client.post(url, headers=headers, json=concurrent_request))

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(capture_once) for _ in range(2)]
            replies = [f.result(timeout=60) for f in futures]
        assert replies[0]["collection"] == replies[1]["collection"]
        assert sorted(r["replayed"] for r in replies) == [False, True]
        with engine.connect() as c:
            assert (
                c.execute(
                    select(func.count())
                    .select_from(tables.ai_issue_trial_collections)
                    .where(
                        tables.ai_issue_trial_collections.c.request_id
                        == UUID(concurrent_request["request_id"])
                    )
                ).scalar_one()
                == 1
            )

        grant = ok(client.get(grant_url, headers=headers))["scope"]
        ok(
            client.post(
                grant_url,
                headers=headers,
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": grant["revision"],
                    "enabled": False,
                    "reason": "模拟：暂停授权仍可采集原登记证据",
                },
            )
        )
        for key in environment:
            monkeypatch.delenv(key)
        (tmp_path / "synthetic-unit-fixture.json").unlink()
        paused_current = ok(client.get(current_url, headers=headers))
        assert paused_current["state"] == "blocked"
        assert paused_current["qualification_granted"] is False
        assert {"scope_changed", "publication_unavailable"} <= {
            r["code"] for r in paused_current["reasons"]
        }
        assert paused_current["latest_collection_id"] == replies[0]["collection"]["id"]
        assert ok(client.get(url + "/" + first["id"], headers=headers)) == first
        identities = {first["id"], replies[0]["collection"]["id"]}
        for _ in range(19):
            captured = ok(client.post(url, headers=headers, json={"request_id": str(uuid4())}))[
                "collection"
            ]
            assert captured["total_runs"] == 3 and captured["matching_runs"] == 0
            assert captured["qualification_granted"] is False
            identities.add(captured["id"])
        assert len(identities) == 21
        page = ok(client.get(url, headers=headers))
        assert len(page["items"]) == 20 and page["next_before_id"]
        latest_current = ok(client.get(current_url, headers=headers))
        assert latest_current["latest_collection_id"] == page["items"][0]["id"]
        assert latest_current["latest_collection_id"] != first["id"]
        assert latest_current["latest_collection_as_of"] == page["items"][0]["as_of"]
        assert latest_current["state"] == "blocked"
        assert latest_current["qualification_granted"] is False
        unknown_current = client.get(base + f"/{uuid4()}/current", headers=headers)
        assert unknown_current.status_code == 404
        assert unknown_current.headers["cache-control"] == "no-store"
        tail = ok(client.get(url, headers=headers, params={"before_id": page["next_before_id"]}))
        assert [v["id"] for v in tail["items"]] == [first["id"]]
        assert tail["next_before_id"] is None
        assert {v["id"] for v in page["items"] + tail["items"]} == identities
        assert ok(client.get(url + "/" + first["id"], headers=headers)) == first
        assert ok(client.post(url, headers=headers, json=request))["collection"] == first
        with pytest.raises(DBAPIError) as caught, engine.begin() as c:
            c.execute(
                tables.ai_issue_trial_collections.update()
                .where(tables.ai_issue_trial_collections.c.id == UUID(first["id"]))
                .values(collection_digest="0" * 64)
            )
        assert getattr(caught.value.orig, "sqlstate", None) == "42501"

        user = client.post(
            "/api/admin/users",
            headers=headers,
            json={
                "username": "collection-supplier",
                "display_name": "模拟供方",
                "role": "supplier",
                "password": PASSWORD,
            },
        )
        assert user.status_code == 201, user.text
        login = client.post(
            "/api/auth/login",
            json={
                "tenant_slug": "beepump",
                "username": "collection-supplier",
                "password": PASSWORD,
            },
        )
        assert login.status_code == 200, login.text
        forbidden = {"Authorization": "Bearer " + login.json()["access_token"]}
        for path in (url, url + "/" + first["id"], current_url):
            denied = client.get(path, headers=forbidden)
            assert denied.status_code == 403
            assert denied.headers["cache-control"] == "no-store"
        assert (
            client.post(url, headers=forbidden, json={"request_id": str(uuid4())}).status_code
            == 403
        )
        assert len(calls) == 3
        with engine.connect() as c:
            for t in original_tables:
                assert [
                    dict(r)
                    for r in c.execute(
                        select(t)
                        .where(t.c.tenant_id == tenant, t.c.project_id == project)
                        .order_by(t.c.id)
                    ).mappings()
                ] == originals[t.name]
            assert (
                c.execute(
                    select(func.count())
                    .select_from(tables.ai_issue_trial_collections)
                    .where(
                        tables.ai_issue_trial_collections.c.tenant_id == tenant,
                        tables.ai_issue_trial_collections.c.project_id == project,
                    )
                ).scalar_one()
                == 21
            )
    finally:
        engine.dispose()
