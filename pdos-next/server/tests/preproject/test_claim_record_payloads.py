"""Pure claim admission checks; no database, provider, or qualification writes."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.agent_kernel import claim_candidate as candidate
from pdos_next.agent_kernel.models import AgentEvent, PublicWebSnapshot
from pdos_next.contracts import Command
from pdos_next.domain.preproject import claim_access
from pdos_next.domain.preproject.evidence_schemas import ClaimRecord
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Principal, Product, UploadedOriginal
from pdos_next.service import Context


class MemorySession:
    def __init__(self, rows=(), answers=()):
        self.rows = {(model, row.id): row for model, row in rows}
        self.answers = iter(answers)
        self.info = {}

    def get(self, model, identity):
        return self.rows.get((model, identity))

    def scalar(self, _query):
        return next(self.answers)


@pytest.mark.parametrize("status,code", [("withdrawn", "SOURCE_STALE"), (None, "NOT_FOUND")])
def test_missing_claim_body_uses_only_authorized_reference_status(status, code):
    tenant, category, identity = uuid4(), uuid4(), uuid4()

    class MetadataSession(MemorySession):
        def execute(self, query, parameters):
            assert "m3_claim_reference_states" in str(query)
            assert parameters == {"tenant": tenant, "category": category, "ids": [identity]}
            return [(identity, 2, status)] if status else []

    with pytest.raises(DomainError) as error:
        claim_access.resolve(
            MetadataSession(answers=[None]),
            SimpleNamespace(tenant_id=tenant, category_id=category),
            identity,
            1,
            approved=True,
        )
    assert error.value.code == code
    assert error.value.detail["reason"] == (
        "claim_withdrawn" if status else "claim_not_found"
    )


def fixture():
    tenant, category, human = uuid4(), uuid4(), uuid4()
    ctx = Context(tenant, human, human, category_id=category)
    source = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant,
        category_id=category,
        visibility="category",
        status="ok",
        markdown="first\n  exact quote  \nlast",
    )
    actor = SimpleNamespace(id=human, tenant_id=tenant, kind="human", active=True)
    run = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant,
        category_id=category,
        requester_id=human,
        writer_id=uuid4(),
        product_id=None,
        proposal_id=None,
        private_context=False,
        cancel_epoch=0,
        reverted_at=None,
        state="running",
    )
    scope = SimpleNamespace(id=None, revision=1)
    return SimpleNamespace(ctx=ctx, source=source, actor=actor, run=run, scope=scope)


def canonical(f, **changes):
    return ClaimRecord(
        source={
            "kind": "snapshot",
            "id": f.source.id,
            "version": 1,
            "locator": "line:2",
            "quote": "  exact quote  ",
        },
        content={"text": "synthetic supported statement"},
        **changes,
    )


def command(f, payload):
    return Command(
        command_id=uuid4(),
        idempotency_key=str(uuid4()),
        category_id=f.ctx.category_id,
        product_id=None,
        expected_revision=1,
        operation="evidence.claim.record",
        source_read_set=[],
        payload=payload.model_dump(mode="json"),
    )


def assert_reason(error, code, reason):
    assert error.value.code == code
    assert error.value.detail["reason"] == reason


def test_legacy_payload_keeps_s0_serialized_content_and_semantic_digest():
    identity = uuid4()
    old = {
        "artifact_id": str(identity),
        "line": 1,
        "quote": "literal",
        "statement": "statement",
        "nature": "extracted",
        "availability": "known",
        "visibility": "category",
        "prepared_event_id": None,
        "confirmation_token": None,
    }
    payload = ClaimRecord.model_validate(old)
    assert payload.model_dump(mode="json") == old
    assert candidate.content(payload) == {
        k: v for k, v in old.items() if k not in {"prepared_event_id", "confirmation_token"}
    }
    assert candidate.semantic(payload) == {
        k: v for k, v in old.items() if k != "confirmation_token"
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("privacy", "shared"),
        ("origin", "human"),
        ("run_id", str(uuid4())),
        ("writer_id", str(uuid4())),
        ("confirmed_by", str(uuid4())),
        ("visibility", "category"),
        ("artifact_id", str(uuid4())),
    ],
)
def test_canonical_payload_rejects_client_provenance_and_legacy_mixing(field, value):
    f = fixture()
    body = canonical(f).model_dump(mode="json")
    body[field] = value
    with pytest.raises(ValidationError):
        ClaimRecord.model_validate(body)


@pytest.mark.parametrize("nature", ["observed", "computed", "inferred", "decided"])
def test_vendor_claimed_is_reserved_for_extracted_evidence(nature):
    with pytest.raises(ValidationError):
        canonical(fixture(), nature=nature, vendor_claimed=True)


def test_canonical_quote_keeps_literal_whitespace_and_source_version():
    f = fixture()
    payload = canonical(f)
    ref = candidate._reference(command(f, payload), payload)
    assert ref.quote == "  exact quote  " and ref.version == 1 and ref.line == 2
    assert claim_access.load_source(MemorySession(answers=[f.source]), f.ctx, ref) is f.source
    f.source.markdown = "first\nexact quote\nlast"
    with pytest.raises(DomainError) as error:
        claim_access.load_source(MemorySession(answers=[f.source]), f.ctx, ref)
    assert_reason(error, "VALIDATION_FAILED", "quote_not_in_source")


@pytest.mark.parametrize("mutation", ["version", "tenant", "category", "status", "line", "quote"])
def test_snapshot_admission_checks_exact_scope_version_state_and_quote(mutation):
    f = fixture()
    payload = canonical(f)
    ref = candidate._reference(command(f, payload), payload)
    reason = "quote_not_in_source"
    code = "VALIDATION_FAILED"
    if mutation == "version":
        ref = ref.model_copy(update={"version": 2})
        code, reason = "SOURCE_STALE", "snapshot_unavailable"
    elif mutation in {"tenant", "category"}:
        setattr(f.source, f"{mutation}_id", uuid4())
        code, reason = "SOURCE_UNAVAILABLE", "snapshot_unreadable"
    elif mutation == "status":
        f.source.status = "failed"
        code, reason = "SOURCE_STALE", "snapshot_unavailable"
    elif mutation == "line":
        ref = ref.model_copy(update={"line": 1})
    else:
        ref = ref.model_copy(update={"quote": "invented quotation"})
    with pytest.raises(DomainError) as error:
        claim_access.load_source(MemorySession(answers=[f.source]), f.ctx, ref)
    assert_reason(error, code, reason)


def test_unsupported_locator_and_unpinned_legacy_source_fail_closed():
    f = fixture()
    body = canonical(f).model_dump(mode="json")
    body["source"]["locator"] = "page:1"
    body["source"].pop("line")
    payload = ClaimRecord.model_validate(body)
    with pytest.raises(DomainError) as error:
        candidate._reference(command(f, payload), payload)
    assert_reason(error, "VALIDATION_FAILED", "unsupported_locator")
    legacy = ClaimRecord(artifact_id=uuid4(), line=1, quote="literal", statement="fact")
    with pytest.raises(DomainError) as error:
        candidate._reference(command(f, legacy), legacy)
    assert_reason(error, "MISSING_REQUIRED_EVIDENCE", "source_version_required")


@pytest.mark.parametrize("nature", ["observed", "decided"])
def test_ai_cannot_claim_firsthand_observations_or_named_decisions(nature):
    f = fixture()
    payload = canonical(f, nature=nature)
    with pytest.raises(DomainError) as error:
        candidate._nature(payload, f.run)
    assert_reason(error, "FORBIDDEN_SCOPE", "human_fact_required")
    candidate._nature(payload, None)


def test_computed_claim_requires_an_actual_deterministic_proof_port():
    f = fixture()
    payload = canonical(f, nature="computed", extraction_ref={"receipt_id": str(uuid4())})
    for run in (None, f.run):
        with pytest.raises(DomainError) as error:
            candidate._nature(payload, run)
        assert_reason(error, "SOURCE_UNAVAILABLE", "deterministic_proof_required")


def test_not_applicable_requires_stated_basis_and_never_contains_a_value():
    f = fixture()
    body = canonical(f, availability="not_applicable").model_dump(mode="json")
    body["content"] = {}
    payload = ClaimRecord.model_validate(body)
    with pytest.raises(DomainError) as error:
        candidate._nature(payload, None)
    assert_reason(error, "VALIDATION_FAILED", "not_applicable_reason_required")
    body["content"] = {"text": "not applicable because the source excludes this variant"}
    candidate._nature(ClaimRecord.model_validate(body), None)
    body["content"]["value"] = "10"
    with pytest.raises(ValidationError):
        ClaimRecord.model_validate(body)


@pytest.mark.parametrize(
    "private_source,private_run,expected",
    [
        (False, False, "shared"),
        (True, False, "private"),
        (False, True, "private"),
        (True, True, "private"),
    ],
)
def test_privacy_uses_real_source_and_run_even_for_public_snapshot(
    monkeypatch, private_source, private_run, expected
):
    f = fixture()
    f.source.visibility = "private" if private_source else "category"
    f.run.proposal_id, f.run.private_context = uuid4(), private_run
    payload = canonical(f)
    ref = candidate._reference(command(f, payload), payload)
    seen = []
    monkeypatch.setattr(
        "pdos_next.domain.preproject.access.proposal",
        lambda _s, _ctx, identity, **_kw: seen.append(identity),
    )
    session = MemorySession(rows=[(PublicWebSnapshot, f.source)])
    identity, privacy, visibility = candidate._placement(
        session, f.ctx, f.scope, payload, ref, f.run
    )
    assert identity == f.run.proposal_id and seen == [identity]
    assert privacy == expected
    assert visibility == ("category" if expected == "shared" else "audience")


def test_private_run_requires_actual_bound_proposal_and_caller_cannot_replace_it(monkeypatch):
    f = fixture()
    f.run.private_context = True
    payload = canonical(f)
    ref = candidate._reference(command(f, payload), payload)
    session = MemorySession(rows=[(PublicWebSnapshot, f.source)])
    with pytest.raises(DomainError) as error:
        candidate._placement(session, f.ctx, f.scope, payload, ref, f.run)
    assert_reason(error, "FORBIDDEN_SCOPE", "private_context_run")
    payload.proposal_id = uuid4()
    monkeypatch.setattr(
        "pdos_next.domain.preproject.access.proposal",
        lambda *_a, **_kw: pytest.fail("Must reject caller substitution before reading it"),
    )
    with pytest.raises(DomainError) as error:
        candidate._placement(session, f.ctx, f.scope, payload, ref, f.run)
    assert_reason(error, "FORBIDDEN_SCOPE", "proposal_run_mismatch")


def test_source_root_includes_private_original_and_private_parent_product():
    f = fixture()
    product = SimpleNamespace(
        id=uuid4(), tenant_id=f.ctx.tenant_id, category_id=f.ctx.category_id, visibility="private"
    )
    original = SimpleNamespace(
        id=uuid4(),
        tenant_id=f.ctx.tenant_id,
        category_id=f.ctx.category_id,
        visibility="category",
        product_id=product.id,
    )
    artifact = SimpleNamespace(
        id=uuid4(),
        tenant_id=f.ctx.tenant_id,
        category_id=f.ctx.category_id,
        visibility="category",
        product_id=None,
        original_id=original.id,
    )
    row = SimpleNamespace(source_kind="artifact", artifact_id=artifact.id)
    session = MemorySession(
        rows=[
            (Artifact, artifact),
            (Product, product),
            (UploadedOriginal, original),
        ]
    )
    assert claim_access.source_privacy(session, f.ctx, row) == "private"
    product.visibility = "category"
    original.visibility = "private"
    assert claim_access.source_privacy(session, f.ctx, row) == "private"
    original.visibility = "category"
    assert claim_access.source_privacy(session, f.ctx, row) == "shared"
    del session.rows[(Product, product.id)]
    with pytest.raises(DomainError) as error:
        claim_access.source_privacy(session, f.ctx, row)
    assert_reason(error, "SOURCE_UNAVAILABLE", "source_unreadable")


def candidate_session(f, payload, command):
    payload.prepared_event_id = uuid4()
    command.payload = payload.model_dump(mode="json")
    event = SimpleNamespace(
        id=payload.prepared_event_id,
        tenant_id=f.ctx.tenant_id,
        run_id=f.run.id,
        body={
            "type": "claim_candidate",
            "cancel_epoch": 0,
            "command": command.model_dump(mode="json"),
        },
    )
    writer = SimpleNamespace(id=f.run.writer_id, active=True, kind="agent")
    return event, MemorySession(
        rows=[(Principal, f.actor), (Principal, writer), (AgentEvent, event)],
        answers=[f.run],
    )


@pytest.mark.parametrize("mutation", ["epoch", "cancelled", "content", "read_set", "category"])
def test_real_candidate_binding_keeps_scope_epoch_content_and_source_proof(mutation):
    f = fixture()
    payload = canonical(f)
    cmd = command(f, payload)
    event, session = candidate_session(f, payload, cmd)
    code, reason = "FORBIDDEN_SCOPE", "candidate_binding_invalid"
    if mutation == "epoch":
        f.run.cancel_epoch = 1
    elif mutation == "cancelled":
        f.run.state = "cancelled"
    elif mutation == "category":
        f.run.category_id = uuid4()
    else:
        code, reason = "DUPLICATE_INTENT_CONFLICT", "candidate_content_changed"
        event.body = deepcopy(event.body)
        if mutation == "content":
            event.body["command"]["payload"]["content"]["text"] = "another model candidate"
        else:
            event.body["command"]["source_read_set"] = [
                {"artifact_id": str(uuid4()), "expected_revision": 1}
            ]
    with pytest.raises(DomainError) as error:
        candidate._candidate_run(session, f.ctx, cmd, f.scope, payload)
    assert_reason(error, code, reason)


def test_t1_apply_keeps_candidate_ai_origin_confirmation_and_atomic_receipt(monkeypatch):
    f = fixture()
    payload = canonical(f)
    payload.prepared_event_id = uuid4()
    cmd = command(f, payload)
    ref = candidate._reference(cmd, payload)
    admitted = candidate.PreparedClaim(f.source, f.run, ref, uuid4(), "private", "audience")
    monkeypatch.setattr(candidate, "prepared", lambda *_args: admitted)
    row, subject_type, visibility = candidate.apply(None, f.ctx, cmd, f.scope, payload)
    assert subject_type == "claim" and visibility == "audience"
    assert row.source_kind == "snapshot" and row.snapshot_id == f.source.id
    assert row.artifact_id is None and row.product_id is None
    assert row.origin == "ai_draft" and row.writer_id == f.run.writer_id
    assert row.run_id == row.prepared_by_run_id == f.run.id
    assert row.confirmed_by == f.ctx.actor_id and row.prepared_event_id == payload.prepared_event_id
    assert row.receipt_id == row.prepared_receipt_id
    assert row.content == payload.content and row.quote == "  exact quote  "


@pytest.mark.parametrize(
    "owner,explicit,allowed", [(True, False, True), (False, True, True), (False, False, False)]
)
def test_withdrawn_claim_body_is_only_historical_for_owner_or_explicit_audience(
    owner, explicit, allowed
):
    f = fixture()
    row = SimpleNamespace(
        id=uuid4(),
        tenant_id=f.ctx.tenant_id,
        category_id=f.ctx.category_id,
        human_owner_id=f.ctx.requester_id if owner else uuid4(),
        proposal_id=uuid4(),
        revision=1,
        status="withdrawn",
    )
    answers = [row] + ([] if owner else [uuid4() if explicit else None])
    if allowed:
        assert (
            claim_access.resolve(
                MemorySession(answers=answers), f.ctx, row.id, 1, allow_withdrawn=True
            )
            is row
        )
    else:
        with pytest.raises(DomainError) as error:
            claim_access.resolve(
                MemorySession(answers=answers), f.ctx, row.id, 1, allow_withdrawn=True
            )
        assert_reason(error, "NOT_FOUND", "claim_not_found")
    with pytest.raises(DomainError) as error:
        claim_access.resolve(
            MemorySession(answers=[row]), f.ctx, row.id, 1, approved=True, allow_withdrawn=True
        )
    assert_reason(error, "SOURCE_STALE", "claim_withdrawn")


def test_legacy_visibility_cannot_expand_a_private_claim_parent_product():
    f = fixture()
    parent = SimpleNamespace(
        id=uuid4(), tenant_id=f.ctx.tenant_id, category_id=f.ctx.category_id, visibility="private"
    )
    f.scope.id = parent.id
    artifact = SimpleNamespace(
        id=uuid4(),
        tenant_id=f.ctx.tenant_id,
        category_id=f.ctx.category_id,
        visibility="category",
        product_id=None,
        original_id=None,
    )
    payload = ClaimRecord(
        artifact_id=artifact.id, line=1, quote="literal", statement="fact", visibility="category"
    )
    from pdos_next.domain.preproject.schemas import Reference

    ref = Reference(type="artifact", id=artifact.id, version=1, line=1, quote="literal")
    session = MemorySession(rows=[(Artifact, artifact), (Product, parent)])
    with pytest.raises(DomainError) as error:
        candidate._placement(session, f.ctx, f.scope, payload, ref, None)
    assert_reason(error, "FORBIDDEN_SCOPE", "private_source_in_shared")
    payload.visibility = "private"
    assert candidate._placement(session, f.ctx, f.scope, payload, ref, None) == (
        None,
        "private",
        "private",
    )


def test_withdrawal_version_bump_still_reports_claim_withdrawn_for_g0_reference():
    f = fixture()
    row = SimpleNamespace(
        id=uuid4(),
        tenant_id=f.ctx.tenant_id,
        category_id=f.ctx.category_id,
        human_owner_id=f.ctx.requester_id,
        revision=2,
        status="withdrawn",
    )
    with pytest.raises(DomainError) as error:
        claim_access.resolve(MemorySession(answers=[row]), f.ctx, row.id, 1, approved=True)
    assert_reason(error, "SOURCE_STALE", "claim_withdrawn")


def test_withdrawn_history_does_not_inherit_new_proposal_audience():
    f = fixture()
    row = SimpleNamespace(id=uuid4(), human_owner_id=uuid4(), proposal_id=uuid4())
    captured = []

    class Capture:
        def scalar(self, query):
            captured.append(query.compile().params)
            return None

    assert not claim_access._historical_reader(Capture(), f.ctx, row)
    values = set(captured[0].values())
    assert "claims" in values and "proposals" not in values
    assert row.proposal_id not in values and row.id in values
