"""Actual uploaded original -> native Human Link -> Run admission; no provider I/O."""
# ruff: noqa: F811 -- explicitly imported native PG fixtures

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall
from pdos_next.agent_kernel.proposal_context import KEY
from pdos_next.domain.preproject.evidence_models import EvidenceLink
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Receipt, now
from pdos_next.original_security import security_row
from pdos_next.originals import require_original
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.agent_kernel.test_m3_original_binding_pg import QUOTE, actual_run, binding, uploaded
from tests.agent_kernel.test_proposal_context_pg import read as agent_read
from tests.agent_kernel.test_transactions import human_session
from tests.preproject.test_evidence_commands_pg import evidence_request, source_rows
from tests.preproject.test_g0 import create, payload, post, read, save
from tests.preproject.test_g0 import work as work
from tests.test_original_security import security_work as security_work


@pytest.mark.parametrize("change", ["none", "new_scan", "withdraw_original", "expire_writer"])
def test_native_locator_link_admits_only_its_current_authorized_original(
    work, security_work, change
):
    original_id, source_id = uploaded(work, security_work)
    data = payload(work)
    data.update(
        title="Synthetic locator-only Link proposal",
        entry_kind="customer_request",
        customer_identities=["Synthetic link customer"],
        source_refs=[],
    )
    proposal_id, _ = create(work, data)
    item = read(work, proposal_id).json()["items"][0]
    linked = post(
        work,
        evidence_request(
            work,
            "evidence.link.create",
            {
                "evidence": {
                    "type": "artifact",
                    "id": str(source_id),
                    "version": 1,
                    "locator": "line:1",
                },
                "target": {
                    "type": "proposal_item",
                    "id": item["item_id"],
                    "version": item["version"],
                },
                "relation": "Supports the synthetic owner proposal",
            },
        ),
    )
    assert linked.status_code == 200, linked.text
    receipt_id = UUID(linked.json()["id"])
    assert source_rows(work, proposal_id) == [(str(source_id), 1, 1, "private")]
    projected = read(work, proposal_id).json()["items"][0]
    fixed = next(ref for ref in projected["source_refs"] if ref["id"] == str(source_id))
    assert fixed["line"] == 1 and fixed["quote"] == QUOTE
    assert "quote" not in projected["evidence_links"][0]["evidence"]

    owner = Bootstrap(work.engine)
    scope, sources = actual_run(work, owner, UUID(proposal_id))
    assert sources == [{"artifact_id": str(source_id), "expected_revision": 1, "product_id": None}]
    assert scope.private_context
    assert scope.data_categories == frozenset({"customer", "customer_original"})
    assert tuple(scope.customer_identities) == ("Synthetic link customer",)
    assert agent_read(owner, scope, "proposal.items.read")["items"]
    assert (
        owner.project_context(scope, "Read the actual linked proposal")["proposal"]["id"]
        == proposal_id
    )
    with Session(work.admin) as session:
        link = session.get(EvidenceLink, UUID(linked.json()["subject_id"]))
        receipt = session.get(Receipt, receipt_id)
        assert link.evidence_id == source_id and link.evidence_locator == "line:1"
        assert link.origin == "human" and link.writer_id == work.human and link.run_id is None
        assert receipt.actor_id == receipt.requester_id == work.human
        assert receipt.agent_run_id is None
        refs = session.get(AgentRun, scope.run_id).versions[KEY]["references"]
        matches = [ref for ref in refs if ref["id"] == str(source_id)]
        assert len(matches) == 1 and matches[0]["quote"] == QUOTE

    if change == "expire_writer":
        # Alter only the existing synthetic authorization fixture, never a
        # source body, Link, proposal history or Run binding.
        with Session(work.admin) as session, session.begin():
            session.scalar(
                select(Grant).where(
                    Grant.tenant_id == work.tenant,
                    Grant.category_id == work.category,
                    Grant.principal_id == work.agent,
                )
            ).expires_at = now() - timedelta(seconds=1)
    elif change in {"new_scan", "withdraw_original"}:
        with human_session(work) as session:
            original = require_original(session, work.ctx, None, original_id)
            epoch = security_row(session, original, lock=False).epoch
        if change == "new_scan":
            scan = security_work.client.post(
                f"/v1/categories/{work.category}/originals/{original_id}/scan",
                headers=work.headers,
                json={"expected_epoch": epoch, "idempotency_key": str(uuid4())},
            )
            assert scan.status_code == 200, scan.text
        else:
            withdrawn, _ = save(
                work,
                evidence_request(
                    work,
                    "evidence.original.withdraw",
                    {
                        "original_id": str(original_id),
                        "expected_epoch": epoch,
                        "reason": "Native synthetic withdrawal after Link admission",
                    },
                ),
            )
            assert withdrawn["operation"] == "evidence.original.withdraw"
    if change != "none":
        for action in (
            lambda: binding(work, owner, UUID(proposal_id)),
            lambda: agent_read(owner, scope, "proposal.items.read"),
            lambda: owner.project_context(scope, "Must not expose invalidated Link source"),
        ):
            with pytest.raises(DomainError):
                action()
    with Session(work.admin) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AgentToolCall)
                .where(
                    AgentToolCall.run_id == scope.run_id,
                )
            )
            == 0
        )
        assert session.get(EvidenceLink, UUID(linked.json()["subject_id"])).receipt_id == receipt_id
