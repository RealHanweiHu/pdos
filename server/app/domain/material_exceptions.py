"""Human-confirmed material exceptions linked to one actual Issue and immutable reviews."""

from decimal import Decimal, localcontext
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.build_materials import BuildMaterialService
from app.domain.issues import IssueDraft, IssueService
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.knowledge_push import KnowledgeAccessError
from app.domain.material_allocations import MaterialAllocationError, MaterialAllocationService
from app.domain.material_coverage import CoverageSelection, MaterialCoverageService
from app.domain.material_supply_pools import lock_pools
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import _plain, digest


class ExceptionCreate(Contract):
    request_id: UUID
    material_key: Digest
    expected_digest: Digest
    selection: CoverageSelection
    title: str = Field(min_length=1, max_length=512)
    severity: Literal["low", "medium", "high", "critical"]
    reason: Text


class ExceptionReview(Contract):
    request_id: UUID
    expected_version: int = Field(ge=1)
    expected_digest: Digest
    selection: CoverageSelection
    disposition: Literal["follow_up", "supply_ready", "scope_changed"]
    reason: Text


def quantity_text(value: Any) -> str:
    """Readable quantity for generated prose: "2.000000" -> "2", "0E-8" -> "0"."""
    if value is None:
        return "未知"
    amount = Decimal(str(value))
    return "0" if amount == 0 else format(amount.normalize(), "f")


def _authorize(
    c: Connection, context: AuthContext, project_id: UUID, *, write: bool = False
) -> None:
    BuildMaterialService._authorize(c, context, project_id, write=write)
    KnowledgeCorrectionService._authorize(
        c,
        context.tenant.id,
        context.user.id,
        project_id,
        Action.WORK_ITEM_EDIT if write else Action.WORK_ITEM_VIEW,
    )


def _editable(c: Connection, context: AuthContext, project_id: UUID) -> bool:
    try:
        _authorize(c, context, project_id, write=True)
        return True
    except KnowledgeAccessError:
        return False


def _row(c: Connection, tenant_id: UUID, project_id: UUID, exception_id: UUID) -> dict[str, Any]:
    t = tables.material_exceptions
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == tenant_id, t.c.project_id == project_id, t.c.id == exception_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise MaterialAllocationError("本项目中没有该物料异常")
    return dict(row)


def _review(c: Connection, tenant_id: UUID, exception_id: UUID) -> dict[str, Any]:
    t = tables.material_exception_reviews
    return dict(
        c.execute(
            select(t)
            .where(t.c.tenant_id == tenant_id, t.c.exception_id == exception_id)
            .order_by(t.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one()
    )


def _assessment(coverage: dict[str, Any], material_key: str) -> dict[str, Any]:
    material = next(
        (row for row in coverage["materials"] if row["material_key"] == material_key), None
    )
    pools = [
        pool
        for pool in coverage["pools"]
        if material
        and (
            (pool["source"] and pool["source"]["id"] in material["pool_ids"])
            or (not pool["source"] and pool["pool_key"][2] == material["material_reference"])
        )
    ]
    keys = {line["bom_item_id"] for line in material["lines"]} if material else set()
    basis = {
        key: coverage[key]
        for key in (
            "policy",
            "selection",
            "revision_id",
            "revision_digest",
            "build",
            "schedule",
            "need_date",
            "need_date_passed",
            "pool_limit_reached",
        )
    }
    basis.update(
        material_key=material_key,
        material=material,
        pools=pools,
        allocations=[
            row
            for row in coverage["allocations"]
            if row["bom_item_id"] in keys and row["revision_id"] == coverage["revision_id"]
        ],
    )
    return {"basis": basis, "digest": digest(basis), "as_of": coverage["as_of"]}


def _lock_sources(c: Connection, context: AuthContext, project_id: UUID, build_id: UUID) -> None:
    current = MaterialAllocationService.read(c, context, project_id, build_id)
    lock_pools(c, context.tenant.id, [tuple(pool["pool_key"]) for pool in current["pools"]])


def _save_review(
    c: Connection,
    context: AuthContext,
    row: dict[str, Any],
    command: ExceptionCreate | ExceptionReview,
    assessment: dict[str, Any],
    signature: str,
    version: int,
) -> dict[str, Any]:
    disposition = command.disposition if isinstance(command, ExceptionReview) else "follow_up"
    material = assessment["basis"]["material"]
    if disposition == "supply_ready" and (
        material is None
        or (Decimal(material["allocated_on_hand"]) + Decimal(material.get("qualified_issued", "0")))
        < Decimal(material["required"])
    ):
        raise MaterialAllocationError(
            "当前固定需求尚未被合格现货分配及领用时合格的有据净领料完整覆盖，不能记录供给已齐备"
        )
    if disposition == "scope_changed" and material is not None:
        raise MaterialAllocationError(
            "该物料仍在当前固定需求中，请保留跟进；需求移除须先完成正式修订"
        )
    if disposition == "follow_up" and material is None:
        raise MaterialAllocationError("该物料已不在当前固定需求中，请核对范围变化并继续原问题办理")
    if assessment["basis"]["revision_id"] is None:
        raise MaterialAllocationError("当前批次没有可固定的需求版本")
    t = tables.material_exception_reviews
    saved = (
        c.execute(
            t.insert()
            .values(
                id=uuid4(),
                tenant_id=context.tenant.id,
                project_id=row["project_id"],
                exception_id=row["id"],
                version=version,
                revision_id=UUID(assessment["basis"]["revision_id"]),
                created_by_user_id=context.user.id,
                request_id=command.request_id,
                request_digest=signature,
                basis_digest=assessment["digest"],
                disposition=disposition,
                reason=command.reason,
                snapshot=assessment,
            )
            .returning(t)
        )
        .mappings()
        .one()
    )
    NpiExecutionService._record_change(
        c,
        tenant_id=context.tenant.id,
        project_id=row["project_id"],
        actor_user_id=context.user.id,
        record_id=row["id"],
        record_type="material_exception",
        action="confirmed" if version == 1 else "reviewed",
        before=None,
        after={
            "exception_id": str(row["id"]),
            "issue_id": str(row["issue_id"]),
            "review": _plain(dict(saved)),
        },
    )
    return _plain(dict(saved))


class MaterialExceptionService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def list(
        self,
        context: AuthContext,
        project_id: UUID,
        *,
        build_id: UUID | None = None,
        issue_id: UUID | None = None,
        material_key: str | None = None,
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            _authorize(c, context, project_id)
            t, i = tables.material_exceptions, tables.issues
            query = (
                select(t, i.c.title.label("issue_title"), i.c.status.label("issue_status"))
                .join(i, (i.c.tenant_id == t.c.tenant_id) & (i.c.id == t.c.issue_id))
                .where(t.c.tenant_id == context.tenant.id, t.c.project_id == project_id)
            )
            if build_id:
                query = query.where(t.c.build_id == build_id)
            if issue_id:
                query = query.where(t.c.issue_id == issue_id)
            if material_key:
                query = query.where(t.c.material_key == material_key)
            rows = list(
                c.execute(query.order_by(t.c.created_at.desc(), t.c.id).limit(201)).mappings()
            )
            return {
                "items": [_plain(dict(row)) for row in rows[:200]],
                "has_more": len(rows) > 200,
                "can_edit": _editable(c, context, project_id),
            }

    def get(
        self,
        context: AuthContext,
        project_id: UUID,
        exception_id: UUID,
        *,
        version: int | None = None,
        selection: CoverageSelection | None = None,
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
            localcontext() as arithmetic,
        ):
            arithmetic.prec = 2048
            _authorize(c, context, project_id)
            row = _row(c, context.tenant.id, project_id, exception_id)
            latest = _review(c, context.tenant.id, exception_id)
            t = tables.material_exception_reviews
            history = [
                _plain(dict(item))
                for item in c.execute(
                    select(t)
                    .where(t.c.tenant_id == context.tenant.id, t.c.exception_id == exception_id)
                    .order_by(t.c.version.desc())
                    .limit(20)
                ).mappings()
            ]
            selected = None
            if version is not None:
                selected_row = (
                    c.execute(
                        select(t).where(
                            t.c.tenant_id == context.tenant.id,
                            t.c.exception_id == exception_id,
                            t.c.version == version,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if selected_row is None:
                    raise MaterialAllocationError("所选历史核对版本不存在")
                selected = _plain(dict(selected_row))
            coverage = MaterialCoverageService.read(
                c,
                context,
                project_id,
                row["build_id"],
                selection
                or CoverageSelection.model_validate(latest["snapshot"]["basis"]["selection"]),
            )
            current = _assessment(coverage, row["material_key"])
            issue = (
                c.execute(
                    select(
                        tables.issues.c.id,
                        tables.issues.c.title,
                        tables.issues.c.status,
                        tables.issues.c.owner_user_id,
                        tables.issues.c.target_date,
                        tables.issues.c.updated_at,
                    ).where(
                        tables.issues.c.tenant_id == context.tenant.id,
                        tables.issues.c.project_id == project_id,
                        tables.issues.c.id == row["issue_id"],
                    )
                )
                .mappings()
                .one()
            )
            return {
                "exception": _plain(row),
                "issue": _plain(dict(issue)),
                "latest": _plain(latest),
                "history": history,
                "selected": selected,
                "current": current,
                "needs_recheck": current["digest"] != latest["basis_digest"],
                "can_edit": _editable(c, context, project_id),
            }

    def create(
        self, context: AuthContext, project_id: UUID, build_id: UUID, command: ExceptionCreate
    ) -> dict[str, Any]:
        signature = digest(
            {
                "project_id": str(project_id),
                "build_id": str(build_id),
                "create": command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as c, localcontext() as arithmetic:
            arithmetic.prec = 2048
            NpiExecutionService._project(
                c, tenant_id=context.tenant.id, project_id=project_id, lock=True
            )
            _authorize(c, context, project_id, write=True)
            t = tables.material_exceptions
            prior = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.created_by_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != signature:
                    raise MaterialAllocationError("该请求已用于不同内容，请核对原异常")
                return _plain(dict(prior))
            if c.execute(
                select(t.c.id).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.build_id == build_id,
                    t.c.material_key == command.material_key,
                )
            ).first():
                raise MaterialAllocationError(
                    "本批次该物料已有异常，请打开原异常继续核对；不重复创建问题"
                )
            _lock_sources(c, context, project_id, build_id)
            coverage = MaterialCoverageService.read(
                c, context, project_id, build_id, command.selection
            )
            if coverage["digest"] != command.expected_digest:
                raise MaterialAllocationError("需求、供给或日期依据已变化，请重新计算后核对")
            assessment = _assessment(coverage, command.material_key)
            material = assessment["basis"]["material"]
            if material is None:
                raise MaterialAllocationError("当前固定需求中没有所选物料")
            identity = uuid4()
            gap = material["observed_on_hand_gap"]
            notes = (
                f"{command.reason}\n\n物料异常：{identity}\n批次：{coverage['build']['code']}"
                f"\n固定需求版本：{coverage['revision_id']}"
                f"\n物料：{material['material_reference'] or '引用待补'}；"
                f"需求 {quantity_text(material['required'])} {material['unit']}"
                f"\n已登记范围现货缺口：{quantity_text(gap)}"
                "\n具名核对与供给出处可从本问题的物料异常来源入口回查。"
                "供给恢复不自动关闭问题。"
            )
            issue = IssueService(self.engine).create(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
                connection=c,
                draft=IssueDraft(
                    stage_id=None,
                    owner_user_id=None,
                    verifier_user_id=None,
                    sample_id=None,
                    title=command.title,
                    description=notes,
                    issue_type="supplier",
                    severity=command.severity,
                    root_cause=None,
                    resolution=None,
                    closure_criteria=None,
                    target_date=None,
                ),
            )
            row = dict(
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        build_id=build_id,
                        material_key=command.material_key,
                        material_reference=material["material_reference"],
                        unit=material["unit"],
                        issue_id=issue.id,
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=signature,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            _save_review(c, context, row, command, assessment, signature, 1)
            return _plain(row)

    def review(
        self, context: AuthContext, project_id: UUID, exception_id: UUID, command: ExceptionReview
    ) -> dict[str, Any]:
        signature = digest(
            {
                "project_id": str(project_id),
                "exception_id": str(exception_id),
                "review": command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as c, localcontext() as arithmetic:
            arithmetic.prec = 2048
            NpiExecutionService._project(
                c, tenant_id=context.tenant.id, project_id=project_id, lock=True
            )
            _authorize(c, context, project_id, write=True)
            row = _row(c, context.tenant.id, project_id, exception_id)
            t = tables.material_exception_reviews
            prior = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.created_by_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != signature:
                    raise MaterialAllocationError("该核对请求已用于不同内容")
                return _plain(dict(prior))
            latest = _review(c, context.tenant.id, exception_id)
            if latest["version"] != command.expected_version:
                raise MaterialAllocationError("原异常已有新的具名核对，请刷新")
            _lock_sources(c, context, project_id, row["build_id"])
            coverage = MaterialCoverageService.read(
                c, context, project_id, row["build_id"], command.selection
            )
            assessment = _assessment(coverage, row["material_key"])
            if assessment["digest"] != command.expected_digest:
                raise MaterialAllocationError("原需求或供给已变化，请刷新原异常后重新核对")
            return _save_review(
                c, context, row, command, assessment, signature, latest["version"] + 1
            )
