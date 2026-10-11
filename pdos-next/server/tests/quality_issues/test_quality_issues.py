"""Synthetic G3.1 contract tests, including caller-transaction refusal paths."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from pdos_next.domain.quality_issues.handlers import QualityIssueHandler
from pdos_next.domain.quality_issues.ports import Ports, VerifiedRun
from pdos_next.domain.quality_issues.rules import failure_ref, issue_sources, replace
from pdos_next.domain.verification.rules import compute_results
from pdos_next.errors import DomainError
from pdos_next.schemas.quality_issues.contracts import (
    CapaAction,
    CapaDraft,
    ContainmentRecord,
    EffectivenessDecide,
    EffectivenessRequirement,
    Hypothesis,
    IssueClose,
    IssueCreate,
    IssueMerge,
    IssueRecheck,
    IssueTriage,
    Ref,
)

from .helpers import NOW, Harness, Rejection, fixed_run, source, uid


def decide():
    return EffectivenessDecide(
        result="effective",
        text="Synthetic independent effectiveness",
        evidence_ids=(uid("verification"),),
    )


def assert_domain(code, fn):
    with pytest.raises(DomainError) as error:
        fn()
    assert error.value.reason == code


def _repeated_source_issue(h, **changes):
    iid = h.create().subject_id
    shared = source("repeated-judgment")
    other = replace(shared, **changes)
    action = h.action("repeated-judgment-action")
    action = replace(
        action,
        evidence=(shared, other, shared),
        at=replace(action.at, source=shared),
    )
    issue = replace(h.issue(iid), status="actioning", containment=(action,))
    h.commands.issues[iid] = issue
    return issue, shared, other


@pytest.mark.parametrize("field", ["kind", "id", "revision", "position"])
def test_normal_action_distinct_sources_preserve_identity_and_recheck_every_call(
    monkeypatch, field
):
    h = Harness()
    changes = {
        "kind": "domain",
        "id": uid("other-judgment"),
        "revision": 2,
        "position": "synthetic: sheet 1 / B2",
    }
    issue, shared, other = _repeated_source_issue(h, **{field: changes[field]})
    assert issue_sources(issue) == (shared, other, shared, shared)
    assert issue_sources(issue, distinct=True) == (shared, other)
    actual = h.evidence.currentness
    calls = []

    def observed(bound_scope, ref, purpose):
        assert bound_scope == issue.scope and purpose == "quality.issue"
        calls.append(ref)
        return actual(bound_scope, ref, purpose)

    monkeypatch.setattr(h.evidence, "currentness", observed)
    assessments = h.handler._current(h.commands.authority, issue)
    assert all(assessment.current for assessment in assessments)
    assert len(assessments) == len(issue.failures) + 2
    assert calls == [shared, other]

    # Each later invocation still asks the actual port; an earlier positive
    # assessment cannot conceal a changed ACL or withdrawn distinct reference.
    action = ContainmentRecord(action=h.action("next-judgment-action"))
    h.evidence.denied.add(other)
    with pytest.raises(Rejection, match="source revoked/ACL denied"):
        h.call("quality.issue.containment.record", issue.id, issue.revision, action)
    assert calls == [shared, other] * 2
    assert h.issue(issue.id) == issue
    h.evidence.denied.clear()
    h.evidence.stale[other] = ("Distinct judgment source withdrawn",)
    assert_domain(
        "RECHECK_REQUIRED",
        lambda: h.call("quality.issue.containment.record", issue.id, issue.revision, action),
    )
    assert calls == [shared, other] * 3
    assert h.issue(issue.id) == issue


def test_raw_recheck_and_reader_preserve_repeated_source_reason_sequence(monkeypatch):
    from pdos_next.domain.quality_issues.read_models import QualityIssueReader

    h = Harness()
    issue, shared, other = _repeated_source_issue(h)
    assert other == shared and issue_sources(issue) == (shared,) * 4
    assert issue_sources(issue, distinct=True) == (shared,)
    reason = "Repeated judgment source withdrawn"
    h.evidence.stale[shared] = (reason,)
    actual = h.evidence.currentness
    calls = []

    def observed(bound_scope, ref, purpose):
        calls.append(ref)
        return actual(bound_scope, ref, purpose)

    monkeypatch.setattr(h.evidence, "currentness", observed)
    assessments = h.handler._current(h.commands.authority, issue, allow_stale=True)
    assert tuple(reason for value in assessments for reason in value.reasons) == (reason,) * 4
    assert calls == [shared] * 4
    reading = QualityIssueReader(h.handler.ports).get(issue.id)
    assert reading.issue == issue and not reading.current
    assert reading.recheck_reasons == (reason,) * 4
    assert calls == [shared] * 8
    h.call(
        "quality.issue.recheck", issue.id, issue.revision, IssueRecheck(reason="Synthetic recheck")
    )
    saved = h.issue(issue.id)
    assert saved.needs_recheck and saved.recheck_reasons == (reason,) * 4
    assert saved.containment == issue.containment and saved.history[:-1] == issue.history
    assert calls == [shared] * 16


def test_synthetic_result_is_strict_verified_failure():
    run = fixed_run()
    assert run.result == "fail"
    assert run.computed_results[0].reasons == ()
    ref = failure_ref(VerifiedRun(run=run, nature="synthetic"), run.measurements[0].id)
    assert ref.nature == "synthetic"
    assert ref.source == run.measurements[0].source
    assert ref.sample.actual_configuration == run.samples[0].actual_configuration
    assert ref.criterion == run.items[0].criterion.source
    assert ref.method == run.items[0].method
    assert not hasattr(ref, "raw_value")  # TestRun retains sole measurement authority.


@pytest.mark.parametrize(
    "delivery,title,key",
    [
        ("delivery", "Changed title", "other-key"),
        ("redelivery", "Same failure second event", "third-key"),
    ],
)
def test_failure_identity_deduplicates_across_event_key_and_title(delivery, title, key):
    h = Harness()
    original = h.create()
    result = h.create(event_name=delivery, title=title, key=key)
    assert result.subject_id == original.subject_id
    assert len(h.commands.issues) == 1
    assert h.issue(original.subject_id).title == "Synthetic failure"
    assert len(h.issue(original.subject_id).history) == 1


def test_unrelated_run_revision_does_not_create_new_issue_or_rewrite_fixed_reference():
    h = Harness()
    first = h.create()
    old = h.issue(first.subject_id)
    verified = h.runs.records[uid("run")]
    h.runs.records[uid("run")] = replace(verified, run=replace(verified.run, revision=19))
    second = h.create(event_name="later-event", title="different title")
    assert second.subject_id == first.subject_id
    assert h.issue(first.subject_id) == old
    observed = h.commands.deliveries[(uid("later-event"), old.failures[0].identity)].observed
    assert observed.run.revision == 19
    assert old.failures[0].run.revision == 1


@pytest.mark.parametrize(
    "change",
    [
        {"status": "planned"},
        {"result": "pending"},
        {"result": "indeterminate"},
        {"actual_start": None},
        {"measurements": ()},
        {"computed_results": ()},
        {"execution": None},
    ],
)
def test_planned_empty_unknown_or_unverified_result_rejected(change):
    run = replace(fixed_run(), **change)
    assert_domain(
        "NOT_ACTUAL_FAILURE",
        lambda: failure_ref(VerifiedRun(run=run, nature="synthetic"), uid("run-measurement")),
    )


@pytest.mark.parametrize(
    "change",
    [
        {"raw_value": "unknown"},
        {"raw_value": None},
        {"source": None},
        {"method": None},
        {"unit": "in"},
        {"conditions": "other"},
        {"observed_at": None},
        {"environment": "other"},
    ],
)
def test_indeterminate_measurement_not_promoted_by_stored_failure(change):
    run = fixed_run()
    measurement = replace(run.measurements[0], **change)
    # Stale stored fail is deliberately preserved; authoritative recomputation must refuse it.
    run = replace(run, measurements=(measurement,))
    assert_domain(
        "NOT_ACTUAL_FAILURE",
        lambda: failure_ref(VerifiedRun(run=run, nature="synthetic"), measurement.id),
    )


def test_pass_measurement_in_failed_run_is_not_issue_failure():
    run = fixed_run()
    second_pair = replace(run.coverage[0], item_id="other")
    second_item = replace(run.items[0], id="other")
    second_measurement = replace(
        run.measurements[0], id=uid("second"), coverage=second_pair, raw_value="9.5"
    )
    run = replace(
        run,
        items=run.items + (second_item,),
        coverage=run.coverage + (second_pair,),
        measurements=run.measurements + (second_measurement,),
    )
    computed, result = compute_results(run, run.measurements)
    run = replace(run, computed_results=computed, result=result)
    assert_domain(
        "NOT_ACTUAL_FAILURE",
        lambda: failure_ref(VerifiedRun(run=run, nature="synthetic"), second_measurement.id),
    )


def test_missing_ports_are_explicitly_unavailable():
    handler = QualityIssueHandler(Ports())
    payload = IssueCreate(
        run_id=uid("run"),
        measurement_id=uid("run-measurement"),
        event_id=uid("delivery"),
        title="Synthetic",
    )
    assert_domain(
        "INTEGRATION_REQUIRED",
        lambda: handler.preview("quality.issue.create", uid("run"), 0, payload),
    )


@pytest.mark.parametrize(
    "authority,code",
    [
        ({"authorized": False}, "FORBIDDEN_OPERATION"),
        ({"roles": ("observer",)}, "FORBIDDEN_OPERATION"),
        ({"qualified": False}, "QUALIFICATION_REQUIRED"),
        ({"cancelled": True}, "RUN_CANCELLED"),
    ],
)
def test_server_authority_is_required_even_for_t0(authority, code):
    h = Harness()
    h.commands.authority = replace(h.commands.authority, **authority)
    assert_domain(code, h.create)
    assert h.commands.issues == {}
    assert h.commands.receipts == {}


def test_payload_cannot_inject_scope_actor_policy_or_business_result():
    payload = dict(
        run_id=uid("run"),
        measurement_id=uid("run-measurement"),
        event_id=uid("delivery"),
        title="Synthetic",
    )
    for field in ("scope", "actor_id", "authorized", "risk", "result"):
        with pytest.raises(ValidationError):
            IssueCreate.model_validate({**payload, field: "forged"})


def test_same_command_key_changed_payload_is_rejected_without_writes():
    h = Harness()
    h.create(key="same-key")
    before = dict(h.commands.issues)
    with pytest.raises(Rejection, match="same command key"):
        h.create(title="Changed title", key="same-key")
    assert h.commands.issues == before


def test_replay_keeps_history_and_receipt_and_rechecks_authority():
    h = Harness()
    iid = h.create().subject_id
    payload = IssueTriage(reason="Synthetic triage")
    inv = h.prepared("quality.issue.triage", iid, 1, payload, key="triage-key")
    result = h.execute(inv, payload)
    count = len(h.issue(iid).history)
    again = h.execute(inv, payload)
    assert again == replace(result, replayed=True)
    assert len(h.issue(iid).history) == count
    assert len(h.commands.consumed) == 1
    h.commands.authority = replace(h.commands.authority, authorized=False)
    assert_domain("FORBIDDEN_OPERATION", lambda: h.execute(inv, payload))


def test_replay_rechecks_precise_source_currentness():
    h = Harness()
    iid = h.create().subject_id
    payload = IssueTriage(reason="Synthetic triage")
    inv = h.prepared("quality.issue.triage", iid, 1, payload)
    h.execute(inv, payload)
    h.runs.stale[h.issue(iid).failures[0].source] = ("Source withdrawn",)
    assert_domain("RECHECK_REQUIRED", lambda: h.execute(inv, payload))


def test_proof_is_single_use_and_cannot_authorize_different_intent():
    h = Harness()
    iid = h.create().subject_id
    payload = IssueTriage(reason="Synthetic triage")
    inv = h.prepared("quality.issue.triage", iid, 1, payload)
    h.execute(inv, payload)
    # A missing replay receipt cannot make consumed proof reusable.
    h.commands.receipts.clear()
    h.commands.issues[iid] = replace(h.issue(iid), revision=1, status="open")
    with pytest.raises(Rejection, match="proof replay"):
        h.execute(replace(inv, command_id=uid("fresh-key")), payload)


def two_issues(h):
    first = h.create().subject_id
    h.runs.records[uid("second-run")] = VerifiedRun(run=fixed_run("second-run"), nature="synthetic")
    second = h.create("second-run", "second-delivery", title="Synthetic failure").subject_id
    return first, second


def test_same_title_independent_failures_remain_separate_until_confirmed_merge():
    h = Harness()
    first, second = two_issues(h)
    assert first != second
    assert len(h.commands.issues) == 2
    old_first, old_second = h.issue(first), h.issue(second)
    payload = IssueMerge(sources=(Ref(id=second, revision=1),), reason="Synthetic reviewed overlap")
    preview = h.handler.preview("quality.issue.merge", first, 1, payload)
    assert len(preview.failures) == 2
    assert len(preview.issues) == 2
    assert any("保留原问题" in difference for difference in preview.differences)
    assert h.issue(first) == old_first and h.issue(second) == old_second
    h.call("quality.issue.merge", first, 1, payload)
    merged = h.issue(first)
    original = h.issue(second)
    assert merged.aliases == (second,)
    assert merged.failures == tuple(
        sorted(old_first.failures + old_second.failures, key=lambda f: f.identity)
    )
    assert original.merged_into == first
    assert original.failures == old_second.failures
    assert original.history[:-1] == old_second.history
    assert merged.history[:-1] == old_first.history
    assert merged.needs_recheck
    result = h.create("second-run", "new-delivery")
    assert result.subject_id == first
    assert len(h.commands.issues) == 2


@pytest.mark.parametrize(
    "change,code",
    [
        ({"audience": ("team", "external")}, "FORBIDDEN_SCOPE"),
        ({"audience": ("restricted",)}, "FORBIDDEN_SCOPE"),
        ({"status": "actioning"}, "MERGE_CONFLICT"),
        ({"merged_into": uid("other")}, "MERGE_CONFLICT"),
    ],
)
def test_merge_rejects_scope_audience_or_work_conflict(change, code):
    h = Harness()
    first, second = two_issues(h)
    h.commands.issues[second] = replace(h.issue(second), **change)
    payload = IssueMerge(sources=(Ref(id=second, revision=1),), reason="Synthetic merge")
    assert_domain(code, lambda: h.handler.preview("quality.issue.merge", first, 1, payload))
    assert h.issue(first).revision == 1


def test_merge_cross_tenant_cannot_read_or_expand_scope():
    h = Harness()
    first, second = two_issues(h)
    other_scope = replace(h.issue(second).scope, tenant_id=uid("other-tenant"))
    h.commands.issues[second] = replace(h.issue(second), scope=other_scope)
    payload = IssueMerge(sources=(Ref(id=second, revision=1),), reason="Synthetic merge")
    assert_domain(
        "FORBIDDEN_SCOPE", lambda: h.handler.preview("quality.issue.merge", first, 1, payload)
    )


def test_merge_revision_and_self_conflicts():
    h = Harness()
    first, second = two_issues(h)
    for source_id, revision, code in (
        (first, 1, "MERGE_CONFLICT"),
        (second, 9, "REVISION_CONFLICT"),
    ):
        payload = IssueMerge(
            sources=(Ref(id=source_id, revision=revision),), reason="Synthetic merge"
        )
        assert_domain(
            code,
            lambda payload=payload: h.handler.preview("quality.issue.merge", first, 1, payload),
        )


@pytest.mark.parametrize(
    "reason",
    [
        "Source withdrawn",
        "Actual configuration changed",
        "Criterion version changed",
        "Method applicability changed",
    ],
)
def test_drift_marks_recheck_preserves_original_and_blocks_judgement(reason):
    h = Harness()
    iid = h.create().subject_id
    original = h.issue(iid)
    h.runs.stale[original.failures[0].source] = (reason,)
    assert_domain(
        "RECHECK_REQUIRED",
        lambda: h.call("quality.issue.triage", iid, 1, IssueTriage(reason="Synthetic")),
    )
    h.call("quality.issue.recheck", iid, 1, IssueRecheck(reason="Synthetic source invalidation"))
    current = h.issue(iid)
    assert current.needs_recheck
    assert current.recheck_reasons == (reason,)
    assert current.failures == original.failures
    assert current.history[:-1] == original.history


def test_source_acl_failure_does_not_even_record_recheck():
    h = Harness()
    iid = h.create().subject_id
    original = h.issue(iid)
    h.runs.denied = True
    assert_domain(
        "FORBIDDEN_SCOPE",
        lambda: h.call("quality.issue.recheck", iid, 1, IssueRecheck(reason="Synthetic")),
    )
    assert h.issue(iid) == original


def test_draft_hypothesis_does_not_become_named_root_cause_or_effectiveness():
    h = Harness()
    iid = h.create().subject_id
    h.call("quality.issue.triage", iid, 1, IssueTriage(reason="Synthetic"))
    h.commands.authority = replace(h.commands.authority, actor_kind="ai")
    payload = CapaDraft(
        capa_id=uid("capa"),
        hypotheses=(Hypothesis(text="AI synthetic hypothesis", sources=(source("hypothesis"),)),),
        actions=(
            CapaAction(
                id=uid("action"), kind="corrective", text="Synthetic", executor_id=uid("executor")
            ),
        ),
        requirement=EffectivenessRequirement(
            method="New run",
            acceptance="Pass",
            observation_until=NOW,
            required_failure_ids=(h.issue(iid).failures[0].identity,),
        ),
    )
    h.call("quality.capa.draft", iid, 2, payload)
    issue = h.issue(iid)
    assert issue.status == "actioning" and issue.root_cause is None
    assert issue.capa.effectiveness is None and issue.closure is None
    assert_domain(
        "NAMED_DECISION_REQUIRED",
        lambda: h.handler.preview(
            "quality.capa.effectiveness.decide", iid, issue.revision, decide()
        ),
    )


def test_completed_actions_cannot_close_without_independent_effectiveness():
    h = Harness()
    iid = h.ready()
    issue = h.issue(iid)
    assert issue.status == "awaiting_verification"
    assert all(action.completion is not None for action in issue.capa.actions)
    assert issue.capa.effectiveness is None and issue.closure is None
    assert_domain(
        "EFFECTIVENESS_REQUIRED",
        lambda: h.call("quality.issue.close", iid, issue.revision, IssueClose(text="Synthetic")),
    )


@pytest.mark.parametrize("actor", ["executor", "tester", "new-tester"])
def test_executor_or_original_test_executor_cannot_decide_effectiveness(actor):
    h = Harness()
    iid = h.ready()
    h.commands.authority = replace(h.commands.authority, actor_id=uid(actor))
    assert_domain(
        "INDEPENDENCE_REQUIRED",
        lambda: h.call("quality.capa.effectiveness.decide", iid, h.issue(iid).revision, decide()),
    )


@pytest.mark.parametrize(
    "operation,payload",
    [
        ("quality.capa.effectiveness.decide", decide()),
        ("quality.issue.close", IssueClose(text="AI synthetic closure")),
    ],
)
def test_ai_cannot_execute_t2(operation, payload):
    h = Harness()
    iid = h.ready()
    h.commands.authority = replace(h.commands.authority, actor_kind="ai")
    assert_domain(
        "NAMED_DECISION_REQUIRED", lambda: h.call(operation, iid, h.issue(iid).revision, payload)
    )


@pytest.mark.parametrize(
    "change,code",
    [
        ({"current": False}, "INVALID_VERIFICATION"),
        ({"applicable": False}, "INVALID_VERIFICATION"),
        ({"sources": ()}, "INVALID_VERIFICATION"),
        ({"run_ids": ()}, "INVALID_VERIFICATION"),
        ({"run_ids": (uid("run"),)}, "INVALID_VERIFICATION"),
        ({"nature": "real"}, "INVALID_VERIFICATION"),
        ({"failure_ids": ()}, "INCOMPLETE_VERIFICATION"),
        ({"failure_ids": ("other-failure",)}, "INCOMPLETE_VERIFICATION"),
        ({"verifier_id": uid("executor")}, "INDEPENDENCE_REQUIRED"),
        ({"verifier_id": uid("different-reviewer")}, "INDEPENDENCE_REQUIRED"),
        ({"result": "indeterminate"}, "NOT_EFFECTIVE"),
        ({"result": "fail"}, "NOT_EFFECTIVE"),
        ({"observed_until": NOW - timedelta(minutes=2)}, "OBSERVATION_PENDING"),
        ({"observed_until": NOW + timedelta(minutes=1)}, "INVALID_VERIFICATION"),
    ],
)
def test_independent_effectiveness_requires_exact_current_new_pass_evidence(change, code):
    h = Harness()
    iid = h.ready()
    h.policies.evidence[uid("verification")] = replace(
        h.policies.evidence[uid("verification")], **change
    )
    assert_domain(
        code,
        lambda: h.call("quality.capa.effectiveness.decide", iid, h.issue(iid).revision, decide()),
    )
    assert h.issue(iid).capa.effectiveness is None


def test_observation_requirement_cannot_be_shortened_by_payload():
    h = Harness()
    iid = h.ready()
    issue = h.issue(iid)
    requirement = replace(issue.capa.requirement, observation_until=NOW + timedelta(days=1))
    h.commands.issues[iid] = replace(issue, capa=replace(issue.capa, requirement=requirement))
    assert_domain(
        "OBSERVATION_PENDING",
        lambda: h.call("quality.capa.effectiveness.decide", iid, issue.revision, decide()),
    )


def test_named_synthetic_effectiveness_and_close_are_separate_commands():
    h = Harness()
    iid = h.ready()
    h.call("quality.capa.effectiveness.decide", iid, h.issue(iid).revision, decide())
    effective = h.issue(iid)
    assert effective.status == "awaiting_verification"
    assert effective.closure is None
    assert effective.capa.effectiveness.actor_id == uid("independent-reviewer")
    h.call(
        "quality.issue.close", iid, effective.revision, IssueClose(text="Synthetic named closure")
    )
    closed = h.issue(iid)
    assert closed.status == "closed"
    assert closed.closure.actor_id == uid("independent-reviewer")
    assert len(h.commands.consumed) == 6


def test_current_policy_drift_blocks_close_preserves_effectiveness_history():
    h = Harness()
    iid = h.ready()
    h.call("quality.capa.effectiveness.decide", iid, h.issue(iid).revision, decide())
    effective = h.issue(iid)
    h.policies.policy = replace(h.policies.policy, ref=replace(h.policies.policy.ref, revision=2))
    assert_domain(
        "RECHECK_REQUIRED",
        lambda: h.call(
            "quality.issue.close", iid, effective.revision, IssueClose(text="Synthetic")
        ),
    )
    assert h.issue(iid) == effective


def test_closed_history_is_retained_after_source_withdrawal():
    h = Harness()
    iid = h.ready()
    h.call("quality.capa.effectiveness.decide", iid, h.issue(iid).revision, decide())
    h.call("quality.issue.close", iid, h.issue(iid).revision, IssueClose(text="Synthetic"))
    closed = h.issue(iid)
    h.runs.stale[closed.failures[0].source] = ("Original reading withdrawn",)
    h.call(
        "quality.issue.recheck", iid, closed.revision, IssueRecheck(reason="Synthetic withdrawal")
    )
    stale = h.issue(iid)
    assert stale.status == "closed" and stale.needs_recheck
    assert stale.closure == closed.closure
    assert stale.capa.effectiveness == closed.capa.effectiveness


@pytest.mark.parametrize(
    "fail_at", ["after-proof", "after-facts", "after-inbox", "after-receipt", "after-outbox"]
)
def test_caller_transaction_rolls_back_facts_proof_receipt_audit_outbox(fail_at):
    h = Harness()
    iid = h.create().subject_id
    payload = IssueTriage(reason="Synthetic triage")
    inv = h.prepared("quality.issue.triage", iid, 1, payload)
    before = {
        name: getattr(h.commands, name).copy()
        for name in ("issues", "failure_map", "deliveries", "intents", "receipts", "proofs")
    }
    audit, outbox, consumed = (
        list(h.commands.audit),
        list(h.commands.outbox),
        set(h.commands.consumed),
    )
    h.commands.fail_at = fail_at
    with pytest.raises(Rejection, match="injected"):
        h.execute(inv, payload)
    for name, value in before.items():
        assert getattr(h.commands, name) == value
    assert h.commands.audit == audit and h.commands.outbox == outbox
    assert h.commands.consumed == consumed


def test_merge_cas_port_failure_rolls_back_all_originals():
    h = Harness()
    first, second = two_issues(h)
    payload = IssueMerge(sources=(Ref(id=second, revision=1),), reason="Synthetic")
    inv = h.prepared("quality.issue.merge", first, 1, payload)
    before = dict(h.commands.issues)
    h.commands.race_revision = True
    with pytest.raises(Rejection, match="CAS"):
        h.execute(inv, payload)
    assert h.commands.issues == before and h.commands.consumed == set()


def test_confirmation_preview_detects_policy_or_payload_drift():
    h = Harness()
    iid = h.create().subject_id
    payload = IssueTriage(reason="Synthetic")
    inv = h.prepared("quality.issue.triage", iid, 1, payload)
    h.policies.policy = replace(h.policies.policy, risk="critical")
    with pytest.raises(Rejection, match="read-set"):
        h.execute(inv, payload)
    assert h.issue(iid).revision == 1


def test_payload_digest_mismatch_rejected_before_begin():
    h = Harness()
    iid = h.create().subject_id
    payload = IssueTriage(reason="Synthetic")
    inv = h.prepared("quality.issue.triage", iid, 1, payload)
    before = dict(h.commands.intents)
    assert_domain("PAYLOAD_DIGEST_MISMATCH", lambda: h.execute(inv, IssueTriage(reason="changed")))
    assert h.commands.intents == before


def test_event_is_server_verified_not_arbitrary_caller_uuid():
    h = Harness()
    run = h.runs.records[uid("run")].run
    payload = IssueCreate(
        run_id=run.id,
        measurement_id=run.measurements[0].id,
        event_id=uid("forged-event"),
        title="Synthetic",
    )
    inv = h.invocation("quality.issue.create", run.id, 0, payload)
    with pytest.raises(Rejection, match="unregistered"):
        h.execute(inv, payload)
    assert h.commands.issues == {} and h.commands.deliveries == {}


def test_one_real_synthetic_event_can_hold_multiple_independent_measurement_failures():
    h = Harness()
    verified = h.runs.records[uid("run")]
    run = verified.run
    pair = replace(run.coverage[0], item_id="other")
    item = replace(run.items[0], id="other")
    m = replace(run.measurements[0], id=uid("second-measurement"), coverage=pair)
    run = replace(
        run,
        items=run.items + (item,),
        coverage=run.coverage + (pair,),
        measurements=run.measurements + (m,),
    )
    computed, result = compute_results(run, run.measurements)
    h.runs.records[run.id] = replace(
        verified, run=replace(run, computed_results=computed, result=result)
    )
    first = h.create().subject_id
    identity = (run.id, m.id, item.criterion.source)
    h.runs.events[uid("delivery")].add(identity)
    payload = IssueCreate(
        run_id=run.id,
        measurement_id=m.id,
        event_id=uid("delivery"),
        title="Synthetic independent failure in same delivery",
    )
    second = h.call("quality.issue.create", run.id, 0, payload).subject_id
    assert first != second
    assert len(h.commands.deliveries) == 2
    assert len(h.commands.issues) == 2


def test_failure_identity_includes_criterion_version_but_not_raw_source_revision():
    run = fixed_run()
    original = failure_ref(VerifiedRun(run=run, nature="synthetic"), run.measurements[0].id)
    changed_source = replace(
        run.measurements[0], source=replace(run.measurements[0].source, revision=2)
    )
    source_run = replace(run, measurements=(changed_source,))
    computed, result = compute_results(source_run, source_run.measurements)
    source_run = replace(source_run, computed_results=computed, result=result)
    corrected = failure_ref(VerifiedRun(run=source_run, nature="synthetic"), changed_source.id)
    assert corrected.identity == original.identity and corrected.source != original.source
    criterion = replace(
        run.items[0].criterion, source=replace(run.items[0].criterion.source, revision=2)
    )
    criterion_run = replace(run, items=(replace(run.items[0], criterion=criterion),))
    other = failure_ref(VerifiedRun(run=criterion_run, nature="synthetic"), run.measurements[0].id)
    assert other.identity != original.identity


def test_source_correction_preserves_old_failure_and_marks_existing_issue_for_recheck():
    h = Harness()
    iid = h.create().subject_id
    original = h.issue(iid)
    verified = h.runs.records[uid("run")]
    m = replace(
        verified.run.measurements[0],
        source=replace(verified.run.measurements[0].source, revision=2),
    )
    new_run = replace(verified.run, revision=2, measurements=(m,))
    computed, result = compute_results(new_run, new_run.measurements)
    h.runs.records[uid("run")] = replace(
        verified, run=replace(new_run, computed_results=computed, result=result)
    )
    h.runs.stale[original.failures[0].source] = ("Original source corrected",)
    second = h.create(event_name="corrected-delivery")
    assert second.subject_id == iid and h.issue(iid).needs_recheck
    assert h.issue(iid).failures == original.failures
    assert h.commands.outbox[-1] == (iid, "issue.recheck_required")
    assert len(h.commands.issues) == 1


def test_duplicate_delivery_does_not_emit_issue_created_again():
    h = Harness()
    iid = h.create().subject_id
    h.create(event_name="redelivery", title="Updated title")
    h.create(event_name="redelivery", title="Another title")
    assert h.commands.outbox == [(iid, "issue.created")]
    assert len(h.issue(iid).history) == 1
    assert len(h.commands.deliveries) == 2


@pytest.mark.parametrize(
    "change",
    [
        {"requirement_digest": "different-CAPA-requirement"},
        {"observed_from": NOW - timedelta(hours=2)},
        {"observed_from": NOW + timedelta(minutes=1)},
    ],
)
def test_effectiveness_evidence_must_follow_completion_and_bind_capa_requirement(change):
    h = Harness()
    iid = h.ready()
    h.policies.evidence[uid("verification")] = replace(
        h.policies.evidence[uid("verification")], **change
    )
    assert_domain(
        "INVALID_VERIFICATION",
        lambda: h.call("quality.capa.effectiveness.decide", iid, h.issue(iid).revision, decide()),
    )


def test_ineffective_then_effective_decisions_preserve_named_history():
    h = Harness()
    iid = h.ready()
    evidence = h.policies.evidence[uid("verification")]
    h.policies.evidence[evidence.id] = replace(evidence, result="fail")
    ineffective_payload = replace(
        decide(), result="ineffective", text="Synthetic ineffective result"
    )
    h.call("quality.capa.effectiveness.decide", iid, h.issue(iid).revision, ineffective_payload)
    ineffective = h.issue(iid).capa.effectiveness
    assert h.issue(iid).status == "awaiting_verification"
    assert_domain(
        "EFFECTIVENESS_REQUIRED",
        lambda: h.call(
            "quality.issue.close", iid, h.issue(iid).revision, IssueClose(text="Synthetic")
        ),
    )
    later = replace(
        evidence,
        id=uid("later-verification"),
        sources=(source("later-result"),),
        run_ids=(uid("later-run"),),
    )
    h.policies.evidence[later.id] = later
    h.call(
        "quality.capa.effectiveness.decide",
        iid,
        h.issue(iid).revision,
        replace(decide(), evidence_ids=(later.id,)),
    )
    capa = h.issue(iid).capa
    assert capa.effectiveness.result == "effective"
    assert capa.effectiveness_history == (ineffective, capa.effectiveness)
    assert ineffective.evidence_ids == (evidence.id,)


@pytest.mark.parametrize("ref_name", ["root", "hypothesis", "containment", "corrective"])
def test_withdrawn_named_or_draft_sources_can_be_rechecked_without_erasing_history(ref_name):
    h = Harness()
    iid = h.ready()
    original = h.issue(iid)
    h.evidence.stale[source(ref_name)] = ("Synthetic evidence withdrawn",)
    assert_domain(
        "RECHECK_REQUIRED",
        lambda: h.call("quality.capa.effectiveness.decide", iid, original.revision, decide()),
    )
    h.call(
        "quality.issue.recheck", iid, original.revision, IssueRecheck(reason="Synthetic withdrawal")
    )
    stale = h.issue(iid)
    assert stale.needs_recheck
    assert stale.root_cause == original.root_cause and stale.capa == original.capa
    assert stale.containment == original.containment


def test_named_t2_requires_common_host_decision_proof():
    h = Harness()
    iid = h.ready()
    inv = h.prepared("quality.capa.effectiveness.decide", iid, h.issue(iid).revision, decide())
    inv = replace(inv, decision_id=None)
    with pytest.raises(Rejection, match="named T2"):
        h.execute(inv, decide())
    assert h.issue(iid).capa.effectiveness is None


def test_reader_uses_archived_fixed_run_and_original_raw_value():
    from pdos_next.domain.quality_issues.read_models import QualityIssueReader

    h = Harness()
    iid = h.create().subject_id
    reading = QualityIssueReader(h.handler.ports).get(iid)
    assert reading.current and reading.failures[0].available
    assert reading.failures[0].measurement.raw_value == "11"
    assert reading.failures[0].failure.run.revision == 1
    assert reading.followup_needs == ()


def test_reader_source_unavailable_returns_reference_without_measurement():
    from pdos_next.domain.quality_issues.read_models import QualityIssueReader

    h = Harness()
    iid = h.create().subject_id
    original = h.issue(iid)
    h.runs.stale[original.failures[0].source] = ("Synthetic source withdrawn",)
    reading = QualityIssueReader(h.handler.ports).get(iid)
    assert not reading.current and not reading.failures[0].available
    assert reading.failures[0].measurement is None
    assert reading.failures[0].failure == original.failures[0]


def test_reader_refuses_current_run_substitution_for_archived_revision():
    from pdos_next.domain.quality_issues.read_models import QualityIssueReader

    h = Harness()
    iid = h.create().subject_id
    verified = h.runs.archives[(uid("run"), 1)]
    h.runs.archives[(uid("run"), 1)] = replace(verified, run=replace(verified.run, revision=2))
    assert_domain("FIXED_REFERENCE_MISMATCH", lambda: QualityIssueReader(h.handler.ports).get(iid))


def test_reader_merge_returns_all_original_rows_and_history():
    from pdos_next.domain.quality_issues.read_models import QualityIssueReader

    h = Harness()
    first, second = two_issues(h)
    payload = IssueMerge(sources=(Ref(id=second, revision=1),), reason="Synthetic")
    h.call("quality.issue.merge", first, 1, payload)
    reading = QualityIssueReader(h.handler.ports).get(first)
    assert reading.originals == (h.issue(second),)
    assert len(reading.failures) == 2
    assert not reading.current
    h.commands.issues[second] = replace(h.issue(second), audience=("private",))
    assert_domain("FORBIDDEN_SCOPE", lambda: QualityIssueReader(h.handler.ports).get(first))


def test_reader_outputs_only_followup_needs_without_creating_external_objects():
    from pdos_next.domain.quality_issues.read_models import QualityIssueReader

    h = Harness()
    iid = h.ready()
    before = list(h.commands.outbox)
    reading = QualityIssueReader(h.handler.ports).get(iid)
    assert {need.kind for need in reading.followup_needs} == {
        "engineering_change_assessment",
        "new_verification_run",
    }
    assert all(need.source_issue.id == iid for need in reading.followup_needs)
    assert h.commands.outbox == before


@pytest.mark.parametrize("fail_at", ["after-facts", "after-inbox", "after-receipt", "after-outbox"])
def test_new_issue_transaction_failure_leaves_zero_partial_side_effects(fail_at):
    h = Harness()
    h.commands.fail_at = fail_at
    with pytest.raises(Rejection, match="injected"):
        h.create()
    for name in ("issues", "failure_map", "deliveries", "intents", "receipts", "audit", "outbox"):
        assert not getattr(h.commands, name)


def test_merge_transaction_failure_restores_canonical_and_alias_facts():
    h = Harness()
    first, second = two_issues(h)
    payload = IssueMerge(sources=(Ref(id=second, revision=1),), reason="Synthetic")
    inv = h.prepared("quality.issue.merge", first, 1, payload)
    original_issues = dict(h.commands.issues)
    original_map = dict(h.commands.failure_map)
    h.commands.fail_at = "after-facts"
    with pytest.raises(Rejection, match="injected"):
        h.execute(inv, payload)
    assert h.commands.issues == original_issues
    assert h.commands.failure_map == original_map
    assert not h.commands.consumed


def test_withdrawn_completion_event_source_requires_recheck_preserves_action_time():
    h = Harness()
    iid = h.ready()
    original = h.issue(iid)
    completion = original.capa.actions[0].completion
    distinct_source = source("action-time-authority")
    completion = replace(completion, at=replace(completion.at, source=distinct_source))
    action = replace(original.capa.actions[0], completion=completion)
    original = replace(original, capa=replace(original.capa, actions=(action,)))
    h.commands.issues[iid] = original
    h.evidence.stale[distinct_source] = ("Action time authority withdrawn",)
    assert_domain(
        "RECHECK_REQUIRED",
        lambda: h.call("quality.capa.effectiveness.decide", iid, original.revision, decide()),
    )
    h.call("quality.issue.recheck", iid, original.revision, IssueRecheck(reason="Synthetic"))
    stale = h.issue(iid)
    assert stale.needs_recheck
    assert stale.capa.actions[0].completion == completion
    assert stale.recheck_reasons == ("Action time authority withdrawn",)


def test_latest_effectiveness_source_withdrawal_retains_historical_closure():
    h = Harness()
    iid = h.ready()
    h.call("quality.capa.effectiveness.decide", iid, h.issue(iid).revision, decide())
    h.call("quality.issue.close", iid, h.issue(iid).revision, IssueClose(text="Synthetic"))
    original = h.issue(iid)
    h.evidence.stale[source("new-run-result")] = ("Latest verification withdrawn",)
    h.call("quality.issue.recheck", iid, original.revision, IssueRecheck(reason="Synthetic"))
    stale = h.issue(iid)
    assert stale.needs_recheck and stale.status == "closed"
    assert stale.closure == original.closure
    assert stale.capa.effectiveness_history == original.capa.effectiveness_history


def test_old_ineffective_evidence_withdrawal_does_not_erase_or_block_latest_decision():
    h = Harness()
    iid = h.ready()
    evidence = h.policies.evidence[uid("verification")]
    h.policies.evidence[evidence.id] = replace(evidence, result="fail")
    h.call(
        "quality.capa.effectiveness.decide",
        iid,
        h.issue(iid).revision,
        replace(decide(), result="ineffective", text="Synthetic prior ineffective result"),
    )
    later = replace(
        evidence,
        id=uid("latest-verification"),
        sources=(source("latest-result"),),
        run_ids=(uid("latest-run"),),
    )
    h.policies.evidence[later.id] = later
    h.call(
        "quality.capa.effectiveness.decide",
        iid,
        h.issue(iid).revision,
        replace(decide(), evidence_ids=(later.id,)),
    )
    history = h.issue(iid).capa.effectiveness_history
    h.evidence.stale[source("new-run-result")] = ("Prior ineffective evidence withdrawn",)
    h.call("quality.issue.close", iid, h.issue(iid).revision, IssueClose(text="Synthetic"))
    assert h.issue(iid).status == "closed"
    assert h.issue(iid).capa.effectiveness_history == history
    assert len(history) == 2


def test_reader_detects_latest_decision_source_withdrawal_before_projection_update():
    from pdos_next.domain.quality_issues.read_models import QualityIssueReader

    h = Harness()
    iid = h.ready()
    h.call("quality.capa.effectiveness.decide", iid, h.issue(iid).revision, decide())
    h.call("quality.issue.close", iid, h.issue(iid).revision, IssueClose(text="Synthetic"))
    original = h.issue(iid)
    h.evidence.stale[source("new-run-result")] = ("Latest verification withdrawn",)
    reading = QualityIssueReader(h.handler.ports).get(iid)
    assert not reading.current
    assert "Latest verification withdrawn" in reading.recheck_reasons
    assert reading.issue == original and not reading.issue.needs_recheck
    assert reading.issue.closure == original.closure
    assert all(f.available for f in reading.failures)
