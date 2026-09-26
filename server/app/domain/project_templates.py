"""Product-specific, immutable project template revisions and explicit adoption."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, select

from app.db.schema import tables
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.workflow_templates import NPD_WORKFLOW_TEMPLATE, StageTemplate, WorkflowTemplate
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

CATALOG_PATH = Path(__file__).with_suffix("")


class ProjectTemplateError(ValueError):
    pass


class ProjectTemplateSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    template_id: str = Field(min_length=1, max_length=128)
    version: int = Field(gt=0)
    features: dict[str, bool] = Field(default_factory=dict)
    language: str = Field(default="zh-CN", pattern=r"^(zh-CN|en)$")
    source_version_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=5000)


def catalog(
    *, connection: Connection | None = None, tenant_id: UUID | None = None
) -> list[dict[str, Any]]:
    builtins = [json.loads(path.read_text()) for path in sorted(CATALOG_PATH.glob("*.json"))]
    if connection is not None and tenant_id is not None:
        from app.domain.process_templates import released_catalog

        return builtins + released_catalog(connection, tenant_id)
    return builtins


class ProjectCreationTemplate(ProjectTemplateSelection):
    """The creation action explicitly adopts this immutable product configuration."""

    source_version_id: None = None


def workflow_from_snapshot(snapshot: dict[str, Any]) -> WorkflowTemplate:
    base = NPD_WORKFLOW_TEMPLATE
    stages = snapshot["stages"]
    if snapshot["workflow"] != base.code or [
        (stage["code"], stage["sequence"]) for stage in stages
    ] != [(stage.code, stage.sequence) for stage in base.stages]:
        raise ProjectTemplateError("此模板的阶段类型或顺序尚未接通项目硬闸")
    if snapshot["gate_policy"] != "existing-versioned-slot-policy":
        raise ProjectTemplateError("此模板的审批规则尚未接通")
    language = snapshot["language"]
    return WorkflowTemplate(
        code=base.code,
        name=snapshot["name_en"] if language == "en" else snapshot["name"],
        description=base.description,
        version=snapshot["version"],
        stages=tuple(
            StageTemplate(
                stage["code"],
                stage["name_en"] if language == "en" else stage["name"],
                stage.get("description") or original.description,
                stage["sequence"],
            )
            for stage, original in zip(stages, base.stages, strict=True)
        ),
    )


def adopt_at_creation(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    actor_user_id: UUID,
    selection: ProjectCreationTemplate,
    snapshot: dict[str, Any],
) -> None:
    row = (
        connection.execute(
            tables.project_template_versions.insert()
            .values(
                id=uuid4(),
                tenant_id=tenant_id,
                project_id=project_id,
                revision=1,
                template_id=selection.template_id,
                template_version=selection.version,
                snapshot=snapshot,
                digest=snapshot["digest"],
                source_version_id=None,
                status="active",
                proposed_by_user_id=actor_user_id,
                decided_by_user_id=actor_user_id,
                decided_at=datetime.now(UTC),
                reason=selection.reason,
                difference=difference(None, snapshot) | {"adoption_scope": "project_creation"},
            )
            .returning(tables.project_template_versions)
        )
        .mappings()
        .one()
    )
    from app.domain.process_template_gates import adopt

    adopt(
        connection,
        tenant_id=tenant_id,
        project_id=project_id,
        actor_user_id=actor_user_id,
        snapshot=snapshot,
        template_version_id=row["id"],
    )
    _event(connection, tenant_id, project_id, actor_user_id, "confirmed", row)


def compile_selection(
    selection: ProjectTemplateSelection, *, templates: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    template = next(
        (
            item
            for item in (catalog() if templates is None else templates)
            if item["id"] == selection.template_id and item["version"] == selection.version
        ),
        None,
    )
    if template is None:
        raise ProjectTemplateError("产品模板或版本不存在")
    if selection.features.keys() - template["features"].keys():
        raise ProjectTemplateError("新增功能须先登记模板差异，不能写入未知功能")
    features = {
        key: selection.features.get(key, value["default"])
        for key, value in template["features"].items()
    }
    selected = [
        task
        for task in template["tasks"]
        if all(features[key] for key in task["required_features"])
    ]
    keys = {task["code"] for task in selected}
    if len(keys) != len(selected):
        raise ProjectTemplateError("模板任务标识重复")
    all_keys = {task["code"] for task in template["tasks"]}
    for task in template["tasks"]:
        if set(task["depends_on"]) - all_keys:
            raise ProjectTemplateError("模板依赖指向未知任务")
    selected = [
        {**task, "depends_on": [key for key in task["depends_on"] if key in keys]}
        for task in selected
    ]
    pending = {task["code"]: set(task["depends_on"]) for task in selected}
    while pending:
        ready = {key for key, dependencies in pending.items() if not dependencies}
        if not ready:
            raise ProjectTemplateError("模板任务依赖存在循环")
        pending = {
            key: dependencies - ready for key, dependencies in pending.items() if key not in ready
        }
    payload = {
        **template,
        "feature_values": features,
        "language": selection.language,
        "tasks": selected,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return {**payload, "digest": digest}


def active_version(connection: Connection, *, tenant_id: UUID, project_id: UUID) -> Any:
    table = tables.project_template_versions
    return (
        connection.execute(
            select(table).where(
                table.c.tenant_id == tenant_id,
                table.c.project_id == project_id,
                table.c.status == "active",
            )
        )
        .mappings()
        .one_or_none()
    )


def difference(before: dict[str, Any] | None, after: dict[str, Any]) -> dict[str, Any]:
    old = before or {}
    old_tasks = {task["code"]: task for task in old.get("tasks", [])}
    new_tasks = {task["code"]: task for task in after["tasks"]}
    return {
        "product_type": {"before": old.get("product_type"), "after": after["product_type"]},
        "features": [
            {"key": key, "before": old.get("feature_values", {}).get(key), "after": value}
            for key, value in after["feature_values"].items()
            if old.get("feature_values", {}).get(key) != value
        ],
        "added_tasks": sorted(new_tasks.keys() - old_tasks.keys()),
        "removed_tasks": sorted(old_tasks.keys() - new_tasks.keys()),
        "changed_tasks": sorted(
            key for key in old_tasks.keys() & new_tasks.keys() if old_tasks[key] != new_tasks[key]
        ),
        "language_changed": old.get("language") != after["language"],
        "existing_plan_policy": (
            "已有阶段、Gate签核要求、提醒规则、任务、测试计划与正式基线保留原版本；另行审阅并应用差异"
        ),
    }


def _event(
    connection: Connection,
    tenant_id: UUID,
    project_id: UUID,
    actor_user_id: UUID,
    action: str,
    row: Any,
) -> None:
    project_status = connection.execute(
        select(tables.projects.c.status).where(
            tables.projects.c.tenant_id == tenant_id, tables.projects.c.id == project_id
        )
    ).scalar_one()
    EventAuditWriter(
        connection, tenant_id=tenant_id, project_id=project_id, actor_user_id=actor_user_id
    ).record(
        EventDraft(
            event_id=f"project-template:{row['id']}:{action}:{uuid4()}",
            event_type="PROJECT_UPDATED",
            source="project_service",
            entity_id=project_id,
            payload={"changed_fields": ["product_template"], "status": project_status},
        ),
        AuditDraft(
            action=f"project.template.{action}",
            after_snapshot={
                "version_id": str(row["id"]),
                "revision": row["revision"],
                "template_id": row["template_id"],
                "digest": row["digest"],
                "status": row["status"],
                "reason": row["reason"],
            },
        ),
    )


class ProjectTemplateService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _lock(connection: Connection, tenant_id: UUID, project_id: UUID) -> None:
        if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
            raise ProjectTemplateError("项目不存在")
        status = connection.execute(
            select(tables.projects.c.status).where(
                tables.projects.c.tenant_id == tenant_id, tables.projects.c.id == project_id
            )
        ).scalar_one()
        if status in {"archived", "completed"}:
            raise ProjectTemplateError("已结项或归档项目不能切换产品模板")

    def get(self, *, tenant_id: UUID, project_id: UUID) -> dict[str, Any]:
        table = tables.project_template_versions
        with self.engine.connect() as connection:
            rows = list(
                connection.execute(
                    select(table)
                    .where(table.c.tenant_id == tenant_id, table.c.project_id == project_id)
                    .order_by(table.c.revision.desc())
                ).mappings()
            )
            active = next((dict(row) for row in rows if row["status"] == "active"), None)
            from app.domain.process_template_reminders import project_policy

            reminder_rules, reminder_source = project_policy(connection, tenant_id, project_id)
            return {
                "creation_reminder_policy": reminder_rules.model_dump(mode="json"),
                "creation_reminder_source": reminder_source,
                "active": active,
                "versions": [dict(row) for row in rows],
                "catalog": catalog(connection=connection, tenant_id=tenant_id),
            }

    def propose(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        selection: ProjectTemplateSelection,
    ) -> dict[str, Any]:
        table = tables.project_template_versions
        with self.engine.begin() as connection:
            self._lock(connection, tenant_id, project_id)
            snapshot = compile_selection(
                selection, templates=catalog(connection=connection, tenant_id=tenant_id)
            )
            active = active_version(connection, tenant_id=tenant_id, project_id=project_id)
            if selection.source_version_id != (active["id"] if active else None):
                raise ProjectTemplateError("当前模板已变化，请刷新并重新生成差异")
            workflow_code = connection.execute(
                select(tables.workflows.c.code)
                .join(tables.projects, tables.projects.c.workflow_id == tables.workflows.c.id)
                .where(tables.projects.c.tenant_id == tenant_id, tables.projects.c.id == project_id)
            ).scalar_one()
            if not (
                workflow_code == snapshot["workflow"]
                or workflow_code.startswith(snapshot["workflow"] + "-")
            ):
                raise ProjectTemplateError("所选模板不匹配项目现有工作流")
            if active and active["digest"] == snapshot["digest"]:
                return dict(active)
            # Repeated clicks return the same unreviewed proposal.
            existing = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == tenant_id,
                        table.c.project_id == project_id,
                        table.c.status == "proposed",
                        table.c.digest == snapshot["digest"],
                        table.c.source_version_id.is_(None)
                        if active is None
                        else table.c.source_version_id == active["id"],
                    )
                )
                .mappings()
                .first()
            )
            if existing:
                return dict(existing)
            latest = (
                connection.execute(
                    select(table.c.revision)
                    .where(table.c.tenant_id == tenant_id, table.c.project_id == project_id)
                    .order_by(table.c.revision.desc())
                    .limit(1)
                ).scalar_one_or_none()
                or 0
            )
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        project_id=project_id,
                        revision=latest + 1,
                        template_id=selection.template_id,
                        template_version=selection.version,
                        snapshot=snapshot,
                        digest=snapshot["digest"],
                        source_version_id=selection.source_version_id,
                        status="proposed",
                        proposed_by_user_id=actor_user_id,
                        reason=selection.reason,
                        difference=difference(
                            dict(active["snapshot"]) if active else None, snapshot
                        ),
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            _event(connection, tenant_id, project_id, actor_user_id, "proposed", row)
            return dict(row)

    def decide(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        version_id: UUID,
        confirm: bool,
    ) -> dict[str, Any]:
        table = tables.project_template_versions
        with self.engine.begin() as connection:
            self._lock(connection, tenant_id, project_id)
            row = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == tenant_id,
                        table.c.project_id == project_id,
                        table.c.id == version_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProjectTemplateError("模板候选不存在")
            if row["status"] == ("active" if confirm else "rejected"):
                return dict(row)
            if row["status"] != "proposed":
                raise ProjectTemplateError("只能确认或拒绝待审模板候选")
            active = active_version(connection, tenant_id=tenant_id, project_id=project_id)
            if confirm:
                if row["source_version_id"] != (active["id"] if active else None):
                    raise ProjectTemplateError("候选依据已过期，请重新生成差异")
                if active:
                    connection.execute(
                        table.update().where(table.c.id == active["id"]).values(status="superseded")
                    )
            after = (
                connection.execute(
                    table.update()
                    .where(table.c.id == version_id)
                    .values(
                        status="active" if confirm else "rejected",
                        decided_by_user_id=actor_user_id,
                        decided_at=datetime.now(UTC),
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            _event(
                connection,
                tenant_id,
                project_id,
                actor_user_id,
                "confirmed" if confirm else "rejected",
                after,
            )
            return dict(after)
