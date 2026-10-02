"""Issue escalation and independent CAPA closure through production HTTP services.

Only synthetic records in the explicitly isolated test database; no model calls.
"""

from __future__ import annotations

# Imported pytest fixtures intentionally share test parameter names.
# ruff: noqa: F811
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.roles import Role
from app.db.engine import get_engine
from app.db.schema import tables
from tests.test_quality_capa_api import (
    SETUP_PAYLOAD,
    client,  # noqa: F401
    isolated_quality_database,  # noqa: F401
    login,
    seed_project_and_engineer,
    seed_project_user,
)


class QualityLoop:
    def __init__(self, http_client: TestClient, database_url: str) -> None:
        self.client = http_client
        setup = http_client.post("/api/setup", json=SETUP_PAYLOAD).json()
        self.tenant, self.owner = UUID(setup["tenant"]["id"]), UUID(setup["user"]["id"])
        self.project, self.engineer = seed_project_and_engineer(
            database_url, self.tenant, self.owner
        )
        self.quality = seed_project_user(
            database_url,
            self.tenant,
            self.project,
            self.owner,
            username="quality",
            role=Role.QUALITY,
        )
        self.reviewer = seed_project_user(
            database_url,
            self.tenant,
            self.project,
            self.owner,
            username="reviewer",
            role=Role.QUALITY,
        )
        self.headers = {
            name: login(http_client, name) for name in ("owner", "engineer", "quality", "reviewer")
        }
        self.base = f"/api/projects/{self.project}"
        self.links = self.base + "/quality/issue-links"
        self.target_date = (date.today() + timedelta(days=7)).isoformat()
        self.case = uuid4()
        with get_engine().begin() as connection:
            project = (
                connection.execute(
                    select(tables.projects).where(tables.projects.c.id == self.project)
                )
                .mappings()
                .one()
            )
            plan = uuid4()
            connection.execute(
                tables.test_plans.insert(),
                {
                    "id": plan,
                    "tenant_id": self.tenant,
                    "project_id": self.project,
                    "workflow_id": project["workflow_id"],
                    "stage_id": project["current_stage_id"],
                    "created_by_user_id": self.owner,
                    "phase": "pvt",
                    "title": "Synthetic quality retest",
                    "sample_size": 3,
                    "status": "active",
                },
            )
            connection.execute(
                tables.test_cases.insert(),
                {
                    "id": self.case,
                    "tenant_id": self.tenant,
                    "project_id": self.project,
                    "plan_id": plan,
                    "created_by_user_id": self.owner,
                    "title": "Leak retest",
                    "category": "reliability",
                    "acceptance_criteria": "Leak rate <= 0.1 sccm",
                    "severity": "critical",
                    "status": "planned",
                },
            )
        failed = self.run("failed", 0.4)
        self.issue = failed["related_issue_id"]
        response = http_client.patch(
            self.base + f"/issues/{self.issue}",
            headers=self.headers["owner"],
            json={
                "owner_user_id": str(self.engineer),
                "verifier_user_id": str(self.reviewer),
                "closure_criteria": "Independent review of passing leak retest",
                "target_date": self.target_date,
            },
        )
        assert response.status_code == 200, response.text

    def run(self, status: str, leak: float) -> dict[str, Any]:
        response = self.client.post(
            self.base + f"/npi/test-cases/{self.case}/runs",
            headers=self.headers["engineer"],
            json={
                "status": status,
                "equipment": "Synthetic LT-3",
                "result_notes": "Synthetic integration scenario",
                "metrics": [
                    {
                        "name": "leak_rate",
                        "value": leak,
                        "unit": "sccm",
                        "target": 0.1,
                        "verdict": "pass" if status == "passed" else "fail",
                    }
                ],
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    def listing(self, *, ncr: bool = False) -> dict[str, Any]:
        response = self.client.get(
            self.links,
            headers=self.headers["quality"],
            params={"ncr_id" if ncr else "issue_id": self.ncr if ncr else self.issue},
        )
        assert response.status_code == 200, response.text
        assert "no-store" in response.headers["cache-control"]
        return response.json()

    def escalation(self) -> dict[str, Any]:
        current = self.listing()
        return {
            "request_id": str(uuid4()),
            "issue_id": self.issue,
            "expected_issue_digest": current["anchor_digest"],
            "expected_links_digest": current["links_digest"],
            "owner_user_id": str(self.quality),
            "title": "Leak quality correction",
            "source": "internal",
            "occurred_at": datetime.now(UTC).isoformat(),
            "nonconformity": "Leak rate 0.4 exceeds 0.1 sccm",
            "requirement_reference": "Leak retest acceptance criteria",
            "severity": "critical",
            "target_date": self.target_date,
            "reason": "Observed nonconformity requires independent quality investigation",
        }

    def escalate(self) -> dict[str, Any]:
        payload = self.escalation()
        first = self.client.post(
            self.links + "/escalate", headers=self.headers["quality"], json=payload
        )
        assert first.status_code == 200, first.text
        assert (
            self.client.post(
                self.links + "/escalate", headers=self.headers["quality"], json=payload
            ).json()
            == first.json()
        )
        self.ncr = first.json()["ncr_id"]
        self.ncr_url = self.base + f"/quality/ncrs/{self.ncr}"
        return first.json()

    def workspace(self) -> dict[str, Any]:
        response = self.client.get(self.ncr_url + "/workspace", headers=self.headers["quality"])
        assert response.status_code == 200, response.text
        return response.json()

    def evidence(self, run_id: str) -> list[dict[str, Any]]:
        response = self.client.get(
            self.ncr_url + "/evidence?kind=test_run", headers=self.headers["engineer"]
        )
        assert response.status_code == 200, response.text
        record = next(item for item in response.json()["items"] if item["reference"] == run_id)
        return [{key: record[key] for key in ("kind", "reference", "expected_digest")}]

    def command(
        self, actor: str, action: str, *, expected: int = 200, **body: Any
    ) -> dict[str, Any]:
        payload = {
            "request_id": str(uuid4()),
            "expected_digest": self.workspace()["digest"],
            "body": {"action": action, **body},
        }
        response = self.client.post(
            self.ncr_url + "/operations", headers=self.headers[actor], json=payload
        )
        assert response.status_code == expected, response.text
        return response.json()

    def transition(self, status: str, *, expected: int = 200, **fields: Any) -> dict[str, Any]:
        return self.command(
            "quality", "ncr_transition", to_status=status, expected=expected, **fields
        )

    def complete_action(
        self, actor: str, owner: UUID, action_type: str, evidence: list[dict[str, Any]]
    ) -> dict[str, Any]:
        receipt = self.command(
            actor,
            "action_create",
            owner_user_id=str(owner),
            action_type=action_type,
            description="Synthetic corrective/preventive work",
            due_date=self.target_date,
        )
        action_id = receipt["result"]["record"]["id"]
        self.command(actor, "action_transition", action_id=action_id, to_status="in_progress")
        self.command(
            actor,
            "action_transition",
            action_id=action_id,
            to_status="completed",
            expected=404,
            completion_summary="A note alone cannot complete work",
        )
        return self.command(
            actor,
            "action_transition",
            action_id=action_id,
            to_status="completed",
            completion_summary="Work completed; original test evidence attached",
            evidence=evidence,
        )["result"]["record"]


def test_issue_escalation_retest_failure_followup_and_independent_closures(
    client: TestClient,
    isolated_quality_database: str,
) -> None:
    scope = QualityLoop(client, isolated_quality_database)
    relation = scope.escalate()
    reverse = scope.listing(ncr=True)
    assert reverse["items"][0]["id"] == relation["id"]
    assert reverse["items"][0]["issue"]["status"] == "open"
    assert scope.listing()["items"][0]["snapshot"]["ncr"]["status"] == "open"
    duplicate = client.post(
        scope.links + "/escalate", headers=scope.headers["quality"], json=scope.escalation()
    )
    assert duplicate.status_code == 409
    assert len(scope.listing()["items"]) == 1

    scope.transition("containment")
    scope.transition("root_cause", containment_action="Quarantine affected synthetic samples")
    initial = scope.run("failed", 0.3)
    assert initial["related_issue_id"] == scope.issue
    evidence = scope.evidence(initial["id"])
    root = scope.command(
        "engineer",
        "root_create",
        method="5why",
        analysis="Measurements identify seal damage",
        root_cause="Seal geometry mismatch",
        evidence=evidence,
    )["result"]["record"]
    scope.command(
        "engineer", "root_approve", expected=403, root_cause_id=root["id"], evidence=evidence
    )
    scope.command("quality", "root_approve", root_cause_id=root["id"], evidence=evidence)
    scope.transition("action")
    corrective = scope.complete_action("engineer", scope.engineer, "corrective", evidence)
    scope.transition(
        "verification",
        expected=409,
        effectiveness_criteria="Leak <= 0.1",
        observation_due_at=datetime.now(UTC).isoformat(),
    )
    preventive = scope.complete_action("quality", scope.quality, "preventive", evidence)
    assert scope.workspace()["ncr"]["status"] == "action"

    def observe(completed: dict[str, Any]) -> None:
        scope.transition(
            "verification",
            effectiveness_criteria="Leak <= 0.1 sccm after observation",
            observation_due_at=(
                datetime.fromisoformat(completed["completed_at"]) + timedelta(microseconds=1)
            ).isoformat(),
        )

    observe(preventive)
    scope.command(
        "quality",
        "effectiveness_review",
        expected=409,
        result="ineffective",
        actual_result="Still leaks",
        evidence=evidence,
    )
    scope.command(
        "reviewer",
        "effectiveness_review",
        result="ineffective",
        actual_result="Observed leak remains 0.3",
        evidence=evidence,
    )
    assert scope.workspace()["ncr"]["status"] == "action"
    scope.transition(
        "verification",
        expected=409,
        effectiveness_criteria="Leak <= 0.1",
        observation_due_at=datetime.now(UTC).isoformat(),
    )
    followup = scope.complete_action("engineer", scope.engineer, "corrective", evidence)
    assert followup["id"] in scope.workspace()["followup_action_ids"]
    observe(followup)
    passed = scope.run("passed", 0.05)
    pass_evidence = scope.evidence(passed["id"])
    scope.command(
        "reviewer",
        "effectiveness_review",
        result="effective",
        actual_result="Retest leak 0.05 meets criterion",
        evidence=pass_evidence,
    )
    current = scope.workspace()
    assert current["ncr"]["status"] == "verification"
    assert [review["result"] for review in current["reviews"]] == ["ineffective", "effective"]
    for record, run in [
        (corrective, initial),
        (current["reviews"][0], initial),
        (current["reviews"][1], passed),
    ]:
        source = current["record_evidence"][record["id"]][0]
        assert source["available"] is True
        assert source["value"]["id"] == run["id"]
        assert source["value"]["status"] == run["status"]
        assert source["value"]["metrics"][0]["value"] == run["metrics"][0]["value"]
    latest = next(
        r for r in current["receipts"] if r["command"]["action"] == "effectiveness_review"
    )
    assert latest["result"]["evidence_sources"][0]["value"]["id"] == passed["id"]
    scope.transition("closed")
    linked = scope.listing()["items"][0]
    assert linked["ncr"]["status"] == "closed"
    assert linked["issue"]["status"] == "open"
    assert linked["has_later_changes"] is True
    assert linked["snapshot"]["ncr"]["status"] == "open"

    issue_transition = scope.base + f"/issues/{scope.issue}/transitions"
    for status in ("analysis", "action", "verification"):
        response = client.post(
            issue_transition, headers=scope.headers["engineer"], json={"to_status": status}
        )
        assert response.status_code == 200, response.text
    denied = client.post(
        issue_transition,
        headers=scope.headers["engineer"],
        json={"to_status": "closed", "closure_evidence_ref": passed["id"]},
    )
    assert denied.status_code == 409
    closed = client.post(
        issue_transition,
        headers=scope.headers["reviewer"],
        json={"to_status": "closed", "closure_evidence_ref": f"test_run:{passed['id']}"},
    )
    assert closed.status_code == 200, closed.text
    assert scope.listing(ncr=True)["items"][0]["issue"]["status"] == "closed"
    assert scope.workspace()["ncr"]["status"] == "closed"

    # Carry the actual closed quality facts into an explicit FMEA draft, never publish or score.
    candidates_url = scope.base + "/quality/fmea/candidates"
    capture = client.post(candidates_url + "/capture", headers=scope.headers["quality"], json={})
    assert capture.status_code == 200, capture.text
    candidate_id = capture.json()["candidate_ids"][0]
    repeated = client.post(candidates_url + "/capture", headers=scope.headers["quality"], json={})
    assert repeated.json()["candidate_ids"] == [candidate_id]
    candidate_response = client.get(
        candidates_url + f"/{candidate_id}", headers=scope.headers["quality"]
    )
    assert candidate_response.status_code == 200, candidate_response.text
    candidate = candidate_response.json()
    assert candidate["status"] == "pending"
    sources = candidate["snapshot"]["sources"]
    ncr_source = next(source for source in sources if source["kind"] == "ncr")
    assert ncr_source["value"]["id"] == scope.ncr
    assert ncr_source["value"]["approved_root_cause"]["id"] == root["id"]
    assert ncr_source["value"]["latest_effectiveness_review"]["result"] == "effective"
    assert (
        ncr_source["value"]["latest_effectiveness_review"]["evidence_refs"][0]["reference"]
        == passed["id"]
    )
    assert len([source for source in sources if source["kind"] == "capa_action"]) == 3
    draft = {
        "request_id": str(uuid4()),
        "expected_digest": candidate["input_digest"],
        "action": "draft_created",
        "reason": "Human review of closed CAPA and retest",
        "content": {
            "title": "Seal leakage",
            "design_function": "Maintain pressure boundary",
            "failure_mode": "Leak above limit",
            "effect": "Loss of pressure",
            "possible_cause": "Seal geometry mismatch",
            "cause_status": "evidence_supported",
            "control_gaps": "Long-term occurrence still requires measurement",
            "scoring_method": "Human assessment pending",
            "scoring_basis": "No population data",
            "unknown_reason": "Do not infer S/O/D from a passing retest",
            "next_action": "Review broader applicability",
            "reason": "Preserve observed quality facts",
            "references": [
                {
                    "kind": source["kind"],
                    "id": source["id"],
                    "expected_digest": source["expected_digest"],
                    "relationship": "Original quality evidence for this revision",
                }
                for source in sources
            ],
        },
    }
    disposed = client.post(
        candidates_url + f"/{candidate_id}/disposition",
        headers=scope.headers["quality"],
        json=draft,
    )
    assert disposed.status_code == 200, disposed.text
    assert (
        client.post(
            candidates_url + f"/{candidate_id}/disposition",
            headers=scope.headers["quality"],
            json=draft,
        ).json()
        == disposed.json()
    )
    fmea_response = client.get(
        scope.base + f"/quality/fmea/{disposed.json()['entry_id']}",
        headers=scope.headers["quality"],
    )
    assert fmea_response.status_code == 200, fmea_response.text
    fmea = fmea_response.json()
    assert fmea["publication"] is None
    assert all(
        fmea["latest"]["body"][field] is None for field in ("severity", "occurrence", "detection")
    )


def test_link_scope_stale_source_and_retraction_preserve_original_objects(
    client: TestClient,
    isolated_quality_database: str,
) -> None:
    scope = QualityLoop(client, isolated_quality_database)
    stale = scope.escalation()
    changed = client.patch(
        scope.base + f"/issues/{scope.issue}",
        headers=scope.headers["owner"],
        json={"description": "New observed facts"},
    )
    assert changed.status_code == 200, changed.text
    assert (
        client.post(
            scope.links + "/escalate", headers=scope.headers["quality"], json=stale
        ).status_code
        == 409
    )
    assert scope.listing()["items"] == []
    relation = scope.escalate()
    other, _ = seed_project_and_engineer(
        isolated_quality_database,
        scope.tenant,
        scope.owner,
        suffix="OTHER",
        engineer_username="outsider",
    )
    outsider = login(client, "outsider")
    assert (
        client.get(scope.links, headers=outsider, params={"issue_id": scope.issue}).status_code
        == 403
    )
    assert client.get(scope.ncr_url + "/workspace", headers=outsider).status_code == 403
    foreign = client.get(
        f"/api/projects/{other}/quality/ncrs/{scope.ncr}/workspace", headers=scope.headers["owner"]
    )
    assert foreign.status_code == 404, foreign.text
    left, right = scope.listing(), scope.listing(ncr=True)
    link = {
        "request_id": str(uuid4()),
        "issue_id": scope.issue,
        "ncr_id": scope.ncr,
        "expected_issue_digest": left["anchor_digest"],
        "expected_ncr_digest": right["anchor_digest"],
        "reason": "Explicit original pair",
    }
    assert client.post(scope.links, headers=scope.headers["engineer"], json=link).status_code == 409
    foreign_link = client.post(
        f"/api/projects/{other}/quality/issue-links", headers=scope.headers["owner"], json=link
    )
    assert foreign_link.status_code in (404, 409), foreign_link.text
    retract = {
        "request_id": str(uuid4()),
        "expected_digest": left["items"][0]["digest"],
        "reason": "Correct mistaken association",
    }
    url = scope.links + f"/{relation['id']}/retract"
    assert client.post(url, headers=scope.headers["engineer"], json=retract).status_code == 403
    first = client.post(url, headers=scope.headers["quality"], json=retract)
    assert first.status_code == 200, first.text
    assert client.post(url, headers=scope.headers["quality"], json=retract).json() == first.json()
    history = scope.listing()["items"][0]
    assert history["retraction"]["reason"] == retract["reason"]
    assert history["issue"]["status"] == history["ncr"]["status"] == "open"
    assert history["snapshot"] == relation["snapshot"]
    restored = client.post(scope.links, headers=scope.headers["engineer"], json=link)
    assert restored.status_code == 200, restored.text
    assert (
        client.post(scope.links, headers=scope.headers["engineer"], json=link).json()
        == restored.json()
    )
    current = scope.listing()["items"]
    assert len(current) == 2
    assert sum(row["retraction"] is None for row in current) == 1
