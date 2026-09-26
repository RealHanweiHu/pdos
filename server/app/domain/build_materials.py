"""Immutable Build Prototype BOM snapshots and exact, reviewable demand expansion."""

from decimal import Decimal, localcontext
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import _plain, digest

POLICY = "bom.parent_relative.quantity.v1"


class BuildMaterialError(ValueError):
    """The selected source or reviewed expansion can no longer be applied."""


class MaterialSelection(Contract):
    bom_id: UUID
    need_by_node_id: UUID
    selected_item_ids: list[UUID] | None = Field(default=None, max_length=2000)
    critical_item_ids: list[UUID] = Field(default_factory=list, max_length=2000)


class MaterialFreeze(MaterialSelection):
    request_id: UUID
    expected_digest: Digest
    reason: Text


def _bom(connection: Connection, tenant_id: UUID, project_id: UUID, bom_id: UUID) -> dict[str, Any]:
    header = (
        connection.execute(
            select(tables.development_boms).where(
                tables.development_boms.c.tenant_id == tenant_id,
                tables.development_boms.c.project_id == project_id,
                tables.development_boms.c.id == bom_id,
                tables.development_boms.c.bom_type == "prototype",
            )
        )
        .mappings()
        .one_or_none()
    )
    if header is None:
        raise BuildMaterialError("请选取本项目实际 Prototype BOM")
    items = list(
        connection.execute(
            select(tables.development_bom_items)
            .where(
                tables.development_bom_items.c.tenant_id == tenant_id,
                tables.development_bom_items.c.project_id == project_id,
                tables.development_bom_items.c.bom_id == bom_id,
            )
            .order_by(tables.development_bom_items.c.line_number)
            .limit(2001)
        ).mappings()
    )
    if not items or len(items) > 2000:
        raise BuildMaterialError("BOM须有1–2000项；空表或超出本次展开范围时不能冻结")
    return _plain({"header": dict(header), "items": [dict(row) for row in items]})


def _capture(
    connection: Connection,
    tenant_id: UUID,
    project_id: UUID,
    build_id: UUID,
    selection: MaterialSelection,
) -> dict[str, Any]:
    build = NpiExecutionService._row(
        connection,
        tables.build_batches,
        tenant_id=tenant_id,
        project_id=project_id,
        record_id=build_id,
    )
    bom = _bom(connection, tenant_id, project_id, selection.bom_id)
    node = (
        connection.execute(
            select(tables.schedule_nodes).where(
                tables.schedule_nodes.c.tenant_id == tenant_id,
                tables.schedule_nodes.c.project_id == project_id,
                tables.schedule_nodes.c.id == selection.need_by_node_id,
                tables.schedule_nodes.c.node_kind == "build",
                tables.schedule_nodes.c.build_id == build_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if node is None:
        raise BuildMaterialError("需料节点须为本批次实际登记的Build排程节点，请先在正式排程登记")
    items = {row["id"]: row for row in bom["items"]}
    parents = {row["parent_item_id"] for row in items.values() if row["parent_item_id"]}
    leaves = set(items) - parents
    selected = (
        {str(value) for value in selection.selected_item_ids}
        if selection.selected_item_ids is not None
        else leaves
    )
    critical = {str(value) for value in selection.critical_item_ids}
    if not selected or not selected <= set(items) or not critical <= selected:
        raise BuildMaterialError("所选需求项须属于本BOM，关键件须同时列为需求项")
    if selection.selected_item_ids is not None and len(selected) != len(
        selection.selected_item_ids
    ):
        raise BuildMaterialError("需求项不得重复选择")
    paths: dict[str, list[str]] = {}
    per_build: dict[str, Decimal] = {}
    with localcontext() as context:
        # DB source quantities have at most 18 digits; 64 levels fit exactly.
        context.prec = 2048
        for key in items:
            path: list[str] = []
            current: str | None = key
            quantity = Decimal(1)
            while current is not None:
                if current in path or current not in items or len(path) >= 64:
                    raise BuildMaterialError("BOM父子关系缺项、成环或超过64层，请先修订原BOM")
                path.append(current)
                component_quantity = Decimal(items[current]["quantity"])
                if not component_quantity.is_finite() or component_quantity <= 0:
                    raise BuildMaterialError("BOM用量须为有限正数，请先修订原始条目")
                quantity *= component_quantity
                current = items[current]["parent_item_id"]
            paths[key] = list(reversed(path))
            per_build[key] = quantity
        if any(len(selected.intersection(paths[leaf])) != 1 for leaf in leaves):
            raise BuildMaterialError(
                "每条末级路径须且只能选一个供料层级；不得同时采购父件和其子件，也不能遗漏路径"
            )
        lines = [
            {
                "bom_item_id": key,
                "line_number": row["line_number"],
                "part_number": row["part_number"],
                "description": row["description"],
                "unit": row["unit"],
                "material_reference": row["material_reference"],
                "path": paths[key],
                "per_build_quantity": str(per_build[key]),
                "required_quantity": str(per_build[key] * build["planned_quantity"]),
                "critical": key in critical,
                "substitution": "not_authorized",
                "quality_release": "unknown",
            }
            for key, row in items.items()
            if key in selected
        ]
    snapshot = _plain(
        {
            "policy": POLICY,
            "build": {
                key: build[key]
                for key in (
                    "id",
                    "code",
                    "stage_id",
                    "phase",
                    "purpose",
                    "planned_quantity",
                    "status",
                )
            },
            "bom": bom,
            "need_by_node": dict(node),
        }
    )
    return {
        "snapshot": snapshot,
        "lines": lines,
        "source_digest": digest(bom),
        "digest": digest({"snapshot": snapshot, "lines": lines}),
        "selected_item_ids": [row["bom_item_id"] for row in lines],
        "warnings": [
            "用量相对上一级，根项为每台；按父子路径相乘后乘批次数量，单位保持原BOM，不自动折算。",
            "选中父件即按整件供料，其子项不再重复计需求；未选父件按所选下级项展开。",
            "物料引用尚未核对ERP主数据；库存、采购、替代批准和质量放行仍需独立来源，不据本表推定齐套。",
        ]
        + (
            ["存在未填物料引用的需求项，供给对账前需补齐映射。"]
            if any(not row["material_reference"] for row in lines)
            else []
        ),
    }


class BuildMaterialService:
    def __init__(self, engine: Engine):
        self.engine = engine

    @staticmethod
    def _authorize(
        c: Connection, context: AuthContext, project_id: UUID, *, write: bool = False
    ) -> None:
        KnowledgeCorrectionService._authorize(
            c,
            context.tenant.id,
            context.user.id,
            project_id,
            Action.PRODUCT_ENGINEERING_EDIT if write else Action.PRODUCT_ENGINEERING_VIEW,
        )

    def get(self, context: AuthContext, project_id: UUID, build_id: UUID) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            self._authorize(c, context, project_id)
            tenant_id = context.tenant.id
            build = NpiExecutionService._row(
                c,
                tables.build_batches,
                tenant_id=tenant_id,
                project_id=project_id,
                record_id=build_id,
            )
            revisions = list(
                c.execute(
                    select(
                        tables.build_material_revisions,
                        tables.users.c.display_name.label("created_by_name"),
                    )
                    .join(
                        tables.users,
                        (tables.users.c.tenant_id == tables.build_material_revisions.c.tenant_id)
                        & (
                            tables.users.c.id
                            == tables.build_material_revisions.c.created_by_user_id
                        ),
                    )
                    .where(
                        tables.build_material_revisions.c.tenant_id == tenant_id,
                        tables.build_material_revisions.c.project_id == project_id,
                        tables.build_material_revisions.c.build_id == build_id,
                    )
                    .order_by(tables.build_material_revisions.c.version.desc())
                    .limit(51)
                ).mappings()
            )
            source_current = None
            if revisions:
                try:
                    source_current = (
                        digest(_bom(c, tenant_id, project_id, revisions[0]["bom_id"]))
                        == revisions[0]["source_digest"]
                    )
                except BuildMaterialError:
                    source_current = False
            boms = list(
                c.execute(
                    select(tables.development_boms)
                    .where(
                        tables.development_boms.c.tenant_id == tenant_id,
                        tables.development_boms.c.project_id == project_id,
                        tables.development_boms.c.bom_type == "prototype",
                    )
                    .order_by(
                        tables.development_boms.c.updated_at.desc(), tables.development_boms.c.id
                    )
                    .limit(201)
                ).mappings()
            )
            nodes = list(
                c.execute(
                    select(tables.schedule_nodes)
                    .where(
                        tables.schedule_nodes.c.tenant_id == tenant_id,
                        tables.schedule_nodes.c.project_id == project_id,
                        tables.schedule_nodes.c.node_kind == "build",
                        tables.schedule_nodes.c.build_id == build_id,
                    )
                    .order_by(tables.schedule_nodes.c.id)
                ).mappings()
            )
            ecns = list(
                c.execute(
                    select(tables.engineering_change_notices)
                    .where(
                        tables.engineering_change_notices.c.tenant_id == tenant_id,
                        tables.engineering_change_notices.c.project_id == project_id,
                        tables.engineering_change_notices.c.status == "erp_handoff",
                    )
                    .order_by(
                        tables.engineering_change_notices.c.created_at.desc(),
                        tables.engineering_change_notices.c.id,
                    )
                    .limit(201)
                ).mappings()
            )
            return _plain(
                {
                    "ecns": [dict(row) for row in ecns[:200]],
                    "ecns_has_more": len(ecns) > 200,
                    "can_revise": is_allowed(context.user.role, Action.CHANGE_APPROVE),
                    "build": dict(build),
                    "revisions": [dict(row) for row in revisions[:50]],
                    "has_more": len(revisions) > 50,
                    "source_is_current": source_current,
                    "boms": [dict(row) for row in boms[:200]],
                    "boms_has_more": len(boms) > 200,
                    "nodes": [dict(row) for row in nodes],
                }
            )

    def preview(
        self, context: AuthContext, project_id: UUID, build_id: UUID, command: MaterialSelection
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            self._authorize(c, context, project_id)
            return _capture(c, context.tenant.id, project_id, build_id, command)

    def freeze(
        self, context: AuthContext, project_id: UUID, build_id: UUID, command: MaterialFreeze
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            self._authorize(c, context, project_id, write=True)
            tenant_id = context.tenant.id
            NpiExecutionService._project(c, tenant_id=tenant_id, project_id=project_id, lock=True)
            table = tables.build_material_revisions
            signature = digest(
                {
                    "project_id": str(project_id),
                    "build_id": str(build_id),
                    "command": command.model_dump(mode="json"),
                }
            )
            previous = (
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
            if previous:
                if previous["request_digest"] != signature:
                    raise BuildMaterialError("原请求编号已用于不同内容，请核对原回执")
                return _plain(dict(previous))
            if c.execute(
                select(table.c.id).where(
                    table.c.tenant_id == tenant_id, table.c.build_id == build_id
                )
            ).first():
                raise BuildMaterialError(
                    "本批次已有固定需求；原版保持只读，后续变更须经ECN形成独立修订，不可重新覆盖"
                )
            captured = _capture(c, tenant_id, project_id, build_id, command)
            if captured["snapshot"]["build"]["status"] != "planned":
                raise BuildMaterialError(
                    "本入口仅在批次开始前固定需求；在途和历史批次不能将当前BOM冒充原始版本"
                )
            if captured["digest"] != command.expected_digest:
                raise BuildMaterialError("批次、BOM或需料节点已变化，请重新预览并核对需求")
            row = (
                c.execute(
                    table.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        project_id=project_id,
                        build_id=build_id,
                        version=1,
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
                action="frozen",
                before=None,
                after=result,
            )
            return result
