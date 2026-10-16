"""Real HTTP evidence lifecycle; only model ledgers use synthetic bootstrap facts."""
# ruff: noqa: F811 -- pytest injects the explicitly re-exported shared fixture

from copy import copy, deepcopy
from dataclasses import replace
from pdos_next.agent_kernel.qualification_binding import model_identity, tool_identity

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from pdos_next.agent_kernel.bindings import execution_key
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.category_scope import MemberGrant, grant_member
from pdos_next.database import tenant_session
from pdos_next.domain.preproject.evidence_models import EvidenceLink
from pdos_next.domain.preproject.models import ProposalSource
from pdos_next.models import Category, Claim, Consumption
from pdos_next.service import Context
from tests.preproject import test_review_fixes as fixtures
from tests.preproject.test_g0 import (
    create,
    decide_request,
    payload,
    post,
    read,
    request,
    save,
    submit,
)
from tests.preproject.test_g0 import work as work
from tests.preproject.test_material_proofs_pg import human_session


def evidence_request(work, operation, body):
    with human_session(work) as session:
        revision = session.get(Category, work.category).revision
    return request(work, operation, body, revision=revision)


def artifact(work, *, body="Synthetic exact public source", visibility="category"):
    response = post(
        work,
        evidence_request(
            work,
            "evidence.artifact.register",
            {
                "title": "合成证据原文",
                "source_label": "本地合成",
                "content": body,
                "visibility": visibility,
            },
        ),
    )
    assert response.status_code == 200, response.text
    return UUID(response.json()["subject_id"])


def claim_body(
    source, *, quote="Synthetic exact public source", text="合成来源事实", proposal_id=None
):
    result = {
        "source": {
            "kind": "artifact",
            "id": str(source),
            "version": 1,
            "locator": "line:1",
            "quote": quote,
        },
        "nature": "extracted",
        "availability": "known",
        "content": {"text": text},
    }
    if proposal_id:
        result["proposal_id"] = str(proposal_id)
    return result


def record_claim(work, source, **changes):
    response = post(
        work, evidence_request(work, "evidence.claim.record", claim_body(source, **changes))
    )
    assert response.status_code == 200, response.text
    return response.json()


def claim_read(work, identity, *, actor=None):
    return work.client.get(
        f"/v1/categories/{work.category}/claims/{identity}",
        headers={"Authorization": f"Bearer {work.tokens[actor or work.human]}"},
    )


def claim_fixture(
    work,
    monkeypatch,
    source,
    proposal_id=None,
    *,
    private_context=False,
    text="合成研究事实",
    arguments=None,
    read_artifacts=(),
):
    arguments = arguments or claim_body(source, text=text, proposal_id=proposal_id)
    original_ledger = fixtures.ledger

    def research_ledger():
        ledger = original_ledger()
        skill = ledger.catalog._skills["public_research"]
        binding = ledger.source.skill.model_copy(
            update={"key": skill.key, "version": skill.version, "digest": skill.digest}
        )
        ledger.source = ledger.source.model_copy(update={"skill": binding})
        ledger.model.execution_binding = {
            **ledger.model.execution_binding,
            "loaded_skills": [binding.model_dump(mode="json")],
        }
        ledger.event.body = {
            **ledger.event.body,
            "key": skill.key,
            "version": skill.version,
            "digest": skill.digest,
        }
        ledger.qualification.skill_key = skill.key
        ledger.qualification.qualified_skill_version = skill.version
        ledger.qualification.qualified_skill_digest = skill.digest
        ledger.qualification.qualified_tool_digest = tool_identity(skill, ledger.registry)
        ledger.qualification.qualified_model_digest = model_identity(ledger.route)
        ledger.scope = replace(ledger.scope, private_context=private_context)
        ledger.run.private_context = private_context
        ledger.run.read_sources = [
            {"artifact_id": str(identity), "expected_revision": 1, "product_id": None}
            for identity in (source, *read_artifacts)
        ]
        return ledger

    with monkeypatch.context() as patch:
        patch.setattr(fixtures, "ledger", research_ledger)
        f = fixtures.agent_fixture(work, "evidence.claim.record", arguments, proposal_id)
    return f, arguments


def private_claim(work, monkeypatch, source, proposal_id, *, text="合成研究事实"):
    f, arguments = claim_fixture(
        work, monkeypatch, source, proposal_id, private_context=True, text=text
    )
    return f.adapter.execute(
        f.scope,
        "evidence.claim.record",
        arguments,
        execution_key(f.scope.run_id, f.source.model_call_id, 0),
        source=f.source,
    )


def prepared_claim(work, monkeypatch, source):
    f, arguments = claim_fixture(work, monkeypatch, source)
    host = Bootstrap(work.engine)
    host.catalog, host.registry, host.route = f.catalog, f.registry, lambda *_: f.route
    candidate = host.prepare_candidate(
        f.scope, f.spec, arguments, execution_key(f.scope.run_id, f.source.model_call_id, 0)
    )
    checked = post(work, candidate["command"], preview=True)
    assert checked.status_code == 200, checked.text
    return candidate["command"], checked.json()["command"]


def link_claim(work, proposal_id, claim_id, *, item=None):
    item = item or read(work, proposal_id).json()["items"][0]
    response = post(
        work,
        evidence_request(
            work,
            "evidence.link.create",
            {
                "evidence": {"type": "claim", "id": str(claim_id), "version": 1},
                "target": {
                    "type": "proposal_item",
                    "id": item["item_id"],
                    "version": item["version"],
                },
                "relation": "supports",
            },
        ),
    )
    assert response.status_code == 200, response.text
    return response.json(), item


def withdraw_request(work, claim_id):
    return evidence_request(
        work,
        "evidence.claim.withdraw",
        {
            "claim_id": str(claim_id),
            "expected_version": 1,
            "reason": "合成事实登记错误",
        },
    )


def share_request(work, proposal_id, *, visibility="category", audience_ids=(), confirmed=True):
    return evidence_request(
        work,
        "proposal.share",
        {
            "proposal_id": str(proposal_id),
            "expected_revision": read(work, proposal_id).json()["revision"],
            "visibility": visibility,
            "audience_ids": [str(i) for i in audience_ids],
            "deidentified_confirmed": confirmed,
        },
    )


def source_rows(work, proposal_id):
    with human_session(work) as session:
        return [
            (str(row.source_id), row.source_version, row.ref_count, row.privacy)
            for row in session.scalars(
                select(ProposalSource).where(ProposalSource.proposal_id == UUID(str(proposal_id)))
            )
        ]


def test_claim_link_projection_counter_and_target_version_are_independent(work):
    source = artifact(work)
    claim = record_claim(work, source)
    proposal_id, _ = create(work)
    receipt, before = link_claim(work, proposal_id, claim["subject_id"])
    projected = read(work, proposal_id).json()["items"][0]
    assert projected["content"] == before["content"] and projected["version"] == before["version"]
    assert projected["source_refs"] == [{"type": "claim", "id": claim["subject_id"], "version": 1}]
    assert projected["evidence_links"][0]["id"] == receipt["result"]["link_id"]
    assert "quote" not in str(projected["evidence_links"])
    assert source_rows(work, proposal_id) == [(str(source), 1, 1, "shared")]
    patch = post(
        work,
        evidence_request(
            work,
            "proposal.item.patch",
            {
                "proposal_id": proposal_id,
                "ops": [
                    {
                        "kind": before["kind"],
                        "item_id": before["item_id"],
                        "base_version": before["version"],
                        "content": {**before["content"], "text": "人工新版"},
                        "source_refs": [],
                    }
                ],
            },
        ),
    )
    assert patch.status_code == 200, patch.text
    current = read(work, proposal_id).json()["items"][0]
    assert current["version"] == 2 and current["source_refs"] == []
    assert current.get("evidence_links", []) == [] and source_rows(work, proposal_id) == []
    with human_session(work) as session:
        historical = session.get(EvidenceLink, UUID(receipt["result"]["link_id"]))
        assert historical.target_version == 1 and historical.reverted_by_receipt_id is None


def test_claim_withdraw_confirmation_replay_and_source_projection(work):
    source = artifact(work)
    claim = record_claim(work, source)
    proposal_id, _ = create(work)
    linked, before = link_claim(work, proposal_id, claim["subject_id"])
    req = withdraw_request(work, claim["subject_id"])
    denied = post(work, req)
    assert denied.status_code == 409 and denied.json()["code"] == "CONFIRMATION_REQUIRED"
    receipt, approved = save(work, req)
    assert post(work, approved).json()["id"] == receipt["id"]
    view = claim_read(work, claim["subject_id"]).json()
    assert view["status"] == "withdrawn" and view["version"] == 2
    assert source_rows(work, proposal_id) == []
    item = read(work, proposal_id).json()["items"][0]
    assert item["content"] == before["content"] and item["version"] == before["version"]
    assert item["source_changes"][0]["status"] == "withdrawn"
    with human_session(work) as session:
        row = session.get(EvidenceLink, UUID(linked["result"]["link_id"]))
        assert str(row.reverted_by_receipt_id) == receipt["id"]


def test_claim_withdraw_failure_rolls_back_status_link_projections_and_confirmation(
    work, monkeypatch
):
    import pdos_next.service as common

    source = artifact(work)
    claim = record_claim(work, source)
    proposal_id, _ = create(work)
    link_claim(work, proposal_id, claim["subject_id"])
    checked = post(work, withdraw_request(work, claim["subject_id"]), preview=True)
    assert checked.status_code == 200, checked.text
    before = deepcopy(read(work, proposal_id).json())
    original = common.append_receipt

    def fail_tail(*_args, **_kwargs):
        raise RuntimeError("synthetic withdrawal receipt failure")

    monkeypatch.setattr(common, "append_receipt", fail_tail)
    with pytest.raises(RuntimeError, match="synthetic withdrawal receipt failure"):
        post(work, checked.json()["command"])
    assert claim_read(work, claim["subject_id"]).json()["status"] == "active"
    assert read(work, proposal_id).json() == before
    assert source_rows(work, proposal_id) == [(str(source), 1, 1, "shared")]
    monkeypatch.setattr(common, "append_receipt", original)
    succeeded = post(work, checked.json()["command"])
    assert succeeded.status_code == 200, succeeded.text


def test_private_context_public_source_claim_shares_only_after_named_confirmation(
    work, monkeypatch
):
    source = artifact(work)
    proposal_id, _ = create(work)
    claim = private_claim(work, monkeypatch, source, proposal_id)
    assert claim_read(work, claim["subject_id"], actor=work.peer).status_code == 404
    missing = share_request(work, proposal_id, confirmed=False)
    checked = post(work, missing, preview=True)
    assert checked.status_code == 200, checked.text
    denied = post(work, checked.json()["command"])
    assert (
        denied.status_code == 409
        and denied.json()["detail"]["reason"] == "deidentification_not_confirmed"
    )
    save(work, share_request(work, proposal_id))
    shared = claim_read(work, claim["subject_id"], actor=work.peer)
    assert shared.status_code == 200, shared.text
    assert shared.json()["privacy"] == "private" and shared.json()["origin"] == "ai_draft"
    assert shared.json()["proposal_id"] == proposal_id


def test_withdrawn_claim_keeps_old_named_reader_but_not_future_shared_readers(work, monkeypatch):
    source = artifact(work)
    proposal_id, _ = create(work)
    claim = private_claim(work, monkeypatch, source, proposal_id, text="合成撤回历史正文")
    save(work, share_request(work, proposal_id, visibility="audience", audience_ids=[work.peer]))
    save(work, withdraw_request(work, claim["subject_id"]))
    assert claim_read(work, claim["subject_id"], actor=work.peer).status_code == 200
    save(work, share_request(work, proposal_id))
    # Expert is a real same-category member but was never an explicit proposal reader.
    with tenant_session(
        work.engine, work.tenant, actor_id=work.expert, category_id=work.category
    ) as s:
        assert s.get(Claim, UUID(claim["subject_id"])) is None
    assert claim_read(work, claim["subject_id"]).json()["content"]["text"] == "合成撤回历史正文"


@pytest.mark.parametrize("private_source", [False, True])
def test_share_rejects_identity_hits_and_private_source_roots(work, monkeypatch, private_source):
    source = artifact(work, visibility="private" if private_source else "category")
    data = payload(work)
    data.update(entry_kind="customer_request", customer_identities=["合成客户秘密甲"])
    proposal_id, _ = create(work, data)
    private_claim(
        work,
        monkeypatch,
        source,
        proposal_id,
        text="通用需求" if private_source else "合成客户秘密甲的定制事实",
    )
    checked = post(work, share_request(work, proposal_id), preview=True)
    if private_source:
        assert (
            checked.status_code == 409
            and checked.json()["detail"]["reason"] == "private_sources_present"
        )
    else:
        assert checked.status_code == 200, checked.text
        assert checked.json()["review"]["checks"]["hits"]
        denied = post(work, checked.json()["command"])
        assert (
            denied.status_code == 409
            and denied.json()["detail"]["reason"] == "identity_not_removed"
        )
    assert read(work, proposal_id, work.peer).status_code == 404


@pytest.mark.parametrize("change", ["watermark", "revision"])
def test_share_rechecks_saved_watermark_and_revision(work, monkeypatch, change):
    source = artifact(work)
    proposal_id, _ = create(work)
    private_claim(work, monkeypatch, source, proposal_id)
    checked = post(work, share_request(work, proposal_id), preview=True)
    assert checked.status_code == 200, checked.text
    if change == "watermark":
        private_claim(work, monkeypatch, source, proposal_id, text="预览之后新增的私有上下文事实")
    else:
        item = read(work, proposal_id).json()["items"][0]
        changed = post(
            work,
            evidence_request(
                work,
                "proposal.item.patch",
                {
                    "proposal_id": proposal_id,
                    "ops": [
                        {
                            "kind": item["kind"],
                            "item_id": item["item_id"],
                            "base_version": item["version"],
                            "content": {**item["content"], "text": "修改后的内容"},
                        }
                    ],
                },
            ),
        )
        assert changed.status_code == 200, changed.text
    denied = post(work, checked.json()["command"])
    assert denied.status_code == 409, denied.text
    assert denied.json()["detail"]["reason"] == (
        "CONFIRMATION_SCOPE_CHANGED" if change == "watermark" else "evidence_version_moved"
    )
    assert read(work, proposal_id, work.peer).status_code == 404


def test_g0_frozen_link_is_independent_and_signed_claim_consumption_blocks_withdraw(work):
    source = artifact(work)
    claim = record_claim(work, source)
    proposal_id, _ = create(work)
    linked, before = link_claim(work, proposal_id, claim["subject_id"])
    submit(work, proposal_id)
    frozen = read(work, proposal_id, work.peer).json()["submission"]["frozen_document"]
    item = next(i for i in frozen["items"] if i["item_id"] == before["item_id"])
    assert item["content"] == before["content"]
    assert item["evidence_links"][0]["id"] == linked["result"]["link_id"]
    assert "quote" not in str(item["evidence_links"])
    approved, _ = save(work, decide_request(work, proposal_id), actor=work.peer)
    with human_session(work) as session:
        consumed = session.scalar(
            select(Consumption).where(Consumption.claim_id == UUID(claim["subject_id"]))
        )
        assert consumed is not None and consumed.claim_version == 1
        assert str(consumed.receipt_id) == approved["id"] and consumed.decision_id is not None
        assert str(consumed.definition_id) == approved["result"]["definition_id"]
    denied = post(work, withdraw_request(work, claim["subject_id"]), preview=True)
    assert denied.status_code == 409 and denied.json()["code"] == "UNDO_BLOCKED_BY_DEPENDENCY"
    assert denied.json()["detail"]["reason"] == "consumed_by_decision"


def test_submitted_claim_withdrawal_blocks_approval_with_exact_stale_reason(work):
    source = artifact(work)
    claim = record_claim(work, source)
    proposal_id, _ = create(work)
    link_claim(work, proposal_id, claim["subject_id"])
    submit(work, proposal_id)
    approval = decide_request(work, proposal_id)
    save(work, withdraw_request(work, claim["subject_id"]))
    denied = post(work, approval, actor=work.peer, preview=True)
    assert denied.status_code == 409 and denied.json()["code"] == "SOURCE_STALE"
    assert denied.json()["detail"]["reason"] == "claim_withdrawn"


def test_withdraw_repairs_hidden_private_proposal_without_disclosing_it(work):
    source = artifact(work)
    claim = record_claim(work, source)
    with human_session(work) as session:
        grant_member(
            session,
            Context(work.tenant, work.human, work.human, category_id=work.category),
            MemberGrant(
                principal_id=work.peer,
                can_write=True,
                expected_revision=1,
                idempotency_key=str(uuid4()),
                decision="批准",
            ),
        )
    peer = copy(work)
    peer.human, peer.headers = work.peer, {"Authorization": f"Bearer {work.tokens[work.peer]}"}
    peer_body = payload(peer)
    peer_body["title"] = "不应泄露的私有提案名称"
    created, _ = save(peer, evidence_request(peer, "proposal.create", peer_body))
    proposal_id = created["subject_id"]
    link_claim(peer, proposal_id, claim["subject_id"])
    assert read(work, proposal_id).status_code == 404
    checked = post(work, withdraw_request(work, claim["subject_id"]), preview=True)
    assert checked.status_code == 200, checked.text
    assert proposal_id not in checked.text and peer_body["title"] not in checked.text
    saved = post(work, checked.json()["command"])
    assert saved.status_code == 200, saved.text
    assert proposal_id not in saved.text and peer_body["title"] not in saved.text
    assert source_rows(peer, proposal_id) == []
    assert read(peer, proposal_id).json()["context_hint"] is True


def test_claim_http_and_application_role_are_tenant_and_category_isolated(work):
    source = artifact(work)
    claim = record_claim(work, source)
    denied = claim_read(work, claim["subject_id"], actor=work.other_human)
    assert denied.status_code in {403, 404}
    with tenant_session(
        work.engine, work.other_tenant, actor_id=work.other_human, category_id=work.category
    ) as session:
        assert session.get(Claim, UUID(claim["subject_id"])) is None
    other_category = uuid4()
    with tenant_session(
        work.engine, work.tenant, actor_id=work.human, category_id=other_category
    ) as session:
        assert session.get(Claim, UUID(claim["subject_id"])) is None


def test_share_scans_legacy_claim_statement_even_when_content_text_is_clean(work, monkeypatch):
    source = artifact(work)
    data = payload(work)
    data.update(entry_kind="customer_request", customer_identities=["合成客户秘密甲"])
    proposal_id, _ = create(work, data)
    arguments = {
        "artifact_id": str(source),
        "line": 1,
        "quote": "Synthetic exact public source",
        "statement": "合成客户秘密甲的原始事实",
        "visibility": "private",
        "content": {"text": "干净的结构化摘要"},
        "proposal_id": proposal_id,
        "nature": "extracted",
        "availability": "known",
    }
    f, arguments = claim_fixture(
        work, monkeypatch, source, proposal_id, private_context=True, arguments=arguments
    )
    result = f.adapter.execute(
        f.scope,
        "evidence.claim.record",
        arguments,
        execution_key(f.scope.run_id, f.source.model_call_id, 0),
        source=f.source,
    )
    view = claim_read(work, result["subject_id"])
    assert view.status_code == 200, view.text
    assert "合成客户秘密甲" in view.json()["statement"]
    assert view.json()["content"]["text"] == "干净的结构化摘要"
    preview = post(work, share_request(work, proposal_id), preview=True)
    assert preview.status_code == 200, preview.text
    assert preview.json()["review"]["checks"]["hits"]
    denied = post(work, preview.json()["command"])
    assert denied.status_code == 409, denied.text
    assert denied.json()["detail"]["reason"] == "identity_not_removed"
    assert claim_read(work, result["subject_id"], actor=work.peer).status_code == 404
    assert read(work, proposal_id, work.peer).status_code == 404


@pytest.fixture
def private_filename_source(work, tmp_path):
    """Upload and parse real synthetic XLSX bytes; only the scanner port is synthetic."""
    from io import BytesIO

    from openpyxl import Workbook
    from security_fixture import secured_parse, synthetic_runtime

    from pdos_next.models import Artifact
    from pdos_next.object_storage import LocalPrivateObjectStore
    from pdos_next.original_security import configure
    from pdos_next.originals import upload
    from tests.test_durable_evidence import upload_input

    filename = "客户X需求.xlsx"
    workbook = Workbook()
    workbook.active["A1"] = "Confidential synthetic original request"
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    store = LocalPrivateObjectStore(tmp_path / "private-filename-regression")
    prior = getattr(work.engine, "_pdos_security_runtime", None)
    configure(work.engine, synthetic_runtime())
    try:
        with human_session(work) as session:
            receipt = upload(
                session,
                Context(work.tenant, work.human, work.human, category_id=work.category),
                None,
                upload_input(output.getvalue(), filename=filename),
                store,
            )
        reference = {
            "tenant_id": str(work.tenant),
            "category_id": str(work.category),
            "actor_id": str(work.human),
            "requester_id": str(work.human),
            "product_id": None,
            "subject_id": receipt["subject_id"],
        }
        parsed = secured_parse(work.engine, reference, store)
        assert parsed["status"] == "parsed", parsed
        with human_session(work) as session:
            source = session.scalar(
                select(Artifact).where(Artifact.original_id == UUID(receipt["subject_id"]))
            )
            assert source.visibility == "private" and source.product_id is None
            assert source.content.splitlines()[0] == "Confidential synthetic original request"
            source_id = source.id
        yield source_id, filename
    finally:
        configure(work.engine, prior)


@pytest.mark.parametrize("identity_history", ["removed_item_reference", "private_run_read_set"])
def test_share_retains_original_filename_identity_after_source_counter_is_empty(
    work, monkeypatch, private_filename_source, identity_history
):
    private_source, filename = private_filename_source
    data = payload(work)
    if identity_history == "removed_item_reference":
        data["groups"]["items"][0]["source_refs"] = [
            {
                "type": "original",
                "id": str(private_source),
                "version": 1,
                "line": 1,
                "quote": "Confidential synthetic original request",
            }
        ]
    proposal_id, _ = create(work, data)
    if identity_history == "removed_item_reference":
        item = read(work, proposal_id).json()["items"][0]
        assert source_rows(work, proposal_id) == [(str(private_source), 1, 1, "private")]
        patched = post(
            work,
            evidence_request(
                work,
                "proposal.item.patch",
                {
                    "proposal_id": proposal_id,
                    "ops": [
                        {
                            "kind": item["kind"],
                            "item_id": item["item_id"],
                            "base_version": item["version"],
                            "content": item["content"],
                            "source_refs": [],
                        }
                    ],
                },
            ),
        )
        assert patched.status_code == 200, patched.text
    assert source_rows(work, proposal_id) == []
    assert read(work, proposal_id).json()["private_source_count"] == 0
    public_source = artifact(work)
    fixture, arguments = claim_fixture(
        work,
        monkeypatch,
        public_source,
        proposal_id,
        private_context=True,
        text=f"来源文件 {filename} 的合成研究事实",
        read_artifacts=(private_source,) if identity_history == "private_run_read_set" else (),
    )
    claim = fixture.adapter.execute(
        fixture.scope,
        "evidence.claim.record",
        arguments,
        execution_key(fixture.scope.run_id, fixture.source.model_call_id, 0),
        source=fixture.source,
    )
    assert claim_read(work, claim["subject_id"]).json()["source"]["id"] == str(public_source)
    checked = post(work, share_request(work, proposal_id), preview=True)
    assert checked.status_code == 200, checked.text
    hits = checked.json()["review"]["checks"]["hits"]
    assert any(hit["kind"] == "filename" and hit["value"] == filename for hit in hits)
    denied = post(work, checked.json()["command"])
    assert denied.status_code == 409, denied.text
    assert denied.json()["detail"]["reason"] == "identity_not_removed"
    assert read(work, proposal_id, work.peer).status_code == 404
    assert claim_read(work, claim["subject_id"], actor=work.peer).status_code == 404
    assert source_rows(work, proposal_id) == []
