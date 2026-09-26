"""Read-only comparison of current, immutable-revision and test-bound configurations."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Connection, Engine, func, select

from app.auth.errors import ObjectPermissionDeniedError
from app.auth.project_access import ProjectAccessService, SqlProjectAccessRepository
from app.auth.repository import AuthContext, AuthRepository
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.product_workspace import _plain

SelectionKind = Literal["current", "revision", "test_run"]
FIELDS = {
    "bom_revision": "BOM版本",
    "pcb_version": "PCB",
    "structure_version": "结构",
    "fw_version": "固件",
    "build_date": "装机日期",
    "key_component_suppliers": "关键件供应商",
}


class ConfigurationComparisonError(ValueError):
    pass


def _authorize(engine: Engine, context: AuthContext, project_id: UUID) -> None:
    current = AuthRepository(engine).find_user_context(context.user.id)
    if (
        current is None
        or current.tenant.id != context.tenant.id
        or not current.user.is_active
        or current.tenant.status != "active"
        or current.user.auth_version != context.user.auth_version
    ):
        raise ObjectPermissionDeniedError
    ProjectAccessService(SqlProjectAccessRepository(engine)).authorize(
        context=current, project_id=project_id, action=Action.PRODUCT_ENGINEERING_VIEW
    )


def _sample(c: Connection, tenant_id: UUID, project_id: UUID, sample_id: UUID) -> dict[str, Any]:
    s, b = tables.samples, tables.build_batches
    row = (
        c.execute(
            select(s, b.c.code.label("build_code"), b.c.phase.label("build_phase"))
            .join(
                b,
                (b.c.tenant_id == s.c.tenant_id)
                & (b.c.project_id == s.c.project_id)
                & (b.c.id == s.c.build_batch_id),
            )
            .where(s.c.tenant_id == tenant_id, s.c.project_id == project_id, s.c.id == sample_id)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ConfigurationComparisonError("所选样机不属于当前项目或已不可用")
    return dict(row)


def _revision(
    c: Connection, tenant_id: UUID, project_id: UUID, revision_id: UUID
) -> dict[str, Any]:
    t, u = tables.sample_configuration_revisions, tables.users
    row = (
        c.execute(
            select(t, u.c.display_name.label("created_by_name"))
            .join(u, (u.c.tenant_id == t.c.tenant_id) & (u.c.id == t.c.created_by_user_id))
            .where(t.c.tenant_id == tenant_id, t.c.project_id == project_id, t.c.id == revision_id)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ConfigurationComparisonError("所选配置版本不属于当前项目或已不可用")
    return dict(row)


def _current(
    c: Connection, tenant_id: UUID, project_id: UUID, sample_id: UUID
) -> dict[str, Any] | None:
    t, fw, bom = tables.sample_build_configurations, tables.fw_releases, tables.development_boms
    row = (
        c.execute(
            select(
                t,
                fw.c.version.label("fw_version"),
                bom.c.code.label("bom_code"),
                bom.c.version.label("bom_version"),
            )
            .outerjoin(
                fw,
                (fw.c.tenant_id == t.c.tenant_id)
                & (fw.c.project_id == t.c.project_id)
                & (fw.c.id == t.c.fw_release_id),
            )
            .outerjoin(
                bom,
                (bom.c.tenant_id == t.c.tenant_id)
                & (bom.c.project_id == t.c.project_id)
                & (bom.c.id == t.c.development_bom_id),
            )
            .where(
                t.c.tenant_id == tenant_id, t.c.project_id == project_id, t.c.sample_id == sample_id
            )
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


def _target(
    c: Connection, tenant_id: UUID, project_id: UUID, kind: SelectionKind, item_id: UUID
) -> dict[str, Any]:
    revision, current, run, sample = None, None, None, None
    if kind == "test_run":
        t, case = tables.test_runs, tables.test_cases
        row = (
            c.execute(
                select(t, case.c.title.label("case_title"))
                .join(
                    case,
                    (case.c.tenant_id == t.c.tenant_id)
                    & (case.c.project_id == t.c.project_id)
                    & (case.c.id == t.c.test_case_id),
                )
                .where(t.c.tenant_id == tenant_id, t.c.project_id == project_id, t.c.id == item_id)
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ConfigurationComparisonError("所选测试记录不属于当前项目或已不可用")
        run = dict(row)
        sample = _sample(c, tenant_id, project_id, run["sample_id"]) if run["sample_id"] else None
        revision = (
            _revision(c, tenant_id, project_id, run["sample_configuration_revision_id"])
            if run["sample_configuration_revision_id"]
            else None
        )
    elif kind == "revision":
        revision = _revision(c, tenant_id, project_id, item_id)
        sample = _sample(c, tenant_id, project_id, revision["sample_id"])
    elif kind == "current":
        sample = _sample(c, tenant_id, project_id, item_id)
        current = _current(c, tenant_id, project_id, item_id)
    else:
        raise ConfigurationComparisonError("配置选择类型无效")
    snapshot = revision["snapshot"] if revision is not None else current
    source_document_id = (
        revision["source_document_id"]
        if revision
        else current["source_document_id"]
        if current
        else None
    )
    label = (
        (sample["serial_number"] if sample else "未绑定样机")
        + " · "
        + (
            f"{run['case_title']} 第{run['run_number']}次"
            if run
            else f"配置版本 {revision['revision_number']}"
            if revision
            else "当前配置"
        )
    )
    return dict(
        kind=kind,
        id=item_id,
        label=label,
        sample=sample,
        revision=revision,
        current=current,
        test_run=run,
        snapshot=snapshot,
        missing_configuration=snapshot is None,
        source_document_href=f"/projects?project={project_id}&tab=documents&entity_id={source_document_id}"
        if source_document_id
        else None,
        test_run_href=f"/projects?project={project_id}&tab=quality&test_case_id={run['test_case_id']}&test_run_id={run['id']}"
        if run
        else None,
    )


def _cell(
    value: Any, *, known: bool | None = None, reason: str | None = None, raw: Any = None
) -> dict[str, Any]:
    available = (
        value is not None and value != "" and value != {} and value != []
        if known is None
        else known
    )
    return dict(
        value=value if available else None,
        known=available,
        reason=reason if not available else None,
        raw_value=raw,
    )


def _field(snapshot: dict[str, Any] | None, field: str) -> dict[str, Any]:
    if snapshot is None:
        return _cell(None, reason="当次配置未绑定，不能使用当前值补齐")
    if field == "bom_revision":
        return _cell(
            {
                "id": snapshot["development_bom_id"],
                "code": snapshot.get("bom_code"),
                "version": snapshot.get("bom_version"),
            }
            if snapshot.get("development_bom_id")
            else None,
            reason="未绑定实际配置的BOM版本",
        )
    value = snapshot.get(field)
    if field == "build_date" and value:
        if isinstance(value, datetime):
            value = value.date().isoformat()
        elif isinstance(value, date):
            value = value.isoformat()
        elif isinstance(value, str):
            try:
                value = datetime.fromisoformat(value).date().isoformat()
            except ValueError:
                return _cell(None, reason="原装机日期无法明确解析", raw=value)
    if isinstance(value, str):
        value = value.strip() or None
    return _cell(value, reason="此字段未记录")


def _key(value: Any) -> str:
    # JSON semantics ignore object key order at every nesting level.
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))


def _row(field: str, label: str, cells: list[dict[str, Any]]) -> dict[str, Any]:
    known = [cell["value"] for cell in cells if cell["known"]]
    different = len({_key(v) for v in known}) > 1
    missing = [i for i, cell in enumerate(cells) if not cell["known"]]
    return dict(
        field=field,
        label=label,
        cells=cells,
        differing=different,
        unknown_columns=missing,
        status="different" if different else "incomplete" if missing else "same",
    )


def compare_selected(
    engine: Engine,
    *,
    context: AuthContext,
    project_id: UUID,
    selections: tuple[tuple[SelectionKind, UUID], ...],
) -> dict[str, Any]:
    _authorize(engine, context, project_id)
    if not 2 <= len(selections) <= 10 or len(set(selections)) != len(selections):
        raise ConfigurationComparisonError("请选择2至10个不重复的当前配置、历史版本或测试记录")
    with engine.connect() as c:
        targets = [
            _target(c, context.tenant.id, project_id, kind, item_id) for kind, item_id in selections
        ]
    fields = [
        _row(field, label, [_field(t["snapshot"], field) for t in targets])
        for field, label in FIELDS.items()
        if field != "key_component_suppliers"
    ]
    suppliers = [
        t["snapshot"].get("key_component_suppliers") if t["snapshot"] else None for t in targets
    ]
    keys = sorted({key for value in suppliers if isinstance(value, dict) for key in value})
    supplier_rows = [
        _row(
            key,
            key,
            [
                _cell(
                    value.get(key) if isinstance(value, dict) else None,
                    reason="此关键件供应商未记录",
                )
                for value in suppliers
            ],
        )
        for key in keys
    ]
    supplier_field = _row(
        "key_component_suppliers",
        FIELDS["key_component_suppliers"],
        [_cell(value, reason="未记录关键件供应商") for value in suppliers],
    )
    supplier_field["differing"] = any(r["differing"] for r in supplier_rows)
    supplier_field["unknown_columns"] = sorted(
        {i for r in supplier_rows for i in r["unknown_columns"]}
        | {i for i, v in enumerate(suppliers) if not v}
    )
    supplier_field["status"] = (
        "different"
        if supplier_field["differing"]
        else "incomplete"
        if supplier_field["unknown_columns"]
        else "same"
    )
    fields.append(supplier_field)
    return _plain(
        dict(
            targets=targets,
            fields=fields,
            supplier_rows=supplier_rows,
            differing_fields=[r["field"] for r in fields if r["differing"]],
            incomplete_fields=[r["field"] for r in fields if r["unknown_columns"]],
            missing_configuration_columns=[
                i for i, t in enumerate(targets) if t["missing_configuration"]
            ],
            notice="历史版本与测试仅使用当次绑定的不可变快照；当前配置按本次读取展示。相同只表示所选已知字段一致，不构成测试结论或根因判定。",
        )
    )


def history(
    engine: Engine,
    *,
    context: AuthContext,
    project_id: UUID,
    sample_id: UUID,
    before_number: int | None = None,
) -> dict[str, Any]:
    _authorize(engine, context, project_id)
    if before_number is not None and before_number < 1:
        raise ConfigurationComparisonError("配置版本分页位置无效")
    with engine.connect() as c:
        sample = _sample(c, context.tenant.id, project_id, sample_id)
        r, t, u = tables.sample_configuration_revisions, tables.test_runs, tables.users
        usage = (
            select(func.count())
            .select_from(t)
            .where(
                t.c.tenant_id == r.c.tenant_id,
                t.c.project_id == r.c.project_id,
                t.c.sample_configuration_revision_id == r.c.id,
            )
            .correlate(r)
            .scalar_subquery()
        )
        rows = (
            c.execute(
                select(r, u.c.display_name.label("created_by_name"), usage.label("test_run_count"))
                .join(u, (u.c.tenant_id == r.c.tenant_id) & (u.c.id == r.c.created_by_user_id))
                .where(
                    r.c.tenant_id == context.tenant.id,
                    r.c.project_id == project_id,
                    r.c.sample_id == sample_id,
                    *([r.c.revision_number < before_number] if before_number is not None else []),
                )
                .order_by(r.c.revision_number.desc())
                .limit(26)
            )
            .mappings()
            .all()
        )
        unknown_count = c.execute(
            select(func.count())
            .select_from(t)
            .where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project_id,
                t.c.sample_id == sample_id,
                t.c.sample_configuration_revision_id.is_(None),
            )
        ).scalar_one()
        current = _current(c, context.tenant.id, project_id, sample_id)
        page = [dict(row) for row in rows[:25]]
    return _plain(
        dict(
            sample=sample,
            current=current,
            revisions=page,
            unknown_test_run_count=unknown_count,
            next_before=page[-1]["revision_number"] if len(rows) > 25 else None,
        )
    )


def edit_options(
    engine: Engine, *, context: AuthContext, project_id: UUID, sample_id: UUID
) -> dict[str, Any]:
    from app.auth.roles import is_allowed
    from app.domain.sample_configurations import configuration_edit_digest

    _authorize(engine, context, project_id)
    with engine.connect() as c:
        sample = _sample(c, context.tenant.id, project_id, sample_id)
        current = _current(c, context.tenant.id, project_id, sample_id)
        boms = (
            c.execute(
                select(tables.development_boms)
                .where(
                    tables.development_boms.c.tenant_id == context.tenant.id,
                    tables.development_boms.c.project_id == project_id,
                )
                .order_by(tables.development_boms.c.code, tables.development_boms.c.version.desc())
            )
            .mappings()
            .all()
        )
        firmware = (
            c.execute(
                select(tables.fw_releases)
                .where(
                    tables.fw_releases.c.tenant_id == context.tenant.id,
                    tables.fw_releases.c.project_id == project_id,
                )
                .order_by(tables.fw_releases.c.version)
            )
            .mappings()
            .all()
        )
    return _plain(
        dict(
            sample=sample,
            current=current,
            boms=[dict(row) for row in boms],
            firmware=[dict(row) for row in firmware],
            digest=configuration_edit_digest(sample_id, current),
            can_edit=is_allowed(context.user.role, Action.PRODUCT_ENGINEERING_EDIT),
        )
    )
