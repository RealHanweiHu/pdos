"""T1 internal risk followup via the common atomic command/confirmation path."""

from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

from pdos_next.contracts import Command
from pdos_next.domain.preproject.access import human
from pdos_next.domain.quality_execution.evidence import merge_reads
from pdos_next.domain.work_management import g0_sources
from pdos_next.domain.work_management import owner as work_owner
from pdos_next.domain.work_management.rules import require, semantic
from pdos_next.domain.work_management.service import _merge_basis
from pdos_next.service import command_digest, command_scope, digest
from pdos_next.source_current import direct_source_basis

from . import owner
from .models import OPERATION, SUBJECT, ProjectRiskFollowup, ProjectRiskFollowupCurrent
from .rules import next_state
from .schemas import RiskFollowupPayload

category_lifecycle_fence = True
EFFECT = "仅登记原G0具名跟进人的内部风险跟进结果；不改变任务、规格、专业批准或放行。"


@dataclass
class Validated:
    session: object
    transaction: object
    fingerprint: str
    project: object
    previous: object
    pointer: object
    plan: dict
    sources: list
    reads: list
    source_basis: dict
    review: dict
    confirmation_id: object = None
    used: bool = False


def validate(s, ctx, command, product, payload):
    key = ("project-risk-followup", digest(vars(ctx)), command_digest(command))
    cached = s.info.get(key)
    if cached is not None and cached.transaction is s.get_transaction() and not cached.used:
        return cached
    human(s, ctx)
    require(
        command.expected_revision == product.revision, "型号范围版本已变化。", "VERSION_CONFLICT"
    )
    project = work_owner.project(s, ctx, product.id, payload.project_id, lock=True)
    basis = g0_sources.resolve(s, ctx, product.id, project.id, payload.risk)
    previous, pointer = owner.current(s, ctx, product.id, project, payload.risk.id, lock=True)
    state = next_state(
        payload,
        basis,
        actor_id=ctx.requester_id,
        legacy_status=owner.legacy_status(s, ctx, product.id, project.id, payload.risk.id),
        previous=previous,
    )
    require(
        previous is None or previous.g0_decision_id == payload.risk.decision_id,
        "风险跟进与原 G0 决定不一致。",
        "INTEGRITY_MISMATCH",
    )
    refs = sorted(set(payload.sources), key=lambda ref: (str(ref.id), ref.revision, ref.position))
    direct, private = direct_source_basis(s, ctx, product, refs, command.source_read_set)
    require(
        not private or project.visibility == "private",
        "私有原件不能随风险跟进扩大到共享项目。",
        "FORBIDDEN_SCOPE",
        403,
    )
    source_basis = _merge_basis(previous.source_basis if previous else {}, {"artifacts": direct})
    source_basis["g0_open_item"] = basis
    work_owner.sources_current(s, ctx, product.id, source_basis)
    body = {
        "risk_id": str(payload.risk.id),
        "decision_id": str(payload.risk.decision_id),
        "revision": previous.revision + 1 if previous else 1,
        "state": state,
        "summary": payload.summary,
    }
    sources = [ref.model_dump(mode="json") for ref in refs]
    review = {
        "operation": OPERATION,
        "project": {
            "id": str(project.id),
            "revision": project.revision,
            "name": project.name,
            "owner_id": str(project.owner_id),
            "visibility": project.visibility,
        },
        "declaration": semantic(payload),
        "before": previous.body if previous else None,
        "after": body,
        "sources": sources,
        "source_basis": source_basis,
        "effect": EFFECT,
    }
    value = Validated(
        s,
        s.get_transaction(),
        command_digest(command),
        project,
        previous,
        pointer,
        body,
        sources,
        [read.model_dump(mode="json") for read in command.source_read_set],
        source_basis,
        review,
    )
    s.info[key] = value
    return value


def confirmation_subject(s, ctx, command, product, payload):
    return "product", product


def preview_view(s, ctx, command, product, payload):
    return validate(s, ctx, command, product, payload).review


def inputs(s, ctx, pid, command):
    require(
        command.operation == OPERATION
        and command.product_id == pid
        and command.category_id == ctx.category_id,
        "材料命令与当前范围不一致。",
        "FORBIDDEN_SCOPE",
        403,
    )
    payload = RiskFollowupPayload.model_validate(command.payload)
    reads = merge_reads(
        [{"artifact_id": str(ref.id), "expected_revision": ref.revision} for ref in payload.sources]
    )
    prepared = Command.model_validate({**command.model_dump(mode="json"), "source_read_set": reads})
    product = command_scope(s, ctx, prepared, lock=True)
    value = validate(s, ctx, prepared, product, payload)
    return {"payload": semantic(payload), "required_source_read_set": reads, "review": value.review}


def apply_validated(s, ctx, command, product, payload, value):
    require(
        value.session is s
        and value.transaction is s.get_transaction()
        and value.fingerprint == command_digest(command)
        and not value.used,
        "须使用本次事务核对过的风险跟进材料。",
        "INTEGRITY_MISMATCH",
    )
    value.used = True
    envelope = command.model_dump(mode="json", exclude={"idempotency_key"})
    envelope["payload"] = semantic(payload)
    previous, body = value.previous, value.plan
    row = ProjectRiskFollowup(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        product_id=product.id,
        project_id=value.project.id,
        owner_id=value.project.owner_id,
        visibility=value.project.visibility,
        writer_id=ctx.actor_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        operation=OPERATION,
        command_id=command.command_id,
        command={
            "envelope": envelope,
            "review": value.review,
            "original_key_sha256": sha256(command.idempotency_key.encode()).hexdigest(),
        },
        revision=body["revision"],
        risk_id=payload.risk.id,
        g0_decision_id=payload.risk.decision_id,
        previous_id=previous.id if previous else None,
        previous_revision=previous.revision if previous else None,
        action=payload.action,
        state=body["state"],
        body=body,
        body_sha256=digest(body),
        sources=value.sources,
        reads=value.reads,
        source_basis=value.source_basis,
        receipt_id=uuid4(),
        confirmation_id=value.confirmation_id,
        request_digest=command_digest(command),
        intent_digest=digest(
            {
                "operation": OPERATION,
                "category": command.category_id,
                "product": command.product_id,
                "payload": envelope["payload"],
                "named_actor": ctx.requester_id,
                "source_revision": None,
                "private_owner": ctx.requester_id,
            }
        ),
    )
    s.add(row)
    s.flush([row])
    if value.pointer is None:
        s.add(
            ProjectRiskFollowupCurrent(
                tenant_id=ctx.tenant_id,
                category_id=ctx.category_id,
                product_id=product.id,
                project_id=row.project_id,
                owner_id=row.owner_id,
                visibility=row.visibility,
                risk_id=row.risk_id,
                g0_decision_id=row.g0_decision_id,
                version_id=row.id,
                revision=row.revision,
                state=row.state,
            )
        )
    else:
        value.pointer.version_id, value.pointer.revision, value.pointer.state = (
            row.id,
            row.revision,
            row.state,
        )
    row.prepared_receipt_id = row.receipt_id
    row.action_result = {
        "risk_id": str(row.risk_id),
        "decision_id": str(row.g0_decision_id),
        "state": row.state,
        "project_id": str(row.project_id),
    }
    row._risk_followup_phase = value
    return row, SUBJECT, row.visibility


def finalize_receipt(s, ctx, command, product, payload, subject, receipt):
    value = getattr(subject, "_risk_followup_phase", None)
    require(
        value is not None
        and value.used
        and value.session is s
        and value.transaction is s.get_transaction()
        and subject.receipt_id == receipt.id
        and digest(subject.body) == subject.body_sha256,
        "风险跟进缺原事务的共同回执绑定。",
        "INTEGRITY_MISMATCH",
    )
    work_owner.sources_current(s, ctx, product.id, value.source_basis)
    require(
        owner.legacy_status(s, ctx, product.id, value.project.id, payload.risk.id) == "open",
        "原风险状态已变化，不能完成此跟进。",
        "SOURCE_STALE",
    )
    del subject._risk_followup_phase
