"""Versioned human test work packages linked to actual tasks and run records."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, delete, select

from app.auth.project_access import ProjectAccessService, SqlProjectAccessRepository
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.npi_execution import NpiExecutionService, _snapshot
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.tasks import TaskDraft, TaskService, TaskUpdate
from app.domain.test_verification_paths import VerificationPathError, _authorize, _state


class ResourceNeed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_id: UUID
    parallel_units: float = Field(gt=0, le=1000)
    basis: str = Field(min_length=1, max_length=2000)


class PreparationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    assignee_user_id: UUID
    start_date: date | None = None
    due_date: date
    required_sample_count: int = Field(gt=0, le=100000)
    sample_ids: list[UUID] = Field(default_factory=list, max_length=500)
    conditions: str = Field(min_length=1, max_length=10000)
    environment: str = Field(min_length=1, max_length=2000)
    expected_output: str = Field(min_length=1, max_length=10000)
    resource_needs: list[ResourceNeed] = Field(default_factory=list, max_length=100)
    resource_notes: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=2000)
    proposal_resolution_notes: str | None = Field(default=None, max_length=4000)


def latest(
    c: Connection, tenant_id: UUID, project_id: UUID, case_id: UUID
) -> dict[str, Any] | None:
    t = tables.test_execution_preparations
    row = (
        c.execute(
            select(t)
            .where(
                t.c.tenant_id == tenant_id,
                t.c.project_id == project_id,
                t.c.test_case_id == case_id,
            )
            .order_by(t.c.revision_number.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


def task_package(
    c: Connection, tenant_id: UUID, project_id: UUID, task_id: UUID
) -> dict[str, Any] | None:
    p = tables.test_execution_preparations
    row = (
        c.execute(
            select(p)
            .where(p.c.tenant_id == tenant_id, p.c.project_id == project_id, p.c.task_id == task_id)
            .order_by(p.c.revision_number.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return _plain(dict(row))


def _basis(c: Connection, tenant_id: UUID, project_id: UUID, case_id: UUID) -> dict[str, Any]:
    state = _state(c, tenant_id, project_id, case_id)
    preparation = latest(c, tenant_id, project_id, case_id)
    task = (
        c.execute(
            select(tables.tasks).where(
                tables.tasks.c.tenant_id == tenant_id,
                tables.tasks.c.project_id == project_id,
                tables.tasks.c.id == preparation["task_id"],
            )
        )
        .mappings()
        .one()
        if preparation
        else None
    )
    samples = list(
        c.execute(
            select(tables.test_case_samples.c.sample_id)
            .where(
                tables.test_case_samples.c.tenant_id == tenant_id,
                tables.test_case_samples.c.project_id == project_id,
                tables.test_case_samples.c.test_case_id == case_id,
            )
            .order_by(tables.test_case_samples.c.sample_id)
        ).scalars()
    )
    return _plain(
        dict(
            state=state,
            preparation=preparation,
            task=dict(task) if task else None,
            sample_ids=samples,
        )
    )


def preparation_proposal(state: dict[str, Any]) -> dict[str, Any] | None:
    plan, case = state["plan"], state["case"]
    item = next(
        (
            item
            for item in (plan.get("template_snapshot") or {}).get("items", [])
            if item["key"] == case.get("template_item_key")
        ),
        None,
    )
    if item is None:
        return None
    proposal = item.get("execution_preparation")
    if not proposal:
        return None
    from app.domain.test_plan_changes import ExecutionPreparationProposal

    value = ExecutionPreparationProposal.model_validate(proposal).model_dump(mode="json")
    return {
        **value,
        "source_finding_id": item.get("source_finding_id"),
        "source_plan_id": plan["id"],
        "template_item_key": case["template_item_key"],
        "plan_reviewed_by_user_id": (plan.get("template_snapshot") or {}).get(
            "reviewed_by_user_id"
        ),
        "plan_applied_by_user_id": (plan.get("template_snapshot") or {}).get(
            "confirmed_by_user_id"
        ),
    }


def read(
    engine: Engine, *, context: AuthContext, project_id: UUID, case_id: UUID
) -> dict[str, Any]:
    _authorize(engine, context, project_id, edit=False)
    with engine.connect() as c:
        tenant_id = context.tenant.id
        basis = _basis(c, tenant_id, project_id, case_id)
        members = (
            c.execute(
                select(tables.users.c.id, tables.users.c.display_name)
                .join(
                    tables.project_members,
                    (tables.project_members.c.tenant_id == tables.users.c.tenant_id)
                    & (tables.project_members.c.user_id == tables.users.c.id),
                )
                .where(
                    tables.users.c.tenant_id == tenant_id,
                    tables.project_members.c.project_id == project_id,
                    tables.users.c.is_active.is_(True),
                )
                .order_by(tables.users.c.display_name)
            )
            .mappings()
            .all()
        )
        samples = (
            c.execute(
                select(tables.samples, tables.build_batches.c.code.label("build_code"))
                .join(
                    tables.build_batches,
                    (tables.build_batches.c.tenant_id == tables.samples.c.tenant_id)
                    & (tables.build_batches.c.id == tables.samples.c.build_batch_id),
                )
                .where(
                    tables.samples.c.tenant_id == tenant_id,
                    tables.samples.c.project_id == project_id,
                    tables.build_batches.c.phase == basis["state"]["plan"]["phase"],
                )
                .order_by(tables.samples.c.serial_number)
            )
            .mappings()
            .all()
        )
        resources = (
            c.execute(
                select(tables.planning_resources)
                .where(tables.planning_resources.c.tenant_id == tenant_id)
                .order_by(tables.planning_resources.c.name)
            )
            .mappings()
            .all()
        )
        reservations = []
        if basis["task"]:
            reservations = [
                dict(r)
                for r in c.execute(
                    select(tables.resource_reservations)
                    .join(
                        tables.schedule_nodes,
                        (
                            tables.schedule_nodes.c.tenant_id
                            == tables.resource_reservations.c.tenant_id
                        )
                        & (tables.schedule_nodes.c.id == tables.resource_reservations.c.node_id),
                    )
                    .where(
                        tables.resource_reservations.c.tenant_id == tenant_id,
                        tables.resource_reservations.c.project_id == project_id,
                        tables.schedule_nodes.c.task_id == UUID(basis["task"]["id"]),
                    )
                    .order_by(tables.resource_reservations.c.created_at)
                ).mappings()
            ]
        run_rows = (
            c.execute(
                select(tables.test_runs).where(
                    tables.test_runs.c.tenant_id == tenant_id,
                    tables.test_runs.c.project_id == project_id,
                    tables.test_runs.c.test_case_id == case_id,
                )
            )
            .mappings()
            .all()
        )
        active_id = basis["preparation"]["id"] if basis["preparation"] else None
        bound_runs = [
            dict(r) for r in run_rows if active_id and str(r["test_preparation_id"]) == active_id
        ]
        passed_samples = {
            str(r["sample_id"])
            for r in bound_runs
            if r["sample_id"] is not None
            and r["draft_state"] == "confirmed"
            and r["status"] == "passed"
            and r["evidence_document_id"] is not None
        }
        execution = {
            "runs": bound_runs,
            "passed_sample_count": len(passed_samples),
            "unbound_run_count": sum(r["test_preparation_id"] is None for r in run_rows),
        }
        p = tables.test_execution_preparations
        history = (
            c.execute(
                select(p)
                .where(
                    p.c.tenant_id == tenant_id,
                    p.c.project_id == project_id,
                    p.c.test_case_id == case_id,
                )
                .order_by(p.c.revision_number.desc())
                .limit(25)
            )
            .mappings()
            .all()
        )
    return {
        **basis,
        "reviewed_proposal": preparation_proposal(basis["state"]),
        "digest": digest(basis),
        **_plain(
            dict(
                members=[dict(r) for r in members],
                samples=[dict(r) for r in samples],
                resources=[dict(r) for r in resources],
                reservations=reservations,
                history=[dict(r) for r in history],
                execution=execution,
            )
        ),
    }


def save(
    engine: Engine,
    *,
    context: AuthContext,
    project_id: UUID,
    case_id: UUID,
    draft: PreparationDraft,
) -> dict[str, Any]:
    _authorize(engine, context, project_id, edit=True)
    ProjectAccessService(SqlProjectAccessRepository(engine)).authorize(
        context=context, project_id=project_id, action=Action.WORK_ITEM_EDIT
    )
    if len(set(draft.sample_ids)) != len(draft.sample_ids) or len(
        {r.resource_id for r in draft.resource_needs}
    ) != len(draft.resource_needs):
        raise VerificationPathError("样机或资源重复，请合并后保存")
    if draft.start_date and draft.start_date > draft.due_date:
        raise VerificationPathError("计划结束日期不能早于开始日期")
    request_digest = digest(
        {"project_id": str(project_id), "case_id": str(case_id), **draft.model_dump(mode="json")}
    )
    t = tables.test_execution_preparations
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project_id):
            raise VerificationPathError("项目不可用")
        _authorize(engine, context, project_id, edit=True)
        previous = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.created_by_user_id == context.user.id,
                    t.c.request_id == draft.request_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if previous is not None:
            if previous["request_digest"] != request_digest:
                raise VerificationPathError("同一提交请求不能改为不同工作包，请刷新后重新提交")
        else:
            basis = _basis(c, context.tenant.id, project_id, case_id)
            if not basis["state"]["can_edit"] or (
                basis["task"] and basis["task"]["status"] in {"done", "skipped"}
            ):
                raise VerificationPathError(
                    "测试或工作任务已开始留存结果，请在新的测试计划修订中准备"
                )
            if digest(basis) != draft.expected_digest:
                raise VerificationPathError("工作包来源或任务已变化，请刷新后核对")
            case, plan = basis["state"]["case"], basis["state"]["plan"]
            proposal = preparation_proposal(basis["state"])
            if (
                proposal
                and proposal["unresolved"]
                and not (draft.proposal_resolution_notes or "").strip()
            ):
                raise VerificationPathError("请说明原执行准备待补条件如何解决，再保存可执行工作包")

            if (
                not (case["method"] or "").strip()
                or not (case["acceptance_criteria"] or "").strip()
            ):
                raise VerificationPathError("请先补齐专业测试方法与判据")
            samples = (
                c.execute(
                    select(tables.samples.c.id)
                    .join(
                        tables.build_batches,
                        (tables.build_batches.c.tenant_id == tables.samples.c.tenant_id)
                        & (tables.build_batches.c.id == tables.samples.c.build_batch_id),
                    )
                    .where(
                        tables.samples.c.tenant_id == context.tenant.id,
                        tables.samples.c.project_id == project_id,
                        tables.samples.c.id.in_(draft.sample_ids),
                        tables.build_batches.c.phase == plan["phase"],
                        tables.samples.c.status != "scrapped",
                    )
                )
                .scalars()
                .all()
            )
            if set(samples) != set(draft.sample_ids):
                raise VerificationPathError("请选择同项目、同阶段且未报废的实际样机")
            member = c.execute(
                select(tables.users.c.id)
                .join(
                    tables.project_members,
                    (tables.project_members.c.tenant_id == tables.users.c.tenant_id)
                    & (tables.project_members.c.user_id == tables.users.c.id),
                )
                .where(
                    tables.users.c.tenant_id == context.tenant.id,
                    tables.users.c.id == draft.assignee_user_id,
                    tables.users.c.is_active.is_(True),
                    tables.project_members.c.project_id == project_id,
                )
            ).first()
            if member is None:
                raise VerificationPathError("请选择当前有效项目成员负责此工作包")
            resource_rows = (
                c.execute(
                    select(tables.planning_resources).where(
                        tables.planning_resources.c.tenant_id == context.tenant.id,
                        tables.planning_resources.c.id.in_(
                            [r.resource_id for r in draft.resource_needs]
                        ),
                    )
                )
                .mappings()
                .all()
            )
            if len(resource_rows) != len(draft.resource_needs):
                raise VerificationPathError("所选资源已不可用，请刷新资源目录")
            fields: dict[str, Any] = dict(
                stage_id=UUID(plan["stage_id"]),
                assignee_user_id=draft.assignee_user_id,
                title=f"验证：{case['title']}"[:512],
                description=draft.conditions,
                start_date=draft.start_date,
                due_date=draft.due_date,
                expected_output=draft.expected_output,
            )
            service = TaskService(engine)
            if basis["task"]:
                task = service.update(
                    tenant_id=context.tenant.id,
                    actor_user_id=context.user.id,
                    project_id=project_id,
                    task_id=UUID(basis["task"]["id"]),
                    patch=TaskUpdate(changes=fields),
                    connection=c,
                )
            else:
                task = service.create(
                    tenant_id=context.tenant.id,
                    actor_user_id=context.user.id,
                    project_id=project_id,
                    draft=TaskDraft(
                        **fields, parent_task_id=None, priority="medium", dependency_task_ids=()
                    ),
                    connection=c,
                )
            snapshot = {
                **draft.model_dump(mode="json", exclude={"request_id", "expected_digest"}),
                "case": case,
                "reviewed_proposal": preparation_proposal(basis["state"]),
                "plan": {
                    key: plan[key] for key in ("id", "title", "phase", "stage_id", "sample_size")
                },
                "resource_snapshots": [_plain(dict(r)) for r in resource_rows],
                "task_id": str(task.id),
            }
            version = basis["preparation"]["revision_number"] + 1 if basis["preparation"] else 1
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        test_case_id=case_id,
                        task_id=task.id,
                        revision_number=version,
                        request_id=draft.request_id,
                        request_digest=request_digest,
                        snapshot=snapshot,
                        created_by_user_id=context.user.id,
                        created_at=datetime.now(UTC),
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            c.execute(
                delete(tables.test_case_samples).where(
                    tables.test_case_samples.c.tenant_id == context.tenant.id,
                    tables.test_case_samples.c.project_id == project_id,
                    tables.test_case_samples.c.test_case_id == case_id,
                )
            )
            if samples:
                c.execute(
                    tables.test_case_samples.insert(),
                    [
                        dict(
                            tenant_id=context.tenant.id,
                            project_id=project_id,
                            test_case_id=case_id,
                            sample_id=id,
                        )
                        for id in samples
                    ],
                )
            NpiExecutionService._record_change(
                c,
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                record_id=row["id"],
                record_type="test_preparation",
                action="prepared",
                before=_snapshot(basis["preparation"]) if basis["preparation"] else None,
                after=_snapshot(dict(row)),
            )
    return read(engine, context=context, project_id=project_id, case_id=case_id)
