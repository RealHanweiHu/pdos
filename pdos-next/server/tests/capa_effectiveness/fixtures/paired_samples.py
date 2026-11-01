"""Synthetic structural/UOW protocol tests only: no DB or live authorization."""

import json
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import paired as p
import pytest
from pdos_next.domain.configurations.schemas import DefinitionReference
from pdos_next.domain.verification.rules import compute_results
from pdos_next.domain.verification_launch.schemas import (
    ExecutionPlan,
    PlanPayload,
    PromisePayload,
    StartPayload,
)
from pdos_next.domain.verification_results.schemas import (
    DispositionPayload,
    ImportPayload,
    ReviewPayload,
)
from pdos_next.errors import DomainError
from pdos_next.schemas.resource_readiness.contracts import ExecutionWindow
from pdos_next.schemas.verification.contracts import (
    Acceptance,
    ExecutionConditions,
    PartialResultsReturn,
    ProfessionalConclusion,
    TimeFact,
)
from pydantic import ValidationError
from verification.helpers import (
    NOW,
    build,
    coverage,
    event,
    measurement,
    request,
    run,
    sample,
    scope,
    uid,
)

AT = NOW + timedelta(hours=3)
OWNER = uid("owner")
CALLER = uid("reader")


def instant(minutes):
    return NOW + timedelta(minutes=minutes)


def exact(name):
    return DefinitionReference(
        artifact_id=uid(name), expected_revision=1, line=1, quote=f"synthetic {name}"
    )


def ev(name, minutes):
    return event(name, offset=minutes)


def tf(value, actor, minutes):
    return TimeFact(**value.model_dump(), actor_id=actor, received_at=instant(minutes))


def form(
    snapshot,
    previous=None,
    operation="verification.handoff.accept",
    actor=OWNER,
    intent="0" * 64,
    minutes=120,
):
    return p.FormalRow(
        ref=p.FixedRef(id=uid(f"formal-{snapshot.revision}"), revision=snapshot.revision),
        previous=previous,
        owner_id=OWNER,
        authority_actor_id=actor,
        visibility="category",
        operation=operation,
        snapshot=snapshot,
        snapshot_sha256=p.digest(snapshot.model_dump(mode="json")),
        domain_intent=intent,
        reads=(p.SourceRead(artifact_id=uid("drawing"), expected_revision=1),),
        created_at=instant(minutes),
    )


def runrow(
    snapshot,
    plan,
    origin,
    previous=None,
    operation="test.run.plan",
    actor=OWNER,
    intent="0" * 64,
    minutes=120,
):
    return p.RunRow(
        ref=p.FixedRef(id=uid(f"run-version-{snapshot.revision}"), revision=snapshot.revision),
        previous=previous,
        origin_request=origin.ref,
        owner_id=uid("planner"),
        writer_id=actor,
        visibility="category",
        operation=operation,
        snapshot=snapshot,
        snapshot_sha256=p.digest(snapshot.model_dump(mode="json")),
        plan=plan,
        plan_sha256=p.digest(plan.model_dump(mode="json")),
        domain_intent=intent,
        reads=origin.reads,
        created_at=instant(minutes),
    )


def semantic(payload):
    # Fixture supplies exact normalized semantics, never an authorization claim.
    value = payload.model_dump(mode="json", exclude={"confirmation_token", "approval_token"})
    value["sources"].sort(key=lambda v: json.dumps(v, sort_keys=True))
    if "coverage" in value:
        value["coverage"].sort(key=lambda v: (v["sample_id"], v["item_id"]))
    return value


def intent(operation, actor, value):
    return p.digest({"operation": operation, "actor": str(actor), "payload": value})


def saved(operation="test.run.plan", *, final=True, formal_complete=True, null_raw=False):
    """Construct only synthetic saved rows using the real DTOs/rules, never ORM."""
    samples = (sample(), sample("sample-b", "B"))
    accepted = tf(ev("accepted", 110), OWNER, 111)
    origin_snapshot = request(
        revision=4,
        status="accepted",
        samples=samples,
        offered_coverage=coverage(),
        acceptances=(Acceptance(coverage=coverage(), actor_id=OWNER, at=accepted),),
    )
    origin = form(origin_snapshot)
    plan = ExecutionPlan(
        window=ExecutionWindow(start=instant(130), finish=instant(170), original_timezone="UTC"),
        executor_id=uid("executor"),
        equipment=exact("equipment"),
        calibration=exact("calibration"),
        environment="23 °C, humidity 50%",
        conditions="23 °C, dry",
        resource_fact_id=uid("resource-fact"),
        expected_resource_fact_revision=1,
    )
    planned = run(request_revision=4)
    actor = uid("planner")
    plan_payload = PlanPayload(
        request_id=origin_snapshot.id,
        expected_request_revision=4,
        run_id=planned.id,
        coverage=planned.coverage,
        execution_plan=plan,
        sources=(exact("plan-source"),),
        reason="plan synthetic",
    )
    raw = semantic(plan_payload)
    planned_row = runrow(
        planned, plan, origin, actor=actor, intent=intent("test.run.plan", actor, raw)
    )
    before_request, after_request, before_run, after_run = origin, origin, None, planned_row
    payload = plan_payload
    minutes = 120
    action_clock = TimeFact(
        occurred_at=instant(120),
        received_at=instant(120),
        original_timezone="UTC",
        actor_id=actor,
        source=p.SourceRef(
            id=uid("command-test.run.plan"), revision=1, kind="command", position="receipt"
        ),
    )

    promised_actor = uid("promiser")
    promised_clock = tf(ev("promised", 130), promised_actor, 121)
    promise_payload = PromisePayload(
        request_id=origin_snapshot.id,
        expected_request_revision=4,
        run_id=planned.id,
        expected_run_revision=1,
        expected_plan_sha256=planned_row.plan_sha256,
        at=ev("promised", 130),
        sources=(exact("promise-source"),),
        reason="promise synthetic",
    )
    scheduled = form(
        origin_snapshot.model_copy(
            update={
                "revision": 5,
                "status": "scheduled",
                "timeline": origin_snapshot.timeline.model_copy(
                    update={"promised_start": promised_clock}
                ),
            }
        ),
        origin.ref,
        "verification.schedule.promise",
        promised_actor,
        intent("verification.schedule.promise", promised_actor, semantic(promise_payload)),
        121,
    )
    if operation != "test.run.plan":
        before_request, after_request, before_run, after_run = (
            origin,
            scheduled,
            planned_row,
            planned_row,
        )
        payload, actor, minutes, action_clock = promise_payload, promised_actor, 121, promised_clock

    start_actor = plan.executor_id
    start_clock = tf(ev("actual-start", 131), start_actor, 132)
    start_payload = StartPayload(
        request_id=origin_snapshot.id,
        expected_request_revision=5,
        run_id=planned.id,
        expected_run_revision=1,
        expected_plan_sha256=planned_row.plan_sha256,
        at=ev("actual-start", 131),
        sources=(exact("start-source"),),
        reason="start synthetic",
    )
    start_intent = intent("test.run.start", start_actor, semantic(start_payload))
    executing = form(
        scheduled.snapshot.model_copy(
            update={
                "revision": 6,
                "status": "executing",
                "timeline": scheduled.snapshot.timeline.model_copy(
                    update={"actual_start": start_clock}
                ),
            }
        ),
        scheduled.ref,
        "test.run.start",
        start_actor,
        start_intent,
        132,
    )
    conditions = ExecutionConditions(
        equipment=p._source(plan.equipment),
        calibration=p._source(plan.calibration),
        environment=plan.environment,
        conditions=plan.conditions,
        executor_id=plan.executor_id,
    )
    running = runrow(
        planned.model_copy(
            update={
                "revision": 2,
                "status": "running",
                "actual_start": start_clock,
                "execution": conditions,
            }
        ),
        plan,
        origin,
        planned_row.ref,
        "test.run.start",
        start_actor,
        start_intent,
        132,
    )
    if operation not in {"test.run.plan", "verification.schedule.promise"}:
        before_request, after_request, before_run, after_run = (
            scheduled,
            executing,
            planned_row,
            running,
        )
        payload, actor, minutes, action_clock = start_payload, start_actor, 132, start_clock

    result_actor = uid("recorder")
    result_clock = tf(ev("result", 149), result_actor, 150)
    end = ev("actual-end", 148) if final else None
    import_payload = ImportPayload(
        request_id=origin_snapshot.id,
        expected_request_revision=6,
        run_id=planned.id,
        expected_run_revision=2,
        capture_id=uid("capture"),
        expected_capture_revision=1,
        final=final,
        at=ev("result", 149),
        actual_end=end,
        sources=(exact("report"),),
        reason="import synthetic",
    )
    readings = tuple(
        measurement(
            f"reading-{i}",
            pair=c,
            raw=None if null_raw and i == 0 else "10.0000",
            observed_at=instant(145),
            equipment=conditions.equipment,
        )
        for i, c in enumerate(coverage() if final else coverage()[:1])
    )
    computed, result = compute_results(running.snapshot, readings, final=final)
    result_intent = intent("test.results.import", result_actor, semantic(import_payload))
    imported = runrow(
        running.snapshot.model_copy(
            update={
                "revision": 3,
                "status": "results_pending" if final else "running",
                "measurements": readings,
                "computed_results": computed,
                "result": result,
                "actual_end": tf(end, result_actor, 150) if end else None,
                "final_result": result_clock if final else None,
                "preliminary_result": None if final else result_clock,
                "partial_returns": ()
                if final
                else (
                    PartialResultsReturn(
                        returned_coverage=(coverage()[0],),
                        pending_coverage=(coverage()[1],),
                        at=result_clock,
                    ),
                ),
            }
        ),
        plan,
        origin,
        running.ref,
        "test.results.import",
        result_actor,
        result_intent,
        150,
    )
    reported = form(
        executing.snapshot.model_copy(
            update={
                "revision": 7,
                "status": "reported" if final and formal_complete else "executing",
                "timeline": executing.snapshot.timeline.model_copy(
                    update={
                        "final_result": result_clock if final and formal_complete else None,
                        "preliminary_result": None if final else result_clock,
                    }
                ),
            }
        ),
        executing.ref,
        "test.results.import",
        result_actor,
        result_intent,
        150,
    )
    projection = p.ProjectionRow(
        ref=p.FixedRef(id=uid("projection"), revision=1),
        scope=scope(),
        build_id=build().id,
        request_id=origin_snapshot.id,
        run_id=planned.id,
        run=imported.ref,
        run_sha256=imported.snapshot_sha256,
        basis_sha256=p.digest({"synthetic": "projection basis"}),
        rules_version="synthetic-existing-rule",
        rules_sha256=p.digest({"rule": "synthetic"}),
        result=result,
        computed_results=computed,
        reads=origin.reads,
    )
    if operation in {"test.results.import", "test.run.review", "test.disposition.decide"}:
        before_request, after_request, before_run, after_run = (
            executing,
            reported,
            running,
            imported,
        )
        payload, actor, minutes, action_clock = import_payload, result_actor, 150, result_clock

    review_actor = uid("independent-reviewer")
    review_clock = tf(ev("review", 154), review_actor, 155)
    review_payload = ReviewPayload(
        request_id=origin_snapshot.id,
        expected_request_revision=7,
        run_id=planned.id,
        expected_run_revision=3,
        projection_id=projection.ref.id,
        expected_projection_revision=1,
        expected_basis_sha256=projection.basis_sha256,
        text="synthetic independent review",
        at=ev("review", 154),
        sources=(exact("review-source"),),
        reason="review synthetic",
    )
    reviewed = runrow(
        imported.snapshot.model_copy(
            update={
                "revision": 4,
                "status": "reviewed",
                "professional_conclusion": ProfessionalConclusion(
                    text=review_payload.text,
                    actor_id=review_actor,
                    source=review_payload.at.source,
                    at=review_clock,
                ),
            }
        ),
        plan,
        origin,
        imported.ref,
        "test.run.review",
        review_actor,
        intent("test.run.review", review_actor, semantic(review_payload)),
        155,
    )
    if operation in {"test.run.review", "test.disposition.decide"}:
        before_request, after_request, before_run, after_run = (
            reported,
            reported,
            imported,
            reviewed,
        )
        payload, actor, minutes, action_clock = review_payload, review_actor, 155, review_clock

    if operation == "test.disposition.decide":
        actor, minutes = uid("disposition-actor"), 160
        payload = DispositionPayload(
            **{
                **review_payload.model_dump(exclude={"approval_token"}),
                "expected_run_revision": 4,
                "at": ev("disposition", 159),
                "text": "synthetic disposition",
            }
        )
        action_clock = tf(payload.at, actor, minutes)
        decision_intent = intent(operation, actor, semantic(payload))
        after_run = runrow(
            reviewed.snapshot.model_copy(
                update={
                    "revision": 5,
                    "status": "disposed",
                    "disposition": ProfessionalConclusion(
                        text=payload.text, actor_id=actor, source=payload.at.source, at=action_clock
                    ),
                }
            ),
            plan,
            origin,
            reviewed.ref,
            operation,
            actor,
            decision_intent,
            minutes,
        )
        before_run, before_request = reviewed, reported
        after_request = (
            form(
                reported.snapshot.model_copy(
                    update={
                        "revision": 8,
                        "status": "disposed",
                        "timeline": reported.snapshot.timeline.model_copy(
                            update={"disposed": action_clock}
                        ),
                    }
                ),
                reported.ref,
                operation,
                actor,
                decision_intent,
                minutes,
            )
            if formal_complete
            else reported
        )

    raw = semantic(payload)
    domain = intent(operation, actor, raw)
    fact_base = dict(
        ref=p.FixedRef(id=uid(f"fact-{operation}"), revision=1),
        scope=scope(),
        build_id=build().id,
        request_id=origin_snapshot.id,
        run_id=planned.id,
        request_before=before_request.ref,
        next_request=after_request.ref,
        actor_id=actor,
        visibility="category",
        operation=operation,
        input_snapshot=raw,
        domain_intent=domain,
        reads=origin.reads,
        created_at=instant(minutes),
    )
    if operation in {"test.run.plan", "verification.schedule.promise", "test.run.start"}:
        subject = origin_snapshot.id if operation == "verification.schedule.promise" else planned.id
        revision = (
            after_request.ref.revision
            if operation == "verification.schedule.promise"
            else after_run.ref.revision
        )
        kernel = p.DomainEvent(
            name=p.EVENTS[operation],
            subject_id=subject,
            revision=revision,
            scope=scope(),
            at=action_clock,
            coverage=coverage(),
        )
        fact = p.LaunchFact(
            **fact_base,
            run=after_run.ref,
            kernel_event=kernel,
            snapshot_sha256=p.digest(kernel.model_dump(mode="json")),
        )
    else:
        fact = p.ResultAction(
            **fact_base,
            run_before=before_run.ref,
            next_run=after_run.ref,
            projection=projection.ref,
            event=payload.at,
        )
    common = p.CommonIntentMaterial(
        handler="verification_launch" if fact.kind == "launch" else "verification_results",
        operation=operation,
        category=uid("category"),
        product=scope().product_id,
        payload=raw,
        named_actor=actor,
        source_revision=None,
        private_owner=actor,
    )
    target = after_request if operation == "verification.schedule.promise" else after_run
    receipt = p.ReceiptRow(
        id=uid(f"receipt-{operation}"),
        tenant_id=scope().tenant_id,
        product_id=scope().product_id,
        command_id=uid(f"command-{operation}"),
        actor_id=actor,
        requester_id=actor,
        operation=operation,
        subject_type="verification_request"
        if operation == "verification.schedule.promise"
        else "test_run",
        subject=target.ref,
        visibility="category",
        request_digest="1" * 64,
        common_intent=p.digest(common.model_dump(mode="json", exclude={"handler"})),
        run_id=None,
        result=p.ReceiptResult(
            id=target.ref.id, revision=target.ref.revision, status=target.snapshot.status
        ),
        created_at=instant(minutes),
    )
    material = p.PairedMaterial(
        request_before=before_request,
        request_after=after_request,
        origin_request=origin,
        run_before=before_run,
        run_after=after_run,
        request_current=after_request.ref,
        run_current=after_run.ref,
        fact=fact,
        receipt=receipt,
        common_material=common,
        audits=(
            p.AuditRow(
                id=uid("audit"),
                tenant_id=scope().tenant_id,
                receipt_id=receipt.id,
                actor_id=actor,
                operation=operation,
            ),
        ),
        outbox=(
            p.OutboxRow(
                id=uid("outbox"),
                tenant_id=scope().tenant_id,
                receipt_id=receipt.id,
                type=p.EVENTS[operation],
                subject=target.ref,
                actor_id=actor,
                correlation_id=receipt.command_id,
                schema_version=1,
            ),
        ),
        projection=projection if fact.kind == "result" else None,
        projection_run=imported if fact.kind == "result" else None,
    )
    # Complete synthetic artifact closure, explicitly not real source/bytes proof.
    reads = p._merged_reads([p._artifact_refs(material.model_dump(mode="json"))])
    updates = {
        key: getattr(material, key).model_copy(update={"reads": reads})
        for key in (
            "request_before",
            "request_after",
            "origin_request",
            "run_after",
            "run_before",
            "fact",
            "projection",
            "projection_run",
        )
        if getattr(material, key) is not None
    }
    material = material.model_copy(update=updates)
    binding = p.PairBinding(
        scope=scope(),
        build=build(),
        request_id=origin_snapshot.id,
        run_id=planned.id,
        purpose=origin_snapshot.purpose,
        caller_id=CALLER,
        output_ref=p.FormalRef(**material.request_after.ref.model_dump()),
    )
    return binding, material


@pytest.mark.parametrize("operation", tuple(p.EVENTS))
def test_actual_transition_matrix_and_common_domain_separate(operation):
    binding, material = saved(operation)
    proof = p.verify_paired_material(binding, material, at=AT).proof
    assert proof.structural_only is True
    assert proof.owner_id == OWNER and proof.writer_id == material.fact.actor_id != OWNER
    assert material.receipt.common_intent != material.fact.domain_intent
    assert proof.meaning == (
        "planned"
        if operation in {"test.run.plan", "verification.schedule.promise"}
        else "performed"
    )
    assert proof.origin_formal == material.origin_request.ref
    if operation == "test.run.plan":
        assert material.request_before == material.request_after and material.run_before is None
    if operation == "verification.schedule.promise":
        assert material.run_before == material.run_after
    if operation == "test.run.review":
        assert material.request_before == material.request_after
        assert material.projection.run != material.run_current


def test_partial_and_final_unknown_values_are_not_complete_success():
    binding, material = saved("test.results.import", final=False)
    proof = p.verify_paired_material(binding, material, at=AT).proof
    assert proof.meaning == "performed" and material.request_after.snapshot.status == "executing"
    assert material.run_after.snapshot.result == "indeterminate"
    binding, material = saved("test.results.import", null_raw=True)
    assert p.verify_paired_material(binding, material, at=AT).proof
    assert material.run_after.snapshot.result == "indeterminate"
    assert material.run_after.snapshot.measurements[0].raw_value is None


def test_disposition_can_advance_run_without_advancing_incomplete_formal():
    binding, material = saved("test.disposition.decide", formal_complete=False)
    assert p.verify_paired_material(binding, material, at=AT).proof
    assert material.request_before == material.request_after
    assert material.request_after.snapshot.status == "executing"


def append_return(binding, material, *, final=False):
    before, request_before = material.run_after, material.request_after
    revision = before.ref.revision + 1
    actor = uid(f"recorder-{revision}")
    minutes = 155 if not final else 160
    observed = ev(f"return-{revision}", minutes - 1)
    clock = tf(observed, actor, minutes)
    payload = ImportPayload(
        request_id=binding.request_id,
        expected_request_revision=request_before.ref.revision,
        run_id=binding.run_id,
        expected_run_revision=before.ref.revision,
        capture_id=None if final else uid(f"capture-{revision}"),
        expected_capture_revision=None if final else 1,
        final=final,
        at=observed,
        actual_end=ev("final-end", 158) if final else None,
        sources=(exact(f"report-{revision}"),),
        reason=f"synthetic return {revision}",
    )
    raw = semantic(payload)
    new_measurement = measurement(
        "reading-second-partial",
        pair=before.snapshot.coverage[1],
        raw="10.0000",
        equipment=before.snapshot.execution.equipment,
        observed_at=instant(153),
    )
    measurements = before.snapshot.measurements + (() if final else (new_measurement,))
    computed, result = compute_results(before.snapshot, measurements, final=final)
    partials = before.snapshot.partial_returns
    if not final:
        partials += (
            PartialResultsReturn(
                returned_coverage=(new_measurement.coverage,), pending_coverage=(), at=clock
            ),
        )
    domain = intent("test.results.import", actor, raw)
    snap = before.snapshot.model_copy(
        update={
            "revision": revision,
            "status": "results_pending" if final else "running",
            "measurements": measurements,
            "computed_results": computed,
            "result": result,
            "partial_returns": partials,
            "actual_end": tf(payload.actual_end, actor, minutes) if final else None,
            "final_result": clock if final else None,
        }
    )
    row = runrow(
        snap,
        before.plan,
        material.origin_request,
        previous=before.ref,
        operation="test.results.import",
        actor=actor,
        intent=domain,
        minutes=minutes,
    )
    req = form(
        request_before.snapshot.model_copy(
            update={
                "revision": request_before.ref.revision + 1,
                "status": "reported" if final else "executing",
                "timeline": request_before.snapshot.timeline.model_copy(
                    update={"final_result": clock if final else None}
                ),
            }
        ),
        previous=request_before.ref,
        operation="test.results.import",
        actor=actor,
        intent=domain,
        minutes=minutes,
    )
    projection = material.projection.model_copy(
        update={
            "ref": p.FixedRef(id=uid(f"projection-{revision}"), revision=1),
            "run": row.ref,
            "run_sha256": row.snapshot_sha256,
            "result": result,
            "computed_results": computed,
        }
    )
    fact = material.fact.model_copy(
        update={
            "ref": p.FixedRef(id=uid(f"return-fact-{revision}"), revision=1),
            "request_before": request_before.ref,
            "next_request": req.ref,
            "actor_id": actor,
            "input_snapshot": raw,
            "domain_intent": domain,
            "created_at": instant(minutes),
            "run_before": before.ref,
            "next_run": row.ref,
            "projection": projection.ref,
            "event": payload.at,
        }
    )
    common = material.common_material.model_copy(
        update={"payload": raw, "named_actor": actor, "private_owner": actor}
    )
    receipt = material.receipt.model_copy(
        update={
            "id": uid(f"return-receipt-{revision}"),
            "command_id": uid(f"return-command-{revision}"),
            "actor_id": actor,
            "requester_id": actor,
            "subject": row.ref,
            "common_intent": p.digest(common.model_dump(mode="json", exclude={"handler"})),
            "result": p.ReceiptResult(id=row.ref.id, revision=revision, status=row.snapshot.status),
            "created_at": instant(minutes),
        }
    )
    audit = material.audits[0].model_copy(
        update={"id": uid(f"audit-{revision}"), "receipt_id": receipt.id, "actor_id": actor}
    )
    outbox = material.outbox[0].model_copy(
        update={
            "id": uid(f"outbox-{revision}"),
            "receipt_id": receipt.id,
            "subject": row.ref,
            "actor_id": actor,
            "correlation_id": receipt.command_id,
        }
    )
    material = material.model_copy(
        update={
            "request_before": request_before,
            "request_after": req,
            "run_before": before,
            "run_after": row,
            "request_current": req.ref,
            "run_current": row.ref,
            "fact": fact,
            "common_material": common,
            "projection": projection,
            "projection_run": row,
            "receipt": receipt,
            "audits": (audit,),
            "outbox": (outbox,),
        }
    )
    reads = p._merged_reads([p._artifact_refs(material.model_dump(mode="json"))])
    material = material.model_copy(
        update={
            key: getattr(material, key).model_copy(update={"reads": reads})
            for key in (
                "request_before",
                "request_after",
                "origin_request",
                "run_before",
                "run_after",
                "fact",
                "projection",
                "projection_run",
            )
        }
    )
    binding = binding.model_copy(update={"output_ref": p.FormalRef(**req.ref.model_dump())})
    return binding, material


def changed_return(material, **fields):
    snap = material.run_after.snapshot.model_copy(update=fields)
    row = material.run_after.model_copy(
        update={"snapshot": snap, "snapshot_sha256": p.digest(snap.model_dump(mode="json"))}
    )
    projection = material.projection.model_copy(update={"run_sha256": row.snapshot_sha256})
    return material.model_copy(
        update={"run_after": row, "projection_run": row, "projection": projection}
    )


def test_two_partial_returns_and_final_preserve_full_history_and_first_clock():
    binding, first = saved("test.results.import", final=False)
    binding, second = append_return(binding, first)
    assert p.verify_paired_material(binding, second, at=AT).proof
    assert second.run_after.snapshot.result == "indeterminate"
    assert (
        second.run_after.snapshot.partial_returns[:-1] == first.run_after.snapshot.partial_returns
    )
    assert (
        second.run_after.snapshot.preliminary_result == first.run_after.snapshot.preliminary_result
    )
    binding, last = append_return(binding, second, final=True)
    assert p.verify_paired_material(binding, last, at=AT).proof
    assert last.run_after.snapshot.result == "pass"
    assert last.run_after.snapshot.partial_returns == second.run_after.snapshot.partial_returns
    assert last.run_after.snapshot.preliminary_result == first.run_after.snapshot.preliminary_result


@pytest.mark.parametrize("mutation", ["delete", "replace", "duplicate", "reorder"])
def test_second_partial_cannot_rewrite_or_duplicate_first_history(mutation):
    binding, first = saved("test.results.import", final=False)
    binding, second = append_return(binding, first)
    old, new = second.run_after.snapshot.partial_returns
    choices = {
        "delete": (new,),
        "replace": (old.model_copy(update={"reason": "changed"}), new),
        "duplicate": (old, old, new),
        "reorder": (new, old),
    }
    expect_error(
        binding,
        changed_return(second, partial_returns=choices[mutation]),
        "PAIR_TIME_MISMATCH" if mutation == "reorder" else "PAIR_PARTIAL_HISTORY_CHANGED",
    )


def test_existing_first_run_clock_and_responsibility_are_immutable():
    binding, first = saved("test.results.import", final=False)
    binding, second = append_return(binding, first)
    old_clock = second.run_after.snapshot.preliminary_result
    changed_clock = old_clock.model_copy(update={"source": ev("different-clock", 149).source})
    expect_error(
        binding, changed_return(second, preliminary_result=changed_clock), "PAIR_EVENT_MISMATCH"
    )
    history = second.run_after.snapshot.partial_returns
    expect_error(
        binding,
        changed_return(
            second,
            partial_returns=history[:-1]
            + (
                history[-1].model_copy(update={"reason": "made-up", "next_owner_id": uid("other")}),
            ),
        ),
        "PAIR_PARTIAL_HISTORY_CHANGED",
    )


def test_final_cannot_delete_partial_history_or_reorder_existing_raw_readings():
    binding, first = saved("test.results.import", final=False)
    binding, second = append_return(binding, first)
    binding, last = append_return(binding, second, final=True)
    expect_error(binding, changed_return(last, partial_returns=()), "PAIR_PARTIAL_HISTORY_CHANGED")
    reversed_readings = tuple(reversed(last.run_after.snapshot.measurements))
    expect_error(
        binding, changed_return(last, measurements=reversed_readings), "PAIR_RAW_VALUE_CHANGED"
    )


def test_one_run_cannot_select_only_subset_of_actual_accepted_pairs():
    binding, material = saved()
    snap = material.run_after.snapshot.model_copy(
        update={"coverage": coverage()[:1], "samples": (sample(),)}
    )
    row = material.run_after.model_copy(
        update={"snapshot": snap, "snapshot_sha256": p.digest(snap.model_dump(mode="json"))}
    )
    expect_error(
        binding, material.model_copy(update={"run_after": row}), "PAIR_FIXED_SCOPE_CHANGED"
    )


@pytest.mark.parametrize("observed_minutes", [130, 149])
def test_final_known_observation_must_be_between_actual_start_and_end(observed_minutes):
    binding, material = saved("test.results.import")
    readings = material.run_after.snapshot.measurements
    changed = readings[0].model_copy(update={"observed_at": instant(observed_minutes)})
    expect_error(
        binding,
        changed_return(material, measurements=(changed,) + readings[1:]),
        "PAIR_TIME_MISMATCH",
    )


def test_new_partial_observation_cannot_be_after_its_actual_return():
    binding, first = saved("test.results.import", final=False)
    binding, second = append_return(binding, first)
    readings = second.run_after.snapshot.measurements
    changed = readings[-1].model_copy(update={"observed_at": instant(156)})
    expect_error(
        binding,
        changed_return(second, measurements=readings[:-1] + (changed,)),
        "PAIR_TIME_MISMATCH",
    )


def test_formal_actual_clock_cannot_impersonate_a_different_start_fact():
    binding, material = saved("test.run.start")
    timeline = material.request_after.snapshot.timeline
    timeline = timeline.model_copy(
        update={
            "actual_start": timeline.actual_start.model_copy(
                update={"source": ev("unrelated-start", 131).source}
            )
        }
    )
    snap = material.request_after.snapshot.model_copy(update={"timeline": timeline})
    formal = material.request_after.model_copy(
        update={"snapshot": snap, "snapshot_sha256": p.digest(snap.model_dump(mode="json"))}
    )
    expect_error(
        binding, material.model_copy(update={"request_after": formal}), "PAIR_EVENT_MISMATCH"
    )


@pytest.mark.parametrize(
    "source_change",
    [
        {"id": uid("another-command")},
        {"revision": 2},
        {"kind": "artifact"},
        {"position": "unrelated"},
    ],
)
def test_plan_clock_is_exact_common_command_receipt_source(source_change):
    binding, material = saved()
    clock = material.fact.kernel_event.at
    kernel = material.fact.kernel_event.model_copy(
        update={
            "at": clock.model_copy(update={"source": clock.source.model_copy(update=source_change)})
        }
    )
    fact = material.fact.model_copy(
        update={"kernel_event": kernel, "snapshot_sha256": p.digest(kernel.model_dump(mode="json"))}
    )
    expect_error(binding, material.model_copy(update={"fact": fact}), "PAIR_EVENT_MISMATCH")


@pytest.mark.parametrize(
    "clock_change",
    [
        {"occurred_at": instant(119)},
        {"original_timezone": "America/Los_Angeles"},
        {"effective_at": instant(121)},
    ],
)
def test_plan_clock_is_actual_server_command_fact_not_an_observation(clock_change):
    binding, material = saved()
    kernel = material.fact.kernel_event.model_copy(
        update={"at": material.fact.kernel_event.at.model_copy(update=clock_change)}
    )
    fact = material.fact.model_copy(
        update={"kernel_event": kernel, "snapshot_sha256": p.digest(kernel.model_dump(mode="json"))}
    )
    expect_error(binding, material.model_copy(update={"fact": fact}), "PAIR_EVENT_MISMATCH")


@pytest.mark.parametrize(
    "field,code",
    [
        ("fact", "PAIR_FACT_MISSING"),
        ("receipt", "PAIR_RECEIPT_MISSING"),
        ("common_material", "PAIR_RECEIPT_MISSING"),
        ("request_current", "PAIR_CURRENT_MISSING"),
        ("run_current", "PAIR_CURRENT_MISSING"),
        ("projection", "PAIR_PROJECTION_MISSING"),
    ],
)
def test_required_real_material_never_filled_from_other_snapshots(field, code):
    binding, material = saved("test.run.review")
    result = p.verify_paired_material(binding, material.model_copy(update={field: None}), at=AT)
    assert result.proof is None and result.missing[0].code == code


def expect_error(binding, material, code):
    with pytest.raises(DomainError) as caught:
        p.verify_paired_material(binding, material, at=AT)
    assert caught.value.code == code


def test_origin_is_not_current_and_scope_cannot_be_substituted():
    binding, material = saved("test.run.start")
    expect_error(
        binding,
        material.model_copy(update={"request_current": material.origin_request.ref}),
        "PAIR_CURRENT_MISMATCH",
    )
    expect_error(
        binding.model_copy(update={"purpose": "different purpose"}), material, "PAIR_SCOPE_MISMATCH"
    )
    expect_error(
        binding,
        material.model_copy(
            update={"fact": material.fact.model_copy(update={"build_id": uid("other-build")})}
        ),
        "PAIR_SCOPE_MISMATCH",
    )
    expect_error(
        binding,
        material.model_copy(
            update={
                "run_after": material.run_after.model_copy(
                    update={"origin_request": material.request_after.ref}
                )
            }
        ),
        "PAIR_SCOPE_MISMATCH",
    )


@pytest.mark.parametrize(
    "change,code",
    [
        ({"actor_id": OWNER}, "PAIR_RECEIPT_MISMATCH"),
        ({"subject_type": "verification_request"}, "PAIR_RECEIPT_MISMATCH"),
        ({"common_intent": "0" * 64}, "PAIR_COMMON_INTENT_MISMATCH"),
        ({"run_id": uid("ai-run")}, "PAIR_RECEIPT_MISMATCH"),
    ],
)
def test_receipt_actor_subject_and_separate_common_semantics(change, code):
    binding, material = saved("test.run.start")
    expect_error(
        binding,
        material.model_copy(update={"receipt": material.receipt.model_copy(update=change)}),
        code,
    )


def test_audit_outbox_atom_and_schema_are_exact():
    binding, material = saved("test.run.start")
    expect_error(binding, material.model_copy(update={"audits": ()}), "PAIR_ATOM_MISSING")
    expect_error(
        binding,
        material.model_copy(
            update={
                "outbox": (material.outbox[0].model_copy(update={"correlation_id": uid("other")}),)
            }
        ),
        "PAIR_ATOM_MISMATCH",
    )
    with pytest.raises(ValidationError):
        p.OutboxRow.model_validate({**material.outbox[0].model_dump(), "schema_version": 2})


def test_original_semantic_is_closed_complete_and_not_rebuilt():
    binding, material = saved("test.run.start")
    fact = material.fact.model_copy(update={"input_snapshot": {}})
    assert (
        p.verify_paired_material(binding, material.model_copy(update={"fact": fact}), at=AT)
        .missing[0]
        .code
        == "PAIR_ORIGINAL_SEMANTIC_MISSING"
    )
    raw = {**material.fact.input_snapshot, "confirmation_token": "secret"}
    expect_error(
        binding,
        material.model_copy(
            update={"fact": material.fact.model_copy(update={"input_snapshot": raw})}
        ),
        "PAIR_ORIGINAL_SEMANTIC_MISMATCH",
    )
    raw = {**material.fact.input_snapshot, "expected_request_revision": 4}
    fact = material.fact.model_copy(
        update={
            "input_snapshot": raw,
            "domain_intent": intent(material.fact.operation, material.fact.actor_id, raw),
        }
    )
    common = material.common_material.model_copy(update={"payload": raw})
    # Hashes may be coherent while original predecessor is still wrong.
    receipt = material.receipt.model_copy(
        update={"common_intent": p.digest(common.model_dump(mode="json", exclude={"handler"}))}
    )
    after = material.run_after.model_copy(update={"domain_intent": fact.domain_intent})
    formal = material.request_after.model_copy(update={"domain_intent": fact.domain_intent})
    expect_error(
        binding,
        material.model_copy(
            update={
                "fact": fact,
                "common_material": common,
                "receipt": receipt,
                "run_after": after,
                "request_after": formal,
            }
        ),
        "PAIR_ORIGINAL_SEMANTIC_MISMATCH",
    )


def test_snapshot_hash_actual_configuration_and_original_raw_values_preserved():
    binding, material = saved("test.run.review")
    changed = material.run_after.snapshot.model_copy(
        update={
            "samples": (
                sample(actual_configuration=build().engineering_configuration),
                sample("sample-b", "B"),
            )
        }
    )
    row = material.run_after.model_copy(
        update={"snapshot": changed, "snapshot_sha256": p.digest(changed.model_dump(mode="json"))}
    )
    expect_error(
        binding, material.model_copy(update={"run_after": row}), "PAIR_FIXED_SCOPE_CHANGED"
    )
    expect_error(
        binding,
        material.model_copy(
            update={
                "run_after": material.run_after.model_copy(update={"snapshot_sha256": "0" * 64})
            }
        ),
        "PAIR_SNAPSHOT_MISMATCH",
    )
    changed = material.run_after.snapshot.model_copy(
        update={
            "measurements": tuple(
                v.model_copy(update={"raw_value": "10"})
                for v in material.run_after.snapshot.measurements
            )
        }
    )
    row = material.run_after.model_copy(
        update={"snapshot": changed, "snapshot_sha256": p.digest(changed.model_dump(mode="json"))}
    )
    expect_error(
        binding, material.model_copy(update={"run_after": row}), "PAIR_FIXED_SCOPE_CHANGED"
    )


def test_saved_clocks_and_projection_basis_cannot_be_replaced():
    binding, material = saved("test.run.review")
    projection = material.projection.model_copy(update={"run_sha256": "0" * 64})
    expect_error(
        binding, material.model_copy(update={"projection": projection}), "PAIR_PROJECTION_MISMATCH"
    )
    conclusion = material.run_after.snapshot.professional_conclusion.model_copy(
        update={"actor_id": OWNER}
    )
    snap = material.run_after.snapshot.model_copy(update={"professional_conclusion": conclusion})
    row = material.run_after.model_copy(
        update={"snapshot": snap, "snapshot_sha256": p.digest(snap.model_dump(mode="json"))}
    )
    expect_error(binding, material.model_copy(update={"run_after": row}), "PAIR_EVENT_MISMATCH")


def test_full_source_union_never_truncated_or_conflicting_or_missing():
    binding, material = saved()
    one = (p.SourceRead(artifact_id=uid("drawing"), expected_revision=1),)
    changes = {
        key: getattr(material, key).model_copy(update={"reads": one})
        for key in ("request_before", "request_after", "origin_request", "run_after", "fact")
    }
    expect_error(binding, material.model_copy(update=changes), "MISSING_REQUIRED_EVIDENCE")
    reads = tuple(
        p.SourceRead(artifact_id=uid(f"extra-{i}"), expected_revision=1) for i in range(20)
    )
    expect_error(
        binding,
        material.model_copy(update={"fact": material.fact.model_copy(update={"reads": reads})}),
        "MISSING_REQUIRED_EVIDENCE",
    )
    conflicting = tuple(v.model_copy(update={"expected_revision": 2}) for v in material.fact.reads)
    expect_error(
        binding,
        material.model_copy(
            update={"fact": material.fact.model_copy(update={"reads": conflicting})}
        ),
        "SOURCE_STALE",
    )


def test_strict_revisions_unknown_fields_and_aware_saved_time():
    with pytest.raises(ValidationError):
        p.FixedRef(id=uid("bad"), revision=True)
    binding, material = saved()
    with pytest.raises(ValidationError):
        p.PairedMaterial.model_validate({**material.model_dump(), "qualified": True})
    with pytest.raises(ValidationError):
        p.RunRow.model_validate(
            {**material.run_after.model_dump(), "created_at": NOW.replace(tzinfo=None)}
        )
    with pytest.raises(DomainError, match="aware"):
        p.verify_paired_material(binding, material, at=NOW.replace(tzinfo=None))


class FakeSession:
    def __init__(self):
        self.transaction = object()
        self.nested = object()

    def get_transaction(self):
        return self.transaction

    def get_nested_transaction(self):
        return self.nested


class SyntheticReader:
    """Opaque protocol simulation; these stamps do not certify a real database."""

    def __init__(self, binding, material):
        self.value = p.ServerPairRead(binding, material)
        self.refresh_value = self.value
        self.stamp_revision = 1
        self.after_refresh_revision = 1
        self.calls = []
        self.gate_transform = lambda gate: gate
        self.valid_until = AT + timedelta(minutes=1)

    def read(self, *args, **kwargs):
        self.calls.append("read")
        return self.value

    def refresh(self, *args, **kwargs):
        self.calls.append("refresh")
        self.stamp_revision = self.after_refresh_revision
        return self.refresh_value

    def attest(self, s, ctx, product_id, read, structure, *, at, write):
        self.calls.append("attest")
        kinds = (
            "acl",
            "sources",
            "professional",
            "original_bytes",
            "semantic",
            "runtime",
            "retained",
            "numerical_rules",
        )
        gate = p.HostGateProof(
            issued_by=self,
            session=s,
            transaction=s.get_transaction(),
            nested_transaction=s.get_nested_transaction(),
            caller_id=ctx.requester_id,
            scope=read.binding.scope,
            structural_sha256=structure.material_sha256,
            stamps=tuple(
                p.GateStamp(
                    kind=k, basis_sha256=p.digest({"synthetic": k, "revision": self.stamp_revision})
                )
                for k in kinds
            ),
            checked_at=at,
            valid_until=self.valid_until,
        )
        return self.gate_transform(gate)


def invoke(reader, *, session=None, clock=lambda: AT):
    s = session or FakeSession()
    ctx = SimpleNamespace(tenant_id=scope().tenant_id, requester_id=CALLER)
    return p.read_paired_formal_output(
        s,
        ctx,
        scope().product_id,
        reader.value.binding.output_ref,
        at=AT,
        reader=reader,
        clock=clock,
    )


def test_default_missing_and_structure_alone_cannot_enable_host():
    binding, material = saved()
    result = p.read_paired_formal_output(None, None, scope().product_id, binding.output_ref, at=AT)
    assert result.host_gate is None and result.missing[0].code == "INTEGRATION_REQUIRED"
    reader = SyntheticReader(binding, material)
    reader.gate_transform = lambda gate: True
    result = invoke(reader)
    assert result.structure.structural_only and result.host_gate is None
    assert result.missing[0].code == "LIVE_HOST_GATE_MISSING"


def test_same_uow_two_independent_reads_and_owner_writer_separation():
    reader = SyntheticReader(*saved("test.run.review"))
    result = invoke(reader)
    assert reader.calls == ["read", "attest", "refresh", "attest"]
    assert result.missing == () and result.host_gate.issued_by is reader
    assert result.structure.owner_id != result.structure.writer_id


@pytest.mark.parametrize(
    "field",
    [
        "issued_by",
        "session",
        "transaction",
        "nested_transaction",
        "caller_id",
        "scope",
        "structural_sha256",
    ],
)
def test_gate_cannot_cross_reader_uow_caller_scope_or_material(field):
    reader = SyntheticReader(*saved("test.run.review"))
    values = {
        "caller_id": uid("other"),
        "scope": scope().model_copy(update={"project_id": uid("other")}),
        "structural_sha256": "0" * 64,
    }
    reader.gate_transform = lambda gate: replace(gate, **{field: values.get(field, object())})
    assert invoke(reader).missing[0].code == "LIVE_HOST_GATE_UNBOUND"


def test_missing_gate_kind_and_expiry_during_read_fail_closed():
    reader = SyntheticReader(*saved("test.run.review"))
    reader.gate_transform = lambda gate: replace(
        gate, stamps=tuple(s for s in gate.stamps if s.kind != "original_bytes")
    )
    assert invoke(reader).missing[0].code == "LIVE_HOST_GATE_UNBOUND"
    reader.gate_transform = lambda gate: gate
    reader.valid_until = AT
    assert invoke(reader).missing[0].code == "LIVE_HOST_GATE_EXPIRED"
    reader.valid_until = AT + timedelta(seconds=1)
    clock_calls = iter((AT, AT, AT, AT, AT + timedelta(seconds=2)))
    assert (
        invoke(reader, clock=lambda: next(clock_calls)).missing[0].code == "LIVE_HOST_GATE_EXPIRED"
    )


def test_post_io_epoch_aba_or_current_pointer_drift_rejected():
    reader = SyntheticReader(*saved("test.run.start"))
    reader.after_refresh_revision = 3  # withdraw -> restore still differs.
    with pytest.raises(DomainError) as caught:
        invoke(reader)
    assert caught.value.code == "SOURCE_STALE"
    reader = SyntheticReader(*saved("test.run.start"))
    reader.refresh_value = p.ServerPairRead(
        reader.value.binding,
        reader.value.material.model_copy(
            update={"request_current": reader.value.material.origin_request.ref}
        ),
    )
    with pytest.raises(DomainError) as caught:
        invoke(reader)
    assert caught.value.code == "PAIR_CURRENT_MISMATCH"


def test_real_transaction_is_required_and_refresh_missing_stays_missing():
    reader = SyntheticReader(*saved())
    session = FakeSession()
    session.transaction = None
    assert invoke(reader, session=session).missing[0].code == "CALLER_UOW_REQUIRED"
    reader.refresh_value = None
    result = invoke(reader)
    assert result.host_gate is None and result.missing[0].code == "INTEGRATION_REQUIRED"


def test_refresh_cannot_replace_the_caller_transaction_even_with_identical_material():
    reader = SyntheticReader(*saved())
    session = FakeSession()

    def refresh(*args, **kwargs):
        session.transaction = object()
        return reader.value

    reader.refresh = refresh
    with pytest.raises(DomainError) as caught:
        invoke(reader, session=session)
    assert caught.value.code == "CALLER_UOW_CHANGED"


def test_an_earlier_opaque_gate_is_not_a_fresh_current_check():
    reader = SyntheticReader(*saved())
    reader.gate_transform = lambda gate: replace(gate, checked_at=AT - timedelta(minutes=1))
    assert invoke(reader).missing[0].code == "LIVE_HOST_GATE_EXPIRED"
