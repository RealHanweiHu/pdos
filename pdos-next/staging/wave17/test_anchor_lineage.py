"""Explicit synthetic pure inputs; no DB/HTTP/source read or real qualification.

The host attestation fixtures below only exercise structural verification. They
are not real approvals, measurements, Receipt groups or production evidence.
"""

from copy import deepcopy
from datetime import timedelta

import pytest
from pdos_next.domain.capa_effectiveness.anchor import (
    CurrentAuthorizationClosure,
    IssueVersionEvidence,
    OriginalFailureProof,
    SourceRead,
    SourceSafety,
    StableCapaAnchor,
    VersionRef,
    build_anchor,
    canonical_reads,
    canonical_sources,
    json_value,
    stable_failure_material,
)
from pdos_next.domain.capa_effectiveness.lineage import (
    CLOSE,
    EFFECT,
    AuditEvidence,
    ConsumedApproval,
    OutboxEvidence,
    ReceiptEvidence,
    SourceDelta,
    TransitionHostProof,
    _check_step,
    consumption_group_material,
    transition_delta_material,
    validate_lineage,
    verify_from_host,
)
from pdos_next.domain.quality_execution.ports import FixedQualityResult
from pdos_next.domain.quality_issues.ports import (
    Authority,
    QualityPolicy,
    VerificationEvidence,
    VerifiedRun,
)
from pdos_next.domain.quality_issues.rules import digest, failure_ref, semantic_digest
from pdos_next.errors import DomainError
from pdos_next.schemas.quality_issues.contracts import (
    Capa,
    CapaAction,
    Containment,
    EffectivenessDecide,
    EffectivenessRequirement,
    History,
    Hypothesis,
    Issue,
    IssueClose,
    NamedConclusion,
    Ref,
)
from pdos_next.schemas.verification.contracts import EventTime
from pydantic import ValidationError
from quality_issues.helpers import NOW, fixed_run, source, uid

PURPOSE = "Synthetic shared investigation; not production qualification"
ACTOR = uid("independent-reviewer")
CATEGORY = uid("category")
AT = NOW + timedelta(hours=1)


def safety(ref):
    return SourceSafety(
        id=ref.id,
        revision=ref.revision,
        hash=digest(str(ref.id)),
        status="active",
        owner_id=uid("owner"),
        visibility="category",
        source_kind="registered_native_text",
        registration={
            "receipt_id": uid(str(ref.id) + "-receipt"),
            "actor_id": uid("owner"),
            "requester_id": uid("owner"),
            "run_id": None,
        },
    )


def origin_fixture():
    run = fixed_run(revision=4)
    failure = failure_ref(VerifiedRun(run=run, nature="synthetic"), run.measurements[0].id)
    root = source("root")
    complete = source("action-complete")
    issue = Issue(
        id=uid("issue"),
        revision=9,
        scope=run.scope,
        audience=(f"category:{CATEGORY}",),
        title="Synthetic actual fixed failure",
        status="awaiting_verification",
        risk="high",
        failures=(failure,),
        root_cause=NamedConclusion(
            text="Named original cause",
            actor_id=uid("owner"),
            sources=(root,),
            at=NOW - timedelta(minutes=90),
        ),
        capa=Capa(
            id=uid("capa"),
            hypotheses=(Hypothesis(text="Original hypothesis", sources=(root,)),),
            actions=(
                CapaAction(
                    id=uid("action"),
                    kind="corrective",
                    text="Original complete action",
                    executor_id=uid("owner"),
                    completion=Containment(
                        id=uid("action"),
                        text="Actual completion",
                        executor_id=uid("owner"),
                        evidence=(complete,),
                        at=EventTime(occurred_at=NOW, original_timezone="UTC", source=complete),
                    ),
                ),
            ),
            requirement=EffectivenessRequirement(
                method="New independent fixed Run and actual observation",
                acceptance="All exact pairs pass",
                observation_until=NOW + timedelta(minutes=10),
                required_failure_ids=(failure.identity,),
            ),
        ),
        history=(
            History(
                command_id=uid("root-command"),
                operation="quality.issue.root_cause.decide",
                actor_id=uid("owner"),
                actor_kind="human",
                at=NOW - timedelta(minutes=90),
                note="Original cause",
            ),
            History(
                command_id=uid("complete-command"),
                operation="quality.capa.actions.complete",
                actor_id=uid("owner"),
                actor_kind="human",
                at=NOW,
                note="Original completion",
            ),
        ),
    )
    sources = canonical_sources((failure.source, failure.method, failure.criterion, root, complete))
    reads = canonical_reads(
        SourceRead(artifact_id=s.id, expected_revision=s.revision) for s in sources
    )
    basis = tuple(safety(s) for s in sources)
    row = IssueVersionEvidence(
        ref=VersionRef(id=uid("issue-v9"), revision=9, snapshot_sha256=digest(json_value(issue))),
        previous_ref=None,
        scope=issue.scope,
        category_id=CATEGORY,
        issue_id=issue.id,
        purpose=PURPOSE,
        owner_id=uid("owner"),
        writer_id=uid("owner"),
        visibility="category",
        nature="synthetic",
        operation="quality.capa.actions.complete",
        domain_intent_sha256=digest("original-domain-intent"),
        created_at=NOW,
        issue=issue,
        sources=sources,
        required_source_read_set=reads,
        source_basis=basis,
        input_snapshot={"complete": "retained full original payload"},
        authority_snapshot={"original_writer": str(uid("owner"))},
        policy_snapshot={"original_policy": "retained"},
        persisted_source_basis={
            "artifact_sources": [json_value(s) for s in basis],
            "original_shared_proof": str(uid("complete-proof")),
        },
    )
    result = FixedQualityResult(
        scope=run.scope,
        purpose=PURPOSE,
        event_id=None,
        run_version_id=uid("fixed-run-v4"),
        run_revision=run.revision,
        measurement_id=failure.measurement_id,
        projection_id=uid("fixed-projection"),
        projection_revision=1,
        basis_sha256=digest("fixed-results-basis"),
        rules_version="fixed-original-rules",
        rules_sha256=digest("fixed-rules"),
        verified=VerifiedRun(run=run, nature="synthetic"),
        visibility="category",
        owner_id=uid("tester"),
        sources=sources,
        required_source_read_set=reads,
        current=True,
        source_basis={
            "evidence": [json_value(s) for s in basis],
            "original_bytes_sha256": digest("actual synthetic original bytes"),
            "runtime_stamp": digest("initial-host-runtime"),
        },
        retained={
            "current": True,
            "original_start_intent": digest("fixed-start"),
            "original_start_version_id": str(uid("start-v2")),
            "original_start_revision": 2,
            "saved_start_at": run.actual_start.received_at.isoformat(),
            "actual_start": json_value(run.actual_start),
            "plan_binding": {"complete_plan": "immutable", "checked_at": "FIXED nested data"},
            "reservation": {"id": str(uid("reservation")), "epoch": 2},
            "occupancy": [{"asset_id": str(uid("equipment")), "epoch": 4}],
            "sample_usage": [{"sample_id": str(run.samples[0].id), "epoch": 2}],
            "facts_revision": digest("all resource facts"),
            "source_basis": {"epoch": 7},
            "source_nature": "synthetic",
            "checked_at": NOW.isoformat(),
            "execution_window_elapsed": False,
        },
    )
    proof = OriginalFailureProof(failure=failure, result=result)
    return build_anchor(row, (proof,), source_basis=basis)


def closure_for(anchor, row=None, *, actor=ACTOR, checked_at=AT):
    row = row or anchor.origin
    return CurrentAuthorizationClosure(
        scope=row.scope,
        purpose=row.purpose,
        audience=row.issue.audience,
        authority=Authority(
            scope=row.scope,
            actor_id=actor,
            actor_kind="human",
            roles=("quality",),
            audience=row.issue.audience,
            authorized=True,
            qualified=True,
            cancelled=False,
            now=checked_at,
        ),
        sources=canonical_sources((*anchor.origin_sources, *row.sources)),
        required_source_read_set=canonical_reads(
            (*anchor.origin_required_source_read_set, *row.required_source_read_set)
        ),
        source_basis=row.source_basis,
        professional_proof={"exact_epoch": 1},
        policy_proof={"exact_epoch": 2},
        source_acl_proof={
            "principal": str(actor),
            "grant_epoch": 3,
            "expires_at": (NOW + timedelta(hours=3)).isoformat(),
        },
        runtime_proof={"current_host_stamp": digest("fresh-runtime")},
        checked_at=checked_at,
        valid_until=NOW + timedelta(hours=3),
    )


def make_step(
    anchor, before, *, operation=EFFECT, result="effective", evidence_result="pass", clock=None
):
    clock = clock or NOW + timedelta(minutes=30 if operation == EFFECT else 40)
    verification_source = source("new-verification")
    policy_source = source("new-rule")
    policy = QualityPolicy(
        ref=Ref(id=uid("published-policy"), revision=2), risk="high", independent_verification=True
    )
    evidence = VerificationEvidence(
        id=uid("new-reviewed-evidence"),
        sources=(verification_source,),
        failure_ids=before.issue.capa.requirement.required_failure_ids,
        run_ids=(uid("new-actual-run"),),
        verifier_id=ACTOR,
        executor_ids=(uid("new-tester"),),
        result=evidence_result,
        requirement_digest=semantic_digest(before.issue.capa.requirement),
        observed_from=NOW + timedelta(minutes=1),
        observed_until=NOW + timedelta(minutes=10),
        applicable=True,
        current=True,
        nature="synthetic",
    )
    payload = (
        EffectivenessDecide(
            result=result, text="Exact named independent decision", evidence_ids=(evidence.id,)
        )
        if operation == EFFECT
        else IssueClose(text="Exact separate named close")
    )
    authority = Authority(
        scope=before.scope,
        actor_id=ACTOR,
        actor_kind="human",
        roles=("quality",),
        audience=before.issue.audience,
        authorized=True,
        qualified=True,
        cancelled=False,
        now=clock,
    )
    read_digest = digest(
        {
            "failures": [json_value(f) for f in before.issue.failures],
            "capa": before.issue.capa.model_dump(
                mode="json", exclude={"effectiveness", "effectiveness_history"}
            ),
            "root": json_value(before.issue.root_cause),
            "containment": [],
            "policy": json_value(policy),
            "evidence": [json_value(evidence)],
        }
    )
    command_id = uid(operation + "-command")
    next_issue = json_value(before.issue)
    next_issue["revision"] += 1
    next_issue["history"].append(
        json_value(
            History(
                command_id=command_id,
                operation=operation,
                actor_id=ACTOR,
                actor_kind="human",
                at=clock,
                note=payload.text,
            )
        )
    )
    if operation == EFFECT:
        decision = {
            "text": payload.text,
            "actor_id": str(ACTOR),
            "sources": [json_value(verification_source)],
            "at": clock.isoformat().replace("+00:00", "Z"),
            "result": result,
            "evidence_ids": [str(evidence.id)],
            "policy": json_value(policy.ref),
            "read_digest": read_digest,
        }
        next_issue["capa"]["effectiveness"] = decision
        next_issue["capa"]["effectiveness_history"].append(deepcopy(decision))
    else:
        next_issue["status"] = "closed"
        next_issue["closure"] = {
            "text": payload.text,
            "actor_id": str(ACTOR),
            "sources": [json_value(verification_source)],
            "at": clock.isoformat().replace("+00:00", "Z"),
        }
    next_issue = Issue.model_validate(next_issue)
    sources = canonical_sources((*before.sources, verification_source, policy_source))
    added_reads = canonical_reads(
        SourceRead(artifact_id=s.id, expected_revision=s.revision)
        for s in (verification_source, policy_source)
    )
    reads = canonical_reads((*before.required_source_read_set, *added_reads))
    safety_map = {
        s.id: s for s in (*before.source_basis, safety(verification_source), safety(policy_source))
    }
    basis = tuple(safety_map[r.artifact_id] for r in reads)
    professional = {
        "scope": json_value(before.scope),
        "subject_id": str(ACTOR),
        "operation": operation,
        "purpose": PURPOSE,
        "authorized": True,
        "qualified": True,
        "roles": ["quality"],
        "facts_revision": digest("exact-authority"),
        "all_issuer_epochs": {"issuer": 2},
    }
    proof_id = uid(operation + "-t2-proof")
    after = IssueVersionEvidence.model_validate(
        {
            **json_value(before),
            "ref": {
                "id": str(uid(operation + "-version")),
                "revision": next_issue.revision,
                "snapshot_sha256": digest(json_value(next_issue)),
            },
            "previous_ref": json_value(before.ref),
            "operation": operation,
            "writer_id": str(ACTOR),
            "domain_intent_sha256": digest(operation + "-DOMAIN"),
            "created_at": (clock + timedelta(seconds=1)).isoformat(),
            "issue": json_value(next_issue),
            "sources": [json_value(s) for s in sources],
            "required_source_read_set": [json_value(r) for r in reads],
            "source_basis": [json_value(s) for s in basis],
            "input_snapshot": {"payload": json_value(payload)},
            "authority_snapshot": professional,
            "policy_snapshot": json_value(policy),
            "persisted_source_basis": {
                "artifact_sources": [json_value(s) for s in basis],
                "shared_proof": {"id": str(proof_id), "tier": "T2"},
            },
        }
    )
    common_intent = digest(operation + "-COMMON-DIFFERENT-FORMAT")
    receipt = ReceiptEvidence(
        id=uid(operation + "-receipt"),
        tenant_id=before.scope.tenant_id,
        product_id=before.scope.product_id,
        command_id=command_id,
        actor_id=ACTOR,
        requester_id=ACTOR,
        operation=operation,
        subject_type="quality_issue",
        subject_id=after.ref.id,
        subject_revision=after.ref.revision,
        visibility=after.visibility,
        request_digest=digest("full common command"),
        intent_digest=common_intent,
        run_id=None,
        result={
            "id": str(after.ref.id),
            "issue_id": str(after.issue_id),
            "revision": after.ref.revision,
            "status": after.issue.status,
        },
        created_at=clock + timedelta(seconds=2),
    )
    proof = TransitionHostProof(
        before_ref=before.ref,
        after_ref=after.ref,
        operation=operation,
        command_id=command_id,
        writer_id=ACTOR,
        payload=payload,
        payload_sha256=semantic_digest(payload),
        domain_intent_sha256=after.domain_intent_sha256,
        common_intent_sha256=common_intent,
        authority=authority,
        professional_snapshot=professional,
        signer_recheck={
            "current": True,
            "reason_codes": [],
            "scope": json_value(before.scope),
            "subject_id": str(ACTOR),
            "operation": operation,
            "purpose": PURPOSE,
            "original_snapshot_sha256": digest(professional),
            "assessment": professional,
        },
        policy=policy,
        policy_snapshot=json_value(policy),
        verification=(evidence,),
        source_delta=SourceDelta(
            verification=(verification_source,),
            policy=(policy_source,),
            professional=(),
            approval=(),
            required_source_read_set=added_reads,
        ),
        approval=ConsumedApproval(
            id=proof_id,
            tier="T2",
            tenant_id=before.scope.tenant_id,
            product_id=before.scope.product_id,
            actor_id=ACTOR,
            subject_id=before.scope.product_id,
            operation=operation,
            product_revision=7,
            consumed=True,
            evaluated_at=clock,
            expires_at=clock + timedelta(minutes=10),
            material_sha256=digest("actual common review with server_on_save"),
            read_set_sha256=digest([json_value(r) for r in reads]),
            approved_delta_sha256="0" * 64,
            transaction_proof_id=proof_id,
            transaction_proof_sha256=digest("actual host group"),
        ),
        receipt=receipt,
        audit=AuditEvidence(
            id=uid(operation + "-audit"),
            tenant_id=receipt.tenant_id,
            receipt_id=receipt.id,
            actor_id=ACTOR,
            operation=operation,
        ),
        outbox=OutboxEvidence(
            id=uid(operation + "-outbox"),
            tenant_id=receipt.tenant_id,
            receipt_id=receipt.id,
            type="capa.effectiveness_decided" if operation == EFFECT else "issue.closed",
            subject_id=after.ref.id,
            subject_revision=after.ref.revision,
            schema_version=1,
            actor_id=ACTOR,
            correlation_id=command_id,
        ),
        proof_sha256="0" * 64,
    )
    proof = proof.model_copy(
        update={
            "approval": proof.approval.model_copy(
                update={
                    "approved_delta_sha256": digest(transition_delta_material(before, after, proof))
                }
            )
        }
    )
    proof = proof.model_copy(
        update={
            "approval": proof.approval.model_copy(
                update={
                    "transaction_proof_sha256": digest(consumption_group_material(after, proof))
                }
            )
        }
    )
    return after, reseal(proof)


def reseal(proof):
    raw = json_value(proof)
    raw.pop("proof_sha256")
    return proof.model_copy(update={"proof_sha256": digest(raw)})


def reseal_approval(after, proof, **changes):
    approval = ConsumedApproval.model_validate(
        json_value(proof.approval.model_copy(update=changes))
    )
    proof = proof.model_copy(update={"approval": approval})
    proof = proof.model_copy(
        update={
            "approval": approval.model_copy(
                update={
                    "transaction_proof_sha256": digest(consumption_group_material(after, proof))
                }
            )
        }
    )
    return reseal(proof)


def chain():
    anchor = origin_fixture()
    effect, first = make_step(anchor, anchor.origin)
    close, second = make_step(anchor, effect, operation=CLOSE)
    return anchor, (anchor.origin, effect, close), (first, second), closure_for(anchor, close)


def test_complete_origin_is_not_hardcoded_v6_and_finite_two_t2_chain_preserves_anchor():
    anchor, versions, steps, closure = chain()
    result = validate_lineage(anchor, versions, steps, closure, at=AT)
    assert [v.ref.revision for v in versions] == [9, 10, 11]
    assert result.current_ref == versions[-1].ref and result.structural_validation_only is True
    assert result.anchor_sha256 == anchor.anchor_sha256
    assert steps[0].domain_intent_sha256 != steps[0].common_intent_sha256
    assert steps[0].approval.id != steps[1].approval.id
    assert set(anchor.origin_sources) < set(closure.sources)


def test_effect_and_close_accept_consumed_t2_without_a_separate_expiry():
    anchor, versions, steps, closure = chain()
    unbounded = tuple(
        reseal_approval(after, step, expires_at=None)
        for after, step in zip(versions[1:], steps, strict=True)
    )
    assert all(json_value(step)["approval"]["expires_at"] is None for step in unbounded)
    result = validate_lineage(anchor, versions, unbounded, closure, at=AT)
    assert result.current_ref == versions[-1].ref
    assert result.anchor_sha256 == anchor.anchor_sha256


@pytest.mark.parametrize("offset", [-1, 0])
def test_real_approval_expiry_is_enforced_at_the_named_decision(offset):
    anchor, versions, steps, closure = chain()
    step = reseal_approval(
        versions[1],
        steps[0],
        expires_at=steps[0].authority.now + timedelta(microseconds=offset),
    )
    with pytest.raises(DomainError, match="real approval is valid"):
        validate_lineage(anchor, versions[:2], (step,), closure, at=AT)


def test_unbounded_approval_still_binds_the_actual_named_decision_time():
    anchor, versions, steps, closure = chain()
    step = reseal_approval(
        versions[1],
        steps[0],
        expires_at=None,
        evaluated_at=steps[0].authority.now + timedelta(microseconds=1),
    )
    with pytest.raises(DomainError, match="real approval is valid"):
        validate_lineage(anchor, versions[:2], (step,), closure, at=AT)


@pytest.mark.parametrize("bad", ["scope", "actor", "unconsumed", "signer", "source"])
def test_unbounded_approval_preserves_binding_and_current_material_checks(bad):
    anchor, versions, steps, closure = chain()
    changes = {"expires_at": None}
    if bad == "scope":
        changes["product_id"] = uid("another-product")
    elif bad == "actor":
        changes["actor_id"] = uid("another-signer")
    elif bad == "unconsumed":
        changes["consumed"] = False
    step = reseal_approval(versions[1], steps[0], **changes)
    if bad == "signer":
        step = reseal(
            step.model_copy(update={"signer_recheck": {**step.signer_recheck, "current": False}})
        )
    elif bad == "source":
        raw = json_value(closure)
        raw["source_basis"][0]["hash"] = digest("source withdrawn and restored")
        closure = CurrentAuthorizationClosure.model_validate(raw)
    with pytest.raises(DomainError):
        validate_lineage(anchor, versions[:2], (step,), closure, at=AT)


@pytest.mark.parametrize(
    "path",
    [
        "root",
        "action",
        "requirement",
        "raw",
        "original_epoch",
        "occupancy",
        "usage",
        "nested_clock",
    ],
)
def test_full_original_material_digests_preserve_every_fixed_field(path):
    anchor = origin_fixture()
    if path in {"root", "action", "requirement"}:
        row = json_value(anchor.origin)
        target = row["issue"]
        if path == "root":
            target["root_cause"]["text"] += " changed"
        elif path == "action":
            target["capa"]["actions"][0]["text"] += " changed"
        else:
            target["capa"]["requirement"]["acceptance"] += " changed"
        row["ref"]["snapshot_sha256"] = digest(target)
        changed = build_anchor(row, anchor.failures, source_basis=anchor.origin_source_basis)
        assert changed.material_sha256 != anchor.material_sha256
    else:
        proof = json_value(anchor.failures[0])
        if path == "raw":
            proof["result"]["verified"]["run"]["measurements"][0]["raw_value"] = "12"
        elif path == "original_epoch":
            proof["result"]["retained"]["source_basis"]["epoch"] += 1
        elif path == "occupancy":
            proof["result"]["retained"]["occupancy"][0]["epoch"] += 1
        elif path == "usage":
            proof["result"]["retained"]["sample_usage"][0]["epoch"] += 1
        else:
            proof["result"]["retained"]["plan_binding"]["checked_at"] = "changed fixed nested data"
        assert digest(stable_failure_material(proof)) != digest(
            stable_failure_material(anchor.failures[0])
        )


def test_only_three_exact_dynamic_paths_excluded_full_origin_proof_stays_unchanged():
    anchor = origin_fixture()
    proof = json_value(anchor.failures[0])
    proof["result"]["retained"]["checked_at"] = AT.isoformat()
    proof["result"]["retained"]["execution_window_elapsed"] = True
    proof["result"]["source_basis"]["runtime_stamp"] = digest("later host runtime")
    changed = build_anchor(anchor.origin, (proof,), source_basis=anchor.origin_source_basis)
    assert changed.stable_failure_material_sha256 == anchor.stable_failure_material_sha256
    assert changed.full_failure_proofs_sha256 != anchor.full_failure_proofs_sha256
    assert changed.anchor_sha256 != anchor.anchor_sha256
    assert anchor.failures[0].result.retained["execution_window_elapsed"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        "root",
        "action",
        "failure",
        "history_prefix",
        "extra_history",
        "risk",
        "owner",
        "purpose",
        "previous",
        "source_epoch",
    ],
)
def test_exact_successor_delta_rejects_hidden_material_and_history_changes(mutation):
    anchor, versions, steps, closure = chain()
    raw = json_value(versions[1])
    if mutation == "root":
        raw["issue"]["root_cause"]["text"] += " drift"
    elif mutation == "action":
        raw["issue"]["capa"]["actions"][0]["completion"]["text"] += " drift"
    elif mutation == "failure":
        raw["issue"]["failures"][0]["sample"]["actual_configuration"]["revision"] += 1
    elif mutation == "history_prefix":
        raw["issue"]["history"][0]["note"] += " overwritten"
    elif mutation == "extra_history":
        raw["issue"]["history"].append(deepcopy(raw["issue"]["history"][-1]))
    elif mutation == "risk":
        raw["issue"]["risk"] = "low"
    elif mutation == "owner":
        raw["owner_id"] = str(uid("other-owner"))
    elif mutation == "purpose":
        raw["purpose"] += " drift"
    elif mutation == "previous":
        raw["previous_ref"]["id"] = str(uid("skipped-predecessor"))
    else:
        raw["source_basis"][0]["hash"] = digest("source ABA")
        raw["persisted_source_basis"]["artifact_sources"][0]["hash"] = raw["source_basis"][0][
            "hash"
        ]
    raw["ref"]["snapshot_sha256"] = digest(raw["issue"])
    # Even a maliciously recomputed outer digest does not authorize material drift.
    changed = IssueVersionEvidence.model_validate(raw)
    step = steps[0].model_copy(update={"after_ref": changed.ref})
    step = step.model_copy(
        update={
            "approval": step.approval.model_copy(
                update={
                    "approved_delta_sha256": digest(
                        transition_delta_material(anchor.origin, changed, step)
                    )
                }
            )
        }
    )
    step = step.model_copy(
        update={
            "approval": step.approval.model_copy(
                update={
                    "transaction_proof_sha256": digest(consumption_group_material(changed, step))
                }
            )
        }
    )
    with pytest.raises((DomainError, ValidationError)):
        validate_lineage(anchor, (anchor.origin, changed), (reseal(step),), closure, at=AT)


@pytest.mark.parametrize(
    "bad",
    [
        "receipt_subject",
        "receipt_string_revision",
        "receipt_writer",
        "audit",
        "event",
        "unconsumed",
        "product_subject",
        "common_intent",
        "payload",
        "shared_uuid",
    ],
)
def test_approval_receipt_audit_event_exact_binding_not_just_reference_presence(bad):
    anchor, versions, steps, closure = chain()
    proof = json_value(steps[0])
    if bad == "receipt_subject":
        proof["receipt"]["subject_id"] = str(anchor.origin.issue_id)
    elif bad == "receipt_string_revision":
        proof["receipt"]["result"]["revision"] = "10"
    elif bad == "receipt_writer":
        proof["receipt"]["requester_id"] = str(anchor.origin.owner_id)
    elif bad == "audit":
        proof["audit"]["receipt_id"] = str(uid("another-receipt"))
    elif bad == "event":
        proof["outbox"]["correlation_id"] = str(uid("another-command"))
    elif bad == "unconsumed":
        proof["approval"]["consumed"] = False
    elif bad == "product_subject":
        proof["approval"]["subject_id"] = str(anchor.origin.issue_id)
    elif bad == "common_intent":
        proof["common_intent_sha256"] = digest("wrong common intent")
    elif bad == "payload":
        proof["payload"]["text"] += " changed"
    else:
        proof["approval"]["id"] = str(uid("unrelated-T2"))
    with pytest.raises((DomainError, ValidationError)):
        validate_lineage(
            anchor,
            versions[:2],
            (reseal(TransitionHostProof.model_validate(proof)),),
            closure,
            at=AT,
        )


def test_ineffective_may_append_once_but_never_close_and_unknown_cannot_be_effective():
    anchor = origin_fixture()
    row, step = make_step(anchor, anchor.origin, result="ineffective", evidence_result="fail")
    assert validate_lineage(anchor, (anchor.origin, row), (step,), closure_for(anchor, row), at=AT)
    with pytest.raises(DomainError):
        close, next_step = make_step(anchor, row, operation=CLOSE, evidence_result="fail")
        validate_lineage(
            anchor,
            (anchor.origin, row, close),
            (step, next_step),
            closure_for(anchor, close),
            at=AT,
        )
    row, step = make_step(anchor, anchor.origin, evidence_result="indeterminate")
    with pytest.raises(DomainError, match="不确定/失败"):
        validate_lineage(anchor, (anchor.origin, row), (step,), closure_for(anchor, row), at=AT)


@pytest.mark.parametrize(
    "bad",
    [
        "missing_origin",
        "missing_new",
        "private_peer",
        "overflow",
        "expired",
        "origin_epoch",
        "duplicate_revision",
    ],
)
def test_complete_current_closure_keeps_original_and_added_sources_with_current_scope(bad):
    anchor, versions, steps, closure = chain()
    raw = json_value(closure)
    if bad in {"missing_origin", "missing_new"}:
        target = anchor.origin_sources[0] if bad == "missing_origin" else source("new-verification")
        raw["sources"] = [s for s in raw["sources"] if s["id"] != str(target.id)]
    elif bad == "private_peer":
        # Existing private facts stay unreadable even with an arbitrary peer Grant proof.
        row = json_value(anchor.origin)
        row["visibility"] = "private"
        row["issue"]["audience"] = [f"private:{anchor.origin.owner_id}"]
        row["ref"]["snapshot_sha256"] = digest(row["issue"])
        private_anchor = build_anchor(row, anchor.failures, source_basis=anchor.origin_source_basis)
        peer = closure_for(private_anchor)
        with pytest.raises(DomainError, match="Peer ProductGrant"):
            validate_lineage(private_anchor, (private_anchor.origin,), (), peer, at=AT)
        return
    elif bad == "overflow":
        raw["required_source_read_set"] += [
            {"artifact_id": str(uid(f"overflow-{i}")), "expected_revision": 1} for i in range(21)
        ]
    elif bad == "expired":
        raw["valid_until"] = AT.isoformat()
    elif bad == "origin_epoch":
        raw["source_basis"][0]["hash"] = digest("withdraw and restored")
    else:
        raw["required_source_read_set"].append(
            {**raw["required_source_read_set"][0], "expected_revision": 2}
        )
    with pytest.raises((DomainError, ValidationError)):
        validate_lineage(anchor, versions, steps, raw, at=AT)


def test_missing_host_is_503_and_mid_read_runtime_drift_refuses_proof():
    anchor, versions, steps, closure = chain()
    with pytest.raises(DomainError) as error:
        verify_from_host(None, anchor, versions[-1].ref, clock=lambda: AT)
    assert error.value.reason == "INTEGRATION_REQUIRED" and error.value.status == 503

    class Host:
        closure_calls = 0

        def read_current_ref(self, _anchor):
            return versions[-1].ref

        def read_version(self, ref):
            return next(v for v in versions if v.ref == ref)

        def read_transition(self, before, after):
            return next(p for p in steps if p.after_ref == after.ref)

        def read_original_failures(self, _anchor):
            return anchor.failures

        def read_current_closure(self, _anchor, _ref):
            self.closure_calls += 1
            if self.closure_calls == 2:
                return closure.model_copy(
                    update={"runtime_proof": {"current_host_stamp": digest("revoked issuer")}}
                )
            return closure

    with pytest.raises(DomainError) as error:
        verify_from_host(Host(), anchor, versions[-1].ref, clock=lambda: AT)
    assert error.value.code == "SOURCE_STALE"


def test_origin_only_validity_and_actor_grant_observations_do_not_change_fixed_anchor():
    anchor = origin_fixture()
    one = closure_for(anchor)
    two = one.model_copy(
        update={
            "source_acl_proof": {
                "principal": str(uid("second-qualified-reader")),
                "grant_epoch": 9,
            },
            "authority": one.authority.model_copy(
                update={"actor_id": uid("second-qualified-reader")}
            ),
        }
    )
    assert (
        validate_lineage(anchor, (anchor.origin,), (), one, at=AT).anchor_sha256
        == anchor.anchor_sha256
    )
    assert (
        validate_lineage(anchor, (anchor.origin,), (), two, at=AT).anchor_sha256
        == anchor.anchor_sha256
    )
    assert digest(json_value(one)) != digest(json_value(two))


def test_stored_anchor_hash_and_extra_fields_cannot_be_trusted_from_client():
    raw = json_value(origin_fixture())
    raw["material_sha256"] = digest("forged")
    with pytest.raises(ValidationError):
        StableCapaAnchor.model_validate(raw)
    raw = json_value(origin_fixture())
    raw["is_authorized"] = True
    with pytest.raises(ValidationError):
        StableCapaAnchor.model_validate(raw)


@pytest.mark.parametrize(
    "change", ["incomplete", "executor", "no_root", "merged", "needs_recheck", "requirement"]
)
def test_origin_requires_genuine_completed_unmerged_exact_investigation(change):
    anchor = origin_fixture()
    row = json_value(anchor.origin)
    if change == "incomplete":
        row["issue"]["capa"]["actions"][0]["completion"] = None
    elif change == "executor":
        row["issue"]["capa"]["actions"][0]["completion"]["executor_id"] = str(ACTOR)
    elif change == "no_root":
        row["issue"]["root_cause"] = None
    elif change == "merged":
        row["issue"]["merged_into"] = str(uid("merged-target"))
    elif change == "needs_recheck":
        row["issue"]["needs_recheck"] = True
    else:
        row["issue"]["capa"]["requirement"]["required_failure_ids"] = ["another-failure"]
    row["ref"]["snapshot_sha256"] = digest(row["issue"])
    with pytest.raises((DomainError, ValidationError)):
        build_anchor(row, anchor.failures, source_basis=anchor.origin_source_basis)


@pytest.mark.parametrize(
    "change", ["revoked_signer", "qualification", "ai", "same_participant", "source_nature"]
)
def test_current_signer_professional_independence_and_nature_never_come_from_source_presence(
    change,
):
    anchor, versions, steps, closure = chain()
    raw = json_value(steps[0])
    if change == "revoked_signer":
        raw["signer_recheck"]["current"] = False
    elif change == "qualification":
        raw["professional_snapshot"]["qualified"] = False
    elif change == "ai":
        raw["authority"]["actor_kind"] = "ai"
    elif change == "same_participant":
        raw["verification"][0]["executor_ids"] = [str(ACTOR)]
    else:
        raw["verification"][0]["nature"] = "real"
    with pytest.raises((DomainError, ValidationError)):
        proof = reseal(TransitionHostProof.model_validate(raw))
        validate_lineage(anchor, versions[:2], (proof,), closure, at=AT)


def test_repeat_effect_skip_predecessor_and_reused_t2_uuid_are_not_finite_lineage():
    anchor, versions, steps, closure = chain()
    with pytest.raises(DomainError):
        validate_lineage(anchor, (versions[0], versions[2]), (steps[1],), closure, at=AT)
    repeated, again = make_step(anchor, versions[1], clock=NOW + timedelta(minutes=45))
    with pytest.raises(DomainError):
        validate_lineage(
            anchor,
            (versions[0], versions[1], repeated),
            (steps[0], again),
            closure_for(anchor, repeated),
            at=AT,
        )
    duplicate = steps[1].model_copy(
        update={"approval": steps[1].approval.model_copy(update={"id": steps[0].approval.id})}
    )
    with pytest.raises(DomainError, match="distinct actual T2"):
        validate_lineage(anchor, versions, (steps[0], reseal(duplicate)), closure, at=AT)


def test_distinct_t2_receipts_with_resealed_same_command_cannot_form_effect_close_chain():
    anchor, versions, steps, _ = chain()
    shared_command = steps[0].command_id
    close_raw = json_value(versions[2])
    close_raw["issue"]["history"][-1]["command_id"] = str(shared_command)
    close_raw["ref"]["snapshot_sha256"] = digest(close_raw["issue"])
    close = IssueVersionEvidence.model_validate(close_raw)

    raw = json_value(steps[1])
    raw["command_id"] = str(shared_command)
    raw["after_ref"] = json_value(close.ref)
    raw["receipt"]["command_id"] = str(shared_command)
    raw["outbox"]["correlation_id"] = str(shared_command)
    proof = TransitionHostProof.model_validate(raw)
    proof = proof.model_copy(
        update={
            "approval": proof.approval.model_copy(
                update={
                    "approved_delta_sha256": digest(
                        transition_delta_material(versions[1], close, proof)
                    )
                }
            )
        }
    )
    proof = proof.model_copy(
        update={
            "approval": proof.approval.model_copy(
                update={
                    "transaction_proof_sha256": digest(consumption_group_material(close, proof))
                }
            )
        }
    )
    proof = reseal(proof)
    closure = closure_for(anchor, close)
    assert steps[0].approval.id != proof.approval.id
    assert steps[0].receipt.id != proof.receipt.id
    # This is a fully resealed, individually valid close, rather than a stale
    # outer hash or mismatched history/envelope accidentally rejecting it.
    _check_step(versions[1], close, proof, closure)
    with pytest.raises(DomainError, match="distinct actual commands") as error:
        validate_lineage(anchor, (*versions[:2], close), (steps[0], proof), closure, at=AT)
    assert error.value.reason == "RECHECK_REQUIRED"


def test_source_set_reordering_preserves_anchor_but_nested_issuer_data_stays_fixed():
    anchor = origin_fixture()
    reordered = build_anchor(
        anchor.origin, anchor.failures, source_basis=reversed(anchor.origin_source_basis)
    )
    assert reordered.anchor_sha256 == anchor.anchor_sha256
    raw = json_value(anchor.failures[0])
    raw["result"]["retained"]["plan_binding"]["runtime_stamp"] = "FIXED nested issuer data"
    assert digest(stable_failure_material(raw)) != digest(
        stable_failure_material(anchor.failures[0])
    )


def test_host_observation_clock_is_sampled_after_reads_and_expiry_after_final_io_blocks():
    anchor = origin_fixture()
    base = closure_for(anchor, checked_at=AT)
    current_time = [AT - timedelta(seconds=1)]

    class Host:
        def read_current_ref(self, _anchor):
            return anchor.origin.ref

        def read_version(self, ref):
            current_time[0] = AT
            return anchor.origin

        def read_transition(self, before, after):
            raise AssertionError("origin only has no transition")

        def read_original_failures(self, _anchor):
            return anchor.failures

        def read_current_closure(self, _anchor, _ref):
            return base

    assert verify_from_host(Host(), anchor, anchor.origin.ref, clock=lambda: current_time[0])

    class ExpiringHost(Host):
        calls = 0

        def read_current_closure(self, _anchor, _ref):
            self.calls += 1
            if self.calls == 2:
                current_time[0] = base.valid_until
            return base

    with pytest.raises(DomainError) as error:
        verify_from_host(ExpiringHost(), anchor, anchor.origin.ref, clock=lambda: current_time[0])
    assert error.value.code == "SOURCE_STALE"


def test_final_current_pointer_io_crossing_expiry_blocks_origin_proof():
    anchor = origin_fixture()
    closure = closure_for(anchor, checked_at=AT)
    current_time = [AT]

    class SlowFinalCurrentHost:
        pointer_reads = 0

        def read_current_ref(self, _anchor):
            self.pointer_reads += 1
            if self.pointer_reads == 2:
                # The final real pointer read is IO too; its return can cross expiry.
                current_time[0] = closure.valid_until
            return anchor.origin.ref

        def read_version(self, _ref):
            return anchor.origin

        def read_transition(self, _before, _after):
            raise AssertionError("origin only has no transition")

        def read_original_failures(self, _anchor):
            return anchor.failures

        def read_current_closure(self, _anchor, _ref):
            return closure

    with pytest.raises(DomainError) as error:
        verify_from_host(
            SlowFinalCurrentHost(), anchor, anchor.origin.ref, clock=lambda: current_time[0]
        )
    assert error.value.code == "SOURCE_STALE"
