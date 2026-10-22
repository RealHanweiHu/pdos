"""Shared actual failure/CAPA to controlled policy, selections and an unapproved order.

Root alone runs PostgreSQL. Every original, professional fact and common command
uses its existing real owner. Missing impact remains unknown at this checkpoint.
"""

# ruff: noqa: F811 - imported pytest fixtures register their dependency tree
import hashlib
import json
from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

from build_start.test_transactions import import_authority
from quality_execution import fixtures as quality
from quality_execution.fixtures import (  # noqa: F401
    accepted_work,
    known_configuration,
    launch_work,
    operational_work,
    quality_work,
    ready_work,
    results_work,
)
from sqlalchemy import func, select
from test_project_first_plan import accepted, cmd, post
from verification_results import fixtures as results

from pdos_next import change_controlled_owner as controlled
from pdos_next.change_controlled_schemas import PolicyImport, PolicyMaterial, SelectionMaterial
from pdos_next.change_controlled_store import ChangePolicyFact, ChangeSelectionFact
from pdos_next.change_order_store import (
    ChangeApprovalRecord,
    ChangeImplementationRecord,
    ChangeOrderRecord,
)
from pdos_next.database import tenant_session
from pdos_next.domain.capa_verification import service as followup_owner
from pdos_next.domain.change_execution.models import ChangeCurrent, ChangeRequestVersion
from pdos_next.domain.projects.models import Project
from pdos_next.domain.verification_launch.models import (
    VerificationRunCurrent,
    VerificationRunVersion,
)
from pdos_next.domain.verification_results.models import MeasurementImportCapture, MeasurementRecord
from pdos_next.models import (
    Artifact,
    Audit,
    Confirmation,
    Outbox,
    Receipt,
    RequestKey,
    UploadedOriginal,
    now,
)
from pdos_next.schemas.change_control.contracts import (
    ControlledIntent,
    Disposition,
    EffectivityPlan,
    ImpactAssessment,
    PlanItem,
    Ref,
    Selection,
)
from pdos_next.schemas.verification.contracts import Scope, SourceRef

from . import test_transactions as change


def session(work, *, caller=None):
    caller = caller or work.quality
    return tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=caller.human,
        requester_id=caller.human,
        category_id=work.setup.category,
    )


def native_original(work, material, title):
    content = json.dumps(
        material.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    response = post(
        work.quality,
        cmd(
            work.quality,
            "evidence.artifact.register",
            {
                "title": title,
                "source_label": "Explicit synthetic controlled publication",
                "visibility": "category",
                "content": content,
            },
        ),
    )
    assert response.status_code == 200, response.text
    return SourceRef(
        id=UUID(response.json()["subject_id"]),
        revision=1,
        kind="artifact",
        position="line:1;quote_sha256:" + hashlib.sha256(content.encode()).hexdigest(),
    )


def inputs(work, operation, payload):
    value = cmd(work.quality, operation, payload)
    response = work.quality.client.post(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/change-execution/inputs",
        headers=work.quality.headers,
        json=value,
    )
    assert response.status_code == 200, response.text
    assert response.json()["allowed"] is True
    return response.json()["command"], response.json()


def shared_capa(work):
    quality.publish_policy(work)
    value = quality.command(
        work, "quality.issue.create", {**quality.payload_create(work), "visibility": "category"}
    )
    created = post(work.quality, value)
    assert created.status_code == 200, created.text
    work.issue_id = UUID(created.json()["result"]["issue_id"])
    quality.triage(work, created.json())
    accepted(
        work.quality,
        quality.command(
            work,
            "quality.issue.containment.record",
            {
                "issue_id": str(work.issue_id),
                "expected_issue_revision": 2,
                "action": {
                    "id": str(uuid4()),
                    "text": "Synthetic named shared containment",
                    "executor_id": str(work.quality.human),
                    "evidence": [work.containment_source.model_dump(mode="json")],
                    "at": {
                        "occurred_at": now().isoformat(),
                        "original_timezone": "UTC",
                        "source": work.containment_source.model_dump(mode="json"),
                    },
                },
            },
        ),
    )
    contained = quality.issue_current(work, work.issue_id)
    work.capa_id = uuid4()
    work.actions = [
        {
            "id": str(uuid4()),
            "kind": "corrective",
            "executor_id": str(work.quality.human),
            "text": f"Prepare controlled {discipline} revision for this failure and later retest",
        }
        for discipline in ("engineering", "manufacturing")
    ]
    drafted = post(
        work.quality,
        quality.command(
            work,
            "quality.capa.draft",
            {
                "issue_id": str(work.issue_id),
                "expected_issue_revision": contained["revision"],
                "capa_id": str(work.capa_id),
                "hypotheses": [
                    {
                        "text": "Synthetic hypothesis remains unproven",
                        "sources": [work.hypothesis_source.model_dump(mode="json")],
                    }
                ],
                "actions": work.actions,
                "requirement": {
                    "method": "Separate actual new configuration and verification Run",
                    "acceptance": "Exact affected pairs with independent applicable verification",
                    "observation_until": (now() + timedelta(days=1)).isoformat(),
                    "required_failure_ids": [
                        value["identity"] for value in contained["issue"]["failures"]
                    ],
                },
            },
        ),
    )
    assert drafted.status_code == 200, drafted.text
    work.issue_view = quality.issue_current(work, work.issue_id)
    assert work.issue_view["visibility"] == "category"
    return work.issue_view


def counts(work):
    with session(work) as stored:
        return {
            model.__tablename__: stored.scalar(select(func.count()).select_from(model))
            for model in (
                ChangePolicyFact,
                ChangeSelectionFact,
                ChangeOrderRecord,
                ChangeApprovalRecord,
                ChangeImplementationRecord,
                ChangeRequestVersion,
                ChangeCurrent,
                Receipt,
                Audit,
                Outbox,
                Confirmation,
                RequestKey,
                Artifact,
                UploadedOriginal,
            )
        }


def order_context(work, change_id):
    before, fixed = counts(work), change.current(work, change_id)
    response = work.quality.client.get(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/change-execution/order-context",
        headers=work.quality.headers,
        params={"change_id": str(change_id)},
    )
    assert response.status_code == 200, response.text
    assert counts(work) == before and change.current(work, change_id) == fixed
    return response.json()


def test_shared_capa_policy_two_selections_prepare_order_without_approving_unknown_impact(
    quality_work,
):
    work = quality_work
    # Declare all separate synthetic series before the Issue's signer snapshots
    # as well as before capture; never update a saved professional basis in place.
    for role, operations in (
        (
            "quality",
            [
                "change.request.create",
                "change.impact.compute",
                "change.policy.import",
                "change.order.prepare",
            ],
        ),
        ("engineering", ["change.selection.decide"]),
        ("manufacturing", ["change.selection.decide"]),
    ):
        for kind in ("duty", "qualification"):
            import_authority(
                work,
                role,
                kind,
                subject_id=str(work.quality.human),
                operations=operations,
                external_id=f"synthetic-shared-order-{work.build_id}-{role}-{kind}",
            )
    # The saved report capture inherits the real Run audience. Its exact source
    # remains in the direct-source RLS read set; sharing never substitutes bytes.
    with session(work) as stored:
        run_pointer = stored.scalar(
            select(VerificationRunCurrent).where(
                VerificationRunCurrent.tenant_id == work.setup.tenant,
                VerificationRunCurrent.product_id == work.setup.product,
                VerificationRunCurrent.run_id == work.failure_run.id,
            )
        )
        assert run_pointer is not None
        run_row = stored.get(VerificationRunVersion, run_pointer.run_version_id)
        measurement = stored.get(MeasurementRecord, work.failure_run.measurements[0].id)
        assert run_row is not None and measurement is not None
        captured = stored.get(MeasurementImportCapture, measurement.capture_id)
        assert captured is not None
        assert captured.visibility == run_row.visibility == measurement.visibility == "category"
        assert captured.owner_id == work.quality.human
        assert captured.run_id == measurement.run_id == run_row.run_id == work.failure_run.id
        assert {
            "artifact_id": str(work.failure_report),
            "expected_revision": 1,
        } in captured.required_source_read_set
        shared_ids = run_row.id, measurement.id, captured.id
    with session(work, caller=work.engineer) as stored:
        peer_run = stored.get(VerificationRunVersion, shared_ids[0])
        peer_measurement = stored.get(MeasurementRecord, shared_ids[1])
        peer_capture = stored.get(MeasurementImportCapture, shared_ids[2])
        assert peer_run is not None and peer_measurement is not None and peer_capture is not None
        assert peer_capture.run_id == peer_measurement.run_id == peer_run.run_id
        assert peer_capture.visibility == peer_run.visibility == "category"
        assert peer_capture.owner_id == work.quality.human != work.engineer.human
    shared_capa(work)
    with session(work) as stored:
        basis = followup_owner.load_followup_basis(
            stored, work.quality.ctx, work.setup.product, work.issue_id, work.issue_view["revision"]
        )
        project = stored.get(Project, UUID(work.config["project"]))
        assert project.visibility == "category"
        project_owner = project.owner_id
    assert basis.root_cause_sha256 is None
    assert all(action.completion_sha256 is None for action in basis.actions)
    with session(work, caller=work.engineer) as stored:
        peer_basis = followup_owner.load_followup_basis(
            stored,
            work.engineer.ctx,
            work.setup.product,
            work.issue_id,
            work.issue_view["revision"],
        )
        assert peer_basis == basis
        assert peer_basis.owner_id == work.quality.human != work.engineer.human
    quality_results = results.listing(work)
    peer_results = results.listing(work, caller=work.engineer)
    assert str(shared_ids[2]) in {value["id"] for value in quality_results["captures"]}
    assert str(shared_ids[2]) not in {value["id"] for value in peer_results["captures"]}
    assert str(shared_ids[1]) in {value["id"] for value in peer_results["measurements"]}

    # The request itself is shared from creation; the old private fixture stays intact.
    created_value, create_inputs = change.command(
        work, "change.request.create", {**change.create_payload(work), "visibility": "category"}
    )
    created = post(work.quality, created_value)
    assert created.status_code == 200, created.text
    change_id = create_inputs["change_id"]
    initial, _ = change.current(work, change_id)
    assert initial["visibility"] == "category"
    scope = Scope(
        tenant_id=work.setup.tenant,
        product_id=work.setup.product,
        project_id=UUID(work.config["project"]),
    )
    at, until = now(), now() + timedelta(minutes=15)
    policy_material = PolicyMaterial(
        schema_version="pdos-controlled-change-policy-v1",
        scope=scope,
        purpose=basis.purpose,
        owner_id=project_owner,
        visibility="category",
        publisher_id=work.quality.human,
        required_disciplines=("engineering", "manufacturing"),
        valid_from=at - timedelta(minutes=1),
        valid_until=until,
        nature="synthetic",
    )
    policy_source = native_original(work, policy_material, "Shared synthetic dual-lane policy")
    policy_payload = PolicyImport(
        project_id=scope.project_id,
        purpose=basis.purpose,
        source=policy_source,
        reason="Synthetic scoped publisher fact; no approval or real qualification",
    )
    with session(work) as stored:
        policy_receipt = controlled.import_policy(
            stored,
            work.quality.ctx,
            work.setup.product,
            policy_payload,
            command_id=uuid4(),
            request_key=str(uuid4()),
        )
    assert policy_receipt["subject_type"] == "change_policy_fact"

    items, selection_sources = [], []
    for index, (discipline, kind, configuration, intent_kind) in enumerate(
        (
            (
                "engineering",
                "engineering_configuration",
                work.config["engineering"],
                "new_engineering_configuration",
            ),
            (
                "manufacturing",
                "manufacturing_configuration",
                work.config["process"],
                "new_manufacturing_configuration",
            ),
        )
    ):
        reference = Ref(kind=kind, id=UUID(configuration["subject_id"]), revision=1)
        item = PlanItem(
            id=uuid4(),
            discipline=discipline,
            selection=Selection(
                objects=(reference,),
                units=(f"object:{reference.identity}",),
                conditions=("Fixed shared configuration and the exact CAPA action only",),
                sources=(policy_source,),
            ),
            intent=ControlledIntent(
                id=uuid4(),
                kind=intent_kind,
                basis=(reference,),
                description=f"Plan new {discipline} configuration; execution pending",
            ),
            verification_requirement="New exact configuration/Run plus independent review",
        )
        action = basis.actions[index]
        reason = f"Named synthetic {discipline} applicability of the fixed action and object"
        material = SelectionMaterial(
            schema_version="pdos-controlled-change-selection-v1",
            scope=scope,
            purpose=basis.purpose,
            change_id=UUID(change_id),
            item=item,
            issue_id=work.issue_id,
            capa_id=work.capa_id,
            action_id=action.action_id,
            action_sha256=action.action_sha256,
            executor_id=action.executor_id,
            decider_id=work.quality.human,
            status="applicable",
            valid_until=until,
            reason=reason,
            nature="synthetic",
        )
        items.append(item)
        selection_sources.append(
            (material, native_original(work, material, f"Shared {discipline} applicability"))
        )

    # Sources are complete before the real dependency watermark is captured.
    captured, _ = change.capture(work, change_id)
    impact, _ = change.command(work, "change.impact.compute", captured["impact_payload"])
    saved_impact = post(work.quality, impact)
    assert saved_impact.status_code == 200, saved_impact.text
    analysis, _ = change.current(work, change_id)
    fixed_assessment = deepcopy(analysis["request_snapshot"]["assessments"][-1])
    assessment = ImpactAssessment.model_validate(fixed_assessment)
    assert assessment.unknown and analysis["request_snapshot"]["orders"] == []
    known = {row.node.ref.identity for row in assessment.known}
    assert all(item.selection.objects[0].identity in known for item in items)

    empty_context = order_context(work, change_id)
    assert empty_context["change"]["id"] == str(analysis["id"])
    assert empty_context["change"]["change_id"] == change_id
    assert empty_context["change"]["visibility"] == "category"
    assert empty_context["policy"]["current"] is True
    assert set(empty_context["policy"]["required_disciplines"]) == {
        "engineering",
        "manufacturing",
    }
    assert empty_context["policy"]["nature"] == "synthetic"
    assert empty_context["selections"] == [] and empty_context["missing"]
    assert {value["action_id"] for value in empty_context["actions"]} == {
        str(action.action_id) for action in basis.actions
    }
    object_options = [value["ref"] for value in empty_context["object_options"]]
    assert all(
        item.selection.objects[0].model_dump(mode="json") in object_options for item in items
    )
    selection_receipts = []
    for material, source in selection_sources:
        before_source, fixed = counts(work), change.current(work, change_id)
        candidate = work.quality.client.post(
            f"/v1/categories/{work.setup.category}/products/{work.setup.product}/change-execution/selection-material",
            headers=work.quality.headers,
            json={
                "change_id": change_id,
                "expected_change_revision": analysis["revision"],
                "source": source.model_dump(mode="json"),
            },
        )
        assert candidate.status_code == 200, candidate.text
        assert counts(work) == before_source and change.current(work, change_id) == fixed
        assert candidate.json()["material"] == material.model_dump(mode="json")
        value = candidate.json()["command"]
        assert value["operation"] == "change.selection.decide" and value["source_read_set"]
        assert value["payload"]["visibility"] == "category"
        assert value["payload"]["item"] == material.item.model_dump(mode="json")
        assert value["payload"]["action"]["action_id"] == str(material.action_id)
        assert value["payload"]["action"]["expected_issue_revision"] == basis.issue_revision
        assert value["payload"].get("approval_token") is None
        receipt, _ = accepted(work.quality, value)
        assert receipt["subject_type"] == "change_selection_fact"
        selection_receipts.append(receipt)
    assert change.current(work, change_id)[0]["id"] == analysis["id"]
    selected_context = order_context(work, change_id)
    assert selected_context["change"] == empty_context["change"]
    assert {value["id"] for value in selected_context["selections"]} == {
        receipt["subject_id"] for receipt in selection_receipts
    }
    assert {value["receipt_id"] for value in selected_context["selections"]} == {
        receipt["id"] for receipt in selection_receipts
    }, selected_context["selections"]
    assert all(
        value["current"] is True
        and value["status"] == "applicable"
        and value["source_status"] == "current"
        for value in selected_context["selections"]
    )
    plan = EffectivityPlan(
        id=uuid4(),
        items=tuple(items),
        expires_at=until,
        dispositions=tuple(
            Disposition(
                object=row.node.ref,
                handling="covered_by_plan"
                if any(row.node.ref in item.selection.objects for item in items)
                else "unknown",
                item_ids=tuple(item.id for item in items if row.node.ref in item.selection.objects),
                rationale="Configuration proposal prepared; other impact requires owner review",
                sources=(policy_source,),
            )
            for row in assessment.known
        ),
    )
    value, proposed = inputs(
        work,
        "change.order.prepare",
        {
            "change_id": change_id,
            "expected_change_revision": analysis["revision"],
            "visibility": "category",
            "assessment_id": str(assessment.id),
            "plan": plan.model_dump(mode="json"),
            "reason": "Prepare both explicit lanes while missing impacts remain unknown",
        },
    )
    assert proposed["review"]["unknown"]
    before = counts(work)
    assert before[ChangePolicyFact.__tablename__] == 1
    assert before[ChangeSelectionFact.__tablename__] == 2
    assert before[ChangeOrderRecord.__tablename__] == 0
    order_receipt, prepared = accepted(work.quality, value)
    current, pointer = change.current(work, change_id)
    request = current["request_snapshot"]
    assert request["status"] == "review" and pointer["revision"] == analysis["revision"] + 1
    assert request["assessments"][-1] == fixed_assessment
    assert len(request["orders"]) == 1
    order = request["orders"][0]
    assert set(order["required_disciplines"]) == {"engineering", "manufacturing"}
    assert order["plan"] == plan.model_dump(mode="json")
    assert order["approvals"] == order["implementations"] == order["verifications"] == []
    assert order["closure"] is None
    after = counts(work)
    for model in (ChangeOrderRecord, ChangeRequestVersion, Receipt, Audit, Outbox, Confirmation):
        assert after[model.__tablename__] == before[model.__tablename__] + 1
    for model in (
        ChangePolicyFact,
        ChangeSelectionFact,
        ChangeApprovalRecord,
        ChangeImplementationRecord,
    ):
        assert after[model.__tablename__] == before[model.__tablename__]
    with session(work) as stored:
        policy = stored.get(ChangePolicyFact, UUID(policy_receipt["subject_id"]))
        assert policy.material == policy_material.model_dump(mode="json")
        assert policy.visibility == "category" and policy.owner_id == project_owner
        for receipt, (material, _) in zip(selection_receipts, selection_sources, strict=True):
            selected = stored.get(ChangeSelectionFact, UUID(receipt["subject_id"]))
            assert selected.material == material.model_dump(mode="json")
            assert selected.action_sha256 == material.action_sha256
            assert selected.visibility == "category" and selected.owner_id == work.quality.human
            selected_proof = stored.get(Confirmation, selected.shared_proof_id)
            assert selected_proof.consumed is True
            assert selected_proof.operation == "change.selection.decide"
        recorded = stored.scalar(
            select(ChangeOrderRecord).where(
                ChangeOrderRecord.change_version_id == UUID(order_receipt["subject_id"])
            )
        )
        assert recorded.order_snapshot == order
        assert recorded.content_sha256 == order["content_digest"]
        proof = stored.get(Confirmation, recorded.shared_proof_id)
        assert proof.consumed is True and proof.operation == "change.order.prepare"
    replay = post(work.quality, prepared)
    assert replay.status_code == 200 and replay.json()["id"] == order_receipt["id"]
    assert counts(work) == after
    unchanged_issue = quality.issue_current(work, work.issue_id)
    assert unchanged_issue["id"] == work.issue_view["id"]
    assert unchanged_issue["issue"]["root_cause"] is None
    assert all(
        action["completion"] is None for action in unchanged_issue["issue"]["capa"]["actions"]
    )
    assert unchanged_issue["issue"]["capa"]["effectiveness"] is None
    assert unchanged_issue["issue"]["closure"] is None
