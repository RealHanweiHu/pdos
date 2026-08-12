"""Validated direct consumption of the CEHub deliverable check-item manifest."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import RowMapping

from app.db.schema import tables
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

MANIFEST_PATH = (
    Path(__file__).resolve().parents[3] / "assets" / "cehub" / "deliverable-guide-manifest.json"
)
EXPECTED_CHECK_ITEM_COUNT = 687
REQUIRED_BINDING_KEYS = frozenset(
    {"projectType", "phaseId", "phaseCode", "phaseName", "taskId", "taskName", "isGate"}
)


class DeliverableAssetError(ValueError):
    """Raised when the checked-in trusted asset violates its frozen contract."""


class DeliverableNotFoundError(LookupError):
    """Raised when a project check item is outside the tenant-bound project."""


class DeliverableTransitionError(ValueError):
    """Raised when completion would bypass the hard-gate contract."""


def _hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(raw, dict)
        or not isinstance(raw.get("schemaVersion"), int)
        or raw["schemaVersion"] <= 0
        or not isinstance(raw.get("templateVersions"), list)
        or not isinstance(raw.get("deliverables"), dict)
    ):
        raise DeliverableAssetError("manifest envelope")
    items: list[dict[str, Any]] = []
    for deliverable_name, deliverable in raw["deliverables"].items():
        if not isinstance(deliverable_name, str) or not isinstance(deliverable, dict):
            raise DeliverableAssetError("deliverable entry")
        check_items = deliverable.get("checkItems")
        if not isinstance(check_items, list):
            raise DeliverableAssetError("checkItems")
        for item in check_items:
            if not isinstance(item, dict) or not isinstance(item.get("bindings"), list):
                raise DeliverableAssetError("check item")
            if not all(
                isinstance(item.get(field), str) and item[field].strip()
                for field in ("id", "requirement", "source")
            ):
                raise DeliverableAssetError("check item text")
            for binding in item["bindings"]:
                if not isinstance(binding, dict) or set(binding) != REQUIRED_BINDING_KEYS:
                    raise DeliverableAssetError("binding shape")
                if not isinstance(binding["isGate"], bool) or not all(
                    isinstance(binding[field], str) and binding[field].strip()
                    for field in REQUIRED_BINDING_KEYS - {"isGate"}
                ):
                    raise DeliverableAssetError("binding values")
            canonical = {
                "check_item_key": item["id"],
                "deliverable_name": deliverable_name,
                "requirement": item["requirement"],
                "source": item["source"],
                "bindings": item["bindings"],
            }
            items.append({**canonical, "content_hash": _hash(canonical)})
    keys = [item["check_item_key"] for item in items]
    if len(items) != EXPECTED_CHECK_ITEM_COUNT or len(set(keys)) != len(keys):
        raise DeliverableAssetError("expected 687 unique check items")
    return {
        "schema_version": raw["schemaVersion"],
        "template_versions": raw["templateVersions"],
        "items": items,
    }


class DeliverableCheckService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _project(
        connection: Connection, *, tenant_id: UUID, project_id: UUID, lock: bool = False
    ) -> RowMapping:
        statement = (
            select(
                tables.projects,
                tables.workflows.c.code.label("workflow_code"),
            )
            .join(
                tables.workflows,
                (tables.workflows.c.tenant_id == tables.projects.c.tenant_id)
                & (tables.workflows.c.id == tables.projects.c.workflow_id),
            )
            .where(
                tables.projects.c.tenant_id == tenant_id,
                tables.projects.c.id == project_id,
            )
        )
        if lock:
            statement = statement.with_for_update(of=tables.projects)
        row = connection.execute(statement).mappings().one_or_none()
        if row is None:
            raise DeliverableNotFoundError
        return row

    @staticmethod
    def _record(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID | None,
        actor_user_id: UUID,
        entity_id: UUID,
        record_type: str,
        action: str,
        count: int,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> None:
        EventAuditWriter(
            connection,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            project_id=project_id,
        ).record(
            EventDraft(
                event_id=f"deliverable:{record_type}:{entity_id}:{action}:{uuid4()}",
                event_type="DELIVERABLE_CHECK_CHANGED",
                source="deliverable_check_service",
                entity_id=entity_id,
                payload={"record_type": record_type, "action": action, "count": count},
            ),
            AuditDraft(
                action=f"deliverable_check.{record_type}.{action}",
                before_snapshot=before,
                after_snapshot=after,
            ),
        )

    @classmethod
    def _import(
        cls,
        connection: Connection,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        manifest: dict[str, Any],
        now: datetime,
    ) -> int:
        tenant = connection.execute(
            select(tables.tenants.c.id).where(tables.tenants.c.id == tenant_id).with_for_update()
        ).scalar_one_or_none()
        if tenant is None:
            raise DeliverableNotFoundError
        existing = {
            row.check_item_key: row.content_hash
            for row in connection.execute(
                select(
                    tables.deliverable_check_templates.c.check_item_key,
                    tables.deliverable_check_templates.c.content_hash,
                ).where(tables.deliverable_check_templates.c.tenant_id == tenant_id)
            )
        }
        manifest_keys = {item["check_item_key"] for item in manifest["items"]}
        if set(existing) - manifest_keys or any(
            existing[key] != item["content_hash"]
            for item in manifest["items"]
            if (key := item["check_item_key"]) in existing
        ):
            raise DeliverableAssetError("imported asset drift")
        missing = [item for item in manifest["items"] if item["check_item_key"] not in existing]
        if missing:
            connection.execute(
                tables.deliverable_check_templates.insert(),
                [
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "asset_schema_version": manifest["schema_version"],
                        "template_versions": manifest["template_versions"],
                        **item,
                        "imported_at": now,
                        "created_at": now,
                        "updated_at": now,
                    }
                    for item in missing
                ],
            )
            cls._record(
                connection,
                tenant_id=tenant_id,
                project_id=None,
                actor_user_id=actor_user_id,
                entity_id=tenant_id,
                record_type="library",
                action="imported",
                count=len(missing),
                before=None,
                after={
                    "asset_schema_version": manifest["schema_version"],
                    "check_item_count": EXPECTED_CHECK_ITEM_COUNT,
                },
            )
        return len(missing)

    def prepare_project(
        self, *, tenant_id: UUID, project_id: UUID, actor_user_id: UUID
    ) -> dict[str, Any]:
        manifest = load_manifest()
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            project = self._project(
                connection, tenant_id=tenant_id, project_id=project_id, lock=True
            )
            imported_count = self._import(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                manifest=manifest,
                now=now,
            )
            project_type = str(project["workflow_code"]).partition("-")[0].lower()
            stages = {
                row.code: row
                for row in connection.execute(
                    select(tables.stages.c.id, tables.stages.c.code).where(
                        tables.stages.c.tenant_id == tenant_id,
                        tables.stages.c.workflow_id == project["workflow_id"],
                    )
                )
            }
            templates = connection.execute(
                select(tables.deliverable_check_templates).where(
                    tables.deliverable_check_templates.c.tenant_id == tenant_id
                )
            ).mappings()
            values: list[dict[str, Any]] = []
            for template in templates:
                for binding in template["bindings"]:
                    stage = stages.get(binding["phaseId"])
                    if binding["projectType"] != project_type or stage is None:
                        continue
                    binding_key = ":".join(
                        (
                            binding["projectType"],
                            binding["phaseId"],
                            binding["taskId"],
                        )
                    )
                    values.append(
                        {
                            "id": uuid4(),
                            "tenant_id": tenant_id,
                            "project_id": project_id,
                            "workflow_id": project["workflow_id"],
                            "stage_id": stage.id,
                            "template_id": template["id"],
                            "created_by_user_id": actor_user_id,
                            "binding_key": binding_key,
                            "phase_id": binding["phaseId"],
                            "phase_code": binding["phaseCode"],
                            "phase_name": binding["phaseName"],
                            "task_id": binding["taskId"],
                            "task_name": binding["taskName"],
                            "deliverable_name": template["deliverable_name"],
                            "requirement": template["requirement"],
                            "is_gate": binding["isGate"],
                            "status": "pending",
                            "created_at": now,
                            "updated_at": now,
                        }
                    )
            created_ids: list[UUID] = []
            if values:
                created_ids = list(
                    connection.execute(
                        pg_insert(tables.project_check_items)
                        .values(values)
                        .on_conflict_do_nothing(
                            constraint="uq_project_check_items_tenant_project_template_binding"
                        )
                        .returning(tables.project_check_items.c.id)
                    ).scalars()
                )
            if created_ids:
                self._record(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    actor_user_id=actor_user_id,
                    entity_id=project_id,
                    record_type="project_items",
                    action="instantiated",
                    count=len(created_ids),
                    before=None,
                    after={"project_type": project_type, "created_count": len(created_ids)},
                )
            total = connection.execute(
                select(tables.project_check_items.c.id).where(
                    tables.project_check_items.c.tenant_id == tenant_id,
                    tables.project_check_items.c.project_id == project_id,
                )
            ).all()
            return {
                "asset_schema_version": manifest["schema_version"],
                "library_count": EXPECTED_CHECK_ITEM_COUNT,
                "imported_count": imported_count,
                "project_type": project_type,
                "created_count": len(created_ids),
                "project_item_count": len(total),
            }

    def list_items(self, *, tenant_id: UUID, project_id: UUID) -> list[dict[str, Any]]:
        with self._engine.connect() as connection:
            self._project(connection, tenant_id=tenant_id, project_id=project_id)
            return [
                dict(row)
                for row in connection.execute(
                    select(tables.project_check_items)
                    .join(
                        tables.stages,
                        (tables.stages.c.tenant_id == tables.project_check_items.c.tenant_id)
                        & (tables.stages.c.id == tables.project_check_items.c.stage_id),
                    )
                    .where(
                        tables.project_check_items.c.tenant_id == tenant_id,
                        tables.project_check_items.c.project_id == project_id,
                    )
                    .order_by(
                        tables.stages.c.sequence,
                        tables.project_check_items.c.is_gate.desc(),
                        tables.project_check_items.c.task_name,
                        tables.project_check_items.c.id,
                    )
                ).mappings()
            ]

    def resolve_item(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        item_id: UUID,
        status: Literal["completed", "not_applicable"],
        evidence_reference: str | None,
        note: str | None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            self._project(connection, tenant_id=tenant_id, project_id=project_id, lock=True)
            before = (
                connection.execute(
                    select(tables.project_check_items)
                    .where(
                        tables.project_check_items.c.tenant_id == tenant_id,
                        tables.project_check_items.c.project_id == project_id,
                        tables.project_check_items.c.id == item_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if before is None:
                raise DeliverableNotFoundError
            if before["status"] != "pending":
                raise DeliverableTransitionError("terminal item")
            if status == "completed" and not evidence_reference:
                raise DeliverableTransitionError("completion evidence required")
            if status == "not_applicable" and (before["is_gate"] or not note):
                raise DeliverableTransitionError("hard gate cannot be bypassed")
            row = (
                connection.execute(
                    tables.project_check_items.update()
                    .where(
                        tables.project_check_items.c.tenant_id == tenant_id,
                        tables.project_check_items.c.id == item_id,
                    )
                    .values(
                        status=status,
                        evidence_reference=evidence_reference,
                        completion_note=note,
                        completed_by_user_id=actor_user_id,
                        completed_at=now,
                        updated_at=now,
                    )
                    .returning(tables.project_check_items)
                )
                .mappings()
                .one()
            )
            self._record(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                entity_id=item_id,
                record_type="project_item",
                action=status,
                count=1,
                before={"status": before["status"]},
                after={
                    "status": row["status"],
                    "is_gate": row["is_gate"],
                    "evidence_reference": row["evidence_reference"],
                },
            )
            return dict(row)
