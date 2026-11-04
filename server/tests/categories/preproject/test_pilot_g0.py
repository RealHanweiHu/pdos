"""P27 keeps self-review confined to current pilot humans and named T2 commands."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent.kernel.models import TenantPilotAdmission
from pdos_next.core.models import Grant
from pdos_next.domain.categories.preproject.models import ProposalDecision
from tests.categories.preproject.test_g0 import create, post, read, request, save
from tests.categories.preproject.test_g0 import work as work  # noqa: F401


def admit(work):
    with Session(work.admin) as s, s.begin():
        s.get(TenantPilotAdmission, work.tenant).active = True
        s.scalar(
            select(Grant).where(
                Grant.principal_id == work.human, Grant.category_id == work.category
            )
        ).product_manager = True


def self_submit(work, proposal_id):
    row = read(work, proposal_id).json()
    return request(
        work,
        "proposal.g0.submit",
        {
            "proposal_id": proposal_id,
            "expected_revision": row["revision"],
            "reviewer_id": str(work.human),
        },
        revision=row["revision"],
    )


def decision(work, proposal_id):
    row = read(work, proposal_id).json()
    return request(
        work,
        "proposal.g0.decide",
        {
            "proposal_id": proposal_id,
            "submission_id": row["submission"]["id"],
            "expected_revision": row["revision"],
            "outcome": "approved",
            "rationale": "Synthetic named pilot self-review",
            "selected_option_item_id": next(
                i["item_id"] for i in row["items"] if i["kind"] == "option"
            ),
            "project": {"name": "P27 synthetic project", "owner_id": str(work.human)},
            "dispositions": [
                {
                    "subject_type": i["subject_type"],
                    "subject_id": i["subject_id"],
                    "kind": "risk",
                    "owner_id": str(work.human),
                    "due_date": "2026-11-20",
                    "note": i["title"],
                }
                for i in row["maturity"]["required_dispositions"]
            ],
        },
        revision=row["revision"],
    )


def test_pilot_owner_appears_and_named_decision_creates_project_once(work):
    admit(work)
    pid, _ = create(work)
    people = work.client.get(
        f"/v1/categories/{work.category}/proposals/{pid}/participants", headers=work.headers
    ).json()["items"]
    assert next(p for p in people if p["id"] == str(work.human))["reviewer_eligible"]
    save(work, self_submit(work, pid))
    cmd = decision(work, pid)
    assert post(work, cmd).status_code != 200  # A raw T2 request cannot stand in for approval.
    receipt, confirmed = save(work, cmd)
    assert receipt["result"]["project_id"] and receipt["result"]["definition_id"]
    assert post(work, confirmed).json()["id"] == receipt["id"]
    with Session(work.admin) as s:
        fact = s.scalar(
            select(ProposalDecision).where(ProposalDecision.receipt_id == UUID(receipt["id"]))
        )
        assert fact.owner_id == fact.decided_by == work.human


def test_pilot_removal_or_revoked_manager_blocks_prepared_self_decision(work):
    admit(work)
    pid, _ = create(work)
    save(work, self_submit(work, pid))
    preview = post(work, decision(work, pid), preview=True)
    assert preview.status_code == 200, preview.text
    with Session(work.admin) as s, s.begin():
        s.get(TenantPilotAdmission, work.tenant).active = False
    assert post(work, preview.json()["command"]).status_code != 200
    assert read(work, pid).json()["status"] == "in_review"
    with Session(work.admin) as s, s.begin():
        s.get(TenantPilotAdmission, work.tenant).active = True
        s.scalar(
            select(Grant).where(
                Grant.principal_id == work.human, Grant.category_id == work.category
            )
        ).product_manager = False
    assert post(work, preview.json()["command"]).status_code != 200


def test_pilot_self_review_is_listed_under_decide_and_blocked_after_the_pilot_ends(work):
    """D25: a P27 self-review reaches the owner's own decide queue."""

    def decide_queue():
        response = work.client.get(
            "/v1/personal/attention",
            params={"queue": "decide", "page_size": 20},
            headers=work.headers,
        )
        assert response.status_code == 200, response.text
        return [item for item in response.json()["items"] if item["kind"] == "g0_review"]

    admit(work)
    pid, _ = create(work)
    save(work, self_submit(work, pid))
    (item,) = decide_queue()
    assert item["source"]["id"] == pid and item["responsible"]["id"] == str(work.human)
    assert item["blocked"] is None

    with Session(work.admin) as s, s.begin():
        s.get(TenantPilotAdmission, work.tenant).active = False
    (item,) = decide_queue()
    assert item["blocked"]["code"] == "NAMED_DECISION_REQUIRED"
