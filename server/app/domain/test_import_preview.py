"""Version-bound previews for the existing deterministic report confirmation path."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, or_, select

from app.auth.errors import ObjectPermissionDeniedError
from app.auth.project_access import ProjectAccessService, SqlProjectAccessRepository
from app.auth.repository import AuthContext, AuthRepository
from app.auth.roles import Action, is_allowed
from app.db.schema import tables
from app.domain.product_workspace import _plain, digest
from app.domain.test_report_workbook import ImportError_


def authorize_preview(engine: Engine, context: AuthContext, project_id: UUID) -> None:
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


def preview_in_connection(
    c: Connection, *, tenant_id: UUID, project_id: UUID, batch_id: UUID
) -> dict[str, Any]:
    batch = (
        c.execute(
            select(tables.test_report_import_batches).where(
                tables.test_report_import_batches.c.tenant_id == tenant_id,
                tables.test_report_import_batches.c.project_id == project_id,
                tables.test_report_import_batches.c.id == batch_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if batch is None:
        raise ImportError_("IMPORT_BATCH_NOT_FOUND", "导入批次不存在")
    document = (
        c.execute(
            select(tables.documents).where(
                tables.documents.c.tenant_id == tenant_id,
                tables.documents.c.project_id == project_id,
                tables.documents.c.id == batch["document_id"],
            )
        )
        .mappings()
        .one_or_none()
    )
    plan = (
        c.execute(
            select(tables.test_plans).where(
                tables.test_plans.c.tenant_id == tenant_id,
                tables.test_plans.c.project_id == project_id,
                tables.test_plans.c.id == batch["plan_id"],
            )
        )
        .mappings()
        .one_or_none()
    )
    if document is None or plan is None:
        raise ImportError_("IMPORT_SOURCE_UNAVAILABLE", "报告或目标计划已不可用")
    run_ids = [UUID(value) for value in batch["created_run_ids"]]
    runs = (
        c.execute(
            select(tables.test_runs)
            .where(
                tables.test_runs.c.tenant_id == tenant_id,
                tables.test_runs.c.project_id == project_id,
                tables.test_runs.c.id.in_(run_ids),
            )
            .order_by(tables.test_runs.c.test_case_id, tables.test_runs.c.run_number)
        )
        .mappings()
        .all()
    )
    if len(runs) != len(run_ids) or len(set(run_ids)) != len(run_ids):
        raise ImportError_("IMPORT_SOURCE_UNAVAILABLE", "批次测试记录不完整，请先核对")
    cases = {
        r["id"]: r
        for r in c.execute(
            select(tables.test_cases).where(
                tables.test_cases.c.tenant_id == tenant_id,
                tables.test_cases.c.project_id == project_id,
                tables.test_cases.c.plan_id == batch["plan_id"],
                tables.test_cases.c.id.in_([r["test_case_id"] for r in runs]),
            )
        ).mappings()
    }
    sample_ids = [r["sample_id"] for r in runs if r["sample_id"] is not None]
    samples = {
        r["id"]: r
        for r in c.execute(
            select(tables.samples).where(
                tables.samples.c.tenant_id == tenant_id,
                tables.samples.c.project_id == project_id,
                tables.samples.c.id.in_(sample_ids),
            )
        ).mappings()
    }
    configs = {
        r["sample_id"]: r
        for r in c.execute(
            select(tables.sample_build_configurations).where(
                tables.sample_build_configurations.c.tenant_id == tenant_id,
                tables.sample_build_configurations.c.project_id == project_id,
                tables.sample_build_configurations.c.sample_id.in_(sample_ids),
            )
        ).mappings()
    }
    revisions = {
        r["id"]: r
        for r in c.execute(
            select(tables.sample_configuration_revisions).where(
                tables.sample_configuration_revisions.c.tenant_id == tenant_id,
                tables.sample_configuration_revisions.c.project_id == project_id,
                tables.sample_configuration_revisions.c.id.in_(
                    [
                        r["sample_configuration_revision_id"]
                        for r in runs
                        if r["sample_configuration_revision_id"]
                    ]
                ),
            )
        ).mappings()
    }
    time_actor_ids = {
        (r["conditions"] or {}).get("execution_time_input", {}).get("recorded_by_user_id")
        for r in runs
    } - {None}
    time_actors = {
        str(r["id"]): r["display_name"]
        for r in c.execute(
            select(tables.users.c.id, tables.users.c.display_name).where(
                tables.users.c.tenant_id == tenant_id,
                tables.users.c.id.in_([UUID(str(v)) for v in time_actor_ids]),
            )
        ).mappings()
    }
    resolution_rows = (
        c.execute(
            select(
                tables.test_import_sample_resolutions,
                tables.users.c.display_name.label("resolved_by_name"),
            )
            .join(
                tables.users,
                (tables.users.c.tenant_id == tables.test_import_sample_resolutions.c.tenant_id)
                & (tables.users.c.id == tables.test_import_sample_resolutions.c.created_by_user_id),
            )
            .where(
                tables.test_import_sample_resolutions.c.tenant_id == tenant_id,
                tables.test_import_sample_resolutions.c.project_id == project_id,
                tables.test_import_sample_resolutions.c.batch_id == batch_id,
            )
        )
        .mappings()
        .all()
    )
    resolutions = {run_id: dict(row) for row in resolution_rows for run_id in row["run_ids"]}
    build_ids = [row["build_batch_id"] for row in samples.values()]
    reported_build_codes = {
        hint["code"]
        for run in runs
        for hint in (run["conditions"] or {}).get("report_source", {}).get("build_hints", [])
        if hint.get("code")
    }
    builds = {
        row["id"]: dict(row)
        for row in c.execute(
            select(tables.build_batches).where(
                tables.build_batches.c.tenant_id == tenant_id,
                tables.build_batches.c.project_id == project_id,
                or_(
                    tables.build_batches.c.id.in_(build_ids),
                    tables.build_batches.c.code.in_(reported_build_codes),
                ),
            )
        ).mappings()
    }
    mappings = batch["mapping_snapshot"] or batch["proposed_mapping"]
    if mappings is None and batch["mapping_version_id"] is not None:
        mappings = c.execute(
            select(tables.import_mapping_versions.c.mapping).where(
                tables.import_mapping_versions.c.tenant_id == tenant_id,
                tables.import_mapping_versions.c.id == batch["mapping_version_id"],
            )
        ).scalar_one_or_none()
    blockers: list[str] = []
    if batch["superseded_by_batch_id"] is not None:
        blockers.append("此批次已有重解析版本，请转入后续版本核对；原草稿仅保留追溯")
    if not runs:
        blockers.append("没有可确认测试记录，请核对跳过说明及原报告缺项")
    items = []
    for run in runs:
        case = cases.get(run["test_case_id"])
        if case is None:
            blockers.append("测试记录的目标用例已不属于本计划")
        elif case["status"] == "waived":
            blockers.append(f"用例“{case['title']}”已豁免，请重新处理报告")
        if run["evidence_document_id"] != document["id"]:
            blockers.append("测试记录的原始证据已变化")
        if batch["status"] == "parsed" and run["draft_state"] != "draft":
            blockers.append("批次中有记录已单独改变确认状态")
        if batch["status"] == "parsed" and (
            run["executed_at"] is None
            or run["executed_at"] > datetime.now(UTC)
            or run["execution_time_source"] not in {"report", "human"}
            or run["execution_time_precision"] == "unknown"
        ):
            blockers.append(
                f"第{run['run_number']}次“{case['title'] if case else '未知用例'}”"
                "需补录已发生的真实测试日期或时间"
            )
        if batch["status"] == "parsed" and run["sample_id"] is None:
            blockers.append(f"第{run['run_number']}次测试尚未绑定实际样机，请先复用或补齐建档")
        source = (run["conditions"] or {}).get("report_source", {})
        revision = revisions.get(run["sample_configuration_revision_id"])
        time_input = (run["conditions"] or {}).get("execution_time_input", {})
        config = configs.get(run["sample_id"])
        sample = samples.get(run["sample_id"])
        if (
            batch["status"] == "parsed"
            and sample is not None
            and sample["built_at_precision"] != "unknown"
            and run["executed_at"] is not None
            and run["execution_time_source"] in {"report", "human"}
            and run["executed_at"].astimezone(UTC).date()
            < sample["built_at"].astimezone(UTC).date()
        ):
            blockers.append(f"第{run['run_number']}次测试日期早于已确认装机日期，请核对真实日期")
        items.append(
            dict(
                run=dict(run),
                case=dict(case) if case is not None else None,
                sample=dict(sample) if sample is not None else None,
                build=builds.get(sample["build_batch_id"]) if sample is not None else None,
                report_build_hints=[
                    {
                        **hint,
                        "matches": [
                            {
                                key: build[key]
                                for key in ("id", "code", "phase", "purpose", "status")
                            }
                            for build in sorted(
                                builds.values(), key=lambda row: (row["phase"], str(row["id"]))
                            )
                            if hint.get("code") and build["code"] == hint["code"]
                        ],
                    }
                    for hint in source.get("build_hints", [])
                ],
                sample_resolution=resolutions.get(str(run["id"])),
                report_sample_serial=(run["conditions"] or {}).get("report_sample_serial"),
                source=source,
                configuration_revision=dict(revision) if revision is not None else None,
                execution_time_recorded_by_name=time_actors.get(
                    time_input.get("recorded_by_user_id")
                ),
                current_sample_configuration=dict(config) if config is not None else None,
                configuration_from_this_report=bool(
                    revision
                    and revision["source"] == "report_extract"
                    and revision["source_document_id"] == document["id"]
                ),
                execution_time_precision=run["execution_time_precision"],
                href=f"/projects?project={project_id}&tab=quality&test_case_id={run['test_case_id']}&test_run_id={run['id']}",
            )
        )
    confirmer = (
        c.execute(
            select(tables.users.c.display_name).where(
                tables.users.c.tenant_id == tenant_id,
                tables.users.c.id == batch["confirmed_by_user_id"],
            )
        ).scalar_one_or_none()
        if batch["confirmed_by_user_id"] is not None
        else None
    )
    reviser = (
        c.execute(
            select(tables.users.c.display_name).where(
                tables.users.c.tenant_id == tenant_id,
                tables.users.c.id == batch["created_by_user_id"],
            )
        ).scalar_one_or_none()
        if batch["parent_batch_id"] is not None
        else None
    )
    body = _plain(
        dict(
            confirmed_by_name=confirmer,
            mapping_revised_by_name=reviser,
            batch=dict(batch),
            plan=dict(plan),
            document={
                k: document[k]
                for k in ("id", "filename", "sha256", "classification", "size_bytes", "created_at")
            },
            mapping=mappings,
            items=items,
            skipped_rows=batch["skipped_rows"],
            blockers=list(dict.fromkeys(blockers)),
            can_confirm=batch["status"] == "parsed" and not blockers,
            can_amend_execution_times=batch["status"] == "parsed"
            and batch["superseded_by_batch_id"] is None,
            can_resolve_samples=batch["status"] == "parsed"
            and batch["superseded_by_batch_id"] is None,
            can_reparse=batch["status"] == "parsed" and batch["superseded_by_batch_id"] is None,
        )
    )
    return body | {"digest": digest(body)}


def get_preview(
    engine: Engine, *, context: AuthContext, project_id: UUID, batch_id: UUID
) -> dict[str, Any]:
    authorize_preview(engine, context, project_id)
    with engine.connect() as c:
        body = preview_in_connection(
            c, tenant_id=context.tenant.id, project_id=project_id, batch_id=batch_id
        )
        body["can_confirm"] = body["can_confirm"] and is_allowed(
            context.user.role, Action.PRODUCT_ENGINEERING_EDIT
        )
        body["can_amend_execution_times"] = body["can_amend_execution_times"] and is_allowed(
            context.user.role, Action.PRODUCT_ENGINEERING_EDIT
        )
        body["can_reparse"] = body["can_reparse"] and is_allowed(
            context.user.role, Action.PRODUCT_ENGINEERING_EDIT
        )
        body["can_resolve_samples"] = body["can_resolve_samples"] and is_allowed(
            context.user.role, Action.PRODUCT_ENGINEERING_EDIT
        )
        return body
