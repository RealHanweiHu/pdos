"""Callable continuation of the root-only real approved-configuration PG chain.

These helpers create synthetic observations through the existing original/import
and command owners. They do not grant people qualifications, patch business ports,
record effectiveness, backdate completion, or close the Issue. Root must declare
the completion executor, test executor/person resource and independent reviewer
before the retained signings and keep the upstream object-store/client/issuer
fixtures alive for the whole call.
"""

from contextvars import ContextVar
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from time import sleep
from types import SimpleNamespace
from uuid import UUID, uuid4

from build_operational_facts import fixtures as operational
from build_start import test_transactions as start
from quality_execution import fixtures as quality
from quality_followup_transactions import fixtures as followup
from sqlalchemy import select
from test_build_execution import (
    actual_command,
    allocation_command,
    execution_view,
    output_command,
)
from test_builds import build_command
from test_builds import listed as builds
from test_project_first_plan import accepted, cmd, post
from test_verification_execution import command as preparation_command
from test_verification_execution import payload as preparation_payload
from test_verification_execution import row_for
from verification_handoff import fixtures as handoff
from verification_launch import fixtures as launch
from verification_launch.test_multi_run_chain import launch_command
from verification_launch.test_multi_run_quality_chain import measurement_rows
from verification_results import fixtures as results

from change_execution import approved_configuration_helpers as approved
from pdos_next.change_implementation_owner import Occurrence, original_occurrence
from pdos_next.change_order_store import ChangeImplementationRecord, ImplementationCapture
from pdos_next.domain.build_operational_facts import service as operational_owner
from pdos_next.domain.build_operational_facts.models import OperationalAsset
from pdos_next.domain.build_operational_facts.schemas import (
    DecisionProof,
    OperationalScope,
    ResourceInput,
)
from pdos_next.domain.builds import service as build_owner
from pdos_next.domain.builds.schemas import BuildCreatePayload
from pdos_next.domain.configurations.service import _merge_reads
from pdos_next.domain.quality_followup.schemas import CompletionFact
from pdos_next.domain.test_resources import service as test_resources
from pdos_next.domain.test_resources.models import TestResourceFact
from pdos_next.domain.test_resources.schemas import TestPlanBinding, TestResourceFactInput
from pdos_next.domain.verification_handoff.models import ActualMethodApplicability
from pdos_next.domain.verification_launch.schemas import ExecutionPlan
from pdos_next.models import Receipt, now
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import digest
from pdos_next.test_resource_import import import_test_resource_fact


def _stamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _caller(work, caller):
    """Keep the real identity/headers; use the live original-store HTTP client."""
    assert caller.tenant == work.setup.tenant and caller.category == work.setup.category
    assert caller.product == work.setup.product
    assert caller.ctx.actor_id == caller.ctx.requester_id == caller.human
    assert caller.ctx.run_id is None
    return SimpleNamespace(**{**vars(caller), "client": work.setup.client})


def _implementation_source(work, executor, receipt, occurrence):
    """Find the one actual capture, then verify its fixed first original source.

    ``prepare_capture`` stores input.source first; this is its original position,
    not a choice of the first/latest row. All scope and immutable atom identities
    below must match before the normal completion owner rechecks the full proof.
    """
    assert type(occurrence) is Occurrence
    with approved.session(work, executor) as stored:
        captures = stored.scalars(
            select(ImplementationCapture).where(
                ImplementationCapture.tenant_id == work.setup.tenant,
                ImplementationCapture.product_id == work.setup.product,
                ImplementationCapture.project_id == occurrence.scope.project_id,
                ImplementationCapture.change_id == occurrence.change_id,
                ImplementationCapture.order_id == occurrence.order_id,
                ImplementationCapture.item_id == occurrence.item_id,
                ImplementationCapture.fact_id == occurrence.implementation_id,
                ImplementationCapture.executor_id == executor.human,
            )
        ).all()
        assert len(captures) == 1, "Need one exact saved implementation capture"
        capture = captures[0]
        assert capture.occurrence_snapshot == occurrence.model_dump(mode="json")
        atoms = stored.scalars(
            select(ChangeImplementationRecord).where(
                ChangeImplementationRecord.tenant_id == work.setup.tenant,
                ChangeImplementationRecord.product_id == work.setup.product,
                ChangeImplementationRecord.project_id == occurrence.scope.project_id,
                ChangeImplementationRecord.capture_id == capture.id,
                ChangeImplementationRecord.fact_id == occurrence.implementation_id,
                ChangeImplementationRecord.item_id == occurrence.item_id,
                ChangeImplementationRecord.order_id == occurrence.order_id,
            )
        ).all()
        assert len(atoms) == 1, "Occurrence must have its actual saved command atom"
        assert atoms[0].fact_snapshot == capture.fact_snapshot
        saved = stored.get(Receipt, UUID(receipt["id"]))
        assert saved is not None and saved.operation == "change.implementation.record"
        assert saved.actor_id == saved.requester_id == executor.human
        assert saved.subject_type == "change_request"
        assert saved.subject_id == atoms[0].change_version_id
        assert saved.subject_revision == receipt["subject_revision"]
        assert saved.created_at == _stamp(receipt["created_at"])
        source = SourceRef.model_validate(capture.sources[0])
        raw, artifact = original_occurrence(stored, executor.ctx, work.setup.product, source)
        assert raw == occurrence and occurrence.occurred_at <= artifact.created_at
        assert artifact.created_at <= capture.created_at <= _stamp(receipt["created_at"])
        return source


def complete_implemented_actions(work, basis, implementations, *, executor):
    """One real T1 batch for (implementation receipt, Occurrence) pairs.

    If a first named root cause is needed it must be recorded with the genuine T2
    command before this call: the kernel will not add it after all actions finish.
    No previous investigation completion or classification is reused here.
    """
    executor = _caller(work, executor)
    acting = SimpleNamespace(**{**vars(work), "quality": executor})
    before = followup.fixed_issue(acting)
    assert before.issue_id == basis.issue_id and basis.capa_id == work.capa_id
    actions = {action.action_id: action for action in basis.actions}
    originals, completions, fixed_implementations = [], [], tuple(implementations)
    assert fixed_implementations
    assert len({occ.action_id for _, occ in fixed_implementations}) == len(fixed_implementations)
    saved_actions = {UUID(a["id"]): a for a in before.issue_snapshot["capa"]["actions"]}
    for receipt, occurrence in fixed_implementations:
        action = actions[occurrence.action_id]
        assert occurrence.scope == basis.scope and occurrence.purpose == basis.purpose
        assert occurrence.issue_id == basis.issue_id and occurrence.capa_id == basis.capa_id
        assert occurrence.action_sha256 == action.action_sha256
        assert occurrence.executor_id == action.executor_id == executor.human
        assert occurrence.outcome == "succeeded" and occurrence.nature == basis.nature
        assert saved_actions[action.action_id]["completion"] is None
        source = _implementation_source(work, executor, receipt, occurrence)
        at = now()
        assert at > _stamp(receipt["created_at"]) >= occurrence.occurred_at
        observation = {
            "issue_id": str(basis.issue_id),
            "capa_id": str(basis.capa_id),
            "action_id": str(action.action_id),
            "executor_id": str(executor.human),
            "operation": "quality.capa.actions.complete",
            "occurred_at": at.isoformat(),
            "original_timezone": "UTC",
            "purpose": basis.purpose,
            "text": (
                f"Personally completed approved configuration implementation "
                f"{occurrence.implementation_id}; its saved outputs are "
                + ", ".join(f"{ref.kind}:{ref.id}@{ref.revision}" for ref in occurrence.outputs)
                + ". Effectiveness and independent retest are not concluded."
            ),
        }
        # Validate the exact nine fields before storing their actual original.
        CompletionFact.model_validate(observation)
        original = approved.original(
            executor, observation, "Synthetic personally observed configuration-action completion"
        )
        assert at < _stamp(original.receipt["created_at"])
        originals.append(original)
        completions.append(
            {
                "id": str(action.action_id),
                "text": observation["text"],
                "executor_id": str(executor.human),
                "evidence": [
                    source.model_dump(mode="json"),
                    original.source.model_dump(mode="json"),
                ],
                "at": {
                    "occurred_at": observation["occurred_at"],
                    "original_timezone": "UTC",
                    "source": original.source.model_dump(mode="json"),
                },
            }
        )
    value = followup.command(
        acting,
        "quality.capa.actions.complete",
        {
            "issue_id": str(basis.issue_id),
            "expected_issue_revision": before.revision,
            "completions": completions,
        },
    )
    receipt, command = accepted(executor, value)
    after = followup.fixed_issue(acting)
    assert after.revision == before.revision + 1
    assert after.issue_snapshot["capa"]["effectiveness"] is None
    assert after.issue_snapshot["closure"] is None
    assert after.issue_snapshot["root_cause"] == before.issue_snapshot["root_cause"]
    assessments = after.source_basis["completion_assessments"]
    assert {value["action_id"] for value in assessments} == {value["id"] for value in completions}
    for assessment in assessments:
        assert assessment["classification"] == "formal_change"
        assert assessment["allowed"] is assessment["current"] is True
        assert all(source["kind"] == "artifact" for source in assessment["sources"])
        actual_receipt = next(
            receipt
            for receipt, occurrence in fixed_implementations
            if str(occurrence.action_id) == assessment["action_id"]
        )
        assert len(assessment["owner_proofs"]) == 1
        proof = assessment["owner_proofs"][0]
        assert (proof["id"], proof["revision"], proof["receipt_id"]) == (
            actual_receipt["subject_id"],
            actual_receipt["subject_revision"],
            actual_receipt["id"],
        )
    for completion in completions:
        saved = next(
            row for row in after.issue_snapshot["capa"]["actions"] if row["id"] == completion["id"]
        )
        assert saved["completion"]["at"]["source"] == completion["at"]["source"]
    return SimpleNamespace(
        receipt=receipt,
        command=command,
        issue=after,
        originals=tuple(originals),
        completions=tuple(completions),
        implementations=fixed_implementations,
    )


def _new_operational_facts(work, cleanup):
    """Use the S2 synthetic publisher with distinct actual declared assets/pool."""
    work.resource_id = uuid4()
    work.decision_ids = {kind: uuid4() for kind in ("acceptance", "calibration")}
    work.named_current = True
    work.payload = operational.fact_payload(work, pool_id=f"SYN-RETEST-{work.build_id}")

    def named_decision(session, ctx, binding, resource, decision, checked_at):
        current = (
            work.named_current
            and binding
            == {
                "build_id": work.build_id,
                "build_revision": 1,
                "project_id": work.config["project"],
                "scope": work.scope.model_dump(mode="json"),
                "engineering_configuration_id": work.config["engineering"]["subject_id"],
                "engineering_configuration_revision": work.config["engineering"][
                    "subject_revision"
                ],
                "manufacturing_configuration_id": work.config["process"]["subject_id"],
                "manufacturing_configuration_revision": work.config["process"]["subject_revision"],
            }
            and resource.id == work.resource_id
            and work.decision_ids.get(decision.kind) == decision.named_decision_id
            and decision.actor_id == work.setup.human
        )
        return DecisionProof(
            current=current,
            facts_revision=digest(
                {"decision": decision.model_dump(mode="json"), "current": current}
            ),
            valid_until=decision.valid_until,
        )

    work.issuer = operational_owner.configure_local_synthetic(
        work.setup.engine,
        tenant_id=work.setup.tenant,
        product_id=work.setup.product,
        project_id=UUID(work.config["project"]),
        key=f"synthetic-retest-{work.build_id}",
        enabled=True,
        test_marker_verified=True,
        verify_named_decision=named_decision,
    )
    cleanup.callback(operational_owner.disable_issuer, work.setup.engine, work.issuer.key)
    work.operational_receipt = operational.imported(work)


def create_new_build(work, engineering, manufacturing, *, cleanup):
    """Create/start a new Build using the saved revisions and the old Build link."""
    continuation = SimpleNamespace(**vars(work))
    # A separate native observation source keeps the S2 helper's exact reference
    # truthful; all actual configuration/definition sources are merged separately.
    event_source = handoff.artifact(work.setup, "Synthetic requirement is unverified")
    continuation.config = {
        "source": event_source["artifact_id"],
        "project": work.config["project"],
        "engineering": deepcopy(engineering),
        "process": deepcopy(manufacturing),
    }
    value = build_command(
        work.setup,
        continuation.config,
        previous_build_id=work.build_id,
        name="Synthetic separate approved-configuration verification Build",
        purpose=work.binding.purpose,
        verification_objectives=(
            "Retest the fixed failure with the actual new linked configurations"
        ),
    )
    with approved.session(work, work.setup) as stored:
        project, eng, mfg, reads = build_owner._linked(
            stored,
            work.setup.ctx,
            work.setup.product,
            BuildCreatePayload.model_validate(value["payload"]),
        )
        assert eng["revision"] == engineering["subject_revision"]
        assert mfg["revision"] == manufacturing["subject_revision"]
        assert engineering["subject_id"] != work.config["engineering"]["subject_id"]
        assert manufacturing["subject_id"] != work.config["process"]["subject_id"]
        value["payload"]["expected_project_revision"] = project.revision
    continuation.config["reads"] = _merge_reads(reads, [event_source])
    value["source_read_set"] = continuation.config["reads"]
    receipt, continuation.build_command = accepted(work.setup, value)
    continuation.build_id = receipt["subject_id"]
    continuation.build_receipt = receipt
    saved = next(row for row in builds(work.setup)["items"] if row["id"] == continuation.build_id)
    assert saved["previous_build_id"] == work.build_id
    assert saved["engineering_configuration"]["id"] == engineering["subject_id"]
    assert saved["manufacturing_configuration"]["id"] == manufacturing["subject_id"]
    value = cmd(
        work.setup,
        "build.readiness.compute",
        {"build_id": continuation.build_id, "expected_build_revision": saved["revision"]},
    )
    value["source_read_set"] = continuation.config["reads"]
    response = post(work.setup, value)
    assert response.status_code == 200, response.text
    saved = next(row for row in builds(work.setup)["items"] if row["id"] == continuation.build_id)
    continuation.config["result"] = saved["readiness"]["result"]
    continuation.at = now()
    continuation.scope = OperationalScope(
        purpose=work.binding.purpose,
        quantity=saved["planned_quantity"],
        unit=saved["unit"],
        site=work.scope.site,
        window={
            "start": continuation.at - timedelta(minutes=1),
            "finish": continuation.at + timedelta(minutes=20),
            "original_timezone": "UTC",
        },
    )
    _new_operational_facts(continuation, cleanup)
    # The existing assessment helper reads its real preparation owner; execute
    # still goes through the actual shared HTTP command/T1 path.
    assessment = start.assessment_command(continuation)
    response = post(work.setup, assessment)
    assert response.status_code == 200, response.text
    continuation.assessment = next(
        row
        for row in start.view(continuation)["assessments"]
        if row["id"] == response.json()["subject_id"]
    )
    authorizations = {}
    for role in ("engineering", "manufacturing"):
        view = start.view(continuation)
        caps = view["capabilities_by_build"][continuation.build_id]
        value = start.authorization_command(continuation, role)
        value["source_read_set"] = _merge_reads(
            caps["required_source_read_set"],
            caps["authority"][f"{role}_authorize"]["required_source_read_set"],
            [event_source],
        )
        receipt, _ = accepted(work.setup, value)
        authorizations[role] = next(
            row
            for row in start.view(continuation)["authorizations"]
            if row["id"] == receipt["subject_id"]
        )
    at = now()
    original = approved.original(
        work.setup,
        {
            "build_id": continuation.build_id,
            "occurred_at": at.isoformat(),
            "purpose": continuation.scope.purpose,
            "engineering_configuration_id": engineering["subject_id"],
            "manufacturing_configuration_id": manufacturing["subject_id"],
        },
        "Synthetic separate Build actual start",
    )
    value = cmd(
        work.setup,
        "build.start",
        {
            "assessment_id": continuation.assessment["id"],
            "expected_assessment_revision": continuation.assessment["revision"],
            "expected_assessment_sha256": continuation.assessment["snapshot_sha256"],
            "engineering_authorization_id": authorizations["engineering"]["id"],
            "expected_engineering_authorization_revision": authorizations["engineering"][
                "revision"
            ],
            "manufacturing_authorization_id": authorizations["manufacturing"]["id"],
            "expected_manufacturing_authorization_revision": authorizations["manufacturing"][
                "revision"
            ],
            "occurred_at": at.isoformat(),
            "occurred_timezone": "UTC",
            "event_source": original.reference,
            "reason": (
                "Start only this new Build after its actual assessment and two named approvals"
            ),
        },
    )
    caps = start.view(continuation)["capabilities_by_build"][continuation.build_id]
    value["source_read_set"] = _merge_reads(
        caps["required_source_read_set"],
        caps["authority"]["start"]["required_source_read_set"],
        *(row["required_source_read_set"] for row in authorizations.values()),
        [original.reference],
    )
    continuation.start_receipt, continuation.start_command = accepted(work.setup, value)
    return continuation


def create_actual_samples(work, *, cavities=("A", "B")):
    """Record new actual configuration, observed output and fresh identities."""
    assert cavities and len(set(cavities)) == len(cavities)
    planned = {**work.config, "build": work.build_receipt}
    value = actual_command(
        work.setup,
        planned,
        observed_at=now().isoformat(),
        expected_actual_engineering_revision=work.config["engineering"]["subject_revision"],
        expected_actual_manufacturing_revision=work.config["process"]["subject_revision"],
    )
    value["source_read_set"] = work.config["reads"]
    work.actual_receipt, _ = accepted(work.setup, value)
    value = output_command(
        work.setup,
        planned,
        work.actual_receipt,
        units=len(cavities),
        observation={
            "system": "Explicit synthetic approved-configuration continuation",
            "external_id": str(uuid4()),
            "nature": "synthetic",
            "occurred_at": now().isoformat(),
        },
    )
    value["source_read_set"] = work.config["reads"]
    work.output_receipt, _ = accepted(work.setup, value)
    value = allocation_command(
        work.setup,
        planned,
        work.output_receipt,
        samples=[{"label": f"SYN-RETEST-{uuid4()}", "cavity": cavity} for cavity in cavities],
    )
    value["source_read_set"] = work.config["reads"]
    work.allocation_receipt, _ = accepted(work.setup, value)
    work.samples = [
        row
        for row in execution_view(work.setup)["samples"]
        if row["allocation_id"] == work.allocation_receipt["subject_id"]
    ]
    assert len(work.samples) == len(cavities)
    for sample in work.samples:
        assert sample["build_id"] == work.build_id
        handoff.readiness(work, sample)
    return work


def create_new_request(work, *, method_dossier):
    """Reuse the explicit S2 dossier, with fresh method decisions on new pairs."""
    planned = {
        **work.config,
        "build": work.build_receipt,
        "preparation_source": method_dossier["artifact_id"],
    }
    lines = (
        "Synthetic drawing",
        "Synthetic limits 9.5 to 10.5",
        "Synthetic report basis",
    )
    refs = [{**method_dossier, "line": i + 1, "quote": line} for i, line in enumerate(lines)]
    payload = preparation_payload(planned, purpose=work.scope.purpose)
    payload["items"][0].update(
        drawing=refs[0],
        method=refs[1],
        criterion={"lower": "9.5", "upper": "10.5", "source": refs[1]},
        sample_count=len(work.samples),
        cavities=[row["cavity"] for row in work.samples],
    )
    payload["documents"][0]["source"] = refs[2]
    payload["sources"] = [refs[0]]
    value = preparation_command(
        work.setup, planned, payload, reads=_merge_reads(work.config["reads"], refs)
    )
    receipt, _ = accepted(work.setup, value)
    prepared = row_for(work.setup, receipt)
    value = cmd(
        work.engineer,
        "verification.request.create",
        {
            "request_id": str(uuid4()),
            "preparation_id": prepared["id"],
            "expected_preparation_revision": prepared["revision"],
            "preparation_sha256": prepared["sha256"],
            "reason": "Separate formal request for the actual new configuration and new samples",
        },
    )
    value["source_read_set"] = prepared["required_source_read_set"]
    # Creating the formal request is the existing qualified T0 command, as in
    # the S2 handoff fixture; its method and reception decisions remain T1.
    response = post(work.engineer, value)
    assert response.status_code == 200, response.text
    work.request_receipt = response.json()
    work.request_id = value["payload"]["request_id"]
    work.actual_source = refs[1]
    value = handoff.command(
        work,
        "verification.method.prepare",
        {
            "assessments": [
                {
                    "item_id": "dimension",
                    "status": "applicable",
                    "conditions": [],
                    "reason": (
                        "Named review of the same fixed limits for this new planned configuration"
                    ),
                    "sources": [refs[1]],
                }
            ]
        },
    )
    accepted(work.quality, value)
    accepted(work.quality, handoff.actual_method(work))
    accepted(work.engineer, handoff.handoff(work))
    accepted(work.quality, handoff.handoff(work, operation="verification.handoff.accept"))
    work.accepted_request = handoff.current(work)
    assert len(work.accepted_request["accepted_coverage"]) == len(work.samples)
    return work


def _prepare_new_run(work, monkeypatch, cleanup, *, test_person_resource):
    """Bind actual new pairs without the batched fixture's capacity-two assumption.

    Root supplies the person's original physical declaration. A new mirror is
    created only by the actual new Run import; an existing mirror must match it
    exactly. Occupancy stays intact and Start still uses the actual capacity
    owner. Receiving old results implies no release or greater capacity.
    """
    from pdos_next import clock

    person_resource = ResourceInput.model_validate(
        test_person_resource.model_dump(mode="python")
        if isinstance(test_person_resource, ResourceInput)
        else test_person_resource
    )
    assert person_resource.resource.id == work.quality.human
    assert person_resource.resource.kind == "person"
    assert person_resource.resource.revision >= 1
    assert person_resource.lifecycle == "active"
    assert person_resource.capacity is not None and person_resource.calendar is not None
    assert person_resource.sources and person_resource.calendar_sources
    assert work.scope.purpose in person_resource.purposes
    assert "test.run.start" in person_resource.operation_ids
    person_physical = test_resources.physical_projection(person_resource)
    run_work = SimpleNamespace(**vars(work))
    view, request = handoff.listing(work), handoff.current(work)
    coverage = request["accepted_coverage"]
    samples = {row["id"]: row for row in view["reference_samples"]}
    methods = {
        (row["sample"]["id"], row["item_id"]): row
        for row in view["actual_methods"]
        if row["current"] and row["request_id"] == work.request_id
    }
    with approved.session(work, work.quality) as stored:
        old = stored.get(TestResourceFact, work.test_fact_id)
        assert old is not None and old.tenant_id == work.setup.tenant
        assert old.product_id == work.setup.product
        assert old.run_id == work.binding.run_id
        assert old.owner_id == work.binding.executor_id
        previous = TestResourceFactInput.model_validate(old.data)
        assert previous.binding == work.binding
        person = stored.get(OperationalAsset, work.quality.human)
        if person is not None:
            assert person.tenant_id == work.setup.tenant and person.kind == "resource"
            assert person.data["state"] == "active"
            assert person.revision == person_resource.resource.revision
            assert test_resources.physical_projection(person.data["value"]) == person_physical
        hashes = {
            key: stored.get(ActualMethodApplicability, UUID(value["id"])).snapshot_sha256
            for key, value in methods.items()
        }
    conditions = {row["conditions"] for row in request["request_snapshot"]["items"]}
    assert conditions == {"23 C, dry"}
    at, run_id = now(), uuid4()
    monkeypatch.setattr(clock, "_clock", ContextVar("continuation_plan_clock", default=lambda: at))
    reference = deepcopy(work.actual_source)
    binding = TestPlanBinding.model_validate(
        {
            "run_id": run_id,
            "request_id": work.request_id,
            "accepted_request_id": request["id"],
            "accepted_request_revision": request["revision"],
            "build_id": work.build_id,
            "project_id": work.config["project"],
            "purpose": request["request_snapshot"]["purpose"],
            "executor_id": work.quality.human,
            "window": {
                "start": at + timedelta(seconds=1),
                "finish": at + timedelta(minutes=12),
                "original_timezone": "UTC",
            },
            "environment": "Synthetic finite lab",
            "conditions": next(iter(conditions)),
            "equipment": reference,
            "calibration": reference,
            "pairs": [
                {
                    "sample": samples[pair["sample_id"]]["reference"],
                    "item_id": pair["item_id"],
                    "method_id": methods[pair["sample_id"], pair["item_id"]]["id"],
                    "method_revision": methods[pair["sample_id"], pair["item_id"]]["revision"],
                    "method_sha256": hashes[pair["sample_id"], pair["item_id"]],
                    "destructive": next(
                        item["destructive"]
                        for item in request["request_snapshot"]["items"]
                        if item["id"] == pair["item_id"]
                    ),
                }
                for pair in coverage
            ],
        }
    )
    equipment = next(row for row in previous.resources if row.resource.kind == "equipment")
    equipment_physical = test_resources.physical_projection(equipment)
    equipment_physical["resource"] = {"id": str(uuid4()), "revision": 1, "kind": "equipment"}
    decisions, resource_inputs = {}, []
    for physical, fact_kinds, declaration in (
        (equipment_physical, ("acceptance", "calibration"), None),
        (person_physical, ("qualification",), person_resource),
    ):
        resource = deepcopy(physical["resource"])
        sources = (
            [value.model_dump(mode="json") for value in declaration.sources]
            if declaration is not None
            else [reference]
        )
        facts = []
        for kind in fact_kinds if declaration is None or not declaration.facts else ():
            decision_id = uuid4()
            decisions[decision_id] = (UUID(resource["id"]), kind)
            facts.append(
                {
                    "kind": kind,
                    "purpose": binding.purpose,
                    "operation_id": "test.run.start",
                    "status": "accepted",
                    "valid_from": at - timedelta(minutes=1),
                    "valid_until": at + timedelta(minutes=20),
                    "actor_id": work.quality.human,
                    "named_decision_id": decision_id,
                    "sources": sources,
                }
            )
        if declaration is not None:
            if declaration.facts:
                facts = [value.model_dump(mode="json") for value in declaration.facts]
                for value in declaration.facts:
                    decisions[value.named_decision_id] = (declaration.resource.id, value.kind)
            resource_inputs.append({**declaration.model_dump(mode="json"), "facts": facts})
        else:
            resource_inputs.append(
                {
                    **deepcopy(physical),
                    "resource": resource,
                    "purposes": [binding.purpose],
                    "operation_ids": ["test.run.start"],
                    "facts": facts,
                    "calendar_sources": [reference],
                    "external_occupancies_complete": True,
                    "sources": [reference],
                }
            )

    def named_decision(session, ctx, declared, resource, decision, checked_at):
        current = (
            declared == binding.model_dump(mode="json")
            and decisions.get(decision.named_decision_id) == (resource.id, decision.kind)
            and decision.actor_id == work.quality.human
        )
        return DecisionProof(
            current=current,
            facts_revision=digest(
                {"decision": decision.model_dump(mode="json"), "current": current}
            ),
            valid_until=decision.valid_until,
        )

    issuer = test_resources.configure_local_synthetic(
        work.setup.engine,
        tenant_id=work.setup.tenant,
        product_id=work.setup.product,
        project_id=UUID(work.config["project"]),
        enabled=True,
        test_marker_verified=True,
        key=f"synthetic-continuation-{run_id}",
        verify_named_decision=named_decision,
    )
    cleanup.callback(test_resources.disable_issuer, work.setup.engine, issuer.key)
    source_values = (
        reference,
        *(value.model_dump(mode="json") for value in person_resource.sources),
        *(value.model_dump(mode="json") for value in person_resource.calendar_sources),
    )
    all_sources = list(
        {
            (value["artifact_id"], value["expected_revision"], value["line"], value["quote"]): value
            for value in source_values
        }.values()
    )
    fact = TestResourceFactInput.model_validate(
        {
            "binding": binding,
            "external_id": f"SYN-CONTINUATION-{run_id}",
            "valid_from": at - timedelta(minutes=1),
            "valid_until": at + timedelta(minutes=20),
            "resources": resource_inputs,
            "required_uses": [
                {"resource": row["resource"], "units": "1"} for row in resource_inputs
            ],
            "requirements_sources": all_sources,
            "sources": all_sources,
            "reason": (
                "Declared synthetic new equipment and unchanged actual person physical capacity"
            ),
        }
    )
    with approved.session(work, work.quality) as stored:
        receipt = import_test_resource_fact(
            stored,
            work.quality.ctx,
            work.setup.product,
            issuer,
            fact,
            request_key=str(uuid4()),
            command_id=uuid4(),
        )
    run_work.binding = binding
    run_work.test_fact_id = UUID(receipt["subject_id"])
    run_work.test_input, run_work.test_issuer = fact, issuer
    run_work.plan = ExecutionPlan(
        **{
            name: getattr(binding, name)
            for name in (
                "window",
                "executor_id",
                "equipment",
                "calibration",
                "environment",
                "conditions",
            )
        },
        resource_fact_id=run_work.test_fact_id,
        expected_resource_fact_revision=1,
    )
    return run_work


def record_new_run_results(
    work,
    monkeypatch,
    *,
    cleanup,
    raw_value,
    test_executor,
    test_person_resource,
    independent_reviewer,
):
    """Real new Run/original/capture/import; reserve the independent reviewer.

    ``raw_value`` is the caller's declared synthetic observation. The actual
    engine computes its result; no boolean pass, action applicability, complete
    observation window, independent effectiveness or close is manufactured.
    """
    executor, reviewer = _caller(work, test_executor), _caller(work, independent_reviewer)
    assert reviewer.human != work.setup.human, "Action executor cannot be the independent reviewer"
    assert reviewer.human != executor.human, "Keep the reviewer separate from the Run executor"
    execution_work = SimpleNamespace(**{**vars(work), "quality": executor})
    run_work = _prepare_new_run(
        execution_work, monkeypatch, cleanup, test_person_resource=test_person_resource
    )
    accepted(run_work.quality, launch_command(run_work, "test.run.plan"))
    accepted(run_work.quality, launch_command(run_work, "verification.schedule.promise"))
    delay = (run_work.binding.window.start - datetime.now(UTC)).total_seconds()
    if delay > 0:
        # Wait for real UTC; never move Python ahead of PostgreSQL's event guard.
        assert delay <= 1
        sleep(delay)
    launch.advance_clock(run_work, monkeypatch)
    accepted(run_work.quality, launch_command(run_work, "test.run.start"))
    run_work.report_rows = measurement_rows(run_work, raw=raw_value)
    run_work.report_artifact = results.upload_report(run_work, run_work.report_rows)
    captured, _ = results.capture(run_work, tuple(range(len(run_work.report_rows))))
    run_work.result_receipt, _ = accepted(
        run_work.quality,
        results.command(run_work, "test.results.import", captured=captured, final=True),
    )
    fixed = results.current_rows(run_work)
    assert fixed.request.status == "reported" and fixed.run.result is not None
    run_work.independent_reviewer = reviewer
    run_work.final = results.current_rows(run_work)
    return run_work


def link_new_outputs(work, continuation, action_ids):
    """Record the real new Build/Run refs, without claiming action fulfillment."""
    fixed = results.current_rows(continuation)
    refs = [
        {"kind": "build", "id": continuation.build_id, "revision": 1, "key": None},
        {
            "kind": "verification_run",
            "id": str(fixed.row.id),
            "revision": fixed.row.revision,
            "key": None,
        },
    ]
    receipts = []
    for action_id in action_ids:
        current = followup.fixed_issue(work)
        value = followup.command(
            work,
            "quality.capa.followup.link",
            {
                "issue_id": str(work.issue_id),
                "expected_issue_revision": current.revision,
                "capa_id": str(work.capa_id),
                "action_id": str(action_id),
                "output_refs": refs,
                "sources": [],
                "reason": (
                    "Link the actual new Build and exact new Run output; "
                    "applicability, observation and independent effectiveness remain undecided"
                ),
            },
        )
        receipt, command = accepted(work.quality, value)
        receipts.append((receipt, command))
    return tuple(receipts)


def continue_after_implementations(
    work,
    basis,
    implementations,
    engineering,
    manufacturing,
    monkeypatch,
    *,
    cleanup,
    executor,
    test_executor,
    test_person_resource,
    independent_reviewer,
    raw_value,
):
    """Root integration entry; ``cleanup`` is its enclosing live ExitStack.

    Root supplies actual saved implementation pairs and configuration receipts.
    It must keep this stack open through later candidate/attestation reads. A
    separate later candidate, actual observation window and independent efficacy
    decision remain necessary; this function returns evidence, never that decision.
    """
    implementations = tuple(implementations)
    actual_outputs = {
        (ref.kind, str(ref.id), ref.revision)
        for _, occurrence in implementations
        for ref in occurrence.outputs
    }
    assert {
        ("engineering_configuration", engineering["subject_id"], engineering["subject_revision"]),
        (
            "manufacturing_configuration",
            manufacturing["subject_id"],
            manufacturing["subject_revision"],
        ),
    } <= actual_outputs, "The new Build must use the actual approved implementation outputs"
    completed = complete_implemented_actions(work, basis, implementations, executor=executor)
    continuation = create_new_build(work, engineering, manufacturing, cleanup=cleanup)
    create_actual_samples(continuation)
    create_new_request(continuation, method_dossier=work.source)
    continued = record_new_run_results(
        continuation,
        monkeypatch,
        cleanup=cleanup,
        raw_value=raw_value,
        test_executor=test_executor,
        test_person_resource=test_person_resource,
        independent_reviewer=independent_reviewer,
    )
    continued.completion = completed
    continued.followup_links = link_new_outputs(
        work, continued, (occurrence.action_id for _, occurrence in implementations)
    )
    unchanged = quality.issue_current(work, work.issue_id)
    assert unchanged["id"] == str(completed.issue.id)
    assert unchanged["issue"]["capa"]["effectiveness"] is None
    assert unchanged["issue"]["closure"] is None
    return continued
