"""Actual capture and retained approved owner; no execution/classification shortcut."""

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4
from weakref import WeakKeyDictionary

from pydantic import AwareDatetime, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, text

from pdos_next import change_order_store as store
from pdos_next.change_controlled_schemas import FieldFeedbackRef
from pdos_next.clock import deadline_current, earliest_deadline, proof_deadline_current
from pdos_next.clock import now as server_now
from pdos_next.database import category_for_product
from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
from pdos_next.domain.capa_verification.service import load_followup_basis
from pdos_next.domain.change_control.rules import digest
from pdos_next.domain.change_execution import service as old
from pdos_next.domain.change_execution.graph import OwnerReader
from pdos_next.domain.change_execution.models import ChangeRequestVersion
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.quality_followup.evidence import _constant, _pairs
from pdos_next.errors import DomainError
from pdos_next.models import (
    Audit,
    Confirmation,
    Grant,
    Outbox,
    Principal,
    Product,
    Receipt,
    RequestKey,
)
from pdos_next.schemas.change_control.contracts import ImplementationFact, Ref
from pdos_next.schemas.verification.contracts import DTO, EventTime, Scope, SourceRef, Text
from pdos_next.service import digest as common_digest
from pdos_next.service import source_for


def clock():
    return server_now()


def _require(value, code="IMPLEMENTATION_OWNER_MISMATCH", status=409):
    if not value:
        raise DomainError(code, "实施原件、批准、本人、实际配置或共同保存组未满足。", status)


class _Occurrence(DTO):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)
    scope: Scope
    purpose: Text
    change_id: UUID
    order_id: UUID
    implementation_id: UUID
    reconciles_id: UUID | None
    item_id: UUID
    intent_id: UUID
    executor_id: UUID
    operation: str = Field(pattern="^change.implementation.record$")
    outcome: str = Field(pattern="^(succeeded|failed|unknown)$")
    occurred_at: AwareDatetime
    original_timezone: str
    sources: tuple[SourceRef, ...] = Field(min_length=1)
    outputs: tuple[Ref, ...] = Field()
    note: Text
    nature: str = Field(pattern="^(real|synthetic)$")

    @field_validator("original_timezone")
    @classmethod
    def timezone(cls, value):
        return EventTime.timezone(value)

    @field_validator("sources", "outputs", mode="before")
    @classmethod
    def revisions(cls, values):
        for v in values:
            n = v.get("revision") if isinstance(v, dict) else v.revision
            if type(n) is not int or n < 1:
                raise ValueError("Actual references require exact integer revisions")
        return values

    @model_validator(mode="after")
    def exact_collections(self):
        if len(set(self.sources)) != len(self.sources) or len(
            {v.identity for v in self.outputs}
        ) != len(self.outputs):
            raise ValueError("Actual occurrence sources/outputs cannot repeat")
        return self


class Occurrence(_Occurrence):
    """The existing CAPA occurrence retains its exact v2 meaning."""

    schema_version: str = Field(pattern="^pdos-change-implementation-occurrence-v2$")
    issue_id: UUID
    capa_id: UUID
    action_id: UUID
    action_sha256: str = Field(pattern="^[0-9a-f]{64}$")


class FieldOccurrence(_Occurrence):
    """Actual Field execution of a fixed, named, approved selection."""

    schema_version: Literal["pdos-field-change-implementation-occurrence-v1"]
    feedback: FieldFeedbackRef
    feedback_version_id: UUID
    feedback_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    selection_id: UUID
    selection_revision: int = Field(strict=True, ge=1)
    selection_sha256: str = Field(pattern="^[0-9a-f]{64}$")


def parse_occurrence(raw):
    kind = raw.get("schema_version") if isinstance(raw, dict) else None
    model = (
        FieldOccurrence if kind == "pdos-field-change-implementation-occurrence-v1" else Occurrence
    )
    return model.model_validate(raw)


def original_occurrence(s, ctx, pid, source):
    _require(source.kind == "artifact", "MISSING_REQUIRED_EVIDENCE", 422)
    artifact = source_for(s, ctx, pid, source.id, source.revision)
    # Native-only candidate: uploaded report offset/parse lineage requires its
    # actual owner, not Artifact.content substitution. Fail closed for that branch.
    _require(artifact.original_id is None, "IMPLEMENTATION_ORIGINAL_OWNER_REQUIRED", 503)
    _require(artifact.content_hash == common_digest(artifact.content), "SOURCE_STALE")
    old._native_registration(s, ctx, pid, artifact)
    match = old.POSITION.fullmatch(source.position)
    _require(match is not None, "MISSING_REQUIRED_EVIDENCE", 422)
    lines = artifact.content.splitlines()
    number = int(match[1])
    _require(number <= len(lines), "MISSING_REQUIRED_EVIDENCE", 422)
    line = lines[number - 1]
    _require(hashlib.sha256(line.encode("utf-8")).hexdigest() == match[2], "SOURCE_STALE")
    try:
        value = parse_occurrence(
            json.loads(line, object_pairs_hook=_pairs, parse_constant=_constant)
        )
    except (ValueError, TypeError) as error:
        raise DomainError(
            "MISSING_REQUIRED_EVIDENCE", "实施原文须完整结构化JSON，不接受重复键/额外字段。", 422
        ) from error
    _require(value.occurred_at <= clock(), "INVALID_EVENT_TIME", 422)
    return value, artifact


OUTPUTS = {
    "engineering_configuration": (
        "engineering.configuration.create",
        "engineering_configuration",
        "configuration.created",
    ),
    "manufacturing_configuration": ("npi.process.revise", "process_revision", "process.revised"),
}


def common_group(s, ctx, pid, row, *, operation, event, actor=None, key_binding=None):
    from pdos_next.change_order_service import _one

    receipt = _one(
        s,
        Receipt,
        Receipt.tenant_id == ctx.tenant_id,
        Receipt.product_id == pid,
        Receipt.subject_id == row.id,
        Receipt.subject_revision == row.revision,
        Receipt.operation == operation,
    )
    _require(
        actor is None
        or (receipt.actor_id == actor and receipt.requester_id == actor and receipt.run_id is None),
        "IMPLEMENTATION_WRITER_MISMATCH",
    )
    _require(
        receipt.visibility == row.visibility
        and str(receipt.result.get("id")) == str(row.id)
        and receipt.result.get("revision") == row.revision,
        "IMPLEMENTATION_GROUP_MISMATCH",
    )
    audit = _one(s, Audit, Audit.tenant_id == ctx.tenant_id, Audit.receipt_id == receipt.id)
    outbox = _one(s, Outbox, Outbox.tenant_id == ctx.tenant_id, Outbox.receipt_id == receipt.id)
    keys = list(
        s.scalars(
            select(RequestKey)
            .where(
                RequestKey.tenant_id == ctx.tenant_id,
                RequestKey.actor_id == receipt.actor_id,
                RequestKey.receipt_id == receipt.id,
                RequestKey.digest == receipt.request_digest,
            )
            .limit(2)
            .execution_options(autoflush=False, populate_existing=True)
        )
    )
    keys_bound = bool(keys)
    if not keys_bound and receipt.actor_id != ctx.actor_id:
        # RequestKey remains private to its actor. A peer may verify only the
        # existence of the exact key/receipt binding for a currently readable
        # receipt; the scoped DB function returns no key, digest or identity.
        keys_bound = (
            s.scalar(
                text(
                    "SELECT public.work_receipt_key_bound(:tenant,:product,:receipt)"
                    if key_binding == "project_work"
                    else "SELECT public.change_receipt_key_bound(:tenant,:product,:receipt)"
                ),
                {"tenant": ctx.tenant_id, "product": pid, "receipt": receipt.id},
            )
            is True
        )
    _require(
        keys_bound
        and audit.actor_id == receipt.actor_id
        and audit.operation == operation
        and (
            outbox.type,
            outbox.actor_id,
            outbox.correlation_id,
            outbox.subject_id,
            outbox.subject_revision,
        )
        == (
            event,
            receipt.actor_id,
            receipt.agent_run_id or receipt.run_id or receipt.command_id,
            row.id,
            row.revision,
        ),
        "IMPLEMENTATION_GROUP_MISMATCH",
    )
    return {
        "receipt": {
            name: getattr(receipt, name)
            for name in (
                "id",
                "tenant_id",
                "product_id",
                "actor_id",
                "requester_id",
                "command_id",
                "operation",
                "subject_type",
                "subject_id",
                "subject_revision",
                "intent_digest",
                "request_digest",
                "visibility",
                "result",
                "created_at",
                "run_id",
            )
        },
        "audit": {
            "id": audit.id,
            "receipt_id": audit.receipt_id,
            "actor_id": audit.actor_id,
            "operation": audit.operation,
        },
        "outbox": {
            "id": outbox.id,
            "receipt_id": outbox.receipt_id,
            "type": outbox.type,
            "actor_id": outbox.actor_id,
            "subject_id": outbox.subject_id,
            "subject_revision": outbox.subject_revision,
            "correlation_id": outbox.correlation_id,
        },
    }


def _atom_proof(s, ctx, pid, atom, group):
    from pdos_next.change_order_service import _one

    proof = _one(
        s,
        Confirmation,
        Confirmation.tenant_id == ctx.tenant_id,
        Confirmation.product_id == pid,
        Confirmation.id == atom.shared_proof_id,
    )
    _require(
        proof.consumed is True
        and proof.subject_id == pid
        and proof.actor_id == atom.actor_id
        and proof.operation == atom.operation
        and proof.revision == atom.shared_proof_revision
        and proof.token_hash == atom.token_sha256
        and proof.payload_digest == atom.material_sha256
        and proof.snapshot == atom.input_snapshot["review"]
        and proof.created_at <= atom.proof_consumed_at <= atom.created_at
        and proof_deadline_current(
            "T2" if atom.operation in {"change.order.approve", "change.selection.decide"} else "T1",
            proof.expires_at,
            atom.created_at,
        )
        and proof.expires_at == atom.proof_expires_at,
        "IMPLEMENTATION_GROUP_MISMATCH",
    )
    _require(
        group["receipt"]["command_id"] == atom.command_id
        and group["receipt"]["intent_digest"] == atom.intent_digest
        and group["receipt"]["actor_id"] == atom.actor_id,
        "IMPLEMENTATION_GROUP_MISMATCH",
    )


def _json(value):
    if isinstance(value, dict):
        return {k: _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    if isinstance(value, (UUID, datetime)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    return value


def verify_outputs(s, ctx, pid, request, order, fact):
    from pdos_next.change_order_service import _one

    reader = OwnerReader(s, ctx, pid, request.scope, request.audience, old._issue_loader(s))
    item = next((value for value in order.plan.items if value.id == fact.item_id), None)
    _require(item is not None and item.intent.id == fact.intent_id)
    expected_kind = {
        "new_engineering_configuration": "engineering_configuration",
        "new_manufacturing_configuration": "manufacturing_configuration",
    }.get(item.intent.kind)
    basis = {}
    for ref in fact.outputs:
        _require(ref.kind in OUTPUTS, "IMPLEMENTATION_OUTPUT_OWNER_REQUIRED", 503)
        _require(ref.kind == expected_kind, "IMPLEMENTATION_OWNER_MISMATCH")
        obj = reader.resolve(ref)
        _require(obj.current, "RECHECK_REQUIRED")
        operation, family, event = OUTPUTS[ref.kind]
        # Exact configuration row and actual owner save; future Build/Run/ERP owners
        # are intentionally absent rather than using a planned UUID as execution.
        from pdos_next.domain.configurations.models import EngineeringConfiguration, ProcessRevision

        model = (
            EngineeringConfiguration if ref.kind == "engineering_configuration" else ProcessRevision
        )
        row = _one(
            s,
            model,
            model.tenant_id == ctx.tenant_id,
            model.product_id == pid,
            model.id == ref.id,
            model.revision == ref.revision,
        )
        group = common_group(
            s, ctx, pid, row, operation=operation, event=event, actor=fact.executor_id
        )
        _require(
            group["receipt"]["subject_type"] == family
            and row.owner_id == fact.executor_id
            and bool(order.approvals)
            and max(value.at for value in order.approvals) <= group["receipt"]["created_at"]
            and group["receipt"]["created_at"] <= fact.occurred_at,
            "IMPLEMENTATION_WRITER_MISMATCH",
        )
        _require(
            any(
                previous.kind == ref.kind
                and previous.key is None
                and previous.id == row.previous_id
                and previous.revision == row.expected_previous_revision
                for previous in item.intent.basis
            ),
            "IMPLEMENTATION_OWNER_MISMATCH",
        )
        basis[str(ref.id)] = {
            "ref": ref.model_dump(mode="json"),
            "object": obj.view,
            "source_basis": obj.source_basis,
            "group": _json(group),
        }
    return basis, reader


def validate_binding(s, ctx, pid, request, order, occurrence, *, new_write=False):
    _require(
        occurrence.scope == request.scope
        and occurrence.change_id == request.id
        and occurrence.order_id == order.id
    )
    _require(
        request.status
        in (
            {"approved", "implementing"}
            if new_write
            else {"approved", "implementing", "verifying", "closed"}
        ),
        "INVALID_STATE",
    )
    _require(
        {v.discipline for v in order.approvals} == set(order.required_disciplines)
        and {"engineering", "manufacturing"} <= set(order.required_disciplines),
        "APPROVAL_REQUIRED",
        403,
    )
    _require(
        all(
            v.actor_id != request.requester_id
            and v.content_digest == order.content_digest
            and v.at <= occurrence.occurred_at
            and deadline_current(v.expires_at, occurrence.occurred_at)
            for v in order.approvals
        ),
        "APPROVAL_REQUIRED",
        403,
    )
    _require(
        deadline_current(order.plan.expires_at, occurrence.occurred_at)
        and occurrence.nature == request.assessments[-1].graph.nature,
        "IMPLEMENTATION_OWNER_MISMATCH",
    )
    item = next((v for v in order.plan.items if v.id == occurrence.item_id), None)
    _require(item is not None and item.intent.id == occurrence.intent_id)
    if new_write:
        _require(
            ctx.actor_id == ctx.requester_id == occurrence.executor_id,
            "NAMED_EXECUTOR_REQUIRED",
            403,
        )
    if isinstance(occurrence, FieldOccurrence):
        return _field_binding(s, ctx, pid, request, item, occurrence), item
    basis = load_followup_basis(
        s,
        ctx,
        pid,
        occurrence.issue_id,
        expected_issue_revision=_current_issue_revision(s, ctx, pid, occurrence.issue_id),
        write=False,
    )
    action = next((v for v in basis.actions if v.action_id == occurrence.action_id), None)
    _require(
        basis.scope == request.scope
        and basis.capa_id == occurrence.capa_id
        and basis.purpose == occurrence.purpose
        and action is not None
        and action.executor_id == occurrence.executor_id
        and action.action_sha256 == occurrence.action_sha256
    )
    _require(
        any(
            r.kind in {"issue", "capa"} and r.id == occurrence.issue_id
            for r in (*request.roots, *request.references)
        )
    )
    return basis, item


def _field_binding(s, ctx, pid, request, item, occurrence):
    """Use the actual selected Field intent, never fabricate a CAPA basis."""
    from pdos_next import change_controlled_owner as controlled
    from pdos_next.change_controlled_schemas import FieldIntentTarget, FieldSelectionMaterial
    from pdos_next.field_change_selection import load_basis, parse_material

    proof = controlled.selection_callback(
        s, ctx, pid, scope=request.scope, purpose=occurrence.purpose, item=item, request=request
    )
    _, selected = controlled.selection_pointer(s, ctx, pid, request.scope, request.id, item.id)
    _require(selected is not None and selected.basis_kind == "field_intent")
    material = parse_material(selected.material)
    _require(isinstance(material, FieldSelectionMaterial), "IMPLEMENTATION_MATERIAL_MISMATCH")
    _require(
        occurrence.selection_id == selected.id
        and occurrence.selection_revision == selected.revision
        and occurrence.selection_sha256 == selected.material_sha256
        and occurrence.selection_sha256 == digest(material)
        and material.scope == request.scope
        and material.purpose == occurrence.purpose
        and material.change_id == request.id
        and material.item == item
        and material.feedback == occurrence.feedback
        and material.feedback_version_id == occurrence.feedback_version_id
        and material.feedback_sha256 == occurrence.feedback_sha256
        and selected.feedback_id == occurrence.feedback.id
        and selected.feedback_version_id == occurrence.feedback_version_id
        and selected.feedback_revision == occurrence.feedback.revision
        and selected.feedback_sha256 == occurrence.feedback_sha256
        and selected.executor_id == occurrence.executor_id
        and material.executor_id == occurrence.executor_id
        and material.nature == occurrence.nature == proof.nature,
        "IMPLEMENTATION_MATERIAL_MISMATCH",
    )
    basis, intent = load_basis(
        s,
        ctx,
        pid,
        FieldIntentTarget(
            kind="field_intent",
            feedback=occurrence.feedback,
            executor_id=occurrence.executor_id,
        ),
        item,
        request,
        request.scope,
        occurrence.purpose,
        material.nature,
    )
    _require(
        basis.feedback_id == occurrence.feedback.id
        and basis.feedback_revision == occurrence.feedback.revision
        and basis.feedback_version_id == occurrence.feedback_version_id
        and basis.feedback_sha256 == occurrence.feedback_sha256
        and intent.intent_id == occurrence.intent_id
        and intent.executor_id == occurrence.executor_id,
        "IMPLEMENTATION_MATERIAL_MISMATCH",
    )
    return basis


def _current_issue_revision(s, ctx, pid, identity):
    from pdos_next.domain.quality_execution.service import get_issue

    row, view = get_issue(s, ctx, pid, identity, write=False)
    return row.revision


@dataclass(frozen=True)
class CaptureRead:
    row: object
    fact: ImplementationFact
    occurrence: Occurrence | FieldOccurrence
    output_basis: dict


def fact_matches_occurrence(fact, occurrence):
    _require(
        fact.id == occurrence.implementation_id
        and all(
            getattr(fact, k) == getattr(occurrence, k)
            for k in (
                "reconciles_id",
                "item_id",
                "intent_id",
                "executor_id",
                "outcome",
                "occurred_at",
                "sources",
                "outputs",
                "note",
                "nature",
            )
        ),
        "IMPLEMENTATION_MATERIAL_MISMATCH",
    )


def read_capture(s, ctx, pid, request, order, fact_id, *, new_write=False):
    from pdos_next.change_order_service import _one

    row = _one(
        s,
        store.ImplementationCapture,
        store.ImplementationCapture.tenant_id == ctx.tenant_id,
        store.ImplementationCapture.product_id == pid,
        store.ImplementationCapture.change_id == request.id,
        store.ImplementationCapture.order_id == order.id,
        store.ImplementationCapture.fact_id == fact_id,
    )
    _require(row.visibility == request.audience[0].split(":", 1)[0] or row.visibility == "category")
    if row.visibility == "private":
        _require(row.owner_id == ctx.requester_id, "FORBIDDEN_SCOPE", 403)
    fact = ImplementationFact.model_validate(row.fact_snapshot)
    occurrence = parse_occurrence(row.occurrence_snapshot)
    _require(
        fact.id == occurrence.implementation_id == row.fact_id
        and fact.executor_id == row.executor_id
        and fact.received_at == row.created_at
    )
    fact_matches_occurrence(fact, occurrence)
    if new_write:
        _require(
            deadline_current(row.expires_at)
            and row.change_revision == request.revision
            and row.change_version_id is not None,
            "CAPTURE_STALE",
        )
    raw, _ = original_occurrence(s, ctx, pid, SourceRef.model_validate(row.sources[0]))
    _require(raw == occurrence, "SOURCE_STALE")
    validate_binding(s, ctx, pid, request, order, occurrence, new_write=new_write)
    outputs, reader = verify_outputs(s, ctx, pid, request, order, fact)
    _require(outputs == row.output_basis, "SOURCE_STALE")
    old._evidence(
        s,
        ctx,
        pid,
        row.required_source_read_set,
        [SourceRef.model_validate(v) for v in row.sources],
    )
    return CaptureRead(row, fact, occurrence, outputs)


def prepare_capture(s, ctx, pid, input):
    from pdos_next.change_order_service import _one, current_fixed, snapshot
    from pdos_next.change_order_service import clock as actualclock

    uow = _uow(s)
    _one(s, Product, Product.tenant_id == ctx.tenant_id, Product.id == pid, lock=True)
    old._human(s, ctx, pid, write=True)
    row = old._version(s, ctx, pid, input.change_id, input.expected_change_revision)
    request = snapshot(row)
    pointer, current = current_fixed(s, ctx, pid, input.change_id, lock=True)
    _require((current.id, current.revision) == (row.id, row.revision), "VERSION_CONFLICT")
    _require(input.visibility == row.visibility, "CHANGE_AUDIENCE_MISMATCH", 403)
    order = next((v for v in request.orders if v.id == input.order_id), None)
    _require(order is not None)
    observed, artifact = original_occurrence(s, ctx, pid, input.source)
    _require(
        observed.item_id == input.item_id and observed.executor_id == ctx.requester_id,
        "NAMED_EXECUTOR_REQUIRED",
        403,
    )
    basis, item = validate_binding(s, ctx, pid, request, order, observed, new_write=True)
    originalintent = common_digest(input.model_dump(mode="json"))
    oldrow = s.scalar(
        select(store.ImplementationCapture)
        .where(
            store.ImplementationCapture.tenant_id == ctx.tenant_id,
            store.ImplementationCapture.product_id == pid,
            store.ImplementationCapture.executor_id == ctx.requester_id,
            store.ImplementationCapture.capture_key == input.capture_key,
        )
        .execution_options(autoflush=False, populate_existing=True)
    )
    if oldrow is not None:
        _require(oldrow.input_digest == originalintent, "DUPLICATE_INTENT_CONFLICT")
        return read_capture(s, ctx, pid, request, order, oldrow.fact_id, new_write=False).row
    received = actualclock()
    fact = ImplementationFact(
        id=observed.implementation_id,
        reconciles_id=observed.reconciles_id,
        item_id=item.id,
        intent_id=item.intent.id,
        executor_id=ctx.requester_id,
        outcome=observed.outcome,
        occurred_at=observed.occurred_at,
        received_at=received,
        sources=observed.sources,
        outputs=observed.outputs,
        note=observed.note,
        nature=observed.nature,
    )
    _require(observed.occurred_at <= artifact.created_at <= received, "INVALID_EVENT_TIME", 422)
    _require(
        fact.reconciles_id is None
        or any(
            v.id == fact.reconciles_id
            and v.outcome == "unknown"
            and (v.item_id, v.intent_id, v.executor_id, v.occurred_at)
            == (fact.item_id, fact.intent_id, fact.executor_id, fact.occurred_at)
            for v in order.implementations
        ),
        "INVALID_RECONCILIATION",
    )
    outputs, reader = verify_outputs(s, ctx, pid, request, order, fact)
    sources = tuple(dict.fromkeys((input.source, *observed.sources, *basis.sources)))
    reads = old._merge_reads(
        old._source_reads(sources),
        row.required_source_read_set,
        [
            v.model_dump(mode="json") if hasattr(v, "model_dump") else dict(v)
            for v in basis.required_source_read_set
        ],
        *[v.reads for v in reader.objects.values()],
    )
    sourcebasis, private, _ = old._evidence(s, ctx, pid, reads, sources)
    _require(not private or row.visibility == "private", "AUDIENCE_USE_FORBIDDEN", 403)
    # Real original/source/current checks occur again after all output/byte IO.
    again, _ = original_occurrence(s, ctx, pid, input.source)
    _require(again == observed, "SOURCE_STALE")
    validate_binding(s, ctx, pid, request, order, observed, new_write=True)
    finaloutputs, _ = verify_outputs(s, ctx, pid, request, order, fact)
    _require(finaloutputs == outputs, "SOURCE_STALE")
    old._human(s, ctx, pid, write=True)
    final, _ = current_fixed(s, ctx, pid, request.id)
    _require(
        (final.version_id, final.revision) == (pointer.version_id, pointer.revision),
        "VERSION_CONFLICT",
    )
    _same_uow(s, uow, ctx, common_digest(vars(ctx)))
    at = actualclock()
    _require(
        deadline_current(
            earliest_deadline(order.plan.expires_at, *[v.expires_at for v in order.approvals]), at
        ),
        "APPROVAL_EXPIRED",
    )
    result = store.ImplementationCapture(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=pid,
        project_id=row.project_id,
        change_id=row.change_id,
        change_version_id=row.id,
        change_revision=row.revision,
        revision=1,
        owner_id=row.owner_id,
        visibility=row.visibility,
        executor_id=ctx.requester_id,
        order_id=order.id,
        item_id=item.id,
        fact_id=fact.id,
        capture_key=input.capture_key,
        input_digest=originalintent,
        fact_snapshot=fact.model_dump(mode="json"),
        occurrence_snapshot=observed.model_dump(mode="json"),
        sources=[v.model_dump(mode="json") for v in sources],
        required_source_read_set=reads,
        source_basis=sourcebasis,
        output_basis=outputs,
        created_at=fact.received_at,
        expires_at=earliest_deadline(
            order.plan.expires_at,
            *[v.expires_at for v in order.approvals],
        ),
    )
    s.add(result)
    s.flush([result])
    return result


def capture_view(row):
    """Materialize the public capture before commit expires the ORM instance."""
    return {
        "id": str(row.id),
        "revision": row.revision,
        "change_id": str(row.change_id),
        "change_revision": row.change_revision,
        "order_id": str(row.order_id),
        "item_id": str(row.item_id),
        "fact_id": str(row.fact_id),
        "fact": deepcopy(row.fact_snapshot),
        "required_source_read_set": deepcopy(row.required_source_read_set),
        "created_at": row.created_at.isoformat(),
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }


@dataclass(frozen=True, eq=False)
class ApprovedImplementationRead:
    version: object
    implementation: object
    receipt_id: UUID
    occurrence: Occurrence | FieldOccurrence
    material: dict
    valid_until: datetime


class ApprovedImplementationOwner:
    """Startup owner; opaque reads are registered to actual Session/UOW, not client flags."""

    def __init__(self, engine):
        self.engine = engine
        self._reads = WeakKeyDictionary()

    def read(self, s, ctx, pid, *, implementation_version_id):
        from pdos_next.change_order_service import _one, _policy, current_fixed, runtime, snapshot

        uow = _uow(s)
        _require(s.get_bind() is self.engine, "IMPLEMENTATION_OWNER_REQUIRED", 503)
        old._human(s, ctx, pid, write=False)
        stamp = old._runtime_stamp(s)
        configured_stamp, callbacks = runtime(s)
        version = _one(
            s,
            ChangeRequestVersion,
            ChangeRequestVersion.tenant_id == ctx.tenant_id,
            ChangeRequestVersion.product_id == pid,
            ChangeRequestVersion.id == implementation_version_id,
        )
        _require(
            version.visibility != "private" or version.owner_id == ctx.requester_id,
            "FORBIDDEN_SCOPE",
            403,
        )
        request = snapshot(version)
        from pdos_next.domain.projects.models import Project

        project = _one(
            s,
            Project,
            Project.tenant_id == ctx.tenant_id,
            Project.product_id == pid,
            Project.id == version.project_id,
        )
        project_stamp = (project.owner_id, project.visibility, project.scope, project.status)
        _require(
            project.visibility != "private" or project.owner_id == ctx.requester_id,
            "FORBIDDEN_SCOPE",
            403,
        )
        atom = _one(
            s,
            store.ChangeImplementationRecord,
            store.ChangeImplementationRecord.tenant_id == ctx.tenant_id,
            store.ChangeImplementationRecord.product_id == pid,
            store.ChangeImplementationRecord.change_version_id == version.id,
            store.ChangeImplementationRecord.change_revision == version.revision,
        )
        fact = ImplementationFact.model_validate(atom.fact_snapshot)
        order = next(v for v in request.orders if v.id == atom.order_id)
        _require(
            fact in order.implementations and fact.outcome == "succeeded",
            "IMPLEMENTATION_INCOMPLETE",
        )
        captured = read_capture(s, ctx, pid, request, order, fact.id, new_write=False)
        group = common_group(
            s,
            ctx,
            pid,
            version,
            operation="change.implementation.record",
            event="change.implementation_recorded",
            actor=fact.executor_id,
        )
        _require(group["receipt"]["subject_type"] == "change_request")
        _atom_proof(s, ctx, pid, atom, group)
        original = _one(
            s,
            store.ChangeOrderRecord,
            store.ChangeOrderRecord.tenant_id == ctx.tenant_id,
            store.ChangeOrderRecord.product_id == pid,
            store.ChangeOrderRecord.order_id == order.id,
            store.ChangeOrderRecord.change_id == request.id,
        )
        original_version = _one(
            s,
            ChangeRequestVersion,
            ChangeRequestVersion.tenant_id == ctx.tenant_id,
            ChangeRequestVersion.product_id == pid,
            ChangeRequestVersion.id == original.change_version_id,
        )
        original_group = common_group(
            s,
            ctx,
            pid,
            original_version,
            operation="change.order.prepare",
            event="change.order_prepared",
            actor=original.actor_id,
        )
        _atom_proof(s, ctx, pid, original, original_group)
        _require(
            original.authority_snapshot.get("subject_id") == str(original.actor_id),
            "INTEGRITY_MISMATCH",
        )
        _require(
            professional.recheck_snapshot(
                s,
                ctx,
                pid,
                version.project_id,
                original.authority_snapshot,
                fact.occurred_at,
                write=False,
                retained=True,
            )["current"]
            is True,
            "RECHECK_REQUIRED",
        )
        policy = _policy(
            s, ctx, pid, request.scope, captured.occurrence.purpose, version, request, callbacks
        )
        _require(policy.model_dump(mode="json") == atom.policy_snapshot, "RECHECK_REQUIRED")
        _require(
            original.content_sha256 == order.content_digest
            and original.order_snapshot["plan"] == order.plan.model_dump(mode="json"),
            "INTEGRITY_MISMATCH",
        )
        for approval in order.approvals:
            approved = _one(
                s,
                store.ChangeApprovalRecord,
                store.ChangeApprovalRecord.tenant_id == ctx.tenant_id,
                store.ChangeApprovalRecord.product_id == pid,
                store.ChangeApprovalRecord.change_id == request.id,
                store.ChangeApprovalRecord.order_id == order.id,
                store.ChangeApprovalRecord.discipline == approval.discipline,
            )
            before = _one(
                s,
                ChangeRequestVersion,
                ChangeRequestVersion.tenant_id == ctx.tenant_id,
                ChangeRequestVersion.product_id == pid,
                ChangeRequestVersion.id == approved.change_version_id,
            )
            approval_group = common_group(
                s,
                ctx,
                pid,
                before,
                operation="change.order.approve",
                event="change.approved",
                actor=approval.actor_id,
            )
            _atom_proof(s, ctx, pid, approved, approval_group)
            proof = _one(
                s,
                Confirmation,
                Confirmation.tenant_id == ctx.tenant_id,
                Confirmation.id == approved.shared_proof_id,
            )
            _require(
                proof.consumed is True
                and proof.id == approval.decision_id
                and proof.actor_id == approval.actor_id
                and proof.operation == "change.order.approve"
                and proof.revision == approved.shared_proof_revision
                and proof.token_hash == approved.token_sha256
                and proof.payload_digest == approved.material_sha256
                and proof.created_at <= approved.proof_consumed_at <= approved.created_at
                and proof_deadline_current("T2", proof.expires_at, approved.created_at),
                "IMPLEMENTATION_GROUP_MISMATCH",
            )
            _require(
                approved.authority_snapshot.get("subject_id") == str(approval.actor_id),
                "INTEGRITY_MISMATCH",
            )
            _require(
                professional.recheck_snapshot(
                    s,
                    ctx,
                    pid,
                    version.project_id,
                    approved.authority_snapshot,
                    fact.occurred_at,
                    write=False,
                    retained=True,
                )["current"]
                is True,
                "RECHECK_REQUIRED",
            )
        old._evidence(
            s,
            ctx,
            pid,
            version.required_source_read_set,
            [SourceRef.model_validate(v) for v in version.sources],
        )
        material = {
            "version": version.request_snapshot,
            "atom": atom.fact_snapshot,
            "capture": captured.row.occurrence_snapshot,
            "outputs": captured.output_basis,
            "group": _json(group),
            "sources": version.source_basis,
        }
        # current pointer may legally append later history; fixed implementation must
        # remain an exact prefix member, never swapped for a guessed latest fact.
        pointer, current = current_fixed(s, ctx, pid, request.id)
        current_request = snapshot(current)
        _require(
            any(
                f == fact
                for o in current_request.orders
                if o.id == order.id
                for f in o.implementations
            ),
            "RECHECK_REQUIRED",
        )
        old._human(s, ctx, pid, write=False)
        project = _one(
            s,
            Project,
            Project.tenant_id == ctx.tenant_id,
            Project.product_id == pid,
            Project.id == version.project_id,
        )
        _require(
            (project.owner_id, project.visibility, project.scope, project.status) == project_stamp
            and (project.visibility != "private" or project.owner_id == ctx.requester_id),
            "FORBIDDEN_SCOPE",
            403,
        )
        _require(
            _policy(
                s,
                ctx,
                pid,
                request.scope,
                captured.occurrence.purpose,
                version,
                request,
                callbacks,
                previous=policy,
            )
            == policy,
            "SOURCE_STALE",
        )
        _require(
            old._runtime_stamp(s) == stamp and runtime(s)[0] == configured_stamp, "SOURCE_STALE"
        )
        _same_uow(s, uow, ctx, common_digest(vars(ctx)))
        grant = _one(
            s,
            Grant,
            Grant.tenant_id == ctx.tenant_id,
            Grant.category_id == category_for_product(pid),
            Grant.principal_id == ctx.requester_id,
        )
        person = _one(
            s, Principal, Principal.tenant_id == ctx.tenant_id, Principal.id == ctx.requester_id
        )
        _require(
            person.active is True
            and person.kind == "human"
            and clock() < earliest_deadline(grant.expires_at, policy.valid_until),
            "FORBIDDEN_SCOPE",
            403,
        )
        value = ApprovedImplementationRead(
            version, atom, group["receipt"]["id"], captured.occurrence, material, grant.expires_at
        )
        self._reads[value] = (
            s,
            uow,
            common_digest(vars(ctx)),
            digest(material),
            stamp,
        )
        return value

    def refresh(self, s, ctx, pid, previous):
        registered = self._reads.get(previous)
        _require(
            registered is not None and registered[0] is s,
            "IMPLEMENTATION_OWNER_REQUIRED",
            503,
        )
        _same_uow(s, registered[1], ctx, registered[2])
        value = self.read(s, ctx, pid, implementation_version_id=previous.version.id)
        _require(value.material == previous.material, "SOURCE_STALE")
        return value

    def attest(self, s, ctx, pid, previous):
        # Full refresh now; do not turn the stored DTO/hash into current authorization.
        fresh = self.refresh(s, ctx, pid, previous)
        from pdos_next.domain.quality_followup.schemas import OwnerImplementationProof

        _require(clock() < fresh.valid_until, "SOURCE_STALE")
        return OwnerImplementationProof(
            kind="approved_change_implementation",
            id=fresh.version.id,
            revision=fresh.version.revision,
            receipt_id=fresh.receipt_id,
            sha256=digest(fresh.material),
            status="implemented",
            current=True,
        )
