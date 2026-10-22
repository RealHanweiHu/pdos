"""Root-only actual policy/coverage to independent approvals and two saved revisions.

Every business object is created by its genuine command. Production switching,
Pilot/Release, CAPA completion and independent retest are outside this checkpoint.
"""

# ruff: noqa: F811 - imported fixtures register the real dependency tree
from copy import deepcopy
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from quality_execution import fixtures as quality
from quality_execution.fixtures import (  # noqa: F401
    accepted_work,
    launch_work,
    operational_work,
    quality_work,
    ready_work,
    results_work,
)
from sqlalchemy import func, select, text
from test_project_first_plan import accepted, cmd, post

from pdos_next.change_implementation_owner import Occurrence
from pdos_next.change_order_store import (
    ChangeApprovalRecord,
    ChangeImplementationRecord,
    ImplementationCapture,
)
from pdos_next.domain.change_control.rules import NEXT, digest
from pdos_next.domain.change_coverage_owner import trust
from pdos_next.domain.configurations.models import EngineeringConfiguration, ProcessRevision
from pdos_next.models import Audit, Confirmation, Outbox, Receipt, RequestKey, now
from pdos_next.schemas.change_control.contracts import (
    Disposition,
    EffectivityPlan,
    GraphSnapshot,
    ImpactAssessment,
    Ref,
)

from . import approved_configuration_helpers as helper
from . import test_transactions as change


@pytest.fixture
def known_configuration(setup):
    return helper.initial_configuration(setup)


def stamp(value):
    return datetime.fromisoformat(value)


def actual_group(work, receipt, caller, operation, event, *, tier):
    with helper.session(work, caller) as stored:
        saved = stored.get(Receipt, UUID(receipt["id"]))
        assert saved.operation == operation and saved.actor_id == caller.human
        assert saved.requester_id == caller.human
        for model, where in (
            (Audit, (Audit.receipt_id == saved.id, Audit.operation == operation)),
            (Outbox, (Outbox.receipt_id == saved.id, Outbox.type == event)),
            (RequestKey, (RequestKey.receipt_id == saved.id,)),
        ):
            assert stored.scalar(select(func.count()).select_from(model).where(*where)) == 1
        atom_model = ChangeApprovalRecord if tier == "T2" else ChangeImplementationRecord
        atom = stored.scalar(
            select(atom_model).where(atom_model.change_version_id == saved.subject_id)
        )
        assert atom is not None and atom.actor_id == caller.human
        proof = stored.get(Confirmation, atom.shared_proof_id)
        assert proof.consumed is True and proof.operation == operation
        assert proof.actor_id == caller.human and proof.snapshot["proof_tier"] == tier
        assert proof.created_at <= atom.proof_consumed_at <= atom.created_at <= saved.created_at
        return helper.snapshot(atom)


def coverage_declarations(graph):
    """Only real missing prototype paths have explicit bounded original exceptions."""
    paths = []
    for node in graph.nodes:
        expected = NEXT.get(node.ref.kind)
        present = {edge.target.kind for edge in graph.edges if edge.origin == node.ref}
        if node.ref.kind == "spec":
            configurations = {
                edge.target
                for edge in graph.edges
                if edge.origin == node.ref
                and edge.target.kind == "engineering_configuration"
                and edge.source is not None
            }
            present.update(
                edge.target.kind
                for edge in graph.edges
                if edge.origin in configurations and edge.source is not None
            )
        if not expected or present.intersection(expected):
            continue
        assert node.ref.kind in {
            "operation",
            "sop",
            "work_instruction",
            "control_plan",
            "manufacturing_baseline",
        }, node.ref
        reason = (
            "This fixed internal prototype operation is manual motor assembly; "
            "no tooling or fixture is specified. It does not authorize a production process."
            if node.ref.kind == "operation"
            else "This fixed internal prototype document has no PilotRun; the bounded change "
            "only prepares new configurations and later independent retest."
        )
        paths.append(
            {
                "node": node.ref.model_dump(mode="json"),
                "targets": sorted(expected),
                "status": "not_applicable",
                "reason": reason,
            }
        )
    reasons = {
        "customer_samples": (
            "This synthetic internal prototype scope has no customer delivery "
            "or customer sample disposition."
        ),
        "supply_inventory_wip": (
            "No external supply commitment, ERP inventory or WIP transaction is within this "
            "internal configuration revision; existing prototype material records are retained."
        ),
        "production_switch": (
            "This is an internal prototype configuration revision and retest plan; "
            "no production switching or ManufacturingRelease is authorized."
        ),
        "training": (
            "No released production instruction or training assignment exists "
            "in this bounded synthetic internal prototype scope."
        ),
    }
    states = [
        {
            "node": node.ref.model_dump(mode="json"),
            "facet": facet,
            "status": "not_applicable",
            "reason": reason,
        }
        for node in graph.nodes
        for facet, reason in reasons.items()
    ]
    return paths, states


def revisions(work, configuration_source, engineering=None):
    """Only the original draft owner saves actual successors, after both approvals."""
    with helper.session(work, work.setup) as stored:
        if engineering is None:
            previous = stored.get(
                EngineeringConfiguration, UUID(work.config["engineering"]["subject_id"])
            )
            assert previous.owner_id == work.setup.human and previous.revision == 1
            payload = {
                "definition_id": str(previous.definition_id),
                "expected_definition_revision": previous.definition_revision,
                "bom_id": str(previous.bom_id),
                "expected_bom_revision": previous.bom_revision,
                "mechanical": {
                    "system": "Synthetic controlled CAD source",
                    "external_id": "SYN-MOTOR-MOUNT",
                    "revision": "synthetic-v2",
                    "basis": configuration_source.reference,
                },
            }
            operation, family = "engineering.configuration.create", "engineering_configuration"
            inherited_reads = previous.required_source_read_set
        else:
            previous = stored.get(ProcessRevision, UUID(work.config["process"]["subject_id"]))
            assert previous.owner_id == work.setup.human and previous.revision == 1
            payload = {
                "engineering_configuration_id": engineering["subject_id"],
                "expected_engineering_revision": engineering["subject_revision"],
                "site": previous.site,
                "line": previous.line,
                "operations": [
                    {
                        "key": "assembly",
                        "name": "Synthetic revised manual motor assembly",
                        "kind": "assembly",
                        "bom_line_keys": ["motor"],
                        "cycle_time_minutes": "1.5",
                        "acceptance_criterion": (
                            "Retain named mount alignment check before a separate verification Run"
                        ),
                    }
                ],
            }
            operation, family = "npi.process.revise", "process_revision"
            next_engineering = stored.get(EngineeringConfiguration, UUID(engineering["subject_id"]))
            assert next_engineering.revision == engineering["subject_revision"]
            inherited_reads = [
                *previous.required_source_read_set,
                *next_engineering.required_source_read_set,
            ]
        target = {
            **payload,
            "name": "Synthetic approved engineering revision"
            if engineering is None
            else "Synthetic approved manufacturing revision",
            "previous_id": str(previous.id),
            "expected_previous_revision": previous.revision,
            "visibility": "category",
            "reason": "Execute only the independently approved internal configuration plan item",
            "sources": [configuration_source.reference],
        }
        reads = {str(configuration_source.source.id): configuration_source.source.revision}
        for read in inherited_reads:
            identity, revision = str(read["artifact_id"]), read["expected_revision"]
            assert identity not in reads or reads[identity] == revision
            reads[identity] = revision
    command = cmd(work.setup, operation, target)
    command["source_read_set"] = [
        {"artifact_id": identity, "expected_revision": reads[identity]}
        for identity in sorted(reads)
    ]
    receipt, command = accepted(work.setup, command)
    assert receipt["subject_type"] == family and receipt["subject_revision"] == 2
    return receipt, command


def record_one(work, change_id, item, action, output, configuration_source):
    current, _ = change.current(work, change_id)
    order = current["request_snapshot"]["orders"][-1]
    output_kind = (
        "engineering_configuration"
        if item.discipline == "engineering"
        else "manufacturing_configuration"
    )
    occurrence = Occurrence(
        schema_version="pdos-change-implementation-occurrence-v2",
        scope=work.failure_run.scope,
        issue_id=work.issue_id,
        capa_id=work.capa_id,
        action_id=action.action_id,
        action_sha256=action.action_sha256,
        purpose=work.binding.purpose,
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
        sources=(configuration_source.source,),
        outputs=(
            Ref(
                kind=output_kind, id=UUID(output["subject_id"]), revision=output["subject_revision"]
            ),
        ),
        note=(
            "Only the real saved configuration output is recorded; "
            "no effectivity or verification is claimed"
        ),
        nature="synthetic",
    )
    assert stamp(output["created_at"]) < occurrence.occurred_at
    source = helper.original(
        work.setup, occurrence, f"Synthetic actual {item.discipline} implementation occurrence"
    )
    assert occurrence.occurred_at < stamp(source.receipt["created_at"])
    capture_payload = {
        "change_id": change_id,
        "expected_change_revision": current["revision"],
        "visibility": "category",
        "capture_key": str(uuid4()),
        "order_id": order["id"],
        "item_id": str(item.id),
        "source": source.source.model_dump(mode="json"),
    }
    before_capture = helper.counts(work)
    endpoint = (
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}"
        "/change-execution/implementation-captures"
    )
    captured = work.setup.client.post(endpoint, headers=work.setup.headers, json=capture_payload)
    assert captured.status_code == 200, captured.text
    captured = captured.json()
    assert captured["fact_id"] == str(occurrence.implementation_id)
    after_capture = helper.counts(work)
    assert (
        after_capture[ImplementationCapture.__tablename__]
        == before_capture[ImplementationCapture.__tablename__] + 1
    )
    assert all(
        after_capture[key] == count
        for key, count in before_capture.items()
        if key != ImplementationCapture.__tablename__
    )
    repeated = work.setup.client.post(endpoint, headers=work.setup.headers, json=capture_payload)
    assert repeated.status_code == 200 and repeated.json()["id"] == captured["id"]
    assert helper.counts(work) == after_capture
    value, _ = helper.inputs(
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
    receipt, command = accepted(work.setup, value)
    atom = actual_group(
        work,
        receipt,
        work.setup,
        "change.implementation.record",
        "change.implementation_recorded",
        tier="T1",
    )
    with helper.session(work, work.setup) as stored:
        saved = stored.get(ImplementationCapture, UUID(captured["id"]))
        assert saved.occurrence_snapshot == occurrence.model_dump(mode="json")
        assert (
            saved.fact_id == occurrence.implementation_id and saved.executor_id == work.setup.human
        )
        assert saved.fact_snapshot["outputs"] == [
            ref.model_dump(mode="json") for ref in occurrence.outputs
        ]
        assert str(occurrence.outputs[0].id) in saved.output_basis
        assert saved.created_at == stamp(saved.fact_snapshot["received_at"])
        assert (
            stamp(source.receipt["created_at"]) <= saved.created_at < stamp(receipt["created_at"])
        )
        assert atom["capture_id"] == saved.id
    after = helper.counts(work)
    replay = post(work.setup, command)
    assert replay.status_code == 200 and replay.json()["id"] == receipt["id"]
    assert helper.counts(work) == after
    return receipt, command, occurrence


def run_approved_configuration_implementations(work, *, after_issue=None, continuation=None):
    """Keep the actual upstream owners alive for a separately scoped continuation."""
    helper.declare_people(work)
    private = post(
        work.quality,
        cmd(
            work.quality,
            "evidence.artifact.register",
            {
                "title": "Synthetic private receipt boundary",
                "content": "Synthetic private input; not shared with the independent approver",
                "source_label": "Explicit synthetic access-boundary check",
                "visibility": "private",
            },
        ),
    )
    assert private.status_code == 200, private.text
    private_receipt = UUID(private.json()["id"])
    for caller, visible in ((work.quality, True), (work.engineer, False)):
        with helper.session(work, caller) as stored:
            assert (stored.get(Receipt, private_receipt) is not None) is visible
            assert (
                stored.scalar(
                    text("SELECT public.change_receipt_key_bound(:tenant,:product,:receipt)"),
                    {
                        "tenant": work.setup.tenant,
                        "product": work.setup.product,
                        "receipt": private_receipt,
                    },
                )
                is visible
            )
    basis = helper.issue_and_actions(work)
    if after_issue is not None:
        basis = after_issue(work, basis)
    created, create_input = change.command(
        work, "change.request.create", {**change.create_payload(work), "visibility": "category"}
    )
    response = post(work.quality, created)
    assert response.status_code == 200, response.text
    change_id = create_input["change_id"]
    until = now() + timedelta(hours=1)
    scope, policy_source, selections = helper.policy_and_items(work, change_id, basis, until)
    items = tuple(material.item for material, _ in selections)
    config_source = helper.original(
        work.setup,
        {
            "purpose": basis.purpose,
            "issue_id": str(basis.issue_id),
            "capa_id": str(basis.capa_id),
            "executor_id": str(work.setup.human),
            "engineering_action_id": str(basis.actions[0].action_id),
            "manufacturing_action_id": str(basis.actions[1].action_id),
            "instruction": (
                "After both independent approvals, save a mechanical mount design revision and "
                "then a manufacturing revision bound to that exact new engineering configuration. "
                "Preserve the motor BOM and retain all existing sample/Run evidence."
            ),
            "manufacturing": (
                "Manual assembly, motor BOM line; cycle time 1.5 minutes with a named alignment "
                "check. No production switch, new fixture or tooling is specified."
            ),
        },
        "Synthetic proposed configuration revision instructions",
    )
    unknown, _ = change.capture(work, change_id)
    graph = GraphSnapshot.model_validate(unknown["capture"]["graph"])
    assert all(value.status == "unknown" for value in graph.coverage)
    assert any(
        edge.origin.kind == "part" and edge.target.kind == "operation" for edge in graph.edges
    )
    disposition_rows = []
    for node in graph.nodes:
        linked = tuple(
            item.id
            for item in items
            if node.ref in item.selection.objects
            or (node.ref.kind == "operation" and item.discipline == "manufacturing")
        )
        disposition_rows.append(
            {
                "object": node.ref.model_dump(mode="json"),
                "handling": "covered_by_plan" if linked else "reviewed_no_change",
                "item_ids": [str(identity) for identity in linked],
                "rationale": (
                    "Revise this fixed configuration/assembly through the named plan item"
                    if linked
                    else "Retain this exact existing prototype, failure or design reference; "
                    "this bounded internal revision preserves its history and disposition"
                ),
            }
        )
    reviewed = helper.original(
        work.quality,
        {
            "change_id": change_id,
            "purpose": basis.purpose,
            "dispositions": disposition_rows,
            "scope": (
                "Synthetic internal prototype configuration revision only; no PilotRun, "
                "production switching, customer delivery, ERP effectivity or release"
            ),
        },
        "Synthetic named exact per-object dispositions",
    )
    paths, facet_states = coverage_declarations(graph)
    helper.publish_coverage(
        work, scope, change_id, graph, until, paths=paths, facet_states=facet_states
    )
    try:
        captured, _ = change.capture(work, change_id)
        fixed_graph = GraphSnapshot.model_validate(captured["capture"]["graph"])
        assert all(value.status in {"complete", "not_applicable"} for value in fixed_graph.coverage)
        impact, _ = change.command(work, "change.impact.compute", captured["impact_payload"])
        response = post(work.quality, impact)
        assert response.status_code == 200, response.text
        analysis, _ = change.current(work, change_id)
        assessment = ImpactAssessment.model_validate(
            analysis["request_snapshot"]["assessments"][-1]
        )
        assert assessment.unknown == ()
        assert {row.node.ref.identity for row in assessment.known} == {
            node.ref.identity for node in graph.nodes
        }
        for material, source in selections:
            response = work.quality.client.post(
                f"/v1/categories/{work.setup.category}/products/{work.setup.product}/change-execution/selection-material",
                headers=work.quality.headers,
                json={
                    "change_id": change_id,
                    "expected_change_revision": analysis["revision"],
                    "source": source.source.model_dump(mode="json"),
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["material"] == material.model_dump(mode="json")
            accepted(work.quality, response.json()["command"])
        plan = EffectivityPlan(
            id=uuid4(),
            items=items,
            expires_at=until,
            dispositions=tuple(
                Disposition.model_validate(
                    {**row, "sources": [reviewed.source.model_dump(mode="json")]}
                )
                for row in disposition_rows
            ),
        )
        value, review = helper.inputs(
            work,
            work.quality,
            "change.order.prepare",
            {
                "change_id": change_id,
                "expected_change_revision": analysis["revision"],
                "visibility": "category",
                "assessment_id": str(assessment.id),
                "plan": plan.model_dump(mode="json"),
                "reason": (
                    "Prepare internal engineering and manufacturing revisions after coverage review"
                ),
            },
        )
        assert not review["unknown"]
        prepared, _ = accepted(work.quality, value)
        prepared_row, _ = change.current(work, change_id)
        fixed_order = deepcopy(prepared_row["request_snapshot"]["orders"][-1])
        assert fixed_order["approvals"] == fixed_order["implementations"] == []
        before = helper.counts(work)
        self_approve = cmd(
            work.quality,
            "change.order.approve",
            {
                "change_id": change_id,
                "expected_change_revision": prepared_row["revision"],
                "visibility": "category",
                "discipline": "engineering",
                "text": "Attempt requester self approval must remain forbidden",
                "expires_at": until.isoformat(),
                "sources": [reviewed.source.model_dump(mode="json")],
            },
        )
        rejected = work.quality.client.post(
            f"/v1/categories/{work.setup.category}/products/{work.setup.product}/change-execution/inputs",
            headers=work.quality.headers,
            json=self_approve,
        )
        assert rejected.status_code == 403 and rejected.json()["code"] == "FORBIDDEN_SCOPE"
        assert rejected.json()["detail"]["reason"] == "SELF_APPROVAL_FORBIDDEN"
        assert helper.counts(work) == before
        approvals = []
        for discipline, caller in (("engineering", work.engineer), ("manufacturing", work.setup)):
            current, _ = change.current(work, change_id)
            value, _ = helper.inputs(
                work,
                caller,
                "change.order.approve",
                {
                    "change_id": change_id,
                    "expected_change_revision": current["revision"],
                    "visibility": "category",
                    "discipline": discipline,
                    "text": (
                        f"Named {discipline} approval of exact content "
                        f"{fixed_order['content_digest']}"
                    ),
                    "expires_at": until.isoformat(),
                    "sources": [
                        reviewed.source.model_dump(mode="json"),
                        policy_source.source.model_dump(mode="json"),
                    ],
                },
            )
            receipt, _ = accepted(caller, value)
            atom = actual_group(
                work, receipt, caller, "change.order.approve", "change.approved", tier="T2"
            )
            assert atom["discipline"] == discipline
            assert atom["approval_snapshot"]["content_digest"] == fixed_order["content_digest"]
            approvals.append(receipt)
        assert work.quality.human != work.engineer.human != work.setup.human != work.quality.human
        assert (
            stamp(prepared["created_at"])
            < stamp(approvals[0]["created_at"])
            < stamp(approvals[1]["created_at"])
        )
        approved, _ = change.current(work, change_id)
        approved_order = deepcopy(approved["request_snapshot"]["orders"][-1])
        assert approved["status"] == "approved"
        assert {value["actor_id"] for value in approved_order["approvals"]} == {
            str(work.engineer.human),
            str(work.setup.human),
        }
        # Never create the manufacturing output before the engineering fact is saved.
        engineering, engineering_command = revisions(work, config_source)
        assert stamp(approvals[-1]["created_at"]) < stamp(engineering["created_at"])
        engineering_record, engineering_record_command, engineering_occurrence = record_one(
            work, change_id, items[0], basis.actions[0], engineering, config_source
        )
        after_engineering, _ = change.current(work, change_id)
        assert len(after_engineering["request_snapshot"]["orders"][-1]["implementations"]) == 1
        manufacturing, manufacturing_command = revisions(work, config_source, engineering)
        assert stamp(engineering_record["created_at"]) < stamp(manufacturing["created_at"])
        manufacturing_record, manufacturing_record_command, manufacturing_occurrence = record_one(
            work, change_id, items[1], basis.actions[1], manufacturing, config_source
        )
        final, _ = change.current(work, change_id)
        order = final["request_snapshot"]["orders"][-1]
        assert final["status"] == "implementing"
        assert order["approvals"] == approved_order["approvals"]
        assert order["content_digest"] == fixed_order["content_digest"]
        assert order["plan"] == plan.model_dump(mode="json")
        assert {value["id"] for value in order["implementations"]} == {
            str(engineering_occurrence.implementation_id),
            str(manufacturing_occurrence.implementation_id),
        }
        assert all(value["outcome"] == "succeeded" for value in order["implementations"])
        assert order["effectivity"] == order["verifications"] == [] and order["closure"] is None
        with helper.session(work, work.setup) as stored:
            new_engineering = stored.get(EngineeringConfiguration, UUID(engineering["subject_id"]))
            new_process = stored.get(ProcessRevision, UUID(manufacturing["subject_id"]))
            assert new_engineering.previous_id == UUID(work.config["engineering"]["subject_id"])
            assert new_process.previous_id == UUID(work.config["process"]["subject_id"])
            assert new_engineering.revision == new_process.revision == 2
            assert new_process.engineering_configuration_id == new_engineering.id
            assert new_process.engineering_revision == new_engineering.revision
            assert new_engineering.owner_id == new_process.owner_id == work.setup.human
        after = helper.counts(work)
        for caller, command, receipt in (
            (work.setup, engineering_command, engineering),
            (work.setup, manufacturing_command, manufacturing),
            (work.setup, engineering_record_command, engineering_record),
            (work.setup, manufacturing_record_command, manufacturing_record),
        ):
            response = post(caller, command)
            assert response.status_code == 200 and response.json()["id"] == receipt["id"]
        assert helper.counts(work) == after
        assert quality.issue_current(work, work.issue_id)["id"] == work.issue_view["id"]
        assert digest(final["request_snapshot"]["assessments"][-1]) == digest(assessment)
        if continuation is not None:
            return continuation(
                work,
                basis,
                (
                    (engineering_record, engineering_occurrence),
                    (manufacturing_record, manufacturing_occurrence),
                ),
                engineering,
                manufacturing,
            )
    finally:
        trust.disable(work.setup.engine, scope=scope)


def test_real_coverage_independent_approvals_then_two_actual_configuration_implementations(
    quality_work,
):
    run_approved_configuration_implementations(quality_work)
