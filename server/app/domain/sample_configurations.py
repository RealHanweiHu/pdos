"""Sample build configuration use cases (vNext V1-B2/B11, D37).

Every sample can answer "which config, which versions, built when" — sourced
from whole-unit test reports (AI import pipeline, draft until confirmed) or
maintained manually. Firmware versions are lightweight first-class releases
(find-or-create by project+version); development stays in Git.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select

from app.db.schema import tables
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class SampleConfigValueError(ValueError):
    """Configuration edit conflicts with current state or source scope."""


class SampleConfigNotFoundError(LookupError):
    """Raised when the sample or configuration is absent from the Project."""


@dataclass(frozen=True)
class SampleConfigRecord:
    id: UUID
    project_id: UUID
    sample_id: UUID
    sample_serial: str | None
    fw_release_id: UUID | None
    fw_version: str | None
    development_bom_id: UUID | None
    bom_code: str | None
    bom_version: int | None
    source_document_id: UUID | None
    pcb_version: str | None
    structure_version: str | None
    key_component_suppliers: dict[str, object]
    build_date: date | None
    source: str
    draft_state: str
    updated_at: datetime
    current_revision_id: UUID | None = None


@dataclass(frozen=True)
class SampleConfigDraft:
    pcb_version: str | None = None
    structure_version: str | None = None
    fw_version: str | None = None
    development_bom_id: UUID | None = None
    key_component_suppliers: dict[str, object] | None = None
    build_date: date | None = None
    clear_fields: tuple[str, ...] = ()


def find_or_create_fw_release(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    version: str,
    actor_user_id: UUID,
) -> UUID:
    existing = connection.execute(
        select(tables.fw_releases.c.id).where(
            tables.fw_releases.c.tenant_id == tenant_id,
            tables.fw_releases.c.project_id == project_id,
            tables.fw_releases.c.version == version,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return cast(UUID, existing)
    fw_id = uuid4()
    connection.execute(
        tables.fw_releases.insert(),
        {
            "id": fw_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "released_by_user_id": actor_user_id,
            "version": version,
        },
    )
    return fw_id


def upsert_configuration(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    actor_user_id: UUID,
    sample_id: UUID,
    draft: SampleConfigDraft,
    source: str,
    draft_state: str,
    source_document_id: UUID | None,
    occurred_at: datetime,
) -> UUID:
    fw_release_id = None
    if draft.fw_version:
        fw_release_id = find_or_create_fw_release(
            connection,
            tenant_id=tenant_id,
            project_id=project_id,
            version=draft.fw_version,
            actor_user_id=actor_user_id,
        )
    existing = (
        connection.execute(
            select(tables.sample_build_configurations)
            .where(
                tables.sample_build_configurations.c.tenant_id == tenant_id,
                tables.sample_build_configurations.c.sample_id == sample_id,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    values = {
        "updated_by_user_id": actor_user_id,
        "source": source,
        "draft_state": draft_state,
        "source_document_id": source_document_id,
        "updated_at": occurred_at,
    }
    if draft.pcb_version is not None:
        values["pcb_version"] = draft.pcb_version
    if draft.structure_version is not None:
        values["structure_version"] = draft.structure_version
    if fw_release_id is not None:
        values["fw_release_id"] = fw_release_id
    if draft.key_component_suppliers is not None:
        values["key_component_suppliers"] = draft.key_component_suppliers
    if draft.development_bom_id is not None:
        values["development_bom_id"] = draft.development_bom_id
    if draft.build_date is not None:
        values["build_date"] = draft.build_date
    for field in draft.clear_fields:
        column = "fw_release_id" if field == "fw_version" else field
        values[column] = {} if field == "key_component_suppliers" else None
    if existing is None:
        config_id = uuid4()
        connection.execute(
            tables.sample_build_configurations.insert(),
            {
                "id": config_id,
                "tenant_id": tenant_id,
                "project_id": project_id,
                "sample_id": sample_id,
                "created_at": occurred_at,
                **values,
            },
        )
    else:
        config_id = existing["id"]
        connection.execute(
            tables.sample_build_configurations.update()
            .where(
                tables.sample_build_configurations.c.tenant_id == tenant_id,
                tables.sample_build_configurations.c.id == config_id,
            )
            .values(**values)
        )
    if draft_state == "confirmed":
        from app.domain.sample_configuration_revisions import pin_current_configuration

        pin_current_configuration(
            connection,
            tenant_id=tenant_id,
            project_id=project_id,
            sample_id=sample_id,
            actor_user_id=actor_user_id,
            occurred_at=occurred_at,
            source="manual",
        )
    return config_id


def _record_from_row(row: Mapping[str, Any]) -> SampleConfigRecord:
    return SampleConfigRecord(
        id=row["id"],
        project_id=row["project_id"],
        sample_id=row["sample_id"],
        sample_serial=row.get("serial_number"),
        fw_release_id=row["fw_release_id"],
        fw_version=row.get("fw_version"),
        development_bom_id=row["development_bom_id"],
        bom_code=row.get("bom_code"),
        bom_version=row.get("bom_version"),
        source_document_id=row["source_document_id"],
        pcb_version=row["pcb_version"],
        structure_version=row["structure_version"],
        key_component_suppliers=dict(row["key_component_suppliers"]),
        build_date=row["build_date"],
        source=row["source"],
        draft_state=row["draft_state"],
        updated_at=row["updated_at"],
        current_revision_id=row["current_revision_id"],
    )


class SampleConfigService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list_configurations(self, *, tenant_id: UUID, project_id: UUID) -> list[SampleConfigRecord]:
        configs = tables.sample_build_configurations
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(
                    configs,
                    tables.samples.c.serial_number,
                    tables.fw_releases.c.version.label("fw_version"),
                    tables.development_boms.c.code.label("bom_code"),
                    tables.development_boms.c.version.label("bom_version"),
                )
                .join(
                    tables.samples,
                    (tables.samples.c.tenant_id == configs.c.tenant_id)
                    & (tables.samples.c.id == configs.c.sample_id),
                )
                .join(
                    tables.fw_releases,
                    (tables.fw_releases.c.tenant_id == configs.c.tenant_id)
                    & (tables.fw_releases.c.id == configs.c.fw_release_id),
                    isouter=True,
                )
                .join(
                    tables.development_boms,
                    (tables.development_boms.c.tenant_id == configs.c.tenant_id)
                    & (tables.development_boms.c.id == configs.c.development_bom_id),
                    isouter=True,
                )
                .where(
                    configs.c.tenant_id == tenant_id,
                    configs.c.project_id == project_id,
                )
                .order_by(tables.samples.c.serial_number.asc())
            ).mappings()
            return [_record_from_row(dict(row)) for row in rows]

    def compare(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        sample_ids: tuple[UUID, ...],
    ) -> SampleComparison:
        """Line up build configurations so a defect can be pinned to a change.

        Samples without a recorded configuration are reported separately rather
        than shown as a row of blanks that reads like "no differences".
        """
        by_sample = {
            record.sample_id: record
            for record in self.list_configurations(tenant_id=tenant_id, project_id=project_id)
        }
        present = tuple(by_sample[sid] for sid in sample_ids if sid in by_sample)
        missing = tuple(sid for sid in sample_ids if sid not in by_sample)
        field_values, differing = compare_configurations(present)
        return SampleComparison(
            samples=present,
            field_values=field_values,
            differing_fields=differing,
            missing_configuration_sample_ids=missing,
        )

    def upsert_manual(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        sample_id: UUID,
        draft: SampleConfigDraft,
        expected_digest: str | None = None,
        reason: str | None = None,
        auth_version: int | None = None,
    ) -> SampleConfigRecord:
        from app.domain.product_workspace import _plain
        from app.domain.sample_configuration_comparison import _current

        editable = (
            "pcb_version",
            "structure_version",
            "fw_version",
            "development_bom_id",
            "key_component_suppliers",
            "build_date",
        )
        if len(set(draft.clear_fields)) != len(draft.clear_fields) or any(
            f not in editable for f in draft.clear_fields
        ):
            raise SampleConfigValueError("清除字段无效或重复")
        if any(getattr(draft, f) is not None for f in draft.clear_fields):
            raise SampleConfigValueError("同一配置字段不能同时填写并清除")
        if any(
            v is not None and (not v.strip() or len(v) > 64)
            for v in (draft.pcb_version, draft.structure_version, draft.fw_version)
        ):
            raise SampleConfigValueError("版本值不能为空；清除已有值请明确选择标为未知")
        if draft.build_date is not None and draft.build_date > datetime.now(UTC).date():
            raise SampleConfigValueError("实际装机日期不能在未来")
        if draft.clear_fields and expected_digest is None:
            raise SampleConfigValueError("清除配置前请先读取当前版本并说明原因")
        if expected_digest is not None and (reason is None or not 1 <= len(reason.strip()) <= 2000):
            raise SampleConfigValueError("请说明本次配置更新依据")
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise SampleConfigNotFoundError
            if auth_version is not None:
                from app.auth.errors import ObjectPermissionDeniedError
                from app.auth.project_access import ProjectAccessService, SqlProjectAccessRepository
                from app.auth.repository import AuthRepository
                from app.auth.roles import Action

                current_actor = AuthRepository(self._engine).find_user_context(actor_user_id)
                if (
                    current_actor is None
                    or current_actor.tenant.id != tenant_id
                    or not current_actor.user.is_active
                    or current_actor.tenant.status != "active"
                    or current_actor.user.auth_version != auth_version
                ):
                    raise ObjectPermissionDeniedError
                ProjectAccessService(SqlProjectAccessRepository(self._engine)).authorize(
                    context=current_actor,
                    project_id=project_id,
                    action=Action.PRODUCT_ENGINEERING_EDIT,
                )
            sample = (
                connection.execute(
                    select(tables.samples).where(
                        tables.samples.c.tenant_id == tenant_id,
                        tables.samples.c.project_id == project_id,
                        tables.samples.c.id == sample_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if sample is None:
                raise SampleConfigNotFoundError
            before = _current(connection, tenant_id, project_id, sample_id)
            old_values = {
                f: before[f]
                if before is not None
                else ({} if f == "key_component_suppliers" else None)
                for f in editable
            }
            desired = dict(old_values)
            for field in editable:
                value = getattr(draft, field)
                if field in draft.clear_fields:
                    desired[field] = {} if field == "key_component_suppliers" else None
                elif value is not None:
                    desired[field] = value
            same = _plain(desired) == _plain(old_values)
            if (
                same
                and before is not None
                and before["draft_state"] == "confirmed"
                and before["current_revision_id"] is not None
            ):
                return _record_from_row({**before, "serial_number": sample["serial_number"]})
            if expected_digest is not None and expected_digest != configuration_edit_digest(
                sample_id, before
            ):
                raise SampleConfigValueError("当前配置已被更新，请重新读取并核对本次修改")
            if draft.development_bom_id is not None:
                bom = connection.execute(
                    select(tables.development_boms.c.id).where(
                        tables.development_boms.c.tenant_id == tenant_id,
                        tables.development_boms.c.project_id == project_id,
                        tables.development_boms.c.id == draft.development_bom_id,
                    )
                ).scalar_one_or_none()
                if bom is None:
                    raise SampleConfigValueError("请选择当前项目实际装机所用的BOM版本")
            config_id = upsert_configuration(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                sample_id=sample_id,
                draft=draft,
                source="manual",
                draft_state="confirmed",
                source_document_id=None,
                occurred_at=occurred_at,
            )
            after = _current(connection, tenant_id, project_id, sample_id)
            if after is None:
                raise SampleConfigNotFoundError
            EventAuditWriter(
                connection, tenant_id=tenant_id, actor_user_id=actor_user_id, project_id=project_id
            ).record(
                EventDraft(
                    event_id=f"npi:sample_config:{config_id}:upserted:{uuid4()}",
                    event_type="NPI_RECORD_CHANGED",
                    source="npi_service",
                    entity_id=config_id,
                    payload={"record_type": "sample_build_configuration", "action": "upserted"},
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="sample_configuration.upsert",
                    before_snapshot=_plain(before) if before else None,
                    after_snapshot={
                        **_plain(after),
                        "reason": reason.strip() if reason else None,
                        "cleared_fields": list(draft.clear_fields),
                    },
                ),
            )
            return _record_from_row({**after, "serial_number": sample["serial_number"]})


def configuration_edit_digest(sample_id: UUID, current: Mapping[str, Any] | None) -> str:
    from app.domain.product_workspace import _plain, digest

    return digest(_plain({"sample_id": sample_id, "current": current}))


COMPARABLE_FIELDS: tuple[str, ...] = (
    "bom_revision",
    "pcb_version",
    "structure_version",
    "fw_version",
    "build_date",
    "key_component_suppliers",
)


@dataclass(frozen=True)
class SampleComparison:
    samples: tuple[SampleConfigRecord, ...]
    """Field name → per-sample value, in the same order as `samples`."""
    field_values: dict[str, list[object | None]]
    differing_fields: tuple[str, ...]
    missing_configuration_sample_ids: tuple[UUID, ...]


def _comparable_value(record: SampleConfigRecord, field: str) -> object | None:
    if field == "bom_revision":
        if record.bom_code is None:
            return None
        return f"{record.bom_code} v{record.bom_version}"
    if field == "build_date":
        return record.build_date.isoformat() if record.build_date else None
    if field == "key_component_suppliers":
        # Compare as sorted pairs so key order never fakes a difference.
        return sorted(record.key_component_suppliers.items()) or None
    # The comparable fields above are exhausted; the rest are plain attributes.
    return cast("object | None", getattr(record, field))


def compare_configurations(
    records: tuple[SampleConfigRecord, ...],
) -> tuple[dict[str, list[object | None]], tuple[str, ...]]:
    field_values: dict[str, list[object | None]] = {}
    differing: list[str] = []
    for field in COMPARABLE_FIELDS:
        values = [_comparable_value(record, field) for record in records]
        field_values[field] = values
        # A field where every sample is blank is not a difference worth showing.
        if (
            len(
                {
                    json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
                    for value in values
                }
            )
            > 1
        ):
            differing.append(field)
    return field_values, tuple(differing)
