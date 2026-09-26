"""Versioned human correspondence between firmware task scope and actual test evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.project_access import ProjectAccessService, SqlProjectAccessRepository
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.firmware_package_tasks import _state, _task
from app.domain.firmware_work_packages import FirmwarePackageError, _source
from app.domain.npi_execution import NpiExecutionService, _snapshot
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.test_verification_paths import _authorize


class RunReference(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    run_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    role: Literal["verification", "comparison"]
    scope: str = Field(min_length=1, max_length=4000)


class ResultDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    outcome: Literal["recorded", "needs_follow_up", "scope_verified"]
    tested_scope: str = Field(min_length=1, max_length=10000)
    excluded_scope: str = Field(min_length=1, max_length=10000)
    criteria_assessment: str = Field(min_length=1, max_length=10000)
    follow_up: str = Field(min_length=1, max_length=10000)
    reason: str = Field(min_length=1, max_length=4000)
    runs: list[RunReference] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_runs(self) -> ResultDraft:
        if len({r.run_id for r in self.runs}) != len(self.runs):
            raise ValueError("同一测试记录请合并对应范围后引用一次")
        if self.outcome == "scope_verified" and not any(
            r.role == "verification" for r in self.runs
        ):
            raise ValueError("本次范围验证结论必须关联实际验证记录")
        return self


def _run(c: Connection, tenant_id: UUID, project_id: UUID, run_id: UUID) -> dict[str, Any]:
    value = _source(c, tenant_id, project_id, "test_run", run_id)
    case = (
        c.execute(
            select(tables.test_cases).where(
                tables.test_cases.c.tenant_id == tenant_id,
                tables.test_cases.c.project_id == project_id,
                tables.test_cases.c.id == UUID(value["test_case_id"]),
            )
        )
        .mappings()
        .one()
    )
    value["verification_basis"] = _plain(
        {key: case[key] for key in ("specification_id", "method", "acceptance_criteria", "status")}
    )
    document = None
    if value["evidence_document_id"]:
        document = (
            c.execute(
                select(
                    tables.documents.c.id, tables.documents.c.filename, tables.documents.c.sha256
                ).where(
                    tables.documents.c.tenant_id == tenant_id,
                    tables.documents.c.project_id == project_id,
                    tables.documents.c.id == UUID(value["evidence_document_id"]),
                )
            )
            .mappings()
            .one_or_none()
        )
    value["evidence"] = _plain(dict(document)) if document else None
    return value


def evaluate_run(run: dict[str, Any], version: str) -> dict[str, Any]:
    gaps = []
    if run["draft_state"] != "confirmed":
        gaps.append("测试记录尚未确认")
    if run["status"] != "passed":
        gaps.append("实际测试未通过")
    if not run["evidence"]:
        gaps.append("缺少原报告证据")
    config = run.get("configuration") or {}
    firmware = (config.get("snapshot") or {}).get("fw_version")
    if not firmware:
        gaps.append("当次固件配置未知")
    elif firmware != version:
        gaps.append("当次固件与工作包版本不同")
    if not run["sample_id"] or config.get("sample_id") != run["sample_id"]:
        gaps.append("缺少同一实际样机的配置绑定")
    if (
        not run["executed_at"]
        or run["execution_time_precision"] not in {"day", "instant"}
        or run["execution_time_source"] in {"legacy_unknown", "system_completion"}
    ):
        gaps.append("实际测试时间尚未明确")
    if (
        not (run["verification_basis"].get("method") or "").strip()
        or not (run["verification_basis"].get("acceptance_criteria") or "").strip()
    ):
        gaps.append("测试方法或判据不完整")
    return {"eligible": not gaps, "gaps": gaps, "firmware_version": firmware}


def _latest(c: Connection, tenant_id: UUID, binding_id: UUID) -> dict[str, Any] | None:
    t = tables.firmware_task_results
    row = (
        c.execute(
            select(t)
            .where(t.c.tenant_id == tenant_id, t.c.binding_id == binding_id)
            .order_by(t.c.revision_number.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


def _basis(c: Connection, tenant_id: UUID, project_id: UUID, binding_id: UUID) -> dict[str, Any]:
    b = tables.firmware_package_tasks
    binding = (
        c.execute(
            select(b).where(
                b.c.tenant_id == tenant_id, b.c.project_id == project_id, b.c.id == binding_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if binding is None:
        raise FirmwarePackageError("任务与工作包的办理记录不存在")
    state = _state(c, tenant_id, project_id, binding["package_id"])
    latest_binding_id = c.execute(
        select(b.c.id)
        .where(
            b.c.tenant_id == tenant_id,
            b.c.project_id == project_id,
            b.c.task_id == binding["task_id"],
        )
        .order_by(b.c.created_at.desc(), b.c.id.desc())
        .limit(1)
    ).scalar_one()
    result = _latest(c, tenant_id, binding_id)
    return _plain(
        {
            **state,
            "binding": dict(binding),
            "task": _task(c, tenant_id, project_id, binding["task_id"]),
            "latest_binding_id": latest_binding_id,
            "latest_result_id": result["id"] if result else None,
            "can_verify_scope": state["can_prepare"] and latest_binding_id == binding_id,
        }
    )


def read(
    engine: Engine,
    *,
    context: AuthContext,
    project_id: UUID,
    binding_id: UUID,
    before_revision: int | None = None,
) -> dict[str, Any]:
    _authorize(engine, context, project_id, edit=False)
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        basis = _basis(c, context.tenant.id, project_id, binding_id)
        t, u = tables.firmware_task_results, tables.users
        q = (
            select(t, u.c.display_name.label("created_by_name"))
            .join(u, (u.c.tenant_id == t.c.tenant_id) & (u.c.id == t.c.created_by_user_id))
            .where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project_id,
                t.c.binding_id == binding_id,
            )
        )
        if before_revision is not None:
            q = q.where(t.c.revision_number < before_revision)
        history = [
            dict(r) for r in c.execute(q.order_by(t.c.revision_number.desc()).limit(21)).mappings()
        ]
        for result in history[:20]:
            comparisons = []
            for ref in result["snapshot"]["runs"]:
                try:
                    current = _run(c, context.tenant.id, project_id, UUID(ref["run_id"]))
                    changed = digest(current) != ref["expected_digest"]
                except FirmwarePackageError:
                    changed = True
                comparisons.append({"run_id": ref["run_id"], "changed": changed})
            result["current_evidence"] = comparisons
    return {
        **basis,
        "digest": digest(basis),
        "history": _plain(history[:20]),
        "next_revision": history[19]["revision_number"] if len(history) > 20 else None,
    }


def run_options(
    engine: Engine,
    *,
    context: AuthContext,
    project_id: UUID,
    binding_id: UUID,
    after_id: UUID | None = None,
) -> dict[str, Any]:
    _authorize(engine, context, project_id, edit=False)
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        state = _basis(c, context.tenant.id, project_id, binding_id)
        version = state["package"]["snapshot"]["firmware_version"]
        t = tables.test_runs
        q = select(t.c.id).where(t.c.tenant_id == context.tenant.id, t.c.project_id == project_id)
        if after_id:
            q = q.where(t.c.id > after_id)
        ids = list(c.execute(q.order_by(t.c.id).limit(51)).scalars())
        runs = [_run(c, context.tenant.id, project_id, id) for id in ids[:50]]
    return {
        "items": [
            {
                "run_id": run["id"],
                "snapshot": run,
                "digest": digest(run),
                "assessment": evaluate_run(run, version),
            }
            for run in runs
        ],
        "next_cursor": str(ids[49]) if len(ids) > 50 else None,
    }


def save(
    engine: Engine, *, context: AuthContext, project_id: UUID, binding_id: UUID, draft: ResultDraft
) -> dict[str, Any]:
    _authorize(engine, context, project_id, edit=False)
    ProjectAccessService(SqlProjectAccessRepository(engine)).authorize(
        context=context, project_id=project_id, action=Action.TEST_RUN_RECORD
    )
    fingerprint = digest(
        {
            "project_id": str(project_id),
            "binding_id": str(binding_id),
            **draft.model_dump(mode="json"),
        }
    )
    t = tables.firmware_task_results
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project_id):
            raise FirmwarePackageError("项目不可用")
        _authorize(engine, context, project_id, edit=False)
        ProjectAccessService(SqlProjectAccessRepository(engine)).authorize(
            context=context, project_id=project_id, action=Action.TEST_RUN_RECORD
        )
        receipt = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.created_by_user_id == context.user.id,
                    t.c.request_id == draft.request_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if receipt:
            if receipt["request_digest"] != fingerprint:
                raise FirmwarePackageError("同一登记请求不能改为不同结果，请刷新后核对")
            return _plain(dict(receipt))
        basis = _basis(c, context.tenant.id, project_id, binding_id)
        if draft.expected_digest != digest(basis):
            raise FirmwarePackageError("任务、工作包或结果已变化，请刷新后核对")
        if draft.outcome == "scope_verified" and not basis["can_verify_scope"]:
            raise FirmwarePackageError(
                "资料或任务已有新承接版本，或原来源已变化；请先核对最新工作包"
            )
        refs = []
        for ref in draft.runs:
            run = _run(c, context.tenant.id, project_id, ref.run_id)
            if digest(run) != ref.expected_digest:
                raise FirmwarePackageError("所选测试、方法或证据已变化，请刷新后重新对应")
            if run["draft_state"] != "confirmed":
                raise FirmwarePackageError("报告草稿需先在原报告办理确认，再登记结果对应")
            assessment = evaluate_run(run, basis["package"]["snapshot"]["firmware_version"])
            if (
                draft.outcome == "scope_verified"
                and ref.role == "verification"
                and not assessment["eligible"]
            ):
                raise FirmwarePackageError("验证记录尚有缺口：" + "；".join(assessment["gaps"]))
            refs.append({**ref.model_dump(mode="json"), "snapshot": run, "assessment": assessment})
        previous = _latest(c, context.tenant.id, binding_id)
        snapshot = {
            **draft.model_dump(mode="json", exclude={"request_id", "expected_digest", "runs"}),
            "runs": refs,
            "task_at_review": basis["task"],
            "package_id": basis["package"]["id"],
            "package_revision": basis["package"]["revision_number"],
            "completion_criteria": basis["binding"]["snapshot"]["completion_criteria"],
            "can_verify_scope_at_review": basis["can_verify_scope"],
        }
        row = (
            c.execute(
                t.insert()
                .values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    project_id=project_id,
                    binding_id=binding_id,
                    revision_number=previous["revision_number"] + 1 if previous else 1,
                    request_id=draft.request_id,
                    request_digest=fingerprint,
                    created_by_user_id=context.user.id,
                    created_at=datetime.now(UTC),
                    snapshot=snapshot,
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
            record_id=row["id"],
            record_type="firmware_task_result",
            action="recorded",
            before=_snapshot(previous) if previous else None,
            after=_snapshot(dict(row)),
        )
        return _plain(dict(row))
