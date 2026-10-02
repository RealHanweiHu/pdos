"""Project-scoped Issue lifecycle use cases."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select
from sqlalchemy.engine import RowMapping

from app.db.schema import tables
from app.domain.process_template_fields import (
    TemplateFieldConflictError,
    project_fields,
    validate_values,
)
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

if TYPE_CHECKING:
    from app.domain.material_exceptions import MaterialClosureReference


class IssueNotFoundError(LookupError):
    """Raised when an Issue is absent from the tenant-bound Project."""


class IssueScopeError(ValueError):
    """Raised when a related Stage or owner is outside the Project."""


class IssueInvalidTransitionError(ValueError):
    """Raised when an Issue status edge is outside the frozen graph."""


class IssueTerminalError(ValueError):
    """Raised when a closed Issue is edited."""


class IssueAssignmentIncompleteError(ValueError):
    """Raised when an Issue enters analysis without owner, verifier, date, and criteria."""


class IssueFourEyesError(ValueError):
    """Raised when a high or critical Issue would have the same owner and verifier."""


class IssueCloseNotVerifierError(ValueError):
    """Raised when someone other than the verifier closes a high or critical Issue."""


class IssueSubmitNotOwnerError(ValueError):
    """Raised when someone other than the owner submits an Issue for verification."""


class IssueRejectNotVerifierError(ValueError):
    """Raised when someone other than the verifier rejects a verification."""


class IssueClosureEvidenceRequiredError(ValueError):
    """Raised when a high or critical Issue closes without closure evidence."""


@dataclass(frozen=True)
class IssueRecord:
    id: UUID
    project_id: UUID
    stage_id: UUID | None
    owner_user_id: UUID | None
    verifier_user_id: UUID | None
    sample_id: UUID | None
    reported_by_user_id: UUID | None
    title: str
    description: str | None
    issue_type: str
    status: str
    severity: str
    root_cause: str | None
    resolution: str | None
    closure_criteria: str | None
    closure_evidence_ref: str | None
    reopen_count: int
    target_date: date | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    source_finding_id: UUID | None = None
    source_field_capture_id: UUID | None = None
    template_fields: dict[str, Any] = field(default_factory=dict)
    created_by_ai_principal_id: UUID | None = None
    ai_writer_name: str | None = None
    withdrawn_at: datetime | None = None
    ai_withdrawal_id: UUID | None = None


@dataclass(frozen=True)
class IssueDraft:
    stage_id: UUID | None
    owner_user_id: UUID | None
    verifier_user_id: UUID | None
    sample_id: UUID | None
    title: str
    description: str | None
    issue_type: str
    severity: str
    root_cause: str | None
    resolution: str | None
    closure_criteria: str | None
    target_date: date | None


@dataclass(frozen=True)
class IssueUpdate:
    changes: dict[str, object]
    expected_updated_at: datetime | None = None


ISSUE_TRANSITIONS = {
    "open": frozenset({"analysis"}),
    "analysis": frozenset({"action"}),
    "action": frozenset({"verification"}),
    "verification": frozenset({"closed", "action"}),
    "closed": frozenset({"action"}),
}


def _issue_statement() -> Any:
    return select(
        tables.issues.c.id,
        tables.issues.c.project_id,
        tables.issues.c.stage_id,
        tables.issues.c.owner_user_id,
        tables.issues.c.verifier_user_id,
        tables.issues.c.sample_id,
        tables.issues.c.reported_by_user_id,
        tables.issues.c.created_by_ai_principal_id,
        tables.issues.c.withdrawn_at,
        tables.issues.c.ai_withdrawal_id,
        select(tables.ai_principals.c.display_name)
        .where(
            tables.ai_principals.c.tenant_id == tables.issues.c.tenant_id,
            tables.ai_principals.c.id == tables.issues.c.created_by_ai_principal_id,
        )
        .correlate(tables.issues)
        .scalar_subquery()
        .label("ai_writer_name"),
        tables.issues.c.title,
        tables.issues.c.description,
        tables.issues.c.issue_type,
        tables.issues.c.status,
        tables.issues.c.severity,
        tables.issues.c.root_cause,
        tables.issues.c.template_fields,
        tables.issues.c.resolution,
        tables.issues.c.closure_criteria,
        tables.issues.c.closure_evidence_ref,
        tables.issues.c.reopen_count,
        tables.issues.c.target_date,
        tables.issues.c.closed_at,
        tables.issues.c.created_at,
        tables.issues.c.updated_at,
        tables.issues.c.source_finding_id,
        select(tables.field_captures.c.id)
        .where(
            tables.field_captures.c.tenant_id == tables.issues.c.tenant_id,
            tables.field_captures.c.project_id == tables.issues.c.project_id,
            tables.field_captures.c.issue_id == tables.issues.c.id,
        )
        .correlate(tables.issues)
        .scalar_subquery()
        .label("source_field_capture_id"),
    )


def _record_from_row(row: RowMapping) -> IssueRecord:
    reporter_id = row["reported_by_user_id"]
    principal_id = row.get("created_by_ai_principal_id")
    if any(
        value is not None and not isinstance(value, UUID) for value in (reporter_id, principal_id)
    ):
        raise IssueNotFoundError
    if (reporter_id is None) == (principal_id is None):
        raise IssueNotFoundError
    if principal_id is not None and not row.get("ai_writer_name"):
        raise IssueNotFoundError
    return IssueRecord(
        id=row["id"],
        project_id=row["project_id"],
        stage_id=row["stage_id"],
        owner_user_id=row["owner_user_id"],
        verifier_user_id=row["verifier_user_id"],
        sample_id=row["sample_id"],
        reported_by_user_id=reporter_id,
        created_by_ai_principal_id=principal_id,
        ai_writer_name=row.get("ai_writer_name"),
        withdrawn_at=row.get("withdrawn_at"),
        ai_withdrawal_id=row.get("ai_withdrawal_id"),
        title=row["title"],
        description=row["description"],
        issue_type=row["issue_type"],
        status=row["status"],
        severity=row["severity"],
        root_cause=row["root_cause"],
        template_fields=dict(row["template_fields"]),
        resolution=row["resolution"],
        closure_criteria=row["closure_criteria"],
        closure_evidence_ref=row["closure_evidence_ref"],
        reopen_count=row["reopen_count"],
        target_date=row["target_date"],
        closed_at=row["closed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        source_finding_id=row["source_finding_id"],
        source_field_capture_id=row.get("source_field_capture_id"),
    )


def _issue_snapshot(record: IssueRecord) -> dict[str, object]:
    return {
        "project_id": str(record.project_id),
        "withdrawn_at": record.withdrawn_at.isoformat() if record.withdrawn_at else None,
        "ai_withdrawal_id": str(record.ai_withdrawal_id) if record.ai_withdrawal_id else None,
        **(
            {"source_finding_id": str(record.source_finding_id)} if record.source_finding_id else {}
        ),
        "stage_id": str(record.stage_id) if record.stage_id is not None else None,
        "owner_user_id": (str(record.owner_user_id) if record.owner_user_id is not None else None),
        "verifier_user_id": (
            str(record.verifier_user_id) if record.verifier_user_id is not None else None
        ),
        "reported_by_user_id": (
            str(record.reported_by_user_id) if record.reported_by_user_id else None
        ),
        **(
            {
                "created_by_ai_principal_id": str(record.created_by_ai_principal_id),
                "ai_writer_name": record.ai_writer_name,
            }
            if record.created_by_ai_principal_id
            else {}
        ),
        **({"template_fields": record.template_fields} if record.template_fields else {}),
        "title": record.title,
        "description": record.description,
        "issue_type": record.issue_type,
        "status": record.status,
        "severity": record.severity,
        "root_cause": record.root_cause,
        "resolution": record.resolution,
        "closure_criteria": record.closure_criteria,
        "closure_evidence_ref": record.closure_evidence_ref,
        "reopen_count": record.reopen_count,
        "target_date": record.target_date.isoformat() if record.target_date is not None else None,
        "closed_at": record.closed_at.isoformat() if record.closed_at is not None else None,
    }


def _require_four_eyes(
    *, severity: str, owner_user_id: UUID | None, verifier_user_id: UUID | None
) -> None:
    if (
        severity in {"high", "critical"}
        and owner_user_id is not None
        and verifier_user_id is not None
        and owner_user_id == verifier_user_id
    ):
        raise IssueFourEyesError


class IssueService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _project_workflow(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
    ) -> UUID:
        workflow_id = connection.execute(
            select(tables.projects.c.workflow_id).where(
                tables.projects.c.tenant_id == tenant_id,
                tables.projects.c.id == project_id,
            )
        ).scalar_one_or_none()
        if not isinstance(workflow_id, UUID):
            raise IssueNotFoundError
        return workflow_id

    @staticmethod
    def _get_record(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        issue_id: UUID,
    ) -> IssueRecord:
        row = (
            connection.execute(
                _issue_statement().where(
                    tables.issues.c.tenant_id == tenant_id,
                    tables.issues.c.project_id == project_id,
                    tables.issues.c.id == issue_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise IssueNotFoundError
        return _record_from_row(row)

    @staticmethod
    def _validate_stage(
        connection: Connection,
        *,
        tenant_id: UUID,
        workflow_id: UUID,
        stage_id: UUID | None,
    ) -> None:
        if stage_id is None:
            return
        found = connection.execute(
            select(tables.stages.c.id).where(
                tables.stages.c.tenant_id == tenant_id,
                tables.stages.c.workflow_id == workflow_id,
                tables.stages.c.id == stage_id,
            )
        ).scalar_one_or_none()
        if found is None:
            raise IssueScopeError

    @staticmethod
    def _validate_member(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        user_id: UUID | None,
    ) -> None:
        if user_id is None:
            return
        found = connection.execute(
            select(tables.project_members.c.id)
            .join(
                tables.users,
                (tables.users.c.tenant_id == tables.project_members.c.tenant_id)
                & (tables.users.c.id == tables.project_members.c.user_id),
            )
            .where(
                tables.project_members.c.tenant_id == tenant_id,
                tables.project_members.c.project_id == project_id,
                tables.project_members.c.user_id == user_id,
                tables.users.c.role.in_(
                    {"owner", "admin", "project_manager", "engineer", "quality"}
                ),
            )
        ).scalar_one_or_none()
        if found is None:
            raise IssueScopeError

    @staticmethod
    def _validate_sample(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        sample_id: UUID | None,
    ) -> None:
        """A defect belongs to a unit built in *this* project (V1-B2)."""
        if sample_id is None:
            return
        found = connection.execute(
            select(tables.samples.c.id).where(
                tables.samples.c.tenant_id == tenant_id,
                tables.samples.c.project_id == project_id,
                tables.samples.c.id == sample_id,
            )
        ).scalar_one_or_none()
        if found is None:
            raise IssueScopeError

    def get(self, *, tenant_id: UUID, project_id: UUID, issue_id: UUID) -> IssueRecord:
        with self._engine.connect() as connection:
            return self._get_record(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                issue_id=issue_id,
            )

    def list(self, *, tenant_id: UUID, project_id: UUID) -> list[IssueRecord]:
        with self._engine.connect() as connection:
            return [
                _record_from_row(row)
                for row in connection.execute(
                    _issue_statement()
                    .where(
                        tables.issues.c.tenant_id == tenant_id,
                        tables.issues.c.project_id == project_id,
                        tables.issues.c.withdrawn_at.is_(None),
                    )
                    .order_by(tables.issues.c.updated_at.desc(), tables.issues.c.id.desc())
                ).mappings()
            ]

    def create(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        draft: IssueDraft,
        connection: Connection | None = None,
        source_finding_id: UUID | None = None,
        now: datetime | None = None,
    ) -> IssueRecord:
        return self._create(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            project_id=project_id,
            draft=draft,
            connection=connection,
            source_finding_id=source_finding_id,
            now=now,
        )

    def create_from_ai_event(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        principal_id: UUID,
        policy_id: UUID,
        scope_revision_id: UUID,
        requested_by_user_id: UUID,
        confirmed_by_user_id: UUID | None,
        result_id: UUID,
        run_id: UUID,
        model_invocation_id: UUID,
        source_event_row_id: int,
        application_id: UUID,
        draft: IssueDraft,
        connection: Connection,
        write_execution: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> IssueRecord:
        """Create a confirmed or qualified automatic proposal with its actual AI author.

        The application service owns source freshness, permissions, deduplication,
        and the atomic application receipt/backlink. No automatic grant is inferred.
        """
        tenant_status = connection.execute(
            select(tables.tenants.c.status)
            .where(tables.tenants.c.id == tenant_id)
            .with_for_update()
        ).scalar_one_or_none()
        if tenant_status != "active" or not lock_project_write_scope(
            connection, tenant_id=tenant_id, project_id=project_id
        ):
            raise IssueNotFoundError
        policy = (
            connection.execute(
                select(tables.ai_write_policies)
                .where(tables.ai_write_policies.c.tenant_id == tenant_id)
                .order_by(tables.ai_write_policies.c.revision.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        scope = (
            connection.execute(
                select(tables.ai_write_scope_revisions)
                .where(
                    tables.ai_write_scope_revisions.c.tenant_id == tenant_id,
                    tables.ai_write_scope_revisions.c.project_id == project_id,
                    tables.ai_write_scope_revisions.c.principal_id == principal_id,
                    tables.ai_write_scope_revisions.c.operation_key == "event.issue.create",
                )
                .order_by(tables.ai_write_scope_revisions.c.revision.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        principal = connection.execute(
            select(tables.ai_principals.c.id).where(
                tables.ai_principals.c.tenant_id == tenant_id,
                tables.ai_principals.c.id == principal_id,
                tables.ai_principals.c.principal_kind == "ai",
            )
        ).scalar_one_or_none()
        if (
            tenant_status != "active"
            or principal is None
            or policy is None
            or policy["id"] != policy_id
            or policy["principal_id"] != principal_id
            or policy["mode"] != "tiered"
            or policy["operation_settings"].get("event.issue.create", {}).get("mode")
            not in {"confirm", "automatic"}
            or scope is None
            or scope["id"] != scope_revision_id
            or not scope["enabled"]
        ):
            raise IssueScopeError("AI 写入政策或项目授权已变化，请重新核对")
        result = (
            connection.execute(
                select(tables.ai_issue_event_results).where(
                    tables.ai_issue_event_results.c.tenant_id == tenant_id,
                    tables.ai_issue_event_results.c.project_id == project_id,
                    tables.ai_issue_event_results.c.id == result_id,
                    tables.ai_issue_event_results.c.run_id == run_id,
                    tables.ai_issue_event_results.c.model_invocation_id == model_invocation_id,
                    tables.ai_issue_event_results.c.event_row_id == source_event_row_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        run = (
            connection.execute(
                select(tables.agent_runs).where(
                    tables.agent_runs.c.tenant_id == tenant_id,
                    tables.agent_runs.c.project_id == project_id,
                    tables.agent_runs.c.id == run_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        expected_people = {requested_by_user_id}
        if confirmed_by_user_id is not None:
            expected_people.add(confirmed_by_user_id)
        people = set(
            connection.execute(
                select(tables.users.c.id).where(
                    tables.users.c.tenant_id == tenant_id,
                    tables.users.c.id.in_(expected_people),
                    tables.users.c.is_active.is_(True),
                )
            ).scalars()
        )
        if (
            result is None
            or run is None
            or run["status"] != "succeeded"
            or run["requested_by_user_id"] != requested_by_user_id
            or people != expected_people
        ):
            raise IssueScopeError("原生成结果、请求人或确认人无法核对")
        if confirmed_by_user_id is None:
            if (
                write_execution is None
                or write_execution.get("route") != "direct"
                or write_execution.get("run_id") != str(run_id)
                or write_execution.get("policy_id") != str(policy_id)
                or write_execution.get("scope_revision_id") != str(scope_revision_id)
                or write_execution.get("principal_id") != str(principal_id)
                or run["run_context"].get("issue_write_execution") != write_execution
                or policy["operation_settings"]["event.issue.create"]["mode"] != "automatic"
            ):
                raise IssueScopeError("自动建单须使用同事务核验的原运行执行依据")
        elif write_execution is not None:
            raise IssueScopeError("人工确认与自动办理回执不能混用")
        proposal = result["proposal"]
        source_kind = result["source_snapshot"].get("source_kind")
        if (
            proposal.get("disposition") != "create_issue"
            or proposal.get("title") != draft.title
            or proposal.get("description") != draft.description
            or proposal.get("severity") != draft.severity
            or draft.issue_type
            != {"test_failure": "test_failure", "material_exception": "supplier"}.get(source_kind)
        ):
            raise IssueScopeError("待创建问题与原生成建议不一致")
        return self._create(
            tenant_id=tenant_id,
            actor_user_id=None,
            project_id=project_id,
            draft=draft,
            connection=connection,
            created_by_ai_principal_id=principal_id,
            audit_context={
                "origin": "ai",
                "writer_principal_id": str(principal_id),
                "requested_by_user_id": str(requested_by_user_id),
                "confirmed_by_user_id": str(confirmed_by_user_id) if confirmed_by_user_id else None,
                **({"write_execution": write_execution} if write_execution else {}),
                "result_id": str(result_id),
                "run_id": str(run_id),
                "model_invocation_id": str(model_invocation_id),
                "source_event_row_id": source_event_row_id,
                "application_id": str(application_id),
                "policy_id": str(policy_id),
                "scope_revision_id": str(scope_revision_id),
            },
            now=now,
        )

    def _create(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID | None,
        project_id: UUID,
        draft: IssueDraft,
        connection: Connection | None = None,
        source_finding_id: UUID | None = None,
        created_by_ai_principal_id: UUID | None = None,
        audit_context: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> IssueRecord:
        issue_id = uuid4()
        occurred_at = now or datetime.now(UTC)
        with (
            nullcontext(connection) if connection is not None else self._engine.begin()
        ) as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise IssueNotFoundError
            workflow_id = self._project_workflow(
                connection, tenant_id=tenant_id, project_id=project_id
            )
            self._validate_stage(
                connection,
                tenant_id=tenant_id,
                workflow_id=workflow_id,
                stage_id=draft.stage_id,
            )
            self._validate_member(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=draft.owner_user_id,
            )
            self._validate_member(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=draft.verifier_user_id,
            )
            self._validate_sample(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                sample_id=draft.sample_id,
            )
            _require_four_eyes(
                severity=draft.severity,
                owner_user_id=draft.owner_user_id,
                verifier_user_id=draft.verifier_user_id,
            )
            connection.execute(
                tables.issues.insert(),
                {
                    "id": issue_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "workflow_id": workflow_id if draft.stage_id is not None else None,
                    "stage_id": draft.stage_id,
                    "owner_user_id": draft.owner_user_id,
                    "verifier_user_id": draft.verifier_user_id,
                    "sample_id": draft.sample_id,
                    "reported_by_user_id": actor_user_id,
                    "created_by_ai_principal_id": created_by_ai_principal_id,
                    "title": draft.title,
                    "source_finding_id": source_finding_id,
                    "description": draft.description,
                    "issue_type": draft.issue_type,
                    "status": "open",
                    "severity": draft.severity,
                    "root_cause": draft.root_cause,
                    "resolution": draft.resolution,
                    "closure_criteria": draft.closure_criteria,
                    "target_date": draft.target_date,
                    "created_at": occurred_at,
                    "updated_at": occurred_at,
                },
            )
            issue = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, issue_id=issue_id
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"issue:{issue_id}:created",
                    event_type="ISSUE_CREATED",
                    source="issue_service",
                    entity_id=issue_id,
                    payload={"issue_id": str(issue_id), "severity": issue.severity},
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="issue.create",
                    after_snapshot=_issue_snapshot(issue),
                    context=audit_context or {},
                ),
            )
            return issue

    def update(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        issue_id: UUID,
        patch: IssueUpdate,
        connection: Connection | None = None,
    ) -> IssueRecord:
        occurred_at = datetime.now(UTC)
        with (
            nullcontext(connection) if connection is not None else self._engine.begin()
        ) as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise IssueNotFoundError
            before = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, issue_id=issue_id
            )
            if (
                patch.expected_updated_at is not None
                and patch.expected_updated_at != before.updated_at
            ):
                raise TemplateFieldConflictError("问题内容或状态已变化，请刷新工作卡后核对")
            if before.status == "closed" or before.withdrawn_at is not None:
                raise IssueTerminalError
            workflow_id = self._project_workflow(
                connection, tenant_id=tenant_id, project_id=project_id
            )
            changes = dict(patch.changes)
            fields, field_source = project_fields(connection, tenant_id, project_id)
            if "template_fields" in changes:
                if (
                    patch.expected_updated_at is None
                    or patch.expected_updated_at != before.updated_at
                ):
                    raise TemplateFieldConflictError("问题已被修改，请重新读取后核对补充字段")
                changes["template_fields"] = validate_values(
                    fields, changes["template_fields"], before.status
                )
            if "stage_id" in changes:
                stage_id = changes["stage_id"]
                if stage_id is not None and not isinstance(stage_id, UUID):
                    raise IssueScopeError
                self._validate_stage(
                    connection,
                    tenant_id=tenant_id,
                    workflow_id=workflow_id,
                    stage_id=stage_id,
                )
                changes["workflow_id"] = workflow_id if stage_id is not None else None
            if "owner_user_id" in changes:
                owner_id = changes["owner_user_id"]
                if owner_id is not None and not isinstance(owner_id, UUID):
                    raise IssueScopeError
                self._validate_member(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    user_id=owner_id,
                )
            if "verifier_user_id" in changes:
                verifier_id = changes["verifier_user_id"]
                if verifier_id is not None and not isinstance(verifier_id, UUID):
                    raise IssueScopeError
                self._validate_member(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    user_id=verifier_id,
                )
            effective_owner = changes.get("owner_user_id", before.owner_user_id)
            effective_verifier = changes.get("verifier_user_id", before.verifier_user_id)
            effective_severity = changes.get("severity", before.severity)
            _require_four_eyes(
                severity=str(effective_severity),
                owner_user_id=effective_owner if isinstance(effective_owner, UUID) else None,
                verifier_user_id=(
                    effective_verifier if isinstance(effective_verifier, UUID) else None
                ),
            )
            connection.execute(
                tables.issues.update()
                .where(
                    tables.issues.c.tenant_id == tenant_id,
                    tables.issues.c.project_id == project_id,
                    tables.issues.c.id == issue_id,
                )
                .values(**changes, updated_at=occurred_at)
            )
            after = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, issue_id=issue_id
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"issue:{issue_id}:updated:{uuid4()}",
                    event_type="ISSUE_UPDATED",
                    source="issue_service",
                    entity_id=issue_id,
                    payload={
                        "changed_fields": sorted(patch.changes),
                        "status": after.status,
                        "severity": after.severity,
                    },
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="issue.update",
                    context={"template_field_source": field_source}
                    if "template_fields" in changes
                    else {},
                    before_snapshot=_issue_snapshot(before),
                    after_snapshot=_issue_snapshot(after),
                ),
            )
            return after

    def transition(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        issue_id: UUID,
        to_status: str,
        comment: str | None = None,
        closure_evidence_ref: str | None = None,
        expected_updated_at: datetime | None = None,
        material_closures: Sequence[MaterialClosureReference] | None = None,
    ) -> IssueRecord:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise IssueNotFoundError
            before = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, issue_id=issue_id
            )
            if expected_updated_at is not None and expected_updated_at != before.updated_at:
                raise TemplateFieldConflictError("问题内容或状态已变化，请刷新工作卡后核对")
            if before.withdrawn_at is not None:
                raise IssueTerminalError
            if to_status not in ISSUE_TRANSITIONS[before.status]:
                raise IssueInvalidTransitionError
            if to_status == "analysis" and (
                before.owner_user_id is None
                or before.verifier_user_id is None
                or before.target_date is None
                or before.closure_criteria is None
            ):
                raise IssueAssignmentIncompleteError
            if to_status == "verification":
                if before.owner_user_id is None:
                    raise IssueAssignmentIncompleteError
                if actor_user_id != before.owner_user_id:
                    raise IssueSubmitNotOwnerError
            if before.status == "verification" and to_status == "action":
                if before.verifier_user_id is None:
                    raise IssueAssignmentIncompleteError
                if actor_user_id != before.verifier_user_id:
                    raise IssueRejectNotVerifierError
            policy = (
                connection.execute(
                    select(
                        tables.projects.c.issue_verify_low, tables.projects.c.issue_verify_medium
                    ).where(
                        tables.projects.c.tenant_id == tenant_id, tables.projects.c.id == project_id
                    )
                )
                .mappings()
                .one()
            )
            require_verifier = before.severity in {"high", "critical"} or policy.get(
                f"issue_verify_{before.severity}", False
            )
            if to_status == "closed" and require_verifier:
                if before.owner_user_id == before.verifier_user_id:
                    raise IssueFourEyesError
                if actor_user_id != before.verifier_user_id:
                    raise IssueCloseNotVerifierError
                if closure_evidence_ref is None:
                    raise IssueClosureEvidenceRequiredError
            fields, _ = project_fields(connection, tenant_id, project_id)
            validate_values(fields, before.template_fields, to_status)
            values: dict[str, object] = {
                "status": to_status,
                "closed_at": occurred_at if to_status == "closed" else None,
                "updated_at": occurred_at,
            }
            audit_context: dict[str, object] = {}
            if comment is not None:
                audit_context["comment"] = comment
            if to_status == "closed":
                # Import locally: material exceptions create their original Issue.
                from app.domain.material_exceptions import validate_material_issue_closure

                material_context = validate_material_issue_closure(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    issue_id=issue_id,
                    actor_user_id=actor_user_id,
                    expected_sources=(
                        list(material_closures) if material_closures is not None else None
                    ),
                )
                if material_context["sources"]:
                    if expected_updated_at is None:
                        raise TemplateFieldConflictError("请先刷新原问题并核对其当前版本再关闭")
                    audit_context["material_closure"] = material_context
                values["closure_evidence_ref"] = closure_evidence_ref
            if before.status == "closed":
                values["reopen_count"] = before.reopen_count + 1
                values["closure_evidence_ref"] = None
                audit_context["reopened_from_closed_at"] = (
                    before.closed_at.isoformat() if before.closed_at is not None else None
                )
            connection.execute(
                tables.issues.update()
                .where(
                    tables.issues.c.tenant_id == tenant_id,
                    tables.issues.c.project_id == project_id,
                    tables.issues.c.id == issue_id,
                )
                .values(**values)
            )
            after = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, issue_id=issue_id
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"issue:{issue_id}:status:{to_status}:{uuid4()}",
                    event_type="ISSUE_STATUS_CHANGED",
                    source="issue_service",
                    entity_id=issue_id,
                    payload={"from_status": before.status, "to_status": after.status},
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="issue.transition",
                    before_snapshot=_issue_snapshot(before),
                    after_snapshot=_issue_snapshot(after),
                    context=audit_context,
                ),
            )
        # Learning is queued by the committed event/audit; collection failure cannot mask closure.
        return after
