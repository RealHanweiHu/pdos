"""One T1 recipient review, using the common atomic command and receipt path."""

from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select

from pdos_next.change_implementation_owner import common_group
from pdos_next.contracts import Command
from pdos_next.domain.preproject.access import human
from pdos_next.domain.quality_execution.evidence import merge_reads
from pdos_next.domain.work_management import owner
from pdos_next.domain.work_management.models import WorkCommitmentVersion
from pdos_next.domain.work_management.rules import semantic
from pdos_next.domain.work_management.service import _merge_basis, _without_recorded
from pdos_next.models import now
from pdos_next.service import command_digest, command_scope, digest
from pdos_next.source_current import direct_source_basis

from .models import EVENT, OPERATION, SUBJECT, WorkCommitmentReview, WorkCommitmentReviewCurrent
from .rules import require, review_state
from .schemas import CommitmentReviewPayload

category_lifecycle_fence = True
EFFECT = "仅登记本接收者对固定承诺成果的核对；不改变任务、承诺原文或日期。"


@dataclass
class Validated:
    session: object
    transaction: object
    fingerprint: str
    project: object
    promise: object
    task: object
    submission: object
    previous: object
    pointer: object
    plan: object
    sources: list
    reads: list
    source_basis: dict
    review: dict
    confirmation_id: object = None
    used: bool = False


def retained(s, ctx, pid, row):
    require(
        row is not None
        and (row.tenant_id, row.category_id, row.product_id)
        == (ctx.tenant_id, ctx.category_id, pid),
        "承诺核对记录不在当前受众内。",
        "FORBIDDEN_SCOPE",
        403,
    )
    require(digest(row.body) == row.body_sha256, "承诺核对摘要无法核对。", "INTEGRITY_MISMATCH")
    common_group(s, ctx, pid, row, operation=OPERATION, event=EVENT, key_binding="project_work")
    return row


def validate(s, ctx, command, product, payload):
    key = ("commitment-fulfillment", digest(vars(ctx)), command_digest(command))
    cached = s.info.get(key)
    if cached is not None and cached.transaction is s.get_transaction() and not cached.used:
        return cached
    human(s, ctx)
    require(
        command.expected_revision == product.revision, "型号范围版本已变化。", "VERSION_CONFLICT"
    )
    project = owner.project(s, ctx, product.id, payload.project_id, lock=True)
    fixed = s.scalar(
        select(WorkCommitmentVersion).where(
            WorkCommitmentVersion.tenant_id == ctx.tenant_id,
            WorkCommitmentVersion.product_id == product.id,
            WorkCommitmentVersion.id == payload.commitment.id,
        )
    )
    require(
        fixed is not None and fixed.project_id == project.id,
        "固定承诺不在本项目受众内。",
        "FORBIDDEN_SCOPE",
        403,
    )
    require(
        fixed.recipient_id == ctx.requester_id,
        "只有原承诺接收者本人可核对履行。",
        "FORBIDDEN_SCOPE",
        403,
    )
    task, task_snapshot, _ = owner.task(
        s, ctx, product.id, payload.task.id, revision=payload.task.revision, lock=True
    )
    promise, promise_snapshot, _ = owner.commitment(
        s, ctx, product.id, fixed.task_id, fixed.promisor_id, fixed.recipient_id, lock=True
    )
    require(
        promise is not None
        and promise.id == payload.commitment.id
        and promise.revision == payload.commitment.revision,
        "承诺已续版，须重新核对。",
        "VERSION_CONFLICT",
    )
    require(
        task.task_id == promise.task_id and task.project_id == project.id,
        "实际任务与承诺范围不一致。",
        "FORBIDDEN_SCOPE",
        403,
    )
    submission, submitted, _ = owner.task(
        s, ctx, product.id, promise.task_id, revision=payload.submission.revision, fixed=True
    )
    require(
        submission.id == payload.submission.id
        and submission.action == "submit"
        and submission.operation == "work.task.submit"
        and submission.actor_id == promise.promisor_id,
        "须固定承诺人本人的实际提交记录。",
        "VERSION_CONFLICT",
    )
    pointer = s.scalar(
        select(WorkCommitmentReviewCurrent)
        .where(
            WorkCommitmentReviewCurrent.tenant_id == ctx.tenant_id,
            WorkCommitmentReviewCurrent.product_id == product.id,
            WorkCommitmentReviewCurrent.commitment_id == promise.id,
        )
        .with_for_update()
    )
    previous = (
        retained(s, ctx, product.id, s.get(WorkCommitmentReview, pointer.version_id))
        if pointer
        else None
    )
    state = review_state(
        payload,
        promise_snapshot,
        task_snapshot,
        submitted,
        actor_id=ctx.requester_id,
        previous=previous,
    )
    refs = sorted(set(payload.sources), key=lambda ref: (str(ref.id), ref.revision, ref.position))
    basis, private = direct_source_basis(s, ctx, product, refs, command.source_read_set)
    require(
        not private or project.visibility == "private",
        "私有原件不能随履行核对扩大到共享项目。",
        "FORBIDDEN_SCOPE",
        403,
    )
    for row in (promise, task, submission):
        owner.sources_current(s, ctx, product.id, row.source_basis)
    source_basis = _merge_basis(
        promise.source_basis, task.source_basis, submission.source_basis, {"artifacts": basis}
    )
    at = now()
    body = {
        "commitment": {"id": str(promise.id), "revision": promise.revision},
        "series_id": str(promise.series_id),
        "task": {"id": str(task.task_id), "revision": task.revision},
        "task_version_id": str(task.id),
        "submission": {"id": str(submission.id), "revision": submission.revision},
        "promisor_id": str(promise.promisor_id),
        "recipient_id": str(promise.recipient_id),
        "decision": payload.decision,
        "state": state,
        "checks": [check.model_dump(mode="json") for check in payload.checks],
        "previous": {"id": str(previous.id), "revision": previous.revision} if previous else None,
        "time": {"actor_id": str(ctx.requester_id), "recorded_at": at.isoformat()},
        "reason": payload.reason,
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
        "before": {"review": body["previous"], "state": previous.state if previous else "open"},
        "after": _without_recorded(body),
        "sources": sources,
        "source_basis": source_basis,
        "effect": EFFECT,
    }
    value = Validated(
        s,
        s.get_transaction(),
        command_digest(command),
        project,
        promise,
        task,
        submission,
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
    payload = CommitmentReviewPayload.model_validate(command.payload)
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
        "须使用本次实际事务核对过的承诺材料。",
        "INTEGRITY_MISMATCH",
    )
    value.used = True
    envelope = command.model_dump(mode="json", exclude={"idempotency_key"})
    envelope["payload"] = semantic(payload)
    promise, task, submitted, previous = value.promise, value.task, value.submission, value.previous
    body = value.plan
    row = WorkCommitmentReview(
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
        revision=previous.revision + 1 if previous else 1,
        commitment_id=promise.id,
        commitment_revision=promise.revision,
        series_id=promise.series_id,
        task_id=task.task_id,
        task_revision=task.revision,
        task_version_id=task.id,
        submission_id=submitted.id,
        submission_revision=submitted.revision,
        promisor_id=promise.promisor_id,
        recipient_id=promise.recipient_id,
        previous_id=previous.id if previous else None,
        previous_revision=previous.revision if previous else None,
        decision=payload.decision,
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
            WorkCommitmentReviewCurrent(
                tenant_id=ctx.tenant_id,
                category_id=ctx.category_id,
                product_id=product.id,
                project_id=row.project_id,
                owner_id=row.owner_id,
                visibility=row.visibility,
                commitment_id=promise.id,
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
        "commitment_id": str(promise.id),
        "task_id": str(task.task_id),
        "recipient_id": str(promise.recipient_id),
        "project_id": str(row.project_id),
    }
    row._fulfillment_phase = value
    return row, SUBJECT, row.visibility


def finalize_receipt(s, ctx, command, product, payload, subject, receipt):
    value = getattr(subject, "_fulfillment_phase", None)
    require(
        value is not None
        and value.used
        and value.session is s
        and value.transaction is s.get_transaction()
        and subject.receipt_id == receipt.id
        and digest(subject.body) == subject.body_sha256,
        "履行核对缺原事务的共同回执绑定。",
        "INTEGRITY_MISMATCH",
    )
    owner.sources_current(s, ctx, product.id, value.source_basis)
    del subject._fulfillment_phase
