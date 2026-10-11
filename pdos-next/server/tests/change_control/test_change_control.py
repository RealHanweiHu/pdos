from datetime import timedelta
from functools import partial

import pytest
from pydantic import ValidationError

from pdos_next.domain.change_control.handlers import ChangeControlHandler
from pdos_next.domain.change_control.ports import Ports
from pdos_next.domain.change_control.read_models import ChangeControlReader
from pdos_next.domain.change_control.rules import (
    compute_impact,
    digest,
    effectivity_status,
    replace,
)
from pdos_next.errors import DomainError
from pdos_next.schemas.change_control.contracts import (
    Hypothesis,
    ImplementationRecord,
    Ref,
    RequestCreate,
)

from .helpers import NOW, SOURCE, FakeHost, graph, plan, ref, uid


def rejected(code, function):
    with pytest.raises(DomainError) as caught:
        function()
    assert caught.value.reason == code


def approval_payload(discipline="engineering"):
    return {
        "discipline": discipline,
        "text": "named decision",
        "expires_at": NOW + timedelta(hours=12),
    }


def reading(host):
    with host.transaction() as uow:
        return ChangeControlReader(host.handler.ports).get(uow, host.subject)


def test_complete_dual_lane_explicit_impact_is_fixed_and_deterministic():
    snapshot = graph()
    first = compute_impact(snapshot, 1)
    assert first == compute_impact(snapshot, 1)
    assert first.input_digest == digest(snapshot)
    assert not first.unknown
    by_kind = {row.node.ref.kind: row for row in first.known}
    assert by_kind["test_run"].path[-1] == "sample-test_run"
    assert by_kind["manufacturing_release"].path[-1] == "pilot_run-manufacturing_release"
    assert by_kind["part"].lanes == ("engineering", "manufacturing")
    assert compute_impact(replace(snapshot, revision=2), 1).id != first.id


@pytest.mark.parametrize(
    "removed", ["part-operation", "part-bom", "operation-tooling", "build-sample"]
)
def test_missing_edges_never_turn_complete_manifests_into_no_impact(removed):
    snapshot = graph()
    assessment = compute_impact(
        replace(snapshot, edges=tuple(e for e in snapshot.edges if e.id != removed)), 1
    )
    assert assessment.unknown
    target = next(e.target for e in snapshot.edges if e.id == removed)
    assert target.identity not in {row.node.ref.identity for row in assessment.known}
    assert any("未知" in u.reason or "缺少" in u.reason for u in assessment.unknown)


@pytest.mark.parametrize(
    "facet", ["evidence_applicability", "customer_samples", "supply_inventory_wip", "training"]
)
def test_missing_facet_coverage_is_explicit_unknown(facet):
    snapshot = graph()
    assessment = compute_impact(
        replace(snapshot, coverage=tuple(c for c in snapshot.coverage if c.facet != facet)), 1
    )
    assert any(u.facet == facet for u in assessment.unknown)


def test_hypothesis_is_separate_and_cannot_supply_missing_edge():
    snapshot = graph()
    snapshot = replace(snapshot, edges=tuple(e for e in snapshot.edges if e.id != "part-operation"))
    hypothesis = Hypothesis(text="AI guesses operation impact", sources=(SOURCE,))
    assessment = compute_impact(snapshot, 1, (hypothesis,))
    assert assessment.hypotheses == (hypothesis,)
    assert ref("operation") not in {row.node.ref for row in assessment.known}
    assert assessment.unknown


@pytest.mark.parametrize(
    "bad", [{"tenant_id": str(uid("other"))}, {"approved": True}, {"actor_kind": "ai"}]
)
def test_dto_rejects_payload_policy_fields(bad):
    with pytest.raises(ValidationError):
        RequestCreate(
            title="request", reason="test", roots=(ref("spec"),), sources=(SOURCE,), **bad
        )


def test_unwired_ports_explicitly_require_integration():
    host = FakeHost()
    host.handler = ChangeControlHandler(Ports())
    rejected("INTEGRATION_REQUIRED", host.create)


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"authorized": False}, "FORBIDDEN_OPERATION"),
        ({"qualified": False}, "QUALIFICATION_REQUIRED"),
        ({"cancelled": True}, "RUN_CANCELLED"),
        ({"roles": ()}, "FORBIDDEN_OPERATION"),
    ],
)
def test_server_authority_is_required(changes, code):
    host = FakeHost()
    host.authority = replace(host.authority, **changes)
    rejected(code, host.create)
    assert not host.requests and not host.receipts


@pytest.mark.parametrize("source", [False, True])
def test_server_acl_denial_prevents_creation(source):
    host = FakeHost()
    if source:
        host.denied_sources.add(digest(SOURCE))
    else:
        host.denied_refs.add(ref("spec").identity)
    rejected("FORBIDDEN_SCOPE" if source else "FORBIDDEN_SCOPE", host.create)


def test_port_must_not_substitute_latest_reference():
    host = FakeHost()
    host.substitute = ref("spec", revision=2)
    rejected("FIXED_REFERENCE_MISMATCH", host.create)


@pytest.mark.parametrize(
    "mutation,code",
    [
        (
            lambda g: replace(g, scope=replace(g.scope, tenant_id=uid("other-tenant"))),
            "FORBIDDEN_SCOPE",
        ),
        (lambda g: replace(g, audience=("restricted",)), "AUDIENCE_USE_FORBIDDEN"),
        (
            lambda g: replace(
                g, nodes=(replace(g.nodes[0], audience=("restricted",)), *g.nodes[1:])
            ),
            "FORBIDDEN_SCOPE",
        ),
        (lambda g: replace(g, expires_at=NOW), "RECHECK_REQUIRED"),
        (lambda g: replace(g, revision=2), "FIXED_REFERENCE_MISMATCH"),
    ],
)
def test_graph_facts_scope_audience_expiry_and_version_are_enforced(mutation, code):
    host = FakeHost()
    host.create()
    original = host.snapshot
    host.snapshot = mutation(original)
    rejected(
        code,
        lambda: host.run("change.impact.compute", {"snapshot": ref("graph_snapshot", "graph")}),
    )
    assert host.request_value.status == "draft"


def test_all_known_objects_need_an_explicit_disposition():
    host = FakeHost()
    host.analyze()
    incomplete = replace(plan(), dispositions=plan().dispositions[:-1])
    rejected(
        "IMPACT_DISPOSITION_MISSING",
        lambda: host.run(
            "change.order.prepare",
            {
                "assessment_id": host.request_value.assessments[-1].id,
                "plan": incomplete,
                "reason": "test",
            },
        ),
    )


def test_unknown_disposition_prevents_approval():
    host = FakeHost()
    host.analyze()
    original = plan()
    changed = replace(
        original,
        dispositions=(
            replace(original.dispositions[0], handling="unknown"),
            *original.dispositions[1:],
        ),
    )
    host.run(
        "change.order.prepare",
        {"assessment_id": host.request_value.assessments[-1].id, "plan": changed, "reason": "test"},
    )
    host.actor("approver")
    rejected("IMPACT_UNKNOWN", lambda: host.run("change.order.approve", approval_payload()))


def test_missing_impact_edges_prevent_approval():
    host = FakeHost()
    host.prepare()
    assessment = host.request_value.assessments[-1]
    incomplete = compute_impact(
        replace(
            assessment.graph,
            edges=tuple(e for e in assessment.graph.edges if e.id != "operation-tooling"),
        ),
        assessment.request_revision,
    )
    host.requests[host.subject] = replace(
        host.request_value,
        assessments=(incomplete,),
        orders=(
            replace(host.order, assessment_id=incomplete.id, assessment_digest=digest(incomplete)),
        ),
    )
    host.actor("approver")
    rejected("IMPACT_UNKNOWN", lambda: host.run("change.order.approve", approval_payload()))


def test_two_named_approvals_do_not_create_implementation_or_effectivity():
    host = FakeHost()
    host.approve()
    assert host.request_value.status == "approved"
    assert (
        not host.order.implementations
        and not host.order.effectivity
        and not host.order.verifications
    )
    projection = reading(host)
    assert projection.engineering_approved and projection.manufacturing_approved
    assert all(i.effectivity_status == "not_effective" for i in projection.items)
    assert not projection.independently_verified and not projection.registered


@pytest.mark.parametrize(
    "mode,code",
    [
        ("ai", "NAMED_HUMAN_REQUIRED"),
        ("self", "SELF_APPROVAL_FORBIDDEN"),
        ("missing-decision", "NAMED_DECISION_REQUIRED"),
    ],
)
def test_ai_self_or_unidentified_approval_is_denied(mode, code):
    host = FakeHost()
    host.prepare()
    if mode == "ai":
        host.actor("ai", actor_kind="ai")
    elif mode == "missing-decision":
        host.actor("approver")
    payload = approval_payload()
    invocation = host.invocation("change.order.approve", payload)
    if mode == "missing-decision":
        invocation = replace(invocation, decision_id=None)
    rejected(code, lambda: host.execute(invocation, payload))
    assert not host.order.approvals


@pytest.mark.parametrize("drift", ["config", "source", "policy", "expiry"])
def test_old_decision_requires_recheck_after_server_drift(drift):
    host = FakeHost()
    host.approve()
    old = host.request_value
    if drift == "config":
        host.stale_refs.add(ref("engineering_configuration").identity)
    elif drift == "source":
        host.stale_sources.add(digest(SOURCE))
    elif drift == "policy":
        host.policy = replace(host.policy, source=replace(SOURCE, revision=2))
    else:
        host.authority = replace(host.authority, now=NOW + timedelta(days=3))
    item = host.order.plan.items[0]
    fact = host.implementation_fact(item)
    rejected(
        "RECHECK_REQUIRED",
        lambda: host.run("change.implementation.record", {"item_id": item.id, "fact_id": fact.id}),
    )
    assert host.request_value == old
    projection = reading(host)
    assert not projection.current and projection.engineering_approved


def test_t1_common_confirmation_one_use_expiry_and_missing_proof():
    host = FakeHost()
    host.approve()
    item = host.order.plan.items[0]
    fact = host.implementation_fact(item)
    payload = {"item_id": item.id, "fact_id": fact.id}
    invocation = host.invocation("change.implementation.record", payload)
    rejected("CONFIRMATION_REQUIRED", lambda: host.execute(invocation, payload))
    invocation = host.proof(invocation, payload)
    host.proofs[invocation.confirmation_token]["expires"] = NOW
    rejected("PREVIEW_EXPIRED", lambda: host.execute(invocation, payload))
    assert not host.order.implementations


def test_fact_drift_invalidates_common_preview_before_writes():
    host = FakeHost()
    host.approve()
    item = host.order.plan.items[0]
    fact = host.implementation_fact(item)
    payload = {"item_id": item.id, "fact_id": fact.id}
    invocation = host.proof(host.invocation("change.implementation.record", payload), payload)
    host.implementations[fact.id] = replace(fact, note="owner corrected execution evidence")
    rejected("RECHECK_REQUIRED", lambda: host.execute(invocation, payload))
    assert not host.order.implementations
    assert not host.proofs[invocation.confirmation_token]["used"]


def test_record_failure_rolls_back_entire_caller_transaction_then_retries_same_proof():
    host = FakeHost()
    host.approve()
    item = host.order.plan.items[0]
    fact = host.implementation_fact(item)
    payload = {"item_id": item.id, "fact_id": fact.id}
    invocation = host.proof(host.invocation("change.implementation.record", payload), payload)
    before = (
        host.request_value,
        len(host.receipts),
        len(host.audit),
        len(host.outbox),
        set(host.imported),
    )
    host.fail_record = True
    with pytest.raises(RuntimeError, match="after all writes"):
        host.execute(invocation, payload)
    assert (
        host.request_value,
        len(host.receipts),
        len(host.audit),
        len(host.outbox),
        set(host.imported),
    ) == before
    assert not host.proofs[invocation.confirmation_token]["used"]
    host.fail_record = False
    result = host.execute(invocation, payload)
    assert result.status == "implementing" and fact.id in host.imported
    assert host.proofs[invocation.confirmation_token]["used"]


def test_exact_and_semantic_replays_have_one_effect_and_no_second_confirmation():
    host = FakeHost()
    host.approve()
    item = host.order.plan.items[0]
    fact = host.implementation_fact(item)
    payload = {"item_id": item.id, "fact_id": fact.id}
    invocation = host.proof(host.invocation("change.implementation.record", payload), payload)
    host.execute(invocation, payload)
    counts = len(host.receipts), len(host.audit), len(host.outbox), host.confirm_calls
    assert host.execute(invocation, payload).replayed
    assert host.execute(
        replace(invocation, command_id=uid("retry-key"), confirmation_token=None), payload
    ).replayed
    assert (len(host.receipts), len(host.audit), len(host.outbox), host.confirm_calls) == counts


def test_key_collision_is_not_replayed_and_stale_revision_never_consumes_proof():
    host = FakeHost()
    host.approve()
    item = host.order.plan.items[0]
    first = host.implementation_fact(item, outcome="failed")
    payload = {"item_id": item.id, "fact_id": first.id}
    invocation = host.proof(host.invocation("change.implementation.record", payload), payload)
    host.execute(invocation, payload)
    second = host.implementation_fact(item)
    changed = {"item_id": item.id, "fact_id": second.id}
    colliding = replace(
        invocation, semantic_digest=digest(ImplementationRecord.model_validate(changed))
    )
    rejected("IDEMPOTENCY_CONFLICT", lambda: host.execute(colliding, changed))
    stale = replace(
        host.invocation("change.implementation.record", changed),
        expected_revision=invocation.expected_revision,
    )
    rejected("VERSION_CONFLICT", lambda: host.execute(stale, changed))


@pytest.mark.parametrize("outcome", ["failed", "unknown"])
def test_implementation_failure_or_unknown_cannot_become_effective(outcome):
    host = FakeHost()
    host.approve()
    item = host.order.plan.items[0]
    host.record_implementation(item, outcome=outcome)
    fact = host.effectivity_fact(item)
    rejected(
        "IMPLEMENTATION_INCOMPLETE",
        lambda: host.run("change.effectivity.record", {"item_id": item.id, "fact_id": fact.id}),
    )
    assert host.request_value.status == "implementing"
    assert reading(host).items[0].implementation_status == outcome
    if outcome == "unknown":
        second = host.implementation_fact(item)
        rejected(
            "IMPLEMENTATION_RECONCILE_REQUIRED",
            lambda: host.run(
                "change.implementation.record", {"item_id": item.id, "fact_id": second.id}
            ),
        )


@pytest.mark.parametrize(
    "changes,code",
    [
        (
            {"outputs": (ref("engineering_configuration", revision=2),)},
            "ORIGINAL_REWRITE_FORBIDDEN",
        ),
        ({"outputs": ()}, "ACTUAL_OUTPUT_REQUIRED"),
        ({"outputs": (ref("test_run", "wrong-output"),)}, "ACTUAL_OUTPUT_REQUIRED"),
        ({"nature": "real"}, "FACT_NATURE_MISMATCH"),
        ({"executor_id": uid("someone-else")}, "NAMED_EXECUTOR_REQUIRED"),
        ({"occurred_at": NOW - timedelta(seconds=1)}, "EXECUTION_BEFORE_APPROVAL"),
        ({"received_at": NOW + timedelta(seconds=1)}, "INVALID_EVENT_TIME"),
    ],
)
def test_owner_execution_must_match_new_fixed_output_and_named_fact(changes, code):
    host = FakeHost()
    host.approve()
    item = host.order.plan.items[0]
    fact = host.implementation_fact(item, **changes)
    rejected(
        code,
        lambda: host.run("change.implementation.record", {"item_id": item.id, "fact_id": fact.id}),
    )


@pytest.mark.parametrize(
    "stage,outcome,units,expected",
    [
        ("sent", "succeeded", ("batch:A", "batch:B"), "not_effective"),
        ("accepted", "succeeded", ("batch:A", "batch:B"), "not_effective"),
        ("effective", "succeeded", ("batch:A",), "partial"),
        ("effective", "unknown", (), "unknown"),
        ("effective", "failed", ("batch:A", "batch:B"), "failed"),
    ],
)
def test_transport_partial_unknown_failed_receipts_never_finish_effectivity(
    stage, outcome, units, expected
):
    host = FakeHost()
    host.approve()
    item = host.order.plan.items[0]
    host.record_implementation(item)
    host.record_effectivity(item, stage=stage, outcome=outcome, covered_units=units)
    assert effectivity_status(host.order, item) == expected
    assert host.request_value.status == "implementing"
    assert reading(host).items[0].effectivity_status == expected


def test_reimport_same_actual_receipt_keeps_single_fact_and_revision():
    host = FakeHost()
    host.approve()
    item = host.order.plan.items[0]
    host.record_implementation(item)
    fact = host.record_effectivity(item, covered_units=("batch:A",))
    old_revision = host.request_value.revision
    host.run("change.effectivity.record", {"item_id": item.id, "fact_id": fact.id})
    assert len(host.order.effectivity) == 1
    assert host.request_value.revision == old_revision


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"covered_units": ("batch:foreign",)}, "EFFECTIVITY_SCOPE_MISMATCH"),
        ({"conditions_digest": "wrong"}, "CONDITION_MISMATCH"),
        ({"covered_units": ()}, "ACTUAL_SCOPE_REQUIRED"),
        (
            {"output_refs": (ref("engineering_configuration", "unimplemented"),)},
            "EFFECTIVITY_OUTPUT_MISMATCH",
        ),
    ],
)
def test_receipt_scope_condition_and_actual_output_are_exact(changes, code):
    host = FakeHost()
    host.approve()
    item = host.order.plan.items[0]
    host.record_implementation(item)
    fact = host.effectivity_fact(item, **changes)
    rejected(
        code,
        lambda: host.run("change.effectivity.record", {"item_id": item.id, "fact_id": fact.id}),
    )


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"item_ids": ()}, "VERIFICATION_SCOPE_MISMATCH"),
        ({"output_refs": ()}, "VERIFICATION_OUTPUT_MISSING"),
        ({"result": "unknown"}, "VERIFICATION_INSUFFICIENT"),
        ({"applicable": False}, "VERIFICATION_INSUFFICIENT"),
        ({"current": False}, "VERIFICATION_INSUFFICIENT"),
        ({"observed_from": NOW - timedelta(seconds=1)}, "VERIFICATION_TOO_EARLY"),
        ({"nature": "real"}, "FACT_NATURE_MISMATCH"),
        ({"executor_ids": (uid("independent-quality"),)}, "INDEPENDENT_VERIFIER_REQUIRED"),
    ],
)
def test_independent_verification_requires_full_scope_actual_outputs_and_valid_evidence(
    changes, code
):
    host = FakeHost()
    host.effective()
    fact = host.verification_fact(**changes)
    rejected(
        code, lambda: host.run("change.verification.record", {"fact_id": fact.id, "text": "verify"})
    )
    assert not host.order.verifications


@pytest.mark.parametrize(
    "actor", ["requester", "approver-engineering", "approver-manufacturing", "executor"]
)
def test_participants_cannot_independently_verify_their_own_change(actor):
    host = FakeHost()
    host.effective()
    fact = host.verification_fact(verifier_id=uid(actor))
    host.actor(actor, ("quality",))
    rejected(
        "INDEPENDENT_VERIFIER_REQUIRED",
        lambda: host.run("change.verification.record", {"fact_id": fact.id, "text": "verify"}),
    )


def test_verification_is_separate_from_closure_and_historical_closure_survives_drift():
    host = FakeHost()
    host.effective()
    assert host.request_value.status == "verifying"
    rejected("CLOSURE_INCOMPLETE", lambda: host.run("change.close", {"text": "close"}))
    fact = host.verification_fact()
    host.run("change.verification.record", {"fact_id": fact.id, "text": "independent pass"})
    assert host.request_value.status == "verifying" and host.order.closure is None
    host.run("change.close", {"text": "named close"})
    original = host.request_value
    assert original.status == "closed" and len(original.history) == 11
    assert reading(host).independently_verified
    host.stale_refs.add(ref("engineering_configuration").identity)
    projection = reading(host)
    assert (
        projection.historically_closed
        and not projection.current
        and not projection.independently_verified
    )
    host.run("change.recheck", {"reason": "current fixed configuration changed"})
    assert host.request_value.needs_recheck and host.request_value.status == "closed"
    assert host.order.closure == original.orders[-1].closure
    assert host.order.approvals == original.orders[-1].approvals


def test_replay_still_checks_current_acl_and_fixed_original_audience():
    host = FakeHost()
    payload = {"title": "request", "reason": "test", "roots": (ref("spec"),), "sources": (SOURCE,)}
    invocation = host.invocation("change.request.create", payload)
    host.execute(invocation, payload)
    host.authority = replace(host.authority, audience=("other",))
    rejected("FORBIDDEN_SCOPE", lambda: host.execute(invocation, payload))


def test_failed_independent_verification_cannot_close():
    host = FakeHost()
    host.effective()
    fact = host.verification_fact(result="fail")
    host.run("change.verification.record", {"fact_id": fact.id, "text": "independent failure"})
    rejected("CLOSURE_INCOMPLETE", lambda: host.run("change.close", {"text": "close"}))
    assert not reading(host).independently_verified


@pytest.mark.parametrize("checkpoint", ["create", "compute", "implementation", "verify", "reader"])
def test_output_use_audience_is_distinct_from_read_permission(checkpoint):
    host = FakeHost()
    if checkpoint == "create":
        action = host.create
    elif checkpoint == "compute":
        host.create()
        action = partial(
            host.run, "change.impact.compute", {"snapshot": ref("graph_snapshot", "graph")}
        )
    elif checkpoint == "implementation":
        host.approve()
        item = host.order.plan.items[0]
        fact = host.implementation_fact(item)
        action = partial(
            host.run, "change.implementation.record", {"item_id": item.id, "fact_id": fact.id}
        )
    elif checkpoint == "verify":
        host.effective()
        fact = host.verification_fact()
        action = partial(
            host.run, "change.verification.record", {"fact_id": fact.id, "text": "verify"}
        )
    else:
        host.prepare()
        action = partial(reading, host)
    before = len(host.receipts)
    host.audience_allowed = False
    rejected("AUDIENCE_USE_FORBIDDEN", action)
    assert len(host.receipts) == before


def test_losing_cas_at_record_rolls_back_consumed_common_proof():
    host = FakeHost()
    host.approve()
    item = host.order.plan.items[0]
    fact = host.implementation_fact(item)
    payload = {"item_id": item.id, "fact_id": fact.id}
    invocation = host.proof(host.invocation("change.implementation.record", payload), payload)
    before = host.request_value
    host.race_record = True
    rejected("VERSION_CONFLICT", lambda: host.execute(invocation, payload))
    assert host.request_value == before
    assert not host.proofs[invocation.confirmation_token]["used"]
    assert fact.id not in host.imported and invocation.command_id not in host.receipts


def test_owner_can_reconcile_same_unknown_implementation_without_rewriting_history():
    host = FakeHost()
    host.approve()
    item = host.order.plan.items[0]
    unknown = host.record_implementation(item, outcome="unknown")
    reconciliation = host.record_implementation(item, reconciles_id=unknown.id)
    assert host.order.implementations == (unknown, reconciliation)
    host.record_effectivity(item)
    assert reading(host).items[0].implementation_status == "succeeded"
    assert reading(host).items[0].effectivity_status == "effective"


@pytest.mark.parametrize(
    "changes",
    [
        {"reconciles_id": uid("absent")},
        {"occurred_at": NOW - timedelta(seconds=1)},
        {"outcome": "unknown"},
    ],
)
def test_unknown_implementation_reconciliation_requires_same_owner_occurrence(changes):
    host = FakeHost()
    host.approve()
    item = host.order.plan.items[0]
    unknown = host.record_implementation(item, outcome="unknown")
    fact = host.implementation_fact(item, **({"reconciles_id": unknown.id} | changes))
    expected = "EXECUTION_BEFORE_APPROVAL" if "occurred_at" in changes else "INVALID_RECONCILIATION"
    rejected(
        expected,
        lambda: host.run("change.implementation.record", {"item_id": item.id, "fact_id": fact.id}),
    )
    assert host.order.implementations == (unknown,)


def test_external_unknown_requires_reconciliation_and_cannot_be_blindly_resent():
    host = FakeHost()
    host.approve()
    item = host.order.plan.items[0]
    host.record_implementation(item)
    unknown = host.record_effectivity(item, outcome="unknown", covered_units=())
    fresh = host.effectivity_fact(item)
    rejected(
        "EFFECTIVITY_RECONCILE_REQUIRED",
        lambda: host.run("change.effectivity.record", {"item_id": item.id, "fact_id": fresh.id}),
    )
    resolved = host.record_effectivity(
        item, reconciles_id=unknown.id, external_id=unknown.external_id
    )
    assert host.order.effectivity == (unknown, resolved)
    assert effectivity_status(host.order, item) == "effective"
    assert reading(host).items[0].remaining_units == ()


@pytest.mark.parametrize(
    "changes",
    [
        {"external_id": "different"},
        {"system": "different"},
        {"covered_units": ("batch:A",)},
        {"outcome": "unknown"},
        {"stage": "accepted"},
    ],
)
def test_external_unknown_reconciliation_matches_all_original_fields(changes):
    host = FakeHost()
    host.approve()
    item = host.order.plan.items[0]
    host.record_implementation(item)
    unknown = host.record_effectivity(item, outcome="unknown", covered_units=())
    fact = host.effectivity_fact(
        item, **({"reconciles_id": unknown.id, "external_id": unknown.external_id} | changes)
    )
    rejected(
        "INVALID_RECONCILIATION",
        lambda: host.run("change.effectivity.record", {"item_id": item.id, "fact_id": fact.id}),
    )
    assert host.order.effectivity == (unknown,)


def test_changed_owner_fact_at_same_id_preserves_history_and_requires_recheck():
    host = FakeHost()
    host.approve()
    item = host.order.plan.items[0]
    fact = host.record_implementation(item)
    host.implementations[fact.id] = replace(fact, note="corrected owner record")
    projection = reading(host)
    assert not projection.current
    assert projection.request.orders[-1].implementations == (fact,)


def test_history_reader_does_not_expose_acl_denied_sources():
    host = FakeHost()
    host.effective()
    host.denied_sources.add(digest(SOURCE))
    rejected("FORBIDDEN_SCOPE", lambda: reading(host))


def test_receipt_transport_identity_cannot_be_reimported_under_fresh_fact_id():
    host = FakeHost()
    host.approve()
    item = host.order.plan.items[0]
    host.record_implementation(item)
    original = host.record_effectivity(item, covered_units=("batch:A",))
    duplicate = host.effectivity_fact(item, external_id=original.external_id)
    rejected(
        "RECEIPT_IDENTITY_CONFLICT",
        lambda: host.run(
            "change.effectivity.record", {"item_id": item.id, "fact_id": duplicate.id}
        ),
    )
    assert host.order.effectivity == (original,)


def test_unknown_receipt_can_only_have_one_reconciliation_result():
    host = FakeHost()
    host.approve()
    item = host.order.plan.items[0]
    host.record_implementation(item)
    unknown = host.record_effectivity(item, outcome="unknown", covered_units=())
    host.record_effectivity(item, reconciles_id=unknown.id, external_id=unknown.external_id)
    duplicate = host.effectivity_fact(
        item, reconciles_id=unknown.id, external_id=unknown.external_id
    )
    rejected(
        "RECONCILIATION_ALREADY_RECORDED",
        lambda: host.run(
            "change.effectivity.record", {"item_id": item.id, "fact_id": duplicate.id}
        ),
    )


def test_common_confirmation_proof_cannot_be_transferred_to_other_actor():
    host = FakeHost()
    host.prepare()
    host.actor("approver-engineering")
    payload = approval_payload()
    invocation = host.proof(host.invocation("change.order.approve", payload), payload)
    host.actor("other-engineer")
    rejected("CONFIRMATION_SCOPE_CHANGED", lambda: host.execute(invocation, payload))
    assert not host.order.approvals
    assert not host.proofs[invocation.confirmation_token]["used"]


@pytest.mark.parametrize("expires", [NOW, NOW + timedelta(days=2)])
def test_named_approval_validity_must_be_inside_fixed_effectivity_plan(expires):
    host = FakeHost()
    host.prepare()
    host.actor("approver")
    rejected(
        "APPROVAL_EXPIRY_INVALID",
        lambda: host.run("change.order.approve", {**approval_payload(), "expires_at": expires}),
    )


def test_model_cannot_change_semantic_payload_after_envelope_digest_is_bound():
    host = FakeHost()
    original = {"title": "fixed", "reason": "test", "roots": (ref("spec"),), "sources": (SOURCE,)}
    invocation = host.invocation("change.request.create", original)
    rejected(
        "PAYLOAD_DIGEST_MISMATCH",
        lambda: host.execute(invocation, {**original, "reason": "changed"}),
    )
    assert not host.requests


def test_server_request_scope_denial_is_checked_even_if_port_returns_cross_tenant_object():
    host = FakeHost()
    host.create()
    host.requests[host.subject] = replace(
        host.request_value, scope=replace(host.authority.scope, tenant_id=uid("other-tenant"))
    )
    rejected("FORBIDDEN_SCOPE", lambda: reading(host))


def test_quality_role_is_required_even_for_independent_uninvolved_actor():
    host = FakeHost()
    host.effective()
    fact = host.verification_fact()
    host.actor("independent-quality", ("engineering",))
    rejected(
        "FORBIDDEN_OPERATION",
        lambda: host.run("change.verification.record", {"fact_id": fact.id, "text": "verify"}),
    )


def test_t1_implementation_recording_is_denied_for_ai_actor():
    host = FakeHost()
    host.approve()
    item = host.order.plan.items[0]
    fact = host.implementation_fact(item)
    host.actor("ai", actor_kind="ai")
    rejected(
        "NAMED_HUMAN_REQUIRED",
        lambda: host.run("change.implementation.record", {"item_id": item.id, "fact_id": fact.id}),
    )


def test_revised_request_keeps_old_closed_order_and_immutable_measurement_history():
    host = FakeHost()
    host.effective()
    fact = host.verification_fact()
    host.run("change.verification.record", {"fact_id": fact.id, "text": "independent pass"})
    host.run("change.close", {"text": "close fixed plan"})
    closed_order = host.order
    old_assessments = host.request_value.assessments
    host.stale_refs.add(ref("engineering_configuration").identity)
    host.run("change.recheck", {"reason": "configuration changes require new analysis"})
    host.run(
        "change.request.revise",
        {
            "title": "revised fixed request",
            "reason": "new analysis",
            "roots": host.request_value.roots,
            "references": host.request_value.references,
            "sources": host.request_value.sources,
        },
    )
    assert host.request_value.status == "draft"
    assert host.request_value.orders == (closed_order,)
    assert host.request_value.assessments == old_assessments
    assert not host.request_value.needs_recheck
    projection = reading(host)
    assert projection.historically_closed
    assert not projection.engineering_approved and not projection.independently_verified
    assert not projection.items


def test_fixed_graph_snapshot_itself_withdrawn_invalidates_old_approval():
    host = FakeHost()
    host.approve()
    snapshot_ref = Ref(id=host.snapshot.id, revision=host.snapshot.revision, kind="graph_snapshot")
    host.stale_refs.add(snapshot_ref.identity)
    with host.transaction() as uow:
        reading = ChangeControlReader(Ports(commands=host, facts=host, policies=host)).get(
            uow,
            host.subject,
        )
    assert not reading.current
    assert reading.engineering_approved and reading.manufacturing_approved
    assert "configuration revision changed" in reading.recheck_reasons
