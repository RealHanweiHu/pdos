"""Append-only correction of false material records, retaining all original evidence."""

from decimal import Decimal, localcontext
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.build_materials import BuildMaterialService
from app.domain.document_previews import document_row, metadata
from app.domain.material_allocations import _key
from app.domain.material_movements import _failure, correction_row, effective
from app.domain.material_supply_pools import lock_pools
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import _plain, digest


class CorrectionDraft(Contract):
    evidence_id: UUID
    reason: Text


class CorrectionApply(CorrectionDraft):
    request_id: UUID
    expected_digest: Digest


def preview(
    c: Connection,
    context: AuthContext,
    project: UUID,
    build: UUID,
    movement: UUID,
    command: CorrectionDraft,
) -> dict[str, Any]:
    BuildMaterialService._authorize(c, context, project, write=True)
    m = tables.material_movements
    row = (
        c.execute(
            select(m).where(
                m.c.tenant_id == context.tenant.id,
                m.c.project_id == project,
                m.c.build_id == build,
                m.c.id == movement,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _failure("原实际记录不存在或不属于本批次")
    if correction_row(c, context.tenant.id, movement):
        raise _failure("原记录已冲正；更正后的事实请沿新记录办理")
    children = list(
        c.execute(
            select(m.c.id, m.c.kind, m.c.quantity, m.c.transaction_reference)
            .where(
                m.c.tenant_id == context.tenant.id,
                m.c.parent_id == movement,
                effective(m),
            )
            .order_by(m.c.id)
            .limit(21)
        ).mappings()
    )
    # A direct child can only be corrected after its own descendants are corrected.
    # Therefore no active grandchild can be orphaned when this record is corrected.
    evidence = metadata(document_row(c, context.tenant.id, project, command.evidence_id))
    quantity = row["quantity"]
    impacts = {
        "undrawn_allocation_delta": quantity if row["kind"] == "issued" else Decimal(0),
        "net_received_delta": -quantity
        if row["kind"] == "issued"
        else (quantity if row["kind"] in {"returned", "scrapped"} else Decimal(0)),
        "source_balance_changed": False,
        "requires_balance_recheck": row["kind"] in {"issued", "returned"},
    }
    basis = _plain(
        {
            "original": dict(row),
            "evidence": evidence,
            "reason": command.reason,
            "active_children": [dict(child) for child in children[:20]],
            "more_children": len(children) > 20,
            "impacts": impacts,
        }
    )
    return {"basis": basis, "digest": digest(basis), "eligible": not children}


class MaterialCorrectionService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def preview(
        self,
        context: AuthContext,
        project: UUID,
        build: UUID,
        movement: UUID,
        command: CorrectionDraft,
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return preview(c, context, project, build, movement, command)

    def apply(
        self,
        context: AuthContext,
        project: UUID,
        build: UUID,
        movement: UUID,
        command: CorrectionApply,
    ) -> dict[str, Any]:
        signature = digest(
            {
                "project": str(project),
                "build": str(build),
                "movement": str(movement),
                "command": command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as c, localcontext() as arithmetic:
            arithmetic.prec = 2048
            NpiExecutionService._project(
                c, tenant_id=context.tenant.id, project_id=project, lock=True
            )
            BuildMaterialService._authorize(c, context, project, write=True)
            table = tables.material_movement_corrections
            prior = (
                c.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.created_by_user_id == context.user.id,
                        table.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != signature:
                    raise _failure("该请求已用于另一冲正记录")
                return _plain(dict(prior))
            value = preview(c, context, project, build, movement, command)
            original = value["basis"]["original"]
            allocation = (
                c.execute(
                    select(tables.material_supply_allocations).where(
                        tables.material_supply_allocations.c.tenant_id == context.tenant.id,
                        tables.material_supply_allocations.c.id == UUID(original["allocation_id"]),
                    )
                )
                .mappings()
                .one()
            )
            lock_pools(c, context.tenant.id, [_key(allocation)])
            # Source-transaction locking is shared with new movement registration.
            c.execute(
                select(
                    func.cehub_supplier.lock_material_transaction(
                        context.tenant.id,
                        original["source_system"],
                        original["kind"],
                        original["transaction_reference"],
                    )
                )
            )
            value = preview(c, context, project, build, movement, command)
            if value["digest"] != command.expected_digest:
                raise _failure("原记录、后续处置或证据发生变化，请重新预览")
            if not value["eligible"]:
                raise _failure("请先逐项冲正仍有效的后续处置，再处理原记录")
            saved = (
                c.execute(
                    table.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project,
                        movement_id=movement,
                        evidence_id=command.evidence_id,
                        reason=command.reason,
                        request_id=command.request_id,
                        request_digest=signature,
                        created_by_user_id=context.user.id,
                        snapshot=value["basis"],
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            NpiExecutionService._record_change(
                c,
                tenant_id=context.tenant.id,
                project_id=project,
                actor_user_id=context.user.id,
                record_id=movement,
                record_type="material_movement_correction",
                action="corrected",
                before=original,
                after=_plain(dict(saved)),
            )
            return _plain(dict(saved))
