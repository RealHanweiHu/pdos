"""Root-run actual Field adoption/independent verification/close, on marked pdos_test.

The unchanged upstream business sequence is copied from the earlier native Field
case because its terminal assertion intentionally forbids closure. Only this new
case adds the explicit development-Build plan and real completion commands.
No Issue/CAPA, fabricated business rows, renewed credentials or external model.
"""

# ruff: noqa: F811 -- actual upstream fixture tree
from contextlib import ExitStack
from datetime import timedelta
from uuid import UUID, uuid4

from build_start.test_transactions import import_authority
from sqlalchemy import func, select
from test_project_first_plan import accepted, post

from pdos_next.change_build_adoption import DEVELOPMENT_BUILD_ADOPTION_CONDITION
from pdos_next.change_order_store import ChangeCompletionRecord
from pdos_next.domain.change_control.rules import digest
from pdos_next.domain.change_coverage_owner import trust
from pdos_next.domain.quality_execution.models import QualityIssueVersion
from pdos_next.models import Audit, Confirmation, Outbox, Receipt, RequestKey, now
from pdos_next.schemas.change_control.contracts import (
    Disposition,
    EffectivityPlan,
    GraphSnapshot,
    ImpactAssessment,
    Ref,
)
from pdos_next.schemas.verification.contracts import VerificationRequest

from . import approved_configuration_continuation_helpers as next_round
from . import approved_configuration_helpers as helper
from . import test_approved_configuration_continuation_chain as people
from . import test_approved_configuration_implementation_chain as upstream
from . import test_transactions as change
from .test_approved_configuration_implementation_chain import (  # noqa: F401
    accepted_work,
    known_configuration,
    launch_work,
    operational_work,
    quality_work,
    ready_work,
    results_work,
)
from .test_field_approved_continuation_chain import (
    endpoint,
    field_occurrence,
    milestone,
    native_field,
    policy_and_field_items,
    select_field_item,
)


def completion_people(work):
    """Actual operation/purpose grants before any retained Change signer snapshots."""
    for person, operations in (
        (work.quality, ("change.effectivity.record", "change.verification.record", "change.close")),
        (work.independent_reviewer, ("change.verification.record", "change.close")),
    ):
        for kind in ("duty", "qualification"):
            import_authority(
                work,
                "quality",
                kind,
                subject_id=str(person.human),
                operations=list(operations),
                external_id=f"synthetic-native-completion-{work.build_id}-{person.human}-{kind}",
            )


def completion_counts(work):
    values = helper.counts(work)
    with helper.session(work) as stored:
        values[ChangeCompletionRecord.__tablename__] = stored.scalar(
            select(func.count()).select_from(ChangeCompletionRecord)
        )
    return values


def context(work, caller, change_id):
    before = completion_counts(work)
    response = caller.client.get(
        endpoint(work) + "/completion-context",
        headers=caller.headers,
        params={"change_id": change_id},
    )
    assert response.status_code == 200, response.text
    assert completion_counts(work) == before, "Context read must not write any business/common row"
    value = response.json()
    assert value["change_id"] == change_id and value["project_id"] == work.config["project"]
    return value


def base_payload(work, value):
    return {
        "change_id": value["change_id"],
        "expected_change_revision": value["change_revision"],
        "visibility": value["visibility"],
    }


def completion_group(work, caller, receipt, operation, tier):
    with helper.session(work, caller) as stored:
        saved = stored.get(Receipt, UUID(receipt["id"]))
        assert saved.operation == operation and saved.subject_type == "change_request"
        assert saved.actor_id == saved.requester_id == caller.human
        for model, where in (
            (Audit, (Audit.receipt_id == saved.id, Audit.operation == operation)),
            (
                Outbox,
                (
                    Outbox.receipt_id == saved.id,
                    Outbox.type
                    == {
                        "change.effectivity.record": "change.effectivity_recorded",
                        "change.verification.record": "change.verification_recorded",
                        "change.close": "change.closed",
                    }[operation],
                ),
            ),
            (RequestKey, (RequestKey.receipt_id == saved.id,)),
        ):
            assert stored.scalar(select(func.count()).select_from(model).where(*where)) == 1
        rows = list(
            stored.scalars(
                select(ChangeCompletionRecord).where(
                    ChangeCompletionRecord.change_version_id == saved.subject_id,
                    ChangeCompletionRecord.operation == operation,
                )
            )
        )
        assert len(rows) == 1
        atom = rows[0]
        proof = stored.get(Confirmation, atom.shared_proof_id)
        assert atom.actor_id == proof.actor_id == caller.human
        assert (
            proof.consumed and proof.operation == operation and proof.snapshot["proof_tier"] == tier
        )
        assert (proof.expires_at is None) == (tier == "T2")
        assert proof.created_at <= atom.proof_consumed_at <= atom.created_at <= saved.created_at
        assert atom.proof_expires_at == proof.expires_at
        return helper.snapshot(atom)


def apply_completion(work, caller, operation, payload, tier):
    before = completion_counts(work)
    response = caller.client.post(
        endpoint(work) + "/completion-material",
        headers=caller.headers,
        json={"operation": operation, "payload": payload},
    )
    assert response.status_code == 200, response.text
    assert completion_counts(work) == before, "Material preparation cannot create an atom or proof"
    value = response.json()
    assert value["allowed"] and value["command"]["operation"] == operation
    receipt, command = accepted(caller, value["command"])
    atom = completion_group(work, caller, receipt, operation, tier)
    after = completion_counts(work)
    assert (
        after[ChangeCompletionRecord.__tablename__]
        == before[ChangeCompletionRecord.__tablename__] + 1
    )
    for model in (Receipt, Audit, Outbox, RequestKey, Confirmation):
        assert after[model.__tablename__] == before[model.__tablename__] + 1
    # Treat a lost response as unknown; only the exact prepared/consumed command
    # is replayed. No second capture/key or extra proof is manufactured.
    replay = post(caller, command)
    assert replay.status_code == 200 and replay.json()["id"] == receipt["id"], replay.text
    assert completion_counts(work) == after
    return receipt, command, atom


def complete_native_change(work, change_id, items, continued, tested):
    receipts = []
    for item in items:
        value = context(work, work.quality, change_id)
        assert value["capabilities"]["change.effectivity.record"]["allowed"]
        choices = [v for v in value["adoptions"] if v["build"]["id"] == continued.build_id]
        assert len(choices) == 1
        choice = choices[0]
        assert {v["ref"]["id"] for v in choice["samples"]} == {s["id"] for s in continued.samples}
        payload = {
            **base_payload(work, value),
            "item_id": str(item.id),
            "lot": choice["lot"],
            "sample_refs": [v["ref"] for v in choice["samples"]],
        }
        receipt, command, atom = apply_completion(
            work, work.quality, "change.effectivity.record", payload, "T1"
        )
        assert atom["item_id"] == item.id and atom["fact_snapshot"]["stage"] == "effective"
        assert atom["fact_snapshot"]["outcome"] == "succeeded"
        assert atom["fact_snapshot"]["covered_units"] == list(item.selection.units)
        receipts.append((work.quality, receipt, command))
    value = context(work, work.independent_reviewer, change_id)
    assert value["capabilities"]["change.verification.record"]["allowed"]
    candidates = [v for v in value["runs"] if v["run"]["id"] == str(tested.final.run.id)]
    assert len(candidates) == 1
    run = candidates[0]
    assert run["run"]["revision"] == tested.final.run.revision
    actual_pairs = {(str(pair.sample_id), pair.item_id) for pair in tested.final.run.coverage}
    assert {(v["sample_id"], v["test_item_id"]) for v in run["mappings"]} == actual_pairs
    item_views = {v["item"]["id"]: v for v in value["items"]}
    mappings = [
        {
            "item_id": str(item.id),
            "run": run["run"],
            "sample_id": pair["sample_id"],
            "test_item_id": pair["test_item_id"],
            "method": pair["method"],
            "requirement_sha256": item_views[str(item.id)]["requirement_sha256"],
            "rationale": (
                "Named applicability: this exact method and actual sample/test item verifies "
                "the fixed requirement of this configuration in the successor development Build"
            ),
        }
        for item in items
        for pair in run["mappings"]
    ]
    assert all(
        m["requirement_sha256"]
        == digest(next(i for i in items if str(i.id) == m["item_id"]).verification_requirement)
        for m in mappings
    )
    payload = {
        **base_payload(work, value),
        "mappings": mappings,
        "text": (
            "Independent named verification of complete actual new-Run evidence "
            "and explicit applicability"
        ),
    }
    # This actor genuinely has the operation's qualification but is the original
    # requester. Reject self-certification through the actual owner/pure boundary.
    before = completion_counts(work)
    denied = work.quality.client.post(
        endpoint(work) + "/completion-material",
        headers=work.quality.headers,
        json={"operation": "change.verification.record", "payload": payload},
    )
    assert denied.status_code == 403, denied.text
    assert denied.json()["detail"]["reason"] == "INDEPENDENT_VERIFIER_REQUIRED"
    assert completion_counts(work) == before
    receipt, command, atom = apply_completion(
        work, work.independent_reviewer, "change.verification.record", payload, "T2"
    )
    fact = atom["fact_snapshot"]
    assert fact["verifier_id"] == str(work.independent_reviewer.human)
    assert str(work.retest_executor.human) in fact["executor_ids"]
    assert fact["result"] == "pass" and fact["nature"] == "synthetic"
    assert fact["applicable"] and fact["current"]
    assert set(fact["item_ids"]) == {str(i.id) for i in items}
    receipts.append((work.independent_reviewer, receipt, command))
    value = context(work, work.independent_reviewer, change_id)
    assert value["status"] == "verifying" and value["closure"] is None
    assert value["capabilities"]["change.close"]["allowed"]
    receipt, command, _ = apply_completion(
        work,
        work.independent_reviewer,
        "change.close",
        {
            **base_payload(work, value),
            "text": (
                "Separately close only this fixed approved development scope "
                "after actual adoption and independent pass"
            ),
        },
        "T2",
    )
    receipts.append((work.independent_reviewer, receipt, command))
    current, _ = change.current(work, change_id)
    order = current["request_snapshot"]["orders"][-1]
    assert current["status"] == "closed" and order["closure"]["actor_id"] == str(
        work.independent_reviewer.human
    )
    assert len(order["effectivity"]) == 2 and len(order["verifications"]) == 1
    with helper.session(work, work.independent_reviewer) as stored:
        atoms = list(
            stored.scalars(
                select(ChangeCompletionRecord).where(
                    ChangeCompletionRecord.change_id == UUID(change_id)
                )
            )
        )
        assert len(atoms) == 4
        assert sum(v.operation == "change.effectivity.record" for v in atoms) == 2
        assert sum(v.operation == "change.verification.record" for v in atoms) == 1
        assert sum(v.operation == "change.close" for v in atoms) == 1
        assert stored.scalar(select(func.count()).select_from(QualityIssueVersion)) == 0
    before = completion_counts(work)
    for caller, saved, original in receipts:
        response = post(caller, original)
        assert response.status_code == 200 and response.json()["id"] == saved["id"], response.text
    assert completion_counts(work) == before
    milestone(
        work,
        "native_field_closed",
        change_id=change_id,
        feedback=None,
        completion_receipts=[r[1]["id"] for r in receipts],
    )


def test_native_field_adoption_independent_verification_and_named_close(quality_work, monkeypatch):
    work = quality_work
    helper.declare_people(work)
    people.continuation_people(work)
    completion_people(work)
    milestone(work, "upstream_ready")
    with helper.session(work) as session:
        assert session.scalar(select(func.count()).select_from(QualityIssueVersion)) == 0
    feedback, report = native_field(work)
    milestone(work, "field_located", feedback=feedback)
    created, inputs = change.command(
        work,
        "change.request.create",
        {
            "title": "Synthetic actual Field corrective configuration change",
            "reason": "Explicit user future plan from actual customer report",
            "roots": [{"kind": "field_feedback", **feedback, "key": None}],
            "references": [],
            "sources": [report.source.model_dump(mode="json")],
            "visibility": "category",
        },
    )
    response = post(work.quality, created)
    assert response.status_code == 200, response.text
    change_id = inputs["change_id"]
    until = now() + timedelta(hours=1)
    scope, policy, items = policy_and_field_items(work, change_id, feedback, report, until)
    # The named selection fixes the old Build before any formal plan/approval.
    old_build = Ref(kind="build", id=UUID(str(work.build_id)), revision=1)
    items = tuple(
        item.model_copy(
            update={
                "selection": item.selection.model_copy(
                    update={
                        "conditions": (DEVELOPMENT_BUILD_ADOPTION_CONDITION,),
                    }
                ),
                "intent": item.intent.model_copy(
                    update={
                        "basis": (*item.intent.basis, old_build),
                    }
                ),
            }
        )
        for item in items
    )
    unknown, _ = change.capture(work, change_id)
    graph = GraphSnapshot.model_validate(unknown["capture"]["graph"])
    assert all(v.status == "unknown" for v in graph.coverage)
    paths, facets = upstream.coverage_declarations(graph)
    try:
        impact, _ = change.command(work, "change.impact.compute", unknown["impact_payload"])
        response = post(work.quality, impact)
        assert response.status_code == 200, response.text
        current, _ = change.current(work, change_id)
        assessment = ImpactAssessment.model_validate(current["request_snapshot"]["assessments"][-1])
        assert assessment.unknown and assessment.known
        selected = [select_field_item(work, change_id, current, item, feedback) for item in items]
        milestone(work, "two_field_selections", change_id=change_id, feedback=feedback)
        rows = []
        for node in graph.nodes:
            linked = tuple(
                item.id
                for item in items
                if node.ref in item.selection.objects
                or (node.ref.kind == "operation" and item.discipline == "manufacturing")
            )
            rows.append(
                {
                    "object": node.ref.model_dump(mode="json"),
                    "handling": "covered_by_plan" if linked else "reviewed_no_change",
                    "item_ids": [str(v) for v in linked],
                    "rationale": "Bounded synthetic disposition; retain historical identities",
                }
            )
        disposition = helper.original(
            work.quality,
            {"change_id": change_id, "dispositions": rows},
            "Synthetic Field per-object reviewed dispositions",
        )
        helper.publish_coverage(
            work, scope, change_id, graph, until, paths=paths, facet_states=facets
        )
        # Source registration changes the genuine dependency watermark. Recapture
        # after all chosen originals exist, rather than relaxing the closure fence.
        response = work.quality.client.post(
            endpoint(work) + "/captures",
            headers=work.quality.headers,
            json={
                "capture_key": str(uuid4()),
                "change_id": change_id,
                "expected_change_revision": current["revision"],
                "reason": "Recheck actual closure after registering the exact plan sources",
            },
        )
        assert response.status_code == 200, response.text
        impact, _ = change.command(work, "change.impact.compute", response.json()["impact_payload"])
        response = post(work.quality, impact)
        assert response.status_code == 200, response.text
        current, _ = change.current(work, change_id)
        assessment = ImpactAssessment.model_validate(current["request_snapshot"]["assessments"][-1])
        assert not assessment.unknown
        milestone(work, "current_covered_impact", change_id=change_id, feedback=feedback)
        plan = EffectivityPlan(
            id=uuid4(),
            items=items,
            expires_at=None,
            dispositions=tuple(
                Disposition.model_validate(
                    {**row, "sources": [disposition.source.model_dump(mode="json")]}
                )
                for row in rows
            ),
        )
        command, review = helper.inputs(
            work,
            work.quality,
            "change.order.prepare",
            {
                "change_id": change_id,
                "expected_change_revision": current["revision"],
                "visibility": "category",
                "assessment_id": str(assessment.id),
                "plan": plan.model_dump(mode="json"),
                "reason": "Prepare the Field plan with actual complete coverage",
            },
        )
        assert not review["unknown"]
        accepted(work.quality, command)
        milestone(work, "order_prepared", change_id=change_id, feedback=feedback)
        for discipline, caller in (("engineering", work.engineer), ("manufacturing", work.setup)):
            current, _ = change.current(work, change_id)
            command, _ = helper.inputs(
                work,
                caller,
                "change.order.approve",
                {
                    "change_id": change_id,
                    "expected_change_revision": current["revision"],
                    "visibility": "category",
                    "discipline": discipline,
                    "text": "Named professional approval of the fixed actual Field plan",
                    "expires_at": None,
                    "sources": [
                        policy.source.model_dump(mode="json"),
                        disposition.source.model_dump(mode="json"),
                    ],
                },
            )
            receipt, _ = accepted(caller, command)
            upstream.actual_group(
                work, receipt, caller, "change.order.approve", "change.approved", tier="T2"
            )
        current, _ = change.current(work, change_id)
        assert current["status"] == "approved"
        milestone(work, "dual_approved", change_id=change_id, feedback=feedback)
        config_source = helper.original(
            work.setup,
            {
                "change_id": change_id,
                "feedback": feedback,
                "instruction": "Synthetic mount and assembly revision after dual approval",
            },
            "Synthetic Field configuration revision instructions",
        )
        eng, _ = upstream.revisions(work, config_source)
        first, _ = field_occurrence(
            work, change_id, items[0], selected[0], feedback, eng, config_source
        )
        milestone(work, "engineering_implemented", change_id=change_id, feedback=feedback)
        mfg, _ = upstream.revisions(work, config_source, eng)
        second, _ = field_occurrence(
            work, change_id, items[1], selected[1], feedback, mfg, config_source
        )
        milestone(work, "both_implemented", change_id=change_id, feedback=feedback)
        with ExitStack() as cleanup:
            continued = next_round.create_new_build(work, eng, mfg, cleanup=cleanup)
            next_round.create_actual_samples(continued)
            next_round.create_new_request(continued, method_dossier=work.source)
            milestone(work, "new_physical_request", change_id=change_id, feedback=feedback)
            tested = next_round.record_new_run_results(
                continued,
                monkeypatch,
                cleanup=cleanup,
                raw_value="10.0000",
                test_executor=work.retest_executor,
                test_person_resource=work.retest_person_resource,
                independent_reviewer=work.independent_reviewer,
            )
            assert tested.final.run.result == "pass" and tested.final.run.id != work.failure_run.id
            request_dto = VerificationRequest.model_validate(tested.final.request.request_snapshot)
            assert request_dto.build.engineering_configuration.id == UUID(eng["subject_id"])
            complete_native_change(work, change_id, items, continued, tested)
            with helper.session(work) as session:
                assert session.scalar(select(func.count()).select_from(QualityIssueVersion)) == 0
    finally:
        trust.disable(work.setup.engine, scope=scope)
