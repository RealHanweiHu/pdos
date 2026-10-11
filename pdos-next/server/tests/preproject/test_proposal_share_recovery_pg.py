"""Actual rejected-command recovery; no model or private ledger bootstrap."""
# ruff: noqa: F811 -- pytest injects the shared explicit fixture

from copy import deepcopy
from uuid import UUID

from sqlalchemy import select

from pdos_next.models import Receipt
from tests.preproject.test_evidence_commands_pg import (
    artifact,
    claim_read,
    evidence_request,
    link_claim,
    record_claim,
    share_request,
    withdraw_request,
)
from tests.preproject.test_g0 import (
    create,
    decide_request,
    payload,
    post,
    read,
    save,
    submit,
)
from tests.preproject.test_g0 import work as work
from tests.preproject.test_material_proofs_pg import human_session


def human_private_claim(work, source, proposal_id, statement):
    command = evidence_request(work, "evidence.claim.record", {
        "artifact_id": str(source), "line": 1,
        "quote": "Synthetic exact public source", "statement": statement,
        "visibility": "private", "proposal_id": proposal_id,
        "content": {"text": statement},
    })
    command["source_read_set"] = [{
        "artifact_id": str(source), "expected_revision": 1,
    }]
    response = post(work, command)
    assert response.status_code == 200, response.text
    return response.json()


def assert_no_receipt(work, command):
    with human_session(work) as session:
        assert session.scalar(select(Receipt).where(
            Receipt.command_id == UUID(command["command_id"])
        )) is None


def test_version_rejection_can_repreview_original_key_and_commit_once(work):
    source = artifact(work)
    proposal, _ = create(work)
    human_private_claim(work, source, proposal, "通用便携需求")
    checked = post(work, share_request(work, proposal), preview=True)
    assert checked.status_code == 200, checked.text
    original = checked.json()["command"]
    item = read(work, proposal).json()["items"][0]
    changed = post(work, evidence_request(work, "proposal.item.patch", {
        "proposal_id": proposal, "ops": [{
            "kind": item["kind"], "item_id": item["item_id"],
            "base_version": item["version"],
            "content": {**item["content"], "text": "人工调整后的通用便携需求"},
        }],
    }))
    assert changed.status_code == 200, changed.text
    for _ in range(2):
        denied = post(work, original)
        assert denied.status_code == 409, denied.text
        assert denied.json()["code"] == "VERSION_CONFLICT"
        assert denied.json()["detail"]["reason"] == "evidence_version_moved"
        assert_no_receipt(work, original)
    refreshed = deepcopy(original)
    refreshed["payload"].pop("confirmation_token")
    revision = read(work, proposal).json()["revision"]
    refreshed["expected_revision"] = revision
    refreshed["payload"]["expected_revision"] = revision
    receipt, approved = save(work, refreshed)
    assert approved["command_id"] == original["command_id"]
    assert approved["idempotency_key"] == original["idempotency_key"]
    assert post(work, approved).json()["id"] == receipt["id"]
    assert read(work, proposal, work.peer).status_code == 200
    with human_session(work) as session:
        rows = list(session.scalars(select(Receipt).where(
            Receipt.command_id == UUID(original["command_id"])
        )))
        assert len(rows) == 1 and str(rows[0].id) == receipt["id"]


def test_consumption_after_withdraw_preview_is_definitive_without_side_effect(work):
    source = artifact(work)
    proposal, _ = create(work)
    claim = record_claim(work, source)
    link_claim(work, proposal, claim["subject_id"])
    checked = post(work, withdraw_request(work, claim["subject_id"]), preview=True)
    assert checked.status_code == 200, checked.text
    original = checked.json()["command"]
    submit(work, proposal)
    save(work, decide_request(work, proposal), actor=work.peer)
    for _ in range(2):
        denied = post(work, original)
        assert denied.status_code == 409, denied.text
        assert denied.json()["code"] == "UNDO_BLOCKED_BY_DEPENDENCY"
        assert denied.json()["detail"]["reason"] == "consumed_by_decision"
        assert_no_receipt(work, original)
    assert claim_read(work, claim["subject_id"]).json()["status"] == "active"


def test_human_identity_hit_withdraw_then_share_keeps_item_value_and_future_scope(work):
    source = artifact(work)
    body = payload(work)
    body.update(entry_kind="customer_request", customer_identities=["合成客户秘密甲"])
    proposal, _ = create(work, body)
    bad = human_private_claim(work, source, proposal, "合成客户秘密甲的便携需求")
    good = human_private_claim(work, source, proposal, "通用便携需求")
    _, before = link_claim(work, proposal, bad["subject_id"])
    checked = post(work, share_request(work, proposal), preview=True)
    assert checked.status_code == 200 and checked.json()["review"]["checks"]["hits"]
    denied = post(work, checked.json()["command"])
    assert denied.status_code == 409, denied.text
    assert denied.json()["detail"]["reason"] == "identity_not_removed"
    assert_no_receipt(work, checked.json()["command"])
    save(work, withdraw_request(work, bad["subject_id"]))
    receipt, approved = save(work, share_request(work, proposal))
    assert post(work, approved).json()["id"] == receipt["id"]
    current = read(work, proposal, work.peer).json()["items"][0]
    assert current["content"] == before["content"]
    assert current["version"] == before["version"]
    assert claim_read(work, good["subject_id"], actor=work.peer).status_code == 200
    assert claim_read(work, bad["subject_id"], actor=work.peer).status_code == 404
