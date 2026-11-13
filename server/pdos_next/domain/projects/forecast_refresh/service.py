"""T0 deterministic forecast refresh through the common command transaction.

The refresh is a "系统重算" (P66): no model, no revert, not a 小Pai action. It
writes only a new forecast record and its project Current; plan revisions,
planned tasks, baselines and commitments are never touched (I08, P58).
"""

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select

from pdos_next.core.models import now
from pdos_next.core.service import command_digest, digest
from pdos_next.domain.categories.preproject.access import human
from pdos_next.domain.projects.models import Project
from pdos_next.domain.projects.work.rules import require

from . import inputs as engine_inputs
from .models import WorkForecastCurrent, WorkForecastRefresh
from .schemas import OPERATION, SUBJECT

category_lifecycle_fence = True


def semantic(payload):
    return payload.model_dump(mode="json")


@dataclass
class Validated:
    session: object
    transaction: object
    fingerprint: str
    project: object
    inputs: object
    result: dict
    previous: object
    pointer: object
    at: object
    used: bool = False


def _project(s, ctx, product_id, project_id):
    row = s.scalar(
        select(Project).where(
            Project.tenant_id == ctx.tenant_id,
            Project.product_id == product_id,
            Project.id == project_id,
        )
    )
    require(row is not None, "项目不在当前可用范围。", "FORBIDDEN_SCOPE", 403)
    return row


def _current(s, ctx, product_id, project_id, *, lock=False):
    query = select(WorkForecastCurrent).where(
        WorkForecastCurrent.tenant_id == ctx.tenant_id,
        WorkForecastCurrent.product_id == product_id,
        WorkForecastCurrent.project_id == project_id,
    )
    pointer = s.scalar(query.with_for_update() if lock else query)
    if pointer is None:
        return None, None
    row = s.scalar(
        select(WorkForecastRefresh).where(
            WorkForecastRefresh.tenant_id == ctx.tenant_id,
            WorkForecastRefresh.id == pointer.version_id,
        )
    )
    require(
        row is not None
        and row.revision == pointer.revision
        and row.result_sha256 == digest(row.result),
        "预测当前指针与固定记录不一致。",
        "INTEGRITY_MISMATCH",
    )
    return pointer, row


def validate(s, ctx, command, product, payload):
    key = ("forecast-refresh", digest(vars(ctx)), command_digest(command))
    cached = s.info.get(key)
    if cached is not None and cached.transaction is s.get_transaction() and not cached.used:
        return cached
    require(
        command.expected_revision == product.revision, "型号范围版本已变化。", "VERSION_CONFLICT"
    )
    if not ctx.agent_run_id and not ctx.run_id:
        human(s, ctx)
    require(not command.source_read_set, "预测重算不读取原件来源。", "VALIDATION_FAILED", 422)
    at = now()
    project = _project(s, ctx, product.id, payload.project_id)
    require(
        project.current_plan_id == payload.plan.id,
        "项目的当前计划已变化，请重新读取。",
        "VERSION_CONFLICT",
    )
    gathered = engine_inputs.gather(s, ctx, product.id, project, at=at)
    require(gathered.plan.revision == payload.plan.revision, "计划版本已变化。", "VERSION_CONFLICT")
    if gathered.input_sha256 != payload.expected_input_sha256:
        from pdos_next.errors import DomainError

        raise DomainError(
            "VERSION_CONFLICT",
            "预测输入已变化（任务实际、计划或日期），请重新读取后再重算。",
            detail={"current_input_sha256": gathered.input_sha256},
        )
    result = engine_inputs.compute(gathered)
    pointer, previous = _current(s, ctx, product.id, project.id, lock=True)
    value = Validated(
        s,
        s.get_transaction(),
        command_digest(command),
        project,
        gathered,
        result,
        previous,
        pointer,
        at,
    )
    s.info[key] = value
    return value


def apply_validated(s, ctx, command, product, payload, value):
    require(
        value.session is s
        and value.transaction is s.get_transaction()
        and value.fingerprint == command_digest(command)
        and not value.used,
        "须使用本事务实际计算的预测。",
        "INTEGRITY_MISMATCH",
    )
    value.used = True
    project, previous = value.project, value.previous
    common = {
        "tenant_id": ctx.tenant_id,
        "category_id": ctx.category_id,
        "product_id": product.id,
        "project_id": project.id,
        "owner_id": project.owner_id,
        "visibility": project.visibility,
    }
    row = WorkForecastRefresh(
        id=uuid4(),
        **common,
        revision=previous.revision + 1 if previous else 1,
        previous_id=previous.id if previous else None,
        previous_revision=previous.revision if previous else None,
        plan_id=value.inputs.plan.id,
        plan_revision=value.inputs.plan.revision,
        as_of=value.inputs.as_of,
        input_sha256=value.inputs.input_sha256,
        algorithm_version=value.result["algorithm_version"],
        status=value.result["status"],
        result=value.result,
        result_sha256=digest(value.result),
        writer_id=ctx.actor_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        operation=OPERATION,
        command_id=command.command_id,
        request_digest=command_digest(command),
        receipt_id=uuid4(),
        created_at=value.at,
    )
    s.add(row)
    s.flush([row])
    if value.pointer is None:
        s.add(WorkForecastCurrent(**common, version_id=row.id, revision=row.revision))
    else:
        value.pointer.version_id, value.pointer.revision = row.id, row.revision
    row.action_result = {
        "project_id": str(project.id),
        "plan_id": str(row.plan_id),
        "input_sha256": row.input_sha256,
        "forecast_status": row.status,
    }
    row.prepared_receipt_id = row.receipt_id
    row._forecast_phase = value
    return row, SUBJECT, row.visibility


def finalize_receipt(s, ctx, command, product, payload, subject, receipt):
    value = getattr(subject, "_forecast_phase", None)
    require(
        value is not None
        and value.used
        and value.session is s
        and value.transaction is s.get_transaction()
        and subject.receipt_id == receipt.id
        and subject.result_sha256 == digest(subject.result),
        "预测缺少本事务共同回执绑定。",
        "INTEGRITY_MISMATCH",
    )
    del subject._forecast_phase


def _record(row):
    return {
        "id": str(row.id),
        "revision": row.revision,
        "plan_id": str(row.plan_id),
        "plan_revision": row.plan_revision,
        "status": row.status,
        "input_sha256": row.input_sha256,
        "created_at": row.created_at.isoformat(),
        "writer_id": str(row.writer_id),
        "requester_id": str(row.requester_id),
        "receipt_id": str(row.receipt_id),
        "kind": "system_recompute",
        "result": row.result,
    }


def view(s, ctx, product_id, project_id):
    """Current refresh plus the live input digest needed for the next refresh."""
    from pdos_next.core.service import require_access

    require_access(s, ctx, product_id)
    project = _project(s, ctx, product_id, project_id)
    _, current = _current(s, ctx, product_id, project.id)
    inputs = None
    unavailable = None
    if project.current_plan_id is not None:
        gathered = engine_inputs.gather(s, ctx, product_id, project, at=now())
        inputs = {
            "plan": {"id": str(gathered.plan.id), "revision": gathered.plan.revision},
            "input_sha256": gathered.input_sha256,
            "as_of_day": gathered.as_of_day,
            "facts": gathered.facts,
            "changed": current is None or current.input_sha256 != gathered.input_sha256,
        }
    else:
        unavailable = "no_applied_plan"
    history = s.scalars(
        select(WorkForecastRefresh)
        .where(
            WorkForecastRefresh.tenant_id == ctx.tenant_id,
            WorkForecastRefresh.product_id == product_id,
            WorkForecastRefresh.project_id == project.id,
        )
        .order_by(WorkForecastRefresh.revision.desc())
        .limit(20)
    ).all()
    return {
        "project": {"id": str(project.id), "revision": project.revision},
        "current": _record(current) if current else None,
        "inputs": inputs,
        "unavailable": unavailable,
        "history": [
            {
                "id": str(row.id),
                "revision": row.revision,
                "status": row.status,
                "created_at": row.created_at.isoformat(),
                "project_finish": row.result.get("project_finish"),
                "kind": "system_recompute",
            }
            for row in history
        ],
    }
