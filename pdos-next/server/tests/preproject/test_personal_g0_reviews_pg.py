"""Actual named G0 submissions in the reviewer's read-only personal inbox.

The root runs PostgreSQL verification against its explicitly checked target.
Only ordinary synthetic membership/login setup and current ACL reductions use
the fixture admin; submissions and decisions always use public commands.
"""
# ruff: noqa: F811 -- pytest injects the imported real G0 fixture.

import json
import os
from copy import copy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from pdos_next.clock import now, using_clock
from pdos_next.database import tenant_session
from pdos_next.domain.preproject.models import Proposal, ProposalSubmission
from pdos_next.models import Grant
from tests.preproject.test_category_matrix_pg import counts, unrelated_member
from tests.preproject.test_evidence_commands_pg import share_request
from tests.preproject.test_frozen_source_audience_pg import expert_login
from tests.preproject.test_g0 import create, decide_request, payload, read, request, save, submit
from tests.preproject.test_g0 import work as work
from tests.preproject.test_proposal_views_pg import other_category


def inbox(work, *, actor=None, **params):
    return work.client.get(
        "/v1/personal/g0-reviews",
        params=params,
        headers={"Authorization": f"Bearer {work.tokens[actor or work.peer]}"},
    )


def successful(work, *, actor=None, **params):
    response = inbox(work, actor=actor, **params)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["version"] == "personal-g0-reviews/v1"
    assert data["principal_id"] == str(actor or work.peer)
    assert data["as_of"]
    assert set(data) == {
        "version",
        "principal_id",
        "as_of",
        "total_pending",
        "items",
        "next_cursor",
    }
    for item in data["items"]:
        assert set(item) == {
            "proposal_id",
            "title",
            "proposal_revision",
            "status",
            "category",
            "owner",
            "reviewer_id",
            "submission",
        }
        assert item["status"] == "in_review"
        assert item["reviewer_id"] == data["principal_id"]
        assert set(item["category"]) == {"id", "name"}
        assert set(item["owner"]) == {"id", "name"}
        assert set(item["submission"]) == {"id", "revision", "submitted_at", "document_digest"}
    return data


def pending(work, title, *, reviewer=None):
    body = payload(work)
    body["title"] = title
    identity, _ = create(work, body)
    if reviewer is None or reviewer == work.peer:
        submit(work, identity)
    else:
        row = read(work, identity).json()
        save(
            work,
            request(
                work,
                "proposal.g0.submit",
                {
                    "proposal_id": identity,
                    "expected_revision": row["revision"],
                    "reviewer_id": str(reviewer),
                },
                revision=row["revision"],
            ),
        )
    row = read(work, identity, reviewer or work.peer)
    assert row.status_code == 200, row.text
    return row.json()


def grant_for(session, work, actor=None):
    grant = session.scalar(
        select(Grant).where(
            Grant.tenant_id == work.tenant,
            Grant.category_id == work.category,
            Grant.principal_id == (actor or work.peer),
        )
    )
    assert grant is not None
    return grant


def other_reviewer(work):
    expert_login(work)
    with Session(work.admin) as session, session.begin():
        grant_for(session, work, work.expert).product_manager = True
    return work.expert


def forbidden_cursor(work, cursor, *, actor=None):
    response = inbox(work, actor=actor, cursor=cursor)
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_SCOPE"
    assert "刷新" in response.text
    assert "items" not in response.json()


def export_qa(work, data, documents):
    """Opt-in synthetic browser evidence; response bundles never contain tokens."""
    if destination := os.environ.get("PDOS_G0_INBOX_QA_RESPONSE_PATH"):
        output = Path(destination)
        assert output.is_absolute(), "QA response destination must be absolute"
        headers = {"Authorization": f"Bearer {work.tokens[work.peer]}"}
        session_info = work.client.get("/v1/session", headers=headers)
        categories = work.client.get("/v1/categories", headers=headers)
        assert session_info.status_code == categories.status_code == 200
        proposals = []
        for document in documents:
            participants = work.client.get(
                f"/v1/categories/{work.category}/proposals/{document['id']}/participants",
                headers=headers,
            )
            assert participants.status_code == 200, participants.text
            proposals.append(
                {
                    "category_id": str(work.category),
                    "proposal": document,
                    "participants": participants.json(),
                }
            )
        bundle = {
            "inbox": data,
            "session": session_info.json(),
            "categories": categories.json(),
            "proposals": proposals,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if destination := os.environ.get("PDOS_G0_INBOX_QA_SESSION_PATH"):
        private_path = Path(destination)
        assert private_path.is_absolute(), "QA session destination must be absolute"
        private_path = private_path.resolve()
        private_root = (Path(__file__).resolve().parents[3] / ".local").resolve()
        assert private_path.is_relative_to(private_root), "QA session must stay in pdos-next/.local"
        private_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            private_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600
        )
        identities = [document["id"] for document in documents]
        with os.fdopen(descriptor, "w", encoding="utf-8") as private_file:
            os.fchmod(private_file.fileno(), 0o600)
            json.dump(
                {
                    "token": work.tokens[work.peer],
                    "principal_id": str(work.peer),
                    "category_id": str(work.category),
                    "proposal_id": identities[0],
                    "category_ids": [str(work.category)],
                    "proposal_ids": identities,
                },
                private_file,
            )
            private_file.write("\n")


def test_http_g0_inbox_actual_pending_metadata_no_body_queries_or_business_writes(work):
    documents = [
        pending(work, "合成便携充气泵立项评审"),
        pending(work, "合成自行车充气泵立项评审"),
    ]
    draft_body = payload(work)
    draft_body.update(title="SYNTHETIC_UNSUBMITTED_DRAFT", brief="SYNTHETIC_BODY_NOT_IN_INBOX")
    draft, _ = create(work, draft_body)
    before = counts(work)
    statements = []

    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement.lower())

    event.listen(work.engine, "before_cursor_execute", capture)
    try:
        data = successful(work)
    finally:
        event.remove(work.engine, "before_cursor_execute", capture)
    assert data["total_pending"] == 2 and data["next_cursor"] is None
    assert {item["proposal_id"] for item in data["items"]} == {doc["id"] for doc in documents}
    for document in documents:
        item = next(row for row in data["items"] if row["proposal_id"] == document["id"])
        assert item["title"] == document["title"]
        assert item["proposal_revision"] == document["revision"]
        assert item["category"] == {"id": str(work.category), "name": "汽车充气泵"}
        assert item["owner"]["id"] == str(work.human)
        assert item["submission"]["id"] == document["submission"]["id"]
        assert item["submission"]["revision"] == document["submission"]["revision"]
        assert item["submission"]["document_digest"] == document["submission"]["document_digest"]
    serialized = json.dumps(data, ensure_ascii=False)
    assert draft not in serialized and draft_body["brief"] not in serialized
    assert "frozen_document" not in serialized and "due_date" not in serialized
    assert statements and all("frozen_document" not in sql for sql in statements)
    assert not any(
        sql.lstrip().startswith(("insert ", "update ", "delete "))
        or "proposals.brief" in sql
        or "proposal_item_versions" in sql
        for sql in statements
    )
    assert counts(work) == before
    export_qa(work, data, documents)


def test_http_g0_inbox_only_named_reviewer_not_owner_other_members_or_tenant(work):
    own = pending(work, "合成本人具名待评审")
    expert = other_reviewer(work)
    other = pending(work, "SYNTHETIC_OTHER_REVIEWER_PRIVATE", reviewer=expert)
    peer_data = successful(work)
    assert peer_data["total_pending"] == 1
    assert [item["proposal_id"] for item in peer_data["items"]] == [own["id"]]
    expert_data = successful(work, actor=expert)
    assert expert_data["total_pending"] == 1
    assert [item["proposal_id"] for item in expert_data["items"]] == [other["id"]]
    for actor in (work.human, unrelated_member(work), work.other_human):
        data = successful(work, actor=actor)
        assert data["items"] == [] and data["total_pending"] == 0
        assert data["next_cursor"] is None
        assert own["title"] not in json.dumps(data) and other["title"] not in json.dumps(data)


def test_http_g0_inbox_cross_category_current_grant_expiry_hides_rows_and_cursor(work):
    first = pending(work, "合成仍可评审的本品类提案")
    other = copy(work)
    other.category = UUID(other_category(work))
    other.ctx = replace(work.ctx, category_id=other.category)
    with Session(work.admin) as session, session.begin():
        session.add(
            Grant(
                tenant_id=work.tenant,
                category_id=other.category,
                principal_id=work.peer,
                can_write=False,
                product_manager=True,
                expires_at=now() + timedelta(hours=1),
            )
        )
    second = pending(other, "SYNTHETIC_EXPIRED_CATEGORY_REVIEW")
    before = successful(work)
    assert before["total_pending"] == 2
    assert {item["category"]["id"] for item in before["items"]} == {
        str(work.category),
        str(other.category),
    }
    with Session(work.admin) as session, session.begin():
        grant_for(session, other).expires_at = now() - timedelta(seconds=1)
    with tenant_session(work.engine, work.tenant, actor_id=work.peer) as session:
        assert session.get(Proposal, UUID(second["id"])) is None
    refreshed = successful(work)
    assert refreshed["total_pending"] == 1
    assert [item["proposal_id"] for item in refreshed["items"]] == [first["id"]]
    assert second["title"] not in json.dumps(refreshed)
    assert str(other.category) not in json.dumps(refreshed)
    forbidden_cursor(work, second["submission"]["id"])


def test_http_g0_inbox_reviewer_eligibility_rechecked_even_when_proposal_still_readable(work):
    identity, _ = create(work)
    save(work, share_request(work, identity))
    submit(work, identity)
    document = read(work, identity, work.peer).json()
    assert successful(work)["total_pending"] == 1
    with Session(work.admin) as session, session.begin():
        grant_for(session, work).product_manager = False
    still_readable = read(work, identity, work.peer)
    assert still_readable.status_code == 200, still_readable.text
    refreshed = successful(work)
    assert refreshed["items"] == [] and refreshed["total_pending"] == 0
    forbidden_cursor(work, document["submission"]["id"])


def test_http_g0_inbox_actual_return_approval_and_resubmit_exclude_settled_submission(work):
    returned = pending(work, "合成退回后重新提交")
    approved = pending(work, "合成已批准立项")
    save(work, decide_request(work, returned["id"], "returned"), actor=work.peer)
    save(work, decide_request(work, approved["id"]), actor=work.peer)
    settled = successful(work)
    assert settled["items"] == [] and settled["total_pending"] == 0
    for document in (returned, approved):
        forbidden_cursor(work, document["submission"]["id"])
    submit(work, returned["id"])
    current = read(work, returned["id"], work.peer).json()
    assert current["submission"]["id"] != returned["submission"]["id"]
    refreshed = successful(work)
    assert refreshed["total_pending"] == 1
    [item] = refreshed["items"]
    assert item["proposal_id"] == returned["id"]
    assert item["submission"]["id"] == current["submission"]["id"]
    assert returned["submission"]["id"] not in json.dumps(refreshed)
    forbidden_cursor(work, returned["submission"]["id"])


def test_http_g0_inbox_keyset_same_time_uuid_ties_and_total_across_pages(work):
    instant = now()
    with using_clock(lambda: instant):
        tied = [pending(work, f"合成同时间评审 {number}") for number in range(3)]
    with using_clock(lambda: instant + timedelta(seconds=1)):
        newest = pending(work, "合成较晚提交评审")
    tied_ids = [doc["submission"]["id"] for doc in tied]
    with Session(work.admin) as session:
        timestamps = list(
            session.scalars(
                select(ProposalSubmission.created_at).where(
                    ProposalSubmission.id.in_(map(UUID, tied_ids))
                )
            )
        )
    assert timestamps == [instant] * 3
    expected = [
        newest["submission"]["id"],
        *sorted(tied_ids, key=lambda value: UUID(value).int, reverse=True),
    ]
    seen, cursor = [], None
    for index, identity in enumerate(expected):
        page = successful(work, page_size=1, **({"cursor": cursor} if cursor else {}))
        assert page["total_pending"] == 4
        [item] = page["items"]
        assert item["submission"]["id"] == identity
        seen.append(item["submission"]["id"])
        cursor = page["next_cursor"]
        assert cursor == (identity if index < len(expected) - 1 else None)
    assert len(set(seen)) == 4
    assert [item["submission"]["id"] for item in successful(work)["items"]] == expected


def test_http_g0_inbox_cursor_must_be_readable_pending_and_owned_by_current_reviewer(work):
    own = pending(work, "SYNTHETIC_PEER_ONLY_PENDING")
    expert = other_reviewer(work)
    other = pending(work, "SYNTHETIC_EXPERT_ONLY_PENDING", reviewer=expert)
    assert read(work, other["id"], work.peer).status_code == 404
    forbidden_cursor(work, other["submission"]["id"])
    forbidden_cursor(work, own["submission"]["id"], actor=expert)
    forbidden_cursor(work, own["submission"]["id"], actor=work.human)
    forbidden_cursor(work, own["submission"]["id"], actor=work.other_human)
    forbidden_cursor(work, str(uuid4()))
    draft, _ = create(work)
    forbidden_cursor(work, draft)
    assert successful(work)["total_pending"] == 1


def test_http_g0_inbox_rejects_invalid_paging_input_and_requires_session(work):
    for params in (
        {"page_size": 0},
        {"page_size": 101},
        {"page_size": "not-an-integer"},
        {"cursor": "not-a-uuid"},
        {"cursor": ""},
    ):
        response = inbox(work, **params)
        assert response.status_code == 422, response.text
        assert response.json()["code"] == "VALIDATION_FAILED"
    unauthenticated = work.client.get("/v1/personal/g0-reviews")
    assert unauthenticated.status_code == 401, unauthenticated.text
    assert successful(work)["items"] == []
