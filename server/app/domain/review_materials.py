"""Server-bound, permission-checked technical material snapshots for review rounds."""

from datetime import date
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Connection, select

from app.auth.roles import Action, Role, is_allowed
from app.contracts.common_objects import Contract, Digest
from app.db.schema import tables
from app.domain.organization import active_delegated_principals
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError, _plain, digest

MaterialKind = Literal["specification", "test_report", "certification"]
KINDS = {
    "specification": (tables.specifications, Action.PRODUCT_ENGINEERING_VIEW),
    "test_report": (tables.test_reports, Action.QUALITY_VIEW),
    "certification": (tables.certifications, Action.QUALITY_VIEW),
}


class MaterialChoice(Contract):
    kind: MaterialKind
    id: UUID
    payload_digest: Digest


def case_project(
    connection: Connection, tenant_id: UUID, case_id: UUID, *, lock: bool = False
) -> Any:
    statement = select(tables.projects).where(
        tables.projects.c.tenant_id == tenant_id, tables.projects.c.development_case_id == case_id
    )
    return (
        connection.execute(statement.with_for_update() if lock else statement)
        .mappings()
        .one_or_none()
    )


def authorize_materials(
    connection: Connection, tenant_id: UUID, case_id: UUID, user_id: UUID, materials: list[Any]
) -> None:
    if not materials:
        return
    project = case_project(connection, tenant_id, case_id)
    user = (
        connection.execute(
            select(tables.users).where(
                tables.users.c.tenant_id == tenant_id,
                tables.users.c.id == user_id,
                tables.users.c.is_active.is_(True),
            )
        )
        .mappings()
        .one_or_none()
    )
    if project is None or user is None:
        raise ProductWorkAccessError("当前人员不能访问评审所引用的项目材料")
    role = Role(user["role"])
    if role not in {Role.OWNER, Role.ADMIN}:
        principals = {
            user_id,
            *active_delegated_principals(connection, tenant_id=tenant_id, delegate_user_id=user_id),
        }
        if (
            connection.execute(
                select(tables.project_members.c.user_id)
                .where(
                    tables.project_members.c.tenant_id == tenant_id,
                    tables.project_members.c.project_id == project["id"],
                    tables.project_members.c.user_id.in_(principals),
                )
                .limit(1)
            ).first()
            is None
        ):
            raise ProductWorkAccessError("当前人员不能访问评审所引用的项目材料")
    for material in materials:
        kind = material["kind"]
        if kind not in KINDS or not is_allowed(role, KINDS[kind][1]):
            raise ProductWorkAccessError("当前人员缺少所选技术材料的读取权限")
        if material.get("project_id") and UUID(str(material["project_id"])) != project["id"]:
            raise ProductWorkAccessError("材料不属于此案例关联项目")


def _bounded_rows(connection: Connection, statement: Any) -> list[dict[str, Any]]:
    rows = list(connection.execute(statement.limit(2001)).mappings())
    if len(rows) > 2000:
        raise ProductWorkError("该报告关联记录超过单轮材料上限，请拆分测试计划后评审")
    return [_plain(row) for row in rows]


def material_snapshot(
    connection: Connection, tenant_id: UUID, project_id: UUID, kind: str, material_id: UUID
) -> dict[str, Any]:
    if kind not in KINDS:
        raise ProductWorkError("不支持此技术材料类型")
    table = KINDS[kind][0]
    row = (
        connection.execute(
            select(table).where(
                table.c.tenant_id == tenant_id,
                table.c.project_id == project_id,
                table.c.id == material_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("技术材料已不存在或不属于本项目")
    snapshot: dict[str, Any] = {"record": _plain(row)}
    if kind == "test_report":
        plan = (
            connection.execute(
                select(tables.test_plans).where(
                    tables.test_plans.c.tenant_id == tenant_id,
                    tables.test_plans.c.project_id == project_id,
                    tables.test_plans.c.id == row["plan_id"],
                )
            )
            .mappings()
            .one()
        )
        snapshot["plan"] = _plain(plan)
        snapshot["test_cases"] = _bounded_rows(
            connection,
            select(tables.test_cases)
            .where(
                tables.test_cases.c.tenant_id == tenant_id,
                tables.test_cases.c.project_id == project_id,
                tables.test_cases.c.plan_id == row["plan_id"],
            )
            .order_by(tables.test_cases.c.id),
        )
        snapshot["test_runs"] = _bounded_rows(
            connection,
            select(tables.test_runs)
            .where(
                tables.test_runs.c.tenant_id == tenant_id,
                tables.test_runs.c.project_id == project_id,
                tables.test_runs.c.test_case_id.in_(
                    [UUID(item["id"]) for item in snapshot["test_cases"]]
                ),
            )
            .order_by(
                tables.test_runs.c.test_case_id,
                tables.test_runs.c.run_number,
                tables.test_runs.c.id,
            ),
        )
    return {
        "kind": kind,
        "id": str(material_id),
        "project_id": str(project_id),
        "snapshot": snapshot,
        "payload_digest": digest(snapshot),
    }


def resolve_materials(
    connection: Connection,
    tenant_id: UUID,
    case_id: UUID,
    choices: list[Any],
    *,
    check_digest: bool = False,
    lock: bool = False,
) -> list[dict[str, Any]]:
    if not choices:
        return []
    project = case_project(connection, tenant_id, case_id, lock=lock)
    if project is None:
        raise ProductWorkError("本案例尚未关联项目，不能引用项目技术材料")
    output = []
    for choice in sorted(choices, key=lambda value: (value["kind"], str(value["id"]))):
        item = material_snapshot(
            connection, tenant_id, project["id"], choice["kind"], UUID(str(choice["id"]))
        )
        if check_digest and item["payload_digest"] != choice["payload_digest"]:
            raise ProductWorkError("所选技术材料已变化，请刷新并重新选择")
        output.append(item)
    return output


def material_blockers(materials: list[dict[str, Any]]) -> list[str]:
    blockers = []
    for material in materials:
        snapshot, kind = material["snapshot"], material["kind"]
        row = snapshot["record"]
        label = row.get("title") or row.get("certificate_type") or "技术材料"
        if kind == "specification" and (
            not row["verification_method"] or not row["acceptance_criteria"]
        ):
            blockers.append(f"{label}缺验证方法或通过判据")
        if kind == "test_report":
            if row["review_status"] != "approved" or row["result"] != "pass":
                blockers.append(f"{label}尚非已审核通过的测试报告")
            if not snapshot["test_cases"] or any(
                item["status"] not in {"passed", "waived"}
                or (item["status"] == "waived" and not item["result_notes"])
                for item in snapshot["test_cases"]
            ):
                blockers.append(f"{label}的测试用例尚未通过或缺少豁免理由")
            latest = {}
            for run in snapshot["test_runs"]:
                if run["draft_state"] == "confirmed":
                    latest[(run["test_case_id"], run["sample_id"])] = run
            if any(
                run["status"] != "passed"
                or any(metric.get("verdict") == "fail" for metric in run["metrics"])
                for run in latest.values()
            ):
                blockers.append(f"{label}的最新确认执行仍未通过")
        if kind == "certification":
            today = date.today()
            if (
                row["status"] != "valid"
                or not row["valid_until"]
                or date.fromisoformat(row["valid_until"]) < today
                or (row["valid_from"] and date.fromisoformat(row["valid_from"]) > today)
            ):
                blockers.append(f"{label}证书当前无效或已过期")
    return blockers


def material_options(
    connection: Connection,
    tenant_id: UUID,
    case_id: UUID,
    user_id: UUID,
    kind: MaterialKind,
    query: str,
) -> dict[str, Any]:
    project = case_project(connection, tenant_id, case_id)
    if project is None:
        return {"items": [], "has_more": False, "project_id": None}
    authorize_materials(connection, tenant_id, case_id, user_id, [{"kind": kind}])
    table = KINDS[kind][0]
    label = table.c.certificate_type if kind == "certification" else table.c.title
    statement = select(table.c.id).where(
        table.c.tenant_id == tenant_id, table.c.project_id == project["id"]
    )
    if query.strip():
        statement = statement.where(label.icontains(query.strip(), autoescape=True))
    ids = list(
        connection.execute(
            statement.order_by(table.c.updated_at.desc(), table.c.id).limit(51)
        ).scalars()
    )
    items = []
    for material_id in ids[:50]:
        material = material_snapshot(connection, tenant_id, project["id"], kind, material_id)
        row = material["snapshot"]["record"]
        items.append(
            {
                "kind": kind,
                "id": str(material_id),
                "project_id": str(project["id"]),
                "title": row.get("title") or row["certificate_type"],
                "payload_digest": material["payload_digest"],
                "summary": row.get("summary")
                or row.get("acceptance_criteria")
                or row.get("certificate_number"),
                "blockers": material_blockers([material]),
            }
        )
    return {"items": items, "has_more": len(ids) > 50, "project_id": str(project["id"])}
