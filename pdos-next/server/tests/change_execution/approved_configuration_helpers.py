"""Actual synthetic originals and commands for the root-only approved revision chain."""

import hashlib
import json
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from build_start.test_transactions import import_authority
from quality_execution import fixtures as quality
from sqlalchemy import func, select
from test_project_first_plan import accepted, cmd, post

from pdos_next import change_controlled_owner as controlled
from pdos_next.change_controlled_schemas import PolicyImport, PolicyMaterial, SelectionMaterial
from pdos_next.change_controlled_store import (
    ChangePolicyFact,
    ChangeSelectionCurrent,
    ChangeSelectionFact,
)
from pdos_next.change_order_store import (
    ChangeApprovalRecord,
    ChangeImplementationRecord,
    ChangeOrderRecord,
    ImplementationCapture,
)
from pdos_next.database import tenant_session
from pdos_next.domain.capa_verification import service as followup
from pdos_next.domain.change_control.rules import digest
from pdos_next.domain.change_coverage_owner import importer, models, owner, schemas, trust
from pdos_next.domain.change_execution.models import (
    ChangeCurrent,
    ChangeGraphCapture,
    ChangeRequestVersion,
)
from pdos_next.domain.configurations.models import EngineeringConfiguration, ProcessRevision
from pdos_next.domain.projects.models import Project
from pdos_next.models import Artifact, Audit, Confirmation, Outbox, Receipt, RequestKey, now
from pdos_next.schemas.change_control.contracts import ControlledIntent, PlanItem, Ref, Selection
from pdos_next.schemas.verification.contracts import Scope, SourceRef
from tests.g0_fixture import create_g0_project


def session(work, caller=None):
    caller = caller or work.quality
    return tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=caller.human,
        requester_id=caller.human,
        category_id=work.setup.category,
    )


def original(caller, material, title):
    raw = material.model_dump(mode="json") if hasattr(material, "model_dump") else material
    content = json.dumps(
        raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    response = post(
        caller,
        cmd(
            caller,
            "evidence.artifact.register",
            {
                "title": title,
                "content": content,
                "visibility": "category",
                "source_label": "Explicit bounded synthetic configuration change",
            },
        ),
    )
    assert response.status_code == 200, response.text
    receipt = response.json()
    return SimpleNamespace(
        source=SourceRef(
            id=UUID(receipt["subject_id"]),
            revision=1,
            kind="artifact",
            position="line:1;quote_sha256:" + hashlib.sha256(content.encode()).hexdigest(),
        ),
        reference={
            "artifact_id": receipt["subject_id"],
            "expected_revision": 1,
            "line": 1,
            "quote": content,
        },
        receipt=receipt,
    )


def initial_configuration(setup):
    """Build the same finite scope with an actual motor-to-assembly association."""
    fixed = create_g0_project(
        setup, visibility="category", name="Approved revision fixture", purpose="Verify preparation"
    )
    source = original(
        setup,
        {"requirement": "Synthetic requirement is unverified", "assembly_bom_line": "motor"},
        "Synthetic motor assembly input",
    )
    common = {
        "visibility": "category",
        "reason": "Explicit shared synthetic configuration",
        "sources": [source.reference],
    }
    bom, _ = accepted(
        setup,
        cmd(
            setup,
            "engineering.bom.revise",
            {
                **common,
                "name": "Synthetic motor BOM",
                "lines": [
                    {
                        "key": "motor",
                        "part": {
                            "name": "Synthetic motor",
                            "internal_number": f"SYN-{setup.product}",
                        },
                        "quantity": "2",
                        "unit": "ea",
                        "loss_rate": "0.1",
                        "critical": True,
                    }
                ],
            },
            str(source.source.id),
        ),
    )
    engineering, _ = accepted(
        setup,
        cmd(
            setup,
            "engineering.configuration.create",
            {
                **common,
                "name": "Synthetic original engineering configuration",
                "definition_id": str(fixed.definition_id),
                "expected_definition_revision": 1,
                "bom_id": bom["subject_id"],
                "expected_bom_revision": 1,
            },
            str(source.source.id),
        ),
    )
    process, _ = accepted(
        setup,
        cmd(
            setup,
            "npi.process.revise",
            {
                **common,
                "name": "Synthetic original motor assembly process",
                "engineering_configuration_id": engineering["subject_id"],
                "expected_engineering_revision": 1,
                "site": "SYN-INTERNAL-LAB",
                "line": "SYN-LINE",
                "operations": [
                    {
                        "key": "assembly",
                        "name": "Synthetic manual motor assembly",
                        "kind": "assembly",
                        "bom_line_keys": ["motor"],
                    }
                ],
            },
            str(source.source.id),
        ),
    )
    return {
        "source": str(source.source.id),
        "project": str(fixed.project_id),
        "engineering": engineering,
        "process": process,
    }


def declare_people(work):
    """Import actual finite synthetic series before any new signer snapshots."""
    for person, role, operations in (
        (
            work.quality.human,
            "quality",
            [
                "change.request.create",
                "change.impact.compute",
                "change.policy.import",
                "change.order.prepare",
            ],
        ),
        (work.quality.human, "engineering", ["change.selection.decide", "change.order.approve"]),
        (work.quality.human, "manufacturing", ["change.selection.decide"]),
        (work.engineer.human, "engineering", ["change.order.approve"]),
        (
            work.setup.human,
            "manufacturing",
            ["change.order.approve", "change.implementation.record"],
        ),
    ):
        for kind in ("duty", "qualification"):
            import_authority(
                work,
                role,
                kind,
                subject_id=str(person),
                operations=operations,
                external_id=f"synthetic-approved-revision-{work.build_id}-{person}-{role}-{kind}",
            )


def issue_and_actions(work):
    quality.publish_policy(work)
    response = post(
        work.quality,
        quality.command(
            work, "quality.issue.create", {**quality.payload_create(work), "visibility": "category"}
        ),
    )
    assert response.status_code == 200, response.text
    work.issue_id = UUID(response.json()["result"]["issue_id"])
    quality.triage(work, response.json())
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
                    "text": "Hold the synthetic failed sample; original results remain fixed",
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
            "executor_id": str(work.setup.human),
            "text": f"Revise the fixed {discipline} configuration under its own approved plan item",
        }
        for discipline in ("engineering", "manufacturing")
    ]
    response = post(
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
                        "text": "Unproven synthetic failure hypothesis",
                        "sources": [work.hypothesis_source.model_dump(mode="json")],
                    }
                ],
                "actions": work.actions,
                "requirement": {
                    "method": "New actual configuration and a separate new verification Run",
                    "acceptance": (
                        "Exact applicable independent verification; "
                        "implementation is not verification"
                    ),
                    "observation_until": (now() + timedelta(days=1)).isoformat(),
                    "required_failure_ids": [
                        value["identity"] for value in contained["issue"]["failures"]
                    ],
                },
            },
        ),
    )
    assert response.status_code == 200, response.text
    work.issue_view = quality.issue_current(work, work.issue_id)
    with session(work) as stored:
        return followup.load_followup_basis(
            stored, work.quality.ctx, work.setup.product, work.issue_id, work.issue_view["revision"]
        )


def policy_and_items(work, change_id, basis, until):
    scope = Scope(
        tenant_id=work.setup.tenant,
        product_id=work.setup.product,
        project_id=UUID(work.config["project"]),
    )
    with session(work) as stored:
        project = stored.get(Project, scope.project_id)
        assert project.visibility == "category"
        project_owner = project.owner_id
    policy = PolicyMaterial(
        schema_version="pdos-controlled-change-policy-v1",
        scope=scope,
        purpose=basis.purpose,
        owner_id=project_owner,
        visibility="category",
        publisher_id=work.quality.human,
        required_disciplines=("engineering", "manufacturing"),
        valid_from=now() - timedelta(minutes=1),
        valid_until=until,
        nature="synthetic",
    )
    policy_original = original(
        work.quality, policy, "Synthetic independent dual-lane decision policy"
    )
    with session(work) as stored:
        receipt = controlled.import_policy(
            stored,
            work.quality.ctx,
            work.setup.product,
            PolicyImport(
                project_id=scope.project_id,
                purpose=basis.purpose,
                source=policy_original.source,
                reason="Explicit synthetic policy publication",
            ),
            command_id=uuid4(),
            request_key=str(uuid4()),
        )
    assert receipt["subject_type"] == "change_policy_fact"
    selections = []
    for index, (discipline, kind, key) in enumerate(
        (
            ("engineering", "engineering_configuration", "engineering"),
            ("manufacturing", "manufacturing_configuration", "process"),
        )
    ):
        fixed = work.config[key]
        ref = Ref(kind=kind, id=UUID(fixed["subject_id"]), revision=fixed["subject_revision"])
        item = PlanItem(
            id=uuid4(),
            discipline=discipline,
            selection=Selection(
                objects=(ref,),
                units=(f"object:{ref.identity}",),
                conditions=("Only this fixed configuration and named CAPA action",),
                sources=(policy_original.source,),
            ),
            intent=ControlledIntent(
                id=uuid4(),
                kind=f"new_{kind}",
                basis=(ref,),
                description=(
                    f"Original owner revises the fixed {discipline} configuration "
                    "after independent approval"
                ),
            ),
            verification_requirement=(
                "New exact configuration/Run and applicable independent review remain required"
            ),
        )
        action = basis.actions[index]
        assert action.executor_id == work.setup.human
        material = SelectionMaterial(
            schema_version="pdos-controlled-change-selection-v1",
            scope=scope,
            purpose=basis.purpose,
            change_id=UUID(change_id),
            item=item,
            issue_id=basis.issue_id,
            capa_id=basis.capa_id,
            action_id=action.action_id,
            action_sha256=action.action_sha256,
            executor_id=action.executor_id,
            decider_id=work.quality.human,
            status="applicable",
            valid_until=until,
            reason=f"Explicit bounded synthetic {discipline} action applicability",
            nature="synthetic",
        )
        selections.append(
            (material, original(work.quality, material, f"Synthetic {discipline} selection"))
        )
    return scope, policy_original, selections


def inputs(work, caller, operation, payload):
    response = caller.client.post(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/change-execution/inputs",
        headers=caller.headers,
        json=cmd(caller, operation, payload),
    )
    assert response.status_code == 200, response.text
    assert response.json()["allowed"] is True
    return response.json()["command"], response.json()["review"]


def counts(work):
    with session(work) as stored:
        return {
            model.__tablename__: stored.scalar(select(func.count()).select_from(model))
            for model in (
                EngineeringConfiguration,
                ProcessRevision,
                ChangeGraphCapture,
                models.ChangeCoverageFact,
                models.ChangeCoverageCurrent,
                ChangePolicyFact,
                ChangeSelectionFact,
                ChangeSelectionCurrent,
                ChangeOrderRecord,
                ChangeApprovalRecord,
                ImplementationCapture,
                ChangeImplementationRecord,
                ChangeRequestVersion,
                ChangeCurrent,
                Receipt,
                Audit,
                Outbox,
                Confirmation,
                RequestKey,
                Artifact,
            )
        }


def publish_coverage(work, scope, change_id, graph, until, *, paths, facet_states):
    with session(work) as stored:
        basis = owner.inspect_basis(
            stored,
            work.quality.ctx,
            work.setup.product,
            change_id=UUID(change_id),
            purpose=work.binding.purpose,
        )
    binding = basis["binding"]
    material = schemas.CoverageMaterial.model_validate(
        {
            "schema_version": "pdos-controlled-change-coverage-v2",
            "scope": scope.model_dump(mode="json"),
            "purpose": work.binding.purpose,
            "change_id": change_id,
            "origin_version_id": binding["origin_version_id"],
            "origin_revision": binding["origin_revision"],
            "owner_id": str(work.quality.human),
            "visibility": "category",
            "publisher_id": str(work.quality.human),
            "roots": [ref.model_dump(mode="json") for ref in graph.roots],
            "nodes": [node.ref.model_dump(mode="json") for node in graph.nodes],
            "units": [
                {"unit": f"object:{node.ref.identity}", "object_identity": node.ref.identity}
                for node in graph.nodes
            ],
            "facets": [
                {
                    "facet": facet,
                    "nodes": [node.ref.model_dump(mode="json") for node in graph.nodes],
                    "statement": (
                        "Bounded synthetic internal prototype revision only; "
                        "every applicability exception is explicit in facet_states and paths"
                    ),
                }
                for facet in schemas.FACETS
            ],
            "closure_sha256": basis["closure_sha256"],
            "valid_from": graph.captured_at,
            "valid_until": until,
            "nature": "synthetic",
            "paths": paths,
            "facet_states": facet_states,
        }
    )
    source = original(work.quality, material, "Synthetic fixed internal revision coverage v2")
    issuer = trust.configure(
        work.setup.engine,
        work.professional_issuer,
        scope=scope,
        approvals=(
            schemas.OriginalApproval(source=source.source, material_sha256=digest(material)),
        ),
    )
    try:
        with session(work) as stored:
            receipt = importer.trusted_import(
                stored,
                work.quality.ctx,
                work.setup.product,
                issuer,
                schemas.CoverageImport(
                    project_id=scope.project_id,
                    change_id=UUID(change_id),
                    purpose=work.binding.purpose,
                    source=source.source,
                    reason="Finite synthetic internal prototype coverage, no production or release",
                ),
                command_id=uuid4(),
                request_key=str(uuid4()),
            )
    except BaseException:
        trust.disable(work.setup.engine, scope=scope)
        raise
    return material, source, receipt


def snapshot(row):
    return {
        column.key: deepcopy(getattr(row, column.key)) for column in row.__mapper__.column_attrs
    }
