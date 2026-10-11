"""Evidence proof failures under the application role and real deferred PG guards."""
# ruff: noqa: F811 -- pytest injects the explicitly re-exported shared fixture

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from pdos_next.database import tenant_session
from pdos_next.domain.preproject.evidence_models import ClaimWithdrawal, EvidenceLink
from pdos_next.domain.preproject.models import Proposal
from pdos_next.models import Claim, Confirmation, ObjectAudience, Receipt
from pdos_next.service import digest
from tests.preproject.test_evidence_commands_pg import (
    artifact,
    claim_read,
    link_claim,
    prepared_claim,
    private_claim,
    record_claim,
    share_request,
    withdraw_request,
)
from tests.preproject.test_g0 import create, post, save
from tests.preproject.test_g0 import work as work
from tests.preproject.test_material_proofs_pg import (
    assert_check_violation,
    commit_command,
    human_session,
    insert_hooks,
)


def proof_id(work, command):
    with human_session(work) as session:
        proof = session.scalar(
            select(Confirmation).where(
                Confirmation.token_hash == digest(command["payload"]["confirmation_token"])
            )
        )
        assert proof is not None and proof.consumed is False
        return proof.id


def retry_ai_claim(work, command, confirmation_id):
    with human_session(work) as session:
        assert session.get(Confirmation, confirmation_id).consumed is False
    result = commit_command(work, command)
    with human_session(work) as session:
        claim = session.get(Claim, UUID(result["subject_id"]))
        receipt = session.get(Receipt, UUID(result["id"]))
        assert claim.origin == "ai_draft" and claim.writer_id == work.agent
        assert claim.confirmed_by == work.human and claim.prepared_event_id is not None
        assert claim.run_id == receipt.agent_run_id and claim.receipt_id == receipt.id
        assert receipt.confirmation_id == confirmation_id
        assert session.get(Confirmation, confirmation_id).consumed is True
    return result


def test_claim_ai_confirmation_cannot_be_laundered_as_human(work, monkeypatch):
    _, command = prepared_claim(work, monkeypatch, artifact(work))
    confirmation_id = proof_id(work, command)
    touched = []

    def wash_claim(_mapper, _connection, row):
        touched.append(row.id)
        row.origin, row.writer_id = "human", work.human
        row.run_id = row.confirmed_by = row.prepared_event_id = None

    def wash_receipt(_mapper, _connection, row):
        row.agent_run_id = None

    with insert_hooks((Claim, wash_claim), (Receipt, wash_receipt)):
        with pytest.raises(DBAPIError) as error:
            commit_command(work, command)
    assert touched
    assert_check_violation(error, "human claim cannot borrow AI proof")
    retry_ai_claim(work, command, confirmation_id)


def test_claim_actual_content_must_equal_confirmed_candidate(work, monkeypatch):
    _, command = prepared_claim(work, monkeypatch, artifact(work))
    confirmation_id = proof_id(work, command)
    touched = []

    def alter_content(_mapper, _connection, row):
        touched.append(row.id)
        row.content, row.statement = {"text": "未曾确认的其他事实"}, "未曾确认的其他事实"

    with insert_hooks((Claim, alter_content)):
        with pytest.raises(DBAPIError) as error:
            commit_command(work, command)
    assert touched
    assert_check_violation(error, "claim differs from candidate source")
    retry_ai_claim(work, command, confirmation_id)


def test_claim_identical_confirmation_from_old_transaction_cannot_be_reused(work, monkeypatch):
    candidate, first_command = prepared_claim(work, monkeypatch, artifact(work))
    old_id = proof_id(work, first_command)
    fresh_preview = post(work, candidate, preview=True)
    assert fresh_preview.status_code == 200, fresh_preview.text
    fresh_command = fresh_preview.json()["command"]
    fresh_id = proof_id(work, fresh_command)
    assert fresh_id != old_id
    # Two genuine previews of the identical actual candidate have the same content,
    # scope, actor and event. Consume the first in its own ordinary app transaction.
    with human_session(work) as session:
        first, fresh = session.get(Confirmation, old_id), session.get(Confirmation, fresh_id)
        assert first.snapshot == fresh.snapshot
        first.consumed = True
    touched = []

    def old_confirmation(_mapper, _connection, row):
        touched.append(row.id)
        row.confirmation_id = old_id

    with insert_hooks((Receipt, old_confirmation)):
        with pytest.raises(DBAPIError) as error:
            commit_command(work, fresh_command)
    assert touched
    assert_check_violation(error, "claim candidate confirmation mismatch")
    retry_ai_claim(work, fresh_command, fresh_id)


def test_claim_sql_withdraw_without_named_withdrawal_record_is_rejected(work):
    claim = record_claim(work, artifact(work))
    with pytest.raises(DBAPIError) as error:
        with human_session(work) as session:
            assert session.scalar(text("SELECT current_user")) == "pdos_next_app"
            session.execute(
                text("UPDATE claims SET status='withdrawn',revision=revision+1 WHERE id=:id"),
                {"id": claim["subject_id"]},
            )
    assert_check_violation(error, "claim withdrawal record required")
    row = claim_read(work, claim["subject_id"]).json()
    assert row["status"] == "active" and row["version"] == 1


def test_claim_withdrawal_reason_must_match_its_actual_confirmation(work):
    claim = record_claim(work, artifact(work))
    preview = post(work, withdraw_request(work, claim["subject_id"]), preview=True)
    assert preview.status_code == 200, preview.text
    command = preview.json()["command"]
    confirmation_id = proof_id(work, command)
    touched = []

    def alter_reason(_mapper, _connection, row):
        touched.append(row.id)
        row.reason = "与具名确认不同的理由"

    with insert_hooks((ClaimWithdrawal, alter_reason)):
        with pytest.raises(DBAPIError) as error:
            commit_command(work, command)
    assert touched
    assert_check_violation(error, "claim withdrawal proof or consumption mismatch")
    assert claim_read(work, claim["subject_id"]).json()["status"] == "active"
    with human_session(work) as session:
        assert session.get(Confirmation, confirmation_id).consumed is False
    committed = commit_command(work, command)
    assert committed["subject_id"] == claim["subject_id"]
    assert claim_read(work, claim["subject_id"]).json()["status"] == "withdrawn"


@pytest.mark.parametrize("change", ["relation", "noop", "delete"])
def test_evidence_link_history_is_immutable_under_application_sql(work, change):
    claim = record_claim(work, artifact(work))
    proposal_id, _ = create(work)
    receipt, _ = link_claim(work, proposal_id, claim["subject_id"])
    identity = receipt["result"]["link_id"]
    sql = {
        "relation": "UPDATE evidence_links SET relation='contradicts' WHERE id=:id",
        "noop": "UPDATE evidence_links SET reverted_by_receipt_id=NULL WHERE id=:id",
        "delete": "DELETE FROM evidence_links WHERE id=:id",
    }[change]
    with pytest.raises(DBAPIError) as error:
        with human_session(work) as session:
            assert session.scalar(text("SELECT current_user")) == "pdos_next_app"
            session.execute(text(sql), {"id": identity})
    if change == "delete":
        assert error.value.orig.sqlstate == "42501"
        assert "permission denied for table evidence_links" in str(error.value.orig)
    else:
        assert_check_violation(error, "evidence link only reverts once")
    with human_session(work) as session:
        row = session.get(EvidenceLink, UUID(identity))
        assert row.relation == "supports" and row.reverted_by_receipt_id is None


def test_old_share_confirmation_cannot_authorize_later_sql_audience_expansion(work, monkeypatch):
    source = artifact(work)
    proposal_id, _ = create(work)
    claim = private_claim(work, monkeypatch, source, proposal_id)
    shared, _ = save(
        work, share_request(work, proposal_id, visibility="audience", audience_ids=[work.peer])
    )
    assert claim_read(work, claim["subject_id"], actor=work.peer).status_code == 200
    with human_session(work) as session:
        receipt = session.get(Receipt, UUID(shared["id"]))
        assert session.get(Confirmation, receipt.confirmation_id).consumed is True
        existing = list(
            session.scalars(
                select(ObjectAudience).where(
                    ObjectAudience.object_type == "proposals",
                    ObjectAudience.subject_id == UUID(proposal_id),
                )
            )
        )
        assert {row.principal_id for row in existing} == {work.peer}
    with pytest.raises(DBAPIError) as error:
        with human_session(work) as session:
            assert session.scalar(text("SELECT current_user")) == "pdos_next_app"
            # Expert is an active, legitimate category member. Only the new named
            # sharing decision is absent; source, owner and category are all valid.
            session.add(
                ObjectAudience(
                    tenant_id=work.tenant,
                    category_id=work.category,
                    object_type="proposals",
                    subject_id=UUID(proposal_id),
                    owner_id=work.human,
                    principal_id=work.expert,
                )
            )
    assert_check_violation(error, "proposal audience share proof mismatch")
    with tenant_session(
        work.engine, work.tenant, actor_id=work.expert, category_id=work.category
    ) as session:
        assert session.get(Proposal, UUID(proposal_id)) is None
        assert session.get(Claim, UUID(claim["subject_id"])) is None
    # The exact same new reader is admitted by a fresh explicit sharing decision.
    save(
        work,
        share_request(
            work, proposal_id, visibility="audience", audience_ids=[work.peer, work.expert]
        ),
    )
    with tenant_session(
        work.engine, work.tenant, actor_id=work.expert, category_id=work.category
    ) as session:
        assert session.get(Claim, UUID(claim["subject_id"])) is not None


def test_read_only_claim_lock_exposes_only_scoped_metadata_and_no_update(work):
    claim = record_claim(work, artifact(work))
    identity = UUID(claim["subject_id"])
    with tenant_session(
        work.engine, work.tenant, actor_id=work.peer, category_id=work.category
    ) as session:
        sql = text(
            "SELECT * FROM m3_lock_claim_references(:tenant,:category,CAST(:ids AS uuid[]))"
        )
        bound = {"tenant": work.tenant, "category": work.category, "ids": [identity]}
        locked = session.execute(sql, bound).mappings().all()
        assert [dict(row) for row in locked] == [
            {"id": identity, "revision": 1, "status": "active"}
        ]
        assert session.execute(sql, {**bound, "category": uuid4()}).all() == []
        assert session.execute(sql, {**bound, "tenant": uuid4()}).all() == []
        changed = session.execute(
            text("UPDATE claims SET status='withdrawn',revision=revision+1 WHERE id=:id"),
            {"id": identity},
        )
        assert changed.rowcount == 0
    assert claim_read(work, identity, actor=work.peer).json()["status"] == "active"


def test_old_shared_confirmation_does_not_allow_sql_audience_deletion(work):
    proposal_id, _ = create(work)
    save(work, share_request(work, proposal_id, visibility="audience", audience_ids=[work.peer]))
    with human_session(work) as session:
        removed = session.execute(
            text("DELETE FROM object_audiences WHERE object_type='proposals' AND subject_id=:id"),
            {"id": UUID(proposal_id)},
        )
        assert removed.rowcount == 0
        retained = list(
            session.scalars(
                select(ObjectAudience.principal_id).where(
                    ObjectAudience.object_type == "proposals",
                    ObjectAudience.subject_id == UUID(proposal_id),
                )
            )
        )
        assert retained == [work.peer]
