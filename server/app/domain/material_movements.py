"""Evidence-bound material movements and explicit ERP balance reconciliation."""

from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import Connection, Engine, case, func, or_, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, Quantity, Text
from app.db.schema import tables
from app.domain.build_materials import BuildMaterialService
from app.domain.document_previews import document_row, metadata
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.material_supply_pools import lock_pools
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import _plain, digest


class MovementDraft(Contract):
    kind: Literal["issued", "consumed", "returned", "scrapped"]
    allocation_id: UUID
    parent_id: UUID | None = None
    replacement_of_id: UUID | None = None
    quantity: Quantity = Field(gt=0)
    occurred_at: AwareDatetime
    transaction_reference: str = Field(min_length=1, max_length=256)
    evidence_id: UUID
    share_with_source: bool = False
    reason: Text

    @model_validator(mode="after")
    def parent_required(self) -> "MovementDraft":
        if (self.kind == "issued") != (self.parent_id is None):
            raise ValueError("领料独立登记；耗用须指向原领料，退回和报废可指向原领料或原耗用")
        if not self.transaction_reference.strip():
            raise ValueError("请填写真实单据/交易及独立行号")
        return self


class MovementApply(MovementDraft):
    request_id: UUID
    expected_digest: Digest


class ReconciliationSelection(Contract):
    supply_snapshot_id: UUID
    outcome: Literal["confirmed", "withdrawn"]
    evidence_id: UUID
    reason: Text


class ReconciliationDraft(ReconciliationSelection):
    request_id: UUID
    expected_version: int = Field(ge=0)
    expected_digest: Digest


def effective(m: Any) -> Any:
    correction = tables.material_movement_corrections
    return (
        ~select(correction.c.id)
        .where(
            correction.c.tenant_id == m.c.tenant_id,
            correction.c.movement_id == m.c.id,
        )
        .correlate(m)
        .exists()
    )


def correction_row(c: Connection, tenant: UUID, movement: UUID) -> dict[str, Any] | None:
    table = tables.material_movement_corrections
    row = (
        c.execute(
            select(table).where(
                table.c.tenant_id == tenant,
                table.c.movement_id == movement,
            )
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


def source_signature(c: Connection, tenant: UUID, rows: list[dict[str, Any]]) -> list[str]:
    ids = [str(row["id"]) for row in rows]
    table = tables.material_movement_corrections
    ids.extend(
        str(value)
        for value in c.execute(
            select(table.c.id).where(
                table.c.tenant_id == tenant,
                table.c.movement_id.in_([row["id"] for row in rows]),
            )
        ).scalars()
    )
    return sorted(ids)


def balances(tenant: UUID) -> Any:
    m = tables.material_movements
    parent = m.alias("consumption_parent")

    def amount(kinds: tuple[str, ...]) -> Any:
        return func.sum(case((m.c.kind.in_(kinds), m.c.quantity), else_=0))

    qualified = case(
        ((m.c.kind == "issued") & m.c.qualified, m.c.quantity),
        ((m.c.kind.in_(("returned", "scrapped"))) & m.c.qualified, -m.c.quantity),
        else_=0,
    )
    return (
        select(
            m.c.allocation_id,
            amount(("issued",)).label("issued"),
            amount(("consumed",)).label("consumed"),
            func.sum(
                case(
                    (
                        (parent.c.kind == "consumed") & m.c.kind.in_(("returned", "scrapped")),
                        m.c.quantity,
                    ),
                    else_=0,
                )
            ).label("consumed_disposed"),
            amount(("returned",)).label("returned"),
            amount(("scrapped",)).label("scrapped"),
            func.sum(qualified).label("qualified_received"),
        )
        .outerjoin(parent, (parent.c.tenant_id == m.c.tenant_id) & (parent.c.id == m.c.parent_id))
        .where(m.c.tenant_id == tenant, effective(m))
        .group_by(m.c.allocation_id)
        .subquery()
    )


def source_movements(c: Connection, tenant: UUID, issue_id: UUID) -> list[dict[str, Any]]:
    m = tables.material_movements
    consumed = m.alias("returned_consumption")
    consumed_ids = select(consumed.c.id).where(
        consumed.c.tenant_id == tenant,
        consumed.c.parent_id == issue_id,
        consumed.c.kind == "consumed",
    )
    return [
        dict(row)
        for row in c.execute(
            select(m)
            .where(
                m.c.tenant_id == tenant,
                or_(
                    m.c.id == issue_id,
                    ((m.c.parent_id == issue_id) | m.c.parent_id.in_(consumed_ids))
                    & (m.c.kind == "returned"),
                ),
            )
            .order_by(m.c.id)
        ).mappings()
    ]


def last_reconciliation(c: Connection, tenant: UUID, movement_id: UUID) -> dict[str, Any] | None:
    r = tables.material_movement_reconciliations
    row = (
        c.execute(
            select(r)
            .where(r.c.tenant_id == tenant, r.c.movement_id == movement_id)
            .order_by(r.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


def reconciliation_evidence_current(
    c: Connection,
    tenant: UUID,
    record: dict[str, Any] | None,
) -> bool:
    if record is None:
        return False
    evidence = record["snapshot"].get("evidence", {})
    d = tables.documents
    current = c.execute(
        select(d.c.sha256).where(
            d.c.tenant_id == tenant,
            d.c.id == record["evidence_id"],
            d.c.project_id == record["project_id"],
        )
    ).scalar_one_or_none()
    return bool(current and current == evidence.get("sha256"))


def pending_issued(
    c: Connection, tenant: UUID, allocation_ids: list[UUID], source_id: UUID
) -> dict[str, Decimal]:
    m = tables.material_movements
    result: dict[str, Decimal] = {}
    for row in c.execute(
        select(m).where(
            m.c.tenant_id == tenant,
            m.c.allocation_id.in_(allocation_ids),
            m.c.kind == "issued",
            effective(m),
        )
    ).mappings():
        last = last_reconciliation(c, tenant, row["id"])
        movement_ids = source_signature(c, tenant, source_movements(c, tenant, row["id"]))
        reflected = bool(
            last
            and last["outcome"] == "confirmed"
            and last["supply_snapshot_id"] == source_id
            and last["snapshot"]["movement_ids"] == movement_ids
            and reconciliation_evidence_current(c, tenant, last)
        )
        if not reflected:
            key = str(row["allocation_id"])
            result[key] = result.get(key, Decimal(0)) + row["quantity"]
    return result


def _failure(message: str) -> Exception:
    from app.domain.material_allocations import MaterialAllocationError

    return MaterialAllocationError(message)


def _allocation(
    c: Connection, tenant: UUID, project: UUID, build: UUID, identity: UUID
) -> dict[str, Any]:
    a = tables.material_supply_allocations
    row = (
        c.execute(
            select(a).where(
                a.c.tenant_id == tenant,
                a.c.project_id == project,
                a.c.build_id == build,
                a.c.id == identity,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _failure("原分配不存在或不属于本批次")
    return dict(row)


def movement_preview(
    c: Connection,
    context: AuthContext,
    project: UUID,
    build: UUID,
    command: MovementDraft,
    *,
    lock: bool = False,
) -> dict[str, Any]:
    from app.domain.material_allocations import _active, _key, _pools

    BuildMaterialService._authorize(c, context, project, write=True)
    allocation = _allocation(c, context.tenant.id, project, build, command.allocation_id)
    if lock:
        lock_pools(c, context.tenant.id, [_key(allocation)])
    b = NpiExecutionService._row(
        c, tables.build_batches, tenant_id=context.tenant.id, project_id=project, record_id=build
    )
    if command.occurred_at > datetime.now(UTC):
        raise _failure("实际发生时间不能填写未来时间")
    evidence = metadata(document_row(c, context.tenant.id, project, command.evidence_id))
    m = tables.material_movements
    parent = None
    source = None
    replacement = None
    if command.replacement_of_id:
        original_row = (
            c.execute(
                select(m).where(
                    m.c.tenant_id == context.tenant.id,
                    m.c.project_id == project,
                    m.c.build_id == build,
                    m.c.id == command.replacement_of_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        corrected = correction_row(c, context.tenant.id, command.replacement_of_id)
        if original_row is None or corrected is None:
            raise _failure("更正登记必须引用本批次已具名冲正的原记录")
        if c.execute(
            select(m.c.id).where(
                m.c.tenant_id == context.tenant.id,
                m.c.replacement_of_id == command.replacement_of_id,
            )
        ).first():
            raise _failure("原记录已有更正登记；再次更正请沿新记录办理")
        replacement = {"original": _plain(dict(original_row)), "correction": _plain(corrected)}
    if command.kind == "issued":
        if b["status"] not in {"planned", "in_progress"} and not command.replacement_of_id:
            raise _failure("本批次已结束，不能新增领料；原领料的后续处置仍可登记")
        active = next(
            (
                row
                for row in _active(c, context.tenant.id, project_id=project, build_id=build)
                if row["id"] == str(command.allocation_id)
            ),
            None,
        )
        if active is None or command.quantity > Decimal(active["remaining_quantity"]):
            raise _failure("本次领料超过原分配尚未领用/释放的数量")
        source = _pools(c, context.tenant.id, project, [_key(allocation)])[_key(allocation)]
        actual = source["source"]
        qualified = bool(
            actual
            and source["state"] == "current"
            and actual["quality_status"] == "released"
            and actual["supply_kind"] == "on_hand"
            and (
                not allocation["supply_grant_id"]
                or str(allocation["supply_grant_id"]) == actual.get("source_grant_id")
            )
            and datetime.fromisoformat(actual["as_of"])
            <= command.occurred_at
            <= datetime.fromisoformat(actual["fresh_until"])
        )
        available = active["remaining_quantity"]
    else:
        parent_row = (
            c.execute(
                select(m).where(
                    m.c.tenant_id == context.tenant.id,
                    m.c.project_id == project,
                    m.c.build_id == build,
                    m.c.allocation_id == allocation["id"],
                    m.c.id == command.parent_id,
                    effective(m),
                    m.c.kind.in_(
                        ("issued",) if command.kind == "consumed" else ("issued", "consumed")
                    ),
                )
            )
            .mappings()
            .one_or_none()
        )
        if parent_row is None or command.occurred_at < parent_row["occurred_at"]:
            raise _failure("后续处置须指向本分配的原领料或原耗用，发生时间不得早于原记录")
        disposed = c.execute(
            select(func.coalesce(func.sum(m.c.quantity), 0)).where(
                m.c.tenant_id == context.tenant.id, m.c.parent_id == command.parent_id, effective(m)
            )
        ).scalar_one()
        available = str(parent_row["quantity"] - disposed)
        if command.quantity > Decimal(available):
            raise _failure("处置数量超过所选原记录尚未处置的余量")
        parent, qualified = _plain(dict(parent_row)), parent_row["qualified"]
    original = c.execute(
        select(tables.supply_snapshots.c.project_id).where(
            tables.supply_snapshots.c.tenant_id == context.tenant.id,
            tables.supply_snapshots.c.id == allocation["supply_snapshot_id"],
        )
    ).scalar_one()
    if (
        original != project
        and command.kind in {"issued", "returned"}
        and not command.share_with_source
    ):
        raise _failure(
            "跨项目领退料须明确同意向来源项目共享交易行号、数量及时间用于对账；原证据文件仍限本项目"
        )
    basis = {
        "build_id": str(build),
        "allocation": _plain(allocation),
        "available_quantity": available,
        "source": source,
        "parent": parent,
        "replacement": replacement,
        "qualified": qualified,
        "evidence": evidence,
        "source_project_id": str(original),
        "command": command.model_dump(mode="json", exclude={"request_id", "expected_digest"}),
    }
    return {"basis": basis, "digest": digest(basis)}


class MaterialMovementService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(
        self,
        context: AuthContext,
        project_id: UUID,
        build_id: UUID,
        movement_id: UUID | None = None,
    ) -> dict[str, Any]:
        from app.domain.material_allocations import _active

        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            BuildMaterialService._authorize(c, context, project_id)
            NpiExecutionService._row(
                c,
                tables.build_batches,
                tenant_id=context.tenant.id,
                project_id=project_id,
                record_id=build_id,
            )
            m, d = tables.material_movements, tables.documents
            query = select(m).where(
                m.c.tenant_id == context.tenant.id,
                m.c.project_id == project_id,
                m.c.build_id == build_id,
            )
            if movement_id:
                children = m.alias("history_children")
                consumed_ids = select(children.c.id).where(
                    children.c.tenant_id == context.tenant.id,
                    children.c.parent_id == movement_id,
                    children.c.kind == "consumed",
                )
                query = query.where(
                    or_(
                        m.c.id == movement_id,
                        m.c.parent_id == movement_id,
                        m.c.parent_id.in_(consumed_ids),
                    )
                ).order_by((m.c.id == movement_id).desc())
            rows = list(
                c.execute(query.order_by(m.c.created_at.desc(), m.c.id).limit(101)).mappings()
            )
            issues = []
            for row in rows[:100]:
                value = _plain(dict(row))
                corrected = correction_row(c, context.tenant.id, row["id"])
                value["correction"] = _plain(corrected) if corrected else None
                replacement_id = c.execute(
                    select(m.c.id).where(
                        m.c.tenant_id == context.tenant.id,
                        m.c.replacement_of_id == row["id"],
                    )
                ).scalar_one_or_none()
                value["replacement_id"] = str(replacement_id) if replacement_id else None
                if not corrected and row["kind"] in {"issued", "consumed"}:
                    disposed = c.execute(
                        select(func.coalesce(func.sum(m.c.quantity), 0)).where(
                            m.c.tenant_id == context.tenant.id,
                            m.c.parent_id == row["id"],
                            effective(m),
                        )
                    ).scalar_one()
                    value["disposable_quantity"] = str(row["quantity"] - disposed)
                issues.append(value)
            from app.domain.input_wait_responsibilities import people

            named = [row["created_by_user_id"] for row in issues] + [
                row["correction"]["created_by_user_id"] for row in issues if row["correction"]
            ]
            return {
                "items": issues,
                "people": people(c, context.tenant.id, named),
                "has_more": len(rows) > 100,
                "allocations": _active(
                    c, context.tenant.id, project_id=project_id, build_id=build_id
                ),
                "documents": [
                    _plain(dict(row))
                    for row in c.execute(
                        select(d.c.id, d.c.filename)
                        .where(d.c.tenant_id == context.tenant.id, d.c.project_id == project_id)
                        .order_by(d.c.created_at.desc())
                        .limit(200)
                    ).mappings()
                ],
            }

    def preview(
        self, context: AuthContext, project: UUID, build: UUID, command: MovementDraft
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
            localcontext() as arithmetic,
        ):
            arithmetic.prec = 2048
            return movement_preview(c, context, project, build, command)

    def apply(
        self, context: AuthContext, project: UUID, build: UUID, command: MovementApply
    ) -> dict[str, Any]:
        signature = digest(
            {
                "project": str(project),
                "build": str(build),
                "command": command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as c, localcontext() as arithmetic:
            arithmetic.prec = 2048
            NpiExecutionService._project(
                c, tenant_id=context.tenant.id, project_id=project, lock=True
            )
            BuildMaterialService._authorize(c, context, project, write=True)
            m = tables.material_movements
            prior = (
                c.execute(
                    select(m).where(
                        m.c.tenant_id == context.tenant.id,
                        m.c.created_by_user_id == context.user.id,
                        m.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != signature:
                    raise _failure("原请求已用于不同实际物料记录")
                return _plain(dict(prior))
            preview = movement_preview(c, context, project, build, command, lock=True)
            if preview["digest"] != command.expected_digest:
                raise _failure("原分配、领料余量或证据已变化，请重新预览")
            values = command.model_dump(exclude={"expected_digest"})
            saved = (
                c.execute(
                    m.insert()
                    .values(
                        **values,
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project,
                        build_id=build,
                        created_by_user_id=context.user.id,
                        request_digest=signature,
                        source_system=preview["basis"]["allocation"]["source_system"],
                        qualified=preview["basis"]["qualified"],
                        snapshot=preview["basis"],
                    )
                    .returning(m)
                )
                .mappings()
                .one()
            )
            NpiExecutionService._record_change(
                c,
                tenant_id=context.tenant.id,
                project_id=project,
                actor_user_id=context.user.id,
                record_id=saved["id"],
                record_type="material_movement",
                action=command.kind,
                before=None,
                after=_plain(dict(saved)),
            )
            return _plain(dict(saved))


def received_lots(
    c: Connection, tenant: UUID, allocation_ids: list[UUID]
) -> dict[str, list[dict[str, Any]]]:
    m = tables.material_movements
    child = m.alias("material_dispositions")
    parent = m.alias("disposition_parent")
    original_issue = case(
        (parent.c.kind == "consumed", parent.c.parent_id), else_=child.c.parent_id
    )
    disposed = (
        select(original_issue.label("parent_id"), func.sum(child.c.quantity).label("quantity"))
        .join(
            parent, (parent.c.tenant_id == child.c.tenant_id) & (parent.c.id == child.c.parent_id)
        )
        .where(
            child.c.tenant_id == tenant,
            child.c.kind.in_(("returned", "scrapped")),
            effective(child),
        )
        .group_by(original_issue)
        .subquery()
    )
    query = (
        select(
            m.c.id,
            m.c.allocation_id,
            m.c.occurred_at,
            m.c.qualified,
            (m.c.quantity - func.coalesce(disposed.c.quantity, 0)).label("quantity"),
        )
        .outerjoin(disposed, disposed.c.parent_id == m.c.id)
        .where(
            m.c.tenant_id == tenant,
            m.c.kind == "issued",
            m.c.allocation_id.in_(allocation_ids),
            effective(m),
        )
        .order_by(m.c.id)
    )
    result: dict[str, list[dict[str, Any]]] = {}
    for row in c.execute(query).mappings():
        result.setdefault(str(row["allocation_id"]), []).append(_plain(dict(row)))
    return result


def reconciliation_preview(
    c: Connection, context: AuthContext, project: UUID, issue_id: UUID, source_id: UUID
) -> dict[str, Any]:
    from app.domain.material_allocations import _key
    from app.domain.material_exposure import _source

    BuildMaterialService._authorize(c, context, project)
    m, a, s = tables.material_movements, tables.material_supply_allocations, tables.supply_snapshots
    row = (
        c.execute(
            select(
                m.c.id,
                m.c.allocation_id,
                m.c.project_id,
                m.c.share_with_source,
                a.c.source_system,
                a.c.external_pool_id,
                a.c.external_item_id,
                a.c.unit,
            )
            .join(a, (a.c.tenant_id == m.c.tenant_id) & (a.c.id == m.c.allocation_id))
            .join(s, (s.c.tenant_id == a.c.tenant_id) & (s.c.id == a.c.supply_snapshot_id))
            .where(
                m.c.tenant_id == context.tenant.id,
                m.c.id == issue_id,
                m.c.kind == "issued",
                s.c.project_id == project,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or (row["project_id"] != project and not row["share_with_source"]):
        raise _failure("当前来源项目没有可核对的该领料行")
    observed = _source(c, context.tenant.id, project, source_id)
    source = observed["source"]
    if _key(source) != _key(row) or source["unit"] != row["unit"]:
        raise _failure("余额快照须对应原供给池、物料和单位")
    movements = source_movements(c, context.tenant.id, issue_id)
    if any(
        value["project_id"] != project and not value["share_with_source"] for value in movements
    ):
        raise _failure("部分退料行尚未获准向来源项目共享")
    public = []
    for value in movements:
        corrected = correction_row(c, context.tenant.id, value["id"])
        public.append(
            _plain(
                {
                    **{
                        key: value[key]
                        for key in (
                            "id",
                            "kind",
                            "quantity",
                            "occurred_at",
                            "transaction_reference",
                        )
                    },
                    "corrected": bool(corrected),
                    "correction": {"id": corrected["id"], "created_at": corrected["created_at"]}
                    if corrected
                    else None,
                }
            )
        )
    latest = last_reconciliation(c, context.tenant.id, issue_id)
    reasons = []
    if correction_row(c, context.tenant.id, issue_id):
        reasons.append("原领料登记已冲正，仅保留历史；如有更正登记须按新记录对账")
    if not observed["current"]:
        reasons.append("所选余额已不是当前来源版本")
    if observed["state"] in {"stale", "source_changed"}:
        reasons.append("余额快照已过期或原件摘要已变化，请取得当前授权快照后重新核对")
    if source["quantity"] is None or source["supply_kind"] != "on_hand":
        reasons.append("须选择有明确余额的实际现货快照")
    if datetime.fromisoformat(source["as_of"]) < max(value["occurred_at"] for value in movements):
        reasons.append("余额数据时点早于部分实际出入库，不可声称已经反映")
    basis = {
        "movement_id": str(issue_id),
        "allocation_id": str(row["allocation_id"]),
        "source": source,
        "source_digest": observed["digest"],
        "recipient_project_id": str(row["project_id"]),
        "movements": public,
        "movement_ids": source_signature(c, context.tenant.id, movements),
        "previous_version": latest["version"] if latest else 0,
    }
    reflected = bool(
        latest
        and not correction_row(c, context.tenant.id, issue_id)
        and latest["outcome"] == "confirmed"
        and str(latest["supply_snapshot_id"]) == str(source_id)
        and latest["snapshot"]["movement_ids"] == basis["movement_ids"]
        and reconciliation_evidence_current(c, context.tenant.id, latest)
    )
    return {
        "basis": basis,
        "digest": digest(basis),
        "latest": _plain(latest) if latest else None,
        "eligible": not reasons,
        "reasons": reasons,
        "reflected": reflected,
    }


def confirmed_reconciliation_preview(
    c: Connection,
    context: AuthContext,
    project: UUID,
    movement: UUID,
    command: ReconciliationSelection,
) -> dict[str, Any]:
    BuildMaterialService._authorize(c, context, project, write=True)
    KnowledgeCorrectionService._authorize(
        c, context.tenant.id, context.user.id, project, Action.GATE_MANAGE
    )
    observed = reconciliation_preview(c, context, project, movement, command.supply_snapshot_id)
    selection = ReconciliationSelection.model_validate(
        command.model_dump(include=set(ReconciliationSelection.model_fields))
    )
    basis = {
        **observed["basis"],
        "tenant_id": str(context.tenant.id),
        "project_id": str(project),
        "reviewer_user_id": str(context.user.id),
        "command": selection.model_dump(mode="json"),
        "evidence": metadata(document_row(c, context.tenant.id, project, command.evidence_id)),
    }
    return {**observed, "basis": basis, "digest": digest(basis)}


class MaterialReconciliationService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def preview(
        self,
        context: AuthContext,
        project: UUID,
        movement: UUID,
        command: ReconciliationSelection,
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return confirmed_reconciliation_preview(c, context, project, movement, command)

    def get(
        self, context: AuthContext, project: UUID, source_id: UUID, after: UUID | None = None
    ) -> dict[str, Any]:
        from app.domain.knowledge_push import KnowledgeAccessError
        from app.domain.material_exposure import _source

        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            BuildMaterialService._authorize(c, context, project)
            observed = _source(c, context.tenant.id, project, source_id)
            source = observed["source"]
            m, a, s = (
                tables.material_movements,
                tables.material_supply_allocations,
                tables.supply_snapshots,
            )
            query = (
                select(m.c.id)
                .join(a, (a.c.tenant_id == m.c.tenant_id) & (a.c.id == m.c.allocation_id))
                .join(s, (s.c.tenant_id == a.c.tenant_id) & (s.c.id == a.c.supply_snapshot_id))
                .where(
                    m.c.tenant_id == context.tenant.id,
                    m.c.kind == "issued",
                    s.c.project_id == project,
                    a.c.source_system == source["source_system"],
                    a.c.external_pool_id == source["external_pool_id"],
                    a.c.external_item_id == source["external_item_id"],
                    a.c.unit == source["unit"],
                    or_(m.c.project_id == project, m.c.share_with_source.is_(True)),
                )
            )
            if after:
                query = query.where(m.c.id > after)
            ids = list(c.execute(query.order_by(m.c.id).limit(21)).scalars())
            try:
                KnowledgeCorrectionService._authorize(
                    c, context.tenant.id, context.user.id, project, Action.GATE_MANAGE
                )
                can_manage = True
            except KnowledgeAccessError:
                can_manage = False
            from app.domain.input_wait_responsibilities import people

            d = tables.documents
            items = [
                reconciliation_preview(c, context, project, identity, source_id)
                for identity in ids[:20]
            ]
            return {
                "source": source,
                "current": observed["current"],
                "items": items,
                "people": people(
                    c,
                    context.tenant.id,
                    [item["latest"]["created_by_user_id"] for item in items if item["latest"]],
                ),
                "next_cursor": str(ids[19]) if len(ids) > 20 else None,
                "can_manage": can_manage,
                "documents": [
                    _plain(dict(row))
                    for row in c.execute(
                        select(d.c.id, d.c.filename)
                        .where(d.c.tenant_id == context.tenant.id, d.c.project_id == project)
                        .order_by(d.c.created_at.desc())
                        .limit(200)
                    ).mappings()
                ],
            }

    def apply(
        self, context: AuthContext, project: UUID, issue_id: UUID, command: ReconciliationDraft
    ) -> dict[str, Any]:
        from app.domain.supply_sharing import _lock_projects

        signature = digest(
            {
                "project": str(project),
                "movement": str(issue_id),
                "command": command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as c:
            BuildMaterialService._authorize(c, context, project, write=True)
            KnowledgeCorrectionService._authorize(
                c, context.tenant.id, context.user.id, project, Action.GATE_MANAGE
            )
            preview = reconciliation_preview(
                c, context, project, issue_id, command.supply_snapshot_id
            )
            _lock_projects(
                c, context.tenant.id, [project, UUID(preview["basis"]["recipient_project_id"])]
            )
            source = preview["basis"]["source"]
            lock_pools(
                c,
                context.tenant.id,
                [(source["source_system"], source["external_pool_id"], source["external_item_id"])],
            )
            r = tables.material_movement_reconciliations
            prior = (
                c.execute(
                    select(r).where(
                        r.c.tenant_id == context.tenant.id,
                        r.c.created_by_user_id == context.user.id,
                        r.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != signature:
                    raise _failure("原请求已用于其他余额核对")
                return _plain(dict(prior))
            preview = confirmed_reconciliation_preview(c, context, project, issue_id, command)
            if (
                preview["digest"] != command.expected_digest
                or preview["basis"]["previous_version"] != command.expected_version
            ):
                raise _failure("出入库、余额或原核对版本已变化，请刷新")
            if command.outcome == "confirmed" and not preview["eligible"]:
                raise _failure("；".join(preview["reasons"]))
            if command.outcome == "withdrawn" and not preview["latest"]:
                raise _failure("没有可撤回的原核对")
            snapshot = preview["basis"]
            saved = (
                c.execute(
                    r.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project,
                        movement_id=issue_id,
                        supply_snapshot_id=command.supply_snapshot_id,
                        version=command.expected_version + 1,
                        outcome=command.outcome,
                        evidence_id=command.evidence_id,
                        reason=command.reason,
                        snapshot=snapshot,
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=signature,
                    )
                    .returning(r)
                )
                .mappings()
                .one()
            )
            NpiExecutionService._record_change(
                c,
                tenant_id=context.tenant.id,
                project_id=project,
                actor_user_id=context.user.id,
                record_id=issue_id,
                record_type="material_balance_reconciliation",
                action=command.outcome,
                before=preview["latest"],
                after=_plain(dict(saved)),
            )
            return _plain(dict(saved))
