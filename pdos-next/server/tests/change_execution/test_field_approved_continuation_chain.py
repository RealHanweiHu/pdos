"""Root-only native Field plan/approval/output/new-Run chain on explicit pdos_test.

No Issue/CAPA is created. All original reports, configuration revisions, named
approvals, Build/sample/test facts and result links use their real owners.
"""

# ruff: noqa: F811 -- real upstream pytest fixture tree
import json
import os
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import func, select
from test_project_first_plan import accepted, cmd, post

from pdos_next import change_controlled_owner as controlled
from pdos_next.change_controlled_schemas import PolicyImport, PolicyMaterial
from pdos_next.change_controlled_store import ChangeSelectionFact
from pdos_next.change_implementation_owner import FieldOccurrence
from pdos_next.change_order_store import ImplementationCapture
from pdos_next.domain.change_coverage_owner import trust
from pdos_next.domain.field_feedback.models import FieldFeedbackVersion, FieldResponseRecord
from pdos_next.domain.quality_execution.models import QualityIssueVersion
from pdos_next.models import Confirmation, now
from pdos_next.schemas.change_control.contracts import (
    ControlledIntent,
    Disposition,
    EffectivityPlan,
    GraphSnapshot,
    ImpactAssessment,
    PlanItem,
    Ref,
    Selection,
)
from pdos_next.schemas.verification.contracts import Scope, VerificationRequest

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


def milestone(work, phase, **details):
    """Optional root evidence log; no application writes or credentials."""
    target = os.environ.get("PDOS_FIELD_LIVE")
    if target:
        Path(target).write_text(
            json.dumps(
                {
                    "phase": phase,
                    "tenant_id": str(work.setup.tenant),
                    "category_id": str(work.setup.category),
                    "product_id": str(work.setup.product),
                    "project_id": work.config["project"],
                    "principal_id": str(work.quality.human),
                    "object_store_root": str(work.report_store.root),
                    **details,
                },
                indent=2,
            )
        )


def endpoint(work):
    return f"/v1/categories/{work.setup.category}/products/{work.setup.product}/change-execution"


def field_command(work, operation, payload):
    value = cmd(work.setup, operation, payload)
    root = f"/v1/categories/{work.setup.category}/products/{work.setup.product}/field-feedback"
    response = work.setup.client.post(root + "/inputs", headers=work.setup.headers, json=value)
    assert response.status_code == 200, response.text
    prepared = response.json()
    value["payload"] = prepared["payload"]
    value["source_read_set"] = prepared["required_source_read_set"]
    if operation == "field.feedback.create":
        response = post(work.setup, value)
        assert response.status_code == 200, response.text
        return response.json()
    return accepted(work.setup, value)[0]


def native_field(work):
    report = helper.original(
        work.setup,
        {
            "observation": "Synthetic customer vibration report; batch unknown",
            "purpose": work.binding.purpose,
        },
        "Synthetic actual customer report",
    )
    created = field_command(
        work,
        "field.feedback.create",
        {
            "visibility": "category",
            "title": "Synthetic customer vibration feedback",
            "description": "Actual synthetic report; no failure event or CAPA is inferred",
            "channel": "customer",
            "feedback_kind": "change_request",
            "received_at": now().isoformat(),
            "reported": {
                "product_label": "Synthetic motor",
                "batch_label": None,
                "configuration_label": None,
            },
            "purpose": work.binding.purpose,
            "sources": [report.source.model_dump(mode="json")],
            "reason": "Retain actual customer source before explicit configuration investigation",
        },
    )
    with helper.session(work, work.setup) as session:
        row = session.get(FieldFeedbackVersion, UUID(created["subject_id"]))
        feedback = {"id": str(row.feedback_id), "revision": row.revision}
    field_command(
        work,
        "field.feedback.locate",
        {
            "feedback": feedback,
            "project_id": work.config["project"],
            "engineering_configuration": {
                "id": work.config["engineering"]["subject_id"],
                "revision": 1,
            },
            "manufacturing_configuration": {
                "id": work.config["process"]["subject_id"],
                "revision": 1,
            },
            "batch": None,
            "sources": [report.source.model_dump(mode="json")],
            "reason": "Locate actual project and fixed configurations; batch stays unknown",
        },
    )
    feedback["revision"] = 2
    return feedback, report


def policy_and_field_items(work, change_id, feedback, source, until):
    scope = Scope(
        tenant_id=work.setup.tenant,
        product_id=work.setup.product,
        project_id=UUID(work.config["project"]),
    )
    with helper.session(work) as session:
        project = controlled._project(session, work.quality.ctx, scope)[0]
        project_owner = project.owner_id
    policy = PolicyMaterial(
        schema_version="pdos-controlled-change-policy-v1",
        scope=scope,
        purpose=work.binding.purpose,
        owner_id=project_owner,
        visibility="category",
        publisher_id=work.quality.human,
        required_disciplines=("engineering", "manufacturing"),
        valid_from=now() - timedelta(minutes=1),
        valid_until=until,
        nature="synthetic",
    )
    original = helper.original(work.quality, policy, "Synthetic actual dual discipline policy")
    with helper.session(work) as session:
        controlled.import_policy(
            session,
            work.quality.ctx,
            work.setup.product,
            PolicyImport(
                project_id=scope.project_id,
                purpose=work.binding.purpose,
                source=original.source,
                reason="Explicit synthetic project policy publication",
            ),
            command_id=uuid4(),
            request_key=str(uuid4()),
        )
    items = []
    for discipline, key, kind in (
        ("engineering", "engineering", "engineering_configuration"),
        ("manufacturing", "process", "manufacturing_configuration"),
    ):
        ref = Ref(kind=kind, id=UUID(work.config[key]["subject_id"]), revision=1)
        items.append(
            PlanItem(
                id=uuid4(),
                discipline=discipline,
                selection=Selection(
                    objects=(ref,),
                    units=(f"object:{ref.identity}",),
                    conditions=("This fixed internal configuration only; batch stays unknown",),
                    sources=(source.source,),
                ),
                intent=ControlledIntent(
                    id=uuid4(),
                    kind=f"new_{kind}",
                    basis=(ref,),
                    description=f"Future {discipline} configuration revision after named approval",
                ),
                verification_requirement="New samples and Run with independent verification",
            )
        )
    return scope, original, tuple(items)


def select_field_item(work, change_id, current, item, feedback):
    draft = {
        "change_id": change_id,
        "expected_change_revision": current["revision"],
        "field_intent": {
            "kind": "field_intent",
            "feedback": feedback,
            "executor_id": str(work.setup.human),
        },
        "item": item.model_dump(mode="json"),
        "status": "applicable",
        "valid_until": None,
        "reason": "Named explicit future Field plan, not the performed response ledger",
    }
    response = work.quality.client.post(
        endpoint(work) + "/selection-material", headers=work.quality.headers, json=draft
    )
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["stage"] == "material_draft"
    assert value["material"]["valid_until"] is None
    assert value["material"]["schema_version"] == "pdos-field-change-selection-v1"
    source = helper.original(
        work.quality, value["material"], "Synthetic explicit Field plan applicability"
    )
    response = work.quality.client.post(
        endpoint(work) + "/selection-material",
        headers=work.quality.headers,
        json={
            "change_id": change_id,
            "expected_change_revision": current["revision"],
            "source": source.source.model_dump(mode="json"),
        },
    )
    assert response.status_code == 200, response.text
    candidate = response.json()
    receipt, command = accepted(work.quality, candidate["command"])
    with helper.session(work) as session:
        row = session.get(ChangeSelectionFact, UUID(receipt["subject_id"]))
        assert (
            row.basis_kind == "field_intent"
            and row.issue_id is row.capa_id is row.action_id is None
        )
        assert row.executor_id == work.setup.human and row.feedback_id == UUID(feedback["id"])
        proof = session.get(Confirmation, row.shared_proof_id)
        assert proof.consumed is True and proof.expires_at is None
        assert row.input_snapshot["review"]["after"]["feedback_version_id"] == str(
            row.feedback_version_id
        )
        assert "issue_version_id" not in row.input_snapshot["review"]["after"]
        selected = SimpleNamespace(
            id=row.id,
            revision=row.revision,
            sha256=row.material_sha256,
            feedback_version_id=row.feedback_version_id,
            feedback_sha256=row.feedback_sha256,
        )
    before = helper.counts(work)
    replay = post(work.quality, command)
    assert replay.status_code == 200 and replay.json()["id"] == receipt["id"]
    assert helper.counts(work) == before
    return selected


def field_occurrence(work, change_id, item, selected, feedback, output, source):
    current, _ = change.current(work, change_id)
    order = current["request_snapshot"]["orders"][-1]
    occurrence = FieldOccurrence(
        schema_version="pdos-field-change-implementation-occurrence-v1",
        scope=work.failure_run.scope,
        purpose=work.binding.purpose,
        feedback=feedback,
        feedback_version_id=selected.feedback_version_id,
        feedback_sha256=selected.feedback_sha256,
        selection_id=selected.id,
        selection_revision=selected.revision,
        selection_sha256=selected.sha256,
        change_id=UUID(change_id),
        order_id=UUID(order["id"]),
        implementation_id=uuid4(),
        reconciles_id=None,
        item_id=item.id,
        intent_id=item.intent.id,
        executor_id=work.setup.human,
        operation="change.implementation.record",
        outcome="succeeded",
        occurred_at=now(),
        original_timezone="UTC",
        sources=(source.source,),
        outputs=(
            Ref(
                kind="engineering_configuration"
                if item.discipline == "engineering"
                else "manufacturing_configuration",
                id=UUID(output["subject_id"]),
                revision=output["subject_revision"],
            ),
        ),
        note="Actual saved configuration; effectivity and verification remain open",
        nature="synthetic",
    )
    original = helper.original(
        work.setup, occurrence, "Synthetic native Field implementation occurrence"
    )
    payload = {
        "change_id": change_id,
        "expected_change_revision": current["revision"],
        "visibility": "category",
        "capture_key": str(uuid4()),
        "order_id": order["id"],
        "item_id": str(item.id),
        "source": original.source.model_dump(mode="json"),
    }
    response = work.setup.client.post(
        endpoint(work) + "/implementation-captures", headers=work.setup.headers, json=payload
    )
    assert response.status_code == 200, response.text
    captured = response.json()
    before = helper.counts(work)
    replay = work.setup.client.post(
        endpoint(work) + "/implementation-captures", headers=work.setup.headers, json=payload
    )
    assert (
        replay.status_code == 200
        and replay.json()["id"] == captured["id"]
        and helper.counts(work) == before
    )
    command, _ = helper.inputs(
        work,
        work.setup,
        "change.implementation.record",
        {
            "change_id": change_id,
            "expected_change_revision": current["revision"],
            "visibility": "category",
            "item_id": str(item.id),
            "fact_id": captured["fact_id"],
        },
    )
    receipt, _ = accepted(work.setup, command)
    upstream.actual_group(
        work,
        receipt,
        work.setup,
        "change.implementation.record",
        "change.implementation_recorded",
        tier="T1",
    )
    with helper.session(work, work.setup) as session:
        capture = session.get(ImplementationCapture, UUID(captured["id"]))
        assert capture.occurrence_snapshot == occurrence.model_dump(mode="json")
        assert capture.fact_snapshot["outputs"] == [
            v.model_dump(mode="json") for v in occurrence.outputs
        ]
    return receipt, occurrence


def test_native_field_to_named_approvals_actual_outputs_and_new_run(quality_work, monkeypatch):
    work = quality_work
    helper.declare_people(work)
    people.continuation_people(work)
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
            field_command(
                work,
                "field.feedback.followup.link",
                {
                    "feedback": feedback,
                    "visibility": "category",
                    "description": "Implementation and new Run results; closure remains open",
                    "occurred_at": now().isoformat(),
                    "result_receipts": [
                        {"receipt_id": r["id"]} for r in (first, second, tested.result_receipt)
                    ],
                    "sources": [report.source.model_dump(mode="json")],
                    "reason": "Retain exact real native result receipts",
                },
            )
            with helper.session(work) as session:
                assert session.scalar(select(func.count()).select_from(QualityIssueVersion)) == 0
                responses = list(session.scalars(select(FieldResponseRecord)))
                assert len(responses) == 1 and responses[0].response_kind == "followup"
                assert len(responses[0].body["result_receipts"]) == 3
        milestone(work, "new_run_results_linked", change_id=change_id, feedback=feedback)
        current, _ = change.current(work, change_id)
        assert current["status"] != "closed" and all(
            order["closure"] is None for order in current["request_snapshot"]["orders"]
        )
    finally:
        trust.disable(work.setup.engine, scope=scope)
