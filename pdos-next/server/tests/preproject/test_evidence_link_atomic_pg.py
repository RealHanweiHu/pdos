"""A valid Link/Receipt must itself require the proposal revision and source projection."""
# ruff: noqa: F811 -- pytest injects the explicitly re-exported shared fixture

from copy import deepcopy
from uuid import UUID

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import DBAPIError

from pdos_next.contracts import Command
from pdos_next.domain.preproject.evidence_models import EvidenceLink
from pdos_next.domain.preproject.models import Proposal, ProposalRevision, ProposalSource
from pdos_next.models import Artifact, Receipt
from pdos_next.service import Context, execute
from tests.preproject.test_evidence_commands_pg import artifact, evidence_request, source_rows
from tests.preproject.test_g0 import create, read
from tests.preproject.test_g0 import work as work
from tests.preproject.test_material_proofs_pg import (
    assert_check_violation,
    commit_command,
    human_session,
)


@pytest.mark.parametrize(
    "omission", ["missing_revision", "missing_source_projection", "private_source_count"]
)
def test_link_receipt_requires_its_proposal_revision_and_complete_source_projection(work, omission):
    private = omission == "private_source_count"
    source = artifact(work, visibility="private" if private else "category")
    proposal_id, _ = create(work)
    proposal_id = UUID(proposal_id)
    before = deepcopy(read(work, proposal_id).json())
    item = before["items"][0]
    assert before["revision"] == 1 and before["private_source_count"] == 0
    assert source_rows(work, proposal_id) == []
    command = evidence_request(
        work,
        "evidence.link.create",
        {
            "evidence": {"type": "artifact", "id": str(source), "version": 1},
            "target": {"type": "proposal_item", "id": item["item_id"], "version": item["version"]},
            "relation": "supports",
        },
    )
    touched, results = [], []

    def omit_one_write(session, _context, _instances):
        if omission in {"missing_revision", "missing_source_projection"}:
            model = ProposalRevision if omission == "missing_revision" else ProposalSource
            for row in list(session.new):
                if isinstance(row, model) and row.proposal_id == proposal_id:
                    assert row.tenant_id == work.tenant and row.category_id == work.category
                    touched.append(row)
                    session.expunge(row)
        else:
            for row in list(session.dirty):
                if isinstance(row, Proposal) and row.id == proposal_id and row.private_source_count:
                    assert row.private_source_count == 1
                    touched.append(row.id)
                    row.private_source_count = 0

    with pytest.raises(DBAPIError) as error:
        with human_session(work) as session:
            assert session.scalar(text("SELECT current_user")) == "pdos_next_app"
            event.listen(session, "before_flush", omit_one_write)
            try:
                result = execute(
                    session,
                    Context(work.tenant, work.human, work.human, category_id=work.category),
                    Command.model_validate(command),
                )
                session.flush()
                results.append(result)
                assert len(touched) == 1
                # The real command admitted the source/target and wrote a genuine
                # human Link and Receipt in this same ordinary-role transaction.
                link = session.get(EvidenceLink, UUID(result["subject_id"]))
                receipt = session.get(Receipt, UUID(result["id"]))
                assert receipt.operation == "evidence.link.create"
                assert receipt.subject_id == link.id and receipt.subject_revision == 1
                assert receipt.actor_id == work.human and receipt.requester_id == work.human
                assert receipt.agent_run_id is None and link.run_id is None
                assert link.origin == "human" and link.writer_id == work.human
                assert link.receipt_id == receipt.id and link.evidence_id == source
                assert link.target_id == UUID(item["item_id"]) and link.target_version == 1
                assert session.get(Artifact, source).status == "active"
                versions = list(
                    session.scalars(
                        select(ProposalRevision).where(
                            ProposalRevision.proposal_id == proposal_id,
                        )
                    )
                )
                pointers = list(
                    session.scalars(
                        select(ProposalSource).where(
                            ProposalSource.proposal_id == proposal_id,
                        )
                    )
                )
                assert len(versions) == (1 if omission == "missing_revision" else 2)
                assert len(pointers) == (0 if omission == "missing_source_projection" else 1)
                assert session.get(Proposal, proposal_id).private_source_count == 0
                # Force this deferred Link-side proof first, so the existing
                # Revision-side guard cannot mask a missing reverse constraint.
                session.execute(text("SET CONSTRAINTS m3_evidence_link_atom IMMEDIATE"))
            finally:
                event.remove(session, "before_flush", omit_one_write)
    assert results and touched
    assert_check_violation(error, "evidence link missing proposal revision or projection")

    failed = results[0]
    with human_session(work) as session:
        assert session.get(Receipt, UUID(failed["id"])) is None
        assert session.get(EvidenceLink, UUID(failed["subject_id"])) is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(ProposalRevision)
                .where(
                    ProposalRevision.proposal_id == proposal_id,
                )
            )
            == 1
        )
    assert source_rows(work, proposal_id) == []
    assert read(work, proposal_id).json() == before

    # The exact same command succeeds once the single injected omission is removed.
    # This also proves rollback preserved its idempotency key and all admission facts.
    retried = commit_command(work, command)
    assert retried["operation"] == "evidence.link.create"
    with human_session(work) as session:
        receipt = session.get(Receipt, UUID(retried["id"]))
        link = session.get(EvidenceLink, UUID(retried["subject_id"]))
        revision = session.scalar(
            select(ProposalRevision).where(
                ProposalRevision.proposal_id == proposal_id,
                ProposalRevision.revision == 2,
            )
        )
        assert link.receipt_id == receipt.id and revision.receipt_id == receipt.id
        proposal = session.get(Proposal, proposal_id)
        assert proposal.revision == 2 and proposal.private_source_count == int(private)
        assert proposal.effective_visibility == "private"
    assert source_rows(work, proposal_id) == [
        (str(source), 1, 1, "private" if private else "shared")
    ]
    current = read(work, proposal_id).json()["items"][0]
    assert current["content"] == item["content"] and current["version"] == item["version"]
    assert current["origin"] == item["origin"] == "human"
    assert current["evidence_links"][0]["id"] == retried["subject_id"]
