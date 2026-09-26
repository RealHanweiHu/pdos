"""Explicit ECN-backed Build demand revisions; old BOM snapshots remain immutable."""

from decimal import Decimal, localcontext
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Digest, Text
from app.db.schema import tables
from app.domain.build_materials import (
    BuildMaterialError,
    BuildMaterialService,
    MaterialSelection,
    _capture,
)
from app.domain.change_execution_tasks import _state
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import _plain, digest


class MaterialRevisionSelection(MaterialSelection):
    previous_revision_id: UUID
    ecn_id: UUID
    applicability_basis: Text


class MaterialRevisionApply(MaterialRevisionSelection):
    request_id: UUID
    expected_digest: Digest
    reason: Text


def _delta(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compare like references/part numbers/units without inferring substitutions."""
    old: dict[tuple[str, str, str], dict[str, Any]] = {}
    new: dict[tuple[str, str, str], dict[str, Any]] = {}
    with localcontext() as context:
        context.prec = 2048
        for lines, target in ((before, old), (after, new)):
            for line in lines:
                key = (line["material_reference"] or "", line["part_number"], line["unit"])
                entry = target.setdefault(
                    key, {"quantity": Decimal(0), "lines": [], "critical": False}
                )
                entry["quantity"] += Decimal(line["required_quantity"])
                entry["lines"].append(line["bom_item_id"])
                entry["critical"] |= line["critical"]
        results = []
        for key in sorted(set(old) | set(new)):
            previous = old.get(key, {"quantity": Decimal(0), "lines": [], "critical": False})
            current = new.get(key, {"quantity": Decimal(0), "lines": [], "critical": False})
            if (
                previous["quantity"] == current["quantity"]
                and previous["critical"] == current["critical"]
            ):
                continue
            results.append(
                {
                    "material_reference": key[0] or None,
                    "part_number": key[1],
                    "unit": key[2],
                    "before_quantity": str(previous["quantity"]),
                    "after_quantity": str(current["quantity"]),
                    "quantity_delta": str(current["quantity"] - previous["quantity"]),
                    "before_critical": previous["critical"],
                    "after_critical": current["critical"],
                    "before_bom_item_ids": previous["lines"],
                    "after_bom_item_ids": current["lines"],
                }
            )
        return results


def _prepare(
    c: Connection,
    context: AuthContext,
    project_id: UUID,
    build_id: UUID,
    command: MaterialRevisionSelection,
) -> dict[str, Any]:
    tenant_id = context.tenant.id
    BuildMaterialService._authorize(c, context, project_id)
    KnowledgeCorrectionService._authorize(
        c, tenant_id, context.user.id, project_id, Action.CHANGE_VIEW
    )
    table = tables.build_material_revisions
    previous = (
        c.execute(
            select(table)
            .where(
                table.c.tenant_id == tenant_id,
                table.c.project_id == project_id,
                table.c.build_id == build_id,
            )
            .order_by(table.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if previous is None or previous["id"] != command.previous_revision_id:
        raise BuildMaterialError("原批次需求版本已变化，请刷新并按最新固定版准备修订")
    ecn = NpiExecutionService._row(
        c,
        tables.engineering_change_notices,
        tenant_id=tenant_id,
        project_id=project_id,
        record_id=command.ecn_id,
    )
    decision = (
        c.execute(
            select(tables.decisions).where(
                tables.decisions.c.tenant_id == tenant_id,
                tables.decisions.c.project_id == project_id,
                tables.decisions.c.id == ecn["effectivity_decision_id"],
                tables.decisions.c.decision_kind == "ecn_effectivity",
                tables.decisions.c.outcome == "approved",
            )
        )
        .mappings()
        .one_or_none()
    )
    if ecn["status"] != "erp_handoff" or decision is None:
        raise BuildMaterialError("请选择已具名批准生效的ECN；取消或尚待裁决的通知不能修订需求")
    approved = _state(c, tenant_id, project_id, ecn["ecr_id"])
    if not approved["can_assign"]:
        raise BuildMaterialError("ECN原ECR的批准范围缺失或已变化，请先完成原变更范围核对")
    affected = {
        (item["kind"], item["id"])
        for item in approved["approved_scope"]["version"]["snapshot"]["items"]
        if item["conclusion"] == "affected"
    }
    if not {("build", str(build_id)), ("bom", str(command.bom_id))} <= affected:
        raise BuildMaterialError(
            "批准范围须明确包含本批次及所选Prototype BOM，不能按同项目推定适用"
        )
    if c.execute(
        select(table.c.id).where(
            table.c.tenant_id == tenant_id,
            table.c.build_id == build_id,
            table.c.ecn_id == command.ecn_id,
        )
    ).first():
        raise BuildMaterialError("本ECN已形成该批次修订，请查看原回执；新的变更另走ECN")
    captured = _capture(c, tenant_id, project_id, build_id, command)
    if captured["snapshot"]["build"]["status"] != "planned":
        raise BuildMaterialError(
            "整批需求修订仅适用于尚未开工批次；在途须先核对已领料、装机与剩余适用数量"
        )
    delta = _delta(previous["lines"], captured["lines"])
    change_context = _plain(
        {
            "ecn": dict(ecn),
            "decision": dict(decision),
            "approved_scope": approved["approved_scope"],
            "source_changes": approved["source_changes"],
            "applicability_basis": command.applicability_basis,
        }
    )
    return {
        **captured,
        "previous": _plain(dict(previous)),
        "delta": delta,
        "change_context": change_context,
        "digest": digest(
            {
                "next": captured["digest"],
                "previous_id": str(previous["id"]),
                "previous_digest": previous["content_digest"],
                "change_context": change_context,
                "delta": delta,
            }
        ),
        "warnings": [
            *captured["warnings"],
            "差量按物料引用、料号和单位汇总；引用或单位改变分别列减少/新增，不认定为批准替代。",
            "差量是两版计划需求的差异，不代表库存变化、已采购数量、实际领料或装机变化。",
        ],
    }


class BuildMaterialChangeService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def preview(
        self,
        context: AuthContext,
        project_id: UUID,
        build_id: UUID,
        command: MaterialRevisionSelection,
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return _prepare(c, context, project_id, build_id, command)

    def apply(
        self, context: AuthContext, project_id: UUID, build_id: UUID, command: MaterialRevisionApply
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            tenant_id = context.tenant.id
            BuildMaterialService._authorize(c, context, project_id, write=True)
            KnowledgeCorrectionService._authorize(
                c, tenant_id, context.user.id, project_id, Action.CHANGE_APPROVE
            )
            NpiExecutionService._project(c, tenant_id=tenant_id, project_id=project_id, lock=True)
            table = tables.build_material_revisions
            signature = digest(
                {
                    "project_id": str(project_id),
                    "build_id": str(build_id),
                    "command": command.model_dump(mode="json"),
                }
            )
            receipt = (
                c.execute(
                    select(table).where(
                        table.c.tenant_id == tenant_id,
                        table.c.created_by_user_id == context.user.id,
                        table.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if receipt:
                if receipt["request_digest"] != signature:
                    raise BuildMaterialError("原请求编号已用于其他内容，请按原输入核对回执")
                return _plain(dict(receipt))
            captured = _prepare(c, context, project_id, build_id, command)
            if captured["digest"] != command.expected_digest:
                raise BuildMaterialError("原需求、新BOM或ECN生效依据已变化，请重新预览差量")
            row = (
                c.execute(
                    table.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        project_id=project_id,
                        build_id=build_id,
                        version=captured["previous"]["version"] + 1,
                        previous_revision_id=command.previous_revision_id,
                        ecn_id=command.ecn_id,
                        change_context=captured["change_context"],
                        delta=captured["delta"],
                        bom_id=command.bom_id,
                        need_by_node_id=command.need_by_node_id,
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=signature,
                        source_digest=captured["source_digest"],
                        content_digest=captured["digest"],
                        snapshot=captured["snapshot"],
                        lines=captured["lines"],
                        reason=command.reason,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            result = _plain(dict(row))
            NpiExecutionService._record_change(
                c,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=context.user.id,
                record_id=row["id"],
                record_type="build_material",
                action="revised",
                before=captured["previous"],
                after=result,
            )
            return result
