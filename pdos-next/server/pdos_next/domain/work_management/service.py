"""Task, personal commitment and named status writes through the common command UOW."""

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select

from pdos_next.domain.preproject.access import human, member
from pdos_next.domain.projects.models import PlanRevision, ProjectTask
from pdos_next.models import now
from pdos_next.service import command_digest, digest
from pdos_next.source_current import direct_source_basis

from . import g0_sources, owner, rules
from .constants import ASSIGN, COMMIT, CREATE, STATUS, TASK_OPERATIONS
from .models import (
    ProjectStatusUpdate,
    WorkCommitmentCurrent,
    WorkCommitmentVersion,
    WorkTaskCurrent,
    WorkTaskVersion,
)
from .schemas import PAYLOADS, VersionRef

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
    task: object
    sources: list
    reads: list
    source_basis: dict
    review: dict
    confirmation_id: object = None
    used: bool = False


def _cache_key(ctx, command):
    return ("project-work", digest(vars(ctx)), command_digest(command))


def _without_recorded(value):
    if isinstance(value, dict):
        return {key: _without_recorded(item) for key, item in value.items() if key != "recorded_at"}
    if isinstance(value, list):
        return [_without_recorded(item) for item in value]
    return value


def _sources(payload):
    refs = {ref: ref for ref in payload.sources}
    for result in getattr(payload, "results", ()):
        for ref in result.sources:
            refs[ref] = ref
    return sorted(refs.values(), key=lambda ref: (str(ref.id), ref.revision, ref.position))


def _merge_basis(*groups):
    values = {}
    for group in groups:
        for value in group.get("artifacts", []):
            old = values.get(value["id"])
            rules.require(old is None or old == value, "固定原件存在不一致版本。", "SOURCE_STALE")
            values[value["id"]] = deepcopy(value)
    return {"artifacts": [values[key] for key in sorted(values)]}


def validate(s, ctx, command, product, payload):
    key = _cache_key(ctx, command)
    cached = s.info.get(key)
    if cached is not None and cached.transaction is s.get_transaction() and not cached.used:
        return cached
    rules.require(
        command.expected_revision == product.revision, "型号范围版本已变化。", "VERSION_CONFLICT"
    )
    project = owner.project(s, ctx, product.id, payload.project_id, lock=True)
    if command.operation != CREATE:
        human(s, ctx)
    elif not ctx.agent_run_id:
        human(s, ctx)
    if getattr(payload, "calendar_id", None) is not None:
        rules.require(
            False,
            "实际日历 owner 尚未接通；不能把任意 ID 当作已核对日历。",
            "INTEGRATION_REQUIRED",
            503,
        )
    previous, pointer, task_row, task_snapshot = None, None, None, None
    if hasattr(payload, "task"):
        task_row, task_snapshot, pointer = owner.task(
            s,
            ctx,
            product.id,
            payload.task.id,
            revision=payload.task.revision,
            lock=True,
        )
        rules.require(
            task_row.project_id == project.id, "任务不属于当前项目。", "FORBIDDEN_SCOPE", 403
        )
        owner.sources_current(s, ctx, product.id, task_row.source_basis)
    if command.operation == CREATE and payload.plan_task is not None:
        fixed = s.scalar(
            select(ProjectTask).where(
                ProjectTask.tenant_id == ctx.tenant_id,
                ProjectTask.product_id == product.id,
                ProjectTask.project_id == project.id,
                ProjectTask.id == payload.plan_task.id,
            )
        )
        plan = s.get(PlanRevision, fixed.plan_id) if fixed else None
        rules.require(
            plan is not None and plan.revision == payload.plan_task.revision,
            "计划任务须固定实际计划版本。",
            "VERSION_CONFLICT",
        )
    if command.operation == ASSIGN:
        rules.require(
            ctx.requester_id == project.owner_id,
            "责任分派由本项目负责人确认。",
            "FORBIDDEN_SCOPE",
            403,
        )
        for identity in {payload.assignee_id, payload.recipient_id}:
            grant = member(s, ctx, identity)
            rules.require(grant.can_write, "办理人须有当前品类写入权限。", "FORBIDDEN_SCOPE", 403)
    refs = _sources(payload)
    native_basis = None
    if command.operation == CREATE and payload.g0_open_item is not None:
        native_basis = g0_sources.resolve(
            s, ctx, product.id, project.id, payload.g0_open_item, lock=True
        )
        existing = s.scalar(
            select(WorkTaskVersion.task_id).where(
                WorkTaskVersion.tenant_id == ctx.tenant_id,
                WorkTaskVersion.g0_open_item_id == payload.g0_open_item.id,
                WorkTaskVersion.revision == 1,
            )
        )
        rules.require(
            existing is None,
            "原 G0 事项已有执行任务，请继续办理该任务。",
            "VERSION_CONFLICT",
        )
    elif command.operation in TASK_OPERATIONS and task_row is not None:
        native_basis = task_row.source_basis.get("g0_open_item")
    rules.require(
        bool(refs) or native_basis is not None,
        "须有实际原件或本次任务的固定 G0 事项来源。",
        "MISSING_REQUIRED_EVIDENCE",
        422,
    )
    basis, private = direct_source_basis(s, ctx, product, refs, command.source_read_set)
    rules.require(
        not private or project.visibility == "private",
        "私有原件不能随任务或周报扩大到共享项目。",
        "FORBIDDEN_SCOPE",
        403,
    )
    source_basis = {"artifacts": basis}
    if task_row is not None:
        source_basis = _merge_basis(task_row.source_basis, source_basis)
    if native_basis is not None:
        source_basis["g0_open_item"] = deepcopy(native_basis)
    at = now()
    if command.operation in TASK_OPERATIONS:
        previous = task_row
        plan = rules.transition(
            command.operation,
            payload,
            current=task_snapshot,
            actor_id=ctx.requester_id,
            at=at,
            task_id=uuid4(),
        )
    elif command.operation == COMMIT:
        grant = member(s, ctx, payload.recipient_id)
        rules.require(
            grant.can_write, "承诺接收者须为当前可办理的品类成员。", "FORBIDDEN_SCOPE", 403
        )
        previous, old, pointer = owner.commitment(
            s, ctx, product.id, payload.task.id, ctx.requester_id, payload.recipient_id, lock=True
        )
        rules.require(
            (previous is None and payload.replaces is None)
            or (
                previous is not None
                and payload.replaces == VersionRef(id=previous.id, revision=previous.revision)
            ),
            "必须精确替代同接收者的当前承诺。",
            "VERSION_CONFLICT",
        )
        if previous is not None:
            owner.sources_current(s, ctx, product.id, previous.source_basis)
            source_basis = _merge_basis(previous.source_basis, source_basis)
        plan = rules.commitment_plan(
            payload, task=task_snapshot, actor_id=ctx.requester_id, previous=old, at=at
        )
    else:
        rules.require(
            command.operation == STATUS and ctx.requester_id == project.owner_id,
            "具名项目状态更新由本项目负责人发布。",
            "FORBIDDEN_SCOPE",
            403,
        )
        snapshots = []
        for ref in payload.task_refs:
            row, snapshot, _ = owner.task(
                s, ctx, product.id, ref.id, revision=ref.revision, fixed=True
            )
            rules.require(
                row.project_id == project.id, "周报不能引用其他项目任务。", "FORBIDDEN_SCOPE", 403
            )
            owner.sources_current(s, ctx, product.id, row.source_basis)
            source_basis = _merge_basis(source_basis, row.source_basis)
            snapshots.append(snapshot)
        plan = rules.status_plan(payload, tasks=tuple(snapshots), actor_id=ctx.requester_id, at=at)
    review = {
        "operation": command.operation,
        "project": {
            "id": str(project.id),
            "revision": project.revision,
            "name": project.name,
            "owner_id": str(project.owner_id),
            "visibility": project.visibility,
        },
        "declaration": semantic(payload),
        "before": task_snapshot.model_dump(mode="json") if task_snapshot else None,
        "after": _without_recorded(plan.model_dump(mode="json")),
        "sources": [ref.model_dump(mode="json") for ref in refs],
        "source_basis": source_basis,
        "effect": (
            "责任承接、对接收者的承诺、成果提交和验收分别保存；"
            "周报仅追加引用，不改四时间或业务状态。"
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
        task_row,
        review["sources"],
        [item.model_dump(mode="json") for item in command.source_read_set],
        source_basis,
        review,
    )
    s.info[key] = value
    return value


def confirmation_subject(s, ctx, command, product, payload):
    # The saved review also fixes the exact task/commitment version and material.
    return "product", product


def preview_view(s, ctx, command, product, payload):
    return validate(s, ctx, command, product, payload).review


def inputs(s, ctx, pid, command):
    from pdos_next.service import command_scope

    rules.require(
        command.product_id == pid and command.category_id == ctx.category_id,
        "材料命令与当前范围不一致。",
        "FORBIDDEN_SCOPE",
        403,
    )
    rules.require(
        command.operation in PAYLOADS, "此入口只接受已登记项目工作操作。", "FORBIDDEN_SCOPE", 403
    )
    payload = PAYLOADS[command.operation].model_validate(command.payload)
    refs = _sources(payload)
    from pdos_next.domain.quality_execution.evidence import merge_reads

    reads = merge_reads(
        [{"artifact_id": str(ref.id), "expected_revision": ref.revision} for ref in refs]
    )
    prepared = command.model_copy(update={"source_read_set": []})
    from pdos_next.contracts import Command

    prepared = Command.model_validate(
        {**prepared.model_dump(mode="json"), "source_read_set": reads}
    )
    product = command_scope(s, ctx, prepared, lock=True)
    value = validate(s, ctx, prepared, product, payload)
    return {"payload": semantic(payload), "required_source_read_set": reads, "review": value.review}


def _common(ctx, command, project, value):
    body = value.plan.model_dump(mode="json")
    envelope = command.model_dump(mode="json", exclude={"idempotency_key"})
    envelope["payload"] = semantic(PAYLOADS[command.operation].model_validate(command.payload))
    return dict(
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        product_id=command.product_id,
        project_id=project.id,
        owner_id=project.owner_id,
        visibility=project.visibility,
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
        body=body,
        body_sha256=digest(body),
        source_basis=value.source_basis,
        sources=value.sources,
        reads=value.reads,
        receipt_id=uuid4(),
        confirmation_id=value.confirmation_id,
        request_digest=command_digest(command),
        intent_digest=digest(
            {
                "operation": command.operation,
                "category": command.category_id,
                "product": command.product_id,
                "payload": envelope["payload"],
                "named_actor": ctx.requester_id,
                "source_revision": None,
                "private_owner": ctx.requester_id,
            }
        ),
    )


def apply_validated(s, ctx, command, product, payload, value):
    rules.require(
        value.session is s
        and value.transaction is s.get_transaction()
        and value.fingerprint == command_digest(command)
        and not value.used,
        "须使用本次实际事务核对过的材料。",
        "INTEGRITY_MISMATCH",
    )
    value.used = True
    data = _common(ctx, command, value.project, value)
    plan = value.plan
    if command.operation in TASK_OPERATIONS:
        previous = value.previous
        row = WorkTaskVersion(
            id=plan.task_id if previous is None else uuid4(),
            revision=plan.revision,
            task_id=plan.task_id,
            previous_id=previous.id if previous else None,
            previous_revision=previous.revision if previous else None,
            action=command.operation.rsplit(".", 1)[1],
            state=plan.state,
            g0_open_item_id=plan.g0_open_item.id if plan.g0_open_item else None,
            g0_decision_id=plan.g0_open_item.decision_id if plan.g0_open_item else None,
            **data,
        )
        s.add(row)
        s.flush([row])
        if value.pointer is None:
            s.add(
                WorkTaskCurrent(
                    tenant_id=row.tenant_id,
                    category_id=row.category_id,
                    product_id=product.id,
                    project_id=row.project_id,
                    owner_id=row.owner_id,
                    visibility=row.visibility,
                    task_id=row.task_id,
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
        kind = "work_task"
        row.action_result = {
            "task_id": str(row.task_id),
            "state": row.state,
            "project_id": str(row.project_id),
        }
    elif command.operation == COMMIT:
        identity = uuid4()
        previous = value.previous
        row = WorkCommitmentVersion(
            id=identity,
            revision=plan.revision,
            series_id=previous.series_id if previous else identity,
            replaces_id=previous.id if previous else None,
            replaces_revision=previous.revision if previous else None,
            task_id=plan.task_id,
            task_revision=plan.task_revision,
            promisor_id=plan.promisor_id,
            recipient_id=plan.recipient_id,
            outcome_keys=list(plan.outcome_keys),
            promised_at=plan.promised_at,
            original_timezone=plan.original_timezone,
            calendar_id=plan.calendar_id,
            **data,
        )
        s.add(row)
        s.flush([row])
        if value.pointer is None:
            s.add(
                WorkCommitmentCurrent(
                    tenant_id=row.tenant_id,
                    category_id=row.category_id,
                    product_id=product.id,
                    project_id=row.project_id,
                    owner_id=row.owner_id,
                    visibility=row.visibility,
                    task_id=row.task_id,
                    promisor_id=row.promisor_id,
                    recipient_id=row.recipient_id,
                    series_id=row.series_id,
                    version_id=row.id,
                    revision=row.revision,
                )
            )
        else:
            value.pointer.version_id, value.pointer.revision = row.id, row.revision
        kind = "work_commitment"
        row.action_result = {"task_id": str(row.task_id), "recipient_id": str(row.recipient_id)}
    else:
        row = ProjectStatusUpdate(
            id=uuid4(),
            revision=1,
            fact_summary=plan.fact_summary,
            next_steps=plan.next_steps,
            task_refs=[ref.model_dump(mode="json") for ref in plan.task_refs],
            **data,
        )
        s.add(row)
        kind = "project_status_update"
        row.action_result = {"project_id": str(row.project_id)}
    row.prepared_receipt_id = row.receipt_id
    row._work_phase = value
    return row, kind, row.visibility


def finalize_receipt(s, ctx, command, product, payload, subject, receipt):
    value = getattr(subject, "_work_phase", None)
    rules.require(
        value is not None
        and value.used
        and value.session is s
        and value.transaction is s.get_transaction()
        and subject.receipt_id == receipt.id
        and subject.body_sha256 == digest(subject.body),
        "工作记录缺原事务的共同回执绑定。",
        "INTEGRITY_MISMATCH",
    )
    owner.sources_current(s, ctx, product.id, value.source_basis)
    del subject._work_phase


def workspace(s, ctx, pid, project_id):
    from .views import workspace as read_workspace

    return read_workspace(s, ctx, pid, project_id)
