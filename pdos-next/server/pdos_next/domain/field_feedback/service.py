"""Field source facts and responses use the shared command/confirmation UOW."""

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4, uuid5

from pdos_next.contracts import Command
from pdos_next.domain.knowledge import provenance
from pdos_next.domain.knowledge.rules import merge_artifacts
from pdos_next.domain.preproject.access import human
from pdos_next.domain.quality_execution.evidence import merge_reads
from pdos_next.domain.work_management.rules import require
from pdos_next.models import Category
from pdos_next.service import command_digest, command_scope, digest

from . import owner
from .models import FieldFeedbackCurrent, FieldFeedbackVersion, FieldResponseRecord
from .schemas import ACTION, CREATE, LINK, LOCATE, PAYLOADS, semantic

category_lifecycle_fence = True


@dataclass
class Validated:
    session: object
    transaction: object
    fingerprint: str
    identity: object
    version_id: object
    revision: int
    previous: object
    pointer: object
    project_id: object
    owner_id: object
    visibility: str
    body: dict
    source_basis: dict
    review: dict
    parent: object = None
    confirmation_id: object = None
    used: bool = False


def _material(s, ctx, product, payload):
    if not hasattr(payload, "engineering_configuration"):
        return None
    return owner.location(s, ctx, product.id, payload)


def validate(s, ctx, command, product, payload):
    key = ("field-command", digest(vars(ctx)), command_digest(command), str(command.command_id))
    cached = s.info.get(key)
    if cached is not None and cached.transaction is s.get_transaction() and not cached.used:
        return cached
    require(command.expected_revision == product.revision, "当前范围已变化。", "VERSION_CONFLICT")
    if not ctx.agent_run_id:
        human(s, ctx)
    artifacts, private = provenance.direct_basis(
        s, ctx, product, payload.sources, command.source_read_set
    )
    private |= getattr(product, "visibility", "category") != "category"
    prior = pointer = parent = None
    identity = version_id = uuid5(command.command_id, "field-object")
    revision, project_id, owner_id = 1, None, ctx.requester_id
    visibility = getattr(payload, "visibility", "private")
    results, result_artifacts = [], []
    if command.operation == CREATE:
        body = {
            "feedback_id": str(identity),
            "revision": 1,
            **{
                key: semantic(payload)[key]
                for key in (
                    "title",
                    "description",
                    "channel",
                    "feedback_kind",
                    "received_at",
                    "reported",
                    "purpose",
                )
            },
            "location": None,
        }
    else:
        parent, pointer = owner.current(
            s, ctx, payload.feedback.id, payload.feedback.revision, lock=True
        )
        require(
            parent.product_id in (None, product.id),
            "本轮定位不跨型号改写反馈；请核对原范围。",
            "FORBIDDEN_SCOPE",
            403,
        )
        if command.operation == LOCATE:
            require(
                parent.owner_id == ctx.requester_id,
                "反馈定位由原反馈所有者确认。",
                "FORBIDDEN_SCOPE",
                403,
            )
            provenance.sources_current(s, ctx, parent.source_basis)
            located, refs, _, target_private = _material(s, ctx, product, payload)
            native_artifacts, native_private = provenance.direct_basis(
                s, ctx, product, refs, command.source_read_set
            )
            artifacts = merge_artifacts(
                artifacts, parent.source_basis["artifacts"], native_artifacts
            )
            private |= target_private or native_private or parent.visibility != "category"
            visibility, owner_id = parent.visibility, parent.owner_id
            identity, version_id, revision = (
                parent.feedback_id,
                uuid5(command.command_id, "field-version"),
                parent.revision + 1,
            )
            project_id = payload.project_id
            if located["project_id"]:
                from uuid import UUID

                project_id = UUID(located["project_id"])
            prior = parent
            body = {**deepcopy(parent.body), "revision": revision, "location": located}
        else:
            require(
                parent.product_id == product.id,
                "处置须在反馈当前实际范围记录。",
                "FORBIDDEN_SCOPE",
                403,
            )
            project_id = parent.project_id
            private |= parent.visibility != "category"
            # Retained facts stay readable after withdrawal; only this action's new
            # evidence is being adopted. Never pretend a prior report is current.
            artifacts = merge_artifacts(parent.source_basis["artifacts"], artifacts)
            if command.operation == LINK:
                results, result_artifacts, hidden = provenance.results(
                    s, ctx, payload.result_receipts
                )
                require(
                    all(
                        item["product_id"] == str(product.id)
                        and item["project_id"] == str(project_id)
                        for item in results
                    ),
                    "后续结果须属于已定位的同一实际项目。",
                    "FORBIDDEN_SCOPE",
                    403,
                )
                private |= hidden
            body = {
                "feedback": payload.feedback.model_dump(mode="json"),
                "feedback_version_id": str(parent.id),
                "response_kind": payload.action_kind if command.operation == ACTION else "followup",
                "description": payload.description,
                "occurred_at": payload.occurred_at.isoformat(),
                "result_receipts": [
                    value.model_dump(mode="json")
                    for value in getattr(payload, "result_receipts", ())
                ],
            }
            pointer = None
    require(
        not private or visibility == "private",
        "私有来源不能扩大为品类共享反馈。",
        "FORBIDDEN_SCOPE",
        403,
    )
    basis = {"artifacts": merge_artifacts(artifacts, result_artifacts), "result_receipts": results}
    review = {
        "operation": command.operation,
        "declaration": semantic(payload),
        "before": deepcopy(prior.body) if prior else None,
        "after": body,
        "sources": [value.model_dump(mode="json") for value in payload.sources],
        "source_basis": basis,
        "effect": (
            "记录来源事实、实际定位或独立跟进；客户意见与承认声明不批准工程/制造放行，"
            "链接结果不代替实施或复验。"
        ),
    }
    value = Validated(
        s,
        s.get_transaction(),
        command_digest(command),
        identity,
        version_id,
        revision,
        prior,
        pointer,
        project_id,
        owner_id,
        visibility,
        body,
        basis,
        review,
        parent,
    )
    s.info[key] = value
    return value


def confirmation_subject(s, ctx, command, product, payload):
    return (
        ("product", product)
        if product.id is not None
        else ("category", s.get(Category, ctx.category_id))
    )


def preview_view(s, ctx, command, product, payload):
    return validate(s, ctx, command, product, payload).review


def inputs(s, ctx, pid, command):
    require(
        command.product_id == pid
        and command.category_id == ctx.category_id
        and command.operation in PAYLOADS,
        "反馈输入与实际范围不一致。",
        "FORBIDDEN_SCOPE",
        403,
    )
    payload = PAYLOADS[command.operation].model_validate(command.payload)
    product = command_scope(s, ctx, command, lock=True)
    reads = [
        {"artifact_id": str(ref.id), "expected_revision": ref.revision} for ref in payload.sources
    ]
    material = _material(s, ctx, product, payload)
    if material is not None:
        parent, _ = owner.current(s, ctx, payload.feedback.id, payload.feedback.revision)
        reads = merge_reads(reads, parent.reads, material[2])
    if command.operation == LINK:
        native, _, _ = provenance.results(s, ctx, payload.result_receipts)
        reads = merge_reads(
            reads,
            [
                {"artifact_id": ref["id"], "expected_revision": ref["revision"]}
                for result in native
                for ref in result["direct_content_refs"]
            ],
        )
    prepared = Command.model_validate(
        {**command.model_dump(mode="json"), "source_read_set": merge_reads(reads)}
    )
    value = validate(s, ctx, prepared, product, payload)
    return {
        "payload": semantic(payload),
        "required_source_read_set": prepared.model_dump(mode="json")["source_read_set"],
        "review": value.review,
    }


def apply_validated(s, ctx, command, product, payload, value):
    require(
        value.session is s
        and value.transaction is s.get_transaction()
        and value.fingerprint == command_digest(command)
        and not value.used,
        "缺少本次事务的反馈核对。",
        "INTEGRITY_MISMATCH",
    )
    value.used = True
    envelope = command.model_dump(mode="json", exclude={"idempotency_key"})
    envelope["payload"] = semantic(payload)
    scope = dict(
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        product_id=product.id,
        project_id=value.project_id,
        owner_id=value.owner_id,
        visibility=value.visibility,
    )
    common = dict(
        **scope,
        id=value.version_id,
        revision=value.revision,
        writer_id=ctx.actor_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        operation=command.operation,
        command_id=command.command_id,
        command={
            "envelope": envelope,
            "review": value.review,
            "original_key_sha256": sha256(command.idempotency_key.encode()).hexdigest(),
        },
        sources=value.review["sources"],
        reads=[read.model_dump(mode="json") for read in command.source_read_set],
        source_basis=value.source_basis,
        body=value.body,
        body_sha256=digest(value.body),
        request_digest=command_digest(command),
        receipt_id=uuid4(),
        confirmation_id=value.confirmation_id,
        intent_digest=digest(
            {
                "operation": command.operation,
                "category": command.category_id,
                "product": command.product_id,
                "payload": semantic(payload),
                "named_actor": ctx.requester_id,
                "source_revision": None,
                "private_owner": ctx.requester_id
                if getattr(payload, "visibility", "private") == "private"
                else None,
            }
        ),
    )
    if command.operation in (CREATE, LOCATE):
        if command.operation == LOCATE:
            refs = value.parent.sources + common["sources"] + value.body["location"]["sources"]
            common["sources"] = list({digest(ref): ref for ref in refs}.values())
        row = FieldFeedbackVersion(
            feedback_id=value.identity,
            previous_id=value.previous.id if value.previous else None,
            previous_revision=value.previous.revision if value.previous else None,
            **common,
        )
        kind = "field_feedback"
        s.add(row)
        s.flush([row])
        if value.pointer is None:
            s.add(
                FieldFeedbackCurrent(
                    **scope, feedback_id=value.identity, version_id=row.id, revision=row.revision
                )
            )
        else:
            value.pointer.version_id, value.pointer.revision = row.id, row.revision
            value.pointer.product_id, value.pointer.project_id = row.product_id, row.project_id
    else:
        row = FieldResponseRecord(
            feedback_id=value.parent.feedback_id,
            feedback_version_id=value.parent.id,
            feedback_revision=value.parent.revision,
            response_kind=value.body["response_kind"],
            **common,
        )
        kind = "field_response"
        s.add(row)
    row.action_result = {
        "feedback_id": str(row.feedback_id),
        "project_id": str(row.project_id) if row.project_id else None,
    }
    row.prepared_receipt_id, row._field_phase = row.receipt_id, value
    return row, kind, row.visibility


def finalize_receipt(s, ctx, command, product, payload, subject, receipt):
    value = getattr(subject, "_field_phase", None)
    require(
        value is not None
        and value.used
        and value.session is s
        and value.transaction is s.get_transaction()
        and subject.receipt_id == receipt.id
        and digest(subject.body) == subject.body_sha256,
        "反馈缺少同事务共同回执。",
        "INTEGRITY_MISMATCH",
    )
    provenance.direct_basis(s, ctx, product, payload.sources, command.source_read_set)
    if command.operation in (CREATE, LOCATE):
        provenance.sources_current(s, ctx, value.source_basis)
    if command.operation == LINK:
        provenance.results_current(s, ctx, value.source_basis)
    if command.operation == LOCATE:
        _material(s, ctx, product, payload)
    del subject._field_phase
