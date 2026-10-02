"""Human-authored firmware investigation and delivery preparation, pinned to real evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, or_, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.npi_execution import NpiExecutionService, _snapshot
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.sample_configurations import find_or_create_fw_release
from app.domain.test_verification_paths import _authorize

SourceKind = Literal["issue", "configuration", "test_run", "build"]


class FirmwarePackageError(ValueError):
    pass


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: SourceKind
    id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    use: Literal["context", "reproduction", "regression"]
    basis: str = Field(min_length=1, max_length=2000)


class SoftwareComponent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Literal["software", "app"]
    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    git_reference: str = Field(min_length=1, max_length=512)
    change_notes: str = Field(min_length=1, max_length=4000)


class FirmwarePackageDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_package_id: UUID | None = None
    firmware_version: str = Field(min_length=1, max_length=64)
    intent: Literal["investigation", "release_preparation"]
    git_reference: str = Field(min_length=1, max_length=512)
    change_notes: str = Field(min_length=1, max_length=10000)
    observations: str = Field(min_length=1, max_length=10000)
    reproduction_steps: str = Field(min_length=1, max_length=10000)
    hypotheses: str = Field(min_length=1, max_length=10000)
    verification_plan: str = Field(min_length=1, max_length=10000)
    unknowns: str = Field(min_length=1, max_length=10000)
    coordination: str = Field(min_length=1, max_length=4000)
    reason: str = Field(min_length=1, max_length=2000)
    components: list[SoftwareComponent] = Field(default_factory=list, max_length=20)
    sources: list[SourceReference] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_sources(self) -> FirmwarePackageDraft:
        if len({(s.kind, s.id) for s in self.sources}) != len(self.sources):
            raise ValueError("同一来源请合并说明后引用一次")
        if any(s.use == "regression" and s.kind != "test_run" for s in self.sources):
            raise ValueError("回归证据必须选择实际逐次测试记录")
        if self.intent == "investigation" and not {"issue", "configuration"}.issubset(
            {s.kind for s in self.sources}
        ):
            raise ValueError("问题调查需要关联原问题及当时的样机配置版本")
        if len({(c.kind, c.name) for c in self.components}) != len(self.components):
            raise ValueError("同一软件组件请只登记一个版本")
        return self


def _table(kind: SourceKind) -> Any:
    return {
        "issue": tables.issues,
        "configuration": tables.sample_configuration_revisions,
        "test_run": tables.test_runs,
        "build": tables.build_batches,
    }[kind]


def _source(
    c: Connection, tenant_id: UUID, project_id: UUID, kind: SourceKind, id: UUID
) -> dict[str, Any]:
    t = _table(kind)
    row = (
        c.execute(
            select(t).where(t.c.tenant_id == tenant_id, t.c.project_id == project_id, t.c.id == id)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise FirmwarePackageError("引用来源不存在或已不属于本项目，请重新选择")
    value = dict(row)
    if kind == "test_run":
        case = (
            c.execute(
                select(tables.test_cases).where(
                    tables.test_cases.c.tenant_id == tenant_id,
                    tables.test_cases.c.project_id == project_id,
                    tables.test_cases.c.id == row["test_case_id"],
                )
            )
            .mappings()
            .one()
        )
        value["case"] = {key: case[key] for key in ("id", "title", "plan_id", "related_issue_id")}
        configuration_id = row["sample_configuration_revision_id"]
        value["configuration"] = (
            _source(c, tenant_id, project_id, "configuration", configuration_id)
            if configuration_id
            else None
        )
    if kind == "configuration":
        sample = (
            c.execute(
                select(tables.samples).where(
                    tables.samples.c.tenant_id == tenant_id,
                    tables.samples.c.project_id == project_id,
                    tables.samples.c.id == row["sample_id"],
                )
            )
            .mappings()
            .one()
        )
        value["sample"] = {key: sample[key] for key in ("id", "serial_number", "build_batch_id")}
    return _plain(value)


def source_options(
    engine: Engine,
    *,
    context: AuthContext,
    project_id: UUID,
    kind: SourceKind,
    after_id: UUID | None = None,
) -> dict[str, Any]:
    _authorize(engine, context, project_id, edit=False)
    t = _table(kind)
    q = select(t.c.id).where(t.c.tenant_id == context.tenant.id, t.c.project_id == project_id)
    if kind == "issue":
        q = q.where(t.c.withdrawn_at.is_(None))
    if after_id:
        q = q.where(t.c.id > after_id)
    with engine.connect() as c:
        ids = list(c.execute(q.order_by(t.c.id).limit(51)).scalars())
        rows = [_source(c, context.tenant.id, project_id, kind, id) for id in ids[:50]]
    return {
        "items": [
            {"kind": kind, "id": row["id"], "snapshot": row, "digest": digest(row)} for row in rows
        ],
        "next_cursor": str(ids[49]) if len(ids) > 50 else None,
    }


def _latest(c: Connection, tenant_id: UUID, project_id: UUID, fw_id: UUID) -> dict[str, Any] | None:
    t = tables.firmware_work_packages
    row = (
        c.execute(
            select(t)
            .where(
                t.c.tenant_id == tenant_id, t.c.project_id == project_id, t.c.fw_release_id == fw_id
            )
            .order_by(t.c.revision_number.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


def list_packages(
    engine: Engine, *, context: AuthContext, project_id: UUID, before_id: UUID | None = None
) -> dict[str, Any]:
    _authorize(engine, context, project_id, edit=False)
    t, fw, u = tables.firmware_work_packages, tables.fw_releases, tables.users
    q = (
        select(t, fw.c.version.label("firmware_version"), u.c.display_name.label("created_by_name"))
        .join(fw, (fw.c.tenant_id == t.c.tenant_id) & (fw.c.id == t.c.fw_release_id))
        .join(u, (u.c.tenant_id == t.c.tenant_id) & (u.c.id == t.c.created_by_user_id))
        .where(t.c.tenant_id == context.tenant.id, t.c.project_id == project_id)
    )
    with engine.connect() as c:
        if before_id:
            boundary = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.project_id == project_id,
                        t.c.id == before_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if boundary is None:
                raise FirmwarePackageError("历史分页位置不存在，请重新读取")
            q = q.where(
                or_(
                    t.c.created_at < boundary["created_at"],
                    (t.c.created_at == boundary["created_at"]) & (t.c.id < before_id),
                )
            )
        rows = [
            dict(r)
            for r in c.execute(
                q.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(26)
            ).mappings()
        ]
    return _plain({"items": rows[:25], "next_cursor": rows[24]["id"] if len(rows) > 25 else None})


def current_package(
    engine: Engine, *, context: AuthContext, project_id: UUID, version: str
) -> dict[str, Any]:
    _authorize(engine, context, project_id, edit=False)
    fw = tables.fw_releases
    with engine.connect() as c:
        id = c.execute(
            select(fw.c.id).where(
                fw.c.tenant_id == context.tenant.id,
                fw.c.project_id == project_id,
                fw.c.version == version,
            )
        ).scalar_one_or_none()
        package = _latest(c, context.tenant.id, project_id, id) if id else None
        sources = []
        for s in package["snapshot"]["sources"] if package else []:
            try:
                current = _source(c, context.tenant.id, project_id, s["kind"], UUID(s["id"]))
                sources.append(
                    {
                        "kind": s["kind"],
                        "id": s["id"],
                        "changed": digest(current) != s["expected_digest"],
                        "current": current,
                        "digest": digest(current),
                    }
                )
            except FirmwarePackageError:
                sources.append(
                    {
                        "kind": s["kind"],
                        "id": s["id"],
                        "changed": True,
                        "current": None,
                        "digest": None,
                    }
                )
    return _plain({"package": package, "sources": sources})


def save(
    engine: Engine, *, context: AuthContext, project_id: UUID, draft: FirmwarePackageDraft
) -> dict[str, Any]:
    _authorize(engine, context, project_id, edit=True)
    fingerprint = digest({"project_id": str(project_id), **draft.model_dump(mode="json")})
    t = tables.firmware_work_packages
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project_id):
            raise FirmwarePackageError("项目不可用")
        _authorize(engine, context, project_id, edit=True)
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
                raise FirmwarePackageError("同一提交请求不能改写成不同资料，请重新核对后提交")
            return _plain(dict(receipt))
        fw_id = find_or_create_fw_release(
            c,
            tenant_id=context.tenant.id,
            project_id=project_id,
            version=draft.firmware_version,
            actor_user_id=context.user.id,
        )
        prior = _latest(c, context.tenant.id, project_id, fw_id)
        if (prior["id"] if prior else None) != draft.expected_package_id:
            raise FirmwarePackageError("此固件版本已有新的工作包，请读取最新资料后修订")
        sources = []
        for ref in draft.sources:
            current = _source(c, context.tenant.id, project_id, ref.kind, ref.id)
            if ref.kind == "issue" and current.get("withdrawn_at") is not None:
                raise FirmwarePackageError("原问题已撤回，不能新增固件关联")
            if digest(current) != ref.expected_digest:
                raise FirmwarePackageError("所选问题或测试来源已变化，请刷新后核对")
            if ref.use == "regression" and current["draft_state"] != "confirmed":
                raise FirmwarePackageError("未确认的报告草稿不能作为回归证据")
            sources.append({**ref.model_dump(mode="json"), "snapshot": current})
        snapshot = draft.model_dump(
            mode="json", exclude={"request_id", "expected_package_id", "sources"}
        )
        snapshot["sources"] = sources
        row = (
            c.execute(
                t.insert()
                .values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    project_id=project_id,
                    fw_release_id=fw_id,
                    revision_number=prior["revision_number"] + 1 if prior else 1,
                    request_id=draft.request_id,
                    request_digest=fingerprint,
                    snapshot=snapshot,
                    created_by_user_id=context.user.id,
                    created_at=datetime.now(UTC),
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
            record_type="firmware_work_package",
            action="prepared",
            before=_snapshot(prior) if prior else None,
            after=_snapshot(dict(row)),
        )
        return _plain(dict(row))
