"""Human amendments to draft execution facts, before report adoption."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Engine

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.product_workspace import _plain
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.test_import_preview import get_preview, preview_in_connection
from app.domain.test_report_import import TestReportImportService
from app.domain.test_report_workbook import ImportError_
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


@dataclass(frozen=True)
class ExecutionTimeInput:
    run_id: UUID
    executed_at: datetime
    precision: str
    reason: str


def amend_execution_times(
    engine: Engine,
    *,
    context: AuthContext,
    project_id: UUID,
    batch_id: UUID,
    expected_digest: str,
    items: tuple[ExecutionTimeInput, ...],
) -> dict[str, object]:
    service = TestReportImportService(engine, object_store=None, gateway=None)

    def authorize() -> None:
        service._authorize_import(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project_id,
            auth_version=context.user.auth_version,
        )

    authorize()
    now = datetime.now(UTC)
    if not 1 <= len(items) <= 100 or len({i.run_id for i in items}) != len(items):
        raise ImportError_("IMPORT_TIME_INVALID", "请选择不重复的测试记录，每次最多100条")
    for item in items:
        if (
            item.precision not in {"day", "instant"}
            or item.executed_at.tzinfo is None
            or not 1 <= len(item.reason.strip()) <= 2000
            or item.executed_at > now
            or (
                item.precision == "day"
                and item.executed_at.astimezone(UTC).time().isoformat() != "00:00:00"
            )
        ):
            raise ImportError_(
                "IMPORT_TIME_INVALID", "请填写已发生的真实日期或带时区的时间，并说明补录依据"
            )
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project_id):
            raise ImportError_("IMPORT_PROJECT_NOT_FOUND", "项目不可用")
        preview = preview_in_connection(
            c, tenant_id=context.tenant.id, project_id=project_id, batch_id=batch_id
        )
        if preview["batch"]["status"] != "parsed" or preview["batch"]["superseded_by_batch_id"]:
            raise ImportError_(
                "IMPORT_BATCH_NOT_PENDING", "只可补录尚未确认的报告草稿；正式结果请沿业务纠错办理"
            )
        runs = {UUID(r["run"]["id"]): r["run"] for r in preview["items"]}
        changes = []
        for item in items:
            run = runs.get(item.run_id)
            if run is None or run["draft_state"] != "draft":
                raise ImportError_("IMPORT_TIME_INVALID", "目标记录不属于本批待确认草稿")
            input_value = dict(
                executed_at=item.executed_at.astimezone(UTC).isoformat(),
                precision=item.precision,
                reason=item.reason.strip(),
                recorded_by_user_id=str(context.user.id),
            )
            previous = run["conditions"].get("execution_time_input", {})
            if all(previous.get(k) == v for k, v in input_value.items()):
                continue  # An uncertain HTTP response reuses the same human receipt.
            changes.append((run, input_value))
        if changes and preview["digest"] != expected_digest:
            raise ImportError_("IMPORT_PREVIEW_CHANGED", "报告资料已变化，请刷新后重新核对补录值")
        authorize()
        for run, input_value in changes:
            after = {**input_value, "recorded_at": now.isoformat()}
            c.execute(
                tables.test_runs.update()
                .where(
                    tables.test_runs.c.tenant_id == context.tenant.id,
                    tables.test_runs.c.project_id == project_id,
                    tables.test_runs.c.id == UUID(run["id"]),
                )
                .values(
                    executed_at=datetime.fromisoformat(input_value["executed_at"]),
                    execution_time_precision=input_value["precision"],
                    execution_time_source="human",
                    conditions={**run["conditions"], "execution_time_input": after},
                    updated_at=now,
                )
            )
            EventAuditWriter(
                c, tenant_id=context.tenant.id, actor_user_id=context.user.id, project_id=project_id
            ).record(
                EventDraft(
                    event_id=f"test-import:{batch_id}:time:{uuid4()}",
                    event_type="NPI_RECORD_CHANGED",
                    source="npi_service",
                    entity_id=UUID(run["id"]),
                    payload={
                        "record_type": "test_run",
                        "action": "draft_execution_time_amended",
                    },
                    occurred_at=now,
                ),
                AuditDraft(
                    action="test_report_import.amend_execution_time",
                    before_snapshot=_plain(run),
                    after_snapshot=after,
                    context={"batch_id": str(batch_id)},
                ),
            )
    return get_preview(engine, context=context, project_id=project_id, batch_id=batch_id)
