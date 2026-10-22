"""Synthetic command consumers; actual locks/proofs/rollback remain host acceptance."""

import pytest

from pdos_next.domain.verification.handlers import VerificationHandler, semantic_digest
from pdos_next.domain.verification.ports import Invocation, Ports, SampleAvailability
from pdos_next.error_catalog import REASONS
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import (
    Acceptance,
    ConfigurationRef,
    Coverage,
    HandoffAccept,
    HandoffOffer,
    HandoffReturn,
    MethodPrepare,
    RequestCreate,
    ResultsSubmit,
    RunDisposition,
    RunPlan,
    RunReview,
    RunStart,
    SchedulePromise,
    ScheduleProposal,
)

from .helpers import (
    HostRejection,
    build,
    coverage,
    document,
    event,
    execution,
    fact,
    item,
    measurement,
    request,
    run,
    sample,
    source,
    uid,
)


def invocation(operation, subject, revision, payload, *, command="command"):
    return Invocation(
        command_id=uid(command),
        operation=operation,
        subject_id=subject,
        expected_revision=revision,
        semantic_digest=semantic_digest(payload),
    )


def prepared(host, operation, subject, revision, payload, *, command="command"):
    handler = VerificationHandler(host)
    preview = handler.preview(operation, subject, revision, payload)
    command = invocation(operation, subject, revision, payload, command=command)
    token = host.commands.issue_proof(command, preview)
    return command.model_copy(update={"confirmation_token": token}), preview


def perform(host, operation, subject, revision, payload, *, command="command", t2=False):
    command, _ = prepared(host, operation, subject, revision, payload, command=command)
    if t2:
        command = command.model_copy(update={"decision_id": uid(f"decision-{operation}")})
    return VerificationHandler(host).execute(command, payload)


def offered(host, *, partial=False, items=None, documents=None):
    refs = (sample(), sample("sample-b", "B"))
    current = request(
        status="offered",
        samples=refs,
        offered_coverage=coverage(samples=refs),
        timeline=request().timeline.model_copy(
            update={
                "offered": fact("offered", offset=0),
                "sample_ready": fact("ready", offset=-5),
            }
        ),
        **({"items": items} if items else {}),
        **({"documents": documents} if documents is not None else {}),
    )
    host.commands.requests[current.id] = current
    selected = current.offered_coverage[:1] if partial else current.offered_coverage
    return current, HandoffAccept(
        coverage=selected,
        reason="B模穴待补" if partial else None,
        next_owner_id=uid("production-owner") if partial else None,
        at=event("accepted", offset=5),
    )


def accepted(host, *, partial=False, destructive=False):
    current, payload = offered(host, partial=partial, items=(item(destructive=destructive),))
    perform(
        host, "verification.handoff.accept", current.id, current.revision, payload, command="accept"
    )
    return host.commands.requests[current.id]


def planned(host, *, partial=False, destructive=False):
    current = accepted(host, partial=partial, destructive=destructive)
    selected = current.acceptances[0].coverage
    payload = RunPlan(run_id=uid("new-run"), coverage=selected)
    perform(host, "test.run.plan", current.id, current.revision, payload, command="plan")
    return host.commands.run_records[payload.run_id]


def running(host, *, partial=False, destructive=False):
    current = planned(host, partial=partial, destructive=destructive)
    payload = RunStart(at=event("start", offset=10), execution=execution())
    perform(host, "test.run.start", current.id, current.revision, payload, command="start")
    return host.commands.run_records[current.id]


def full_final(current, **changes):
    readings = tuple(measurement(f"m-{i}", pair=p) for i, p in enumerate(current.coverage))
    data = dict(
        measurements=readings,
        final=True,
        at=event("results", offset=30),
        actual_end=event("end", offset=27),
    )
    data.update(changes)
    return ResultsSubmit(**data)


def test_planned_build_allows_request_with_method_unknown_and_no_sample_fact(host):
    host.builds.current = host.builds.current.model_copy(update={"status": "planned"})
    payload = RequestCreate(
        request_id=uid("new-request"),
        build_id=build().id,
        expected_build_revision=1,
        title="试模前准备",
        purpose="合成验证",
        items=(item(method=None),),
        return_form="读数表",
    )
    handler = VerificationHandler(host)
    preview = handler.preview("verification.request.create", payload.request_id, 0, payload)
    assert preview.allowed and preview.gaps
    command = invocation("verification.request.create", payload.request_id, 0, payload)
    result = handler.execute(command, payload)
    current = host.commands.requests[payload.request_id]
    assert result.status == "draft" and current.samples == ()
    assert current.timeline.sample_ready is None and current.timeline.accepted is None
    assert current.timeline.actual_start is None and not host.commands.confirmations


def test_request_create_rechecks_build_revision(host):
    payload = RequestCreate(
        request_id=uid("new-request"),
        build_id=build().id,
        expected_build_revision=2,
        title="合成验证",
        purpose="尺寸",
        items=(item(),),
        return_form="读数表",
    )
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).preview(
            "verification.request.create", payload.request_id, 0, payload
        )
    assert rejected.value.code == "VERSION_CONFLICT" and not host.commands.records


def test_early_method_preparation_keeps_tentative_promise_and_actual_separate(host):
    host.builds.current = host.builds.current.model_copy(update={"status": "planned"})
    payload = MethodPrepare(
        items=(item(),), documents=(document(),), tentative_start=event("tentative", offset=500)
    )
    perform(host, "verification.method.prepare", uid("request"), 1, payload)
    current = host.commands.requests[uid("request")]
    assert current.status == "draft" and current.tentative_start == payload.tentative_start
    assert current.timeline.documents_complete is not None
    assert current.timeline.promised_start is None and current.timeline.accepted is None
    assert current.timeline.sample_ready is None and current.timeline.actual_start is None


def test_preview_does_not_consume_proof_intent_or_create_reservation(host):
    current = accepted(host)
    host.commands.records.clear()
    host.commands.command_intents.clear()
    host.commands.confirmations.clear()
    before = host.commands.requests[current.id]
    payload = RunPlan(run_id=uid("readonly-plan"), coverage=coverage())
    preview = VerificationHandler(host).preview(
        "test.run.plan", current.id, current.revision, payload
    )
    assert preview.allowed and before == host.commands.requests[current.id]
    assert not host.commands.records and not host.commands.command_intents
    assert not host.commands.confirmations and not host.samples.reservations
    assert payload.run_id not in host.commands.run_records


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"authorized": False}, "FORBIDDEN_OPERATION"),
        ({"roles": ("project",)}, "FORBIDDEN_OPERATION"),
        ({"cancelled": True}, "RUN_CANCELLED"),
        ({"actor_kind": "ai"}, "NAMED_DECISION_REQUIRED"),
    ],
)
def test_current_server_authority_refuses_method_action(host, changes, code):
    host.commands.authority = host.commands.authority.model_copy(update=changes)
    payload = MethodPrepare(items=(item(),))
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).preview("verification.method.prepare", uid("request"), 1, payload)
    assert rejected.value.reason == code and not host.commands.records
    assert rejected.value.code == REASONS[code]


def test_ai_request_creation_requires_current_qualification(host):
    host.commands.authority = host.commands.authority.model_copy(
        update={"actor_kind": "ai", "qualified": False},
    )
    payload = RequestCreate(
        request_id=uid("new-request"),
        build_id=build().id,
        expected_build_revision=1,
        title="合成请求",
        purpose="尺寸",
        items=(item(),),
        return_form="读数",
    )
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).preview(
            "verification.request.create", payload.request_id, 0, payload
        )
    assert rejected.value.code == "QUALIFICATION_REQUIRED"


@pytest.mark.parametrize("port_name", ["commands", "builds", "evidence", "samples"])
def test_missing_required_port_explicitly_blocks_success(host, port_name):
    payload = HandoffOffer(samples=(sample(),), coverage=coverage()[:1], at=event("offered"))
    setattr(host, port_name, None)
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).preview("verification.handoff.offer", uid("request"), 1, payload)
    assert rejected.value.reason == "INTEGRATION_REQUIRED"
    assert rejected.value.code == REASONS["INTEGRATION_REQUIRED"]


def test_unknown_operation_or_mismatched_payload_is_rejected_before_begin(host):
    payload = MethodPrepare(items=(item(),))
    for operation in ("test.run.start", "verification.uncontrolled.write"):
        command = invocation(operation, uid("request"), 1, payload)
        with pytest.raises(DomainError) as rejected:
            VerificationHandler(host).execute(command, payload)
        assert rejected.value.reason == "INVALID_OPERATION_PAYLOAD"
        assert rejected.value.code == REASONS["INVALID_OPERATION_PAYLOAD"]
    assert not host.commands.command_intents


def test_offer_keeps_missing_documents_and_sample_readiness_separate(host):
    host.commands.requests[uid("request")] = request(documents=(document(present=False),))
    host.samples.unavailable.add(sample().id)
    payload = HandoffOffer(samples=(sample(),), coverage=coverage()[:1], at=event("offered"))
    command, preview = prepared(host, "verification.handoff.offer", uid("request"), 1, payload)
    assert preview.allowed and {g.code for g in preview.gaps} == {
        "DOCUMENT_MISSING",
        "SAMPLE_UNAVAILABLE",
    }
    VerificationHandler(host).execute(command, payload)
    current = host.commands.requests[uid("request")]
    assert current.status == "offered" and current.timeline.offered is not None
    assert current.timeline.documents_complete is None
    assert current.timeline.sample_ready.occurred_at == event("sample-ready", offset=-5).occurred_at
    assert not current.acceptances and current.timeline.accepted is None


def test_partial_acceptance_preserves_precise_pairs_reason_and_next_owner(host):
    current, payload = offered(host, partial=True)
    perform(host, "verification.handoff.accept", current.id, current.revision, payload)
    saved = host.commands.requests[current.id]
    assert saved.acceptances[0].coverage == payload.coverage
    assert saved.returns[0].coverage == current.offered_coverage[1:]
    assert saved.returns[0].reason == payload.reason
    assert saved.returns[0].next_owner_id == payload.next_owner_id
    assert saved.timeline.accepted.actor_id == host.commands.authority.actor_id


@pytest.mark.parametrize("changes", [{"reason": None}, {"next_owner_id": None}])
def test_partial_acceptance_requires_return_reason_and_next_responsibility(host, changes):
    current, payload = offered(host, partial=True)
    payload = payload.model_copy(update=changes)
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).preview(
            "verification.handoff.accept", current.id, current.revision, payload
        )
    assert rejected.value.reason == "PARTIAL_RESPONSIBILITY_REQUIRED"
    assert rejected.value.code == REASONS["PARTIAL_RESPONSIBILITY_REQUIRED"]
    assert not host.commands.records


def test_missing_document_for_other_item_does_not_block_selected_item(host):
    refs = (sample(), sample("sample-b", "B"))
    selected = coverage(samples=refs)
    other = Coverage(sample_id=refs[0].id, item_id="pressure")
    current, _ = offered(
        host,
        items=(item(), item("pressure", sample_count=1, cavities=("A",))),
        documents=(document("pressure-only", items=("pressure",), present=False),),
    )
    current = current.model_copy(update={"offered_coverage": selected + (other,)})
    host.commands.requests[current.id] = current
    payload = HandoffAccept(
        coverage=selected,
        returned_coverage=(other,),
        reason="压力规程待补",
        next_owner_id=uid("method-owner"),
        at=event("accepted", offset=5),
    )
    _, preview = prepared(host, "verification.handoff.accept", current.id, 1, payload)
    assert preview.allowed and not preview.gaps
    perform(host, "verification.handoff.accept", current.id, 1, payload)
    saved = host.commands.requests[current.id]
    assert saved.acceptances[0].coverage == selected
    assert saved.returns[0].gaps[0].item_id == "pressure"


def test_missing_document_for_selected_item_prevents_acceptance_record(host):
    current, payload = offered(host, documents=(document(present=False),))
    command, preview = prepared(host, "verification.handoff.accept", current.id, 1, payload)
    assert not preview.allowed
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).execute(command, payload)
    assert rejected.value.code == "MISSING_REQUIRED_EVIDENCE"
    assert not host.commands.records and not host.commands.confirmations


@pytest.mark.parametrize("state", ["planned", "draft", "preparing", "authorized", "unknown"])
def test_plan_or_authorization_is_not_actual_sample_proof_at_acceptance(host, state):
    current, payload = offered(host)
    host.builds.current = host.builds.current.model_copy(update={"status": state})
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).preview("verification.handoff.accept", current.id, 1, payload)
    assert rejected.value.reason == "ACTUAL_SAMPLE_REQUIRED" and not host.commands.records
    assert rejected.value.code == REASONS["ACTUAL_SAMPLE_REQUIRED"]


@pytest.mark.parametrize("condition", ["unavailable", "inapplicable"])
def test_sample_availability_and_applicability_are_rechecked_on_acceptance(host, condition):
    current, payload = offered(host)
    getattr(host.samples, condition).add(sample().id)
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).preview("verification.handoff.accept", current.id, 1, payload)
    assert rejected.value.reason == "SAMPLE_UNAVAILABLE" and not host.commands.records
    assert rejected.value.code == REASONS["SAMPLE_UNAVAILABLE"]


def test_returning_defect_records_owner_without_creating_acceptance(host):
    current, _ = offered(host)
    payload = HandoffReturn(
        coverage=coverage()[:1],
        reason="原件待补",
        next_owner_id=uid("document-owner"),
        at=event("returned", offset=5),
    )
    perform(host, "verification.handoff.return", current.id, 1, payload)
    saved = host.commands.requests[current.id]
    assert saved.status == "offered" and not saved.acceptances
    assert saved.timeline.accepted is None
    assert saved.returns[0].next_owner_id == payload.next_owner_id


def test_repeated_acceptance_under_new_intent_cannot_duplicate_business_scope(host):
    current = accepted(host)
    payload = HandoffAccept(coverage=coverage(), at=event("accept-again", offset=7))
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).preview(
            "verification.handoff.accept", current.id, current.revision, payload
        )
    assert rejected.value.reason == "ALREADY_ACCEPTED"
    assert rejected.value.code == REASONS["ALREADY_ACCEPTED"]
    assert len(host.commands.records) == 1


def test_promised_start_can_be_future_and_does_not_start_run(host):
    fixed_run = planned(host)
    current = host.commands.requests[fixed_run.request_id]
    payload = SchedulePromise(
        run_id=fixed_run.id,
        expected_run_revision=fixed_run.revision,
        at=event("promise", offset=500),
    )
    perform(
        host,
        "verification.schedule.promise",
        current.id,
        current.revision,
        payload,
        command="promise",
    )
    saved = host.commands.requests[current.id]
    assert saved.status == "scheduled" and saved.timeline.promised_start.occurred_at == (
        payload.at.occurred_at
    )
    assert saved.timeline.actual_start is None and not host.samples.reservations


def test_run_cannot_be_planned_over_unaccepted_pairs(host):
    current = accepted(host, partial=True)
    payload = RunPlan(run_id=uid("new-run"), coverage=coverage())
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).preview("test.run.plan", current.id, current.revision, payload)
    assert rejected.value.reason == "INVALID_COVERAGE"
    assert rejected.value.code == REASONS["INVALID_COVERAGE"]


def test_start_requires_current_person_executor_and_no_side_effect_on_mismatch(host):
    current = planned(host)
    payload = RunStart(
        at=event("start", offset=10),
        execution=execution().model_copy(
            update={"executor_id": uid("other-person")},
        ),
    )
    before = len(host.commands.records)
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).preview("test.run.start", current.id, 1, payload)
    assert rejected.value.code == "NAMED_DECISION_REQUIRED"
    assert len(host.commands.records) == before and not host.samples.reservations


def test_start_rejects_actual_configuration_changed_after_plan(host):
    current = planned(host)
    host.samples.current[sample().id] = sample(
        actual_configuration=ConfigurationRef(
            id=uid("actual-other"),
            revision=2,
        )
    )
    payload = RunStart(at=event("start", offset=10), execution=execution())
    before = len(host.commands.records)
    with pytest.raises(HostRejection):
        VerificationHandler(host).preview("test.run.start", current.id, 1, payload)
    assert len(host.commands.records) == before and not host.samples.reservations


def test_handler_rejects_port_returning_a_different_actual_configuration(host):
    current = planned(host)
    original = host.samples.inspect

    def changed(bound_scope, ref, purpose):
        state = original(bound_scope, ref, purpose)
        return SampleAvailability(
            **{
                **state.model_dump(),
                "sample": ref.model_copy(
                    update={"revision": ref.revision + 1},
                ),
            }
        )

    host.samples.inspect = changed
    payload = RunStart(at=event("start", offset=10), execution=execution())
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).preview("test.run.start", current.id, 1, payload)
    assert rejected.value.reason == "SOURCE_CHANGED" and not host.samples.reservations
    assert rejected.value.code == REASONS["SOURCE_CHANGED"]


def test_destructive_start_sends_exact_coverage_once_to_controlled_reservation(host):
    current = running(host, destructive=True)
    assert current.status == "running" and current.result == "pending"
    assert len(host.samples.reservations) == 1
    reservation = host.samples.reservations[0]
    assert reservation[0] == current.id and reservation[3] == current.coverage
    assert current.actual_start.actor_id == host.commands.authority.actor_id


def test_two_destructive_items_cannot_consume_same_sample(host):
    ref = sample()
    selected = (
        Coverage(sample_id=ref.id, item_id="dimension"),
        Coverage(sample_id=ref.id, item_id="pressure"),
    )
    accepted_fact = fact("accepted", offset=5)
    items = (item(destructive=True), item("pressure", destructive=True))
    current_request = request(
        status="accepted",
        samples=(ref,),
        items=items,
        offered_coverage=selected,
        acceptances=(Acceptance(coverage=selected, actor_id=uid("actor"), at=accepted_fact),),
        timeline=request().timeline.model_copy(update={"accepted": accepted_fact}),
    )
    current_run = run(samples=(ref,), items=items, coverage=selected)
    host.commands.requests[current_request.id] = current_request
    host.commands.run_records[current_run.id] = current_run
    payload = RunStart(at=event("start", offset=10), execution=execution())
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).preview("test.run.start", current_run.id, 1, payload)
    assert rejected.value.reason == "DESTRUCTIVE_CONFLICT" and not host.samples.reservations
    assert rejected.value.code == REASONS["DESTRUCTIVE_CONFLICT"]


def test_reservation_port_failure_prevents_recording_started_fact(host):
    current = planned(host)
    payload = RunStart(at=event("start", offset=10), execution=execution())
    command, _ = prepared(host, "test.run.start", current.id, 1, payload)
    host.samples.reject_reserve = True
    before = len(host.commands.records)
    with pytest.raises(HostRejection):
        VerificationHandler(host).execute(command, payload)
    assert len(host.commands.records) == before
    assert host.commands.run_records[current.id].status == "planned"


def test_partial_run_final_pass_leaves_whole_request_unreported(host):
    current = running(host, partial=True)
    payload = full_final(current)
    perform(host, "test.results.import", current.id, current.revision, payload, command="final")
    saved_run = host.commands.run_records[current.id]
    saved_request = host.commands.requests[current.request_id]
    assert saved_run.status == "results_pending" and saved_run.result == "pass"
    assert saved_request.status == "executing" and saved_request.timeline.final_result is None
    assert saved_request.returns[0].gaps


def test_full_request_and_run_have_separate_clocks_and_final_state(host):
    current = running(host)
    payload = full_final(current)
    perform(host, "test.results.import", current.id, current.revision, payload, command="final")
    saved = host.commands.run_records[current.id]
    aggregate = host.commands.requests[current.request_id]
    assert saved.result == "pass" and saved.status == "results_pending"
    assert aggregate.status == "reported" and aggregate.timeline.final_result is not None
    assert saved.actual_end.occurred_at == payload.actual_end.occurred_at
    assert saved.final_result.received_at == host.commands.authority.now
    assert saved.final_result.occurred_at != saved.final_result.received_at


def test_partial_results_keep_run_running_and_unreturned_pair_unknown(host):
    current = running(host)
    payload = ResultsSubmit(
        measurements=(measurement(pair=current.coverage[0]),), at=event("partial", offset=30)
    )
    perform(host, "test.results.import", current.id, current.revision, payload, command="partial")
    saved = host.commands.run_records[current.id]
    assert saved.status == "running" and saved.result == "indeterminate"
    assert len(saved.measurements) == 1 and saved.final_result is None and saved.actual_end is None
    assert saved.preliminary_result is not None


def test_final_unknown_reading_is_recorded_without_becoming_pass(host):
    current = running(host)
    readings = tuple(
        measurement(f"m-{i}", pair=p, raw=None) for i, p in enumerate(current.coverage)
    )
    payload = full_final(current, measurements=readings)
    perform(host, "test.results.import", current.id, current.revision, payload, command="final")
    saved = host.commands.run_records[current.id]
    assert saved.status == "results_pending" and saved.result == "indeterminate"
    assert all(m.raw_value is None for m in saved.measurements)


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"actual_end": None}, "ACTUAL_END_REQUIRED"),
        ({"measurements": (measurement(),)}, "INCOMPLETE_FINAL_SCOPE"),
        ({"actual_end": event("too-early", offset=20)}, "INVALID_EVENT_TIME"),
    ],
)
def test_final_result_requires_whole_run_measurement_scope_and_actual_end(host, changes, code):
    current = running(host)
    payload = full_final(current, **changes)
    before = len(host.commands.records)
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).preview(
            "test.results.import", current.id, current.revision, payload
        )
    assert rejected.value.reason == code and len(host.commands.records) == before
    assert rejected.value.code == REASONS[code]


def test_result_configuration_drift_host_refusal_records_no_success(host):
    current = running(host)
    payload = full_final(current)
    command, _ = prepared(host, "test.results.import", current.id, current.revision, payload)
    host.samples.reject_running = True
    before = len(host.commands.records)
    with pytest.raises(HostRejection):
        VerificationHandler(host).execute(command, payload)
    assert len(host.commands.records) == before
    assert host.commands.run_records[current.id].measurements == ()


def test_raw_measurement_cannot_be_overwritten_by_later_partial_import(host):
    current = running(host)
    first = ResultsSubmit(measurements=(measurement(),), at=event("partial", offset=30))
    perform(host, "test.results.import", current.id, current.revision, first, command="partial")
    current = host.commands.run_records[current.id]
    changed = ResultsSubmit(measurements=(measurement(raw="9"),), at=event("correction", offset=35))
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).preview(
            "test.results.import", current.id, current.revision, changed
        )
    assert rejected.value.reason == "MEASUREMENT_ALREADY_RECORDED"
    assert rejected.value.code == REASONS["MEASUREMENT_ALREADY_RECORDED"]
    assert current.measurements[0].raw_value == "10.000"


def test_source_revocation_after_preview_prevents_measurement_record(host):
    current = running(host)
    payload = full_final(current)
    command, _ = prepared(host, "test.results.import", current.id, current.revision, payload)
    host.evidence.rejected.add(payload.measurements[0].source.id)
    before = len(host.commands.records)
    with pytest.raises(HostRejection):
        VerificationHandler(host).execute(command, payload)
    assert len(host.commands.records) == before


def test_build_drift_after_preview_prevents_acceptance_record(host):
    current, payload = offered(host)
    command, _ = prepared(host, "verification.handoff.accept", current.id, 1, payload)
    host.builds.current = host.builds.current.model_copy(
        update={
            "ref": build().model_copy(
                update={"revision": 2},
            )
        }
    )
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).execute(command, payload)
    assert rejected.value.reason == "SOURCE_CHANGED" and not host.commands.records
    assert rejected.value.code == REASONS["SOURCE_CHANGED"]


@pytest.mark.parametrize("operation", ["test.run.review", "test.disposition.decide"])
def test_ai_cannot_execute_named_quality_decision(host, operation):
    host.commands.authority = host.commands.authority.model_copy(update={"actor_kind": "ai"})
    payload_cls = RunReview if operation == "test.run.review" else RunDisposition
    payload = payload_cls(text="合成专业结论", at=event("decision", offset=50))
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).preview(operation, uid("run"), 1, payload)
    assert rejected.value.code == "NAMED_DECISION_REQUIRED" and not host.commands.records


def test_review_and_disposition_preserve_computed_result_and_named_actor(host):
    current = running(host)
    final = full_final(current)
    perform(host, "test.results.import", current.id, current.revision, final, command="final")
    current = host.commands.run_records[current.id]
    review = RunReview(text="当前固定范围满足尺寸判据", at=event("review", offset=40))
    command, _ = prepared(
        host, "test.run.review", current.id, current.revision, review, command="review"
    )
    before = len(host.commands.records)
    with pytest.raises(HostRejection):
        VerificationHandler(host).execute(command, review)
    assert len(host.commands.records) == before
    perform(
        host,
        "test.run.review",
        current.id,
        current.revision,
        review,
        command="named-review",
        t2=True,
    )
    reviewed = host.commands.run_records[current.id]
    assert reviewed.status == "reviewed" and reviewed.result == "pass"
    assert reviewed.professional_conclusion.actor_id == host.commands.authority.actor_id
    decision = RunDisposition(text="合成处置：留存样件", at=event("dispose", offset=50))
    perform(
        host,
        "test.disposition.decide",
        reviewed.id,
        reviewed.revision,
        decision,
        command="dispose",
        t2=True,
    )
    disposed = host.commands.run_records[reviewed.id]
    assert disposed.status == "disposed" and disposed.result == "pass"
    assert host.commands.requests[disposed.request_id].status == "disposed"


def test_stable_repeat_with_new_command_id_has_no_second_record_or_consumption(host):
    current = planned(host, destructive=True)
    payload = RunStart(at=event("start", offset=10), execution=execution())
    command, _ = prepared(host, "test.run.start", current.id, 1, payload, command="start-one")
    first = VerificationHandler(host).execute(command, payload)
    before = len(host.commands.records)
    repeat = command.model_copy(update={"command_id": uid("start-two")})
    replay = VerificationHandler(host).execute(repeat, payload)
    assert replay.replayed and replay.revision == first.revision
    assert len(host.commands.records) == before and len(host.samples.reservations) == 1


def test_replay_host_reauthorizes_current_audience(host):
    current = planned(host)
    payload = RunStart(at=event("start", offset=10), execution=execution())
    command, _ = prepared(host, "test.run.start", current.id, 1, payload)
    VerificationHandler(host).execute(command, payload)
    host.commands.authority = host.commands.authority.model_copy(update={"authorized": False})
    before = len(host.commands.records)
    with pytest.raises(HostRejection):
        VerificationHandler(host).execute(command, payload)
    assert len(host.commands.records) == before


def test_same_command_key_changed_payload_is_refused_by_host(host):
    payload = MethodPrepare(items=(item(),))
    command, _ = prepared(host, "verification.method.prepare", uid("request"), 1, payload)
    VerificationHandler(host).execute(command, payload)
    changed = MethodPrepare(items=(item(conditions="80 °C"),))
    conflict = invocation("verification.method.prepare", uid("request"), 1, changed)
    with pytest.raises(HostRejection):
        VerificationHandler(host).execute(conflict, changed)
    assert len(host.commands.records) == 1


def test_wrong_semantic_digest_is_refused_before_begin(host):
    payload = MethodPrepare(items=(item(),))
    command = invocation("verification.method.prepare", uid("request"), 1, payload)
    command = command.model_copy(update={"semantic_digest": "f" * 64})
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).execute(command, payload)
    assert rejected.value.reason == "INTENT_CONFLICT" and not host.commands.command_intents
    assert rejected.value.code == REASONS["INTENT_CONFLICT"]


def test_one_confirmation_is_bound_to_actor_and_current_preview(host):
    payload = MethodPrepare(items=(item(),))
    command, _ = prepared(host, "verification.method.prepare", uid("request"), 1, payload)
    host.commands.authority = host.commands.authority.model_copy(
        update={"actor_id": uid("new-actor")},
    )
    with pytest.raises(HostRejection):
        VerificationHandler(host).execute(command, payload)
    assert not host.commands.records


def test_expired_confirmation_host_refusal_prevents_record(host):
    payload = MethodPrepare(items=(item(),))
    command, _ = prepared(host, "verification.method.prepare", uid("request"), 1, payload)
    host.commands.reject_confirmation = True
    with pytest.raises(HostRejection):
        VerificationHandler(host).execute(command, payload)
    assert not host.commands.records


def test_semantic_digest_uses_exact_scope_but_canonical_selection_order():
    refs = (sample(), sample("sample-b", "B"))
    payload = HandoffOffer(samples=refs, coverage=coverage(), at=event("offered"))
    reordered = payload.model_copy(update={"samples": refs[::-1], "coverage": coverage()[::-1]})
    assert semantic_digest(payload) == semantic_digest(reordered)
    changed = payload.model_copy(update={"coverage": coverage()[:1]})
    assert semantic_digest(payload) != semantic_digest(changed)


def test_default_ports_never_imply_an_enabled_handler():
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(Ports()).preview(
            "verification.method.prepare", uid("request"), 1, MethodPrepare(items=(item(),))
        )
    assert rejected.value.reason == "INTEGRATION_REQUIRED"
    assert rejected.value.code == REASONS["INTEGRATION_REQUIRED"]


def test_human_quality_action_requires_current_operation_qualification(host):
    host.commands.authority = host.commands.authority.model_copy(update={"qualified": False})
    payload = MethodPrepare(items=(item(),))
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).preview("verification.method.prepare", uid("request"), 1, payload)
    assert rejected.value.code == "QUALIFICATION_REQUIRED" and not host.commands.records


def test_planned_build_cannot_offer_fictitious_sample_even_when_payload_has_sample_ref(host):
    host.builds.current = host.builds.current.model_copy(update={"status": "planned"})
    payload = HandoffOffer(samples=(sample(),), coverage=coverage()[:1], at=event("offered"))
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).preview("verification.handoff.offer", uid("request"), 1, payload)
    assert rejected.value.reason == "ACTUAL_SAMPLE_REQUIRED" and not host.commands.records
    assert rejected.value.code == REASONS["ACTUAL_SAMPLE_REQUIRED"]


def test_cumulative_second_acceptance_needs_no_new_partial_reason_or_empty_return(host):
    current = accepted(host, partial=True)
    payload = HandoffAccept(coverage=coverage()[1:], at=event("accept-remainder", offset=30))
    perform(
        host,
        "verification.handoff.accept",
        current.id,
        current.revision,
        payload,
        command="accept-remainder",
    )
    saved = host.commands.requests[current.id]
    assert len(saved.acceptances) == 2 and len(saved.returns) == 1
    assert saved.acceptances[-1].coverage == coverage()[1:]


def test_start_cannot_precede_acceptance_of_its_specific_sample_pair(host):
    current = accepted(host, partial=True)
    payload = HandoffAccept(coverage=coverage()[1:], at=event("accept-remainder", offset=30))
    perform(
        host,
        "verification.handoff.accept",
        current.id,
        current.revision,
        payload,
        command="accept-remainder",
    )
    current = host.commands.requests[current.id]
    plan = RunPlan(run_id=uid("second-run"), coverage=coverage()[1:])
    perform(host, "test.run.plan", current.id, current.revision, plan, command="second-plan")
    start = RunStart(at=event("premature-start", offset=20), execution=execution())
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).preview("test.run.start", plan.run_id, 1, start)
    assert rejected.value.reason == "INVALID_EVENT_TIME" and not host.samples.reservations
    assert rejected.value.code == REASONS["INVALID_EVENT_TIME"]


def test_acceptance_cannot_precede_current_selected_sample_ready_time(host):
    current, _ = offered(host)
    original = host.samples.inspect

    def late_ready(bound_scope, ref, purpose):
        state = original(bound_scope, ref, purpose)
        return state.model_copy(update={"ready_at": event("late-ready", offset=4)})

    host.samples.inspect = late_ready
    payload = HandoffAccept(coverage=coverage(), at=event("premature-accept", offset=2))
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).preview("verification.handoff.accept", current.id, 1, payload)
    assert rejected.value.reason == "INVALID_EVENT_TIME" and not host.commands.records
    assert rejected.value.code == REASONS["INVALID_EVENT_TIME"]


def test_drift_of_unselected_sample_does_not_block_applicable_partial_acceptance(host):
    current, payload = offered(host, partial=True)
    host.samples.current[sample("sample-b", "B").id] = sample("sample-b", "B", revision=2)
    perform(host, "verification.handoff.accept", current.id, 1, payload)
    saved = host.commands.requests[current.id]
    assert saved.acceptances[0].coverage == coverage()[:1]


def test_later_remainder_acceptance_preserves_prior_sample_ready_fact_after_consumption(host):
    current = accepted(host, partial=True)
    prior = current.timeline.sample_ready
    host.samples.unavailable.add(sample().id)
    payload = HandoffAccept(coverage=coverage()[1:], at=event("accept-remainder", offset=30))
    perform(
        host,
        "verification.handoff.accept",
        current.id,
        current.revision,
        payload,
        command="accept-remainder",
    )
    saved = host.commands.requests[current.id]
    assert saved.timeline.sample_ready == prior
    assert len(saved.acceptances) == 2


def test_complete_partial_measurements_can_finalize_without_resubmitting_raw_values(host):
    current = running(host)
    readings = full_final(current).measurements
    partial = ResultsSubmit(measurements=readings, at=event("partial", offset=30))
    perform(host, "test.results.import", current.id, current.revision, partial, command="partial")
    current = host.commands.run_records[current.id]
    host.evidence.measurement_calls.clear()
    final = ResultsSubmit(
        measurements=(),
        at=event("final", offset=40),
        final=True,
        actual_end=event("end", offset=27),
    )
    perform(host, "test.results.import", current.id, current.revision, final, command="empty-final")
    saved = host.commands.run_records[current.id]
    assert saved.measurements == readings and saved.result == "pass"
    assert saved.preliminary_result.occurred_at == partial.at.occurred_at
    assert saved.final_result.occurred_at == final.at.occurred_at
    assert {m.id for _, m, _ in host.evidence.measurement_calls} == {m.id for m in readings}
    assert all(run_id == current.id for _, _, run_id in host.evidence.measurement_calls)


def test_prior_partial_source_revocation_blocks_empty_final_success(host):
    current = running(host)
    readings = full_final(current).measurements
    partial = ResultsSubmit(measurements=readings, at=event("partial", offset=30))
    perform(host, "test.results.import", current.id, current.revision, partial, command="partial")
    current = host.commands.run_records[current.id]
    host.evidence.rejected.add(current.measurements[0].source.id)
    final = ResultsSubmit(
        measurements=(),
        at=event("final", offset=40),
        final=True,
        actual_end=event("end", offset=27),
    )
    before = len(host.commands.records)
    with pytest.raises(HostRejection):
        VerificationHandler(host).preview(
            "test.results.import", current.id, current.revision, final
        )
    assert len(host.commands.records) == before and current.final_result is None


def test_fixed_run_methods_cannot_drift_to_current_request_methods(host):
    current = running(host)
    parent = host.commands.requests[current.request_id]
    host.commands.requests[parent.id] = parent.model_copy(
        update={
            "items": (item(conditions="80 °C"),),
        }
    )
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).preview(
            "test.results.import", current.id, current.revision, full_final(current)
        )
    assert rejected.value.reason == "SOURCE_CHANGED"
    assert rejected.value.code == REASONS["SOURCE_CHANGED"]


def test_run_action_mutation_binds_both_aggregate_cas_versions(host):
    current = planned(host)
    parent = host.commands.requests[current.request_id]
    payload = RunStart(at=event("start", offset=10), execution=execution())
    perform(host, "test.run.start", current.id, current.revision, payload, command="start")
    mutation = host.commands.records[-1]
    assert mutation.request_before_revision == parent.revision
    assert mutation.run_before_revision == current.revision
    assert mutation.request.revision == parent.revision + 1
    assert mutation.run.revision == current.revision + 1
    assert mutation.events[0].subject_id == mutation.run.id


def test_host_cas_refuses_overwriting_existing_request_identity(host):
    payload = RequestCreate(
        request_id=uid("request"),
        build_id=build().id,
        expected_build_revision=1,
        title="冲突合成请求",
        purpose="尺寸",
        items=(item(),),
        return_form="读数",
    )
    command = invocation("verification.request.create", payload.request_id, 0, payload)
    with pytest.raises(HostRejection):
        VerificationHandler(host).execute(command, payload)
    assert not host.commands.records and host.commands.requests[payload.request_id].revision == 1


def test_request_version_change_after_run_preview_invalidates_confirmation(host):
    current = planned(host)
    payload = RunStart(at=event("start", offset=10), execution=execution())
    command, _ = prepared(host, "test.run.start", current.id, 1, payload)
    parent = host.commands.requests[current.request_id]
    host.commands.requests[parent.id] = parent.model_copy(update={"revision": parent.revision + 1})
    before = len(host.commands.records)
    with pytest.raises(HostRejection):
        VerificationHandler(host).execute(command, payload)
    assert len(host.commands.records) == before and not host.samples.reservations


def test_tentative_schedule_proposal_can_prepare_planned_build_without_sample_port(host):
    host.builds.current = host.builds.current.model_copy(update={"status": "planned"})
    host.commands.authority = host.commands.authority.model_copy(update={"actor_kind": "ai"})
    host.samples = None
    payload = ScheduleProposal(at=event("tentative", offset=500))
    command = invocation("verification.schedule.propose", uid("request"), 1, payload)
    VerificationHandler(host).execute(command, payload)
    saved = host.commands.requests[uid("request")]
    assert saved.status == "draft" and saved.tentative_start == payload.at
    assert saved.timeline.promised_start is None and saved.timeline.accepted is None
    assert saved.timeline.actual_start is None and not host.commands.confirmations


def test_available_sample_without_physical_ready_fact_cannot_be_accepted(host):
    current, payload = offered(host)
    host.samples.no_ready.add(sample().id)
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).preview("verification.handoff.accept", current.id, 1, payload)
    assert rejected.value.reason == "SAMPLE_UNAVAILABLE" and not host.commands.records
    assert rejected.value.code == REASONS["SAMPLE_UNAVAILABLE"]


def test_method_can_complete_unaccepted_item_without_changing_received_scope(host):
    refs = (sample(), sample("sample-b", "B"))
    selected = coverage(samples=refs)
    other = Coverage(sample_id=refs[0].id, item_id="pressure")
    pressure = item("pressure", sample_count=1, cavities=("A",), method=None)
    current, _ = offered(
        host,
        items=(item(), pressure),
        documents=(document("pressure-only", items=("pressure",), present=False),),
    )
    host.commands.requests[current.id] = current.model_copy(
        update={"offered_coverage": selected + (other,)},
    )
    accept = HandoffAccept(
        coverage=selected,
        reason="压力规程待补",
        next_owner_id=uid("method-owner"),
        at=event("accepted", offset=5),
    )
    perform(host, "verification.handoff.accept", current.id, 1, accept, command="accept")
    current = host.commands.requests[current.id]
    prior_acceptances = current.acceptances
    prepared_pressure = pressure.model_copy(update={"method": source("method-pressure")})
    prepare = MethodPrepare(
        items=(item(), prepared_pressure),
        documents=(document("pressure-only", items=("pressure",)),),
    )
    perform(
        host,
        "verification.method.prepare",
        current.id,
        current.revision,
        prepare,
        command="prepare-unreceived",
    )
    saved = host.commands.requests[current.id]
    assert saved.status == "accepted" and saved.acceptances == prior_acceptances
    assert saved.items[1].method == prepared_pressure.method


def test_method_update_cannot_change_already_received_item(host):
    current = accepted(host)
    payload = MethodPrepare(items=(item(conditions="80 °C"),), documents=current.documents)
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).preview(
            "verification.method.prepare", current.id, current.revision, payload
        )
    assert rejected.value.reason == "ACCEPTED_SCOPE_FROZEN"
    assert rejected.value.code == REASONS["ACCEPTED_SCOPE_FROZEN"]


@pytest.mark.parametrize("refusal", ["raw", "locator"])
def test_measurement_proof_refusal_after_preview_records_no_success(host, refusal):
    current = running(host)
    payload = full_final(current)
    command, _ = prepared(host, "test.results.import", current.id, current.revision, payload)
    first = payload.measurements[0]
    if refusal == "raw":
        host.evidence.rejected_raw.add(first.raw_value)
    else:
        host.evidence.rejected_locators.add(
            (first.source.id, first.source.revision, first.source.position)
        )
    before = len(host.commands.records)
    confirmations = len(host.commands.confirmations)
    with pytest.raises(HostRejection):
        VerificationHandler(host).execute(command, payload)
    assert len(host.commands.records) == before
    assert len(host.commands.confirmations) == confirmations
    assert host.commands.run_records[current.id].measurements == ()
    assert host.evidence.measurement_calls[-1][1] == first


def test_evidence_source_check_without_measurement_verifier_explicitly_blocks_import(host):
    current = running(host)
    checker = host.evidence.check

    class CheckOnlyEvidence:
        def check(self, bound_scope, ref, purpose):
            checker(bound_scope, ref, purpose)

    host.evidence = CheckOnlyEvidence()
    payload = full_final(current)
    command = invocation("test.results.import", current.id, current.revision, payload)
    before = len(host.commands.records)
    with pytest.raises(DomainError) as rejected:
        VerificationHandler(host).execute(command, payload)
    assert rejected.value.reason == "INTEGRATION_REQUIRED" and rejected.value.status == 503
    assert rejected.value.code == REASONS["INTEGRATION_REQUIRED"]
    assert len(host.commands.records) == before
    assert host.commands.run_records[current.id].measurements == ()
