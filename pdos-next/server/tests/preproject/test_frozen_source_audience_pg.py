"""Actual HTTP audience expansion must not expose private citations in frozen history.

Only the synthetic expert's login session is seeded. Business facts, source
links, G0 submission/return, item replacement and sharing use public commands.
The root session runs this file against its verified isolated PG target.
"""
# ruff: noqa: F811 -- pytest injects the imported real human G0 fixture.

import secrets
from copy import deepcopy
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.domain.preproject.evidence_models import EvidenceLink
from pdos_next.domain.preproject.models import ProposalSubmission
from pdos_next.models import Artifact, Grant, LoginSession, now
from pdos_next.service import digest
from tests.agent_kernel.test_transactions import human_session
from tests.preproject.test_evidence_commands_pg import (
    artifact,
    evidence_request,
    share_request,
    source_rows,
)
from tests.preproject.test_g0 import create, decide_request, post, read, save, submit
from tests.preproject.test_g0 import work as work


def expert_login(work):
    """Authenticate the fixture's existing read-only expert; add no source audience."""
    token = secrets.token_urlsafe(32)
    with Session(work.admin) as session, session.begin():
        grant = session.scalar(select(Grant).where(
            Grant.tenant_id == work.tenant,
            Grant.category_id == work.category,
            Grant.principal_id == work.expert,
        ))
        assert grant is not None and grant.can_write is False
        session.add(LoginSession(
            tenant_id=work.tenant, principal_id=work.expert,
            token_hash=digest(token), expires_at=now() + timedelta(hours=1),
        ))
    work.tokens[work.expert] = token


def test_private_link_frozen_body_is_hidden_from_later_shared_proposal_audience(work):
    expert_login(work)
    private_quote = "SYNTHETIC_PRIVATE_LINK_CITATION_not_for_new_readers"
    source_id = artifact(work, body=f"Header\n{private_quote}", visibility="private")
    proposal_id, _ = create(work)
    before = read(work, proposal_id).json()
    item = next(value for value in before["items"] if value["kind"] == "section")
    linked = post(work, evidence_request(work, "evidence.link.create", {
        "evidence": {
            "type": "artifact", "id": str(source_id), "version": 1, "locator": "line:2",
        },
        "target": {"type": "proposal_item", "id": item["item_id"], "version": item["version"]},
        "relation": "supports",
    }))
    assert linked.status_code == 200, linked.text
    link_id = UUID(linked.json()["result"]["link_id"])
    assert source_rows(work, proposal_id) == [(str(source_id), 1, 1, "private")]
    submit(work, proposal_id)

    owner_before = read(work, proposal_id)
    assert owner_before.status_code == 200, owner_before.text
    submission = owner_before.json()["submission"]
    assert submission["frozen_document_available"] is True
    frozen = deepcopy(submission["frozen_document"])
    assert private_quote in str(frozen)
    assert digest(frozen) == submission["document_digest"]
    metadata = {key: submission[key] for key in (
        "id", "revision", "reviewer_id", "document_digest",
    )}
    assert read(work, proposal_id, actor=work.expert).status_code == 404

    # The actual named reviewer returns this submitted copy. The owner then
    # makes a new item version; the old independent Link remains historical.
    save(work, decide_request(work, proposal_id, outcome="returned"), actor=work.peer)
    patched = post(work, evidence_request(work, "proposal.item.patch", {
        "proposal_id": proposal_id,
        "ops": [{
            "kind": item["kind"], "item_id": item["item_id"],
            "base_version": item["version"],
            "content": {**item["content"], "text": "Synthetic deidentified public reason"},
            "source_refs": [],
        }],
    }))
    assert patched.status_code == 200, patched.text
    current = read(work, proposal_id).json()
    revised = next(value for value in current["items"] if value["item_id"] == item["item_id"])
    assert current["status"] == "returned" and current["private_source_count"] == 0
    assert revised["version"] == item["version"] + 1
    assert revised["source_refs"] == [] and revised.get("evidence_links", []) == []
    assert source_rows(work, proposal_id) == []
    save(work, share_request(work, proposal_id, visibility="category"))

    # Actual ordinary RLS still denies the old private source to this new reader.
    # Sharing a cleaned proposal has not independently shared the source itself.
    with tenant_session(
        work.engine, work.tenant, actor_id=work.expert,
        requester_id=work.expert, category_id=work.category, read_snapshot=True,
    ) as session:
        assert session.get(Artifact, source_id) is None
    newly_visible = read(work, proposal_id, actor=work.expert)
    assert newly_visible.status_code == 200, newly_visible.text
    value = newly_visible.json()
    assert value["visibility"] == "category"
    assert {key: value["submission"][key] for key in metadata} == metadata
    assert value["submission"]["frozen_document_available"] is False
    assert value["submission"]["frozen_document"] is None
    assert private_quote not in newly_visible.text
    history = work.client.get(
        f"/v1/categories/{work.category}/proposals/{proposal_id}/items",
        params={"include_history": "true"},
        headers={"Authorization": f"Bearer {work.tokens[work.expert]}"},
    )
    assert history.status_code == 200, history.text
    assert private_quote not in history.text
    old = next(value for value in history.json()["items"] if (
        value["item_id"] == item["item_id"] and value["version"] == item["version"]
    ))
    assert old["evidence_links"][0]["status"] == "stale"

    for actor in (work.human, work.peer):
        authorized = read(work, proposal_id, actor=actor)
        assert authorized.status_code == 200, authorized.text
        actual = authorized.json()["submission"]
        assert {key: actual[key] for key in metadata} == metadata
        assert actual["frozen_document_available"] is True
        assert actual["frozen_document"] == frozen

    # The read-time redaction must not alter a signed copy, its digest, or Link.
    with human_session(work) as session:
        stored = session.get(ProposalSubmission, UUID(metadata["id"]))
        assert stored.frozen_document == frozen
        assert stored.document_digest == digest(frozen) == metadata["document_digest"]
        actual_link = session.get(EvidenceLink, link_id)
        assert actual_link.target_version == item["version"]
        assert actual_link.evidence_id == source_id and actual_link.evidence_locator == "line:2"
        assert actual_link.reverted_by_receipt_id is None
