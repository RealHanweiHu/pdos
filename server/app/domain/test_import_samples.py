"""Human resolution of missing report samples using the original NPI lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.npi_execution import (
    NpiConflictError,
    NpiExecutionService,
    NpiNotFoundError,
    NpiScopeError,
    NpiTransitionError,
)
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.sample_configuration_revisions import create_revision
from app.domain.test_import_preview import get_preview, preview_in_connection
from app.domain.test_report_import import TestReportImportService
from app.domain.test_report_workbook import ImportError_
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


@dataclass(frozen=True)
class NewReportSample:
    serial_number: str
    build_id: UUID
    built_date: date
    parent_sample_id: UUID | None = None
    prototype_bom_id: UUID | None = None
    notes: str | None = None


def _authorize(engine: Engine, context: AuthContext, project_id: UUID) -> None:
    TestReportImportService(engine, object_store=None, gateway=None)._authorize_import(
        tenant_id=context.tenant.id,
        actor_user_id=context.user.id,
        project_id=project_id,
        auth_version=context.user.auth_version,
    )


def sample_options(
    engine: Engine, *, context: AuthContext, project_id: UUID, batch_id: UUID, search: str = ""
) -> dict[str, Any]:
    _authorize(engine, context, project_id)
    preview = get_preview(engine, context=context, project_id=project_id, batch_id=batch_id)
    with engine.connect() as c:
        s, b = tables.samples, tables.build_batches
        samples = (
            c.execute(
                select(s)
                .where(
                    s.c.tenant_id == context.tenant.id,
                    s.c.project_id == project_id,
                    s.c.serial_number.contains(search.strip(), autoescape=True),
                )
                .order_by(s.c.serial_number)
                .limit(201)
            )
            .mappings()
            .all()
        )
        count = (
            select(func.count())
            .select_from(s)
            .where(
                s.c.tenant_id == b.c.tenant_id,
                s.c.project_id == b.c.project_id,
                s.c.build_batch_id == b.c.id,
            )
            .correlate(b)
            .scalar_subquery()
        )
        builds = (
            c.execute(
                select(b, count.label("registered_samples"))
                .where(
                    b.c.tenant_id == context.tenant.id,
                    b.c.project_id == project_id,
                )
                .order_by(b.c.created_at.desc())
            )
            .mappings()
            .all()
        )
        boms = (
            c.execute(
                select(tables.development_boms)
                .where(
                    tables.development_boms.c.tenant_id == context.tenant.id,
                    tables.development_boms.c.project_id == project_id,
                    tables.development_boms.c.bom_type == "prototype",
                )
                .order_by(tables.development_boms.c.code, tables.development_boms.c.version.desc())
            )
            .mappings()
            .all()
        )
    return _plain(
        dict(
            samples=[dict(r) for r in samples[:200]],
            more_samples=len(samples) > 200,
            builds=[dict(r) for r in builds],
            prototype_boms=[dict(r) for r in boms],
            digest=preview["digest"],
            can_resolve=preview["can_resolve_samples"],
        )
    )


def resolve_samples(
    engine: Engine,
    *,
    context: AuthContext,
    project_id: UUID,
    batch_id: UUID,
    request_id: UUID,
    expected_digest: str,
    run_ids: tuple[UUID, ...],
    reason: str,
    sample_id: UUID | None,
    new_sample: NewReportSample | None,
) -> dict[str, Any]:
    _authorize(engine, context, project_id)
    if (
        (sample_id is None) == (new_sample is None)
        or not 1 <= len(run_ids) <= 100
        or len(set(run_ids)) != len(run_ids)
        or not 1 <= len(reason.strip()) <= 2000
    ):
        raise ImportError_(
            "IMPORT_SAMPLE_INVALID", "选择已有样机或确认新建，并填写不重复的测试记录与依据"
        )
    if new_sample is not None and (
        not 1 <= len(new_sample.serial_number.strip()) <= 128
        or new_sample.built_date > datetime.now(UTC).date()
    ):
        raise ImportError_("IMPORT_SAMPLE_INVALID", "请填写真实样机编号和已发生的装机日期")
    payload = dict(
        expected_digest=expected_digest,
        run_ids=sorted(str(i) for i in run_ids),
        reason=reason.strip(),
        sample_id=str(sample_id) if sample_id else None,
        new_sample=_plain(vars(new_sample)) if new_sample else None,
        actor=str(context.user.id),
    )
    request_digest = digest(payload)
    receipt = tables.test_import_sample_resolutions
    try:
        with engine.begin() as c:
            if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project_id):
                raise ImportError_("IMPORT_PROJECT_NOT_FOUND", "项目不可用")
            previous = (
                c.execute(
                    select(receipt).where(
                        receipt.c.tenant_id == context.tenant.id,
                        receipt.c.project_id == project_id,
                        receipt.c.batch_id == batch_id,
                        receipt.c.request_id == request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if previous is not None:
                if previous["request_digest"] != request_digest:
                    raise ImportError_(
                        "IMPORT_SAMPLE_CONFLICT", "原样机办理请求内容已不同，请重新核对"
                    )
            else:
                preview = preview_in_connection(
                    c, tenant_id=context.tenant.id, project_id=project_id, batch_id=batch_id
                )
                if not preview["can_resolve_samples"] or preview["digest"] != expected_digest:
                    raise ImportError_(
                        "IMPORT_PREVIEW_CHANGED", "草稿已有变化或停止办理，请刷新后重新核对"
                    )
                by_id = {UUID(i["run"]["id"]): i["run"] for i in preview["items"]}
                selected = [by_id.get(i) for i in run_ids]
                if any(
                    r is None
                    or r["sample_id"] is not None
                    or r["draft_state"] != "draft"
                    or r["sample_configuration_revision_id"] is not None
                    for r in selected
                ):
                    raise ImportError_(
                        "IMPORT_SAMPLE_INVALID", "只能为本批尚未绑定样机的测试草稿补缺"
                    )
                _authorize(engine, context, project_id)
                if new_sample is not None:
                    actual = NpiExecutionService(engine).create_sample_in_connection(
                        c,
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        actor_user_id=context.user.id,
                        build_id=new_sample.build_id,
                        serial_number=new_sample.serial_number.strip(),
                        parent_sample_id=new_sample.parent_sample_id,
                        prototype_bom_id=new_sample.prototype_bom_id,
                        notes=new_sample.notes,
                        built_at=datetime.combine(
                            new_sample.built_date, datetime.min.time(), tzinfo=UTC
                        ),
                        built_at_precision="day",
                    )
                    sample_id = UUID(actual["id"])
                s = tables.samples
                sample = (
                    c.execute(
                        select(s).where(
                            s.c.tenant_id == context.tenant.id,
                            s.c.project_id == project_id,
                            s.c.id == sample_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if sample is None:
                    raise ImportError_("IMPORT_SAMPLE_INVALID", "样机不属于当前项目")
                if sample["built_at_precision"] != "unknown" and any(
                    run is not None
                    and run["executed_at"] is not None
                    and run["execution_time_source"] in {"report", "human"}
                    and datetime.fromisoformat(run["executed_at"]).astimezone(UTC).date()
                    < sample["built_at"].astimezone(UTC).date()
                    for run in selected
                ):
                    raise ImportError_(
                        "IMPORT_SAMPLE_INVALID", "样机装机日期晚于测试日期，请核对真实样机或日期"
                    )
                now, receipt_id = datetime.now(UTC), uuid4()
                c.execute(
                    receipt.insert().values(
                        id=receipt_id,
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        batch_id=batch_id,
                        request_id=request_id,
                        request_digest=request_digest,
                        sample_id=sample["id"],
                        run_ids=[str(i) for i in run_ids],
                        created_sample=new_sample is not None,
                        reason=reason.strip(),
                        created_by_user_id=context.user.id,
                        created_at=now,
                    )
                )
                for run in selected:
                    if run is None:
                        raise ImportError_("IMPORT_SAMPLE_INVALID", "测试草稿缺失")
                    config = run["conditions"].get("report_configuration")
                    revision_id = (
                        create_revision(
                            c,
                            tenant_id=context.tenant.id,
                            project_id=project_id,
                            sample_id=sample["id"],
                            actor_user_id=context.user.id,
                            source="report_extract",
                            snapshot=dict(config),
                            source_document_id=UUID(run["evidence_document_id"]),
                            occurred_at=now,
                        )
                        if isinstance(config, dict) and config
                        else None
                    )
                    c.execute(
                        tables.test_runs.update()
                        .where(
                            tables.test_runs.c.tenant_id == context.tenant.id,
                            tables.test_runs.c.project_id == project_id,
                            tables.test_runs.c.id == UUID(run["id"]),
                        )
                        .values(
                            sample_id=sample["id"],
                            sample_configuration_revision_id=revision_id,
                            conditions={
                                **run["conditions"],
                                "sample_resolution_id": str(receipt_id),
                            },
                            updated_at=now,
                        )
                    )
                EventAuditWriter(
                    c,
                    tenant_id=context.tenant.id,
                    actor_user_id=context.user.id,
                    project_id=project_id,
                ).record(
                    EventDraft(
                        event_id=f"test-import:sample:{receipt_id}",
                        event_type="NPI_RECORD_CHANGED",
                        source="npi_service",
                        entity_id=receipt_id,
                        payload={
                            "record_type": "test_report_import",
                            "action": "sample_resolved",
                        },
                        occurred_at=now,
                    ),
                    AuditDraft(
                        action="test_report_import.resolve_sample",
                        before_snapshot={"run_ids": [str(i) for i in run_ids]},
                        context={"batch_id": str(batch_id)},
                        after_snapshot={
                            "receipt_id": str(receipt_id),
                            "sample_id": str(sample["id"]),
                            "created_sample": new_sample is not None,
                            "reason": reason.strip(),
                        },
                    ),
                )
    except (
        NpiNotFoundError,
        NpiScopeError,
        NpiTransitionError,
        NpiConflictError,
        IntegrityError,
    ) as error:
        raise ImportError_(
            "IMPORT_SAMPLE_CONFLICT",
            "样机编号、批次数量或状态已不适用；请核对已有样机或沿原流程调整批次",
        ) from error
    return get_preview(engine, context=context, project_id=project_id, batch_id=batch_id)
