"""Actual retained row composition over explicit no-connect SQL fixtures.

The upstream physical/original readers and release.get_package run unchanged.
Persisted package/decision/common rows and signature/key-binding SQL are fixture
IO, not evidence of PostgreSQL guards, qualification or an external handoff.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from manufacturing_preparation.test_publication_material_owner import (
    world as native_world,  # noqa: F401
)
from manufacturing_preparation.test_publication_rules import case as publication_case  # noqa: F401
from manufacturing_trials.test_native_material_owner import work as native_work  # noqa: F401
from manufacturing_trials.test_native_statistics_owner import work as statistics_work  # noqa: F401
from release.test_material_owner import work as release_work  # noqa: F401

from pdos_next.domain.external_handoff import material_owner as owner
from pdos_next.domain.external_handoff import rules, schemas
from pdos_next.domain.release import rules as release_rules
from pdos_next.domain.release import schemas as release_schemas
from pdos_next.domain.release.models import ReleaseDecision, ReleasePackage, ReleasePackageCurrent
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Outbox, Receipt, RequestKey
from pdos_next.service import digest


def _common(work, row, *, decision=False):
    at = row.created_at + timedelta(microseconds=1)
    receipt = work.s.add_row(
        Receipt(
            id=row.receipt_id,
            tenant_id=work.ctx.tenant_id,
            category_id=work.ctx.category_id,
            product_id=work.pid,
            command_id=row.command_id,
            actor_id=row.actor_id,
            requester_id=row.requester_id,
            operation=row.operation,
            subject_type="release_decision" if decision else "release_package",
            subject_id=row.id,
            subject_revision=row.revision,
            visibility=row.visibility,
            request_digest=row.request_digest,
            intent_digest=row.intent_digest,
            run_id=None,
            agent_run_id=None,
            confirmation_id=row.shared_proof_id if decision else None,
            result={"id": str(row.id), "revision": row.revision, "status": row.status},
            created_at=at,
        )
    )
    work.s.add_row(
        Audit(
            id=uuid4(),
            tenant_id=work.ctx.tenant_id,
            category_id=work.ctx.category_id,
            receipt_id=receipt.id,
            actor_id=row.actor_id,
            operation=row.operation,
            created_at=at,
        )
    )
    work.s.add_row(
        Outbox(
            id=uuid4(),
            tenant_id=work.ctx.tenant_id,
            category_id=work.ctx.category_id,
            receipt_id=receipt.id,
            actor_id=row.actor_id,
            type=release_schemas.OPERATIONS[row.operation][1],
            subject_id=row.id,
            subject_revision=row.revision,
            correlation_id=row.command_id,
            schema_version=1,
            created_at=at,
        )
    )
    work.s.add_row(
        RequestKey(
            id=uuid4(),
            tenant_id=work.ctx.tenant_id,
            category_id=work.ctx.category_id,
            actor_id=row.actor_id,
            key="explicit-synthetic-common-key-" + str(row.id),
            digest=row.request_digest,
            receipt_id=receipt.id,
            created_at=at,
        )
    )
    return receipt


@pytest.fixture
def work(request, monkeypatch):
    base = request.getfixturevalue("release_work")
    read = base.read_release()
    at = datetime.now(UTC)
    plan = release_rules.assemble(
        base.release_payload, read.material, owner_id=base.ctx.requester_id
    )
    identity = uuid4()
    fields = {
        "tenant_id": base.ctx.tenant_id,
        "category_id": base.ctx.category_id,
        "product_id": base.pid,
        "project_id": base.project.id,
        "owner_id": base.ctx.requester_id,
        "writer_id": base.ctx.actor_id,
        "actor_id": base.ctx.actor_id,
        "requester_id": base.ctx.requester_id,
        "visibility": "private",
        "purpose": base.project.purpose,
        "revision": 1,
        "material_snapshot": read.material.model_dump(mode="json"),
        "source_basis": {"material_owner": read.source_basis},
        "sources": [v.model_dump(mode="json") for v in read.sources],
        "required_source_read_set": [
            v.model_dump(mode="json") for v in read.required_source_read_set
        ],
        "input_snapshot": {},
        "created_at": at,
    }
    package = base.s.add_row(
        ReleasePackage(
            **fields,
            id=identity,
            series_id=identity,
            previous_id=None,
            previous_revision=None,
            status="assembled",
            operation=release_schemas.ASSEMBLE,
            write_tier="T0",
            body=plan.model_dump(mode="json"),
            body_sha256=release_rules.digest(plan),
            command_id=uuid4(),
            receipt_id=uuid4(),
            request_digest=digest("synthetic-package-request"),
            intent_digest=digest("synthetic-package-intent"),
        )
    )
    _common(base, package)
    pointer = base.s.add_row(
        ReleasePackageCurrent(
            id=uuid4(),
            tenant_id=base.ctx.tenant_id,
            category_id=base.ctx.category_id,
            product_id=base.pid,
            project_id=base.project.id,
            series_id=package.series_id,
            owner_id=base.ctx.requester_id,
            visibility="private",
            version_id=package.id,
            revision=1,
            epoch=1,
            created_at=at,
        )
    )
    decisions = []
    for discipline in ("engineering", "manufacturing"):
        operation = f"release.{discipline}.approve"
        declaration = release_schemas.ApprovePayload(
            package={"id": package.id, "revision": 1},
            release_scope=plan.declaration.release_scope,
            purpose=plan.declaration.purpose,
            sources=base.release_payload.sources,
            reason="Explicit synthetic saved decision row IO",
        )
        decision_plan = release_rules.prepare_decision(
            operation,
            declaration.model_dump(mode="json"),
            declaration.package,
            plan,
            ctx=base.ctx,
            at=at,
        )
        row = base.s.add_row(
            ReleaseDecision(
                **fields,
                id=uuid4(),
                package_id=package.id,
                package_revision=1,
                discipline=discipline,
                status="approved",
                operation=operation,
                write_tier="T2",
                body=decision_plan.model_dump(mode="json"),
                body_sha256=release_rules.digest(decision_plan),
                authority_snapshot={
                    "scope": plan.scope.model_dump(mode="json"),
                    "subject_id": str(base.ctx.actor_id),
                    "operation": operation,
                    "purpose": base.project.purpose,
                    "explicit_io": "saved signature watermark",
                },
                command_id=uuid4(),
                receipt_id=uuid4(),
                request_digest=digest(operation + "request"),
                intent_digest=digest(operation + "intent"),
                shared_proof_id=uuid4(),
                shared_proof_revision=base.product.revision,
                proof_consumed_at=at,
                proof_expires_at=None,
                token_sha256="a" * 64,
                material_sha256="b" * 64,
                read_set_sha256="c" * 64,
            )
        )
        _common(base, row, decision=True)
        decisions.append(row)
    owner.releases.configure(base.s.get_bind())
    reader = owner.ActualHandoffMaterialOwner(base.s.get_bind())
    base.s.get_bind()._pdos_external_handoff = SimpleNamespace(owner=reader, evidence_owner=None)
    io = SimpleNamespace(
        signature_current=True, key_bound=True, signature_calls=0, binding_calls=[]
    )

    def signature(*args):
        io.signature_calls += 1
        return io.signature_current

    def key_bound(s, ctx, pid, receipt_id):
        io.binding_calls.append(receipt_id)
        receipt = s.get(Receipt, receipt_id)
        return io.key_bound and any(
            v.receipt_id == receipt_id
            and v.actor_id == receipt.actor_id
            and v.digest == receipt.request_digest
            for v in s.rows[RequestKey]
        )

    monkeypatch.setattr(owner, "signature_current", signature)
    monkeypatch.setattr(owner.releases, "signature_current", signature)
    monkeypatch.setattr(owner, "readable_receipt_request_bound", key_bound)
    payload = schemas.AuthorizePayload(
        project_id=base.project.id,
        package={"id": package.id, "revision": 1},
        engineering_decision={"id": decisions[0].id, "revision": 1},
        manufacturing_decision={"id": decisions[1].id, "revision": 1},
        subject_config=plan.declaration.subject_config,
        release_scope=plan.declaration.release_scope,
        purpose=plan.declaration.purpose,
        visibility="private",
        destination={"system": "synthetic-erp", "recipient_id": "synthetic-factory"},
        external_id="synthetic-handoff-one",
        sources=base.release_payload.sources,
        reason="Prepare only; contract and external outcome remain unknown",
    )
    result = SimpleNamespace(
        **vars(base),
        handoff_owner=reader,
        handoff_payload=payload,
        package=package,
        package_plan=plan,
        package_pointer=pointer,
        decisions=decisions,
        io=io,
    )
    result.read_handoff = lambda: reader.read(
        result.s, result.ctx, result.pid, result.handoff_payload
    )
    return result


def reject(call, code):
    with pytest.raises(DomainError) as error:
        call()
    assert error.value.reason == code


def test_actual_package_and_selected_decision_rows_do_not_invent_contract_or_sources(work):
    value = work.read_handoff()
    assert value.actual.package_ref == work.handoff_payload.package and value.actual.package_current
    assert {v.ref.id for v in value.actual.decisions} == {v.id for v in work.decisions}
    assert all(
        v.plan.model_dump(mode="json") == row.body
        for v, row in zip(value.actual.decisions, work.decisions, strict=True)
    )
    assert value.actual.contract_read is None
    assert value.actual.required_mapping_refs is value.actual.required_manifest_refs is None
    assert (
        value.actual.sources_current is None
        and value.sources == value.required_source_read_set == ()
    )
    assert (
        value.source_basis["artifact_sources"] == {}
        and value.source_basis["evidence_owner"] is None
    )
    candidate = rules.prepare(
        work.handoff_payload, value.actual, ctx=work.ctx, at=datetime.now(UTC)
    )
    assert candidate.state == "UNKNOWN" and "HANDOFF_CONTRACT_NOT_READ" in candidate.unknown
    assert (
        candidate.network_send
        is candidate.external_received
        is candidate.external_effective
        is False
    )
    assert work.handoff_owner.current(work.s, work.ctx, work.pid, value)
    assert not (work.s.new or work.s.dirty or work.s.deleted)


def test_current_uses_saved_metadata_without_original_bytes_or_historical_assessment(
    work, monkeypatch
):
    value = work.read_handoff()

    def forbidden(*args, **kwargs):
        raise AssertionError("Retained signature must not reread bytes or reassess qualification")

    monkeypatch.setattr(owner.evidence, "_evidence", forbidden)
    from pdos_next.domain.professional_authority import service as professional

    monkeypatch.setattr(professional, "assess", forbidden)
    monkeypatch.setattr(professional, "recheck_snapshot", forbidden)
    actual, basis = value.actual.model_dump(mode="json"), deepcopy(value.source_basis)
    work.s.rollback()
    work.s.begin()
    assert work.handoff_owner.current(work.s, work.ctx, work.pid, actual, basis)
    reject(
        lambda: work.handoff_owner.current(work.s, work.ctx, work.pid, value),
        "FACT_CALLER_UOW_CHANGED",
    )


def test_same_uow_cache_and_seal_reject_copy_mutation_and_runtime_swap(work):
    value = work.read_handoff()
    count, bindings = len(work.s.queries), len(work.io.binding_calls)
    assert work.read_handoff() is value
    assert len(work.s.queries) == count and len(work.io.binding_calls) == bindings
    reject(
        lambda: work.handoff_owner.current(work.s, work.ctx, work.pid, replace(value)),
        "SOURCE_STALE",
    )
    value.source_basis["artifact_sources"][str(uuid4())] = {"forged": True}
    reject(lambda: work.handoff_owner.current(work.s, work.ctx, work.pid, value), "SOURCE_STALE")


def test_explicit_old_package_is_not_replaced_by_latest_or_marked_current(work):
    work.package_pointer.version_id, work.package_pointer.revision, work.package_pointer.epoch = (
        uuid4(),
        2,
        2,
    )
    value = work.read_handoff()
    assert value.actual.package_ref == work.handoff_payload.package
    assert value.actual.package_current is False
    assert all(v.current is False for v in value.actual.decisions)


def test_missing_exact_decision_never_uses_another_saved_decision(work):
    work.handoff_payload = work.handoff_payload.model_copy(
        update={"engineering_decision": release_schemas.VersionRef(id=uuid4(), revision=1)}
    )
    value = work.read_handoff()
    assert len(value.actual.decisions) == 1
    assert value.actual.decisions[0].ref == work.handoff_payload.manufacturing_decision


@pytest.mark.parametrize("fault", ["decision_hash", "package_binding", "receipt", "proof", "key"])
def test_matching_dto_or_hash_cannot_replace_actual_row_and_common_group(work, fault):
    decision = work.decisions[0]
    code = "STORED_ATOM_MISMATCH"
    if fault == "decision_hash":
        decision.body_sha256 = "0" * 64
    elif fault == "package_binding":
        decision.package_id = uuid4()
    elif fault == "receipt":
        work.s.get(Receipt, decision.receipt_id).intent_digest = "0" * 64
    elif fault == "proof":
        work.s.get(Receipt, decision.receipt_id).confirmation_id = uuid4()
    else:
        work.io.key_bound = False
        code = "STORED_ATOM_INCOMPLETE"
    reject(work.read_handoff, code)


@pytest.mark.parametrize("fault", ["current", "signature", "common", "private"])
def test_retained_current_checks_only_direct_scope_and_watermarks(work, fault):
    value = work.read_handoff()
    code = "SOURCE_STALE"
    if fault == "current":
        work.package_pointer.epoch += 1
    elif fault == "signature":
        work.io.signature_current = False
        code = "RECHECK_REQUIRED"
    elif fault == "common":
        work.s.get(Receipt, work.decisions[0].receipt_id).subject_revision += 1
    else:
        work.package.owner_id = uuid4()
    reject(lambda: work.handoff_owner.current(work.s, work.ctx, work.pid, value), code)


def test_private_package_cannot_be_widened_and_wrong_runtime_cannot_issue_read(work):
    work.handoff_payload = work.handoff_payload.model_copy(update={"visibility": "category"})
    reject(work.read_handoff, "FORBIDDEN_SCOPE")
    work.s.get_bind()._pdos_external_handoff.owner = object()
    reject(work.read_handoff, "INTEGRATION_REQUIRED")
