"""T0 ExternalWait declarations through the common command transaction."""

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select

from pdos_next.domain.builds.models import Build
from pdos_next.domain.preproject.access import human, member
from pdos_next.domain.projects.models import PlanRevision, ProjectTask
from pdos_next.domain.work_management.service import _merge_basis
from pdos_next.models import now
from pdos_next.service import command_digest, digest
from pdos_next.source_current import direct_source_basis

from . import calendar_owner, owner, rules
from .models import SUBJECT, ExternalWaitCurrent, ExternalWaitVersion
from .schemas import OPERATION, Payload

category_lifecycle_fence = True
semantic = rules.semantic


@dataclass
class Validated:
    session: object
    transaction: object
    fingerprint: str
    project: object
    plan: object
    previous: object
    pointer: object
    sources: list
    reads: list
    source_basis: dict
    review: dict
    at: object
    used: bool = False


def _anchors(s, ctx, pid, project_id, plan):
    if plan.milestone:
        task = s.scalar(
            select(ProjectTask).where(
                ProjectTask.tenant_id == ctx.tenant_id,
                ProjectTask.category_id == ctx.category_id,
                ProjectTask.product_id == pid,
                ProjectTask.project_id == project_id,
                ProjectTask.id == plan.milestone.id,
            )
        )
        fixed = s.get(PlanRevision, task.plan_id) if task else None
        rules.require(
            fixed is not None and fixed.revision == plan.milestone.revision,
            "里程碑须固定本项目实际计划任务及计划版本。",
            "VERSION_CONFLICT",
        )
    if plan.build:
        build = s.scalar(
            select(Build).where(
                Build.tenant_id == ctx.tenant_id,
                Build.category_id == ctx.category_id,
                Build.product_id == pid,
                Build.project_id == project_id,
                Build.id == plan.build.id,
            )
        )
        rules.require(
            build is not None and build.revision == plan.build.revision,
            "Build须为本项目实际固定版本。",
            "VERSION_CONFLICT",
        )
    if plan.replaces:
        old, _, _ = owner.waiting(
            s, ctx, pid, plan.replaces.id, revision=plan.replaces.revision, fixed=True
        )
        rules.require(
            old.project_id == project_id and old.wait_id != plan.wait_id,
            "替代关系须引用本项目另一实际等待，不自动关闭原记录。",
            "FORBIDDEN_SCOPE",
            403,
        )


def validate(s, ctx, command, product, payload):
    key = ("external-wait", digest(vars(ctx)), command_digest(command))
    cached = s.info.get(key)
    if cached is not None and cached.transaction is s.get_transaction() and not cached.used:
        return cached
    rules.require(
        command.expected_revision == product.revision, "型号范围版本已变化。", "VERSION_CONFLICT"
    )
    project = owner.project(s, ctx, product.id, payload.project_id, lock=True)
    human_actor = not ctx.agent_run_id and not ctx.run_id
    if human_actor:
        human(s, ctx)
    previous, old, pointer = None, None, None
    if payload.wait:
        previous, old, pointer = owner.waiting(
            s, ctx, product.id, payload.wait.id, revision=payload.wait.revision, lock=True
        )
        rules.require(
            previous.project_id == project.id, "等待不属于当前项目。", "FORBIDDEN_SCOPE", 403
        )
        owner.sources_current(s, ctx, product.id, project.id, previous.source_basis)
    if payload.record.action == "transfer_request":
        grant = member(s, ctx, payload.record.to_id)
        rules.require(
            grant.can_write, "接收人须为品类有效、可办理的人类成员。", "FORBIDDEN_SCOPE", 403
        )
    at = now()
    plan = rules.transition(
        payload,
        current=old,
        wait_id=uuid4(),
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        project_owner_id=project.owner_id,
        at=at,
        human_actor=human_actor,
    )
    _anchors(s, ctx, product.id, project.id, plan)
    refs = sorted(set(payload.sources), key=lambda ref: (str(ref.id), ref.revision, ref.position))
    basis, private = direct_source_basis(s, ctx, product, refs, command.source_read_set)
    rules.require(
        not private or project.visibility == "private",
        "私有原件不能随等待扩大到共享项目。",
        "FORBIDDEN_SCOPE",
        403,
    )
    source_basis = _merge_basis(previous.source_basis if previous else {}, {"artifacts": basis})
    if plan.calendar:
        resolved = calendar_owner.resolve(s, ctx, product.id, project.id, plan.calendar)
        adopted = resolved["basis"]
        source_basis = _merge_basis(source_basis, adopted["material"]["source_basis"])
        source_basis["calendar"] = deepcopy(adopted)
    else:
        source_basis["calendar"] = None
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
        "before": old.model_dump(mode="json") if old else None,
        "after": plan.model_dump(mode="json"),
        "sources": [ref.model_dump(mode="json") for ref in refs],
        "source_basis": source_basis,
        "effect": (
            "仅登记内部等待与材料。有效送达、对方声明、实际到达和正式接收分别核对；"
            "责任须接收人本人接受。"
        ),
    }
    value = Validated(
        s,
        s.get_transaction(),
        command_digest(command),
        project,
        plan,
        previous,
        pointer,
        review["sources"],
        [r.model_dump(mode="json") for r in command.source_read_set],
        source_basis,
        review,
        at,
    )
    s.info[key] = value
    return value


def inputs(s, ctx, pid, command):
    from pdos_next.contracts import Command
    from pdos_next.domain.quality_execution.evidence import merge_reads
    from pdos_next.service import command_scope

    rules.require(
        command.product_id == pid
        and command.category_id == ctx.category_id
        and command.operation == OPERATION,
        "材料命令不属于当前等待范围。",
        "FORBIDDEN_SCOPE",
        403,
    )
    payload = Payload.model_validate(command.payload)
    reads = merge_reads(
        [{"artifact_id": str(ref.id), "expected_revision": ref.revision} for ref in payload.sources]
    )
    prepared = Command.model_validate({**command.model_dump(mode="json"), "source_read_set": reads})
    product = command_scope(s, ctx, prepared, lock=True)
    value = validate(s, ctx, prepared, product, payload)
    return {"payload": semantic(payload), "required_source_read_set": reads, "review": value.review}


def apply_validated(s, ctx, command, product, payload, value):
    rules.require(
        value.session is s
        and value.transaction is s.get_transaction()
        and value.fingerprint == command_digest(command)
        and not value.used,
        "须使用本事务实际核对过的等待材料。",
        "INTEGRITY_MISMATCH",
    )
    value.used = True
    envelope = command.model_dump(mode="json", exclude={"idempotency_key"})
    envelope["payload"] = semantic(payload)
    body = value.plan.model_dump(mode="json")
    project, previous = value.project, value.previous
    row = ExternalWaitVersion(
        id=value.plan.wait_id if previous is None else uuid4(),
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        product_id=product.id,
        project_id=project.id,
        owner_id=project.owner_id,
        visibility=project.visibility,
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
        body=body,
        body_sha256=digest(body),
        source_basis=value.source_basis,
        sources=value.sources,
        reads=value.reads,
        receipt_id=uuid4(),
        confirmation_id=None,
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
        created_at=value.at,
        wait_id=value.plan.wait_id,
        revision=value.plan.revision,
        previous_id=previous.id if previous else None,
        previous_revision=previous.revision if previous else None,
        action=payload.record.action,
        state=value.plan.state,
    )
    s.add(row)
    s.flush([row])
    if value.pointer is None:
        s.add(
            ExternalWaitCurrent(
                tenant_id=ctx.tenant_id,
                category_id=ctx.category_id,
                product_id=product.id,
                project_id=project.id,
                owner_id=project.owner_id,
                visibility=project.visibility,
                wait_id=row.wait_id,
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
    row.action_result = {
        "wait_id": str(row.wait_id),
        "state": row.state,
        "project_id": str(row.project_id),
    }
    row.prepared_receipt_id = row.receipt_id
    row._wait_phase = value
    return row, SUBJECT, row.visibility


def finalize_receipt(s, ctx, command, product, payload, subject, receipt):
    value = getattr(subject, "_wait_phase", None)
    rules.require(
        value is not None
        and value.used
        and value.session is s
        and value.transaction is s.get_transaction()
        and subject.receipt_id == receipt.id
        and subject.body_sha256 == digest(subject.body),
        "等待缺少本事务共同回执绑定。",
        "INTEGRITY_MISMATCH",
    )
    owner.sources_current(s, ctx, product.id, value.project.id, value.source_basis)
    _anchors(s, ctx, product.id, value.project.id, value.plan)
    del subject._wait_phase
