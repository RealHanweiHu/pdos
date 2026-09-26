"""Explicit material constraints for forecasts; source observations never read forecasts."""

from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.formal_schedule import current_plan
from app.domain.material_allocations import MaterialAllocationError, read_material_state
from app.domain.material_coverage import CoverageSelection, calculate
from app.domain.material_exceptions import _assessment, _authorize, _lock_sources, _review, _row
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import _plain, digest
from app.domain.resource_reservations import _project

POLICY = "material.forecast.explicit_scope.v1"


class BindingDraft(Contract):
    request_id: UUID
    expected_version: int = Field(ge=0)
    review_id: UUID
    source_digest: Digest
    mode: Literal["waiting", "estimate", "released"]
    target_point: Literal["start", "remaining"]
    node_ids: list[UUID] = Field(max_length=100)
    ready_at: AwareDatetime | None = None
    reason: Text

    @model_validator(mode="after")
    def scope(self) -> Self:
        if len(set(self.node_ids)) != len(self.node_ids):
            raise ValueError("受影响节点不能重复")
        if (self.mode == "released") != (len(self.node_ids) == 0):
            raise ValueError("解除影响需清空节点；其他模式须明确至少一个节点")
        if (self.mode == "estimate") != (self.ready_at is not None):
            raise ValueError("只有明确预计可用时间的模式可以填写时间")
        return self


def source_core(assessment: dict[str, Any]) -> dict[str, Any]:
    basis = assessment["basis"]
    material = basis["material"]
    return {
        "revision_id": basis["revision_id"],
        "revision_digest": basis["revision_digest"],
        "material_key": basis["material_key"],
        "material": {
            key: material[key]
            for key in ("material_key", "material_reference", "unit", "required", "lines")
        }
        if material
        else None,
        "pools": [
            {key: value for key, value in pool.items() if key != "delivery"}
            for pool in basis["pools"]
        ],
        "allocations": basis["allocations"],
        "pool_limit_reached": basis["pool_limit_reached"],
    }


def observations(
    c: Connection, tenant_id: UUID, project_id: UUID, entries: list[dict[str, Any]]
) -> dict[UUID, dict[str, Any]]:
    """Source-only projection prevents supply -> forecast -> supply recursion."""
    result = {}
    build_cache: dict[UUID, dict[str, Any]] = {}
    with localcontext() as arithmetic:
        arithmetic.prec = 2048
        for entry in entries:
            build_id = entry["build_id"]
            if build_id not in build_cache:
                data = read_material_state(c, tenant_id, project_id, build_id)
                build_cache[build_id] = calculate(
                    data,
                    {"node": None, "calendar": None, "times": {}, "issues": []},
                    CoverageSelection(),
                )
            assessment = _assessment(build_cache[build_id], entry["material_key"])
            latest = _review(c, tenant_id, entry["id"])
            core = source_core(assessment)
            core_digest = digest(core)
            review_current = digest(source_core(latest["snapshot"])) == core_digest
            material = assessment["basis"]["material"]
            ready = material is not None and (
                Decimal(material["allocated_on_hand"])
                + Decimal(material.get("qualified_issued", "0"))
            ) >= Decimal(material["required"])
            result[entry["id"]] = {
                "core": core,
                "source_digest": core_digest,
                "review_current": review_current,
                "latest_review": _plain(latest),
                "material": material,
                "supply_ready": bool(
                    ready and review_current and latest["disposition"] == "supply_ready"
                ),
            }
    return result


def latest_bindings(c: Connection, tenant_id: UUID, project_id: UUID) -> list[dict[str, Any]]:
    t = tables.material_schedule_bindings
    return [
        dict(row)
        for row in c.execute(
            select(t)
            .where(t.c.tenant_id == tenant_id, t.c.project_id == project_id)
            .distinct(t.c.exception_id)
            .order_by(t.c.exception_id, t.c.version.desc())
        ).mappings()
    ]


def conditions(
    c: Connection, tenant_id: UUID, project_id: UUID
) -> dict[UUID, list[dict[str, Any]]]:
    bindings = latest_bindings(c, tenant_id, project_id)
    active = [row for row in bindings if row["mode"] != "released"]
    if not active:
        return {}
    t = tables.material_exceptions
    entries = [
        dict(row)
        for row in c.execute(
            select(t).where(
                t.c.tenant_id == tenant_id,
                t.c.project_id == project_id,
                t.c.id.in_([row["exception_id"] for row in active]),
            )
        ).mappings()
    ]
    current = observations(c, tenant_id, project_id, entries)
    issue_ids = {entry["id"]: entry["issue_id"] for entry in entries}
    result: dict[UUID, list[dict[str, Any]]] = {}
    for binding in active:
        state = current[binding["exception_id"]]
        same_revision = binding["snapshot"]["source"]["revision_id"] == state["core"]["revision_id"]
        if state["supply_ready"] and same_revision:
            status = "ready"
        elif not same_revision or state["source_digest"] != binding["source_digest"]:
            status = "source_changed"
        elif binding["mode"] == "estimate":
            status = "estimate" if binding["ready_at"] > datetime.now(UTC) else "estimate_expired"
        else:
            status = "waiting"
        value = _plain(
            {
                "policy": POLICY,
                "binding_id": binding["id"],
                "binding_version": binding["version"],
                "exception_id": binding["exception_id"],
                "issue_id": issue_ids[binding["exception_id"]],
                "review_id": state["latest_review"]["id"],
                "source_digest": state["source_digest"],
                "target_point": binding["target_point"],
                "status": status,
                "ready_at": binding["ready_at"] if status == "estimate" else None,
            }
        )
        for identity in binding["node_ids"]:
            result.setdefault(UUID(identity), []).append(value)
    return result


def meeting_summary(
    c: Connection, tenant_id: UUID, project_id: UUID, issue_ids: list[UUID]
) -> dict[UUID, dict[str, Any]]:
    if not issue_ids:
        return {}
    t = tables.material_exceptions
    entries = [
        dict(row)
        for row in c.execute(
            select(t).where(
                t.c.tenant_id == tenant_id,
                t.c.project_id == project_id,
                t.c.issue_id.in_(issue_ids),
            )
        ).mappings()
    ]
    if not entries:
        return {}
    current = observations(c, tenant_id, project_id, entries)
    bindings = {row["exception_id"]: row for row in latest_bindings(c, tenant_id, project_id)}
    result = {}
    for entry in entries:
        value = current[entry["id"]]
        material = value["material"]
        binding = bindings.get(entry["id"])
        summary = [
            f"物料异常 {entry['id']}；批次 {entry['build_id']}。",
            f"最近具名核对 v{value['latest_review']['version']}："
            f"{value['latest_review']['reason']}",
            "当前供给依据与最近核对一致。"
            if value["review_current"]
            else "供给或需求来源已变化，须回到原异常重新核对。",
        ]
        if material:
            gap = material["observed_on_hand_gap"]
            summary.append(
                f"需求 {material['required']} {material['unit']}；"
                f"已分配合格现货 {material['allocated_on_hand']}，"
                f"领用时合格净领料 {material.get('qualified_issued', '0')}；"
                f"已登记范围现货缺口 {gap if gap is not None else '未知'}。"
            )
        else:
            summary.append("当前固定需求已不含该物料，须核对范围修订及原问题处理。")
        summary.append(
            f"已登记排程影响 v{binding['version']}，共 {len(binding['node_ids'])} 个节点；"
            "仅用于预测。"
            if binding
            else "尚未登记对正式节点的预测影响。"
        )
        if binding and binding["mode"] != "released" and not value["supply_ready"]:
            if binding["source_digest"] != value["source_digest"]:
                summary.append("原排程影响的供给来源已变化，须重新登记预测依据或明确解除。")
            elif binding["ready_at"] and binding["ready_at"] <= datetime.now(UTC):
                summary.append("原预计可用时间已过，预测恢复时间须重新核对。")
        summary.append("供给齐备不等于原问题或会议行动已关闭，需沿原业务核对。")
        result[entry["issue_id"]] = {
            "summary": summary,
            "digest": digest(
                {
                    "source": value["source_digest"],
                    "review_id": value["latest_review"]["id"],
                    "binding_id": str(binding["id"]) if binding else None,
                    "summary": summary,
                }
            ),
            "material_review_ready": bool(
                value["review_current"]
                and value["latest_review"]["disposition"] in {"supply_ready", "scope_changed"}
            ),
        }
    return result


class MaterialScheduleService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(
        self,
        context: AuthContext,
        project_id: UUID,
        exception_id: UUID,
        *,
        version: int | None = None,
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            _authorize(c, context, project_id)
            _project(c, context, project_id)
            row = _row(c, context.tenant.id, project_id, exception_id)
            observation = observations(c, context.tenant.id, project_id, [row])[exception_id]
            formal = current_plan(c, context.tenant.id, project_id)
            nodes = (
                [
                    {
                        "id": str(node["id"]),
                        "node_key": node["node_key"],
                        "title": node["title"],
                        "node_kind": node["node_kind"],
                    }
                    for node in formal["nodes"]
                ]
                if formal
                else []
            )
            t = tables.material_schedule_bindings
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
                    raise MaterialAllocationError("所选排程影响历史版本不存在")
                selected = _plain(dict(selected_row))
            return {
                "selected": selected,
                "nodes": nodes,
                "history": history,
                "current": observation,
                "baseline_id": str(formal["baseline_id"]) if formal else None,
            }

    def apply(
        self, context: AuthContext, project_id: UUID, exception_id: UUID, command: BindingDraft
    ) -> dict[str, Any]:
        signature = digest(
            {
                "project_id": str(project_id),
                "exception_id": str(exception_id),
                "command": command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as c, localcontext() as arithmetic:
            arithmetic.prec = 2048
            _project(c, context, project_id, write=True)
            _authorize(c, context, project_id, write=True)
            row = _row(c, context.tenant.id, project_id, exception_id)
            t = tables.material_schedule_bindings
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
                    raise MaterialAllocationError("原请求已用于其他排程影响")
                return _plain(dict(prior))
            previous = (
                c.execute(
                    select(t)
                    .where(t.c.tenant_id == context.tenant.id, t.c.exception_id == exception_id)
                    .order_by(t.c.version.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            version = previous["version"] if previous else 0
            if version != command.expected_version or (command.mode == "released" and not previous):
                raise MaterialAllocationError("原排程影响版本已变化，请刷新核对")
            _lock_sources(c, context, project_id, row["build_id"])
            observation = observations(c, context.tenant.id, project_id, [row])[exception_id]
            if (
                observation["source_digest"] != command.source_digest
                or observation["latest_review"]["id"] != str(command.review_id)
                or not observation["review_current"]
            ):
                raise MaterialAllocationError(
                    "当前物料来源尚未具名核对或已变化，请先回到原异常核对"
                )
            if command.mode != "released" and observation["material"] is None:
                raise MaterialAllocationError("当前需求已移除此物料，请明确解除旧影响")
            if command.ready_at and command.ready_at <= datetime.now(UTC):
                raise MaterialAllocationError("预计可用时间已过，请核对实际到货或更新预计依据")
            formal = current_plan(c, context.tenant.id, project_id)
            nodes = {node["id"]: node for node in formal["nodes"]} if formal else {}
            if set(command.node_ids) - set(nodes):
                raise MaterialAllocationError("影响节点须来自当前正式计划")
            snapshot = {
                "policy": POLICY,
                "source_digest": observation["source_digest"],
                "source": observation["core"],
                "review": observation["latest_review"],
                "baseline_id": str(formal["baseline_id"]) if formal else None,
                "nodes": [_plain(nodes[node_id]) for node_id in command.node_ids],
                "previous_id": str(previous["id"]) if previous else None,
            }
            saved = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        exception_id=exception_id,
                        version=version + 1,
                        review_id=command.review_id,
                        mode=command.mode,
                        target_point=command.target_point,
                        node_ids=[str(value) for value in command.node_ids],
                        ready_at=command.ready_at,
                        source_digest=command.source_digest,
                        snapshot=snapshot,
                        reason=command.reason,
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=signature,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            NpiExecutionService._record_change(
                c,
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                record_id=exception_id,
                record_type="material_schedule",
                action="revised",
                before=_plain(dict(previous)) if previous else None,
                after=_plain(dict(saved)),
            )
            return _plain(dict(saved))
