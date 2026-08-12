"""Frozen CEHub v1 source-to-PDOS mapping contract."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import Connection, Engine, bindparam, select, text
from sqlalchemy.engine import RowMapping, make_url

from app.db.schema import tables
from app.db.url import psycopg_database_url
from app.domain.workflow_templates import (
    NPD_WORKFLOW_TEMPLATE,
    OBT_WORKFLOW_TEMPLATE,
    WorkflowTemplate,
)

SOURCE_SYSTEM = "cehub-v3"
SOURCE_SCHEMA_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_USER_ROLE_MAP = {
    "owner": "admin",
    "admin": "admin",
    "member": "engineer",
    "user": "engineer",
    "viewer": "engineer",
    "external": "supplier",
}
_GATE_STATUS_MAP = {
    "approved": "approved",
    "conditional": "reviewing",
    "rejected": "rejected",
}
_ENTITY_COUNT_KEYS = (
    "users",
    "projects",
    "tasks",
    "gate_reviews",
    "file_references",
)
_ENTITY_TO_COUNT_KEY = {
    "user": "users",
    "project": "projects",
    "task": "tasks",
    "gate_review": "gate_reviews",
    "file_reference": "file_references",
}
_WORKFLOW_TEMPLATES: dict[str, WorkflowTemplate] = {
    NPD_WORKFLOW_TEMPLATE.code: NPD_WORKFLOW_TEMPLATE,
    OBT_WORKFLOW_TEMPLATE.code: OBT_WORKFLOW_TEMPLATE,
}
_SOURCE_TABLES = (
    "users",
    "projects",
    "project_tasks",
    "project_gate_reviews",
    "project_files",
)
_TASK_STATUSES = frozenset(
    {"todo", "in_progress", "blocked", "done", "skipped", "pending_approval"}
)
_TASK_PRIORITIES = frozenset({"low", "medium", "high", "critical"})


@dataclass(frozen=True)
class SourceSnapshot:
    requested_project_ids: tuple[str, ...]
    users: tuple[dict[str, Any], ...]
    projects: tuple[dict[str, Any], ...]
    tasks: tuple[dict[str, Any], ...]
    gate_reviews: tuple[dict[str, Any], ...]
    file_references: tuple[dict[str, Any], ...]
    fingerprint: str


@dataclass(frozen=True)
class MigrationError:
    code: str
    entity_type: str
    source_id: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "entity_type": self.entity_type,
            "source_id": self.source_id,
            "message": self.message,
        }


@dataclass(frozen=True)
class MigrationReport:
    mode: str
    status: str
    source_system: str
    source_schema: str
    selected_project_ids: tuple[str, ...]
    source_fingerprint: str
    source_counts: dict[str, int]
    created_counts: dict[str, int]
    skipped_counts: dict[str, int]
    target_writes: int
    errors: tuple[MigrationError, ...]
    samples: tuple[dict[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "status": self.status,
            "source_system": self.source_system,
            "source_schema": self.source_schema,
            "selected_project_ids": list(self.selected_project_ids),
            "source_fingerprint": self.source_fingerprint,
            "source_counts": self.source_counts,
            "created_counts": self.created_counts,
            "skipped_counts": self.skipped_counts,
            "target_writes": self.target_writes,
            "errors": [error.to_dict() for error in self.errors],
            "samples": list(self.samples),
        }


class MigrationValidationError(ValueError):
    def __init__(self, report: MigrationReport) -> None:
        self.report = report
        super().__init__("CEHub migration validation failed")


def cehub_psycopg_database_url(value: str) -> str:
    """Remove the Prisma-only libpq flag while preserving real PostgreSQL options."""
    url = make_url(value)
    query = {key: nested for key, nested in url.query.items() if key.lower() != "uselibpqcompat"}
    normalized = url.set(query=query).render_as_string(hide_password=False)
    return psycopg_database_url(normalized)


class CeHubSourceAdapter:
    """Reads one repeatable, read-only snapshot from the legacy PostgreSQL schema."""

    def __init__(self, engine: Engine, *, source_schema: str) -> None:
        self._engine = engine
        self._schema = validate_source_schema(source_schema)

    def read_snapshot(self, *, project_ids: tuple[str, ...]) -> SourceSnapshot:
        normalized_refs = tuple(dict.fromkeys(project_id.strip() for project_id in project_ids))
        if not normalized_refs or any(not project_id for project_id in normalized_refs):
            raise ValueError("at least one nonblank CEHub project id or project number is required")
        connection = self._engine.connect().execution_options(isolation_level="REPEATABLE READ")
        try:
            with connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                self._assert_readonly_role(connection)
                candidates = self._project_rows(connection, normalized_refs)
                projects = self._resolve_project_rows(candidates, normalized_refs)
                resolved_ids = tuple(str(row["source_id"]) for row in projects)
                tasks_rows = self._scoped_rows(connection, "project_tasks", resolved_ids)
                gate_rows = self._scoped_rows(connection, "project_gate_reviews", resolved_ids)
                file_rows = self._scoped_rows(connection, "project_files", resolved_ids)
                users = self._user_rows(
                    connection,
                    _required_user_ids(projects, tasks_rows, gate_rows, file_rows),
                )
        finally:
            connection.close()

        project_dicts = _hash_rows(projects)
        task_dicts = _hash_rows(tasks_rows)
        gate_dicts = _hash_rows(gate_rows)
        file_dicts = _hash_rows(file_rows)
        user_dicts = _hash_rows(users)
        snapshot_payload = {
            "requested_project_ids": resolved_ids,
            "users": user_dicts,
            "projects": project_dicts,
            "tasks": task_dicts,
            "gate_reviews": gate_dicts,
            "file_references": file_dicts,
        }
        return SourceSnapshot(
            requested_project_ids=resolved_ids,
            users=user_dicts,
            projects=project_dicts,
            tasks=task_dicts,
            gate_reviews=gate_dicts,
            file_references=file_dicts,
            fingerprint=_content_hash(snapshot_payload),
        )

    def _assert_readonly_role(self, connection: Connection) -> None:
        default_read_only = connection.execute(
            text("SELECT current_setting('default_transaction_read_only') = 'on'")
        ).scalar_one()
        privileges = []
        for table_name in _SOURCE_TABLES:
            qualified_name = f'"{self._schema}"."{table_name}"'
            privileges.append(
                connection.execute(
                    text(
                        """
                        SELECT has_table_privilege(current_user, :table_name, 'SELECT')
                                   AS can_select,
                               has_table_privilege(
                                   current_user,
                                   :table_name,
                                   'INSERT,UPDATE,DELETE,TRUNCATE'
                               ) AS can_write
                        """
                    ),
                    {"table_name": qualified_name},
                )
                .mappings()
                .one()
            )
        if not default_read_only or any(
            not bool(privilege["can_select"]) or bool(privilege["can_write"])
            for privilege in privileges
        ):
            raise ValueError(
                "CEHub source must use an independent read-only role with SELECT-only "
                "access to the five migration tables and default_transaction_read_only=on"
            )

    def _project_rows(
        self, connection: Connection, project_refs: tuple[str, ...]
    ) -> tuple[RowMapping, ...]:
        statement = text(
            f'''
            SELECT id AS source_id, name, "projectNumber" AS project_number,
                   category, "pmUserId" AS pm_user_id, description,
                   "currentPhase" AS current_phase, "startDate" AS start_date,
                   "targetDate" AS target_date, "createdBy" AS created_by,
                   archived, lifecycle, "createdAt" AS created_at,
                   "updatedAt" AS updated_at
              FROM "{self._schema}"."projects"
             WHERE id IN :project_ids OR "projectNumber" IN :project_numbers
             ORDER BY id
            '''
        ).bindparams(
            bindparam("project_ids", expanding=True),
            bindparam("project_numbers", expanding=True),
        )
        return tuple(
            connection.execute(
                statement,
                {"project_ids": project_refs, "project_numbers": project_refs},
            ).mappings()
        )

    @staticmethod
    def _resolve_project_rows(
        candidates: tuple[RowMapping, ...],
        project_refs: tuple[str, ...],
    ) -> tuple[RowMapping, ...]:
        by_id = {str(row["source_id"]): row for row in candidates}
        by_number: dict[str, list[RowMapping]] = {}
        for row in candidates:
            by_number.setdefault(str(row["project_number"]), []).append(row)

        resolved: list[RowMapping] = []
        resolved_ids: set[str] = set()
        for project_ref in project_refs:
            selected = by_id.get(project_ref)
            if selected is None:
                number_matches = by_number.get(project_ref, [])
                if not number_matches:
                    raise ValueError(f"CEHub project selector was not found: {project_ref}")
                if len(number_matches) > 1:
                    raise ValueError(
                        f"CEHub project number is ambiguous; use the source id: {project_ref}"
                    )
                selected = number_matches[0]
            source_id = str(selected["source_id"])
            if source_id not in resolved_ids:
                resolved.append(selected)
                resolved_ids.add(source_id)
        return tuple(resolved)

    def _scoped_rows(
        self,
        connection: Connection,
        table_name: str,
        project_ids: tuple[str, ...],
    ) -> tuple[RowMapping, ...]:
        queries = {
            "project_tasks": f'''
                SELECT CAST(id AS text) AS source_id, "projectId" AS project_id,
                       "phaseId" AS phase_id, "taskId" AS task_id, completed,
                       instructions, completion_note, "assigneeUserId" AS assignee_user_id,
                       "dueDate" AS due_date, "startDate" AS start_date,
                       "actualStartedAt" AS actual_started_at, status, blocked_reason,
                       priority, "completedAt" AS completed_at, "createdAt" AS created_at,
                       "updatedAt" AS updated_at
                  FROM "{self._schema}"."project_tasks"
                 WHERE "projectId" IN :project_ids
                 ORDER BY "projectId", id
            ''',
            "project_gate_reviews": f'''
                SELECT CAST(id AS text) AS source_id, "projectId" AS project_id,
                       "phaseId" AS phase_id, "phaseName" AS phase_name,
                       "gateName" AS gate_name, "reviewDate" AS review_date,
                       participants, decision, conditions, notes,
                       "roundNumber" AS round_number, "createdBy" AS created_by,
                       "createdAt" AS created_at, "updatedAt" AS updated_at
                  FROM "{self._schema}"."project_gate_reviews"
                 WHERE "projectId" IN :project_ids
                 ORDER BY "projectId", "phaseId", "roundNumber", id
            ''',
            "project_files": f'''
                SELECT CAST(id AS text) AS source_id, "projectId" AS project_id,
                       "phaseId" AS phase_id, "taskId" AS task_id, visibility,
                       "securityClassification" AS security_classification, name,
                       "mimeType" AS mime_type, size, "storageKey" AS storage_key,
                       "storageUrl" AS storage_url, "uploadedBy" AS uploaded_by,
                       "createdAt" AS created_at
                  FROM "{self._schema}"."project_files"
                 WHERE "projectId" IN :project_ids
                 ORDER BY "projectId", id
            ''',
        }
        statement = text(queries[table_name]).bindparams(bindparam("project_ids", expanding=True))
        return tuple(connection.execute(statement, {"project_ids": project_ids}).mappings())

    def _user_rows(
        self, connection: Connection, user_ids: tuple[int, ...]
    ) -> tuple[RowMapping, ...]:
        if not user_ids:
            return ()
        statement = text(
            f'''
            SELECT CAST(id AS text) AS source_id,
                   COALESCE(username, "openId") AS username,
                   COALESCE(name, username, "openId") AS display_name,
                   email, role, "createdAt" AS created_at, "updatedAt" AS updated_at
              FROM "{self._schema}"."users"
             WHERE id IN :user_ids
             ORDER BY id
            '''
        ).bindparams(bindparam("user_ids", expanding=True))
        return tuple(connection.execute(statement, {"user_ids": user_ids}).mappings())


def _required_user_ids(
    projects: tuple[RowMapping, ...],
    tasks_rows: tuple[RowMapping, ...],
    gate_rows: tuple[RowMapping, ...],
    file_rows: tuple[RowMapping, ...],
) -> tuple[int, ...]:
    values: set[int] = set()
    for row in projects:
        for key in ("pm_user_id", "created_by"):
            if row[key] is not None:
                values.add(int(row[key]))
    for rows, key in (
        (tasks_rows, "assignee_user_id"),
        (gate_rows, "created_by"),
        (file_rows, "uploaded_by"),
    ):
        for row in rows:
            if row[key] is not None:
                values.add(int(row[key]))
    return tuple(sorted(values))


def _json_safe(value: object) -> object:
    if isinstance(value, datetime):
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return normalized.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(nested) for key, nested in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _content_hash(value: object) -> str:
    payload = json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _hash_rows(rows: tuple[RowMapping, ...]) -> tuple[dict[str, Any], ...]:
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["source_id"] = str(item["source_id"])
        item["source_hash"] = _content_hash(item)
        result.append(item)
    return tuple(result)


def _target_id(tenant_id: UUID, entity_type: str, source_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"pdos:{tenant_id}:{SOURCE_SYSTEM}:{entity_type}:{source_id}")


def _workflow_id(tenant_id: UUID, source_project_id: str) -> UUID:
    return _target_id(tenant_id, "workflow", source_project_id)


def _stage_id(tenant_id: UUID, source_project_id: str, stage_code: str) -> UUID:
    return _target_id(tenant_id, "stage", f"{source_project_id}:{stage_code}")


def _gate_id(tenant_id: UUID, source_project_id: str, stage_code: str) -> UUID:
    return _target_id(tenant_id, "gate", f"{source_project_id}:{stage_code}")


def _legacy_username(source_id: str, username: object) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", str(username).strip()).strip("-")
    normalized = normalized or "user"
    prefix = f"cehub-{source_id}-"
    return f"{prefix}{normalized[: 64 - len(prefix)]}"


def _parse_date(value: object, *, field: str, source_id: str) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ValueError(f"{source_id}: invalid {field}: {value}") from exc


def _parse_datetime(value: object, *, field: str, source_id: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    else:
        raw = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            try:
                parsed = datetime.combine(date.fromisoformat(raw[:10]), time.min)
            except ValueError:
                raise ValueError(f"{source_id}: invalid {field}: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _source_counts(snapshot: SourceSnapshot) -> dict[str, int]:
    return {
        "users": len(snapshot.users),
        "projects": len(snapshot.projects),
        "tasks": len(snapshot.tasks),
        "gate_reviews": len(snapshot.gate_reviews),
        "file_references": len(snapshot.file_references),
    }


def _empty_counts() -> dict[str, int]:
    return dict.fromkeys(_ENTITY_COUNT_KEYS, 0)


def _records_by_entity(
    snapshot: SourceSnapshot,
) -> tuple[tuple[str, dict[str, Any]], ...]:
    return tuple(
        (entity_type, row)
        for entity_type, rows in (
            ("user", snapshot.users),
            ("project", snapshot.projects),
            ("task", snapshot.tasks),
            ("gate_review", snapshot.gate_reviews),
            ("file_reference", snapshot.file_references),
        )
        for row in rows
    )


def _planned_counts(
    snapshot: SourceSnapshot,
    mappings: dict[tuple[str, str], tuple[UUID, str]],
) -> tuple[dict[str, int], dict[str, int]]:
    created_counts = _empty_counts()
    skipped_counts = _empty_counts()
    for entity_type, row in _records_by_entity(snapshot):
        count_key = _ENTITY_TO_COUNT_KEY[entity_type]
        if (entity_type, str(row["source_id"])) in mappings:
            skipped_counts[count_key] += 1
        else:
            created_counts[count_key] += 1
    return created_counts, skipped_counts


def _existing_mappings(
    connection: Connection, *, tenant_id: UUID
) -> dict[tuple[str, str], tuple[UUID, str]]:
    rows = connection.execute(
        select(
            tables.migration_mappings.c.entity_type,
            tables.migration_mappings.c.source_id,
            tables.migration_mappings.c.target_id,
            tables.migration_mappings.c.source_hash,
        ).where(
            tables.migration_mappings.c.tenant_id == tenant_id,
            tables.migration_mappings.c.source_system == SOURCE_SYSTEM,
        )
    )
    return {(row.entity_type, row.source_id): (row.target_id, row.source_hash) for row in rows}


def _mapping_target(
    *,
    mappings: dict[tuple[str, str], tuple[UUID, str]],
    tenant_id: UUID,
    entity_type: str,
    source_id: object,
) -> UUID:
    key = (entity_type, str(source_id))
    existing = mappings.get(key)
    return existing[0] if existing is not None else _target_id(tenant_id, *key)


def _append_error(
    errors: list[MigrationError],
    *,
    code: str,
    entity_type: str,
    source_id: object,
    message: str,
) -> None:
    errors.append(
        MigrationError(
            code=code,
            entity_type=entity_type,
            source_id=str(source_id),
            message=message,
        )
    )


def _target_table_for_entity(entity_type: str) -> Any:
    return {
        "user": tables.users,
        "project": tables.projects,
        "task": tables.tasks,
        "gate_review": tables.gate_history_records,
        "file_reference": tables.external_file_references,
    }[entity_type]


def _validate_snapshot(
    connection: Connection,
    *,
    snapshot: SourceSnapshot,
    tenant_id: UUID,
    actor_user_id: UUID,
    mappings: dict[tuple[str, str], tuple[UUID, str]],
) -> tuple[MigrationError, ...]:
    errors: list[MigrationError] = []
    tenant = connection.execute(
        select(tables.tenants.c.status).where(tables.tenants.c.id == tenant_id)
    ).scalar_one_or_none()
    actor = connection.execute(
        select(tables.users.c.is_active).where(
            tables.users.c.tenant_id == tenant_id,
            tables.users.c.id == actor_user_id,
        )
    ).scalar_one_or_none()
    if tenant != "active":
        _append_error(
            errors,
            code="TARGET_CONTEXT_INVALID",
            entity_type="tenant",
            source_id=tenant_id,
            message="target tenant does not exist or is not active",
        )
    if actor is not True:
        _append_error(
            errors,
            code="TARGET_CONTEXT_INVALID",
            entity_type="user",
            source_id=actor_user_id,
            message="migration actor does not exist, is cross-tenant, or is inactive",
        )

    found_projects = {str(row["source_id"]) for row in snapshot.projects}
    for source_id in sorted(set(snapshot.requested_project_ids) - found_projects):
        _append_error(
            errors,
            code="SOURCE_PROJECT_MISSING",
            entity_type="project",
            source_id=source_id,
            message="requested CEHub project was not found in the read-only snapshot",
        )

    user_ids = {str(row["source_id"]) for row in snapshot.users}
    required_users: set[str] = set()
    for row in snapshot.projects:
        for key in ("pm_user_id", "created_by"):
            if row[key] is not None:
                required_users.add(str(row[key]))
    for rows, key in (
        (snapshot.tasks, "assignee_user_id"),
        (snapshot.gate_reviews, "created_by"),
        (snapshot.file_references, "uploaded_by"),
    ):
        for row in rows:
            if row[key] is not None:
                required_users.add(str(row[key]))
    for source_id in sorted(required_users - user_ids):
        _append_error(
            errors,
            code="SOURCE_REFERENCE_MISSING",
            entity_type="user",
            source_id=source_id,
            message="a selected CEHub record references a missing user",
        )

    for row in snapshot.users:
        source_id = str(row["source_id"])
        try:
            map_user_role(str(row["role"]))
        except ValueError as exc:
            _append_error(
                errors,
                code="UNSUPPORTED_VALUE",
                entity_type="user",
                source_id=source_id,
                message=str(exc),
            )
        username = _legacy_username(source_id, row["username"])
        existing_user_id = connection.execute(
            select(tables.users.c.id).where(
                tables.users.c.tenant_id == tenant_id,
                tables.users.c.username == username,
            )
        ).scalar_one_or_none()
        mapped_target = mappings.get(("user", source_id), (None, ""))[0]
        if existing_user_id is not None and existing_user_id != mapped_target:
            _append_error(
                errors,
                code="TARGET_CONFLICT",
                entity_type="user",
                source_id=source_id,
                message=f"target username already exists: {username}",
            )
        email = row["email"]
        if email:
            email_owner = connection.execute(
                select(tables.users.c.id).where(
                    tables.users.c.tenant_id == tenant_id,
                    tables.users.c.email == str(email),
                )
            ).scalar_one_or_none()
            if email_owner is not None and email_owner != mapped_target:
                _append_error(
                    errors,
                    code="TARGET_CONFLICT",
                    entity_type="user",
                    source_id=source_id,
                    message=f"target email already exists: {email}",
                )

    seen_codes: set[str] = set()
    project_templates: dict[str, WorkflowTemplate] = {}
    for row in snapshot.projects:
        source_id = str(row["source_id"])
        category = str(row["category"])
        template = _WORKFLOW_TEMPLATES.get(category)
        if template is None:
            _append_error(
                errors,
                code="UNSUPPORTED_PROJECT_CATEGORY",
                entity_type="project",
                source_id=source_id,
                message=(f"migration v1 supports npd and obt project categories; got {category}"),
            )
        else:
            project_templates[source_id] = template
        stage_codes = (
            frozenset(stage.code for stage in template.stages) if template is not None else ()
        )
        if template is not None and row["current_phase"] not in stage_codes:
            _append_error(
                errors,
                code="UNSUPPORTED_STAGE",
                entity_type="project",
                source_id=source_id,
                message=f"unknown {category.upper()} stage: {row['current_phase']}",
            )
        try:
            map_project_status(archived=bool(row["archived"]), lifecycle=str(row["lifecycle"]))
            start_date = _parse_date(row["start_date"], field="start_date", source_id=source_id)
            target_date = _parse_date(row["target_date"], field="target_date", source_id=source_id)
            if start_date is not None and target_date is not None and target_date < start_date:
                raise ValueError(f"{source_id}: target_date precedes start_date")
            code = normalize_project_code(
                project_number=str(row["project_number"] or ""), source_id=source_id
            )
        except ValueError as exc:
            _append_error(
                errors,
                code="UNSUPPORTED_VALUE",
                entity_type="project",
                source_id=source_id,
                message=str(exc),
            )
            continue
        if code in seen_codes:
            _append_error(
                errors,
                code="SOURCE_DUPLICATE",
                entity_type="project",
                source_id=source_id,
                message=f"duplicate project code in selected snapshot: {code}",
            )
        seen_codes.add(code)
        existing_project_id = connection.execute(
            select(tables.projects.c.id).where(
                tables.projects.c.tenant_id == tenant_id,
                tables.projects.c.code == code,
            )
        ).scalar_one_or_none()
        mapped_target = mappings.get(("project", source_id), (None, ""))[0]
        if existing_project_id is not None and existing_project_id != mapped_target:
            _append_error(
                errors,
                code="TARGET_CONFLICT",
                entity_type="project",
                source_id=source_id,
                message=f"target project code already exists: {code}",
            )

    for row in snapshot.tasks:
        source_id = str(row["source_id"])
        project_id = str(row["project_id"])
        template = project_templates.get(project_id)
        if project_id not in found_projects:
            _append_error(
                errors,
                code="SOURCE_REFERENCE_MISSING",
                entity_type="task",
                source_id=source_id,
                message="task references a project outside the selected snapshot",
            )
        if template is not None and row["phase_id"] not in {
            stage.code for stage in template.stages
        }:
            _append_error(
                errors,
                code="UNSUPPORTED_STAGE",
                entity_type="task",
                source_id=source_id,
                message=f"unknown {template.code.upper()} stage: {row['phase_id']}",
            )
        if row["status"] not in _TASK_STATUSES or row["priority"] not in _TASK_PRIORITIES:
            _append_error(
                errors,
                code="UNSUPPORTED_VALUE",
                entity_type="task",
                source_id=source_id,
                message=f"unsupported task status/priority: {row['status']}/{row['priority']}",
            )
        try:
            start_date = _parse_date(row["start_date"], field="start_date", source_id=source_id)
            due_date = _parse_date(row["due_date"], field="due_date", source_id=source_id)
            if start_date is not None and due_date is not None and due_date < start_date:
                raise ValueError(f"{source_id}: due_date precedes start_date")
        except ValueError as exc:
            _append_error(
                errors,
                code="UNSUPPORTED_VALUE",
                entity_type="task",
                source_id=source_id,
                message=str(exc),
            )

    for row in snapshot.gate_reviews:
        source_id = str(row["source_id"])
        project_id = str(row["project_id"])
        template = project_templates.get(project_id)
        if project_id not in found_projects:
            _append_error(
                errors,
                code="SOURCE_REFERENCE_MISSING",
                entity_type="gate_review",
                source_id=source_id,
                message="Gate review references a project outside the selected snapshot",
            )
        if template is not None and row["phase_id"] not in {
            stage.code for stage in template.stages
        }:
            _append_error(
                errors,
                code="UNSUPPORTED_STAGE",
                entity_type="gate_review",
                source_id=source_id,
                message=f"unknown {template.code.upper()} stage: {row['phase_id']}",
            )
        try:
            map_gate_decision(str(row["decision"]))
            _parse_datetime(row["review_date"], field="review_date", source_id=source_id)
            if int(row["round_number"]) <= 0:
                raise ValueError(f"{source_id}: round_number must be positive")
        except ValueError as exc:
            _append_error(
                errors,
                code="UNSUPPORTED_VALUE",
                entity_type="gate_review",
                source_id=source_id,
                message=str(exc),
            )

    for row in snapshot.file_references:
        source_id = str(row["source_id"])
        project_id = str(row["project_id"])
        template = project_templates.get(project_id)
        if project_id not in found_projects:
            _append_error(
                errors,
                code="SOURCE_REFERENCE_MISSING",
                entity_type="file_reference",
                source_id=source_id,
                message="file reference points outside the selected project snapshot",
            )
        if (
            template is not None
            and row["phase_id"] is not None
            and row["phase_id"] not in {stage.code for stage in template.stages}
        ):
            _append_error(
                errors,
                code="UNSUPPORTED_STAGE",
                entity_type="file_reference",
                source_id=source_id,
                message=f"unknown {template.code.upper()} stage: {row['phase_id']}",
            )
        if not str(row["storage_key"]).strip() or not str(row["name"]).strip():
            _append_error(
                errors,
                code="SOURCE_VALUE_INVALID",
                entity_type="file_reference",
                source_id=source_id,
                message="file name and OSS object key must be nonblank",
            )
        if int(row["size"]) < 0:
            _append_error(
                errors,
                code="SOURCE_VALUE_INVALID",
                entity_type="file_reference",
                source_id=source_id,
                message="file size must be nonnegative",
            )

    for entity_type, row in _records_by_entity(snapshot):
        source_id = str(row["source_id"])
        existing = mappings.get((entity_type, source_id))
        if existing is None:
            continue
        target_id, source_hash = existing
        if source_hash != row["source_hash"]:
            _append_error(
                errors,
                code="SOURCE_CHANGED",
                entity_type=entity_type,
                source_id=source_id,
                message="source row changed after its first successful import",
            )
            continue
        target_table = _target_table_for_entity(entity_type)
        target_exists = connection.execute(
            select(target_table.c.id).where(
                target_table.c.tenant_id == tenant_id,
                target_table.c.id == target_id,
            )
        ).scalar_one_or_none()
        if target_exists is None:
            _append_error(
                errors,
                code="TARGET_MISSING",
                entity_type=entity_type,
                source_id=source_id,
                message="migration mapping exists but the target row is missing",
            )
    return tuple(errors)


def _sample_rows(
    snapshot: SourceSnapshot,
    *,
    tenant_id: UUID,
    mappings: dict[tuple[str, str], tuple[UUID, str]],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "source_project_id": source_id,
            "target_project_id": str(
                _mapping_target(
                    mappings=mappings,
                    tenant_id=tenant_id,
                    entity_type="project",
                    source_id=source_id,
                )
            ),
            "project_code": normalize_project_code(
                project_number=str(project["project_number"] or ""),
                source_id=source_id,
            ),
            "project_name": str(project["name"]),
            "current_stage": str(project["current_phase"]),
            "task_count": sum(str(row["project_id"]) == source_id for row in snapshot.tasks),
            "gate_review_count": sum(
                str(row["project_id"]) == source_id for row in snapshot.gate_reviews
            ),
            "file_reference_count": sum(
                str(row["project_id"]) == source_id for row in snapshot.file_references
            ),
        }
        for project in snapshot.projects
        for source_id in (str(project["source_id"]),)
    )


def _plan_report(
    target_engine: Engine,
    *,
    snapshot: SourceSnapshot,
    tenant_id: UUID,
    actor_user_id: UUID,
    source_schema: str,
    dry_run: bool,
) -> tuple[
    MigrationReport,
    dict[tuple[str, str], tuple[UUID, str]],
]:
    with target_engine.connect() as connection:
        mappings = _existing_mappings(connection, tenant_id=tenant_id)
        errors = _validate_snapshot(
            connection,
            snapshot=snapshot,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            mappings=mappings,
        )
    created_counts, skipped_counts = _planned_counts(snapshot, mappings)
    samples: tuple[dict[str, object], ...]
    try:
        samples = _sample_rows(snapshot, tenant_id=tenant_id, mappings=mappings)
    except ValueError:
        samples = ()
    return (
        MigrationReport(
            mode="dry-run" if dry_run else "apply",
            status="invalid" if errors else "ready",
            source_system=SOURCE_SYSTEM,
            source_schema=source_schema,
            selected_project_ids=snapshot.requested_project_ids,
            source_fingerprint=snapshot.fingerprint,
            source_counts=_source_counts(snapshot),
            created_counts=created_counts,
            skipped_counts=skipped_counts,
            target_writes=0,
            errors=errors,
            samples=samples,
        ),
        mappings,
    )


def _insert_mapping(
    connection: Connection,
    *,
    tenant_id: UUID,
    run_id: UUID,
    entity_type: str,
    row: dict[str, Any],
    target_id: UUID,
) -> int:
    connection.execute(
        tables.migration_mappings.insert(),
        {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "run_id": run_id,
            "source_system": SOURCE_SYSTEM,
            "entity_type": entity_type,
            "source_id": str(row["source_id"]),
            "target_id": target_id,
            "source_hash": row["source_hash"],
        },
    )
    return 1


def _insert_users(
    connection: Connection,
    *,
    snapshot: SourceSnapshot,
    tenant_id: UUID,
    run_id: UUID,
    mappings: dict[tuple[str, str], tuple[UUID, str]],
) -> int:
    writes = 0
    for row in snapshot.users:
        source_id = str(row["source_id"])
        if ("user", source_id) in mappings:
            continue
        target_id = _target_id(tenant_id, "user", source_id)
        connection.execute(
            tables.users.insert(),
            {
                "id": target_id,
                "tenant_id": tenant_id,
                "username": _legacy_username(source_id, row["username"]),
                "email": row["email"],
                "display_name": str(row["display_name"])[:256],
                "role": map_user_role(str(row["role"])),
                "password_hash": None,
                "is_active": False,
                "created_at": _parse_datetime(
                    row["created_at"], field="created_at", source_id=source_id
                ),
                "updated_at": _parse_datetime(
                    row["updated_at"], field="updated_at", source_id=source_id
                ),
            },
        )
        writes += 1 + _insert_mapping(
            connection,
            tenant_id=tenant_id,
            run_id=run_id,
            entity_type="user",
            row=row,
            target_id=target_id,
        )
        mappings[("user", source_id)] = (target_id, str(row["source_hash"]))
    return writes


def _project_member_values(
    *,
    tenant_id: UUID,
    project_id: UUID,
    actor_user_id: UUID,
    owner_user_id: UUID,
) -> list[dict[str, object]]:
    user_ids = tuple(dict.fromkeys((actor_user_id, owner_user_id)))
    return [
        {
            "id": uuid5(NAMESPACE_URL, f"pdos:{tenant_id}:member:{project_id}:{user_id}"),
            "tenant_id": tenant_id,
            "project_id": project_id,
            "user_id": user_id,
            "added_by_user_id": actor_user_id,
        }
        for user_id in user_ids
    ]


def _insert_projects(
    connection: Connection,
    *,
    snapshot: SourceSnapshot,
    tenant_id: UUID,
    actor_user_id: UUID,
    run_id: UUID,
    mappings: dict[tuple[str, str], tuple[UUID, str]],
) -> int:
    writes = 0
    for row in snapshot.projects:
        source_id = str(row["source_id"])
        if ("project", source_id) in mappings:
            continue
        template = _WORKFLOW_TEMPLATES[str(row["category"])]
        target_id = _target_id(tenant_id, "project", source_id)
        workflow_id = _workflow_id(tenant_id, source_id)
        stage_values = [
            {
                "id": _stage_id(tenant_id, source_id, stage.code),
                "tenant_id": tenant_id,
                "workflow_id": workflow_id,
                "code": stage.code,
                "name": stage.name,
                "description": stage.description,
                "sequence": stage.sequence,
            }
            for stage in template.stages
        ]
        owner_source_id = row["pm_user_id"] or row["created_by"]
        owner_user_id = _mapping_target(
            mappings=mappings,
            tenant_id=tenant_id,
            entity_type="user",
            source_id=owner_source_id,
        )
        project_code = normalize_project_code(
            project_number=str(row["project_number"] or ""), source_id=source_id
        )
        connection.execute(
            tables.workflows.insert(),
            {
                "id": workflow_id,
                "tenant_id": tenant_id,
                "code": f"{template.code}-cehub-{target_id.hex}",
                "name": f"{template.name} · {project_code}",
                "description": f"CEHub v1 imported {template.name} workflow",
                "version": template.version,
                "is_active": True,
            },
        )
        connection.execute(tables.stages.insert(), stage_values)
        connection.execute(
            tables.projects.insert(),
            {
                "id": target_id,
                "tenant_id": tenant_id,
                "workflow_id": workflow_id,
                "current_stage_id": _stage_id(tenant_id, source_id, str(row["current_phase"])),
                "owner_user_id": owner_user_id,
                "code": project_code,
                "name": str(row["name"]),
                "description": row["description"],
                "status": map_project_status(
                    archived=bool(row["archived"]), lifecycle=str(row["lifecycle"])
                ),
                "start_date": _parse_date(
                    row["start_date"], field="start_date", source_id=source_id
                ),
                "target_date": _parse_date(
                    row["target_date"], field="target_date", source_id=source_id
                ),
                "created_at": _parse_datetime(
                    row["created_at"], field="created_at", source_id=source_id
                ),
                "updated_at": _parse_datetime(
                    row["updated_at"], field="updated_at", source_id=source_id
                ),
            },
        )
        member_values = _project_member_values(
            tenant_id=tenant_id,
            project_id=target_id,
            actor_user_id=actor_user_id,
            owner_user_id=owner_user_id,
        )
        connection.execute(tables.project_members.insert(), member_values)
        connection.execute(
            tables.gates.insert(),
            [
                {
                    "id": _gate_id(tenant_id, source_id, stage.code),
                    "tenant_id": tenant_id,
                    "project_id": target_id,
                    "stage_id": _stage_id(tenant_id, source_id, stage.code),
                    "code": stage.code,
                    "name": f"{stage.name} Gate",
                    "status": "preparing",
                }
                for stage in template.stages
            ],
        )
        writes += 1 + len(stage_values) + 1 + len(member_values) + len(stage_values)
        writes += _insert_mapping(
            connection,
            tenant_id=tenant_id,
            run_id=run_id,
            entity_type="project",
            row=row,
            target_id=target_id,
        )
        mappings[("project", source_id)] = (target_id, str(row["source_hash"]))
    return writes


def _task_description(row: dict[str, Any]) -> str | None:
    values = [str(row[key]).strip() for key in ("instructions", "completion_note") if row[key]]
    return "\n\n".join(values) or None


def _task_status(row: dict[str, Any]) -> str:
    return "done" if bool(row["completed"]) else str(row["status"])


def _insert_tasks(
    connection: Connection,
    *,
    snapshot: SourceSnapshot,
    tenant_id: UUID,
    run_id: UUID,
    mappings: dict[tuple[str, str], tuple[UUID, str]],
) -> int:
    writes = 0
    for row in snapshot.tasks:
        source_id = str(row["source_id"])
        if ("task", source_id) in mappings:
            continue
        source_project_id = str(row["project_id"])
        project_id = _mapping_target(
            mappings=mappings,
            tenant_id=tenant_id,
            entity_type="project",
            source_id=source_project_id,
        )
        assignee_id = (
            _mapping_target(
                mappings=mappings,
                tenant_id=tenant_id,
                entity_type="user",
                source_id=row["assignee_user_id"],
            )
            if row["assignee_user_id"] is not None
            else None
        )
        status = _task_status(row)
        completed_at = (
            _parse_datetime(
                row["completed_at"] or row["updated_at"],
                field="completed_at",
                source_id=source_id,
            )
            if status == "done"
            else None
        )
        blocked_reason = row["blocked_reason"]
        if status == "blocked" and not str(blocked_reason or "").strip():
            blocked_reason = "Migrated from CEHub as blocked"
        if status != "blocked":
            blocked_reason = None
        target_id = _target_id(tenant_id, "task", source_id)
        connection.execute(
            tables.tasks.insert(),
            {
                "id": target_id,
                "tenant_id": tenant_id,
                "project_id": project_id,
                "workflow_id": _workflow_id(tenant_id, source_project_id),
                "stage_id": _stage_id(tenant_id, source_project_id, str(row["phase_id"])),
                "assignee_user_id": assignee_id,
                "title": str(row["task_id"]),
                "description": _task_description(row),
                "status": status,
                "blocked_reason": blocked_reason,
                "priority": str(row["priority"]),
                "start_date": _parse_date(
                    row["start_date"], field="start_date", source_id=source_id
                ),
                "due_date": _parse_date(row["due_date"], field="due_date", source_id=source_id),
                "completed_at": completed_at,
                "created_at": _parse_datetime(
                    row["created_at"], field="created_at", source_id=source_id
                ),
                "updated_at": _parse_datetime(
                    row["updated_at"], field="updated_at", source_id=source_id
                ),
            },
        )
        writes += 1 + _insert_mapping(
            connection,
            tenant_id=tenant_id,
            run_id=run_id,
            entity_type="task",
            row=row,
            target_id=target_id,
        )
        mappings[("task", source_id)] = (target_id, str(row["source_hash"]))
    return writes


def _insert_gate_history(
    connection: Connection,
    *,
    snapshot: SourceSnapshot,
    tenant_id: UUID,
    run_id: UUID,
    mappings: dict[tuple[str, str], tuple[UUID, str]],
) -> int:
    writes = 0
    affected_gates: set[tuple[str, str]] = set()
    for row in snapshot.gate_reviews:
        source_id = str(row["source_id"])
        if ("gate_review", source_id) in mappings:
            continue
        source_project_id = str(row["project_id"])
        stage_code = str(row["phase_id"])
        project_id = _mapping_target(
            mappings=mappings,
            tenant_id=tenant_id,
            entity_type="project",
            source_id=source_project_id,
        )
        reviewer_id = (
            _mapping_target(
                mappings=mappings,
                tenant_id=tenant_id,
                entity_type="user",
                source_id=row["created_by"],
            )
            if row["created_by"] is not None
            else None
        )
        target_id = _target_id(tenant_id, "gate_review", source_id)
        connection.execute(
            tables.gate_history_records.insert(),
            {
                "id": target_id,
                "tenant_id": tenant_id,
                "project_id": project_id,
                "gate_id": _gate_id(tenant_id, source_project_id, stage_code),
                "reviewed_by_user_id": reviewer_id,
                "source_system": SOURCE_SYSTEM,
                "source_id": source_id,
                "source_hash": row["source_hash"],
                "round_number": int(row["round_number"]),
                "reviewed_at": _parse_datetime(
                    row["review_date"], field="review_date", source_id=source_id
                ),
                "participants": row["participants"],
                "decision": str(row["decision"]),
                "conditions": row["conditions"],
                "notes": row["notes"],
                "created_at": _parse_datetime(
                    row["created_at"], field="created_at", source_id=source_id
                ),
            },
        )
        writes += 1 + _insert_mapping(
            connection,
            tenant_id=tenant_id,
            run_id=run_id,
            entity_type="gate_review",
            row=row,
            target_id=target_id,
        )
        mappings[("gate_review", source_id)] = (target_id, str(row["source_hash"]))
        affected_gates.add((source_project_id, stage_code))

    for source_project_id, stage_code in affected_gates:
        latest = max(
            (
                row
                for row in snapshot.gate_reviews
                if str(row["project_id"]) == source_project_id
                and str(row["phase_id"]) == stage_code
            ),
            key=lambda row: (
                int(row["round_number"]),
                _parse_datetime(
                    row["review_date"],
                    field="review_date",
                    source_id=str(row["source_id"]),
                ),
                str(row["source_id"]),
            ),
        )
        gate_status = map_gate_decision(str(latest["decision"]))
        reviewer_id = (
            _mapping_target(
                mappings=mappings,
                tenant_id=tenant_id,
                entity_type="user",
                source_id=latest["created_by"],
            )
            if latest["created_by"] is not None
            else None
        )
        decided_at = (
            _parse_datetime(
                latest["review_date"],
                field="review_date",
                source_id=str(latest["source_id"]),
            )
            if gate_status in {"approved", "rejected"}
            else None
        )
        connection.execute(
            tables.gates.update()
            .where(
                tables.gates.c.tenant_id == tenant_id,
                tables.gates.c.id == _gate_id(tenant_id, source_project_id, stage_code),
            )
            .values(
                status=gate_status,
                decided_at=decided_at,
                decided_by_user_id=reviewer_id if decided_at is not None else None,
                updated_at=datetime.now(UTC),
            )
        )
        writes += 1
    return writes


def _file_classification(value: object) -> str:
    if value == "confidential":
        return "confidential"
    if value in {"restricted", "unknown"}:
        return "restricted"
    return "internal"


def _insert_file_references(
    connection: Connection,
    *,
    snapshot: SourceSnapshot,
    tenant_id: UUID,
    run_id: UUID,
    mappings: dict[tuple[str, str], tuple[UUID, str]],
) -> int:
    writes = 0
    for row in snapshot.file_references:
        source_id = str(row["source_id"])
        if ("file_reference", source_id) in mappings:
            continue
        source_project_id = str(row["project_id"])
        target_id = _target_id(tenant_id, "file_reference", source_id)
        connection.execute(
            tables.external_file_references.insert(),
            {
                "id": target_id,
                "tenant_id": tenant_id,
                "project_id": _mapping_target(
                    mappings=mappings,
                    tenant_id=tenant_id,
                    entity_type="project",
                    source_id=source_project_id,
                ),
                "uploaded_by_user_id": _mapping_target(
                    mappings=mappings,
                    tenant_id=tenant_id,
                    entity_type="user",
                    source_id=row["uploaded_by"],
                ),
                "source_system": SOURCE_SYSTEM,
                "source_id": source_id,
                "source_hash": row["source_hash"],
                "object_key": str(row["storage_key"]),
                "source_url": row["storage_url"],
                "filename": str(row["name"]),
                "media_type": str(row["mime_type"]),
                "size_bytes": int(row["size"]),
                "classification": _file_classification(row["security_classification"]),
                "stage_code": row["phase_id"],
                "task_source_id": row["task_id"],
                "created_at": _parse_datetime(
                    row["created_at"], field="created_at", source_id=source_id
                ),
            },
        )
        writes += 1 + _insert_mapping(
            connection,
            tenant_id=tenant_id,
            run_id=run_id,
            entity_type="file_reference",
            row=row,
            target_id=target_id,
        )
        mappings[("file_reference", source_id)] = (
            target_id,
            str(row["source_hash"]),
        )
    return writes


def migrate_cehub_v1(
    *,
    source_engine: Engine,
    target_engine: Engine,
    tenant_id: UUID,
    actor_user_id: UUID,
    project_ids: tuple[str, ...],
    source_schema: str = "public",
    dry_run: bool = True,
) -> MigrationReport:
    """Validate or atomically import a bounded CEHub project snapshot.

    Dry-run reads both databases without writing. Apply serializes migrations per
    tenant, validates the snapshot again under the target lock, and commits one
    all-or-nothing batch plus immutable source-to-target mapping rows.
    """

    source_schema = validate_source_schema(source_schema)
    snapshot = CeHubSourceAdapter(source_engine, source_schema=source_schema).read_snapshot(
        project_ids=project_ids
    )
    report, mappings = _plan_report(
        target_engine,
        snapshot=snapshot,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        source_schema=source_schema,
        dry_run=dry_run,
    )
    if report.errors:
        if dry_run:
            return report
        raise MigrationValidationError(report)
    if dry_run:
        return report

    run_id = uuid4()
    target_writes = 0
    with target_engine.begin() as connection:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": f"pdos-cehub-migration:{tenant_id}"},
        )
        mappings = _existing_mappings(connection, tenant_id=tenant_id)
        locked_errors = _validate_snapshot(
            connection,
            snapshot=snapshot,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            mappings=mappings,
        )
        if locked_errors:
            locked_report = MigrationReport(
                mode="apply",
                status="invalid",
                source_system=report.source_system,
                source_schema=report.source_schema,
                selected_project_ids=report.selected_project_ids,
                source_fingerprint=report.source_fingerprint,
                source_counts=report.source_counts,
                created_counts=report.created_counts,
                skipped_counts=report.skipped_counts,
                target_writes=0,
                errors=locked_errors,
                samples=report.samples,
            )
            raise MigrationValidationError(locked_report)
        apply_created_counts, apply_skipped_counts = _planned_counts(snapshot, mappings)
        connection.execute(
            tables.migration_runs.insert(),
            {
                "id": run_id,
                "tenant_id": tenant_id,
                "actor_user_id": actor_user_id,
                "source_system": SOURCE_SYSTEM,
                "source_schema": source_schema,
                "source_fingerprint": snapshot.fingerprint,
                "selected_project_ids": list(snapshot.requested_project_ids),
                "status": "completed",
                "stats": {
                    "source_counts": report.source_counts,
                    "created_counts": apply_created_counts,
                    "skipped_counts": apply_skipped_counts,
                },
            },
        )
        target_writes += 1
        target_writes += _insert_users(
            connection,
            snapshot=snapshot,
            tenant_id=tenant_id,
            run_id=run_id,
            mappings=mappings,
        )
        target_writes += _insert_projects(
            connection,
            snapshot=snapshot,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            run_id=run_id,
            mappings=mappings,
        )
        target_writes += _insert_tasks(
            connection,
            snapshot=snapshot,
            tenant_id=tenant_id,
            run_id=run_id,
            mappings=mappings,
        )
        target_writes += _insert_gate_history(
            connection,
            snapshot=snapshot,
            tenant_id=tenant_id,
            run_id=run_id,
            mappings=mappings,
        )
        target_writes += _insert_file_references(
            connection,
            snapshot=snapshot,
            tenant_id=tenant_id,
            run_id=run_id,
            mappings=mappings,
        )

    return MigrationReport(
        mode="apply",
        status="completed",
        source_system=report.source_system,
        source_schema=report.source_schema,
        selected_project_ids=report.selected_project_ids,
        source_fingerprint=report.source_fingerprint,
        source_counts=report.source_counts,
        created_counts=apply_created_counts,
        skipped_counts=apply_skipped_counts,
        target_writes=target_writes,
        errors=(),
        samples=report.samples,
    )


def map_user_role(source_role: str) -> str:
    try:
        return _USER_ROLE_MAP[source_role]
    except KeyError as exc:
        raise ValueError(f"unsupported CEHub user role: {source_role}") from exc


def map_project_status(*, archived: bool, lifecycle: str) -> str:
    if archived or lifecycle == "terminated":
        return "archived"
    if lifecycle == "paused":
        return "on_hold"
    if lifecycle == "active":
        return "active"
    raise ValueError(f"unsupported CEHub project lifecycle: {lifecycle}")


def map_gate_decision(source_decision: str) -> str:
    try:
        return _GATE_STATUS_MAP[source_decision]
    except KeyError as exc:
        raise ValueError(f"unsupported CEHub Gate decision: {source_decision}") from exc


def normalize_project_code(*, project_number: str | None, source_id: str) -> str:
    value = (project_number or "").strip() or source_id.strip()
    if not value:
        raise ValueError("CEHub project has no stable project number or source id")
    if len(value) > 64:
        raise ValueError(f"CEHub project code exceeds 64 characters: {value}")
    return value


def validate_source_schema(value: str) -> str:
    if SOURCE_SCHEMA_PATTERN.fullmatch(value) is None:
        raise ValueError(f"invalid CEHub source schema: {value}")
    return value
