"""Port-level policy tests without a database; PostgreSQL integration runs centrally."""

from copy import deepcopy
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from pdos_next.domain.preproject import evidence_service as service
from pdos_next.domain.preproject.evidence_schemas import (
    ClaimWithdraw,
    EvidenceLinkCreate,
    ProposalShare,
)
from pdos_next.errors import DomainError


class MemorySession:
    def __init__(self, scalar=None, rows=()):
        self.scalar_value, self.rows = scalar, list(rows)
        self.added, self.deleted = [], []
        self.info = {}

    def scalar(self, query, parameters=None):
        return self.scalar_value

    def scalars(self, query):
        return self.rows

    def add(self, row):
        self.added.append(row)

    def delete(self, row):
        self.deleted.append(row)

    def flush(self):
        pass


@pytest.fixture
def ctx():
    human = uuid4()
    return NS(
        tenant_id=uuid4(),
        category_id=uuid4(),
        actor_id=human,
        requester_id=human,
        run_id=None,
        agent_run_id=None,
    )


def proposal(ctx, **changes):
    return NS(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        owner_id=ctx.requester_id,
        revision=1,
        visibility="private",
        effective_visibility="private",
        private_source_count=0,
        status="draft",
        current_submission_id=None,
        **changes,
    )


def link_payload(kind="claim", target_type="proposal_item"):
    return EvidenceLinkCreate(
        evidence={"type": kind, "id": uuid4(), "version": 1},
        target={"type": target_type, "id": uuid4(), "version": 1},
        relation="supports",
    )


def share_payload(owner, **changes):
    return ProposalShare(
        **{
            "proposal_id": owner.id,
            "expected_revision": owner.revision,
            "visibility": "category",
            "audience_ids": [],
            "deidentified_confirmed": False,
            **changes,
        }
    )


def assert_reason(error, reason):
    assert error.value.detail["reason"] == reason


def test_shared_bottom_source_does_not_make_private_context_claim_shareable(ctx, monkeypatch):
    owner = proposal(ctx)
    payload = link_payload(target_type="knowledge_entry")
    monkeypatch.setattr(service, "category_scope", lambda *a, **k: None)
    monkeypatch.setattr(service, "_target", lambda *a: (NS(), None, True))
    monkeypatch.setattr(
        service,
        "_source",
        lambda *a: (
            NS(type="snapshot", id=uuid4(), version=1),
            "shared",
            NS(privacy="private", proposal_id=owner.id),
        ),
    )
    with pytest.raises(DomainError) as error:
        service.validate(MemorySession(), ctx, NS(), NS(), payload)
    assert_reason(error, "private_source_in_shared")


def test_private_context_claim_can_link_same_private_proposal_with_shared_source_count(
    ctx, monkeypatch
):
    owner = proposal(ctx)
    source = NS(type="snapshot", id=uuid4(), version=1)
    monkeypatch.setattr(service, "category_scope", lambda *a, **k: None)
    monkeypatch.setattr(service, "_target", lambda *a: (NS(), owner, False))
    monkeypatch.setattr(
        service,
        "_source",
        lambda *a: (
            source,
            "shared",
            NS(privacy="private", proposal_id=owner.id),
        ),
    )
    monkeypatch.setattr(service, "_link_provenance", lambda *a: {"origin": "human"})
    checked = service.validate(MemorySession(), ctx, NS(), NS(), link_payload())
    assert checked.source_privacy == "shared"
    assert checked.proposal is owner and checked.source_ref is source


def test_private_claim_cannot_be_relinked_into_another_private_proposal(ctx, monkeypatch):
    owner = proposal(ctx)
    monkeypatch.setattr(service, "category_scope", lambda *a, **k: None)
    monkeypatch.setattr(service, "_target", lambda *a: (NS(), owner, False))
    monkeypatch.setattr(
        service,
        "_source",
        lambda *a: (
            NS(),
            "shared",
            NS(privacy="private", proposal_id=uuid4()),
        ),
    )
    with pytest.raises(DomainError) as error:
        service.validate(MemorySession(), ctx, NS(), NS(), link_payload())
    assert_reason(error, "claim_proposal_mismatch")


@pytest.mark.parametrize("state", ["in_review", "approved", "rejected", "withdrawn"])
def test_associations_cannot_change_locked_proposals(state):
    with pytest.raises(DomainError) as error:
        service._editable(NS(status=state))
    assert_reason(error, "proposal_locked")


@pytest.mark.parametrize("state", ["draft", "returned"])
def test_draft_and_returned_proposals_remain_editable(state):
    service._editable(NS(status=state))


def test_readable_does_not_mean_owner_writable(ctx):
    with pytest.raises(DomainError) as error:
        service._owner(ctx, NS(owner_id=uuid4()))
    assert_reason(error, "owner_only")


def test_reference_counter_preserves_other_items_and_counts_distinct_private_sources(ctx):
    owner = proposal(ctx)
    owner.private_source_count = 1
    pointer = NS(ref_count=3, privacy="private")
    session = MemorySession(scalar=pointer)
    ref = NS(type="artifact", id=uuid4(), version=2)
    service._source_delta(session, ctx, owner, ref, -2, "private")
    assert pointer.ref_count == 1 and owner.private_source_count == 1
    assert session.deleted == []
    service._source_delta(session, ctx, owner, ref, -1, "private")
    assert session.deleted == [pointer] and owner.private_source_count == 0


def test_shared_snapshot_counter_does_not_force_proposal_private(ctx):
    owner = proposal(ctx)
    owner.visibility = owner.effective_visibility = "category"
    session = MemorySession()
    service._source_delta(
        session, ctx, owner, NS(type="snapshot", id=uuid4(), version=1), 1, "shared"
    )
    assert owner.private_source_count == 0 and owner.effective_visibility == "category"
    assert session.added[0].source_type == "snapshot" and session.added[0].ref_count == 1


@pytest.mark.parametrize("pointer", [None, NS(ref_count=1, privacy="shared")])
def test_withdrawal_never_silently_underflows_reference_counter(ctx, pointer):
    owner = proposal(ctx)
    session = MemorySession(scalar=pointer)
    with pytest.raises(DomainError) as error:
        service._source_delta(
            session, ctx, owner, NS(type="snapshot", id=uuid4(), version=1), -2, "shared"
        )
    assert_reason(error, "source_count_inconsistent")
    assert session.added == [] and session.deleted == []


def test_withdrawal_preserves_claim_text_and_historical_item_values(ctx, monkeypatch):
    claim = NS(
        id=uuid4(),
        revision=1,
        status="active",
        privacy="private",
        quote="来源原话",
        content={"value": "42"},
        writer_id=uuid4(),
    )
    immutable = deepcopy((claim.content, claim.quote, claim.writer_id))
    link = NS(reverted_by_receipt_id=None)
    owner = proposal(ctx)
    assessed = service.ValidatedEvidence(
        claim,
        source_ref=NS(),
        source_privacy="shared",
        links=[link],
        changes={owner.id: (owner, 2)},
        confirmation_id=uuid4(),
    )
    calls = []
    monkeypatch.setattr(service, "_source_delta", lambda *args: calls.append(args))
    session = MemorySession()
    payload = ClaimWithdraw(claim_id=claim.id, expected_version=1, reason="纠正登记错误")
    subject, kind, visibility = service.apply_validated(session, ctx, NS(), NS(), payload, assessed)
    assert claim.status == "withdrawn" and claim.revision == 2
    assert (claim.content, claim.quote, claim.writer_id) == immutable
    assert calls == []
    assert link.reverted_by_receipt_id is None
    assert kind == "claim" and visibility == "private"
    assert session.added[0].confirmation_id == assessed.confirmation_id
    assert session.added[0].receipt_id == subject.prepared_receipt_id


def test_withdrawal_refuses_to_write_without_consumed_confirmation(ctx):
    row = NS(id=uuid4(), revision=1, status="active", privacy="shared")
    session = MemorySession()
    with pytest.raises(DomainError) as error:
        service.apply_validated(
            session,
            ctx,
            NS(),
            NS(),
            ClaimWithdraw(claim_id=row.id, expected_version=1, reason="错误"),
            service.ValidatedEvidence(row),
        )
    assert_reason(error, "confirmation_missing")
    assert session.added == [] and row.status == "active"


def test_hidden_signed_dependency_still_blocks_withdrawal(ctx):
    with pytest.raises(DomainError) as error:
        service._signed_consumptions(MemorySession(scalar=True), ctx, NS(id=uuid4()))
    assert_reason(error, "consumed_by_decision")


def test_unsealed_dependency_does_not_block_withdrawal(ctx):
    service._signed_consumptions(MemorySession(scalar=False), ctx, NS(id=uuid4()))


def test_definition_target_requires_its_actual_product_scope(ctx, monkeypatch):
    row = NS(product_id=uuid4())
    monkeypatch.setattr(service, "_row", lambda *a, **kw: row)
    with pytest.raises(DomainError) as error:
        service._target(
            MemorySession(),
            ctx,
            NS(product_id=uuid4()),
            NS(id=uuid4()),
            link_payload(target_type="definition_spec").target,
        )
    assert_reason(error, "evidence_target_scope")


def test_link_append_does_not_rewrite_human_item_content_or_attribution(ctx, monkeypatch):
    from pdos_next.domain.preproject import views

    owner = proposal(ctx)
    item = NS(content={"value": "42", "unit": "dB"}, writer_id=uuid4(), origin="human")
    original = deepcopy(vars(item))
    assessed = service.ValidatedEvidence(
        item,
        provenance={
            "origin": "human",
            "writer_id": ctx.actor_id,
            "run_id": None,
            "confirmed_by": None,
        },
        proposal=owner,
        source_ref=NS(),
        source_privacy="shared",
    )
    monkeypatch.setattr(service, "_source_delta", lambda *a: None)
    monkeypatch.setattr(views, "document", lambda *a: {"title": "合成提案"})
    session = MemorySession()
    subject, kind, _ = service.apply_validated(session, ctx, NS(), NS(), link_payload(), assessed)
    assert vars(item) == original
    assert owner.revision == 2 and kind == "evidence_link"
    assert session.added[0].receipt_id == subject.prepared_receipt_id
    assert session.added[1].revision == owner.revision


def test_share_updates_only_audience_and_proposal_revision(ctx, monkeypatch):
    from pdos_next.domain.preproject import views

    owner = proposal(ctx)
    old_person, new_person = uuid4(), uuid4()
    old_audience = NS(principal_id=old_person)
    private_claim = NS(id=uuid4(), privacy="private", content={"text": "脱敏观察"})
    claim_before = deepcopy(vars(private_claim))
    session = MemorySession(rows=[old_audience])
    assessed = service.ValidatedEvidence(owner, checks={"hits": []}, claims=[private_claim])
    payload = share_payload(
        owner, visibility="audience", audience_ids=[new_person], deidentified_confirmed=True
    )
    monkeypatch.setattr(views, "document", lambda *a: {"title": "合成提案"})
    subject, kind, visibility = service.apply_validated(session, ctx, NS(), NS(), payload, assessed)
    assert (kind, visibility, owner.revision) == ("proposal", "audience", 2)
    assert vars(private_claim) == claim_before
    assert session.deleted == [old_audience]
    assert session.added[0].principal_id == new_person
    assert session.added[0].object_type == "proposals"
    assert subject.action_result["shared_claim_ids"] == [str(private_claim.id)]


def test_share_preview_can_show_identity_hits_but_apply_refuses_them(ctx, monkeypatch):
    owner = proposal(ctx)
    payload = share_payload(owner, deidentified_confirmed=True)
    assessed = service.ValidatedEvidence(
        owner, checks={"hits": [{"kind": "identity", "value": "客户甲"}]}
    )
    monkeypatch.setattr(service, "validate", lambda *a: assessed)
    review = service.preview_view(
        MemorySession(), ctx, NS(operation="proposal.share"), NS(), payload
    )
    assert review["checks"]["hits"][0]["value"] == "客户甲"
    session = MemorySession()
    with pytest.raises(DomainError) as error:
        service.apply_validated(session, ctx, NS(), NS(), payload, assessed)
    assert_reason(error, "identity_not_removed")
    assert owner.visibility == "private" and session.added == []


def test_share_requires_explicit_confirmation_for_active_private_context_claims(ctx):
    owner = proposal(ctx)
    assessed = service.ValidatedEvidence(owner, checks={"hits": []}, claims=[NS(id=uuid4())])
    with pytest.raises(DomainError) as error:
        service.apply_validated(MemorySession(), ctx, NS(), NS(), share_payload(owner), assessed)
    assert_reason(error, "deidentification_not_confirmed")
    assert owner.visibility == "private"


@pytest.mark.parametrize("field", ["run_id", "agent_run_id"])
def test_share_rejects_ai_run_even_if_actor_is_proposal_owner(ctx, monkeypatch, field):
    setattr(ctx, field, uuid4())
    monkeypatch.setattr(service, "category_scope", lambda *a, **k: None)
    with pytest.raises(DomainError) as error:
        service.validate(MemorySession(), ctx, NS(), NS(), share_payload(proposal(ctx)))
    assert_reason(error, "owner_only")


def test_share_watermark_changes_confirmation_material_without_payload_changes(ctx, monkeypatch):
    owner = proposal(ctx)
    assessed = service.ValidatedEvidence(
        owner,
        checks={"hits": [], "claims": []},
        watermark={"sources": [], "counts": [], "links": []},
    )
    monkeypatch.setattr(service, "validate", lambda *a: assessed)
    args = (MemorySession(), ctx, NS(operation="proposal.share"), NS(), share_payload(owner))
    first = service.digest(service.preview_view(*args))
    assessed.watermark["links"].append(str(uuid4()))
    assert service.digest(service.preview_view(*args)) != first


def test_link_projection_suppresses_withdrawn_claims_without_emitting_their_text(ctx, monkeypatch):
    active, withdrawn = uuid4(), uuid4()
    rows = [
        NS(evidence_type="claim", evidence_id=identity, evidence_version=1)
        for identity in (active, withdrawn)
    ]
    monkeypatch.setattr(service, "links_for_target", lambda *a: rows)
    monkeypatch.setattr(
        service,
        "_row",
        lambda s, c, m, identity, **kw: NS(
            status="active" if identity == active else "withdrawn", revision=1
        ),
    )
    refs = service.active_link_refs(MemorySession(), ctx, "proposal_item", uuid4(), 1)
    assert refs == [{"type": "claim", "id": str(active), "version": 1}]
