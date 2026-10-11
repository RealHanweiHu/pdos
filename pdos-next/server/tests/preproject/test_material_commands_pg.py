"""Real M3 command transactions on the explicit, marked synthetic PostgreSQL fixture."""
# ruff: noqa: F811 -- pytest injects the shared fixture

from copy import deepcopy
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.domain.preproject.category_models import (
    KnowledgeEntry,
    ParameterVersion,
    PromotionProof,
)
from pdos_next.models import Receipt
from tests.preproject.test_g0 import (
    create,  # noqa: F401
    decide_request,
    payload,
    post,
    read,
    request,
    save,
    submit,
)
from tests.preproject.test_g0 import work as work


def parameter(**changes):
    return {
        "parameter_id": None,
        "expected_current_version": 0,
        "key": "noise",
        "name": "噪声",
        "value_type": "number",
        "unit": "dB",
        "direction": "lower",
        "standard_condition": None,
        "method": None,
        "acceptance_criterion": None,
        "change_note": "合成规格字典",
        **changes,
    }


def knowledge(**changes):
    return {"kind": "boundary", "content": {"definition": "按主要用途划分"}, **changes}


def test_parameter_versions_are_atomic_immutable_and_replayable(work):
    receipt, command = save(work, request(work, "category.parameter.publish", parameter()))
    identity = receipt["result"]["parameter_id"]
    assert post(work, command).json()["id"] == receipt["id"]
    req = request(
        work,
        "category.parameter.publish",
        parameter(
            parameter_id=identity,
            expected_current_version=1,
            unit="dB(A)",
            change_note="确认新口径",
        ),
    )
    second, _ = save(work, req)
    assert second["result"]["version"] == 2
    stale = post(work, req, preview=True)
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    history = work.client.get(
        f"/v1/categories/{work.category}/parameters?include_history=true", headers=work.headers
    ).json()["items"]
    rows = sorted((r for r in history if r["parameter_id"] == identity), key=lambda r: r["version"])
    assert [(r["version"], r["unit"]) for r in rows] == [(1, "dB"), (2, "dB(A)")]
    assert rows[0]["standard_condition"] is None
    with (
        pytest.raises(DBAPIError),
        tenant_session(
            work.engine, work.tenant, actor_id=work.human, category_id=work.category
        ) as s,
    ):
        s.execute(
            text("UPDATE parameter_versions SET unit='Pa' WHERE parameter_id=:p"),
            {"p": UUID(identity)},
        )
    with tenant_session(
        work.engine, work.tenant, actor_id=work.human, category_id=work.category
    ) as s:
        versions = list(
            s.scalars(
                select(ParameterVersion).where(ParameterVersion.parameter_id == UUID(identity))
            )
        )
        assert all(s.get(Receipt, r.receipt_id) is not None for r in versions)
        assert all(
            r.writer_id == work.human and r.origin == "human" and r.run_id is None for r in versions
        )


def test_old_parameter_reference_hints_draft_and_preserves_submitted_g0(work):
    registered, _ = save(work, request(work, "category.parameter.publish", parameter()))
    identity = registered["result"]["parameter_id"]
    body = payload(work)
    body["groups"]["items"][3]["content"].update(
        parameter_id=identity, parameter_version=1, unit="dB"
    )
    draft_id, _ = create(work, deepcopy(body))
    body["title"] = "固定参数旧版的在审合成提案"
    reviewing_id, _ = create(work, deepcopy(body))
    assert draft_id != reviewing_id
    submit(work, reviewing_id)
    snapshot = read(work, reviewing_id, work.peer).json()["submission"]["frozen_document"]
    save(
        work,
        request(
            work,
            "category.parameter.publish",
            parameter(
                parameter_id=identity,
                expected_current_version=1,
                unit="dB(A)",
                change_note="新版量纲",
            ),
        ),
    )
    assert read(work, draft_id).json()["context_hint"] is True
    assert read(work, draft_id).json()["revision"] == 1
    approved, _ = save(work, decide_request(work, reviewing_id), actor=work.peer)
    assert approved["result"]["status"] == "approved"
    assert read(work, reviewing_id, work.peer).json()["submission"]["frozen_document"] == snapshot
    with Session(work.admin) as s:
        assert s.execute(
            text(
                "SELECT parameter_id,parameter_version,unit FROM definition_specs "
                "WHERE definition_id=:id AND key='noise'"
            ),
            {"id": UUID(approved["result"]["definition_id"])},
        ).one() == (UUID(identity), 1, "dB")


def test_parameter_type_and_unit_must_match_actual_dictionary(work):
    registered, _ = save(work, request(work, "category.parameter.publish", parameter()))
    for field, value, reason in [
        ("unit", "Pa", "parameter_unit_mismatch"),
        ("value_type", "range", "parameter_type_mismatch"),
    ]:
        body = payload(work)
        spec = body["groups"]["items"][3]["content"]
        spec.update(
            parameter_id=registered["result"]["parameter_id"], parameter_version=1, unit="dB"
        )
        spec[field] = value
        denied = post(work, request(work, "proposal.create", body), preview=True)
        assert denied.status_code == 409 and denied.json()["detail"]["reason"] == reason


def test_knowledge_withdrawal_keeps_history_and_does_not_block_fixed_g0(work):
    added = post(work, request(work, "category.knowledge.add", knowledge()))
    assert added.status_code == 200, added.text
    entry = added.json()["result"]
    body = payload(work)
    body["context_refs"] = [{"type": "knowledge", "id": entry["entry_id"], "version": 1}]
    proposal_id, _ = create(work, body)
    submit(work, proposal_id)
    save(
        work,
        request(
            work,
            "category.knowledge.withdraw",
            {"lineage_id": entry["lineage_id"], "expected_version": 1, "reason": "边界需重新研究"},
        ),
    )
    active = work.client.get(
        f"/v1/categories/{work.category}/knowledge", headers=work.headers
    ).json()
    assert all(r["lineage_id"] != entry["lineage_id"] for r in active["items"])
    history = work.client.get(
        f"/v1/categories/{work.category}/knowledge?status=withdrawn&include_history=true",
        headers=work.headers,
    ).json()["items"]
    assert [(r["version"], r["action"]) for r in history] == [(1, "add"), (2, "withdraw")]
    approved, _ = save(work, decide_request(work, proposal_id), actor=work.peer)
    assert approved["result"]["status"] == "approved"


def test_promotion_identity_preview_and_private_proof(work):
    body = payload(work)
    body.update(entry_kind="customer_request", customer_identities=["合成客户甲"])
    proposal_id, _ = create(work, body)
    data = {
        "source_proposal_id": proposal_id,
        "source_proposal_revision": 1,
        "kind": "boundary",
        "content": {"definition": "合成客户甲要求便携"},
        "deidentified_confirmed": True,
    }
    preview = post(work, request(work, "category.knowledge.promote", data), preview=True)
    assert preview.status_code == 200, preview.text
    denied = post(work, preview.json()["command"])
    assert denied.status_code == 409 and denied.json()["detail"]["reason"] == "identity_not_removed"
    data["content"] = {"definition": "需提供便携方案"}
    saved, _ = save(work, request(work, "category.knowledge.promote", data))
    with Session(work.admin) as s:
        proof = s.scalar(
            select(PromotionProof).where(
                PromotionProof.knowledge_entry_id == UUID(saved["result"]["entry_id"])
            )
        )
        proof_id = proof.id
        entry = s.get(KnowledgeEntry, proof.knowledge_entry_id)
        assert entry.source_refs == [] and "source_proposal_id" not in entry.content
    root = f"/v1/categories/{work.category}/promotion-proofs/{proof_id}"
    assert work.client.get(root, headers=work.headers).status_code == 200
    assert (
        work.client.get(
            root, headers={"Authorization": f"Bearer {work.tokens[work.peer]}"}
        ).status_code
        == 404
    )
    with tenant_session(
        work.engine, work.tenant, actor_id=work.peer, category_id=work.category
    ) as s:
        assert s.get(PromotionProof, proof_id) is None
    visible = work.client.get(
        f"/v1/categories/{work.category}/knowledge",
        headers={"Authorization": f"Bearer {work.tokens[work.peer]}"},
    ).json()
    assert saved["result"]["entry_id"] in {r["id"] for r in visible["items"]}


def test_receipt_failure_rolls_back_version_and_current(work, monkeypatch):
    import pdos_next.service as common

    req = request(work, "category.parameter.publish", parameter())
    preview = post(work, req, preview=True)
    assert preview.status_code == 200, preview.text

    def fail_receipt(*args, **kwargs):
        raise RuntimeError("synthetic receipt failure")

    monkeypatch.setattr(common, "append_receipt", fail_receipt)
    with pytest.raises(RuntimeError, match="synthetic receipt failure"):
        post(work, preview.json()["command"])
    with Session(work.admin) as s:
        assert not list(
            s.scalars(select(ParameterVersion).where(ParameterVersion.tenant_id == work.tenant))
        )
        assert (
            s.scalar(
                text("SELECT count(*) FROM parameter_current WHERE tenant_id=:t"),
                {"t": work.tenant},
            )
            == 0
        )
