"""Pure candidates only; fixtures never establish saved approval or real delivery."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.external_handoff import rules, schemas
from pdos_next.domain.release import rules as release_rules
from pdos_next.domain.release.schemas import ApprovePayload, VersionRef
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import Context
from tests.release.test_rules import AT
from tests.release.test_rules import case as release_case  # noqa: F401


@pytest.fixture
def case(request):
    base = request.getfixturevalue("release_case")
    package_ref = VersionRef(id=uuid4(), revision=1)
    decisions = []
    for operation in ("release.engineering.approve", "release.manufacturing.approve"):
        payload = ApprovePayload(
            package=package_ref,
            release_scope=base.payload.release_scope,
            purpose=base.payload.purpose,
            sources=(base.original,),
            reason="本人拟作本专业范围决定",
        )
        plan = release_rules.prepare_decision(
            operation, payload.model_dump(mode="json"), package_ref, base.plan, ctx=base.ctx, at=AT
        )
        decisions.append(
            schemas.ActualDecision(ref=VersionRef(id=uuid4(), revision=1), plan=plan, current=True)
        )
    source = schemas.OriginalRef.model_validate(base.original)
    mapping = schemas.NumberMapping(
        ref={
            "kind": "engineering_configuration",
            **base.payload.subject_config.engineering_configuration.model_dump(),
        },
        external_number="ERP-ENG-1",
        external_version="V1",
        sources=(source,),
    )
    file = schemas.ManifestFile(
        artifact={"id": source.id, "revision": source.revision},
        logical_name="controlled-package.json",
        content_sha256="a" * 64,
        external_number="ERP-DOC-1",
        external_version="V1",
        sources=(source,),
    )
    payload = schemas.AuthorizePayload(
        project_id=base.scope.project_id,
        package=package_ref,
        engineering_decision=decisions[0].ref,
        manufacturing_decision=decisions[1].ref,
        subject_config=base.payload.subject_config,
        release_scope=base.payload.release_scope,
        purpose=base.payload.purpose,
        visibility="category",
        destination={"system": "erp-test", "recipient_id": "factory-receiver-1"},
        external_id="handoff-001",
        mappings=(mapping,),
        manifest=(file,),
        sources=(source,),
        reason="固定发布包及两专业批准，准备人工交接",
    )
    data = schemas.ActualData(
        scope=base.scope,
        category_id=base.ctx.category_id,
        visibility="category",
        package_ref=package_ref,
        package=base.plan,
        package_current=True,
        decisions=tuple(decisions),
        mappings=(mapping,),
        files=(file,),
        contract_read=True,
        required_mapping_refs=(mapping.ref,),
        required_manifest_refs=(file.artifact,),
        sources_current=True,
        sources=(base.source,),
        required_source_read_set=base.material.required_source_read_set,
    )
    plan = rules.prepare(payload, data, ctx=base.ctx, at=AT)
    handoff, intent = VersionRef(id=uuid4(), revision=1), VersionRef(id=uuid4(), revision=1)
    issuer = schemas.ReceiptIssuer(
        key="actual-host-issuer",
        version="v1",
        epoch=1,
        system=payload.destination.system,
        subject_id=payload.destination.recipient_id,
        proof_sha256="b" * 64,
    )

    def receipt(stage="sent", outcome="succeeded", **updates):
        return schemas.ReceiptOriginal(
            **{
                "schema_version": "pdos-external-receipt-v1",
                "handoff": handoff,
                "intent": intent,
                "destination": payload.destination,
                "external_id": payload.external_id,
                "manifest_sha256": plan.manifest_sha256,
                "release_scope": payload.release_scope,
                "stage": stage,
                "outcome": outcome,
                "external_receipt_id": f"remote-{stage}-{uuid4()}",
                "occurred_at": AT - timedelta(seconds=1),
                **updates,
            }
        )

    def fact(original, **updates):
        return schemas.ReceiptFact(
            **{
                "id": uuid4(),
                "revision": 1,
                "original": original,
                "source": source,
                "issuer": issuer,
                "received_at": AT,
                **updates,
            }
        )

    def reading(*facts):
        return rules.fold(handoff=handoff, intent=intent, authorization=plan, receipts=facts)

    return SimpleNamespace(**locals())


def test_exact_two_approvals_manifest_and_mapping_make_candidate_not_delivery(case):
    assert case.plan.state == "READY"
    assert rules.require_authorizable(case.plan) is case.plan
    assert case.plan.signers == (case.base.ctx.actor_id,)
    assert case.plan.network_send is False
    assert case.plan.external_received is case.plan.external_effective is False
    assert all(value.plan.external_received is False for value in case.data.decisions)
    assert case.plan.manifest_sha256 == rules.manifest_digest(case.payload.manifest)


@pytest.mark.parametrize(
    "fault",
    [
        "package_current",
        "sources_current",
        "contract",
        "requirements",
        "missing_decision",
        "stale_decision",
        "expired",
        "narrow_approval",
        "null_widen",
    ],
)
def test_unknown_actual_material_or_approval_scope_does_not_authorize(case, fault):
    data, payload = case.data, case.payload
    if fault in {"package_current", "sources_current"}:
        data = data.model_copy(update={fault: None})
    elif fault == "contract":
        data = data.model_copy(update={"contract_read": None})
    elif fault == "requirements":
        data = data.model_copy(update={"required_manifest_refs": None})
    elif fault == "missing_decision":
        data = data.model_copy(update={"decisions": data.decisions[:1]})
    elif fault == "null_widen":
        payload = payload.model_copy(
            update={
                "release_scope": payload.release_scope.model_copy(
                    update={"quantity": None, "unit": None}
                )
            }
        )
    else:
        decision = data.decisions[0]
        plan = decision.plan
        if fault == "stale_decision":
            decision = decision.model_copy(update={"current": False})
        elif fault == "expired":
            decision = decision.model_copy(update={"plan": plan.model_copy(update={"expiry": AT})})
        else:
            decision = decision.model_copy(
                update={
                    "plan": plan.model_copy(
                        update={
                            "release_scope": plan.release_scope.model_copy(update={"quantity": 1})
                        }
                    )
                }
            )
        data = data.model_copy(update={"decisions": (decision, data.decisions[1])})
    result = rules.prepare(payload, data, ctx=case.base.ctx, at=AT)
    assert result.state == "UNKNOWN"
    with pytest.raises(DomainError):
        rules.require_authorizable(result)


def test_no_universal_all_mapping_or_manifest_rule_and_no_ttl(case):
    payload = case.payload.model_copy(update={"mappings": (), "manifest": ()})
    data = case.data.model_copy(
        update={
            "mappings": (),
            "files": (),
            "required_mapping_refs": (),
            "required_manifest_refs": (),
        }
    )
    result = rules.prepare(payload, data, ctx=case.base.ctx, at=AT)
    assert result.state == "READY"
    assert all(value.plan.expiry is None for value in data.decisions)
    missing = rules.prepare(
        payload, data.model_copy(update={"required_manifest_refs": None}), ctx=case.base.ctx, at=AT
    )
    assert missing.state == "UNKNOWN"


def test_equal_explicit_empty_scope_is_empty_and_does_not_cover_selected_objects(case):
    empty = case.payload.release_scope.model_copy(update={"lots": (), "lines": ()})
    assert rules.scope_covers(empty, empty) is True
    assert rules.scope_covers(empty, case.payload.release_scope) is False


@pytest.mark.parametrize("fault", ["manifest", "mapping"])
def test_content_hash_and_number_version_must_match_actual_material(case, fault):
    update = (
        {"manifest": (case.file.model_copy(update={"content_sha256": "f" * 64}),)}
        if fault == "manifest"
        else {"mappings": (case.mapping.model_copy(update={"external_version": "unread-version"}),)}
    )
    result = rules.prepare(
        case.payload.model_copy(update=update), case.data, ctx=case.base.ctx, at=AT
    )
    assert result.state == "BLOCKED" and result.blocked


def test_typed_refs_do_not_scan_free_uuid_text_and_named_scope_cannot_be_borrowed(case):
    with pytest.raises(ValidationError):
        schemas.MappingRef.model_validate({"kind": "free_text", "id": uuid4(), "revision": 1})
    with pytest.raises(ValidationError):
        schemas.AuthorizePayload.model_validate(
            {**case.payload.model_dump(), "sender_authorized": True}
        )
    with pytest.raises(DomainError) as caught:
        rules.prepare(
            case.payload,
            case.data,
            ctx=Context(
                case.base.scope.tenant_id,
                uuid4(),
                case.base.ctx.requester_id,
                category_id=case.base.ctx.category_id,
            ),
            at=AT,
        )
    assert caught.value.code == "FORBIDDEN_SCOPE"


def test_each_stage_is_independent_and_absence_never_becomes_success(case):
    empty = case.reading()
    assert empty.status == "authorized"
    assert empty.sent.state == empty.accepted.state == empty.effective.state == "not_recorded"
    sent = case.fact(case.receipt())
    accepted = case.fact(case.receipt("accepted"))
    effective = case.fact(case.receipt("effective"))
    assert case.reading(sent).status == "sent"
    assert case.reading(sent).effective.state == "not_recorded"
    received = case.reading(accepted)
    assert received.status == "acknowledged" and received.sent.state == "not_recorded"
    final = case.reading(effective)
    assert final.status == "reconciled" and final.accepted.state == "not_recorded"
    assert final.network_send is False


def test_partial_receipt_scope_never_becomes_full_effectivity_or_summed_quantity(case):
    scope = case.payload.release_scope.model_copy(update={"quantity": 6})
    first = case.fact(case.receipt("effective", release_scope=scope))
    second = case.fact(
        case.receipt("effective", release_scope=scope), received_at=AT + timedelta(seconds=1)
    )
    result = case.reading(first, second)
    assert result.effective.state == "partial"
    assert result.effective.covered_scopes == (scope, scope)
    assert result.status == "authorized"


def test_unknown_sent_requires_explicit_same_occurrence_reconciliation(case):
    old = case.fact(case.receipt(outcome="unknown"))
    assert case.reading(old).delivery_unknown is True
    with pytest.raises(DomainError) as caught:
        case.reading(old, case.fact(case.receipt()))
    assert caught.value.code == "EXTERNAL_OUTCOME_UNKNOWN"
    solved = case.fact(
        case.receipt(reconciles=VersionRef(id=old.id, revision=old.revision)),
        received_at=AT + timedelta(seconds=1),
    )
    final = case.reading(old, solved)
    assert final.sent.state == "succeeded" and not final.delivery_unknown
    assert final.history == (old, solved)
    assert final.history[0].original.outcome == "unknown"


@pytest.mark.parametrize(
    "fault", ["stage", "manifest_sha256", "external_id", "release_scope", "destination"]
)
def test_reconciliation_cannot_change_intent_envelope_or_stage(case, fault):
    old = case.fact(case.receipt(outcome="unknown"))
    update = (
        {"stage": "accepted"}
        if fault == "stage"
        else {"manifest_sha256": "f" * 64}
        if fault == "manifest_sha256"
        else {"external_id": "different-external-object"}
        if fault == "external_id"
        else {"release_scope": case.payload.release_scope.model_copy(update={"regions": ("US",)})}
        if fault == "release_scope"
        else {
            "destination": schemas.Destination(
                system="another-system", recipient_id="another-recipient"
            )
        }
    )
    original = case.receipt(reconciles=VersionRef(id=old.id, revision=old.revision), **update)
    with pytest.raises(DomainError):
        case.reading(old, case.fact(original, received_at=AT + timedelta(seconds=1)))


@pytest.mark.parametrize("outcome", ["unknown", "rejected", "failed"])
def test_non_success_is_kept_separately_and_never_fills_effective(case, outcome):
    fact = case.fact(case.receipt("accepted", outcome))
    result = case.reading(fact)
    assert result.accepted.state == outcome
    assert result.effective.state == "not_recorded"
    assert result.rejected is (outcome == "rejected")
    assert result.failed is (outcome == "failed")
    assert result.history == (fact,)


def test_trusted_receipt_candidate_keeps_mismatch_record_as_conflict(case):
    original = case.receipt("accepted", manifest_sha256="f" * 64, external_id="remote-wrong-number")
    payload = schemas.ReceiptRecordPayload(
        handoff=case.handoff,
        intent=case.intent,
        source=case.source,
        reason="按实际原件登记不一致响应",
    )
    data = schemas.ReceiptActualData(
        scope=case.data.scope,
        category_id=case.data.category_id,
        handoff=case.handoff,
        intent=case.intent,
        authorization=case.plan,
        authorized=True,
        source=case.source,
        original=original,
        issuer=case.issuer,
        issuer_current=True,
        sources_current=True,
        sources=case.data.sources,
        required_source_read_set=case.data.required_source_read_set,
    )
    before = deepcopy(original.model_dump())
    plan = rules.prepare_receipt(payload, data, at=AT)
    assert rules.require_recordable(plan) is plan
    assert set(plan.mismatches) == {"MANIFEST_MISMATCH", "EXTERNAL_ID_MISMATCH"}
    result = case.reading(case.fact(original))
    assert result.accepted.state == "conflict" and result.conflict
    assert result.effective.state == "not_recorded"
    assert result.history[0].original.model_dump() == before
    unverified = rules.prepare_receipt(
        payload, data.model_copy(update={"issuer": None, "issuer_current": None}), at=AT
    )
    assert unverified.state == "UNKNOWN"
    with pytest.raises(DomainError):
        rules.require_recordable(unverified)


def test_receipt_verified_original_subclass_matches_only_exact_source_fields(case):
    payload = schemas.ReceiptRecordPayload(
        handoff=case.handoff,
        intent=case.intent,
        source=case.source,
        reason="登记已由实际原件owner核验的同一引用",
    )
    data = schemas.ReceiptActualData(
        scope=case.data.scope,
        category_id=case.data.category_id,
        handoff=case.handoff,
        intent=case.intent,
        authorization=case.plan,
        authorized=True,
        source=case.source,
        original=case.receipt(),
        issuer=case.issuer,
        issuer_current=True,
        sources_current=True,
        sources=(case.source,),
        required_source_read_set=case.data.required_source_read_set,
    )
    assert type(data.sources[0]) is schemas.OriginalRef
    plan = rules.prepare_receipt(payload, data, at=AT)
    assert plan.state == "READY" and not plan.unknown
    assert all(type(value) is SourceRef for value in plan.sources)
    base_source = SourceRef.model_validate(case.source.model_dump(mode="json"))
    assert (
        rules.prepare_receipt(payload, data.model_copy(update={"sources": (base_source,)}), at=AT)
        == plan
    )

    for change in ({"position": "quote:sha256:" + "f" * 64}, {"revision": 2}):
        changed_source = schemas.OriginalRef.model_validate(
            {**case.source.model_dump(mode="json"), **change}
        )
        changed = rules.prepare_receipt(
            payload, data.model_copy(update={"sources": (changed_source,)}), at=AT
        )
        assert changed.state == "UNKNOWN"
        assert "RECEIPT_ORIGINAL_NOT_VERIFIED" in changed.unknown
