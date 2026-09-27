"""Excel test-report AI import pipeline (vNext V1-B10, D36).

Engineers keep writing their own Excel test reports; PDOS reads them. The
model only proposes a COLUMN MAPPING for an unseen template — row data is
always extracted deterministically by applying that mapping in code. Confirmed
mappings are versioned per template fingerprint, so a template is calibrated
once and every later upload of it imports with zero model calls.

Runs land as `draft` rows (D32 free zone) and only sync their parent test
cases when a human confirms the batch.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, RowMapping, select, text

from app.ai.budget_ledger import BudgetLedgerError
from app.ai.call_identity import ModelCallSlot, model_call_id
from app.ai.gateway import GatewayInvocation, StructuredModelGateway
from app.ai.import_mapping_runs import ImportMappingRunError, ImportMappingRunStore
from app.ai.model_catalog import AgentTier
from app.ai.runtime_contract import AgentKey
from app.auth.errors import ObjectPermissionDeniedError
from app.auth.project_access import ProjectAccessService, SqlProjectAccessRepository
from app.auth.repository import AuthRepository
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.documents import DocumentRecord, DocumentService, extract_document
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.sample_configuration_revisions import create_revision
from app.domain.test_report_workbook import ImportError_ as ImportError_
from app.domain.test_report_workbook import ParsedWorkbook, parse_workbook
from app.domain.test_runs import sync_case_with_run_result
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft
from app.storage.documents import DocumentObjectStore

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "ai" / "prompts" / "test_report_import_v1.json"
_MAX_SAMPLE_ROWS_FOR_MODEL = 5


class ImportPromptFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    agent_key: AgentKey
    system_prompt: str
    instruction: str


IMPORT_PROMPT = ImportPromptFile.model_validate_json(_PROMPT_PATH.read_text())


class MetricColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    unit: str | None = Field(default=None, max_length=32)


class ExcelImportMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_title_column: str = Field(min_length=1, max_length=128)
    sample_serial_column: str | None = Field(default=None, max_length=128)
    result_column: str = Field(min_length=1, max_length=128)
    notes_column: str | None = Field(default=None, max_length=128)
    metric_columns: list[MetricColumn] = Field(default_factory=list, max_length=50)
    pcb_version_column: str | None = Field(default=None, max_length=128)
    structure_version_column: str | None = Field(default=None, max_length=128)
    fw_version_column: str | None = Field(default=None, max_length=128)
    build_date_column: str | None = Field(default=None, max_length=128)
    pass_values: list[str] = Field(default_factory=list, max_length=20)
    fail_values: list[str] = Field(default_factory=list, max_length=20)
    confidence: float = Field(ge=0, le=1)
    unmapped_headers: list[str] = Field(default_factory=list, max_length=50)


@dataclass(frozen=True)
class ImportRevision:
    parent_batch_id: UUID
    request_id: UUID
    request_digest: str
    reason: str


@dataclass(frozen=True)
class ImportBatchResult:
    id: UUID
    project_id: UUID
    plan_id: UUID
    document_id: UUID
    template_fingerprint: str
    mapping_source: str
    status: str
    confidence: float | None
    created_run_ids: tuple[UUID, ...]
    skipped_rows: tuple[dict[str, object], ...]
    reused_existing: bool = False


def mapping_request(
    *, report: ParsedWorkbook, actor_user_id: UUID, plan_id: UUID, content_sha256: str
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    # Fixed keys only: the gateway projection drops free-form keys such as header names,
    # so each cell carries its column instead of being keyed by it.
    model_context = {
        "report_mapping": {
            "headers": [{"column": header} for header in report.headers],
            "sample_rows": [
                {
                    "row": row.source["row"],
                    "cells": [
                        {"column": header, "value": _normalize(row.values.get(header))}
                        for header in report.headers
                    ],
                }
                for row in report.rows[:_MAX_SAMPLE_ROWS_FOR_MODEL]
            ],
            "total_rows": len(report.rows),
        }
    }

    def digest(value: object) -> str:
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    request_id = "report-mapping.v1:" + digest(
        {
            "actor_user_id": str(actor_user_id),
            "plan_id": str(plan_id),
            "file_sha256": content_sha256,
        }
    )
    request_context = {
        "plan_id": str(plan_id),
        "file_sha256": content_sha256,
        "input_projection_sha256": digest(model_context),
        "prompt_version": IMPORT_PROMPT.version,
        "prompt_sha256": digest(IMPORT_PROMPT.model_dump(mode="json")),
        "output_schema_sha256": digest(ExcelImportMapping.model_json_schema()),
    }
    return request_id, request_context, model_context


def _normalize(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _fingerprint(headers: list[str]) -> str:
    return hashlib.sha256("|".join(header.lower() for header in headers).encode()).hexdigest()


def _apply_mapping(
    mapping: ExcelImportMapping,
    rows: list[dict[str, object]],
    *,
    report: ParsedWorkbook | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, object]]]:
    extracted: list[dict[str, Any]] = []
    skipped: list[dict[str, object]] = []
    pass_values = {value.strip().lower() for value in mapping.pass_values}
    fail_values = {value.strip().lower() for value in mapping.fail_values}
    for index, row in enumerate(rows, start=2):
        source = report.rows[index - 2].source if report is not None else {"row": index}

        def skip(reason: str, *, source: dict[str, Any] = source, **extra: object) -> None:
            skipped.append(
                {
                    "row": source["row"],
                    "sheet": source.get("sheet"),
                    "reason": reason,
                    **extra,
                    "source": source,
                }
            )

        title = _normalize(row.get(mapping.case_title_column))
        result_raw = _normalize(row.get(mapping.result_column)).lower()
        if not title:
            skip("missing_case_title")
            continue
        if result_raw in {
            "参考",
            "reference",
            "不适用",
            "n/a",
            "na",
            "not applicable",
            "未测试",
            "not tested",
            "",
        }:
            skip("non_decisive_result", value=result_raw)
            continue
        if result_raw in pass_values and result_raw in fail_values:
            skip("ambiguous_result_mapping", value=result_raw)
            continue
        if (
            report is not None
            and report.layout == "test_form_v1"
            and not source.get("has_observations")
        ):
            skip("missing_observations", value=result_raw)
            continue
        if result_raw in pass_values:
            status = "passed"
        elif result_raw in fail_values:
            status = "failed"
        else:
            skip("unknown_result_value", value=result_raw)
            continue
        metrics = []
        for metric in mapping.metric_columns:
            value = row.get(metric.column)
            if value is None or _normalize(value) == "":
                continue
            metrics.append({"name": metric.name, "value": value, "unit": metric.unit})
        config: dict[str, str] = {}
        for key, column in (
            ("pcb_version", mapping.pcb_version_column),
            ("structure_version", mapping.structure_version_column),
            ("fw_version", mapping.fw_version_column),
            ("build_date", mapping.build_date_column),
        ):
            if column:
                value = _normalize(row.get(column))
                if value:
                    config[key] = value
        extracted.append(
            {
                "row": source["row"],
                "source": source,
                "case_title": title,
                "sample_serial": (
                    _normalize(row.get(mapping.sample_serial_column))
                    if mapping.sample_serial_column
                    else ""
                ),
                "status": status,
                "metrics": metrics,
                "notes": (
                    _normalize(row.get(mapping.notes_column)) or None
                    if mapping.notes_column
                    else None
                ),
                "config": config,
            }
        )
    return extracted, skipped


class TestReportImportService:
    def __init__(
        self,
        engine: Engine,
        *,
        # Only the parse path needs these; confirm is a zero-model,
        # deterministic step and is constructed without them (V1-B10).
        object_store: DocumentObjectStore | None,
        gateway: StructuredModelGateway | None,
    ) -> None:
        self._engine = engine
        self._object_store = object_store
        self._gateway = gateway

    def _latest_confirmed_mapping(
        self, connection: Connection, *, tenant_id: UUID, fingerprint: str
    ) -> RowMapping | None:
        return (
            connection.execute(
                select(tables.import_mapping_versions)
                .where(
                    tables.import_mapping_versions.c.tenant_id == tenant_id,
                    tables.import_mapping_versions.c.template_fingerprint == fingerprint,
                    tables.import_mapping_versions.c.superseded_by_id.is_(None),
                )
                .order_by(tables.import_mapping_versions.c.version.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )

    def _authorize_import(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        auth_version: int | None = None,
    ) -> int:
        context = AuthRepository(self._engine).find_user_context(actor_user_id)
        try:
            if (
                context is None
                or context.tenant.id != tenant_id
                or context.tenant.status != "active"
                or not context.user.is_active
                or (auth_version is not None and context.user.auth_version != auth_version)
            ):
                raise ObjectPermissionDeniedError
            ProjectAccessService(SqlProjectAccessRepository(self._engine)).authorize(
                context=context, project_id=project_id, action=Action.PRODUCT_ENGINEERING_EDIT
            )
        except ObjectPermissionDeniedError as error:
            raise ImportError_(
                "IMPORT_ACCESS_DENIED", "import access is no longer available"
            ) from error
        return context.user.auth_version

    def start_import(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        plan_id: UUID,
        filename: str,
        content: bytes,
        auth_version: int | None = None,
        queued_run_id: UUID | None = None,
        queued_mapping: ExcelImportMapping | None = None,
    ) -> ImportBatchResult:
        # Serialize identical uploads without holding a project/business row lock
        # across model I/O. The advisory-only transaction writes no business rows.
        with self._engine.begin() as guard:
            guard.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {
                    "key": f"pdos-import-request:{tenant_id}:{project_id}:{plan_id}:"
                    f"{hashlib.sha256(content).hexdigest()}",
                },
            )
            return self._start_import_serialized(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
                plan_id=plan_id,
                filename=filename,
                content=content,
                auth_version=auth_version,
                queued_run_id=queued_run_id,
                queued_mapping=queued_mapping,
            )

    def _start_import_serialized(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        plan_id: UUID,
        filename: str,
        content: bytes,
        auth_version: int | None,
        queued_run_id: UUID | None = None,
        queued_mapping: ExcelImportMapping | None = None,
    ) -> ImportBatchResult:
        if self._object_store is None or self._gateway is None:
            raise RuntimeError("parsing a report needs an object store and a model gateway")
        auth_version = self._authorize_import(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            project_id=project_id,
            auth_version=auth_version,
        )
        with self._engine.connect() as connection:
            if (
                connection.execute(
                    select(tables.projects.c.id).where(
                        tables.projects.c.tenant_id == tenant_id, tables.projects.c.id == project_id
                    )
                ).first()
                is None
            ):
                raise ImportError_("IMPORT_PROJECT_NOT_FOUND", "project was not found")
            if (
                connection.execute(
                    select(tables.test_plans.c.id).where(
                        tables.test_plans.c.tenant_id == tenant_id,
                        tables.test_plans.c.project_id == project_id,
                        tables.test_plans.c.id == plan_id,
                    )
                ).first()
                is None
            ):
                raise ImportError_("IMPORT_PLAN_NOT_FOUND", "test plan was not found")
            existing = self._existing_import(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                plan_id=plan_id,
                content=content,
            )
            if existing is not None:
                if queued_run_id is not None:
                    from app.ai.report_queue_receipts import complete_import

                    with self._engine.begin() as completed:
                        complete_import(
                            completed,
                            self._gateway,
                            tenant_id=tenant_id,
                            run_id=queued_run_id,
                            batch_id=existing.id,
                        )
                return existing
            # Validate the upload before any model egress. Persistence stays in
            # the final transaction, so failed imports still leave no document.
            extract_document(filename=filename, content=content)
            report = parse_workbook(content)
            fingerprint = _fingerprint(
                report.headers if report.layout == "flat_v1" else [report.layout, *report.headers]
            )
            needs_model = (
                report.layout != "test_form_v1"
                and self._latest_confirmed_mapping(
                    connection, tenant_id=tenant_id, fingerprint=fingerprint
                )
                is None
            )
        self._authorize_import(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            project_id=project_id,
            auth_version=auth_version,
        )
        prepared_mapping = queued_mapping or (
            self._suggest_mapping(
                tenant_id=tenant_id,
                project_id=project_id,
                report=report,
                actor_user_id=actor_user_id,
                plan_id=plan_id,
                content_sha256=hashlib.sha256(content).hexdigest(),
                auth_version=auth_version,
            )
            if needs_model
            else None
        )
        self._authorize_import(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            project_id=project_id,
            auth_version=auth_version,
        )
        document: DocumentRecord | None = None
        try:
            with self._engine.begin() as connection:
                # Serialize lookup and creation, including file persistence, with confirmations.
                if not lock_project_write_scope(
                    connection, tenant_id=tenant_id, project_id=project_id
                ):
                    raise ImportError_("IMPORT_PROJECT_NOT_FOUND", "project was not found")
                self._authorize_import(
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    project_id=project_id,
                    auth_version=auth_version,
                )
                if queued_run_id is not None:
                    from app.ai.report_queue_receipts import require_import_lease

                    require_import_lease(connection, self._gateway, tenant_id, queued_run_id)
                plan = (
                    connection.execute(
                        select(tables.test_plans).where(
                            tables.test_plans.c.tenant_id == tenant_id,
                            tables.test_plans.c.project_id == project_id,
                            tables.test_plans.c.id == plan_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if plan is None:
                    raise ImportError_("IMPORT_PLAN_NOT_FOUND", "test plan was not found")
                existing = self._existing_import(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    plan_id=plan_id,
                    content=content,
                )
                if existing is not None:
                    if queued_run_id is not None:
                        from app.ai.report_queue_receipts import complete_import

                        complete_import(
                            connection,
                            self._gateway,
                            tenant_id=tenant_id,
                            run_id=queued_run_id,
                            batch_id=existing.id,
                        )
                    return existing
                document = DocumentService(self._engine, object_store=self._object_store).analyze(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    actor_user_id=actor_user_id,
                    filename=filename,
                    classification="internal",
                    content=content,
                    connection=connection,
                )
                result = self._parse_import(
                    connection,
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    project_id=project_id,
                    plan_id=plan_id,
                    plan=plan,
                    document=document,
                    content=content,
                    prepared_mapping=prepared_mapping,
                )
                if queued_run_id is not None:
                    from app.ai.report_queue_receipts import complete_import

                    complete_import(
                        connection,
                        self._gateway,
                        tenant_id=tenant_id,
                        run_id=queued_run_id,
                        batch_id=result.id,
                    )
                return result
        except Exception:
            if document is not None:
                # The document and batch now share a transaction; discard staged bytes on failure.
                with suppress(Exception):
                    self._object_store.delete(
                        object_key=(
                            f"tenants/{tenant_id}/projects/{project_id}/documents/"
                            f"{document.id}/{document.filename}"
                        )
                    )
            raise

    def _existing_import(
        self,
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        plan_id: UUID,
        content: bytes,
    ) -> ImportBatchResult | None:
        batch = tables.test_report_import_batches
        doc = tables.documents
        existing = (
            connection.execute(
                select(batch)
                .join(
                    doc,
                    (doc.c.id == batch.c.document_id)
                    & (doc.c.tenant_id == batch.c.tenant_id)
                    & (doc.c.project_id == batch.c.project_id),
                )
                .where(
                    batch.c.tenant_id == tenant_id,
                    batch.c.project_id == project_id,
                    batch.c.plan_id == plan_id,
                    batch.c.status.in_(["parsed", "confirmed"]),
                    batch.c.superseded_by_batch_id.is_(None),
                    doc.c.sha256 == hashlib.sha256(content).hexdigest(),
                )
                # Preserve legacy duplicates; prefer an adopted batch, then the oldest.
                .order_by((batch.c.status == "confirmed").desc(), batch.c.created_at, batch.c.id)
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            return ImportBatchResult(
                id=existing["id"],
                project_id=project_id,
                plan_id=plan_id,
                document_id=existing["document_id"],
                template_fingerprint=existing["template_fingerprint"],
                mapping_source=existing["mapping_source"],
                status=existing["status"],
                confidence=dict(existing["parse_confidence"]).get("mapping_confidence"),
                created_run_ids=tuple(UUID(value) for value in existing["created_run_ids"]),
                skipped_rows=tuple(dict(item) for item in existing["skipped_rows"]),
                reused_existing=True,
            )
        return None

    def _suggest_mapping(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        report: ParsedWorkbook,
        actor_user_id: UUID,
        plan_id: UUID,
        content_sha256: str,
        auth_version: int | None = None,
        queue_worker: bool = False,
    ) -> ExcelImportMapping:
        request_id, request_context, model_context = mapping_request(
            report=report,
            actor_user_id=actor_user_id,
            plan_id=plan_id,
            content_sha256=content_sha256,
        )
        sample_rows = [
            {cell["column"]: cell["value"] for cell in row["cells"]}
            for row in model_context["report_mapping"]["sample_rows"]
        ]
        store = ImportMappingRunStore(self._engine, gateway=self._gateway)
        try:
            run, created = store.start(
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                request_id=request_id,
                auth_version=auth_version,
                request_context=request_context,
                claim_queue=queue_worker,
            )
        except BudgetLedgerError as error:
            raise ImportError_(
                "IMPORT_ACCESS_DENIED"
                if error.code == "APPLICATION_AUTHORIZATION_DENIED"
                else "IMPORT_MODEL_UNAVAILABLE",
                "当前请求无法获得运行授权",
            ) from error
        except ImportMappingRunError as error:
            raise ImportError_(
                str(error), "original mapping request is in progress or conflicts"
            ) from error
        if not created:
            if run["status"] != "succeeded" or run["run_context"].get("mapping_result") is None:
                raise ImportError_(
                    "IMPORT_MODEL_UNAVAILABLE",
                    "original mapping request is unavailable; use a confirmed template",
                )
            return ExcelImportMapping.model_validate(run["run_context"]["mapping_result"])
        assert self._gateway is not None
        finished = False
        try:
            from app.ai.application_domain_context import record

            record(
                self._engine,
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run["id"],
                model_call_id=model_call_id(run["id"], ModelCallSlot.REPORT_MAPPING),
                purpose="report_mapping",
                context=model_context,
                snapshot=dict(
                    request=run["run_context"]["mapping_request"],
                    headers=report.headers,
                    sample_rows=sample_rows,
                    total_rows=len(report.rows),
                ),
            )
            result = self._gateway.invoke_structured(
                GatewayInvocation(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    run_id=run["id"],
                    model_call_id=model_call_id(run["id"], ModelCallSlot.REPORT_MAPPING),
                    agent_key=IMPORT_PROMPT.agent_key,
                    agent_tier=AgentTier.DEFAULT,
                    prompt_version=IMPORT_PROMPT.version,
                    system_prompt=IMPORT_PROMPT.system_prompt,
                    instruction=IMPORT_PROMPT.instruction,
                    context=model_context,
                ),
                ExcelImportMapping,
            )
            mapping = result.output if result.status == "succeeded" else None
            store.finish(
                tenant_id=tenant_id,
                run_id=run["id"],
                mapping=mapping.model_dump(mode="json") if mapping is not None else None,
                error_code=(result.error_code or "IMPORT_MODEL_UNAVAILABLE")
                if mapping is None
                else None,
                invocation_id=result.invocation_id,
            )
            finished = True
            if mapping is None:
                raise ImportError_(
                    "IMPORT_MODEL_UNAVAILABLE",
                    "original mapping request is unavailable; use a confirmed template",
                )
            return mapping
        except BudgetLedgerError as error:
            store.finish(
                tenant_id=tenant_id,
                run_id=run["id"],
                mapping=None,
                error_code=error.code,
            )
            raise ImportError_(
                "IMPORT_MODEL_UNAVAILABLE", "original mapping context is unavailable"
            ) from error
        except Exception:
            if not finished:
                with suppress(Exception):
                    store.finish(
                        tenant_id=tenant_id,
                        run_id=run["id"],
                        mapping=None,
                        error_code="IMPORT_MAPPING_REQUEST_FAILED",
                    )
            raise

    def _parse_import(
        self,
        connection: Connection,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        plan_id: UUID,
        plan: RowMapping,
        document: DocumentRecord,
        content: bytes,
        prepared_mapping: ExcelImportMapping | None,
        corrected_mapping: ExcelImportMapping | None = None,
        revision: ImportRevision | None = None,
    ) -> ImportBatchResult:
        report = parse_workbook(content)
        headers = report.headers
        rows = [row.values for row in report.rows]
        fingerprint = _fingerprint(
            headers if report.layout == "flat_v1" else [report.layout, *headers]
        )
        occurred_at = datetime.now(UTC)
        batch_id = uuid4()
        excluded_titles = {
            item["title"].strip(): item["exclusion_reason"]
            for item in (plan["template_snapshot"] or {}).get("items", [])
            if not item["applicable"]
        }

        mapping_row = self._latest_confirmed_mapping(
            connection, tenant_id=tenant_id, fingerprint=fingerprint
        )
        if corrected_mapping is not None:
            if revision is None or report.layout != "flat_v1":
                raise ImportError_("IMPORT_REMAP_INVALID", "列映射修订需要平面表格和来源批次")
            mapping = corrected_mapping
            mapping_source = "human"
            mapping_version_id = None
            confidence = None
        elif report.layout == "test_form_v1":
            mapping = ExcelImportMapping(
                case_title_column="用例名称",
                result_column="测试结果",
                sample_serial_column="样机SN",
                notes_column="备注",
                pass_values=["合格", "PASS", "通过"],
                fail_values=["不合格", "FAIL", "失败"],
                confidence=1,
            )
            mapping_source = "mapping"
            mapping_version_id = None
            confidence = None
        elif mapping_row is not None:
            mapping = ExcelImportMapping.model_validate(mapping_row["mapping"])
            mapping_source = "mapping"
            mapping_version_id = mapping_row["id"]
            confidence = None
        else:
            if prepared_mapping is None:
                raise ImportError_("IMPORT_MAPPING_CHANGED", "mapping changed; submit again")
            mapping = prepared_mapping
            mapping_source = "model"
            mapping_version_id = None
            confidence = mapping.confidence

        extracted, skipped = _apply_mapping(mapping, rows, report=report)
        skipped = [*report.skipped, *skipped]

        cases = {
            row["title"].strip(): row
            for row in connection.execute(
                select(
                    tables.test_cases.c.id,
                    tables.test_cases.c.title,
                    tables.test_cases.c.severity,
                    tables.test_cases.c.status,
                ).where(
                    tables.test_cases.c.tenant_id == tenant_id,
                    tables.test_cases.c.plan_id == plan_id,
                )
            ).mappings()
        }
        samples = {
            row["serial_number"]: row["id"]
            for row in connection.execute(
                select(tables.samples.c.id, tables.samples.c.serial_number).where(
                    tables.samples.c.tenant_id == tenant_id,
                    tables.samples.c.project_id == project_id,
                )
            ).mappings()
        }
        run_counters: dict[UUID, int] = {}
        created_run_ids: list[UUID] = []
        for item in extracted:
            if item["case_title"] in excluded_titles:
                skipped.append(
                    {
                        "row": item["row"],
                        "reason": "template_not_applicable",
                        "source": item["source"],
                        "exclusion_reason": excluded_titles[item["case_title"]],
                    }
                )
                continue
            case = cases.get(item["case_title"])
            if case is None:
                skipped.append(
                    {
                        "row": item["row"],
                        "reason": "unknown_test_case",
                        "source": item["source"],
                    }
                )
                continue
            if case["status"] == "waived":
                skipped.append(
                    {"row": item["row"], "reason": "test_case_waived", "source": item["source"]}
                )
                continue
            case_id = case["id"]
            if case_id not in run_counters:
                run_counters[case_id] = (
                    connection.execute(
                        select(
                            select(tables.test_runs.c.run_number)
                            .where(
                                tables.test_runs.c.tenant_id == tenant_id,
                                tables.test_runs.c.test_case_id == case_id,
                            )
                            .order_by(tables.test_runs.c.run_number.desc())
                            .limit(1)
                            .scalar_subquery()
                        )
                    ).scalar_one()
                    or 0
                )
            run_counters[case_id] += 1
            run_id = uuid4()
            sample_id = samples.get(item["sample_serial"])
            revision_id = None
            if sample_id is not None and item["config"]:
                revision_id = create_revision(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    sample_id=sample_id,
                    actor_user_id=actor_user_id,
                    source="report_extract",
                    snapshot=dict(item["config"]),
                    source_document_id=document.id,
                    occurred_at=occurred_at,
                )
            reported_day = (
                item["source"].get("reported_date") if report.layout == "test_form_v1" else None
            )
            connection.execute(
                tables.test_runs.insert(),
                {
                    "id": run_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "test_case_id": case_id,
                    "sample_id": sample_id,
                    "sample_configuration_revision_id": revision_id,
                    "execution_time_precision": "day" if reported_day else "unknown",
                    "execution_time_source": "report" if reported_day else "unknown",
                    "operator_user_id": actor_user_id,
                    "evidence_document_id": document.id,
                    "run_number": run_counters[case_id],
                    "status": item["status"],
                    "draft_state": "draft",
                    "metrics": item["metrics"],
                    "result_notes": item["notes"],
                    "conditions": {
                        "report_source": item["source"],
                        "report_sample_serial": item["sample_serial"],
                        "report_configuration": item["config"],
                    },
                    "started_at": None,
                    # Date-only form data uses UTC midnight as a storage
                    # representation, with precision explicitly retained.
                    "executed_at": (
                        datetime.fromisoformat(reported_day).replace(tzinfo=UTC)
                        if reported_day
                        else None
                    ),
                    "created_at": occurred_at,
                    "updated_at": occurred_at,
                },
            )
            created_run_ids.append(run_id)

        connection.execute(
            tables.test_report_import_batches.insert(),
            {
                "id": batch_id,
                "tenant_id": tenant_id,
                "project_id": project_id,
                "plan_id": plan_id,
                "document_id": document.id,
                "mapping_version_id": mapping_version_id,
                "created_by_user_id": actor_user_id,
                "template_fingerprint": fingerprint,
                "mapping_source": mapping_source,
                "proposed_mapping": (
                    mapping.model_dump() if mapping_source in {"model", "human"} else None
                ),
                "mapping_snapshot": mapping.model_dump(mode="json"),
                "parser_version": "test-report.v5",
                "workbook_layout": report.layout,
                "parent_batch_id": revision.parent_batch_id if revision else None,
                "remap_request_id": revision.request_id if revision else None,
                "remap_request_digest": revision.request_digest if revision else None,
                "remap_reason": revision.reason if revision else None,
                "status": "parsed",
                "parse_confidence": (
                    {"mapping_confidence": confidence} if confidence is not None else {}
                ),
                "created_run_ids": [str(run_id) for run_id in created_run_ids],
                "skipped_rows": skipped,
                "created_at": occurred_at,
                "updated_at": occurred_at,
            },
        )
        EventAuditWriter(
            connection,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            project_id=project_id,
        ).record(
            EventDraft(
                event_id=f"npi:import_batch:{batch_id}:parsed",
                event_type="NPI_RECORD_CHANGED",
                source="npi_service",
                entity_id=batch_id,
                payload={"record_type": "test_report_import", "action": "parsed"},
                occurred_at=occurred_at,
            ),
            AuditDraft(
                action="test_report_import.parse",
                after_snapshot={
                    "batch_id": str(batch_id),
                    "document_id": str(document.id),
                    "mapping_source": mapping_source,
                    "created_run_ids": [str(run_id) for run_id in created_run_ids],
                    "skipped_rows": skipped,
                },
            ),
        )
        return ImportBatchResult(
            id=batch_id,
            project_id=project_id,
            plan_id=plan_id,
            document_id=document.id,
            template_fingerprint=fingerprint,
            mapping_source=mapping_source,
            status="parsed",
            confidence=confidence,
            created_run_ids=tuple(created_run_ids),
            skipped_rows=tuple(skipped),
        )

    def confirm(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        batch_id: UUID,
        expected_digest: str | None = None,
        auth_version: int | None = None,
    ) -> ImportBatchResult:
        self._authorize_import(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            project_id=project_id,
            auth_version=auth_version,
        )
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise ImportError_("IMPORT_PROJECT_NOT_FOUND", "project was not found")
            batch = (
                connection.execute(
                    select(tables.test_report_import_batches)
                    .where(
                        tables.test_report_import_batches.c.tenant_id == tenant_id,
                        tables.test_report_import_batches.c.project_id == project_id,
                        tables.test_report_import_batches.c.id == batch_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if batch is None:
                raise ImportError_("IMPORT_BATCH_NOT_FOUND", "import batch was not found")
            if batch["status"] == "confirmed":
                return ImportBatchResult(
                    id=batch_id,
                    project_id=project_id,
                    plan_id=batch["plan_id"],
                    document_id=batch["document_id"],
                    template_fingerprint=batch["template_fingerprint"],
                    mapping_source=batch["mapping_source"],
                    status="confirmed",
                    confidence=dict(batch["parse_confidence"]).get("mapping_confidence"),
                    created_run_ids=tuple(UUID(value) for value in batch["created_run_ids"]),
                    skipped_rows=tuple(dict(item) for item in batch["skipped_rows"]),
                    reused_existing=True,
                )
            if batch["status"] != "parsed":
                raise ImportError_("IMPORT_BATCH_NOT_PENDING", "batch cannot be confirmed")
            from app.domain.test_import_preview import preview_in_connection

            preview = preview_in_connection(
                connection, tenant_id=tenant_id, project_id=project_id, batch_id=batch_id
            )
            if expected_digest is not None and preview["digest"] != expected_digest:
                raise ImportError_(
                    "IMPORT_PREVIEW_CHANGED", "报告草稿或目标资料已变化，请刷新预览后确认"
                )
            if preview["blockers"]:
                raise ImportError_("IMPORT_CONFIRMATION_BLOCKED", "；".join(preview["blockers"]))
            self._authorize_import(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
                auth_version=auth_version,
            )

            run_ids = [UUID(run_id) for run_id in batch["created_run_ids"]]
            if not run_ids:
                raise ImportError_(
                    "IMPORT_NO_CONFIRMABLE_RUNS",
                    "no test runs are ready for confirmation; review skipped records",
                )
            runs = (
                connection.execute(
                    select(tables.test_runs)
                    .where(
                        tables.test_runs.c.tenant_id == tenant_id,
                        tables.test_runs.c.id.in_(run_ids),
                    )
                    .order_by(tables.test_runs.c.run_number.asc())
                )
                .mappings()
                .all()
            )
            connection.execute(
                tables.test_runs.update()
                .where(
                    tables.test_runs.c.tenant_id == tenant_id,
                    tables.test_runs.c.id.in_(run_ids),
                )
                .values(draft_state="confirmed", updated_at=occurred_at)
            )
            final_run_by_case: dict[UUID, RowMapping] = {}
            for run in runs:
                final_run_by_case[run["test_case_id"]] = run
            for case_id, final_run in final_run_by_case.items():
                case = (
                    connection.execute(
                        select(tables.test_cases)
                        .where(
                            tables.test_cases.c.tenant_id == tenant_id,
                            tables.test_cases.c.id == case_id,
                        )
                        .with_for_update()
                    )
                    .mappings()
                    .one()
                )
                if case["status"] == "waived":
                    raise ImportError_(
                        "IMPORT_CASE_WAIVED",
                        "test case was waived after parsing; re-import against the current plan",
                    )
                sync_case_with_run_result(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    actor_user_id=actor_user_id,
                    case=case,
                    run_status=final_run["status"],
                    executed_at=final_run["executed_at"],
                    occurred_at=occurred_at,
                )

            mapping_version_id = batch["mapping_version_id"]
            if (
                batch["mapping_source"] in {"model", "human"}
                and batch["proposed_mapping"] is not None
            ):
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": f"pdos-import-mapping:{tenant_id}:{batch['template_fingerprint']}"},
                )
                previous = self._latest_confirmed_mapping(
                    connection,
                    tenant_id=tenant_id,
                    fingerprint=batch["template_fingerprint"],
                )
                mapping_version_id = uuid4()
                connection.execute(
                    tables.import_mapping_versions.insert(),
                    {
                        "id": mapping_version_id,
                        "tenant_id": tenant_id,
                        "template_fingerprint": batch["template_fingerprint"],
                        "version": (previous["version"] + 1) if previous else 1,
                        "mapping": dict(batch["proposed_mapping"]),
                        "confirmed_by_user_id": actor_user_id,
                        "created_at": occurred_at,
                    },
                )
                if previous is not None:
                    connection.execute(
                        tables.import_mapping_versions.update()
                        .where(
                            tables.import_mapping_versions.c.tenant_id == tenant_id,
                            tables.import_mapping_versions.c.id == previous["id"],
                        )
                        .values(superseded_by_id=mapping_version_id)
                    )
            connection.execute(
                tables.test_report_import_batches.update()
                .where(
                    tables.test_report_import_batches.c.tenant_id == tenant_id,
                    tables.test_report_import_batches.c.id == batch_id,
                )
                .values(
                    status="confirmed",
                    confirmed_by_user_id=actor_user_id,
                    confirmed_at=occurred_at,
                    mapping_version_id=mapping_version_id,
                    updated_at=occurred_at,
                )
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"npi:import_batch:{batch_id}:confirmed",
                    event_type="NPI_RECORD_CHANGED",
                    source="npi_service",
                    entity_id=batch_id,
                    payload={"record_type": "test_report_import", "action": "confirmed"},
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="test_report_import.confirm",
                    after_snapshot={
                        "batch_id": str(batch_id),
                        "confirmed_run_ids": [str(run_id) for run_id in run_ids],
                    },
                ),
            )
            return ImportBatchResult(
                id=batch_id,
                project_id=project_id,
                plan_id=batch["plan_id"],
                document_id=batch["document_id"],
                template_fingerprint=batch["template_fingerprint"],
                mapping_source=batch["mapping_source"],
                status="confirmed",
                confidence=dict(batch["parse_confidence"]).get("mapping_confidence"),
                created_run_ids=tuple(run_ids),
                skipped_rows=tuple(dict(item) for item in batch["skipped_rows"]),
            )
